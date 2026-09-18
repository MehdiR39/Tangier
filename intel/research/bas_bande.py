"""AU PLUS BAS + BANDE, PRE-ENREGISTRE le 18/09/2026 a 09h30 UTC (11h30 Paris).

L IDEE, VENUE DE MIDO. « Limiter une perte est un element indispensable d une strategie gagnante. »
Exact, et c est la MOITIE du travail. Ce projet a mesure les deux moities separement :

  BANDE 0,20-0,35   limite la casse -- on evite les jetons trop morts (qui ne montent jamais) et
                    les trop dangereux ; c est un filtre sur la probabilite de vidage predite.
  AU PLUS BAS       grossit le gain -- gros gains >= +50 % multiplies par 2,32 (p < 0,0001) sans
                    augmentation mesurable des catastrophes (x1,20, p = 0,232) (§3.116).

Aucune des deux ne suffit seule. Leur conjonction est la PREMIERE regle du projet a passer les
trois controles qu on applique depuis le debut :

| | n | net | moities | sans ses 3 meilleurs | p contre le hasard |
|---|---|---|---|---|---|
| temoin | 1 892 | -2,35 % | -1,93 / -2,77 | -2,83 | 0,498 |
| RISQUE seul | 1 320 | -0,58 % | -0,73 / -0,43 | -1,26 | 0,121 |
| AU PLUS BAS | 421 | +0,89 % | +2,61 / -0,82 | -1,25 | 0,129 |
| au plus bas + RISQUE | 205 | +3,42 % | -1,98 / +8,77 | -0,98 | 0,074 |
| **au plus bas + BANDE** | **268** | **+5,10 %** | **+5,98 / +4,22** | **+1,76** | **0,017** |

Taux de gros gains de la conjonction : **21,6 %**.

TROIS RAISONS DE SE MEFIER, ecrites avant de voir la suite.
  1. C est une COMBINAISON CHOISIE APRES AVOIR REGARDE, parmi plusieurs essayees. Le p de 0,017 ne
     tient pas compte de cette multiplicite.
  2. Elle repose sur la BANDE, qui vient d ECHOUER seule hors echantillon : -8,38 % par ticket sur
     244 tickets posterieurs a son propre gel (§3.111). Qu elle aide ici ne la rehabilite pas.
  3. 2,8 jours de donnees. La bande affichait +3,90 % sur une fenetre comparable avant de mourir.

PUISSANCE, CALCULEE AVANT DE FIGER. Ecart-type du net : 79,3 points par ticket. Detecter l effet
observe (+5,1 pt) demande 1 893 tickets ; un effet moitie (+2,5 pt) en demanderait 7 879. On
dimensionne donc a 1 200 tickets -- ce qui ne tranche PAS le net a lui seul -- et on ajoute deux
conditions de robustesse qui, elles, se lisent a cet effectif. Flux mesure : 96 tickets par jour,
soit ~13 jours.

CRITERE, FIGE, au premier atteint de 1 200 tickets posterieurs au gel ou de 21 jours :
  (a) le NET apres les 2,62 pts mesures doit etre POSITIF ;
  (b) il doit rester positif sur les DEUX moities chronologiques ;
  (c) il doit rester positif en retirant les TROIS MEILLEURS tickets -- c est ce controle, et non
      le p, qui a demasque toutes les fausses pistes de ce projet.
Les trois, sinon la piste est abandonnee et ecrite comme telle.

CE QUI NE CHANGE PAS. La production ne decide rien a partir de ce fichier. Lecture seule sur
`papier_combo`, aucun processus lance, aucune base ecrite. Aucun collecteur en marche, aucun des six
autres gels, n est touche.
"""
from __future__ import annotations

import json
import os
import sqlite3
import statistics as st

GEL_BB = 1789723800.0             # 18/09/2026 09h30 UTC = 11h30 Paris
BANDE = (0.20, 0.35)              # la meme bande que papier_combo, inchangee
COUT = 0.0262                     # cout d execution mesure sur 244 tickets reels
PLAFOND = 3.0
N_CRITERE, JOURS_CRITERE = 1200, 21
BASE = os.environ.get("COMBO_DB", "/app/db/papier_combo.sqlite")


def retenu(f: dict, risque: float | None) -> bool | None:
    """Les DEUX conditions. None si une variable manque -- on n invente pas un ticket.

    `depuis_min` = prix/min - 1, donc exactement 0 quand le prix a 45 s EST son plus bas depuis la
    naissance. NaN est ecarte AVANT la comparaison : une comparaison avec NaN est toujours fausse
    et ferait silencieusement basculer le ticket du mauvais cote.
    """
    if risque is None:
        return None
    x = f.get("depuis_min")
    if x is None or x != x:
        return None
    return float(x) <= 1e-9 and BANDE[0] <= risque < BANDE[1]


def tickets(ici: sqlite3.Connection, depuis: float = GEL_BB) -> list[tuple[float, float]]:
    out = []
    for t, vj, risque, b in ici.execute(
            "SELECT d.t_dec, d.variables, d.risque, i.brut_240 FROM decision d"
            " JOIN issue i ON i.pair = d.pair WHERE d.eligible = 1 AND i.brut_240 IS NOT NULL"
            " AND d.variables IS NOT NULL AND d.t_dec >= ? ORDER BY d.t_dec", (depuis,)):
        try:
            f = json.loads(vj)
        except Exception:  # noqa: BLE001
            continue
        if retenu(f, risque):
            out.append((t, min(b - COUT, PLAFOND)))
    return out


def rapport(ici: sqlite3.Connection, mise: float = 25.0) -> None:
    v = tickets(ici)
    print("\nAU PLUS BAS + BANDE · PRE-ENREGISTRE le 18/09 a 11h30 Paris")
    print("   %d ticket(s) depuis le gel, sur les %d du critere" % (len(v), N_CRITERE))
    if len(v) < 8:
        print("   CRITERE : net positif, sur les deux moities, et sans ses trois meilleurs tickets.")
        return
    r = [x[1] for x in v]
    m = len(r) // 2
    h1, h2 = st.mean(r[:m]), st.mean(r[m:])
    s3 = st.mean(sorted(r, reverse=True)[3:])
    print("   NET %+.2f %% · %+.0f EUR · moities %+.2f %% / %+.2f %% · sans 3 meilleurs %+.2f %%"
          % (100 * st.mean(r), mise * sum(r), 100 * h1, 100 * h2, 100 * s3))
    print("   gros gains >= +50 %% : %.1f %%" % (100 * sum(1 for x in r if x >= 0.50) / len(r)))
    a, b, d = st.mean(r) > 0, (h1 > 0 and h2 > 0), s3 > 0
    print("   (a) net positif : %s · (b) deux moities : %s · (c) sans 3 meilleurs : %s"
          % ("oui" if a else "NON", "oui" if b else "NON", "oui" if d else "NON"))
    print("   -> %s" % ("CRITERE TENU" if (a and b and d) else "critere non atteint a ce stade"))
    print("   CRITERE, a %d tickets ou %d jours : les trois, sinon abandon." % (N_CRITERE, JOURS_CRITERE))


if __name__ == "__main__":
    rapport(sqlite3.connect("file:%s?mode=ro" % BASE, uri=True, timeout=60))
