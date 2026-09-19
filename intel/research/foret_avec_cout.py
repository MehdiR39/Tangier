"""LA METHODE REENTRAINEE FAIT-ELLE MIEUX AVEC LA VARIABLE DE COUT ? Et avec le VRAI cout ?

MIDO, 19/09 22h : « le fait qu'une variable soit ecartee on s'en fout, le resultat est le meme, tu
as trouve une methode qui est meilleure. Il faut la reentrainer avec la variable manquante pour voir
si on ne fait pas encore mieux. »

CE QUI S EST PASSE. Le test de §3.157 demandait `px_cout` ; cette colonne n existe pas dans la table
de recherche et le filtre des colonnes disponibles l a ecartee en silence. La methode a donc ete
validee (p = 0,016) sur 18 variables et non 19 -- alors que le modele en production en a 19, dont
`cout`, qui porte 21 % de son importance.

TROIS JEUX, et le troisieme est la vraie question :
  18 variables        ce qui a ete teste hier soir, sans aucun cout
  + cout FORMULE      la variable du moteur reconstruite : 0,017 + 2.mise_SOL/(coffre + V).
                      C est exactement ce que le modele en prod recoit.
  + cout MESURE       le meme, mais recale sur la realite. La formule annonce 0,21 % en median
                      quand le cout reellement paye est de 3,29 %, et elle correle a r = +0,025
                      avec lui -- c est-a-dire pas du tout. On teste donc si un cout QUI DIT VRAI
                      vaut mieux qu un cout qui se trompe d un facteur quinze.

Le « cout mesure » est reconstruit a partir de ce que le registre a etabli au lamport (§3.156) :
une part constante (commission du pool et prelevements du protocole, 1,41 % par jambe) plus la part
qui depend de la taille : 2 x mise_SOL / (coffre + V). Il n utilise AUCUNE information posterieure
a la decision -- sinon ce serait une fuite, et le resultat ne voudrait rien dire.

Meme protocole que §3.157, sinon les chiffres ne sont pas comparables : marche avant par coupes de
6 h, entrainement sur tout ce qui precede, on garde 80 %, cout 3,71 pt, barre du hasard sur le
MEILLEUR des trois jeux.
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
# CORRECTION DU 19/09 23h, apres la question de Mido « le top 20 c est du leakage ? ». La premiere
# version gardait les GARDE % du haut DANS chaque fenetre de 6 h -- donc en classant un ticket contre
# des voisins pas encore nes a l instant de decider. Pas une fuite de resultat, mais pas decidable en
# vrai. On decide desormais par SEUIL ABSOLU, le quantile des scores d ENTRAINEMENT, exactement comme
# `foret_marche` le fait dans son carnet papier. Le nombre de tickets gardes varie alors, et c est le
# vrai comportement de la regle. SEUIL_ABSOLU=0 rejoue l ancienne, pour mesurer ce que le defaut valait.
SEUIL_ABSOLU = os.environ.get("SEUIL_ABSOLU", "1") == "1"
V_RESERVE = 17.5845
SOL_PAR_EUR = 0.31 / 30.0
PART_FIXE = 0.0141                 # 1,41 % par jambe, mesure au lamport sur 15 transactions
BASE = ["px_n_lect", "px_ret_naiss", "px_dd_max", "px_depuis_min", "px_t_depuis_max", "px_vol",
        "q", "px_q_croiss", "px_ret_10", "px_ret_30", "px_ret_60", "px_ret_120",
        "px_q_croiss_30", "px_q_croiss_60", "px_lancements_10min", "px_heure", "V", "px_A"]


def net(r):
    return (1.0 + r) * (1.0 - COUT) - 1.0


def main() -> None:
    df = pd.read_pickle(os.path.join(DOSSIER, "table.pkl"))
    df = df[(df["eligible"] == 1) & df["ret_240"].notna()]
    df = df.sort_values("t_dec").reset_index(drop=True)
    base = [c for c in BASE if c in df.columns and df[c].notna().sum() >= 100]

    q = pd.to_numeric(df["q"], errors="coerce").astype(float)
    mise_sol = MISE * SOL_PAR_EUR
    impact = 2 * mise_sol / (q + V_RESERVE)
    # LA FORMULE DU MOTEUR, telle qu il la calcule (`COUT_FIXE_MODELE + 2 . mise_SOL / (q + V)`).
    df["cout_formule"] = 0.017 + impact
    # LE COUT QUI DIT VRAI : la part constante mesuree au lamport, plus la meme part d impact. Rien
    # d autre -- surtout rien qui vienne d apres la decision.
    df["cout_mesure"] = 2 * PART_FIXE + impact

    jeux = {
        "18 variables (le test d hier)": base,
        "+ cout FORMULE (comme la prod)": base + ["cout_formule"],
        "+ cout MESURE (recale sur le reel)": base + ["cout_mesure"],
    }
    y_net = net(df["ret_240"].to_numpy(dtype=float))
    y_vid = (y_net <= -0.5).astype(int)
    t = df["t_dec"].to_numpy()
    print("%d tickets · cout %.2f pt · on garde %.0f %%" % (len(df), 100 * COUT, 100 * GARDE))
    print("   cout FORMULE : median %.3f %% · cout MESURE : median %.3f %% · reel mesure 3,29 %%"
          % (100 * df["cout_formule"].median(), 100 * df["cout_mesure"].median()))
    print()

    tz = dt.timezone(dt.timedelta(hours=2))
    DEBUT = dt.datetime(2026, 9, 16, 0, 0, tzinfo=tz)
    FIN = dt.datetime(2026, 9, 19, 12, 0, tzinfo=tz)

    def marche(yv, yn):
        tot = {k: [] for k in jeux}
        tem = []
        c = DEBUT
        while c < FIN:
            c0, c1 = c.timestamp(), (c + dt.timedelta(hours=6)).timestamp()
            A, J = t < c0, (t >= c0) & (t < c1)
            c += dt.timedelta(hours=6)
            if A.sum() < 150 or J.sum() < 20:
                continue
            nets = yn[J]
            tem.extend(nets.tolist())
            for nom, cols in jeux.items():
                X = df[cols].apply(pd.to_numeric, errors="coerce").astype(float)
                med = X[A].median()
                XA = X[A].fillna(med).fillna(0)
                rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=20, n_jobs=-1,
                                            random_state=0).fit(XA, yv[A])
                p = rf.predict_proba(X[J].fillna(med).fillna(0))[:, 1]
                if SEUIL_ABSOLU:
                    # DECIDABLE A 45 s : le seuil vient des scores d ENTRAINEMENT, connus avant la
                    # fenetre, comme le fait `foret_marche` en carnet papier. Le nombre de tickets
                    # gardes n est alors plus exactement GARDE, et c est le vrai comportement.
                    seuil = float(np.quantile(rf.predict_proba(XA)[:, 1], GARDE))
                    tot[nom].extend(nets[p <= seuil].tolist())
                else:
                    # CLASSEMENT DANS LA FENETRE : compare un ticket a des voisins pas encore nes.
                    k = max(5, int(len(nets) * GARDE))
                    tot[nom].extend(nets[np.argsort(p, kind="stable")[:k]].tolist())
        return tot, np.array(tem)

    tot, tem = marche(y_vid, y_net)
    sigma = MISE * tem.std(ddof=1)
    print("   %-38s %6s %11s %11s %9s" % ("", "n", "EUR/ticket", "vs temoin", "ecarts-t"))
    print("   %-38s %6d %+10.3f %+10.3f %9s" % ("TEMOIN : tout prendre", len(tem),
                                                MISE * tem.mean(), 0.0, "-"))
    res = {}
    for nom, v in tot.items():
        v = np.array(v)
        if len(v) < 20:
            continue
        d = MISE * (v.mean() - tem.mean())
        n_, k_ = len(tem), len(v)
        bruit = sigma * np.sqrt((n_ - k_) / (n_ * k_)) if 0 < k_ < n_ else float("inf")
        res[nom] = d
        print("   %-38s %6d %+10.3f %+10.3f %+9.2f" % (nom, k_, MISE * v.mean(), d, d / bruit))

    if NULLS and res:
        print()
        print("BARRE DU HASARD : %d marches avant permutees, meilleur des %d jeux retenu"
              % (NULLS, len(jeux)))
        rng = np.random.default_rng(29)
        maxs = []
        for i in range(NULLS):
            perm = rng.permutation(len(y_net))
            tp, rt = marche(y_vid[perm], y_net[perm])
            maxs.append(max(MISE * (np.array(tp[k]).mean() - rt.mean()) for k in jeux))
            if (i + 1) % 15 == 0:
                print("   %d/%d · meilleur du hasard %+0.3f" % (i + 1, NULLS, max(maxs)), flush=True)
        meilleur = max(res, key=res.get)
        ks = sum(1 for m in maxs if m >= res[meilleur])
        print("   -> meilleur jeu « %s » a %+.3f · %d sur %d font aussi bien (p ~ %.3f)"
              % (meilleur, res[meilleur], ks, len(maxs), (ks + 1) / (len(maxs) + 1)))


if __name__ == "__main__":
    main()
