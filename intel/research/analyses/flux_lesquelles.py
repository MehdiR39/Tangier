"""QUELLES variables de flux portent le signal -- et lesquelles le moteur peut-il voir a 45 s ?

§3.155 a montre que le flux d ordres bat le prix (+0,430 EUR/ticket contre le temoin, p ~ 0,020).
Mais `v1_enregistreur` ne va chercher les transactions du pool qu a 70 s, APRES notre decision a
45 s : ces 16 variables existent pour la recherche, pas en direct. Avant de promettre un gel il faut
savoir ce qu il faudrait aller chercher.

DEUX FAMILLES, et elles ne coutent pas la meme chose :
  DEDUCTIBLE   ce qui se lit dans la suite des soldes du coffre, que `solana_prix_chaine` enregistre
               deja toutes les quelques secondes : nombre de mouvements, SOL entre, SOL sorti, ratio.
               Zero appel supplementaire, zero latence.
  PAR TRANSACTION  ce qui exige de savoir QUI signe : acheteurs uniques, vendeurs sans achat, gini,
               robots, part des portefeuilles jamais vus. Un appel Helius au moment de decider.

On mesure l importance PAR PERMUTATION (regle 17 : jamais l impurete quand on melange continu et
binaire), hors echantillon, en marche avant -- le meme protocole que foret_vidage_plus.py, sinon les
chiffres ne sont pas comparables a ceux du journal.
"""
from __future__ import annotations

import datetime as dt
import os
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")
DOSSIER = "/app/data/recherche/tout"
COUT = float(os.environ.get("COUT_MESURE", "0.0298"))
MISE = 20.0
GARDE = 0.80
TIRAGES = 12

# Ce que la suite des soldes du coffre donne sans rien demander de plus a Helius.
DEDUCTIBLE = {"v1_n_achats", "v1_n_ventes", "v1_sol_achats", "v1_sol_ventes", "v1_ratio_ventes",
              "v1_premier_achat", "v1_achat_median", "v1_achat_max"}


def net(r):
    return (1.0 + r) * (1.0 - COUT) - 1.0


def main() -> None:
    df = pd.read_pickle(os.path.join(DOSSIER, "table.pkl"))
    df = df[(df["eligible"] == 1) & df["ret_240"].notna() & df["v1_n_achats"].notna()]
    df = df.sort_values("t_dec").reset_index(drop=True)
    flux = [c for c in df.columns if c.startswith("v1_") and df[c].notna().sum() >= 100
            and pd.to_numeric(df[c], errors="coerce").nunique(dropna=True) >= 2]
    y_net = net(df["ret_240"].to_numpy(dtype=float))
    y_vid = (y_net <= -0.5).astype(int)
    t = df["t_dec"].to_numpy()
    X = df[flux].apply(pd.to_numeric, errors="coerce").astype(float)

    # --- importance par permutation, hors echantillon, agregee sur les fenetres de marche avant ---
    tz = dt.timezone(dt.timedelta(hours=2))
    c = dt.datetime(2026, 9, 16, 0, 0, tzinfo=tz)
    fin = dt.datetime(2026, 9, 18, 18, 0, tzinfo=tz)
    rng = np.random.default_rng(7)
    pertes = {v: [] for v in flux}
    aucs = []
    while c < fin:
        c0, c1 = c.timestamp(), (c + dt.timedelta(hours=6)).timestamp()
        A, J = t < c0, (t >= c0) & (t < c1)
        c += dt.timedelta(hours=6)
        if A.sum() < 150 or J.sum() < 20 or len(set(y_vid[J])) < 2:
            continue
        med = X[A].median()
        XA, XJ = X[A].fillna(med).fillna(0), X[J].fillna(med).fillna(0)
        rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=20, n_jobs=-1,
                                    random_state=0).fit(XA, y_vid[A])
        base = roc_auc_score(y_vid[J], rf.predict_proba(XJ)[:, 1])
        aucs.append(base)
        for v in flux:
            d = []
            for _ in range(TIRAGES):
                Z = XJ.copy()
                Z[v] = rng.permutation(Z[v].to_numpy())
                d.append(base - roc_auc_score(y_vid[J], rf.predict_proba(Z)[:, 1]))
            pertes[v].append(float(np.mean(d)))

    print("MARCHE AVANT : %d fenetres · AUC hors echantillon %.3f (min %.3f, max %.3f)"
          % (len(aucs), np.mean(aucs), min(aucs), max(aucs)))
    print()
    moy = {v: float(np.mean(p)) for v, p in pertes.items() if p}
    tot = sum(max(0.0, x) for x in moy.values()) or 1.0
    print("IMPORTANCE PAR PERMUTATION (perte d AUC quand on brouille la variable)")
    print("   %-24s %10s %6s   %s" % ("", "perte AUC", "part", "disponible a 45 s ?"))
    for v, x in sorted(moy.items(), key=lambda kv: -kv[1]):
        ou = "coffre (gratuit)" if v in DEDUCTIBLE else "APPEL par transaction"
        print("   %-24s %+9.4f %5.0f %%   %s" % (v, x, 100 * max(0.0, x) / tot, ou))
    part_d = sum(max(0.0, moy[v]) for v in moy if v in DEDUCTIBLE) / tot
    print()
    print("   -> deductible du coffre : %.0f %% de l importance · par transaction : %.0f %%"
          % (100 * part_d, 100 * (1 - part_d)))

    # --- ce qui compte vraiment : l argent, avec chaque moitie SEULE, en marche avant ---
    ded = [v for v in flux if v in DEDUCTIBLE]
    tx = [v for v in flux if v not in DEDUCTIBLE]
    jeux = {"flux COMPLET (16)": flux, "coffre seul (%d)" % len(ded): ded,
            "par transaction seul (%d)" % len(tx): tx}
    tot2 = {k: [] for k in jeux}
    tot2["tout prendre"] = []
    c = dt.datetime(2026, 9, 16, 0, 0, tzinfo=tz)
    while c < fin:
        c0, c1 = c.timestamp(), (c + dt.timedelta(hours=6)).timestamp()
        A, J = t < c0, (t >= c0) & (t < c1)
        c += dt.timedelta(hours=6)
        if A.sum() < 150 or J.sum() < 20:
            continue
        nets = y_net[J]
        k = max(5, int(len(nets) * GARDE))
        tot2["tout prendre"].extend(nets.tolist())
        for nom, cols in jeux.items():
            Z = df[cols].apply(pd.to_numeric, errors="coerce").astype(float)
            med = Z[A].median()
            rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=20, n_jobs=-1,
                                        random_state=0).fit(Z[A].fillna(med).fillna(0), y_vid[A])
            p = rf.predict_proba(Z[J].fillna(med).fillna(0))[:, 1]
            tot2[nom].extend(nets[np.argsort(p, kind="stable")[:k]].tolist())
    print()
    print("EN ARGENT : que vaut chaque moitie SEULE (marche avant, cout %.2f pt, on garde 80 %%)" % (100 * COUT))
    ref = np.array(tot2["tout prendre"])
    print("   %-26s %6s %11s %11s" % ("", "n", "EUR/ticket", "vs temoin"))
    for nom, v in tot2.items():
        v = np.array(v)
        print("   %-26s %6d %+10.3f %+10.3f" % (nom, len(v), MISE * v.mean(),
                                                MISE * (v.mean() - ref.mean())))


if __name__ == "__main__":
    main()
