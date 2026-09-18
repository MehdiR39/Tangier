"""Grand balayage, etape 2 : chercher partout, ne croire que ce qui survit a trois tranches.

PROTOCOLE FIGE AVANT LE CALCUL (15/09)
  donnees     table.pkl (grand_balayage_table.py) : prix corriges, couts reels, 3 157 pools.
  tranches    par date de naissance du pool : RECHERCHE 60 %, TRI 20 %, TEST FINAL 20 %.
              Le test final n est lu qu une fois, a la fin, pour les 20 meilleurs candidats.
  rendement   net apres cout ; plafonne a +300 % pour les moyennes (un x315 ne doit rien decider).
  familles    F1 : une variable (quintile ou valeur) x age d entree x duree
              F2 : deux variables (quintiles extremes ou valeurs) x age x duree
  candidat    RECHERCHE : n >= 100 (F1) / 60 (F2), moyenne >= +1,1 %, sans ses 3 meilleurs >= +1,1 %,
              t >= 2
  survivant   TRI : n >= 30, moyenne >= +1,1 %, sans son meilleur > 0
  hasard      le meme pipeline sur des rendements MELANGES (ordre aleatoire au sein de chaque age) :
              combien de « survivants » le hasard seul produit-il ?
  final       les 20 survivants au meilleur min(recherche, tri) sur le TEST ; GO seulement si TEST :
              moyenne >= +1,1 %, sans son meilleur > 0, n >= 30.
"""
from __future__ import annotations

import itertools
import os
import sys

import numpy as np
import pandas as pd

ICI = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(os.path.abspath(os.path.join(ICI, "..", "..")), "data", "recherche", "balayage")
OBJ = 0.011
PLAFOND = 3.0
HORIZONS = (30, 60, 120, 240, 480, 900)
CONTINUES = ["n_lect", "ret_naiss", "dd_max", "depuis_min", "t_depuis_max", "vol", "q", "q_croiss",
             "ret_10", "ret_30", "ret_60", "ret_120", "q_croiss_30", "q_croiss_60", "n_descr",
             "sac1", "n_sacs5", "createur_prec", "lancements_10min", "marche_ret_30min",
             "marche_vides_30min", "heure", "cout"]
CATEGORIES = ["V", "telegram", "twitter", "site", "det_a_vide", "fin_a_vide"]


def tranches(df):
    naiss = np.sort(df.naissance.unique())
    c1, c2 = naiss[int(0.6 * len(naiss))], naiss[int(0.8 * len(naiss))]
    df["tranche"] = np.where(df.naissance < c1, "R", np.where(df.naissance < c2, "T", "F"))
    return df


def stats(v):
    v = np.asarray(v, float)
    v = v[~np.isnan(v)]
    if len(v) < 2:
        return None
    w = np.minimum(v, PLAFOND)
    s = np.sort(w)[::-1]
    m = w.mean()
    return {"n": len(w), "moy": m, "sb1": s[1:].mean(), "sb3": s[3:].mean() if len(s) > 3 else np.nan,
            "t": m / (w.std(ddof=1) / np.sqrt(len(w))) if w.std(ddof=1) > 0 else 0.0}


def masques(sub, edges):
    """Tous les sous-ensembles d une variable : quintiles pour les continues, valeurs pour les categories."""
    out = []
    for f in CONTINUES:
        if f not in edges:
            continue
        x = sub[f].to_numpy(float)
        e = edges[f]
        for q in range(5):
            m = (x >= e[q]) & (x <= e[q + 1]) if q == 4 else (x >= e[q]) & (x < e[q + 1])
            out.append(("%s:Q%d" % (f, q + 1), m))
    for f in CATEGORIES:
        x = sub[f]
        for val in (0, 1):
            out.append(("%s=%d" % (f, val), (x == val).to_numpy()))
    return out


def balayer(df, col_rend, extremes_seulement=True):
    candidats = []
    for A, sa in df.groupby("A"):
        R = sa[sa.tranche == "R"]
        edges = {}
        for f in CONTINUES:
            x = R[f].dropna()
            if x.nunique() >= 5:
                edges[f] = np.unique(np.quantile(x, [0, .2, .4, .6, .8, 1]))
                if len(edges[f]) < 6:
                    del edges[f]
        mR = masques(R, edges)
        for H in HORIZONS:
            y = R["%s_%d" % (col_rend, H)].to_numpy(float)
            base = [(nom, m) for nom, m in mR]
            # F1
            for nom, m in base:
                s = stats(y[m])
                if s and s["n"] >= 100 and s["moy"] >= OBJ and s["sb3"] >= OBJ and s["t"] >= 2:
                    candidats.append((A, H, (nom,), s, edges))
            # F2 : quintiles extremes et categories seulement
            ext = [(nom, m) for nom, m in base if (not extremes_seulement) or nom.endswith(("Q1", "Q5")) or "=" in nom]
            for (n1, m1), (n2, m2) in itertools.combinations(ext, 2):
                if n1.split(":")[0].split("=")[0] == n2.split(":")[0].split("=")[0]:
                    continue
                m = m1 & m2
                if m.sum() < 60:
                    continue
                s = stats(y[m])
                if s and s["moy"] >= OBJ and s["sb3"] >= OBJ and s["t"] >= 2:
                    candidats.append((A, H, (n1, n2), s, edges))
    return candidats


def appliquer(sub, noms, edges):
    m = np.ones(len(sub), bool)
    for nom in noms:
        if "=" in nom:
            f, val = nom.split("=")
            m &= (sub[f] == int(val)).to_numpy()
        else:
            f, q = nom.split(":Q")
            q = int(q) - 1
            e = edges[f]
            x = sub[f].to_numpy(float)
            m &= ((x >= e[q]) & (x <= e[q + 1])) if q == 4 else ((x >= e[q]) & (x < e[q + 1]))
    return m


def trier(df, candidats, col_rend):
    surv = []
    for A, H, noms, sR, edges in candidats:
        T = df[(df.A == A) & (df.tranche == "T")]
        s = stats(T["%s_%d" % (col_rend, H)].to_numpy(float)[appliquer(T, noms, edges)])
        if s and s["n"] >= 30 and s["moy"] >= OBJ and s["sb1"] > 0:
            surv.append((A, H, noms, sR, s, edges))
    return surv


def main():
    df = tranches(pd.read_pickle(os.path.join(D, "table.pkl")))
    jours = {t: (g.naissance.max() - g.naissance.min()) / 86400 for t, g in df.groupby("tranche")}
    print("tranches : " + " · ".join("%s %d lignes %.1f j" % (t, (df.tranche == t).sum(), jours[t]) for t in "RTF"))

    # --- le hasard d abord : rendements melanges au sein de chaque age ---
    rng = np.random.default_rng(15)
    melange = df.copy()
    for H in HORIZONS:
        col = "net_%d" % H
        melange[col] = melange.groupby("A")[col].transform(lambda s: rng.permutation(s.to_numpy()))
    cand_h = balayer(melange, "net")
    surv_h = trier(melange, cand_h, "net")
    print("HASARD (rendements melanges) : %d candidats en recherche, %d survivent au tri" % (len(cand_h), len(surv_h)))

    cand = balayer(df, "net")
    surv = trier(df, cand, "net")
    print("VRAI : %d candidats en recherche, %d survivent au tri" % (len(cand), len(surv)))
    if not surv:
        print("aucun survivant : rien a tester")
        return
    surv.sort(key=lambda z: -min(z[3]["moy"], z[4]["moy"]))
    print("\nTEST FINAL des %d meilleurs survivants (lu une seule fois) :" % min(20, len(surv)))
    print("%-4s %-4s %-58s %-22s %-22s %-30s %s" % ("A", "H", "regle", "recherche", "tri", "TEST FINAL", "verdict"))
    go = 0
    for A, H, noms, sR, sT, edges in surv[:20]:
        F = df[(df.A == A) & (df.tranche == "F")]
        m = appliquer(F, noms, edges)
        sF = stats(F["net_%d" % H].to_numpy(float)[m])
        ok = bool(sF) and sF["n"] >= 30 and sF["moy"] >= OBJ and sF["sb1"] > 0
        go += ok
        par_jour = (sF["n"] / max(jours["F"], 1e-9)) if sF else 0
        print("%-4d %-4d %-58s %+.3f n=%-4d       %+.3f n=%-4d       %s  %s" % (
            A, H, " & ".join(noms)[:58], sR["moy"], sR["n"], sT["moy"], sT["n"],
            ("%+.3f sb %+.3f n=%-3d %3.0f/j" % (sF["moy"], sF["sb1"], sF["n"], par_jour)) if sF else "trop peu",
            "GO" if ok else "non"))
    print("\n%d regle(s) passent le test final. Le hasard seul faisait survivre %d regles au tri." % (go, len(surv_h)))
    pd.to_pickle({"surv": surv, "cand": len(cand), "hasard": len(surv_h)}, os.path.join(D, "balayage_resultat.pkl"))


if __name__ == "__main__":
    main()
