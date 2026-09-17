"""PISTE PRE-ENREGISTREE : la foule ajoute-t-elle de l information DANS la bande de risque ?

Pourquoi cette question. Le 17/09 on a etabli deux choses. D abord que le modele de vidage ne
mesure pas le danger mais la VIE, ce qui a donne la bande [0,20 ; 0,35[ (voir `papier_combo.py`).
Ensuite qu a l interieur de cette bande, AUCUNE des 17 variables de prix ne garde de pouvoir
predictif sur deux moities chronologiques : l information de prix est epuisee. Restent les
variables NON-PRIX, que le modele n a jamais vues. Le collecteur large en enregistre une qui ne
doit rien au prix : le nombre d ACHETEURS UNIQUES avant la decision.

Ce qu on a vu, et qui ne prouve RIEN. Sur les 251 tickets deja croises, couper a la mediane des
acheteurs donne +10,8 % puis +6,7 % en faveur du groupe haut sur les deux moities. Meme signe des
deux cotes -- mais la barre de bruit, obtenue en melangeant les valeurs 400 fois, est de +/-20 %.
L ecart observe est donc PLUS PETIT que ce que le hasard produit couramment. Avec un ecart-type de
70 points par ticket, 251 tickets ne permettent de voir aucun effet sous ~25 points. Le test n est
pas negatif : il est sous-alimente. D ou ce pre-enregistrement, pour que la reponse a venir soit un
vrai test et non une trouvaille d apres coup.

CE QUI EST FIGE ICI, AVANT LES DONNEES :
  - population : tickets de la bande [0,20 ; 0,35[ joignables avec le collecteur large ;
  - coupure : SEUIL = 91 acheteurs, la mediane observee AVANT le gel -- fixee une fois pour
    toutes, jamais reajustee, sinon on refait le seuil sur les donnees qu il doit juger ;
  - direction annoncee : le groupe >= 91 acheteurs rend PLUS que le groupe < 91 ;
  - critere : ecart >= +10 points, de MEME SIGNE sur les deux moities chronologiques ;
  - echeance : 1 568 tickets posterieurs au gel (la taille calculee pour detecter 10 points avec
    un ecart-type de 70) ou 21 jours, au premier atteint. Sinon la piste est abandonnee.

Lecture seule stricte : ce module n ecrit jamais dans les bases des tests en cours.
"""
from __future__ import annotations

import math
import sqlite3
import statistics as st

BASE_COMBO = "file:/app/db/papier_combo.sqlite?mode=ro"
BASE_LARGE = "file:/app/db/papier_large.sqlite?mode=ro"

GEL_FOULE = 1789675200.0        # 17/09/2026 20h00 UTC = 22h00 Paris
SEUIL_FOULE = 91                # mediane des acheteurs dans la bande avant le gel
CRITERE_FOULE = 0.10            # ecart minimal entre groupe haut et groupe bas
N_FOULE = 1568                  # taille calculee : 32 * (0,70 / 0,10)^2, avec 0,70 l ecart-type mesure
JOURS_FOULE = 21
BANDE = (0.20, 0.35)


def _propre(x) -> bool:
    """Un NaN ne leve pas d erreur, il fabrique un resultat : on l ecarte avant tout tri."""
    return isinstance(x, (int, float)) and not (isinstance(x, float) and math.isnan(x))


def tickets(ici: sqlite3.Connection, depuis: float = GEL_FOULE) -> list[dict]:
    ici.execute("ATTACH DATABASE '%s' AS L" % BASE_LARGE)
    rows = ici.execute(
        """SELECT d.t_dec, i.brut_240, d.cout_reduit, g.acheteurs
           FROM decision d JOIN issue i ON i.pair = d.pair JOIN L.decision g ON g.pair = d.pair
           WHERE d.eligible = 1 AND i.brut_240 IS NOT NULL AND d.risque IS NOT NULL
           AND d.risque >= ? AND d.risque < ? AND d.t_dec >= ? ORDER BY d.t_dec""",
        (BANDE[0], BANDE[1], depuis)).fetchall()
    return [{"t": t, "r": min(b - c, 3.0), "foule": a}
            for t, b, c, a in rows if _propre(a)]


def ecart(part: list[dict]) -> float | None:
    """Rendement moyen du groupe >= SEUIL moins celui du groupe < SEUIL."""
    haut = [x["r"] for x in part if x["foule"] >= SEUIL_FOULE]
    bas = [x["r"] for x in part if x["foule"] < SEUIL_FOULE]
    if len(haut) < 20 or len(bas) < 20:
        return None
    return st.mean(haut) - st.mean(bas)


def rapport(ici: sqlite3.Connection) -> None:
    t = tickets(ici)
    print("\nPISTE FOULE (>= %d acheteurs) DANS LA BANDE · PRE-ENREGISTREE le 17/09 a 22h00 Paris"
          % SEUIL_FOULE)
    print("   %d ticket(s) depuis le gel, sur les %d du critere" % (len(t), N_FOULE))
    if t:
        m = len(t) // 2
        e1, e2, tout = ecart(t[:m]), ecart(t[m:]), ecart(t)
        if tout is not None:
            print("   ecart global %+.2f %%" % (100 * tout))
        if e1 is not None and e2 is not None:
            tenu = e1 > CRITERE_FOULE and e2 > CRITERE_FOULE
            print("   moities %+.2f %% / %+.2f %%   -> %s"
                  % (100 * e1, 100 * e2, "CRITERE TENU" if tenu else "critere non atteint"))
    print("   CRITERE : ecart >= +%.0f points, meme signe sur les deux moities, a %d tickets ou %d jours."
          % (100 * CRITERE_FOULE, N_FOULE, JOURS_FOULE))


if __name__ == "__main__":
    rapport(sqlite3.connect(BASE_COMBO, uri=True, timeout=30))
