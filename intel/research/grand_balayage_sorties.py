"""Grand balayage, etape 4 : les sorties dynamiques (prise de gain, stop, detention max).

PROTOCOLE FIGE AVANT LE CALCUL (15/09), memes tranches (date de naissance du pool, 60/20/20).
  entree    age A parmi {45, 60, 90, 120} s, prix d execution = lecture la plus proche de A+2 s.
  groupes   tous / telegram / non-telegram / pools >= 200 SOL / pools < 200 SOL.
  sortie    gain >= TP ou perte <= SL, constate sur une lecture, EXECUTE A LA LECTURE SUIVANTE
            (~10 s plus tard, au prix de ce moment -- un stop ne s execute pas a son niveau, §5) ;
            sinon a la duree maximale. TP {5,10,20,30,50,100 %, aucun}, SL {-10,-20,-30,-50 %, aucun},
            duree max {120, 240, 480, 800 s}.
  cout      celui de la table (1,7 % + impact aller et retour).
  decision  meme chaine : RECHERCHE (moyenne >= +1,1 %, sb3 >= +1,1 %, t >= 2, n >= 100) -> TRI (n >= 30,
            moyenne >= +1,1 %, sb1 > 0) -> TEST FINAL une fois pour les 20 meilleurs.
"""
from __future__ import annotations

import itertools
import os
import sys
from bisect import bisect_right

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grand_balayage as gb  # noqa: E402
import grand_balayage_table as gt  # noqa: E402

AGES = (45, 60, 90, 120)
TPS = (0.05, 0.10, 0.20, 0.30, 0.50, 1.00, None)
SLS = (-0.10, -0.20, -0.30, -0.50, None)
DMAX = (120, 240, 480, 800)


def simuler(ages, prix, e, tp, sl, dmax):
    """Rendement brut d une sortie dynamique a partir de la lecture d entree e."""
    pe, t0 = prix[e], ages[e]
    # COUVERTURE DECIDEE AVANT L ISSUE. Le collecteur ne suit un pool que 15 min. Sans cette ligne, un
    # trade dont le chemin s arretait avant la duree max rendait NaN et disparaissait -- sauf s il avait
    # touche sa prise de gain : il ne restait que les gagnants (premier passage du 15/09 : « TP +100 %
    # rapporte +112 % », 20 regles « GO », toutes fausses).
    if ages[-1] - t0 < dmax:
        return np.nan
    for i in range(e + 1, len(ages)):
        if ages[i] - t0 > dmax:
            return prix[i] / pe - 1
        r = prix[i] / pe - 1
        if (tp is not None and r >= tp) or (sl is not None and r <= sl):
            j = min(i + 1, len(ages) - 1)
            return prix[j] / pe - 1
    return np.nan


def main():
    pools, tg, *_ = gt.charger()
    lignes = []
    for pair, pts in pools.items():
        if pts[0][0] > 20 or len(pts) < 6:
            continue
        ages = [x[0] for x in pts]
        prix = np.array([x[2] for x in pts])
        qs = np.array([x[3] for x in pts])
        v, mint = pts[0][5], pts[0][6]
        naissance = pts[0][1] - pts[0][0]
        for A in AGES:
            e = gt.a_age(ages, prix, A + gt.EXEC_S, 6)
            if e is None or qs[e] + v <= 0 or gt.MISE_SOL / (qs[e] + v) > 0.15 or ages[-1] - ages[e] < 100:
                continue
            cout = gt.COUT_FIXE + 2 * gt.MISE_SOL / (qs[e] + v)
            ligne = {"naissance": naissance, "A": A, "tg": tg.get(mint), "gros": int(qs[e] >= 200), "cout": cout}
            for tp, sl, dm in itertools.product(TPS, SLS, DMAX):
                ligne[(tp, sl, dm)] = simuler(ages, prix, e, tp, sl, dm) - cout
            lignes.append(ligne)
    df = gb.tranches(pd.DataFrame(lignes))
    regles = [k for k in df.columns if isinstance(k, tuple)]
    groupes = {"tous": lambda d: np.ones(len(d), bool), "telegram": lambda d: (d.tg == 1).to_numpy(),
               "non-telegram": lambda d: (d.tg == 0).to_numpy(), "pool>=200": lambda d: (d.gros == 1).to_numpy(),
               "pool<200": lambda d: (d.gros == 0).to_numpy()}
    print("%d entrees simulees, %d regles de sortie x %d groupes x %d ages" % (len(df), len(regles), len(groupes), len(AGES)))
    jF = (df[df.tranche == "F"].naissance.max() - df[df.tranche == "F"].naissance.min()) / 86400
    surv = []
    ref = []
    for A in AGES:
        for gnom, gf in groupes.items():
            sub = df[df.A == A]
            mg = gf(sub)
            for rg in regles:
                y = sub[rg].to_numpy(float)
                sR = gb.stats(y[mg & (sub.tranche == "R").to_numpy()])
                if rg == (None, None, 240) and gnom == "tous":
                    ref.append((A, sR))
                if not (sR and sR["n"] >= 100 and sR["moy"] >= gb.OBJ and sR["sb3"] >= gb.OBJ and sR["t"] >= 2):
                    continue
                sT = gb.stats(y[mg & (sub.tranche == "T").to_numpy()])
                if sT and sT["n"] >= 30 and sT["moy"] >= gb.OBJ and sT["sb1"] > 0:
                    sF = gb.stats(y[mg & (sub.tranche == "F").to_numpy()])
                    surv.append((min(sR["moy"], sT["moy"]), A, gnom, rg, sR, sT, sF))
    for A, s in ref:
        print("reference sans regle (tous, sortie 240 s) A=%d : recherche %+.4f n=%d" % (A, s["moy"], s["n"]))
    surv.sort(key=lambda z: -z[0])
    print("\n%d regles survivent recherche + tri. Test final des 20 meilleures :" % len(surv))
    go = 0
    for _, A, gnom, rg, sR, sT, sF in surv[:20]:
        ok = bool(sF) and sF["n"] >= 30 and sF["moy"] >= gb.OBJ and sF["sb1"] > 0
        go += ok
        print("  A=%3d %-12s TP %-5s SL %-5s max %3ds · R %+.3f(%d) T %+.3f(%d) F %s %s" % (
            A, gnom, rg[0], rg[1], rg[2], sR["moy"], sR["n"], sT["moy"], sT["n"],
            ("%+.3f sb %+.3f n=%d (%.0f/j)" % (sF["moy"], sF["sb1"], sF["n"], sF["n"] / max(jF, 1e-9))) if sF else "trop peu",
            "GO" if ok else ""))
    print("-> %d GO" % go)


if __name__ == "__main__":
    main()
