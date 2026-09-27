"""Etude de la COURBE pump.fun, etape 2 : le verdict. PROTOCOLE FIGE AVANT DE LIRE LA TABLE (15/09 soir).

DONNEES  data/recherche/courbe/table.pkl (courbe_table.py). Tranches par heure de creation du jeton.
COUT     PRINCIPAL 0,025 + 0,0032 + 2 x 0,31 / (30 + S_entree) ; PRUDENT = principal + 0,01 (pourboires).
         Rendements plafonnes a +300 % pour les moyennes. Une regle = un niveau S fixe : un trade par jeton au plus.
TEMOIN   sans filtre, par niveau S et duree H, par tranche (imprime d abord).
FAMILLE 1  regles : S x H x filtre, filtres = {aucun, bons >= 1 sans vente d un bon, createur n a pas vendu,
           les deux, rapide (secondes pour atteindre S <= mediane RECHERCHE au meme S), lent (> mediane),
           acheteurs >= mediane RECHERCHE, flux calme (SOL achete 30 s <= mediane RECHERCHE), createur a vendu}.
FAMILLE 2  LightGBM du rendement net (un modele par H, S en variable) appris sur RECHERCHE ; haut q dans
           {5, 10, 20 %} (seuils = quantiles RECHERCHE au meme S).
SELECTION  meilleure moyenne TRI avec n >= 50, dans chaque famille. TEST FINAL lu une fois par famille.
GO       TEST : moyenne >= +1,1 % (cout principal), sans le meilleur > 0, n >= 30, deux moities > 0, ET hasard aussi
         bon dans au plus 10 % des tirages (F1 : rendements melanges au sein de chaque S, 20 tirages ; F2 : cible
         melangee dans RECHERCHE, 10 tirages). Imprime aussi : cout prudent, part des sorties approximees, EUR/jour
         a 30 EUR.
RESERVE  deux jours de donnees seulement ; un GO devra se confirmer sur des jours NEUFS avant tout euro reel, et
         la faisabilite temps reel (suivre la courbe de tous les jetons) reste a etablir.
"""
from __future__ import annotations

import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

ICI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ICI)
import copie_verdict as cv  # noqa: E402
import grand_balayage as gb  # noqa: E402

DC = os.path.join(os.path.abspath(os.path.join(ICI, "..", "..")), "data", "recherche", "courbe")
HS = (30, 60, 120, 300, 600, 1800)
QS = (0.05, 0.10, 0.20)
VARS = ["S", "S_e", "age", "n_echanges", "n_acheteurs", "n_vendeurs", "sol_achete_30", "sol_vendu_30", "sol_achete_60",
        "sol_vendu_60", "part_top", "createur_connu", "createur_vendu", "part_createur", "n_bloc_creation", "n_bons",
        "sol_bons", "n_bons_vendu"]
PARAMS = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=80, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0, verbose=-1)


def preparer():
    df = pd.read_pickle(os.path.join(DC, "table.pkl")).reset_index(drop=True)
    df["cout"] = 0.025 + 0.0032 + 2 * 0.31 / (30 + df.S_e)
    for H in HS:
        df["net_%d" % H] = np.minimum(df["brut_%d" % H] - df.cout, gb.PLAFOND)
    assert not [v for v in VARS if v.startswith(("brut", "net", "cout", "approx", "complet"))]
    return df


def filtres(df):
    R = df[df.tranche == "R"]
    med = lambda col: R.groupby("S")[col].median()
    m_age, m_ach, m_sol30 = med("age"), med("n_acheteurs"), med("sol_achete_30")
    a = lambda s: df.S.map(s).to_numpy()
    age, nach, s30 = df.age.to_numpy(), df.n_acheteurs.to_numpy(), df.sol_achete_30.to_numpy()
    bons = (df.n_bons >= 1).to_numpy() & (df.n_bons_vendu == 0).to_numpy()
    crea_ok = (df.createur_vendu == 0).to_numpy()
    return {"aucun": np.ones(len(df), bool), "bons>=1": bons, "createur garde": crea_ok, "bons+createur": bons & crea_ok,
            "rapide": age <= a(m_age), "lent": age > a(m_age), "acheteurs>=med": nach >= a(m_ach),
            "flux calme": s30 <= a(m_sol30), "createur a vendu": ~crea_ok}


def stats_go(df, masque, H):
    y = df["net_%d" % H].to_numpy(float)[masque]
    t = df.t0.to_numpy()[masque]
    ok = ~np.isnan(y)
    y, t = y[ok], t[ok]
    s = gb.stats(y)
    if not s:
        return None, False, y, t
    mil = np.median(t)
    h1, h2 = gb.stats(y[t < mil]), gb.stats(y[t >= mil])
    go = s["n"] >= 30 and s["moy"] >= gb.OBJ and s["sb1"] > 0 and bool(h1) and bool(h2) and h1["moy"] > 0 and h2["moy"] > 0
    return (s, h1, h2), go, y, t


def selection_regles(df, cib, filt):
    best = None
    T = (df.tranche == "T").to_numpy()
    for S in sorted(df.S.unique()):
        mS = (df.S == S).to_numpy()
        for nom, m in filt.items():
            for H in HS:
                s = gb.stats(cib[H][T & mS & m])
                if s and s["n"] >= 50 and (best is None or s["moy"] > best[3]["moy"]):
                    best = (S, nom, H, s)
    return best


def dire(r):
    if not r:
        return "trop peu"
    s, h1, h2 = r
    return "%s · moities %+.4f / %+.4f" % (cv.fmt(s), h1["moy"] if h1 else np.nan, h2["moy"] if h2 else np.nan)


def main():
    df = preparer()
    jours = {t: (g.t0.max() - g.t0.min()) / 86400 for t, g in df.groupby("tranche")}
    print("table : %d decisions, %d jetons · %s" % (len(df), df.mint.nunique(),
          " · ".join("%s %d jetons %.2f j" % (t, df[df.tranche == t].mint.nunique(), jours[t]) for t in "RTF")))
    print("\nTEMOIN sans filtre, cout principal : moyenne (n) par tranche R / T / F")
    for S in sorted(df.S.unique()):
        for H in (60, 300, 1800):
            cells = []
            for t in "RTF":
                s = gb.stats(df[(df.S == S) & (df.tranche == t)]["net_%d" % H].to_numpy(float))
                cells.append(("%+.3f (%d)" % (s["moy"], s["n"])) if s else "-")
            print("  S=%-3d H=%-5d %s" % (S, H, "   ".join(cells)))

    filt = filtres(df)
    cib = {H: df["net_%d" % H].to_numpy(float) for H in HS}
    print("\nFAMILLE 1 : regles")
    ch = selection_regles(df, cib, filt)
    go1 = False
    if ch:
        S, nom, H, sT = ch
        mF = ((df.tranche == "F") & (df.S == S)).to_numpy() & filt[nom]
        r, ok, y, t = stats_go(df, mF, H)
        print("  retenue : S=%d SOL, filtre %s, H=%d s · TRI %s" % (S, nom, H, cv.fmt(sT)))
        print("  TEST FINAL : %s" % dire(r))
        if r:
            prud = gb.stats(y - 0.01)
            appro = df["approx_%d" % H].to_numpy(float)[mF]
            print("  cout prudent %+.4f · sorties approximees %.0f %% · %.0f trades/jour x 30 EUR = %+.0f EUR/jour" % (
                prud["moy"], 100 * np.nanmean(appro), r[0]["n"] / max(jours["F"], 1e-9), r[0]["n"] / max(jours["F"], 1e-9) * r[0]["moy"] * 30))
        rng = np.random.default_rng(3)
        mieux = 0
        for _ in range(20):
            mel = {}
            for H2, v in cib.items():
                vv = v.copy()
                for S2 in df.S.unique():
                    idx = np.where((df.S == S2).to_numpy())[0]
                    vv[idx] = rng.permutation(v[idx])
                mel[H2] = vv
            c2 = selection_regles(df, mel, filt)
            if c2 and r:
                S2, n2, H2, _ = c2
                m2 = ((df.tranche == "F") & (df.S == S2)).to_numpy() & filt[n2]
                s2 = gb.stats(mel[H2][m2])
                if s2 and s2["moy"] >= r[0]["moy"]:
                    mieux += 1
        go1 = ok and mieux <= 2
        print("  HASARD : %d tirages sur 20 font aussi bien · VERDICT %s" % (mieux, "GO" if go1 else "NON"))

    print("\nFAMILLE 2 : LightGBM du rendement net")
    R = (df.tranche == "R").to_numpy()
    T = (df.tranche == "T").to_numpy()
    X = df[VARS].astype(float)

    def scores(rng=None):
        out = {}
        for H in HS:
            y = cib[H]
            ok = R & ~np.isnan(y)
            yy = y.copy()
            if rng is not None:
                yy[ok] = rng.permutation(y[ok])
            out[H] = lgb.LGBMRegressor(**PARAMS).fit(X[ok], yy[ok]).predict(X)
        return out

    def choisir(sc):
        best = None
        for H in HS:
            for S in sorted(df.S.unique()):
                mS = (df.S == S).to_numpy()
                if (R & mS).sum() < 50:
                    continue
                for q in QS:
                    seuil = np.quantile(sc[H][R & mS], 1 - q)
                    m = mS & (sc[H] >= seuil)
                    s = gb.stats(cib[H][T & m])
                    if s and s["n"] >= 50 and (best is None or s["moy"] > best[3]["moy"]):
                        best = (S, H, q, s, seuil)
        return best

    sc = scores()
    ch2 = choisir(sc)
    if ch2:
        S, H, q, sT, seuil = ch2
        mF = ((df.tranche == "F") & (df.S == S)).to_numpy() & (sc[H] >= seuil)
        r, ok, y, t = stats_go(df, mF, H)
        print("  retenue : S=%d SOL, H=%d s, haut %d %% · TRI %s" % (S, H, int(100 * q), cv.fmt(sT)))
        print("  TEST FINAL : %s" % dire(r))
        rng = np.random.default_rng(5)
        mieux = 0
        for _ in range(10):
            sch = scores(rng)
            c = choisir(sch)
            if c and r:
                S2, H2, q2, _, s2 = c
                m2 = ((df.tranche == "F") & (df.S == S2)).to_numpy() & (sch[H2] >= s2)
                st = gb.stats(cib[H2][m2])
                if st and st["moy"] >= r[0]["moy"]:
                    mieux += 1
        print("  HASARD : %d tirages sur 10 font aussi bien · VERDICT %s" % (mieux, "GO" if (ok and mieux <= 1) else "NON"))


if __name__ == "__main__":
    main()
