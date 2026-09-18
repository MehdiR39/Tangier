"""SELECTIVITE, CALIBRATION, CIBLE : ce que vaut un classement REEL en argent.

§3.139 a etabli que la foret de gain classe gagnants/perdants hors echantillon (AUC 0,65-0,82 sur
9 fenetres sur 9, chacune au-dessus du max de 20 permutations). Ce module repond a la question
suivante : COMBIEN d argent ce classement rend-il, selon (a) la selectivite -- garder les k % les
plus probables -- et (b) la CIBLE d entrainement -- reconnaitre « net > 0 » ou « net > +5/10/20 % ».

Protocole : marche avant, coupes de 6 h du 16/09 00h au 18/09 18h, tickets avec donnees de
transactions (V1_SEUL), foret 300 arbres / feuilles 20 / trous a la mediane, cout 6,55 multiplicatif.
Barre du hasard : NULLS permutations des RESULTATS a l interieur de chaque fenetre, en retenant a
chaque fois la meilleure des cellules (cible x coupe) -- le maximum sous permutation de la procedure.

Usage : python -m intel.research.selectivite
"""
from __future__ import annotations

import datetime as dt
import os
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

warnings.filterwarnings("ignore")
DOSSIER = "/app/data/recherche/tout"
COUT = float(os.environ.get("COUT_MESURE", "0.0655"))
MISE = 20.0
TAUS = (0.0, 0.05, 0.10, 0.20)
CUTS = (0.05, 0.10, 0.20, 0.30)
NULLS = int(os.environ.get("NULLS", "200"))


def main() -> None:
    df = pd.read_pickle(os.path.join(DOSSIER, "table.pkl"))
    variables = [v for v in df.attrs["VARIABLES"] if v != "tg_poste"]
    df = df[(df.eligible == 1) & df.ret_240.notna() & df.v1_n_achats.notna()].sort_values("t_dec").reset_index(drop=True)
    X = df[variables].apply(pd.to_numeric, errors="coerce").astype(float)
    garde = [v for v in variables if X[v].notna().sum() >= 100 and X[v].nunique(dropna=True) >= 2]
    X = X[garde]
    ynet = (1 + df.ret_240.to_numpy()) * (1 - COUT) - 1
    t = df.t_dec.to_numpy()
    tz = dt.timezone(dt.timedelta(hours=2))
    c, fin = dt.datetime(2026, 9, 16, 0, 0, tzinfo=tz), dt.datetime(2026, 9, 18, 18, 0, tzinfo=tz)
    tot = {(tau, k): [] for tau in TAUS for k in CUTS}
    fen = {(tau, k): [] for tau in TAUS for k in CUTS}
    scores = {tau: [] for tau in TAUS}
    nets_all, wid, w = [], [], 0
    while c < fin:
        c0, c1 = c.timestamp(), (c + dt.timedelta(hours=6)).timestamp()
        A, J = t < c0, (t >= c0) & (t < c1)
        if A.sum() >= 150 and J.sum() >= 20:
            med = X[A].median()
            XA, XJ = X[A].fillna(med).fillna(0), X[J].fillna(med).fillna(0)
            nets = ynet[J]
            for tau in TAUS:
                y = (ynet > tau).astype(int)
                if y[A].sum() >= 30:
                    p = (RandomForestClassifier(n_estimators=300, min_samples_leaf=20, n_jobs=-1, random_state=0)
                         .fit(XA, y[A]).predict_proba(XJ)[:, 1])
                else:
                    p = np.zeros(J.sum())
                scores[tau].extend(p.tolist())
                o = np.argsort(-p, kind="stable")
                for k in CUTS:
                    v = nets[o[:max(3, int(len(nets) * k))]]
                    tot[(tau, k)].extend(v.tolist())
                    fen[(tau, k)].append(v.mean())
            nets_all.extend(nets.tolist())
            wid.extend([w] * len(nets))
            w += 1
        c += dt.timedelta(hours=6)

    print("CIBLE x SELECTIVITE, %d fenetres, cout %.2f pt" % (w, 100 * COUT))
    print("   %6s %5s %5s %9s %8s %9s %6s %6s %7s" % ("cible", "garde", "n", "net/tick", "EUR", "sans3", "gagn", "cata", "fen>0"))
    for tau in TAUS:
        for k in CUTS:
            v = np.array(tot[(tau, k)])
            s = np.sort(v)
            print("   >%3.0f%% %4.0f%% %5d %+8.2f%% %+7.0f %+8.2f%% %5.0f%% %5.0f%%   %d/%d" % (
                100 * tau, 100 * k, len(v), 100 * v.mean(), MISE * v.sum(), 100 * s[:-3].mean(),
                100 * (v > 0).mean(), 100 * (v < -0.5).mean(), sum(1 for x in fen[(tau, k)] if x > 0), w))
        print()

    p0, n = np.array(scores[0.0]), np.array(nets_all)
    print("CALIBRATION de la cible > 0 : probabilite predite contre realite")
    for lo, hi in ((0.0, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.01)):
        m = (p0 >= lo) & (p0 < hi)
        if m.sum() >= 10:
            v = n[m]
            print("   p in [%.1f,%.1f)  n=%4d  gagnants %3.0f %%  net %+6.2f %%  gain moyen des gagnants %+5.1f %%"
                  "  perte moyenne des perdants %+6.1f %%"
                  % (lo, hi, m.sum(), 100 * (v > 0).mean(), 100 * v.mean(),
                     100 * v[v > 0].mean() if (v > 0).any() else 0, 100 * v[v <= 0].mean() if (v <= 0).any() else 0))

    if NULLS:
        wid = np.array(wid)
        rng = np.random.default_rng(2)
        best = []
        P = {tau: np.array(scores[tau]) for tau in TAUS}
        for _ in range(NULLS):
            npm = n.copy()
            for ww in range(w):
                idx = np.where(wid == ww)[0]
                npm[idx] = n[idx][rng.permutation(len(idx))]
            bt = []
            for tau in TAUS:
                for k in CUTS:
                    acc = []
                    for ww in range(w):
                        idx = np.where(wid == ww)[0]
                        o = np.argsort(-P[tau][idx], kind="stable")
                        acc.extend(npm[idx][o[:max(3, int(len(idx) * k))]].tolist())
                    bt.append(np.mean(acc))
            best.append(max(bt))
        vrai = max(np.mean(v) for v in tot.values())
        k_sup = sum(1 for b in best if b >= vrai)
        print()
        print("BARRE DU HASARD (%d permutations dans chaque fenetre, meilleure des %d cellules) :" % (NULLS, len(tot)))
        print("   95e centile %+.2f %% · max %+.2f %% · vrai meilleur %+.2f %% · tirages >= vrai : %d/%d (p ~ %.3f)"
              % (100 * np.quantile(best, 0.95), 100 * max(best), 100 * vrai, k_sup, NULLS, (k_sup + 1) / (NULLS + 1)))


if __name__ == "__main__":
    main()
