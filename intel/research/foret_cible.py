"""LA CIBLE EST-ELLE LE DEFAUT ? « ne pas s effondrer » contre « etre gagnant », toutes choses egales.

MIDO, 20/09 au matin, devant la courbe de FORET REENTRAINEE 6h : « bizarre que la foret non
reentrainee fasse mieux et que l entrainee crache en continu, c est une pente libre, il y a un truc
qui est faux dans tout ca ». Il avait raison, et le diagnostic est arithmetique, pas statistique.

CE QUI A ETE MESURE SUR LE CARNET PAPIER (185 tickets juges, 20/09 11h) : le cinquieme que le modele
declare le PLUS SUR ne contient que 9 % de vidages contre 18 % partout -- il fait donc parfaitement
son travail -- et perd -1,310 EUR/ticket. Parce que ces jetons-la bougent de 3,1 % en median quand
le peage est de 3,71 %. Le moyen le plus sur de ne pas s effondrer, c est de ne pas bouger ; un jeton
immobile paie le cout et rien d autre. Le cinquieme suivant bouge de 19 %, n a que 4 % de vidages,
et rapporte +1,711.

L ASYMETRIE, et c est tout le sujet :
    « gagnant net »       = ca monte plus que le cout  ET  ca ne s effondre pas (un jeton effondre
                            n est jamais un gagnant : la protection est comprise dedans)
    « pas de vidage »     =                                ca ne s effondre pas, point
La premiere question est PLUS exigeante que la seconde, pas moins prudente. On demandait moins que
ce qu on voulait.

CE QUE CE TEST TRANCHE. Trois cibles, tout le reste identique -- memes variables, meme moment de
decision, memes tickets, meme marche avant par coupes de 6 h, meme cout, meme facon de decider
(SEUIL ABSOLU, quantile des scores d entrainement : voir §3.158, on ne classe jamais un ticket
contre des voisins pas encore nes).
    VIDAGE     net_240 <= -50 %        la cible de foret_marche ET du modele en production
    GAGNANT    net_240 > 0             la cible de la foret 75s, la seule qui gagne
    FRANC      net_240 > +20 %         « monte nettement » -- au cas ou viser le zero ne suffirait pas
Trois taux de garde chacune (5 %, 20 %, 80 %) pour separer l effet de la CIBLE de l effet de la
SELECTIVITE : foret_marche garde 80 %, la 75s garde 20 %, et les deux differences sont confondues
dans ce que Mido voit sur la page.

BARRE DU HASARD en ECARTS-TYPES et non en euros (§3.158) : une case a 100 tickets a un bruit trois
fois plus large qu une case a 900, et le maximum sur neuf cases serait sinon confisque par la plus
petite. Papier, zero euro, aucune ecriture ailleurs que sur la sortie.
"""
from __future__ import annotations

import datetime as dt
import os
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
DOSSIER = "/app/data/recherche/tout"
COUT = float(os.environ.get("COUT_MESURE", "0.0371"))
MISE = 20.0
PAS_H = 6
NULLS = int(os.environ.get("NULLS", "60"))
TZ = dt.timezone(dt.timedelta(hours=2))
DEBUT = dt.datetime(2026, 9, 16, 0, 0, tzinfo=TZ)
FIN = dt.datetime(2026, 9, 20, 6, 0, tzinfo=TZ)
GARDES = (0.05, 0.20, 0.80)
VARIABLES = ["px_n_lect", "px_ret_naiss", "px_dd_max", "px_depuis_min", "px_t_depuis_max", "px_vol",
             "q", "px_q_croiss", "px_ret_10", "px_ret_30", "px_ret_60", "px_ret_120",
             "px_q_croiss_30", "px_q_croiss_60", "px_lancements_10min", "px_heure", "V", "px_A"]
# nom -> (fonction cible, faut-il garder les probabilites BASSES ?)
#   vidage : on fuit la classe 1, donc on garde les probabilites basses
#   gagnant/franc : on cherche la classe 1, donc on garde les hautes
CIBLES = {"VIDAGE  (net <= -50 %)": (lambda n: n <= -0.50, True),
          "GAGNANT (net > 0)": (lambda n: n > 0.0, False),
          "FRANC   (net > +20 %)": (lambda n: n > 0.20, False)}


def main() -> None:
    from sklearn.ensemble import RandomForestClassifier

    df = pd.read_pickle(os.path.join(DOSSIER, "table.pkl"))
    df = df[(df["eligible"] == 1) & df["ret_240"].notna()].sort_values("t_dec").reset_index(drop=True)
    cols = [c for c in VARIABLES if c in df.columns and df[c].notna().sum() >= 100]
    X = df[cols].apply(pd.to_numeric, errors="coerce").astype(float)
    t = df["t_dec"].to_numpy(dtype=float)
    net0 = (1.0 + df["ret_240"].to_numpy(dtype=float)) * (1.0 - COUT) - 1.0
    print("%d tickets · %d variables · cout %.2f pt · fenetre %s -> %s"
          % (len(df), len(cols), 100 * COUT, DEBUT.strftime("%d/%m %Hh"), FIN.strftime("%d/%m %Hh")),
          flush=True)
    print(flush=True)

    mi_chemin = DEBUT + (FIN - DEBUT) / 2

    def marche(net, moities=False):
        """`moities` : rend en plus, pour chaque case, ses tickets separes en deux moities
        CHRONOLOGIQUES -- le rejeu en deux moities exige par la regle 5 du projet. Une regle qui
        gagne sur l ensemble mais perd sur une moitie n a pas d edge, elle a eu un bon jour (le
        frein : +123 sur une moitie, -81 sur l autre, et il est passe en prod quand meme)."""
        pris = {(c, g): [] for c in CIBLES for g in GARDES}
        deux = {(c, g): ([], []) for c in CIBLES for g in GARDES}
        tem = []
        cur = DEBUT
        while cur < FIN:
            c0 = cur.timestamp()
            c1 = (cur + dt.timedelta(hours=PAS_H)).timestamp()
            cur += dt.timedelta(hours=PAS_H)
            A, J = t < c0, (t >= c0) & (t < c1)
            if A.sum() < 300 or J.sum() < 20:
                continue
            tem.extend(net[J].tolist())
            med = X[A].median()
            XA = X[A].fillna(med).fillna(0.0)
            XJ = X[J].fillna(med).fillna(0.0)
            for nom, (f, bas) in CIBLES.items():
                y = f(net[A]).astype(int)
                if y.sum() < 20 or y.sum() > len(y) - 20:
                    continue                       # classe trop rare pour apprendre quoi que ce soit
                rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=20, n_jobs=-1,
                                            random_state=0).fit(XA, y)
                p_tr = rf.predict_proba(XA)[:, 1]
                p = rf.predict_proba(XJ)[:, 1]
                for g in GARDES:
                    # SEUIL ABSOLU, pris sur l entrainement : decidable ticket par ticket.
                    s = float(np.quantile(p_tr, g if bas else 1.0 - g))
                    garde = (p <= s) if bas else (p >= s)
                    v = net[J][garde].tolist()
                    pris[(nom, g)].extend(v)
                    if moities:
                        deux[(nom, g)][0 if c0 < mi_chemin.timestamp() else 1].extend(v)
        return (pris, np.array(tem), deux) if moities else (pris, np.array(tem))

    def z(v, tm):
        k_, n_ = len(v), len(tm)
        if not 0 < k_ < n_:
            return 0.0
        s = MISE * tm.std(ddof=1)
        return MISE * (v.mean() - tm.mean()) / (s * np.sqrt((n_ - k_) / (n_ * k_)))

    pris, tem, moities = marche(net0, moities=True)
    sigma = MISE * tem.std(ddof=1)
    n_ = len(tem)
    print("   %-26s %6s %11s %11s %9s %11s"
          % ("", "n", "EUR/ticket", "vs temoin", "sig(vs)", "sig(niveau)"))
    print("   %-26s %6d %+10.3f %+10.3f %9s %+11.2f"
          % ("TEMOIN : tout prendre", n_, MISE * tem.mean(), 0.0, "-",
             MISE * tem.mean() / (sigma / np.sqrt(n_))))
    res, zs = {}, {}
    for (nom, g), v in sorted(pris.items()):
        v = np.array(v)
        if len(v) < 10:
            continue
        res[(nom, g)] = MISE * (v.mean() - tem.mean())
        zs[(nom, g)] = z(v, tem)
        niv = MISE * v.mean()
        print("   %-26s %6d %+10.3f %+10.3f %+9.2f %+11.2f"
              % ("%s  %.0f %%" % (nom, 100 * g), len(v), niv, res[(nom, g)], zs[(nom, g)],
                 niv / (sigma / np.sqrt(len(v)))), flush=True)

    if NULLS and res:
        print()
        print("BARRE DU HASARD : %d marches avant permutees, meilleure des %d cases retenue"
              % (NULLS, len(res)), flush=True)
        rng = np.random.default_rng(45)
        maxs = []
        for i in range(NULLS):
            tp, rt = marche(net0[rng.permutation(len(net0))])
            maxs.append(max(z(np.array(v), rt) for _, v in tp.items() if len(v) >= 10))
            if (i + 1) % 15 == 0:
                print("   %d/%d · meilleur du hasard %+0.2f sigma" % (i + 1, NULLS, max(maxs)),
                      flush=True)
        # LE p DE CHAQUE CASE, et pas seulement de la meilleure. La meilleure par sigma est
        # `VIDAGE 80 %` -- qui PERD de l argent. Ne donner que son p repondrait a une question qu on
        # ne se pose pas. Chaque case est comparee au MEME maximum permute : la correction pour
        # avoir regarde neuf fois reste entiere, et elle est conservatrice pour les autres cases.
        print()
        print("   %-26s %8s %9s %11s %13s" % ("", "sigma", "p", "EUR/ticket", "moities (EUR)"))
        for k in sorted(zs, key=lambda x: -zs[x]):
            ks = sum(1 for x in maxs if x >= zs[k])
            a, b = moities.get(k, ([], []))
            ma = MISE * (np.mean(a) - tem.mean()) if len(a) >= 10 else float("nan")
            mb = MISE * (np.mean(b) - tem.mean()) if len(b) >= 10 else float("nan")
            print("   %-26s %+8.2f %9.3f %+11.3f %+6.2f / %+6.2f"
                  % ("%s %.0f %%" % (k[0], 100 * k[1]), zs[k], (ks + 1) / (len(maxs) + 1),
                     MISE * np.array(pris[k]).mean(), ma, mb), flush=True)
        print()
        print("   Rappel : la colonne qui paie est EUR/ticket, pas sigma (regle 4). Et les DEUX")
        print("   moities doivent etre positives, sinon la regle a eu un bon jour, pas un edge.")


if __name__ == "__main__":
    main()
