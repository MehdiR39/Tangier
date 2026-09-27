"""Combiner les trois effets vrais : regime + risque de vidage + duree (15/09, demande de l operateur).

Chaque effet seul reduit la perte sans la rendre positive :
  - coupe-circuit de regime (moyenne des 50 derniers resultats connus > 0) : ecart +3 a +6 points sur les
    trois tranches, niveau sur donnees jamais vues -0,6 % / -0,1 % a cout reduit (series.py) ;
  - le vidage se predit (LightGBM, AUC 0,79 / 0,82 hors echantillon), mais les jetons surs bougent peu ;
  - une detention courte expose moins aux vidages (3,5 % a 60 s contre 13,6 % a 240 s).
Le ticket median gagne ; les vidages tirent la moyenne. S ils retirent des vidages DIFFERENTS, la moyenne
peut remonter vers la mediane.

GRILLE FIGEE AVANT LE CALCUL (81 combinaisons, rien d autre)
  age d entree A {45, 60, 90} s · duree H {60, 120, 240} s
  regime   N {30, 50, 100} derniers resultats connus (reference : sortie 240 s des decisions a 60 s,
           TOUS les jetons), seuil fixe : moyenne > 0
  risque   classifieur de vidage appris sur RECHERCHE seulement ; on garde tout / les 80 % / les 60 % les
           moins risques (seuils = quantiles des scores de RECHERCHE)
  cout     reduit : 1,25 % + impact / 2 (depot recupere, priorite baissee)
SELECTION  la combinaison au meilleur min(RECHERCHE, TRI), n_TRI >= 50.
TEST       lu une fois. GO si moyenne >= +1,1 %, sans son meilleur > 0, n >= 30.
HASARD     la meme selection avec un indicateur de regime calcule sur des resultats melanges dans le temps
           (50 tirages) : quelle part obtient un TEST aussi bon ?
"""
from __future__ import annotations

import itertools
import os
import sys
from bisect import bisect_right

import numpy as np
import pandas as pd
import lightgbm as lgb

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import grand_balayage as gb  # noqa: E402

AGES = (45, 60, 90)
DUREES = (60, 120, 240)
NS = (30, 50, 100)
RISQUES = (1.0, 0.8, 0.6)
VARS = [v for v in gb.CONTINUES if not v.startswith("marche_")] + gb.CATEGORIES + ["A"]


def cout_reduit(d):
    return 0.0125 + (d.cout - gb.CONTINUES and 0) * 0 + (d.cout - 0.017) / 2


def indicateur(d_ref, t_dec, N, rng=None):
    """Moyenne des N derniers resultats connus a chaque instant de decision."""
    fin = d_ref.t_fin.to_numpy()
    y = d_ref.r.to_numpy()
    if rng is not None:
        y = rng.permutation(y)                                  # le temps ne dit plus rien
    o = np.argsort(fin)
    fin, y = fin[o], y[o]
    cum = np.concatenate([[0.0], np.cumsum(y)])
    k = np.searchsorted(fin, t_dec, side="right")
    out = np.full(len(t_dec), np.nan)
    ok = k >= N
    out[ok] = (cum[k[ok]] - cum[k[ok] - N]) / N
    return out


def evaluer(df, risque, regimes):
    res = []
    for A, H, N, q in itertools.product(AGES, DUREES, NS, RISQUES):
        sub = df[df.A == A]
        y = sub["netr_%d" % H].to_numpy(float)
        reg = regimes[(A, N)]
        seuil_risque = RISQUE_SEUILS[q]
        garde = (~np.isnan(y)) & (~np.isnan(reg)) & (reg > 0) & (risque[sub.index] <= seuil_risque)
        st = {t: gb.stats(np.minimum(y[garde & (sub.tranche == t).to_numpy()], gb.PLAFOND)) for t in "RTF"}
        res.append(((A, H, N, q), st, garde.sum()))
    return res


RISQUE_SEUILS = {}


def main():
    df = gb.tranches(pd.read_pickle(os.path.join(gb.D, "table.pkl"))).reset_index(drop=True)
    for H in DUREES:
        df["netr_%d" % H] = df["brut_%d" % H] - (0.0125 + (df.cout - 0.017) / 2) - 0.017 + 0.017 - 0.0 if False else df["brut_%d" % H] - (0.0125 + (df.cout - 0.017) / 2)
    # --- risque de vidage : appris sur RECHERCHE seulement ---
    X = df[VARS].astype(float)
    y_vide = (df.brut_240 <= -0.5).astype(float)
    ok = df.brut_240.notna().to_numpy()
    R = (df.tranche == "R").to_numpy()
    clf = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=80,
                             subsample=0.8, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0,
                             verbose=-1).fit(X[R & ok], y_vide[R & ok])
    risque = clf.predict_proba(X)[:, 1]
    for q in RISQUES:
        RISQUE_SEUILS[q] = np.inf if q == 1.0 else np.quantile(risque[R & ok], q)
    # --- reference du regime : tous les jetons, decision a 60 s, sortie 240 s, cout reduit ---
    ref = df[(df.A == 60)].dropna(subset=["netr_240"]).copy()
    ref["t_fin"] = ref.naissance + 60 + 2 + 240
    ref["r"] = np.minimum(ref.netr_240, gb.PLAFOND)

    def regimes_pour(rng=None):
        out = {}
        for A in AGES:
            sub = df[df.A == A]
            for N in NS:
                full = np.full(len(df), np.nan)
                full[sub.index] = indicateur(ref, (sub.naissance + A).to_numpy(), N, rng)
                out[(A, N)] = full[sub.index]
        return out

    res = evaluer(df, risque, regimes_pour())
    valides = [(k, st, n) for k, st, n in res if st["R"] and st["T"] and st["T"]["n"] >= 50]
    valides.sort(key=lambda z: -min(z[1]["R"]["moy"], z[1]["T"]["moy"]))
    print("81 combinaisons · classees par min(RECHERCHE, TRI) · les 10 premieres, avec leur TEST FINAL :")
    print("%-4s %-4s %-4s %-6s %-26s %-26s %-34s" % ("A", "H", "N", "risque", "RECHERCHE", "TRI", "TEST FINAL"))
    f = lambda s: ("%+.4f n=%-4d sb %+.3f" % (s["moy"], s["n"], s["sb1"])) if s else "-"
    for (A, H, N, q), st, n in valides[:10]:
        print("%-4d %-4d %-4d %-6s %-26s %-26s %-34s" % (A, H, N, "tout" if q == 1 else "%d %%" % (100 * q), f(st["R"]), f(st["T"]), f(st["F"])))
    (A, H, N, q), st, _ = valides[0]
    sF = st["F"]
    go = bool(sF) and sF["n"] >= 30 and sF["moy"] >= gb.OBJ and sF["sb1"] > 0
    jF = (df[df.tranche == "F"].naissance.max() - df[df.tranche == "F"].naissance.min()) / 86400
    print("\nCOMBINAISON RETENUE : entree %d s, sortie %d s, regime N=%d, risque %s" % (A, H, N, "tout" if q == 1 else "%d %%" % (100 * q)))
    print("  TEST FINAL : %s · %.0f trades/jour · a 30 EUR : %+.0f EUR/jour · VERDICT %s" % (
        f(sF), sF["n"] / max(jF, 1e-9) if sF else 0, (sF["n"] / max(jF, 1e-9)) * sF["moy"] * 30 if sF else 0, "GO" if go else "NON"))
    # decomposition : ce que chaque effet apporte a cette combinaison
    sub = df[df.A == A]
    y = np.minimum(sub["netr_%d" % H].to_numpy(float), gb.PLAFOND)
    reg = regimes_pour()[(A, N)]
    for lib, m in (("rien", np.ones(len(sub), bool)), ("regime seul", reg > 0),
                   ("risque seul", risque[sub.index] <= RISQUE_SEUILS[q]), ("les deux", (reg > 0) & (risque[sub.index] <= RISQUE_SEUILS[q]))):
        m = m & ~np.isnan(y)
        print("  %-12s " % lib + " · ".join("%s %+.4f (n=%d, vides %.0f %%)" % (t, y[m & (sub.tranche == t).to_numpy()].mean(), (m & (sub.tranche == t).to_numpy()).sum(),
                                     100 * (sub.brut_240.to_numpy()[m & (sub.tranche == t).to_numpy()] <= -0.5).mean()) for t in "RTF"))
    # hasard : regime calcule sur des resultats melanges
    rng = np.random.default_rng(2)
    mieux = 0
    for _ in range(50):
        rh = evaluer(df, risque, regimes_pour(rng))
        vh = [(k, s, n) for k, s, n in rh if s["R"] and s["T"] and s["T"]["n"] >= 50]
        vh.sort(key=lambda z: -min(z[1]["R"]["moy"], z[1]["T"]["moy"]))
        if vh and vh[0][1]["F"] and sF and vh[0][1]["F"]["moy"] >= sF["moy"]:
            mieux += 1
    print("\nHASARD : %d tirages sur 50 (regime sans information temporelle) obtiennent un TEST aussi bon" % mieux)


if __name__ == "__main__":
    main()
