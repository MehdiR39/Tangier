"""REENTRAINER `risque` JUSQU A UNE HEURE DONNEE, ET JUGER APRES : le modele en service vieillit-il ?

LA QUESTION, DE MIDO (18/09 22h) : « si tu reentraines risque seul jusqu a aujourd hui 18h, ameliore-t-il
les donnees apres 18h ? »

C est une bonne question et elle a un test propre. Le modele en service (`modele_vidage.json`) a ete
entraine sur des jetons d avant le 17/09 ; depuis, ~2 000 tickets sont passes. Si l information
qu il capte derive avec le marche, un modele frais devrait faire mieux sur ce qui suit ; si elle
n existe pas, frais ou vieux feront pareil -- et le hasard aussi.

LE MEME MODELE, PAS UN AUTRE. Memes 19 variables (lues dans le JSON du modele en service), meme
cible (`brut_240 <= -0,50`, grand_balayage_ml.py), memes hyperparametres. Seule la date de fin
d entrainement change. Deux coupes :
    entraine avant 18h00 Paris, juge sur 18h00 -> maintenant   (la question posee : 126 tickets)
    entraine avant 12h00 Paris, juge sur 12h00 -> 18h00          (plus de poids)

COMPARAISON A EFFECTIF EGAL. Sur la fenetre de jugement, la regle en service garde k tickets
(risque <= 0,2694). Le modele frais garde ses k scores les plus bas. Meme k, memes jetons possibles :
seul le classement change. Puis a 50 % et 30 % pour les deux. Cout 6,55, multiplicatif. Et un
tirage AU HASARD de k tickets, 4 000 fois, pour savoir ou chacun des deux se situe.

On affiche aussi l AUC de chaque modele sur la fenetre de jugement pour la cible vidage : c est la
question « l information existe-t-elle ? », independante du cout.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

COMBO = os.environ.get("COMBO_DB", "/app/db/papier_combo.sqlite")
MODELE = os.environ.get("MODELE_VIDAGE", "/app/data/recherche/balayage/modele_vidage.json")
COUT = float(os.environ.get("COUT_MESURE", "0.0655"))
SEUIL_PROD = 0.2694
PARAMS = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=80,
              subsample=0.8, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0, verbose=-1)
rng = np.random.default_rng(3)


def paris(h: int) -> float:
    return dt.datetime(2026, 9, 18, h - 2, 0, tzinfo=dt.timezone.utc).timestamp()


def net(r):
    return (1.0 + r) * (1.0 - COUT) - 1.0


def charger(variables: list[str]) -> pd.DataFrame:
    c = sqlite3.connect("file:%s?mode=ro" % COMBO, uri=True)
    rows = []
    for t, risque, var, b in c.execute(
            "SELECT d.t_dec, d.risque, d.variables, i.brut_240 FROM decision d JOIN issue i ON i.pair = d.pair"
            " WHERE d.eligible = 1 AND i.brut_240 IS NOT NULL AND d.risque IS NOT NULL"):
        try:
            v = json.loads(var or "{}")
        except Exception:  # noqa: BLE001
            v = {}
        r = {"t": t, "risque": risque, "brut": b}
        for k in variables:
            x = v.get(k)
            r[k] = float(x) if x is not None else np.nan
        rows.append(r)
    return pd.DataFrame(rows).sort_values("t").reset_index(drop=True)


def stats(y: np.ndarray) -> str:
    if len(y) < 5:
        return "n=%d trop peu" % len(y)
    s = np.sort(y)
    return "n=%3d  net %+6.2f %%  sans3 %+6.2f %%  gagnants %3.0f %%  cata %3.0f %%" % (
        len(y), 100 * y.mean(), 100 * s[:-3].mean(), 100 * (y > 0).mean(), 100 * (y < -0.5).mean())


def coupe(df: pd.DataFrame, variables: list[str], t_fin: float, t_max: float, titre: str) -> None:
    A = df[df["t"] < t_fin]
    J = df[(df["t"] >= t_fin) & (df["t"] < t_max)]
    if len(J) < 20:
        print("%s : %d tickets de jugement, trop peu" % (titre, len(J)))
        return
    y_tr = (A["brut"] <= -0.5).astype(int).to_numpy()
    clf = lgb.LGBMClassifier(**PARAMS).fit(A[variables].astype(float), y_tr)
    p_frais = clf.predict_proba(J[variables].astype(float))[:, 1]
    p_prod = J["risque"].to_numpy()
    y_j = (J["brut"] <= -0.5).astype(int).to_numpy()
    nets = net(J["brut"].to_numpy())

    print("=" * 96)
    print("%s" % titre)
    print("   entraine sur %d tickets · juge sur %d tickets · vidages dans le jugement : %.1f %%"
          % (len(A), len(J), 100 * y_j.mean()))
    try:
        print("   AUC vidage sur le jugement : en service %.3f · frais %.3f"
              % (roc_auc_score(y_j, p_prod), roc_auc_score(y_j, p_frais)))
    except Exception:  # noqa: BLE001
        pass
    print("   temoin (tout prendre)            %s" % stats(nets))

    k_prod = int((p_prod <= SEUIL_PROD).sum())
    for nom, k in (("effectif de la regle en service", k_prod),
                   ("50 % gardes", len(J) // 2), ("30 % gardes", int(len(J) * 0.3))):
        if k < 5:
            continue
        m_prod = np.argsort(p_prod, kind="stable")[:k]
        m_frais = np.argsort(p_frais, kind="stable")[:k]
        print("   -- %s (k=%d) --" % (nom, k))
        print("   en service (risque, vieux)       %s" % stats(nets[m_prod]))
        print("   REENTRAINE (frais)               %s" % stats(nets[m_frais]))
        tir = np.array([nets[rng.choice(len(J), k, replace=False)].mean() for _ in range(4000)])
        print("   hasard, k tickets : moyenne %+.2f %% · le frais bat le hasard dans %.0f %% des tirages,"
              " le vieux dans %.0f %%" % (100 * tir.mean(), 100 * (tir < nets[m_frais].mean()).mean(),
                                          100 * (tir < nets[m_prod].mean()).mean()))
    print()


def main() -> None:
    variables = json.load(open(MODELE, encoding="utf-8"))["feature_names"]
    df = charger(variables)
    print("%d tickets executables avec un risque et un resultat · %d variables · cout %.2f pt"
          % (len(df), len(variables), 100 * COUT))
    print()
    coupe(df, variables, paris(18), 9e18, "COUPE 18h00 : entraine AVANT 18h, juge APRES 18h (la question posee)")
    coupe(df, variables, paris(12), paris(18), "COUPE 12h00 : entraine AVANT midi, juge midi -> 18h (plus de poids)")


if __name__ == "__main__":
    main()
