"""Rejouer le balayage d ENTREE avec la nouvelle SORTIE (prise de gain +25 %), 16/09.

POURQUOI. Tous nos balayages jugeaient une sortie a heure fixe. La prise de gain a +25 % (sinon 240 s) gagne 1 a
3 points par ticket dans les quatre populations testees (§3.91) : les conclusions d entree doivent etre refaites,
puisque la cible a change.

DONNEES  variables d entree : data/recherche/copie/etude.pkl (56 variables visibles a la decision, A = 45 s) ;
         cible : rendement avec prise de gain, calcule transaction par transaction sur echanges.jsonl (entree au
         prix de la derniere transaction <= 47 s, sortie a la premiere transaction >= +25 %, executee 2 s plus
         tard, sinon 287 s), cout reel mesure 2,62 points, plafond +300 %.
         Ajout : `q_naissance` = coffre SOL + reserve virtuelle a la premiere transaction (marqueur d injection).
PROTOCOLE  tranches par naissance du pool (RECHERCHE 60 %, TRI 20 %, TEST 20 %) deja dans la table.
         F1 : LightGBM appris sur RECHERCHE, on garde le haut q (5, 10, 20 %) ; choix (q) sur TRI ; TEST lu une fois.
         F2 : regles a une variable (quintiles) et la regle connue « tendance > 0 et coffre < 100 SOL » ;
              candidat si RECHERCHE n >= 80 et moyenne >= +1,1 % ; survivant si TRI n >= 30 et moyenne >= +1,1 % ;
              TEST lu une fois pour les 10 meilleurs.
         HASARD : memes familles sur des rendements melanges au sein de la tranche (10 tirages).
RESERVE  la tranche TEST a deja servi deux fois (§3.87, §3.88) : un GO ici ne vaut pas preuve, il doit etre
         confirme sur des jours neufs (regles D et E pre-enregistrees).
"""
from __future__ import annotations

import json
import os
import sys
from bisect import bisect_right

import numpy as np
import pandas as pd

ICI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ICI)
import copie_verdict as cv  # noqa: E402
import grand_balayage as gb  # noqa: E402

D = cv.D
COUT, MISE, PLAFOND, TP, RETARD = 0.0262, 30.0, 3.0, 0.25, 2.0


def cible_tp():
    """Rendement avec prise de gain, par pool, entree 47 s."""
    out = {}
    for ligne in open(os.path.join(D, "echanges.jsonl"), encoding="utf-8"):
        d = json.loads(ligne)
        if d.get("erreur") or not d.get("echanges"):
            continue
        e = [x for x in d["echanges"] if x[2] and x[0] <= 320]
        if len(e) < 5:
            continue
        ages = [x[0] for x in e]
        prix = [x[2] for x in e]
        q = [x[3] + d["V"] for x in e]

        def idx(t):
            i = bisect_right(ages, t) - 1
            return i if i >= 0 else None

        i0, fin = idx(47), idx(287)
        if i0 is None or fin is None or fin <= i0 or prix[i0] <= 0 or 0.31 / q[i0] > 0.15:
            continue
        pe = prix[i0]
        r = None
        for i in range(i0 + 1, fin + 1):
            if prix[i] >= pe * (1 + TP):
                j = idx(ages[i] + RETARD)
                j = min(j if j is not None else i, fin)
                r = prix[j] / pe - 1
                break
        if r is None:
            r = prix[fin] / pe - 1
        out[d["pair"]] = (min(r, PLAFOND) - COUT, q[0])
    return out


def main():
    df = pd.read_pickle(os.path.join(D, "etude.pkl"))
    df = df[df.A == 45].copy()
    cible = cible_tp()
    df["net_tp"] = df.pair.map(lambda p: cible.get(p, (np.nan, np.nan))[0])
    df["q_naissance"] = df.pair.map(lambda p: cible.get(p, (np.nan, np.nan))[1])
    df = df[df.net_tp.notna()].reset_index(drop=True)
    vars_ = [c for c in df.columns if c not in {"pair", "t0", "tranche", "q_e", "qV", "bon_achete_10",
                                                "brut_sortie_bons", "net_tp"} and not c.startswith(("brut_", "net_", "cout"))]
    print("pools : %d · R %d / T %d / F %d · variables %d" % (
        len(df), *[int((df.tranche == t).sum()) for t in "RTF"], len(vars_)))
    y = df.net_tp.to_numpy(float)
    t0 = df.t0.to_numpy()
    R, T, F = [(df.tranche == t).to_numpy() for t in "RTF"]
    for nom, m in (("tous", np.ones(len(df), bool)), ("coffre < 100 SOL", (df.q_naissance < 100).to_numpy()),
                   ("tendance > 0", (df.regime50 > 0).to_numpy()),
                   ("tendance + coffre < 100", ((df.regime50 > 0) & (df.q_naissance < 100)).to_numpy())):
        print("  %-24s R %+6.2f %% (%4d) %+6.0f EUR · T %+6.2f %% (%3d) %+6.0f EUR · F %+6.2f %% (%3d) %+6.0f EUR" % (
            nom, *sum([[100 * y[m & g].mean() if (m & g).sum() else np.nan, int((m & g).sum()), MISE * y[m & g].sum()]
                       for g in (R, T, F)], [])))

    import lightgbm as lgb
    X = df[vars_].astype(float)
    mod = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=80,
                            subsample=0.8, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0,
                            verbose=-1).fit(X[R], y[R])
    score = mod.predict(X)
    print("\nFAMILLE 1 : modele du rendement avec prise de gain")
    best = None
    for q in (0.05, 0.10, 0.20):
        seuil = np.quantile(score[R], 1 - q)
        m = score >= seuil
        s = gb.stats(y[T & m])
        if s and s["n"] >= 30 and (best is None or s["moy"] > best[1]["moy"]):
            best = (q, s, seuil)
    if best:
        q, sT, seuil = best
        m = F & (score >= seuil)
        sF = gb.stats(y[m])
        print("  haut %d %% · TRI %s · TEST %s · %+.0f EUR" % (int(100 * q), cv.fmt(sT), cv.fmt(sF), MISE * y[m].sum()))
        imp = sorted(zip(mod.booster_.feature_importance("gain"), vars_), reverse=True)[:8]
        tot = sum(mod.booster_.feature_importance("gain")) or 1
        print("  variables : " + ", ".join("%s %.0f %%" % (v, 100 * g / tot) for g, v in imp))

    print("\nFAMILLE 2 : regles a une variable (quintiles de RECHERCHE)")
    cands = []
    for v in vars_:
        x = df[v].to_numpy(float)
        xr = x[R][~np.isnan(x[R])]
        if len(np.unique(xr)) < 5:
            continue
        e = np.unique(np.quantile(xr, [0, .2, .4, .6, .8, 1]))
        if len(e) < 6:
            continue
        for k in range(5):
            m = (x >= e[k]) & ((x <= e[k + 1]) if k == 4 else (x < e[k + 1]))
            s = gb.stats(y[R & m])
            if s and s["n"] >= 80 and s["moy"] >= gb.OBJ and s["sb3"] >= gb.OBJ:
                cands.append(("%s Q%d" % (v, k + 1), m, s))
    surv = []
    for nom, m, sR in cands:
        s = gb.stats(y[T & m])
        if s and s["n"] >= 30 and s["moy"] >= gb.OBJ and s["sb1"] > 0:
            surv.append((nom, m, sR, s))
    print("  candidats RECHERCHE : %d · survivants TRI : %d" % (len(cands), len(surv)))
    surv.sort(key=lambda z: -min(z[2]["moy"], z[3]["moy"]))
    for nom, m, sR, sT in surv[:10]:
        sF = gb.stats(y[F & m])
        print("  %-28s R %+6.2f %% (%4d) · T %+6.2f %% (%3d) · TEST %s · %+.0f EUR" % (
            nom, 100 * sR["moy"], sR["n"], 100 * sT["moy"], sT["n"], cv.fmt(sF), MISE * y[F & m].sum()))
    rng = np.random.default_rng(16)
    faux = 0
    for _ in range(10):
        yp = y.copy()
        for g in (R, T, F):
            yp[g] = rng.permutation(y[g])
        c = 0
        for v in vars_:
            x = df[v].to_numpy(float)
            xr = x[R][~np.isnan(x[R])]
            if len(np.unique(xr)) < 5:
                continue
            e = np.unique(np.quantile(xr, [0, .2, .4, .6, .8, 1]))
            if len(e) < 6:
                continue
            for k in range(5):
                m = (x >= e[k]) & ((x <= e[k + 1]) if k == 4 else (x < e[k + 1]))
                s1, s2 = gb.stats(yp[R & m]), gb.stats(yp[T & m])
                if s1 and s2 and s1["n"] >= 80 and s1["moy"] >= gb.OBJ and s1["sb3"] >= gb.OBJ and s2["n"] >= 30 and s2["moy"] >= gb.OBJ and s2["sb1"] > 0:
                    c += 1
        faux += c
    print("  HASARD : %.1f survivants par tirage (10 tirages sur rendements melanges)" % (faux / 10))


if __name__ == "__main__":
    main()
