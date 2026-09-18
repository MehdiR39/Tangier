"""Grand balayage, etape 3 : l apprentissage automatique combine toutes les variables a la fois.

PROTOCOLE FIGE AVANT LE CALCUL (15/09), memes tranches que grand_balayage.py.
  modeles   M1 LightGBM regression du rendement net plafonne, un modele par duree H.
            M2 LightGBM classification du VIDAGE (brut_240 <= -0,5), tous ages confondus.
  apprentissage  sur RECHERCHE seulement ; parametres fixes, prudents (peu de feuilles, regularisation).
  seuil     sur TRI : le seuil ABSOLU de score qui donne la meilleure moyenne avec n >= 50, parmi les
            quantiles 50/70/80/90/95 % du score de TRI. Pas de recalcul sur la tranche finale.
  final     GO si TEST FINAL : moyenne >= +1,1 %, sans son meilleur > 0, n >= 30.
  controle  AUC du classifieur de vidage sur TRI et TEST : l information existe-t-elle hors echantillon ?
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grand_balayage as gb  # noqa: E402

import lightgbm as lgb  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

VARS = gb.CONTINUES + gb.CATEGORIES + ["A"]
PARAMS = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=80,
              subsample=0.8, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0, verbose=-1)


def stats_ligne(nom, v):
    s = gb.stats(v)
    if not s:
        return "%-10s trop peu" % nom
    return "%-10s n=%4d moy %+.4f sb %+.4f" % (nom, s["n"], s["moy"], s["sb1"])


def main():
    df = gb.tranches(pd.read_pickle(os.path.join(gb.D, "table.pkl")))
    X = df[VARS].astype(float)
    R, T, F = (df.tranche == "R").to_numpy(), (df.tranche == "T").to_numpy(), (df.tranche == "F").to_numpy()

    # --- M2 : le vidage est-il predictible hors echantillon ? ---
    y_vide = (df.brut_240 <= -0.5).astype(float)
    ok = df.brut_240.notna().to_numpy()
    clf = lgb.LGBMClassifier(**PARAMS).fit(X[R & ok], y_vide[R & ok])
    p_vide = clf.predict_proba(X)[:, 1]
    for nom, m in (("RECHERCHE", R), ("TRI", T), ("TEST", F)):
        mm = m & ok
        print("M2 vidage : AUC %s = %.3f (n=%d, vides %.1f %%)" % (nom, roc_auc_score(y_vide[mm], p_vide[mm]), mm.sum(), 100 * y_vide[mm].mean()))
    # strategie : n acheter que les plus faibles risques de vidage, a chaque duree
    print("\nM2 strategie : n acheter que sous un seuil de risque choisi sur TRI")
    for H in gb.HORIZONS:
        y = df["net_%d" % H].to_numpy(float)
        meilleur = None
        for q in (0.05, 0.1, 0.2, 0.3, 0.5):
            seuil = np.nanquantile(p_vide[T], q)
            s = gb.stats(y[T & (p_vide <= seuil)])
            if s and s["n"] >= 50 and (meilleur is None or s["moy"] > meilleur[1]["moy"]):
                meilleur = (seuil, s, q)
        if not meilleur:
            continue
        seuil, sT, q = meilleur
        sF = gb.stats(y[F & (p_vide <= seuil)])
        ok_go = bool(sF) and sF["n"] >= 30 and sF["moy"] >= gb.OBJ and sF["sb1"] > 0
        print("  H=%4d s · risque <= p%02d du TRI · TRI %s · TEST %s %s" % (
            H, 100 * q, stats_ligne("", y[T & (p_vide <= seuil)]), stats_ligne("", y[F & (p_vide <= seuil)]), "GO" if ok_go else "non"))

    # --- M1 : regression du rendement, un modele par duree ---
    print("\nM1 strategie : n acheter que les meilleurs rendements predits (seuil choisi sur TRI)")
    for H in gb.HORIZONS:
        y = np.minimum(df["net_%d" % H].to_numpy(float), gb.PLAFOND)
        okH = ~np.isnan(y)
        reg = lgb.LGBMRegressor(**PARAMS).fit(X[R & okH], y[R & okH])
        pred = reg.predict(X)
        meilleur = None
        for q in (0.5, 0.7, 0.8, 0.9, 0.95):
            seuil = np.nanquantile(pred[T & okH], q)
            s = gb.stats(y[T & okH & (pred >= seuil)])
            if s and s["n"] >= 50 and (meilleur is None or s["moy"] > meilleur[1]["moy"]):
                meilleur = (seuil, s, q)
        if not meilleur:
            continue
        seuil, sT, q = meilleur
        mF = F & okH & (pred >= seuil)
        sF = gb.stats(y[mF])
        ok_go = bool(sF) and sF["n"] >= 30 and sF["moy"] >= gb.OBJ and sF["sb1"] > 0
        corr_T = np.corrcoef(pred[T & okH], y[T & okH])[0, 1]
        corr_F = np.corrcoef(pred[F & okH], y[F & okH])[0, 1]
        print("  H=%4d s · top %2d %% du TRI · correlation prediction/rendement TRI %+.3f TEST %+.3f · TRI %s · TEST %s %s" % (
            H, round(100 * (1 - q)), corr_T, corr_F, stats_ligne("", y[T & okH & (pred >= seuil)]), stats_ligne("", y[mF]), "GO" if ok_go else "non"))


if __name__ == "__main__":
    main()
