"""Pourquoi les bons portefeuilles gagnent : etape 2, le verdict. PROTOCOLE FIGE AVANT DE LIRE LA TABLE (15/09 soir).

DONNEES  data/recherche/copie/etude.pkl (bons_etude.py). Tranches par naissance : RECHERCHE / TRI / TEST FINAL.
COUT     PRINCIPAL = cout reel du moteur : 0,017 + 2 x 0,31 / (coffre SOL + reserve virtuelle) a l entree.
         Information seulement : cout reduit 0,0125 + (reel - 0,017) / 2.
RENDEMENT plafonne a +300 %. Une regle = un age A fixe, donc un trade par pool au plus.

FAMILLE 1  LightGBM du rendement net a H (un modele par H dans {60, 120, 240}, A en variable), appris sur
           RECHERCHE. On achete les lignes dont la prediction est dans le haut q (q dans {5, 10, 20 %}, seuils =
           quantiles des predictions de RECHERCHE au meme A).
FAMILLE 2  LightGBM « un bon portefeuille achete dans les 10 s » appris sur RECHERCHE ; memes seuils q, P&L a H.
FAMILLE 3  Regles tirees du comportement des bons, grille fixe :
           3a bons presents : n_bons >= m (m dans {1, 2, 3}) et aucun n a vendu ; sortie H ou « a la premiere
              vente d un bon » (plafond 240 s) ;
           3b achat apres grosse vente : plus grosse vente des 30 s >= x du pool (x dans {3 %, 5 %}), il y a au
              plus 5 s, repli depuis le plus haut <= -y (y dans {10 %, 20 %}) ; sortie H ;
           3c chaque regle 3a / 3b ET regime50 > 0.
SELECTION  dans chaque famille, la combinaison (A, H, reglage) a la meilleure moyenne TRI avec n >= 50.
TEST     TEST FINAL lu une fois par famille. GO si moyenne >= +1,1 %, sans le meilleur > 0, n >= 30, les deux
         moities > 0, ET si le temoin de hasard fait aussi bien dans au plus 10 % des tirages.
HASARD   F1 et F2 : modele appris sur une cible melangee dans RECHERCHE (10 tirages), meme selection.
         F3 : rendements melanges au sein de chaque age sur toutes les tranches (20 tirages), meme selection.
RESERVE  Le TEST FINAL a deja servi une fois (verdict de copie, §3.87). Un GO ici ne suffit pas pour du reel : il
         devra se confirmer sur des pools nes APRES le 15/09 (nouvelle collecte), sans rien changer.
DIAGNOSTIC (ne decide rien) : importance des variables des modeles ; rendement net a 120 s par quintile de chaque
         variable sur RECHERCHE et TRI (meme signe ?).
"""
from __future__ import annotations

import itertools
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
import copie_verdict as cv  # noqa: E402
import grand_balayage as gb  # noqa: E402

HS = (60, 120, 240)
QS = (0.05, 0.10, 0.20)
# qV est lu a A + 2 s (fuite) ; les brut_* sont les RESULTATS. Controle a l execution : aucune variable ne doit
# commencer par brut_ ni net_ (un commentaire mal place les avait laisses entrer le 15/09 : faux GO a +108 %).
NON_VARS = {"pair", "t0", "tranche", "q_e", "qV", "bon_achete_10", "brut_sortie_bons"} | {"brut_%d" % h for h in (60, 120, 240, 480)}
PARAMS = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=80, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0, verbose=-1)


def preparer():
    df = pd.read_pickle(os.path.join(cv.D, "etude.pkl"))
    df["cout"] = cv.COUT_FIXE + 2 * cv.MISE_SOL / df.qV
    df["cout_reduit"] = 0.0125 + (df.cout - 0.017) / 2
    for h in (60, 120, 240):
        df["net_%d" % h] = np.minimum(df["brut_%d" % h] - df.cout, gb.PLAFOND)
    df["net_sortie_bons"] = np.minimum(df.brut_sortie_bons - df.cout, gb.PLAFOND)
    for c in ("telegram", "twitter", "site", "det_a_vide", "fin_a_vide"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    vars_ = [c for c in df.columns if c not in NON_VARS and not c.startswith(("net_", "cout"))]
    fuites = [c for c in vars_ if c.startswith(("brut", "net", "cout")) or c in ("qV", "q_e", "bon_achete_10")]
    assert not fuites, "variables de resultat dans les entrees : %s" % fuites
    return df.reset_index(drop=True), vars_


def verdict_ligne(v, t0):
    s = gb.stats(v)
    if not s:
        return None, False
    mil = np.median(t0)
    h1, h2 = gb.stats(v[t0 < mil]), gb.stats(v[t0 >= mil])
    ok = s["n"] >= 30 and s["moy"] >= gb.OBJ and s["sb1"] > 0 and bool(h1) and bool(h2) and h1["moy"] > 0 and h2["moy"] > 0
    return (s, h1, h2), ok


def fmt3(r):
    if not r:
        return "trop peu"
    s, h1, h2 = r
    return "%s · moities %+.4f / %+.4f" % (cv.fmt(s), h1["moy"] if h1 else np.nan, h2["moy"] if h2 else np.nan)


def selection_modele(df, score, cible_h=HS):
    """Seuils par A sur RECHERCHE ; meilleure moyenne TRI (n >= 50). Renvoie (A, H, q, stats TRI)."""
    best = None
    R, T = (df.tranche == "R").to_numpy(), (df.tranche == "T").to_numpy()
    for A in sorted(df.A.unique()):
        mA = (df.A == A).to_numpy()
        for q in QS:
            seuil = np.quantile(score[R & mA], 1 - q)
            m = mA & (score >= seuil)
            for H in cible_h:
                y = df["net_%d" % H].to_numpy(float)
                s = gb.stats(y[T & m])
                if s and s["n"] >= 50 and (best is None or s["moy"] > best[3]["moy"]):
                    best = (A, H, q, s, seuil)
    return best


def appliquer_modele(df, score, choix):
    A, H, q, _, seuil = choix
    m = ((df.tranche == "F") & (df.A == A)).to_numpy() & (score >= seuil)
    y = df["net_%d" % H].to_numpy(float)[m]
    t = df.t0.to_numpy()[m]
    ok = ~np.isnan(y)
    return y[ok], t[ok]


def famille_modele(df, vars_, nom, cible, regression):
    R = (df.tranche == "R").to_numpy()
    X = df[vars_].astype(float)
    y = cible.to_numpy(float)
    ok = R & ~np.isnan(y)
    Mod = lgb.LGBMRegressor if regression else lgb.LGBMClassifier
    m = Mod(**PARAMS).fit(X[ok], y[ok])
    score = m.predict(X) if regression else m.predict_proba(X)[:, 1]
    choix = selection_modele(df, score)
    print("\n%s" % nom)
    if not choix:
        print("  aucune combinaison avec n >= 50 sur TRI")
        return None
    A, H, q, sT, _ = choix
    yF, tF = appliquer_modele(df, score, choix)
    r, ok_go = verdict_ligne(yF, tF)
    print("  retenue : A=%d s, H=%d s, haut %d %% · TRI %s" % (A, H, int(100 * q), cv.fmt(sT)))
    print("  TEST FINAL : %s" % fmt3(r))
    rng = np.random.default_rng(7)
    mieux = 0
    for _ in range(10):
        yp = y.copy()
        yp[ok] = rng.permutation(y[ok])
        mh = Mod(**PARAMS).fit(X[ok], yp[ok])
        sh = mh.predict(X) if regression else mh.predict_proba(X)[:, 1]
        ch = selection_modele(df, sh)
        if ch and r:
            yh, _ = appliquer_modele(df, sh, ch)
            s_h = gb.stats(yh)
            if s_h and s_h["moy"] >= r[0]["moy"]:
                mieux += 1
    go = ok_go and mieux <= 1
    print("  HASARD : %d tirages sur 10 font aussi bien au TEST · VERDICT %s" % (mieux, "GO" if go else "NON"))
    imp = sorted(zip(m.booster_.feature_importance("gain"), vars_), reverse=True)[:12]
    tot = sum(g for g, _ in zip(m.booster_.feature_importance("gain"), vars_)) or 1
    print("  variables les plus utiles : " + ", ".join("%s %.0f %%" % (v, 100 * g / tot) for g, v in imp))
    return go


def regles(df):
    out = []
    reg = (df.regime50 > 0).to_numpy()
    sans_sortie = (df.n_bons_sortis == 0).to_numpy()
    for mm in (1, 2, 3):
        base = (df.n_bons >= mm).to_numpy() & sans_sortie
        for avec_reg in (False, True):
            m = base & reg if avec_reg else base
            for sortie in HS + ("sortie_bons",):
                out.append(("3%s bons>=%d%s sortie %s" % ("c" if avec_reg else "a", mm, " +regime" if avec_reg else "", sortie), m, sortie))
    for x, yv in itertools.product((0.03, 0.05), (0.10, 0.20)):
        base = ((df.max_vente_30_part >= x) & (df.t_depuis_grosse_vente <= 5) & (df.dd_max <= -yv)).to_numpy()
        for avec_reg in (False, True):
            m = base & reg if avec_reg else base
            for H in HS:
                out.append(("3%s vente>=%d%% repli<=-%d%%%s sortie %s" % ("c" if avec_reg else "b", 100 * x, 100 * yv, " +regime" if avec_reg else "", H), m, H))
    return out


def selection_regles(df, cibles):
    best = None
    for A in sorted(df.A.unique()):
        mA = (df.A == A).to_numpy()
        T = (df.tranche == "T").to_numpy() & mA
        for nom, m, sortie in regles(df):
            y = cibles[sortie]
            s = gb.stats(y[T & m])
            if s and s["n"] >= 50 and (best is None or s["moy"] > best[3]["moy"]):
                best = (A, nom, sortie, s, m)
    return best


def famille_regles(df):
    cibles = {H: df["net_%d" % H].to_numpy(float) for H in HS}
    cibles["sortie_bons"] = df.net_sortie_bons.to_numpy(float)
    print("\nFAMILLE 3 : regles tirees du comportement des bons")
    choix = selection_regles(df, cibles)
    if not choix:
        print("  aucune regle avec n >= 50 sur TRI")
        return None
    A, nom, sortie, sT, m = choix
    F = ((df.tranche == "F") & (df.A == A)).to_numpy() & m
    y = cibles[sortie][F]
    t = df.t0.to_numpy()[F]
    ok = ~np.isnan(y)
    r, ok_go = verdict_ligne(y[ok], t[ok])
    print("  retenue : A=%d s, %s · TRI %s" % (A, nom, cv.fmt(sT)))
    print("  TEST FINAL : %s" % fmt3(r))
    rng = np.random.default_rng(11)
    mieux = 0
    for _ in range(20):
        melange = {}
        for k, v in cibles.items():
            vv = v.copy()
            for A_ in df.A.unique():
                idx = np.where((df.A == A_).to_numpy())[0]
                vv[idx] = rng.permutation(v[idx])
            melange[k] = vv
        ch = selection_regles(df, melange)
        if ch and r:
            A2, _, s2, _, m2 = ch
            F2 = ((df.tranche == "F") & (df.A == A2)).to_numpy() & m2
            sh = gb.stats(melange[s2][F2])
            if sh and sh["moy"] >= r[0]["moy"]:
                mieux += 1
    go = ok_go and mieux <= 2
    print("  HASARD : %d tirages sur 20 font aussi bien au TEST · VERDICT %s" % (mieux, "GO" if go else "NON"))
    return go


def diagnostic(df, vars_):
    print("\nDIAGNOSTIC : rendement net a 120 s (cout reel) par quintile, RECHERCHE puis TRI, decision a 45 et 90 s")
    for A in (45, 90):
        sub = df[df.A == A]
        R, T = sub[sub.tranche == "R"], sub[sub.tranche == "T"]
        for v in vars_:
            x = R[v].dropna()
            if x.nunique() < 5:
                continue
            e = np.unique(np.quantile(x, [0, .2, .4, .6, .8, 1]))
            if len(e) < 6:
                continue
            ligne = []
            for part in (R, T):
                xx, yy = part[v].to_numpy(float), part.net_120.to_numpy(float)
                moy = []
                for k in range(5):
                    mk = (xx >= e[k]) & ((xx <= e[k + 1]) if k == 4 else (xx < e[k + 1])) & ~np.isnan(yy)
                    moy.append(np.mean(yy[mk]) if mk.sum() >= 20 else np.nan)
                ligne.append(moy)
            ecart_R, ecart_T = ligne[0][4] - ligne[0][0], ligne[1][4] - ligne[1][0]
            if np.sign(ecart_R) == np.sign(ecart_T) and min(abs(ecart_R), abs(ecart_T)) >= 0.02:
                print("  A=%-3d %-22s R %s | T %s" % (A, v, " ".join("%+.3f" % z for z in ligne[0]), " ".join("%+.3f" % z for z in ligne[1])))


def main():
    df, vars_ = preparer()
    jours = {t: (g.t0.max() - g.t0.min()) / 86400 for t, g in df.groupby("tranche")}
    print("etude : %d lignes, %d pools · %s · %d variables" % (len(df), df.pair.nunique(),
          " ".join("%s %d pools %.1f j" % (t, (df[df.tranche == t].pair.nunique()), jours[t]) for t in "RTF"), len(vars_)))
    print("sans filtre, cout reel, par tranche (A=45, H=120) : " + " · ".join(
        "%s %s" % (t, cv.fmt(gb.stats(df[(df.A == 45) & (df.tranche == t)].net_120.to_numpy(float)))) for t in "RTF"))
    # un modele par H : on les entraine tous, la selection choisit (A, H, q) parmi eux
    print("\nFAMILLE 1 : LightGBM du rendement net (un modele par H)")
    R = (df.tranche == "R").to_numpy()
    X = df[vars_].astype(float)
    scores = {}
    for H in HS:
        y = df["net_%d" % H].to_numpy(float)
        ok = R & ~np.isnan(y)
        scores[H] = lgb.LGBMRegressor(**PARAMS).fit(X[ok], y[ok]).predict(X)
    best = None
    T = (df.tranche == "T").to_numpy()
    for H in HS:
        for A in sorted(df.A.unique()):
            mA = (df.A == A).to_numpy()
            for q in QS:
                seuil = np.quantile(scores[H][R & mA], 1 - q)
                m = mA & (scores[H] >= seuil)
                s = gb.stats(df["net_%d" % H].to_numpy(float)[T & m])
                if s and s["n"] >= 50 and (best is None or s["moy"] > best[3]["moy"]):
                    best = (A, H, q, s, seuil)
    if best:
        A, H, q, sT, seuil = best
        m = ((df.tranche == "F") & (df.A == A)).to_numpy() & (scores[H] >= seuil)
        y = df["net_%d" % H].to_numpy(float)[m]; t = df.t0.to_numpy()[m]; ok = ~np.isnan(y)
        r, ok_go = verdict_ligne(y[ok], t[ok])
        print("  retenue : A=%d s, H=%d s, haut %d %% · TRI %s" % (A, H, int(100 * q), cv.fmt(sT)))
        print("  TEST FINAL : %s" % fmt3(r))
        rng = np.random.default_rng(7)
        mieux = 0
        for _ in range(10):
            sc = {}
            for H2 in HS:
                y2 = df["net_%d" % H2].to_numpy(float)
                ok2 = R & ~np.isnan(y2)
                yp = y2.copy(); yp[ok2] = rng.permutation(y2[ok2])
                sc[H2] = lgb.LGBMRegressor(**PARAMS).fit(X[ok2], yp[ok2]).predict(X)
            bh = None
            for H2 in HS:
                for A2 in sorted(df.A.unique()):
                    mA2 = (df.A == A2).to_numpy()
                    for q2 in QS:
                        s2 = np.quantile(sc[H2][R & mA2], 1 - q2)
                        mm = mA2 & (sc[H2] >= s2)
                        st = gb.stats(df["net_%d" % H2].to_numpy(float)[T & mm])
                        if st and st["n"] >= 50 and (bh is None or st["moy"] > bh[3]["moy"]):
                            bh = (A2, H2, q2, st, s2)
            if bh and r:
                A2, H2, q2, _, s2 = bh
                mm = ((df.tranche == "F") & (df.A == A2)).to_numpy() & (sc[H2] >= s2)
                sh = gb.stats(df["net_%d" % H2].to_numpy(float)[mm])
                if sh and sh["moy"] >= r[0]["moy"]:
                    mieux += 1
        print("  HASARD : %d tirages sur 10 font aussi bien au TEST · VERDICT %s" % (mieux, "GO" if (ok_go and mieux <= 1) else "NON"))
    famille_modele(df, vars_, "FAMILLE 2 : LightGBM « un bon achete dans les 10 s »", df.bon_achete_10, False)
    famille_regles(df)
    diagnostic(df, vars_)


if __name__ == "__main__":
    main()
