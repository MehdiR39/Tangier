"""AMELIORER LA FORET DE VIDAGE : lui donner le FLUX D ORDRES, pas plus de variables de prix.

MIDO, 19/09 11h30 : « vu tes remarques sur la foret, peut-on l ameliorer ? »

CE QUE L ANALYSE A MONTRE (§3.154). La foret en service tient a 86 % sur la LIQUIDITE -- `q`,
`vol`, `cout`, `q_croiss` -- et les rendements (`ret_10/60/120`, `dd_max`) ne pesent rien. Pire :
`cout` est une fonction directe de `q` (impact = 2 x mise / (q + V)), donc ces quatre variables ne
sont pas quatre informations mais une seule vue sous quatre angles. Et trier sur `q` SEUL capture
95 % de son avantage (+0,646 contre +0,677 par ticket). Ajouter des variables de prix ne peut donc
rien apporter : il faut une information d une AUTRE nature.

CE QU ON AJOUTE, et pourquoi c est autre chose. Le flux d ordres des 45 premieres secondes
(`v1_enregistreur`) : qui achete, combien, combien de vendeurs, combien de portefeuilles jamais vus,
la concentration des achats. La marche avant du 18/09 au soir a mesure que cette famille porte 44 %
de l importance par permutation d une foret sur les 107 variables -- devant le prix (14 %). Elle n a
jamais ete donnee a un modele de VIDAGE.

TROIS MODELES, JUGES EN MARCHE AVANT, jamais sur les donnees qui les ont entraines :
    prix       les 19 variables de la foret en service              (la reference)
    flux       les 16 variables de transactions SEULES              (l information est-elle la ?)
    les deux   prix + flux                                          (s ajoutent-elles ?)
et deux temoins qui ne s entrainent sur rien : tout prendre, et trier sur `q` seul.

PROTOCOLE. Coupes de 6 h du 16/09 au 18/09 18h ; a chaque coupe, entrainement sur tout ce qui
precede, jugement sur les 6 h suivantes, on garde la meme PROPORTION que la foret en service
(80 %, son seuil p80) pour que la comparaison soit a effectif egal. Cout 2,98 pt (caution recuperee,
priorite d achat a 100 000). Cible : vidage = net <= -50 %.

BARRE DU HASARD : NULLS marches avant avec les resultats permutes dans chaque fenetre, en retenant
a chaque fois LE MEILLEUR des trois modeles -- le maximum sous permutation de la procedure entiere.
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
COUT = float(os.environ.get("COUT_MESURE", "0.0298"))
MISE = 20.0
GARDE = 0.80                      # la proportion que garde la foret en service (seuil p80)
NULLS = int(os.environ.get("NULLS", "100"))
PRIX = ["px_n_lect", "px_ret_naiss", "px_dd_max", "px_depuis_min", "px_t_depuis_max", "px_vol",
        "q", "px_q_croiss", "px_ret_10", "px_ret_30", "px_ret_60", "px_ret_120",
        "px_q_croiss_30", "px_q_croiss_60", "px_lancements_10min", "px_heure", "V", "px_A"]


def net(r):
    return (1.0 + r) * (1.0 - COUT) - 1.0


def main() -> None:
    df = pd.read_pickle(os.path.join(DOSSIER, "table.pkl"))
    df = df[(df["eligible"] == 1) & df["ret_240"].notna() & df["v1_n_achats"].notna()]
    df = df.sort_values("t_dec").reset_index(drop=True)
    prix = [c for c in PRIX if c in df.columns and df[c].notna().sum() >= 100]
    flux = [c for c in df.columns if c.startswith("v1_") and df[c].notna().sum() >= 100
            and pd.to_numeric(df[c], errors="coerce").nunique(dropna=True) >= 2]
    jeux = {"prix (la reference)": prix, "flux d ordres SEUL": flux, "prix + flux": prix + flux}
    y_net = net(df["ret_240"].to_numpy(dtype=float))
    y_vid = (y_net <= -0.5).astype(int)
    t = df["t_dec"].to_numpy()
    print("%d tickets · prix %d variables · flux %d variables · cout %.2f pt · on garde %.0f %%"
          % (len(df), len(prix), len(flux), 100 * COUT, 100 * GARDE))
    print()

    def marche(yv, yn, verbeux=True):
        tz = dt.timezone(dt.timedelta(hours=2))
        c, fin = dt.datetime(2026, 9, 16, 0, 0, tzinfo=tz), dt.datetime(2026, 9, 18, 18, 0, tzinfo=tz)
        tot = {k: [] for k in jeux}
        tot["tout prendre"] = []
        tot["q seul (le plus gros)"] = []
        while c < fin:
            c0, c1 = c.timestamp(), (c + dt.timedelta(hours=6)).timestamp()
            A, J = t < c0, (t >= c0) & (t < c1)
            if A.sum() >= 150 and J.sum() >= 20:
                nets = yn[J]
                k = max(5, int(len(nets) * GARDE))
                tot["tout prendre"].extend(nets.tolist())
                qj = pd.to_numeric(df.loc[J, "q"], errors="coerce").to_numpy(dtype=float)
                tot["q seul (le plus gros)"].extend(nets[np.argsort(-np.nan_to_num(qj))[:k]].tolist())
                for nom, cols in jeux.items():
                    X = df[cols].apply(pd.to_numeric, errors="coerce").astype(float)
                    med = X[A].median()
                    rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=20, n_jobs=-1,
                                                random_state=0).fit(X[A].fillna(med).fillna(0), yv[A])
                    p = rf.predict_proba(X[J].fillna(med).fillna(0))[:, 1]
                    tot[nom].extend(nets[np.argsort(p, kind="stable")[:k]].tolist())
            c += dt.timedelta(hours=6)
        return tot

    tot = marche(y_vid, y_net)
    ref = np.array(tot["tout prendre"])
    print("   %-24s %6s %11s %11s %11s" % ("", "n", "EUR/ticket", "vs temoin", "sans 3 meil."))
    res = {}
    for nom, v in tot.items():
        v = np.array(v)
        if len(v) < 20:
            continue
        s = np.sort(v)
        d = MISE * (v.mean() - ref.mean())
        res[nom] = d
        print("   %-24s %6d %+10.3f %+10.3f %+10.3f" % (nom, len(v), MISE * v.mean(), d,
                                                        MISE * (s[:-3].mean() - ref.mean())))
    if NULLS:
        print()
        print("BARRE DU HASARD : %d marches avant, resultats permutes, MEILLEUR des trois modeles retenu" % NULLS)
        rng = np.random.default_rng(11)
        maxs = []
        for i in range(NULLS):
            perm = rng.permutation(len(y_net))
            tp = marche(y_vid[perm], y_net[perm], verbeux=False)
            r = np.array(tp["tout prendre"])
            maxs.append(max(MISE * (np.array(tp[k]).mean() - r.mean()) for k in jeux))
            if (i + 1) % 10 == 0:
                print("   %d/%d tirages · meilleur du hasard jusqu ici %+0.3f" % (i + 1, NULLS, max(maxs)), flush=True)
        vrai = max(res[k] for k in jeux)
        k_sup = sum(1 for m in maxs if m >= vrai)
        print("   -> vrai meilleur %+.3f EUR/ticket · %d tirages sur %d font aussi bien (p ~ %.3f)"
              % (vrai, k_sup, NULLS, (k_sup + 1) / (NULLS + 1)))


if __name__ == "__main__":
    main()
