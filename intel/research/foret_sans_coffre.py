"""LA FORET TRIE-T-ELLE MIEUX SANS LA TAILLE DU COFFRE ? Le test que le carnet reel a impose.

CE QUE MIDO A VU, 19/09 au soir, sur la page de suivi : la foret ecarte des jetons a +14,2 % de
rendement brut et garde ceux a +1,3 %. Elle trie a l envers sur le HAUT de la distribution --
9 fusees ecartees sur 13.

LE MECANISME, mesure sur les 466 tickets du carnet reel :
    tickets GARDES   coffre median 128 SOL
    tickets ECARTES  coffre median  74 SOL
    les fusees (> +50 %)          coffre median  74 SOL
La foret s appuie d abord sur `q`, la taille du coffre (§3.154 : 86 % de son modele est de la
liquidite, et `cout` est une fonction directe de `q`). Elle prefere donc les gros pools. Or les
fusees naissent dans les PETITS. En preferant les gros, elle jette mecaniquement ce qui rapporte.

Et ce n est pas un probleme de recolte : sur les 16 fusees qu on a achetees, on a encaisse 84,1 %
pour un mouvement de 88,4 %, soit 95 %. Elles sont parfaitement encaissables, meme a 75 SOL.

CE QU ON COMPARE, en marche avant, memes coupes de 6 h, meme cout, meme proportion gardee :
    toutes          les 19 variables de prix, comme la foret en service
    sans coffre     les memes SANS `q` ni `cout` -- on lui retire la taille du pool
    sans liquidite  sans `q`, `cout`, `q_croiss`, `vol` -- toute la famille
    petits pools    trier sur `q` CROISSANT : prendre les PLUS PETITS, l inverse de `q seul`
et deux temoins : tout prendre, et `q seul` (les plus gros), la strategie implicite d aujourd hui.

ON COMPTE AUSSI LES FUSEES. Un modele peut gagner en euros et rater les fusees, ou l inverse :
c est la question de Mido, et la moyenne seule n y repond pas.

BARRE DU HASARD sur le MEILLEUR des variantes -- la procedure entiere, choix du jeu de variables
compris (regle de la loi du maximum).
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
COUT = float(os.environ.get("COUT_MESURE", "0.0371"))
MISE = 20.0
GARDE = 0.80
NULLS = int(os.environ.get("NULLS", "60"))
PRIX = ["px_n_lect", "px_ret_naiss", "px_dd_max", "px_depuis_min", "px_t_depuis_max", "px_vol",
        "q", "px_q_croiss", "px_ret_10", "px_ret_30", "px_ret_60", "px_ret_120",
        "px_q_croiss_30", "px_q_croiss_60", "px_lancements_10min", "px_heure", "V", "px_A",
        "px_cout"]


def net(r):
    return (1.0 + r) * (1.0 - COUT) - 1.0


def main() -> None:
    df = pd.read_pickle(os.path.join(DOSSIER, "table.pkl"))
    df = df[(df["eligible"] == 1) & df["ret_240"].notna()]
    df = df.sort_values("t_dec").reset_index(drop=True)
    prix = [c for c in PRIX if c in df.columns and df[c].notna().sum() >= 100]
    coffre = {"q", "px_cout"}
    liquidite = coffre | {"px_q_croiss", "px_vol", "px_q_croiss_30", "px_q_croiss_60"}
    jeux = {
        "toutes (la foret en service)": prix,
        "SANS le coffre": [c for c in prix if c not in coffre],
        "SANS la liquidite": [c for c in prix if c not in liquidite],
    }
    y_net = net(df["ret_240"].to_numpy(dtype=float))
    y_vid = (y_net <= -0.5).astype(int)
    brut = 100 * df["ret_240"].to_numpy(dtype=float)
    t = df["t_dec"].to_numpy()
    q = pd.to_numeric(df["q"], errors="coerce").to_numpy(dtype=float)
    print("%d tickets · cout %.2f pt · on garde %.0f %% · %d fusees (> +50 %%)"
          % (len(df), 100 * COUT, 100 * GARDE, int((brut > 50).sum())))
    print()

    tz = dt.timezone(dt.timedelta(hours=2))
    DEBUT = dt.datetime(2026, 9, 16, 0, 0, tzinfo=tz)
    FIN = dt.datetime(2026, 9, 19, 12, 0, tzinfo=tz)

    def marche(yv, yn):
        """Renvoie {nom: (nets gardes, bruts gardes)} et le temoin."""
        tot = {k: ([], []) for k in list(jeux) + ["q seul : LES PLUS GROS", "q seul : LES PLUS PETITS"]}
        tem = ([], [])
        c = DEBUT
        while c < FIN:
            c0, c1 = c.timestamp(), (c + dt.timedelta(hours=6)).timestamp()
            A, J = t < c0, (t >= c0) & (t < c1)
            c += dt.timedelta(hours=6)
            if A.sum() < 150 or J.sum() < 20:
                continue
            nets, bruts = yn[J], brut[J]
            k = max(5, int(len(nets) * GARDE))
            tem[0].extend(nets.tolist())
            tem[1].extend(bruts.tolist())
            qj = np.nan_to_num(q[J], nan=-1.0)
            for nom, ordre in (("q seul : LES PLUS GROS", np.argsort(-qj)),
                               ("q seul : LES PLUS PETITS", np.argsort(qj))):
                tot[nom][0].extend(nets[ordre[:k]].tolist())
                tot[nom][1].extend(bruts[ordre[:k]].tolist())
            for nom, cols in jeux.items():
                X = df[cols].apply(pd.to_numeric, errors="coerce").astype(float)
                med = X[A].median()
                rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=20, n_jobs=-1,
                                            random_state=0).fit(X[A].fillna(med).fillna(0), yv[A])
                p = rf.predict_proba(X[J].fillna(med).fillna(0))[:, 1]
                o = np.argsort(p, kind="stable")[:k]
                tot[nom][0].extend(nets[o].tolist())
                tot[nom][1].extend(bruts[o].tolist())
        return tot, tem

    tot, tem = marche(y_vid, y_net)
    ref = np.array(tem[0])
    refb = np.array(tem[1])
    n_fus_ref = int((refb > 50).sum())
    print("   %-30s %6s %11s %11s %9s %11s" %
          ("", "n", "EUR/ticket", "vs temoin", "fusees", "part gardee"))
    print("   %-30s %6d %+10.3f %+10.3f %9d %10.0f %%" %
          ("TEMOIN : tout prendre", len(ref), MISE * ref.mean(), 0.0, n_fus_ref, 100.0))
    res = {}
    for nom, (v, b) in tot.items():
        v, b = np.array(v), np.array(b)
        if len(v) < 20:
            continue
        d = MISE * (v.mean() - ref.mean())
        res[nom] = d
        nf = int((b > 50).sum())
        print("   %-30s %6d %+10.3f %+10.3f %9d %10.0f %%"
              % (nom, len(v), MISE * v.mean(), d, nf, 100.0 * nf / max(1, n_fus_ref)))
    print()
    print("   « part gardee » = la fraction des fusees du marche que la strategie a prises.")
    print("   On garde 80 %% des tickets : une strategie NEUTRE en garderait donc 80 %% aussi.")

    if NULLS and res:
        print()
        print("BARRE DU HASARD : %d marches avant permutees, meilleur des %d jeux de variables"
              % (NULLS, len(jeux)))
        rng = np.random.default_rng(17)
        maxs = []
        for i in range(NULLS):
            perm = rng.permutation(len(y_net))
            tp, rt = marche(y_vid[perm], y_net[perm])
            r = np.array(rt[0])
            maxs.append(max(MISE * (np.array(tp[k][0]).mean() - r.mean()) for k in jeux))
            if (i + 1) % 15 == 0:
                print("   %d/%d · meilleur du hasard %+0.3f" % (i + 1, NULLS, max(maxs)), flush=True)
        meilleur = max((k for k in jeux), key=lambda k: res.get(k, -9e9))
        vrai = res[meilleur]
        ks = sum(1 for m in maxs if m >= vrai)
        print("   -> meilleur jeu « %s » a %+.3f · %d tirages sur %d font aussi bien (p ~ %.3f)"
              % (meilleur, vrai, ks, len(maxs), (ks + 1) / (len(maxs) + 1)))


if __name__ == "__main__":
    main()
