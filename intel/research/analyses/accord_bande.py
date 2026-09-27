"""LE `risque` DU MOTEUR EST-IL LE MEME QUE CELUI DU CARNET ? La bande en depend entierement.

La regle `BANDE + PAUSE` est definie par `0,20 <= risque < 0,35`, ou `risque` est la probabilite de
vidage calculee par `modele_vidage.json` dans `papier_combo`. Le moteur charge le meme fichier --
mais il calcule ses variables LUI-MEME, en direct. Si sa version differe un peu, la bande ne
designe plus les memes jetons, et rien ne le signalerait : le score resterait dans [0 ; 1] et la
regle continuerait de « marcher ».

C est exactement le piege qui a fait rater deux fois la journee du 20/09 : une fenetre confondue
avec un age, un historique sans filtre d age. Les deux donnaient des variables au bon nom et a la
mauvaise valeur.

ON COMPARE, sur les jetons vus des deux cotes : l ecart des scores, et surtout l accord sur
l APPARTENANCE A LA BANDE -- c est elle qui decide de l achat, pas le score.

Lecture seule.
"""
from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                "research"))
BANDE = (0.20, 0.35)


def main() -> None:
    # SEULEMENT LES DECISIONS PRISES AVEC `modele_vidage.json`. Le premier essai comparait
    # 1 892 tickets historiques dont la plupart avaient ete decides par d AUTRES modeles -- la
    # foret, la reentrainee, la 75s -- et concluait que « la bande differe » alors qu il comparait
    # des scores qui ne sortaient pas du meme modele. DEPUIS est l instant ou le moteur a charge
    # `modele_vidage.json` ; tout ce qui precede est hors sujet.
    depuis = float(os.environ.get("DEPUIS", "0"))
    i = sqlite3.connect("file:/app/db/intel.sqlite?mode=ro", uri=True, timeout=30)
    moteur = {str(p): float(r) for p, r in i.execute(
        "SELECT pair, risque FROM mr_lignes WHERE pair IS NOT NULL AND risque IS NOT NULL"
        " AND t_dec >= ?", (depuis,))}
    c = sqlite3.connect("file:/app/db/papier_combo.sqlite?mode=ro", uri=True, timeout=30)
    carnet = {str(p): float(r) for p, r in c.execute(
        "SELECT pair, risque FROM decision WHERE risque IS NOT NULL")}
    communs = sorted(set(moteur) & set(carnet))
    print("moteur %d · carnet %d · en commun %d" % (len(moteur), len(carnet), len(communs)))
    if len(communs) < 10:
        print("   trop peu pour comparer")
        return
    e = sorted(abs(moteur[p] - carnet[p]) for p in communs)
    q = lambda f: e[min(int(f * len(e)), len(e) - 1)]  # noqa: E731
    print()
    print("   ecart des scores : median %.5f · q3 %.5f · d9 %.5f · max %.5f"
          % (q(.5), q(.75), q(.9), e[-1]))
    dans = lambda x: BANDE[0] <= x < BANDE[1]  # noqa: E731
    acc = [p for p in communs if dans(moteur[p]) == dans(carnet[p])]
    m_seul = [p for p in communs if dans(moteur[p]) and not dans(carnet[p])]
    c_seul = [p for p in communs if dans(carnet[p]) and not dans(moteur[p])]
    print()
    print("   DANS LA BANDE -- c est ce qui decide de l achat :")
    print("      d accord     %4d sur %d (%.1f %%)" % (len(acc), len(communs), 100 * len(acc) / len(communs)))
    print("      moteur seul  %4d   il achete ce que le carnet laisse" % len(m_seul))
    print("      carnet seul  %4d   il laisse ce que le carnet prend" % len(c_seul))
    if m_seul or c_seul:
        bord = [p for p in (m_seul + c_seul)
                if min(abs(carnet[p] - BANDE[0]), abs(carnet[p] - BANDE[1])) < 0.01]
        print("      dont a moins de 0,01 d une borne : %d sur %d"
              % (len(bord), len(m_seul) + len(c_seul)))
    print()
    if len(acc) / len(communs) >= 0.98:
        print("   -> meme bande. La regle deployee est celle qui a ete mesuree.")
    else:
        print("   -> LA BANDE DIFFERE. Ce qui tourne n est pas ce qui a ete mesure.")


if __name__ == "__main__":
    main()
