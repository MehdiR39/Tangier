"""DECIDER A 75 s AVEC TOUTE LA PREMIERE MINUTE, contre decider a 45 s avec la moitie.

MIDO, 18/09 23h30 : « fais le truc qui me donne le plus de chances de gagner de l argent ».

D OU CA VIENT. Le modele qui classe le mieux (§3.139) s appuie d abord sur les TRANSACTIONS des
premieres secondes. Le collecteur les lit a 70 s, d un coup, pour toute la premiere minute. A 45 s,
en production, ces donnees n existent pas encore ; a 75 s elles existent TELLES QUELLES, sans rien
construire. Et deux faits mesures vont dans le meme sens : sortir plus tard rapporte plus (§3.126,
287 s > 240 s sur tous les tickets), et le modele reconnait des SURVIVANTS -- qui se voient mieux
apres la premiere minute qu au milieu.

CE QU ON COMPARE, memes tickets, meme foret (gain, 25 variables choisies sur le passe), memes
fenetres de 6 h, cout 6,55 :
    45 s : variables a 45 s (transactions <= 45 s), entree au dernier prix <= 47 s
    75 s : transactions <= 60 s (toute la minute), entree au dernier prix <= 77 s
  chacune avec sortie au premier prix >= 240 s et >= 287 s, a 5 / 10 / 20 / 30 % gardes.

CONVENTION D EXECUTABILITE : entree au dernier prix OBSERVE avant l instant d achat, sortie au
premier prix OBSERVE apres l horizon. Jamais un prix interpole.

BARRE DU HASARD : 200 permutations des resultats dans chaque fenetre, meilleure cellule de la
variante 75 s retenue a chaque fois.
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tout_table  # noqa: E402

DOSSIER = "/app/data/recherche/tout"
INTEL = "/app/db/intel.sqlite"
COUT = float(os.environ.get("COUT_MESURE", "0.0655"))
MISE = 20.0
CUTS = (0.05, 0.10, 0.20, 0.30)
NULLS = int(os.environ.get("NULLS", "200"))
N_VAR = 25


def net(r):
    return (1.0 + r) * (1.0 - COUT) - 1.0


def prix(df: pd.DataFrame, entree: int, sorties=(240, 287)) -> pd.DataFrame:
    """Entree au dernier prix <= entree, sortie au premier prix >= H, depuis solana_prix_chaine."""
    c = sqlite3.connect("file:%s?mode=ro" % INTEL, uri=True)
    out = {h: [] for h in sorties}
    for pair in df["pair"]:
        pts = c.execute("SELECT age_s, prix_sol FROM solana_prix_chaine WHERE pair_id = ? AND prix_sol > 0 ORDER BY age_s",
                        (pair,)).fetchall()
        avant = [p for a, p in pts if a is not None and a <= entree]
        p0 = avant[-1] if avant else None
        for h in sorties:
            apres = [p for a, p in pts if a is not None and a >= h]
            out[h].append((apres[0] / p0 - 1.0) if (p0 and apres) else np.nan)
    for h in sorties:
        df["r%d_%d" % (entree, h)] = out[h]
    return df


def marche(df: pd.DataFrame, cols: list[str], y_net: dict[int, np.ndarray], t: np.ndarray):
    tz = dt.timezone(dt.timedelta(hours=2))
    c, fin = dt.datetime(2026, 9, 16, 0, 0, tzinfo=tz), dt.datetime(2026, 9, 18, 18, 0, tzinfo=tz)
    tot = {(h, k): [] for h in y_net for k in CUTS}
    scores, wid, w = [], [], 0
    X = df[cols].apply(pd.to_numeric, errors="coerce").astype(float)
    cible = (y_net[240] > 0).astype(int)          # la cible reste « gagnant a 240 s », comme le gel
    while c < fin:
        c0, c1 = c.timestamp(), (c + dt.timedelta(hours=6)).timestamp()
        A, J = (t < c0) & ~np.isnan(y_net[240]), (t >= c0) & (t < c1) & ~np.isnan(y_net[240])
        if A.sum() >= 150 and J.sum() >= 20:
            med = X[A].median()
            XA, XJ = X[A].fillna(med).fillna(0), X[J].fillna(med).fillna(0)
            rf0 = RandomForestClassifier(n_estimators=200, min_samples_leaf=20, n_jobs=-1, random_state=0).fit(XA, cible[A])
            garde = [g for _, g in sorted(zip(rf0.feature_importances_, cols), reverse=True)[:N_VAR]]
            rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=20, n_jobs=-1, random_state=0).fit(XA[garde], cible[A])
            p = rf.predict_proba(XJ[garde])[:, 1]
            o = np.argsort(-p, kind="stable")
            for h in y_net:
                nets = y_net[h][J]
                for k in CUTS:
                    v = nets[o[:max(3, int(len(nets) * k))]]
                    tot[(h, k)].extend(v[~np.isnan(v)].tolist())
            scores.extend(p.tolist())
            wid.extend([w] * int(J.sum()))
            w += 1
        c += dt.timedelta(hours=6)
    return tot, np.array(scores), np.array(wid), w


def montre(titre: str, tot: dict) -> None:
    print(titre)
    print("   %6s %5s %5s %9s %8s %9s %6s %6s" % ("sortie", "garde", "n", "net/tick", "EUR", "sans3", "gagn", "cata"))
    for (h, k), v in tot.items():
        v = np.array(v)
        if len(v) < 5:
            continue
        s = np.sort(v)
        print("   %5ds %4.0f%% %5d %+8.2f%% %+7.0f %+8.2f%% %5.0f%% %5.0f%%" % (
            h, 100 * k, len(v), 100 * v.mean(), MISE * v.sum(), 100 * s[:-3].mean(), 100 * (v > 0).mean(), 100 * (v < -0.5).mean()))
    print()


def main() -> None:
    df = pd.read_pickle(os.path.join(DOSSIER, "table.pkl"))
    variables = [v for v in df.attrs["VARIABLES"] if v != "tg_poste"]
    df = df[(df["eligible"] == 1) & df["v1_n_achats"].notna()].sort_values("t_dec").reset_index(drop=True)
    t = df["t_dec"].to_numpy()

    # ---- 45 s : la table telle quelle (transactions <= 45 s, entree <= 47 s)
    y45 = {240: net(df["ret_240"].to_numpy(dtype=float)), 287: net(df["ret_287"].to_numpy(dtype=float))}
    cols45 = [v for v in variables if df[v].notna().sum() >= 100 and df[v].nunique(dropna=True) >= 2]

    # ---- 75 s : transactions <= 60 s (toute la minute) et entree <= 77 s
    tout_table.AGE_V1 = 60
    base = df.drop(columns=[c for c in df.columns if c.startswith("v1_")])
    df75 = tout_table.transactions(base)
    df75 = prix(df75, 77)
    y75 = {240: net(df75["r77_240"].to_numpy(dtype=float)), 287: net(df75["r77_287"].to_numpy(dtype=float))}
    cols75 = [v for v in variables if v in df75.columns and df75[v].notna().sum() >= 100 and df75[v].nunique(dropna=True) >= 2]
    print("%d tickets · 45 s : %d variables · 75 s : %d variables · cout %.2f pt" % (len(df), len(cols45), len(cols75), 100 * COUT))
    print("   temoin 45 s -> 240 : %+.2f %%   · temoin 77 s -> 240 : %+.2f %%   · temoin 77 s -> 287 : %+.2f %%"
          % (100 * np.nanmean(y45[240]), 100 * np.nanmean(y75[240]), 100 * np.nanmean(y75[287])))
    print()

    tot45, _, _, _ = marche(df, cols45, y45, t)
    montre("DECISION A 45 s (transactions <= 45 s, entree <= 47 s)", tot45)
    tot75, sc, wid, w = marche(df75, cols75, y75, t)
    montre("DECISION A 75 s (transactions <= 60 s, entree <= 77 s)", tot75)

    if NULLS:
        n240 = y75[240]
        rng = np.random.default_rng(5)
        # on ne permute que les tickets juges (ceux qui ont un score), fenetre par fenetre
        J = np.zeros(len(n240), dtype=bool)
        # reconstruire l ordre des tickets juges : marche() les a pris dans l ordre chronologique
        idx_j = np.where(~np.isnan(n240))[0]
        # meme selection que marche(): tickets des fenetres avec assez de donnees ; on approxime en
        # utilisant les scores dans l ordre -- la longueur doit correspondre
        if len(sc) != len(wid):
            print("(barre du hasard : incoherence de taille, ignoree)")
            return
        best, vrai = [], max(np.mean(v) for v in tot75.values() if len(v) >= 5)
        # les nets juges, dans le meme ordre que sc/wid
        tz = dt.timezone(dt.timedelta(hours=2))
        c, fin = dt.datetime(2026, 9, 16, 0, 0, tzinfo=tz), dt.datetime(2026, 9, 18, 18, 0, tzinfo=tz)
        nets_j = {240: [], 287: []}
        while c < fin:
            c0, c1 = c.timestamp(), (c + dt.timedelta(hours=6)).timestamp()
            A, Jm = (t < c0) & ~np.isnan(n240), (t >= c0) & (t < c1) & ~np.isnan(n240)
            if A.sum() >= 150 and Jm.sum() >= 20:
                nets_j[240].extend(y75[240][Jm].tolist())
                nets_j[287].extend(y75[287][Jm].tolist())
            c += dt.timedelta(hours=6)
        N = {h: np.array(v) for h, v in nets_j.items()}
        for _ in range(NULLS):
            perm = {h: N[h].copy() for h in N}
            for ww in range(w):
                ix = np.where(wid == ww)[0]
                pr = rng.permutation(len(ix))
                for h in N:
                    perm[h][ix] = N[h][ix][pr]
            bt = []
            for h in N:
                for k in CUTS:
                    acc = []
                    for ww in range(w):
                        ix = np.where(wid == ww)[0]
                        o = np.argsort(-sc[ix], kind="stable")
                        v = perm[h][ix][o[:max(3, int(len(ix) * k))]]
                        acc.extend(v[~np.isnan(v)].tolist())
                    bt.append(np.mean(acc) if acc else -9)
            best.append(max(bt))
        k_sup = sum(1 for b in best if b >= vrai)
        print("BARRE DU HASARD, variante 75 s (%d permutations, meilleure des 8 cellules) :" % NULLS)
        print("   95e centile %+.2f %% · max %+.2f %% · vrai meilleur %+.2f %% · tirages >= vrai : %d/%d (p ~ %.3f)"
              % (100 * np.quantile(best, 0.95), 100 * max(best), 100 * vrai, k_sup, NULLS, (k_sup + 1) / (NULLS + 1)))


if __name__ == "__main__":
    main()
