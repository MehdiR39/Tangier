"""REENTRAINER LA FORET 75s AMELIORE-T-IL, COMME POUR CELLE A 45 s ?

MIDO, 19/09 22h50 : « on a vu qu'en reentrainant un modele ca ameliore, et on a un modele a 75 s
qui est bon -- on peut essayer de reentrainer le modele 75 ? »

LA QUESTION, POSEE PROPREMENT. Le 19/09 au soir on a montre qu une foret REENTRAINEE toutes les 6 h
bat le temoin de +0,363 EUR/ticket, 0 tirage sur 60 (p ~ 0,016) -- mais sur la recette a 45 s : 18
variables de prix, cible « vidage », on garde 80 %. La foret a 75 s est un objet different : 107
variables de toutes les sources reduites a 25, cible « gagnant net », on garde les 5 % les plus surs,
decision a 75 s et entree au dernier prix <= 77 s. Rien ne dit que ce qui aide l une aide l autre.

CE QUE CE TEST COMPARE, et c est le seul point qui compte : LA MEME RECETTE, LES MEMES TICKETS, LA
MEME FENETRE. Trois bras.
    TEMOIN        tout prendre
    GELEE         entrainee UNE SEULE FOIS a la premiere coupe, puis jamais -- exactement ce que
                  fait `foret_gel75` en production papier depuis le 18/09 23h10
    REENTRAINEE   reentrainee a CHAQUE coupe de 6 h sur tout ce qui precede, selection des 25
                  variables refaite a chaque fois (§3.136)
Aucun ticket n est jamais note par un modele qui l a vu : les deux bras s entrainent sur le passe
strict de la fenetre qu ils jugent. La difference entre les deux bras N EST QUE la fraicheur des
poids -- c est la definition meme de la question de Mido.

LE COUT. `foret_gel` a ete gele avec COUT = 6,55 pt, l estimation de l epoque. Ici on applique
3,71 pt, le cout mesure au lamport, PARTOUT : a la cible comme au resultat, et identiquement sur les
trois bras. Un cout different changerait les trois de la meme facon et ne peut pas fabriquer un
ecart entre eux.

COMMENT ON DECIDE, ET UN DEFAUT CORRIGE. Premiere version : a chaque coupe, classer les tickets de
la fenetre entre eux et garder les g % du haut. MIDO, en lisant le premier resultat : « tu veux dire
quoi, le top 20 c est du leakage ? » -- non, mais sa question a fait voir autre chose. Classer un
ticket contre ses voisins de la meme tranche de 6 h, c est le comparer a des tickets qui naitront
APRES lui : a 75 s on ne les connait pas. Ce n est PAS une fuite de resultat (le test ne voit jamais
la reponse), c est une fuite de VOISINAGE FUTUR -- plus legere, mais pas implementable en vrai.
Par defaut on decide donc comme `foret_gel` le fait en production papier : un SEUIL ABSOLU, le
quantile (1 - g) des scores d ENTRAINEMENT, connu avant la fenetre. Le nombre de tickets retenus
n est alors plus exactement g %, et c est normal -- c est le vrai comportement de la regle.
SEUIL_ABSOLU=0 rejoue l ancienne version, pour mesurer ce que le defaut valait.
(Meme defaut dans `foret_avec_cout` et `marche_avant*` : a corriger de la meme facon.)

LA BARRE DU HASARD. Comme partout dans ce projet : on repermute les resultats, on refait la marche
avant entiere, et on retient le MEILLEUR des bras a chaque tirage. Sinon on se felicite d avoir
regarde deux fois. Papier, zero euro, aucune ecriture ailleurs que sur la sortie.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
os.environ.setdefault("AGE_DECISION", "75")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

COUT = float(os.environ.get("COUT_MESURE", "0.0371"))
MISE = 20.0
N_VARIABLES = 25                   # la recette du gel : les 25 plus utiles sur le passe
PAS_H = 6
NULLS = int(os.environ.get("NULLS", "40"))
TZ = dt.timezone(dt.timedelta(hours=2))
DEBUT = dt.datetime(2026, 9, 16, 0, 0, tzinfo=TZ)
FIN = dt.datetime(2026, 9, 19, 12, 0, tzinfo=TZ)
GARDES = (0.05, 0.10, 0.20)        # 5 % est la recette ; 10 et 20 sont donnes pour lecture
# SEUIL_ABSOLU=1 : la version DECIDABLE EN VRAI. Voir `_apprendre` et la boucle de decision.
SEUIL_ABSOLU = os.environ.get("SEUIL_ABSOLU", "1") == "1"


def _foret(n=300):
    from sklearn.ensemble import RandomForestClassifier
    return RandomForestClassifier(n_estimators=n, min_samples_leaf=20, n_jobs=-1, random_state=0)


def _apprendre(X, y, cols):
    """La recette du gel : une foret pour classer les variables, les 25 meilleures, une seconde foret.

    Rend aussi les SEUILS, pris sur les scores d entrainement -- c est ce que fait `foret_gel` en
    production papier (quantile 0,95 des scores d entrainement), et c est ce qui rend la regle
    decidable ticket par ticket, sans connaitre les tickets a venir.
    """
    med = X[cols].median()
    XA = X[cols].fillna(med).fillna(0.0)
    imp = _foret(200).fit(XA, y).feature_importances_
    gard = [c for _, c in sorted(zip(imp, cols), key=lambda z: -z[0])[:N_VARIABLES]]
    rf = _foret(300).fit(XA[gard], y)
    p_tr = rf.predict_proba(XA[gard])[:, 1]
    return rf, med[gard], gard, {g: float(np.quantile(p_tr, 1.0 - g)) for g in GARDES}


def main() -> None:
    import foret_gel as G

    df, cols = G.table()
    df = df[df["ret_240"].notna()].sort_values("t_dec").reset_index(drop=True)
    X = df[cols].apply(pd.to_numeric, errors="coerce").astype(float)
    t = df["t_dec"].to_numpy(dtype=float)
    net0 = (1.0 + df["ret_240"].to_numpy(dtype=float)) * (1.0 - COUT) - 1.0
    print("FORET 75s : %d tickets avec resultat · %d variables disponibles · cout %.2f pt"
          % (len(df), len(cols), 100 * COUT), flush=True)
    print("   fenetre jugee %s -> %s, coupes de %d h · decision par %s"
          % (DEBUT.strftime("%d/%m %Hh"), FIN.strftime("%d/%m %Hh"), PAS_H,
             "SEUIL ABSOLU (decidable en vrai)" if SEUIL_ABSOLU
             else "classement dans la fenetre (PAS decidable en vrai)"), flush=True)
    print(flush=True)

    def marche(net):
        """Rend, pour chaque bras et chaque taux de garde, la liste des nets retenus ; plus le temoin."""
        y = (net > 0).astype(int)
        pris = {(b, g): [] for b in ("GELEE", "REENTRAINEE") for g in GARDES}
        tem = []
        fige = None
        c = DEBUT
        while c < FIN:
            c0 = c.timestamp()
            c1 = (c + dt.timedelta(hours=PAS_H)).timestamp()
            c += dt.timedelta(hours=PAS_H)
            A = t < c0
            J = (t >= c0) & (t < c1)
            if A.sum() < 300 or J.sum() < 20:
                continue
            tem.extend(net[J].tolist())
            if fige is None:
                fige = _apprendre(X[A], y[A], cols)      # UNE SEULE FOIS : c est le gel
            frais = _apprendre(X[A], y[A], cols)         # a chaque coupe : c est la question
            for nom, m in (("GELEE", fige), ("REENTRAINEE", frais)):
                rf, med, gard, q_tr = m
                p = rf.predict_proba(X.loc[J, gard].fillna(med).fillna(0.0))[:, 1]
                for g in GARDES:
                    if SEUIL_ABSOLU:
                        # DECIDABLE EN VRAI : le seuil vient des scores d ENTRAINEMENT, connus avant
                        # la fenetre. Un ticket est compare a ce nombre, et a rien d autre.
                        garde_ = p >= q_tr[g]
                    else:
                        # CLASSEMENT DANS LA FENETRE : compare un ticket a ses voisins de la meme
                        # tranche de 6 h, dont certains naitront APRES lui. Pas implementable a 75 s.
                        ordre = np.argsort(-p, kind="stable")
                        garde_ = np.zeros(len(p), bool)
                        garde_[ordre[:max(1, int(round(len(p) * g)))]] = True
                    pris[(nom, g)].extend(net[J][garde_].tolist())
        return pris, np.array(tem)

    def z(v, tm):
        """L ecart au temoin, EN ECARTS-TYPES DE SA PROPRE CASE.

        La barre du hasard doit comparer des cases comparables. En euros bruts elle ne le fait pas :
        une case a 40 tickets a un bruit trois fois plus large qu une case a 320, donc le hasard y
        produit de gros ecarts sans rien savoir, et le maximum sur six cases est confisque par la
        plus petite -- ce qui condamnerait d avance les cases larges, les seules exploitables. En
        ecarts-types les six cases jouent au meme jeu. (Meme correction que flux_severite, §3.150.)
        """
        k_, n_ = len(v), len(tm)
        if not 0 < k_ < n_:
            return 0.0
        s = MISE * tm.std(ddof=1)
        return MISE * (v.mean() - tm.mean()) / (s * np.sqrt((n_ - k_) / (n_ * k_)))

    pris, tem = marche(net0)
    sigma = MISE * tem.std(ddof=1)
    n_ = len(tem)
    print("   %-28s %6s %11s %11s %9s %11s"
          % ("", "n", "EUR/ticket", "vs temoin", "sig(vs)", "sig(niveau)"))
    print("   %-28s %6d %+10.3f %+10.3f %9s %11.2f"
          % ("TEMOIN : tout prendre", n_, MISE * tem.mean(), 0.0, "-",
             MISE * tem.mean() / (sigma / np.sqrt(n_))))
    res, zs = {}, {}
    for (nom, g), v in pris.items():
        v = np.array(v)
        if len(v) < 10:
            continue
        k_ = len(v)
        res[(nom, g)] = MISE * (v.mean() - tem.mean())
        zs[(nom, g)] = z(v, tem)
        # NIVEAU : l argent reellement gagne, et SON bruit a lui (sigma/racine(k)). C est lui qui
        # paie ; le contraste ne paie rien (regle 23).
        niv = MISE * v.mean()
        print("   %-28s %6d %+10.3f %+10.3f %+9.2f %+11.2f"
              % ("%s  top %.0f %%" % (nom, 100 * g), k_, niv, res[(nom, g)], zs[(nom, g)],
                 niv / (sigma / np.sqrt(k_))), flush=True)

    # LA RECETTE, c est le top 5 %. Le reste est de la lecture, et on le dit avant de regarder.
    print()
    for g in GARDES:
        a, b = res.get(("GELEE", g)), res.get(("REENTRAINEE", g))
        if a is not None and b is not None:
            print("   top %3.0f %% : reentrainee %+0.3f contre gelee %+0.3f  ->  %+0.3f"
                  % (100 * g, b, a, b - a), flush=True)

    if NULLS and res:
        print()
        print("BARRE DU HASARD : %d marches avant permutees, meilleur des %d cases retenu"
              % (NULLS, len(res)), flush=True)
        rng = np.random.default_rng(75)
        maxs = []
        for i in range(NULLS):
            perm = rng.permutation(len(net0))
            tp, rt = marche(net0[perm])
            maxs.append(max(z(np.array(v), rt) for _, v in tp.items() if len(v) >= 10))
            if (i + 1) % 10 == 0:
                print("   %d/%d · meilleur du hasard %+0.2f sigma" % (i + 1, NULLS, max(maxs)),
                      flush=True)
        meilleur = max(zs, key=zs.get)
        ks = sum(1 for m in maxs if m >= zs[meilleur])
        print("   -> meilleure case « %s top %.0f %% » a %+.2f sigma (%+.3f EUR/ticket)"
              % (meilleur[0], 100 * meilleur[1], zs[meilleur], res[meilleur]), flush=True)
        print("      %d sur %d font aussi bien (p ~ %.3f)"
              % (ks, len(maxs), (ks + 1) / (len(maxs) + 1)), flush=True)


if __name__ == "__main__":
    main()
