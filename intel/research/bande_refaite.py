"""OU EST VRAIMENT L ARGENT DANS LE SCORE DE RISQUE ? La bande, redeterminee proprement.

MIDO, 20/09 : « le document c est pas la bible, ca a ete ecrit par nous, c est les chiffres qui
parlent. Et si t es pas satisfait de la facon dont la bande est determinee, trouve mieux, c est ton
travail. »

CE QUI NE VA PAS DANS LA BANDE ACTUELLE. [0,20 ; 0,35[ a ete lue a l oeil sur les QUINTILES de
1 356 tickets le 17/09 : « le quintile le plus sur n a aucun gain > +50 %, le plus risque a 33 % de
chutes mais 18 % de gros gains ». Le raisonnement est juste -- c est meme le diagnostic de §3.159,
trois jours avant -- mais la BORNE, elle, n a jamais ete mesuree : un quintile est un decoupage
arbitraire en cinq, pas un optimum. Et 1 356 tickets, c est le quart de ce qu on a aujourd hui.

COMMENT ON LA REFAIT SANS SE MENTIR. Chercher la meilleure fenetre sur toutes les donnees puis
l annoncer, c est garantir un beau chiffre qui ne survivra pas -- c est exactement ce qui a tue
BAS + BANDE, FREIN x BANDE et RISQUE + FREIN. Donc :
  1. on coupe les tickets en DEUX MOITIES chronologiques ;
  2. on cherche la meilleure fenetre sur la PREMIERE seulement ;
  3. on la juge sur la SECONDE, qu on n a pas regardee ;
  4. et on compare a la bande actuelle sur cette meme seconde moitie.
Si la fenetre trouvee ne bat pas [0,20 ; 0,35[ hors echantillon, on garde l ancienne et on le dit.

Papier, zero euro, lecture seule.
"""
from __future__ import annotations

import os
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

COUT = float(os.environ.get("COUT_MESURE", "0.0367"))
MISE = 20.0
V = 17.5845
BANDE_ACTUELLE = (0.20, 0.35)
PAS = 0.025                        # grille de recherche des bornes
LARGEUR_MIN = 0.05
N_MIN = 40                         # une fenetre qui garde moins que ca ne se mesure pas


def charger():
    c = sqlite3.connect("file:/app/db/papier_combo.sqlite?mode=ro", uri=True, timeout=30)
    L = []
    for t, risque, q, b in c.execute(
            "SELECT d.t_dec, d.risque, d.q, i.brut_240 FROM decision d JOIN issue i"
            " ON i.pair=d.pair WHERE d.eligible=1 AND i.brut_240 IS NOT NULL"
            " AND d.risque IS NOT NULL AND d.q IS NOT NULL ORDER BY d.t_dec"):
        cout = COUT + 2 * (MISE * 0.31 / 30.0) / (float(q) + V)
        L.append((float(t), float(risque), MISE * min(float(b) - cout, 3.0)))
    return L


def gain(L, a, b):
    v = [x[2] for x in L if a <= x[1] < b]
    return (sum(v) / len(v), len(v), sum(v)) if v else (0.0, 0, 0.0)


def main() -> None:
    L = charger()
    if len(L) < 400:
        print("bande_refaite: %d tickets, trop peu" % len(L))
        return
    mi = len(L) // 2
    A, B = L[:mi], L[mi:]
    print("%d tickets · moitie 1 : %d · moitie 2 : %d · cout %.2f pt"
          % (len(L), len(A), len(B), 100 * COUT))
    print()

    # --- ce que le score fait, en clair, sur TOUT : la forme, pas encore une regle
    print("EUR/ticket PAR TRANCHE DE RISQUE (toutes donnees, pour voir la forme)")
    bornes = np.arange(0.0, 0.601, 0.05)
    for a, b in zip(bornes[:-1], bornes[1:]):
        m, n, tot = gain(L, a, b)
        if n:
            print("   [%.2f ; %.2f[  %4d tickets  %+7.3f EUR/ticket  %+8.0f EUR  %3.0f %% gagnants"
                  % (a, b, n, m, tot, 100 * sum(1 for x in L if a <= x[1] < b and x[2] > 0) / n))
    m, n, _ = gain(L, 0.0, 1.0)
    print("   TOUT           %4d tickets  %+7.3f EUR/ticket" % (n, m))
    print()

    # --- la recherche, sur la PREMIERE moitie seulement
    grille = np.arange(0.0, 0.701, PAS)
    best = None
    for i, a in enumerate(grille):
        for b in grille[i + 1:]:
            if b - a < LARGEUR_MIN:
                continue
            m, n, _ = gain(A, a, b)
            if n >= N_MIN and (best is None or m > best[0]):
                best = (m, a, b, n)
    if not best:
        print("bande_refaite: aucune fenetre exploitable sur la premiere moitie")
        return
    _, a, b, n_a = best
    print("MEILLEURE FENETRE SUR LA PREMIERE MOITIE : [%.3f ; %.3f[" % (a, b))
    print("   sur la moitie 1 (ou elle a ete choisie) : %+7.3f EUR/ticket · %d tickets"
          % (gain(A, a, b)[0], n_a))
    print()
    print("LE SEUL TEST QUI COMPTE -- la SECONDE moitie, jamais regardee :")
    print("   %-28s %6s %12s %11s" % ("", "n", "EUR/ticket", "total"))
    for nom, (x, y) in (("fenetre TROUVEE", (a, b)),
                        ("bande ACTUELLE [0,20;0,35[", BANDE_ACTUELLE),
                        ("tout prendre", (0.0, 1.0))):
        m, n, tot = gain(B, x, y)
        print("   %-28s %6d %+11.3f %+10.0f" % (nom, n, m, tot))
    print()
    # --- et la bande actuelle, sur tout ce qui suit son propre gel
    from papier_combo import GEL_BANDE
    P = [x for x in L if x[0] >= GEL_BANDE]
    print("LA BANDE ACTUELLE DEPUIS SON PROPRE GEL (%d tickets apres le 17/09 18h30) :" % len(P))
    for nom, (x, y) in (("bande [0,20 ; 0,35[", BANDE_ACTUELLE), ("tout prendre", (0.0, 1.0))):
        m, n, tot = gain(P, x, y)
        s = np.std([z[2] for z in P], ddof=1) if len(P) > 1 else 0.0
        print("   %-28s %6d %+11.3f %+10.0f  (%.2f sigma sur le niveau)"
              % (nom, n, m, tot, m / (s / n ** 0.5) if n and s else 0.0))


if __name__ == "__main__":
    main()
