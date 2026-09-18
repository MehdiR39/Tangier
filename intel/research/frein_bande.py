"""FREIN x BANDE, PRE-ENREGISTRE le 18/09/2026 a 16h30 UTC (18h30 Paris).

POURQUOI CETTE CONJONCTION ET PAS UNE AUTRE. C est le SEUL croisement de deux axes INDEPENDANTS du
projet. Tout ce qui a ete teste depuis trois jours filtre le JETON -- le prix, le coffre, la
volatilite, les detenteurs, l image, l usine. Le frein, lui, filtre le MARCHE : il refuse d acheter
quand les vingt derniers tickets clotures ont majoritairement perdu. Les deux ne regardent pas la
meme chose, donc ils peuvent s apporter quelque chose -- ce qui n etait pas le cas de l ensemble et
de la foret (correlation 0,939, 91 % de recouvrement, rien a echanger).

ET ÇA EXPLIQUE POURQUOI LA BANDE SEULE EST MORTE. Elle choisit correctement les jetons -- ni trop
morts (les quintiles surs ont 0,0 % de gros gains) ni trop dangereux -- mais elle les achetait aussi
dans les mauvaises fenetres de marche. Hors echantillon elle fait -8,38 % par ticket (§3.111). Le
frein bouche exactement ce trou.

LA MESURE, sur 1 414 tickets `RISQUE seul` :

| regle | n | net | deux moities | sans ses 3 meilleurs | p |
|---|---|---|---|---|---|
| RISQUE seul (reference) | 1 414 | -0,31 % | -1,34 / +0,73 | | |
| FREIN seul | 1 009 | +1,14 % | +1,28 / +0,99 | +0,25 % | 0,163 |
| **FREIN x BANDE** | **392** | **+6,28 %** | **+8,90 / +3,66** | **+4,02 %** | **0,004** |

**Aucune regle de ce projet n avait jamais coche les trois** : deux moities positives, positive sans
ses trois meilleurs tickets, et p < 0,01.

LA RESERVE, ECRITE AVANT DE VOIR LA SUITE -- et elle est serieuse. NEUF combinaisons ont ete
essayees avant de retenir celle-ci. En tirant la loi du MEILLEUR sous permutation sur ces neuf
tailles, le hasard produit +4,58 % en mediane et +10,54 % au 95e centile : **le meilleur observe
(+6,97 %, qui etait « au plus bas x ipfs ») tombe DANS ce nuage.** La barre du balayage n est donc
pas franchie par l ensemble de la recherche.

Ce qui distingue quand meme cette conjonction : la barre est dominee par les petits echantillons
(n = 86, 103, 129) qui tirent des extremes, alors que FREIN x BANDE porte sur 392 tickets ; son p
individuel de 0,004 et sa robustesse au retrait des trois meilleurs ne s expliquent pas par la
multiplicite seule. C est un argument, pas une preuve -- d ou le gel.

CAUSALITE, le point critique du frein : un ticket decide a t ne rend son resultat qu a t+242 s. Le
taux de gagnants ne compte donc QUE les tickets deja CLOTURES avant t. Utiliser les tickets encore
ouverts serait lire l avenir, et c est ce qui a fabrique de faux regimes plus tot dans ce projet.

CRITERE, FIGE, au premier atteint de 800 tickets posterieurs au gel ou de 21 jours :
  (a) la conjonction doit faire MIEUX que `RISQUE seul` sur EXACTEMENT les memes tickets ;
  (b) elle doit etre positive sur les DEUX moities chronologiques ;
  (c) elle doit rester positive en retirant ses TROIS MEILLEURS tickets.
Les trois, sinon la piste est abandonnee et ecrite comme telle.

La production ne lit pas ce fichier. Lecture seule sur `papier_combo`.
"""
from __future__ import annotations

import bisect
import os
import sqlite3
import statistics as st

GEL_FB = 1789741800.0             # 18/09/2026 16h30 UTC = 18h30 Paris
BANDE = (0.20, 0.35)
FENETRE, SEUIL = 20, 0.50         # le frein : taux de gagnants des 20 derniers CLOTURES
SEUIL_RISQUE = 0.2694
COUT, TENUE_S, PLAFOND = 0.0262, 242.0, 3.0
N_CRITERE, JOURS_CRITERE = 800, 21
BASE = os.environ.get("COMBO_DB", "/app/db/papier_combo.sqlite")


def serie(ici: sqlite3.Connection):
    """(instant, risque, net) pour tous les tickets de `RISQUE seul`, tries."""
    return [(t, rq, min(b - COUT, PLAFOND)) for t, rq, b in ici.execute(
        "SELECT d.t_dec, d.risque, i.brut_240 FROM decision d JOIN issue i ON i.pair = d.pair"
        " WHERE d.eligible = 1 AND i.brut_240 IS NOT NULL AND d.risque IS NOT NULL"
        " AND d.risque <= ? ORDER BY d.t_dec", (SEUIL_RISQUE,))]


def retenus(R):
    """(instant, pris_par_la_conjonction, net) -- le frein ne voit QUE les tickets clotures."""
    clos = sorted((t + TENUE_S, r) for t, _q, r in R)
    tc = [x[0] for x in clos]
    out = []
    for t, rq, r in R:
        i = bisect.bisect_right(tc, t)
        if i < FENETRE:
            continue
        frein = sum(1 for k in range(i - FENETRE, i) if clos[k][1] > 0) / FENETRE > SEUIL
        out.append((t, bool(frein and BANDE[0] <= rq < BANDE[1]), r))
    return out


def rapport(ici: sqlite3.Connection, mise: float = 25.0) -> None:
    R = [x for x in serie(ici) if x[0] >= GEL_FB]
    D = retenus(R)
    pris = [r for _, ok, r in D if ok]
    print("\nFREIN x BANDE · PRE-ENREGISTRE le 18/09 a 18h30 Paris")
    print("   %d ticket(s) retenus depuis le gel, sur les %d du critere" % (len(pris), N_CRITERE))
    if len(pris) < 30:
        print("   CRITERE : mieux que RISQUE seul, positive sur les deux moities,")
        print("             et positive sans ses trois meilleurs tickets.")
        return
    tous = [r for _, _, r in D]
    vt = [(t, r) for t, ok, r in D if ok]
    m = len(vt) // 2
    h1, h2 = st.mean(x[1] for x in vt[:m]), st.mean(x[1] for x in vt[m:])
    s3 = st.mean(sorted(pris, reverse=True)[3:])
    print("   RISQUE seul    n=%4d · %+6.2f %%" % (len(tous), 100 * st.mean(tous)))
    print("   FREIN x BANDE  n=%4d · %+6.2f %% · %+7.0f EUR · moities %+6.2f/%+6.2f · sans 3 best %+6.2f %%"
          % (len(pris), 100 * st.mean(pris), mise * sum(pris), 100 * h1, 100 * h2, 100 * s3))
    a = st.mean(pris) > st.mean(tous)
    b = h1 > 0 and h2 > 0
    d = s3 > 0
    print("   (a) mieux que RISQUE seul : %s · (b) deux moities : %s · (c) sans 3 meilleurs : %s"
          % ("oui" if a else "NON", "oui" if b else "NON", "oui" if d else "NON"))
    print("   -> %s" % ("CRITERE TENU" if (a and b and d) else "critere non atteint a ce stade"))
    print("   CRITERE, a %d tickets ou %d jours : les trois, sinon abandon." % (N_CRITERE, JOURS_CRITERE))


if __name__ == "__main__":
    rapport(sqlite3.connect("file:%s?mode=ro" % BASE, uri=True, timeout=60))
