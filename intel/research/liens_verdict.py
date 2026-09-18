"""UN SITE DECLARE REND-IL UN JETON MEILLEUR A ACHETER ? Critere ECRIT AVANT de lire la table.

LA QUESTION, DE MIDO : « le fait d avoir un site web, ca ajoute plus serieux ? »

ELLE N A JAMAIS ETE TESTEE DANS CE PROJET. Ce qui avait ete teste sous le nom « Telegram », ce sont
des SIGNAUX DE CHAINES -- quelqu un poste un jeton, on l achete. Ici il s agit de la METADONNEE :
le createur a-t-il declare un site, un Twitter, un Telegram ? `features_lancement.py` annonce
`a_site` depuis le 09/09 sans l avoir jamais implemente.

CE QUE DIT LA LITTERATURE, pour cadrer et non pour conclure. Kamat 2026 (832 941 lancements) :
Telegram HR 5,40 · Twitter 1,30 · **site 1,19**. Le site est le plus faible des trois, et l effet
porte sur la SURVIE du jeton, pas sur le rendement d un acheteur apres couts -- or ce projet a
mesure que les deux divergent (« le modele mesure la VIE, pas le danger »).

LE CRITERE, FIGE AVANT DE REGARDER. « Avoir un site » ne compte que s il passe les CINQ :

 1. l ecart entre AVEC et SANS est d au moins **+2,62 points** apres coup -- en dessous, il ne paie
    meme pas l aller-retour, donc il ne vaut rien meme s il est reel ;
 2. il garde le meme SIGNE sur les deux moities chronologiques ;
 3. il survit au retrait des 3 MEILLEURS tickets du groupe AVEC ;
 4. il bat un tirage ALEATOIRE de meme taille dans au moins 95 % des cas ;
 5. le groupe AVEC est positif en NIVEAU apres cout -- un contraste ne se trade pas, seul un niveau
    se trade (regle 4 de la discipline, -436 EUR le 15/09).

Les cinq, sinon NON. Et on affiche la part d ex aequo et les effectifs a cote de chaque chiffre.

TROIS VARIABLES SONT LUES, PAS UNE. Site, Twitter, Telegram : les tester separement coute le meme
travail et permet de voir si l une se detache. Mais un balayage de trois variables se juge plus
severement qu une seule -- la loi du maximum -- donc on affiche aussi ce que le hasard produit de
MIEUX sur trois essais.
"""
from __future__ import annotations

import os
import random
import sqlite3
import statistics as st

LIENS = os.environ.get("LIENS_DB", "/app/db/liens.sqlite")
COMBO = os.environ.get("COMBO_DB", "/app/db/papier_combo.sqlite")
COUT = 0.0262
TIRAGES = 4000
ECART_MIN = 0.0262          # un ecart plus petit que le peage ne se trade pas


def net(r: float) -> float:
    return (1.0 + r) * (1.0 - COUT) - 1.0


def decris(nom: str, v: list[float]) -> str:
    if len(v) < 20:
        return "  %-26s n=%4d  trop peu" % (nom, len(v))
    s = sorted(v)
    return ("  %-26s n=%4d  moy %+6.2f %%  med %+6.2f %%  sans 3 meil. %+6.2f %%  gagnants %4.1f %%"
            % (nom, len(v), 100 * st.mean(v), 100 * st.median(v), 100 * st.mean(s[:-3]),
               100 * sum(1 for x in v if x > 0) / len(v)))


def main() -> None:
    c = sqlite3.connect("file:%s?mode=ro" % LIENS, uri=True)
    d = sqlite3.connect("file:%s?mode=ro" % COMBO, uri=True)
    res = {}
    for mint, t, r in d.execute(
            "SELECT d.mint, d.t_dec, i.brut_240 FROM decision d JOIN issue i ON i.pair = d.pair"
            " WHERE i.brut_240 IS NOT NULL"):
        res[mint] = (t, r)

    lignes = []
    for mint, si, tw, tg, nd in c.execute(
            "SELECT mint, a_site, a_twitter, a_telegram, n_description FROM lien"
            " WHERE erreur IS NULL"):
        if mint in res:
            t, r = res[mint]
            lignes.append((t, si, tw, tg, nd, net(r)))
    lignes.sort(key=lambda x: x[0])
    print("%d jetons lus ET avec un resultat" % len(lignes))
    if len(lignes) < 100:
        print("trop peu pour conclure quoi que ce soit")
        return

    tout = [x[5] for x in lignes]
    print(decris("TOUS (temoin)", tout))
    print()

    resultats = {}
    for i, nom in ((1, "SITE"), (2, "TWITTER"), (3, "TELEGRAM")):
        avec = [x[5] for x in lignes if x[i] == 1]
        sans = [x[5] for x in lignes if x[i] == 0]
        print("%s -- declare par %.1f %% des jetons" % (nom, 100 * len(avec) / len(lignes)))
        print(decris("avec", avec))
        print(decris("sans", sans))
        if len(avec) < 20 or len(sans) < 20:
            print()
            continue
        ecart = st.mean(avec) - st.mean(sans)
        print("  ecart %+.2f pt" % (100 * ecart))

        # (2) les deux moities
        h = len(lignes) // 2
        a1 = [x[5] for x in lignes[:h] if x[i] == 1]
        s1 = [x[5] for x in lignes[:h] if x[i] == 0]
        a2 = [x[5] for x in lignes[h:] if x[i] == 1]
        s2 = [x[5] for x in lignes[h:] if x[i] == 0]
        e1 = (st.mean(a1) - st.mean(s1)) if a1 and s1 else float("nan")
        e2 = (st.mean(a2) - st.mean(s2)) if a2 and s2 else float("nan")
        print("  moities %+.2f / %+.2f pt   %s" % (100 * e1, 100 * e2,
              "meme signe" if (e1 > 0) == (e2 > 0) else "SIGNE OPPOSE"))

        # (4) le hasard, a taille egale
        k, mieux = len(avec), 0
        for _ in range(TIRAGES):
            if st.mean(random.sample(tout, k)) >= st.mean(avec):
                mieux += 1
        p = mieux / TIRAGES
        print("  un tirage au hasard de %d fait aussi bien dans %.1f %% des cas" % (k, 100 * p))

        sa = sorted(avec)
        crit = {
            "(1) ecart >= 2,62 pt": ecart >= ECART_MIN,
            "(2) meme signe sur les deux moities": (e1 > 0) == (e2 > 0),
            "(3) tient sans ses 3 meilleurs": (st.mean(sa[:-3]) - st.mean(sans)) >= 0,
            "(4) bat le hasard (p <= 5 %)": p <= 0.05,
            "(5) le groupe AVEC est positif": st.mean(avec) > 0,
        }
        for k2, v in crit.items():
            print("   %-38s %s" % (k2, "oui" if v else "NON"))
        print("  -> %s" % ("CRITERE TENU" if all(crit.values()) else "NON"))
        resultats[nom] = ecart
        print()

    # la loi du MAXIMUM : trois variables essayees, il faut battre le meilleur des trois au hasard
    if resultats:
        meilleur = max(resultats.values())
        k = len([x for x in lignes if x[1] == 1]) or 1
        pires = 0
        for _ in range(1000):
            m = max(st.mean(random.sample(tout, k)) - st.mean(tout) for _ in range(3))
            if m >= meilleur:
                pires += 1
        print("TROIS VARIABLES ESSAYEES : le MEILLEUR de trois tirages au hasard fait aussi bien")
        print("que notre meilleur ecart (%+.2f pt) dans %.1f %% des cas."
              % (100 * meilleur, 100 * pires / 1000))


if __name__ == "__main__":
    main()
