"""LE MOTEUR PREND-IL LES MEMES TICKETS QUE LE CARNET ? La derniere verification avant l argent.

Le carnet `foret_gel75` dit +0,462 EUR/ticket sur sa periode commune. Ce chiffre ne concerne le
MOTEUR que si le moteur prend les MEMES tickets. Il decide en direct, a 75 s, avec des variables
calculees dans l urgence et un appel reseau qui peut tronquer ; le carnet, lui, lit une table
construite apres coup. Rien ne garantit qu ils soient d accord, et tout le reste en depend.

CE QU ON COMPARE, sur les jetons vus des deux cotes :
    d accord        les deux prennent, ou les deux ecartent
    le moteur seul  il achete ce que le carnet aurait laisse
    le carnet seul  il laisse passer ce que le carnet aurait pris
Un desaccord n est pas forcement une erreur -- le moteur voit un flux tronque a 3 pages, le carnet
voit tout -- mais au-dela de quelques pour cent, le +0,462 ne vaut plus pour la production.

ON REGARDE AUSSI LES SCORES, pas seulement les decisions : deux scores qui different de 0,001
autour du seuil donnent un desaccord sans que rien ne soit casse, et c est une information
differente d un ecart de 0,4.

Lecture seule. Ne decide rien, ne touche a rien.
"""
from __future__ import annotations

import os
import sqlite3

INTEL = "/app/db/intel.sqlite"
CARNET = "/app/db/papier_foret75.sqlite"
SEUIL_DIRECT = 0.7996              # le carnet garde p >= 0,7996


def main() -> None:
    c = sqlite3.connect("file:%s?mode=ro" % INTEL, uri=True, timeout=30)
    moteur = {}
    for pair, statut, risque, var in c.execute(
            "SELECT pair, statut, risque, variables FROM mr_lignes"
            " WHERE pair IS NOT NULL AND risque IS NOT NULL AND variables IS NOT NULL"):
        if "v1_n_achats" not in (var or ""):
            continue                       # decision de l ancien chemin : hors sujet
        moteur[str(pair)] = (float(risque), statut != "ECARTEE")
    if not moteur:
        print("accord_75: aucune decision du chemin 75 s pour l instant")
        return
    if not os.path.exists(CARNET):
        print("accord_75: carnet %s introuvable" % CARNET)
        return
    d = sqlite3.connect("file:%s?mode=ro" % CARNET, uri=True, timeout=30)
    carnet = {str(p): (float(pr), bool(r10)) for p, pr, r10 in d.execute(
        "SELECT pair, p, retenu10 FROM decision WHERE p IS NOT NULL")}

    communs = sorted(set(moteur) & set(carnet))
    print("moteur : %d decisions a 75 s · carnet : %d · en commun : %d"
          % (len(moteur), len(carnet), len(communs)))
    if not communs:
        print("   aucun jeton vu des deux cotes pour l instant -- il faut attendre que le carnet")
        print("   repasse (toutes les 6 h) sur les tickets que le moteur vient de decider.")
        return

    accord = [p for p in communs if moteur[p][1] == carnet[p][1]]
    moteur_seul = [p for p in communs if moteur[p][1] and not carnet[p][1]]
    carnet_seul = [p for p in communs if carnet[p][1] and not moteur[p][1]]
    print()
    print("   d accord        %4d  (%.0f %%)" % (len(accord), 100 * len(accord) / len(communs)))
    print("   moteur seul     %4d   il achete ce que le carnet laisse" % len(moteur_seul))
    print("   carnet seul     %4d   il laisse ce que le carnet prend" % len(carnet_seul))

    # LES SCORES : un desaccord a 0,001 du seuil n est pas la meme chose qu un ecart de 0,4
    e = sorted(abs((1.0 - moteur[p][0]) - carnet[p][0]) for p in communs)
    q = lambda f: e[min(int(f * len(e)), len(e) - 1)]  # noqa: E731
    print()
    print("   ecart des SCORES (1 - moteur contre carnet) :")
    print("      median %.4f · q3 %.4f · d9 %.4f · max %.4f" % (q(.5), q(.75), q(.9), e[-1]))
    print("      sous 0,01 : %.0f %% des jetons" % (100 * sum(1 for x in e if x < 0.01) / len(e)))
    desac = moteur_seul + carnet_seul
    if desac:
        pres = [p for p in desac if abs(carnet[p][0] - SEUIL_DIRECT) < 0.05]
        print("      desaccords a moins de 0,05 du seuil : %d sur %d" % (len(pres), len(desac)))
    print()
    if len(accord) / len(communs) >= 0.95:
        print("   -> le moteur reproduit le carnet. Le +0,462 EUR/ticket le concerne.")
    else:
        print("   -> DESACCORD TROP LARGE. Le chiffre du carnet ne vaut pas pour la production")
        print("      tant qu on n a pas explique d ou vient l ecart.")


if __name__ == "__main__":
    main()
