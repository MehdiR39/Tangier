"""Verification du SEUL candidat qui a passe tri et test : LightGBM, detention 8 h, top 10 % (15/09).

Resultat a verifier (grand_balayage_long.py) : TRI +5,6 % (n=276), TEST +14,0 % (sb +11,1 %, n=74).
Une correlation prediction/rendement de +0,55 sur des memecoins est trop belle : on cherche le biais.

VERIFICATIONS FIGEES AVANT DE LES LANCER
  V1 survie     si le suivi s arrete avant la sortie, on sort au DERNIER prix connu (au lieu d ecarter).
  V2 doublons   un seul trade par pool : la premiere decision ou le score passe le seuil.
  V3 hasard     50 modeles entraines sur des rendements melanges (au sein de chaque age) : quelle part
                fait aussi bien sur le TEST ?
  V4 robustesse 9 reglages du modele (feuilles 7/15/31 x arbres 150/300/600) : le TEST reste-t-il positif ?
  V5 regularite rendement du TEST jour par jour et moitie par moitie.
  VERDICT       le candidat n est retenu que si V1+V2 gardent TRI et TEST >= +1,1 %, V3 < 5 %,
                V4 positif dans au moins 7 reglages sur 9.
"""
from __future__ import annotations

import os
import sqlite3
import sys

import numpy as np
import pandas as pd
import lightgbm as lgb

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import grand_balayage as gb  # noqa: E402
import grand_balayage_long as gl  # noqa: E402

H = 480
Q_TOP = 0.90


def sorties_prudentes(df):
    """Rendement a 8 h en sortant au dernier releve si le suivi s arrete avant."""
    c = sqlite3.connect("file:%s?mode=ro" % os.path.join(gl.D, "archive_solana.sqlite"), uri=True, timeout=120)
    s = pd.read_sql("SELECT pair_id, age_min, price_usd AS p FROM solana_suivi_long WHERE price_usd > 0"
                    " ORDER BY pair_id, age_min", c)
    chemins = {k: (g.age_min.to_numpy(float), g.p.to_numpy(float)) for k, g in s.groupby("pair_id", sort=False)}
    out = []
    for pair, A, cout in df[["pair", "A", "cout"]].itertuples(index=False):
        age, p = chemins[pair]
        e = np.searchsorted(age, A, side="right")
        if e >= len(age):
            out.append(np.nan)
            continue
        cible = age[e] + H
        j = np.searchsorted(age, cible)
        cand = [x for x in (j - 1, j) if 0 <= x < len(age) and x > e and abs(age[x] - cible) <= 15]
        if cand:
            x = min(cand, key=lambda x: abs(age[x] - cible))
        elif age[-1] < cible and len(age) - 1 > e:
            x = len(age) - 1                                  # suivi arrete : dernier prix connu
        else:
            out.append(np.nan)
            continue
        out.append(p[x] / p[e] - 1 - cout)
    return np.array(out)


def entrainer(X, y, R, leaves=15, arbres=300, seed=0):
    ok = ~np.isnan(y)
    m = lgb.LGBMRegressor(n_estimators=arbres, learning_rate=0.03, num_leaves=leaves, min_child_samples=80,
                          subsample=0.8, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0,
                          random_state=seed, verbose=-1)
    m.fit(X[R & ok], np.minimum(y[R & ok], gb.PLAFOND))
    return m.predict(X)


def evaluer(df, pred, y, T, F, dedup):
    ok = ~np.isnan(y)
    seuil = np.quantile(pred[T & ok], Q_TOP)
    choix = ok & (pred >= seuil)
    if dedup:
        d = df.assign(choix=choix, ordre=df.naissance + df.A * 60).sort_values("ordre")
        premier = d[d.choix].groupby("pair").head(1).index
        choix = np.zeros(len(df), bool)
        choix[premier] = True
    return gb.stats(np.minimum(y[T & choix], gb.PLAFOND)), gb.stats(np.minimum(y[F & choix], gb.PLAFOND)), choix


def main():
    gb.CONTINUES, gb.CATEGORIES, gb.HORIZONS = gl.CONT, gl.CAT, gl.HORIZONS
    df = gb.tranches(pd.read_pickle(os.path.join(gl.D, "balayage", "table_long.pkl"))).reset_index(drop=True)
    X = df[gl.CONT + gl.CAT + ["A"]].astype(float)
    R, T, F = [(df.tranche == t).to_numpy() for t in "RTF"]
    y_base = df["net_%d" % H].to_numpy(float)
    y_prud = sorties_prudentes(df)
    print("lignes a 8 h : base %d · prudentes %d" % ((~np.isnan(y_base)).sum(), (~np.isnan(y_prud)).sum()))

    fmt = lambda s: ("moy %+.3f sb %+.3f n=%d" % (s["moy"], s["sb1"], s["n"])) if s else "trop peu"
    resultats = {}
    for nom, y in (("base", y_base), ("V1 survie", y_prud)):
        pred = entrainer(X, y, R)
        for dedup in (False, True):
            sT, sF, choix = evaluer(df, pred, y, T, F, dedup)
            cle = nom + (" + V2 doublons" if dedup else "")
            resultats[cle] = (sT, sF)
            print("%-26s TRI %-32s TEST %s" % (cle, fmt(sT), fmt(sF)))
    y = y_prud
    pred = entrainer(X, y, R)
    sT0, sF0, choix0 = evaluer(df, pred, y, T, F, True)

    print("\nV3 hasard : 50 modeles sur rendements melanges (V1+V2)")
    rng = np.random.default_rng(7)
    mieux = 0
    for i in range(50):
        ym = pd.Series(y).groupby(df.A).transform(lambda s: pd.Series(rng.permutation(s.to_numpy()), index=s.index)).to_numpy()
        p_m = entrainer(X, ym, R, seed=i)
        _, sF_m, _ = evaluer(df, p_m, y, T, F, True)            # modele appris sur du bruit, juge sur le VRAI rendement
        if sF_m and sF0 and sF_m["moy"] >= sF0["moy"]:
            mieux += 1
    print("   %d / 50 modeles appris sur du bruit font aussi bien sur le TEST (%.0f %%)" % (mieux, 2 * mieux))

    print("\nV4 robustesse : 9 reglages du modele (V1+V2)")
    positifs = 0
    for leaves in (7, 15, 31):
        for arbres in (150, 300, 600):
            p_r = entrainer(X, y, R, leaves, arbres)
            sT, sF, _ = evaluer(df, p_r, y, T, F, True)
            positifs += bool(sF and sF["moy"] > 0)
            print("   feuilles %2d arbres %3d · TRI %-30s TEST %s" % (leaves, arbres, fmt(sT), fmt(sF)))
    print("   TEST positif dans %d reglages sur 9" % positifs)

    print("\nV5 regularite du TEST (V1+V2)")
    t = df[F & choix0].assign(r=np.minimum(y[F & choix0], gb.PLAFOND),
                              jour=lambda d: pd.to_datetime(d.naissance + d.A * 60 + 7200, unit="s").dt.strftime("%d/%m %Hh"))
    t = t.sort_values("naissance")
    moit = len(t) // 2
    print("   1re moitie : moy %+.3f n=%d · 2de moitie : moy %+.3f n=%d" % (t.r.iloc[:moit].mean(), moit, t.r.iloc[moit:].mean(), len(t) - moit))
    print("   par tranche de 6 h : " + " · ".join("%s %+.3f (n=%d)" % (k, g.r.mean(), len(g)) for k, g in
                                             t.assign(b=pd.to_datetime(t.naissance + 7200, unit="s").dt.floor("6h").dt.strftime("%d/%m %Hh")).groupby("b")))
    top = t.r.sort_values(ascending=False)
    print("   les 5 meilleurs tickets : %s · moyenne sans les 3 meilleurs : %+.3f" % (", ".join("%+.2f" % x for x in top.head(5)), top.iloc[3:].mean()))

    sT, sF = resultats["V1 survie + V2 doublons"]
    ok = (sT and sF and sT["moy"] >= gb.OBJ and sF["moy"] >= gb.OBJ and mieux < 3 and positifs >= 7)
    print("\nVERDICT : %s" % ("RETENU pour un test EN PAPIER" if ok else "NON RETENU"))


if __name__ == "__main__":
    main()
