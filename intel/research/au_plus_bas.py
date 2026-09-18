"""ACHETER AU PLUS BAS, PRE-ENREGISTRE le 18/09/2026 a 08h00 UTC (10h00 Paris).

LA QUESTION DE MIDO. « Le probleme vient des grosses pertes ; peut-on les eviter, les prevoir ? »
Reponse mesuree : **non, et ce n est pas la bonne question.** Aucune variable disponible a 45 s ne
predit la catastrophe sans predire aussi le gain -- `risque` atteint AUC 0,674 sur les chutes a
-70 % hors echantillon, mais 0,730 sur les gains a +50 %, du MEME cote. C est le resultat central du
projet, retrouve une nouvelle fois : le modele mesure la VIE, pas le danger.

UNE SEULE VARIABLE FAIT EXCEPTION. `depuis_min` = prix a 45 s rapporte a son minimum depuis la
naissance. Son AUC catastrophe (0,563) et son AUC gros-gain (0,481) partent de cotes OPPOSES. Et
son premier quintile n est pas un seuil taille dans les donnees : c est la valeur EXACTE zero,
c est-a-dire **le prix a 45 s EST son plus bas depuis la naissance**. Le jeton n a fait que
descendre, il n a pas rebondi.

CE QUE ÇA CHANGE, sur 418 tickets contre 1 454 (tests de PERMUTATION, 5 000 melanges) :

| | au plus bas | le reste | rapport | p |
|---|---|---|---|---|
| gros gains >= +50 % | **19,6 %** | 8,5 % | **x2,32** | **< 0,0001** |
| tres gros >= +100 % | **8,6 %** | 3,0 % | **x2,87** | **< 0,0001** |
| catastrophes <= -70 % | 13,4 % | 11,2 % | x1,20 | **0,232 (non signif.)** |
| gagnants | 46,4 % | 64,9 % | x0,72 | < 0,0001 |

**Les gros gains plus que DOUBLENT sans que les catastrophes augmentent de facon mesurable.** On ne
supprime pas la queue gauche -- on epaissit la queue droite. On gagne plus rarement (46 % contre
65 %) et beaucoup plus gros. C est la premiere fois qu une variable separe les deux ici.

CE QU IL NE FAUT PAS SE RACONTER. Le NET n est PAS demontre : +1,07 % contre -2,45 % pour le
temoin, mais p = 0,098 contre un tirage au hasard de meme taille, deuxieme moitie chronologique
negative (-0,69 %), et **negatif en retirant ses trois meilleurs tickets (-1,07 %)**. Par jour :
+274 / -77 / +201 / -287 EUR. Ce qui est solide, c est le DEPLACEMENT DES TAUX ; le gain en euros
ne l est pas.

POURQUOI LE CRITERE PORTE SUR LE TAUX ET PAS SEULEMENT SUR L ARGENT. L ecart-type du net est de
74 points par ticket : detecter +3,5 pt demanderait **3 503 tickets**. Le taux de gros gains, lui,
se tranche en **352 tickets** pour un rapport de 1,8. On juge donc d abord ce qui est mesurable, et
on exige quand meme que l argent suive. Flux mesure : 151 tickets « au plus bas » par jour.

CRITERE, FIGE, au premier atteint de 800 tickets posterieurs au gel ou de 21 jours :
  (a) le taux de gros gains (>= +50 %) doit rester au moins **1,5 fois** celui des autres tickets
      de la meme periode -- c est la partie bien mesuree, et 800 tickets la tranchent ;
  (b) le taux de catastrophes (<= -70 %) ne doit pas depasser **1,5 fois** celui des autres ;
  (c) le NET apres les 2,62 pts mesures doit etre positif, sur les deux moities chronologiques.
Les trois, sinon la piste est abandonnee et ecrite comme telle.

CE QUI NE CHANGE PAS. La production ne decide rien a partir de ce fichier. Il relit `papier_combo`
en LECTURE SEULE, ne lance aucun processus, n ecrit dans aucune base. Aucun collecteur en marche,
aucun des cinq autres gels, n est touche.
"""
from __future__ import annotations

import json
import os
import sqlite3
import statistics as st

GEL_APB = 1789718400.0            # 18/09/2026 08h00 UTC = 10h00 Paris
COUT = 0.0262                     # cout d execution mesure sur 244 tickets reels
PLAFOND = 3.0
GROS, CATA = 0.50, -0.70          # les deux queues qu on surveille
RAPPORT_GAIN_MIN, RAPPORT_CATA_MAX = 1.5, 1.5
N_CRITERE, JOURS_CRITERE = 800, 21
BASE = os.environ.get("COMBO_DB", "/app/db/papier_combo.sqlite")


def au_plus_bas(f: dict) -> bool | None:
    """Le prix a 45 s est-il son plus bas depuis la naissance ? None si la variable manque.

    `depuis_min` vaut prix/min - 1, donc exactement 0 quand le dernier prix EST le minimum. On
    compare a une tolerance et non a zero strict, parce qu un flottant issu d une division peut
    valoir 1e-17 au lieu de 0. NaN est ecarte AVANT toute comparaison : une comparaison avec NaN
    est toujours fausse et ferait passer le ticket dans « pas au plus bas » en silence.
    """
    x = f.get("depuis_min")
    if x is None or x != x:
        return None
    return float(x) <= 1e-9


def tickets(ici: sqlite3.Connection, depuis: float = GEL_APB):
    """(t, au_plus_bas, net) pour chaque ticket analysable posterieur au gel."""
    out = []
    for t, vj, b in ici.execute(
            "SELECT d.t_dec, d.variables, i.brut_240 FROM decision d JOIN issue i ON i.pair = d.pair"
            " WHERE d.eligible = 1 AND i.brut_240 IS NOT NULL AND d.variables IS NOT NULL"
            " AND d.t_dec >= ? ORDER BY d.t_dec", (depuis,)):
        try:
            f = json.loads(vj)
        except Exception:  # noqa: BLE001
            continue
        bas = au_plus_bas(f)
        if bas is None:
            continue
        out.append((t, bas, min(b - COUT, PLAFOND)))
    return out


def rapport(ici: sqlite3.Connection, mise: float = 25.0) -> None:
    v = tickets(ici)
    bas = [x for x in v if x[1]]
    aut = [x for x in v if not x[1]]
    print("\nACHETER AU PLUS BAS · PRE-ENREGISTRE le 18/09 a 10h00 Paris")
    print("   %d ticket(s) « au plus bas » depuis le gel, sur les %d du critere"
          % (len(bas), N_CRITERE))
    if not bas or not aut:
        print("   CRITERE : gros gains >= %.1fx, catastrophes <= %.1fx, net positif sur les deux moities."
              % (RAPPORT_GAIN_MIN, RAPPORT_CATA_MAX))
        return
    taux = lambda s, c: sum(1 for x in s if c(x[2])) / len(s)
    g1, g0 = taux(bas, lambda r: r >= GROS), taux(aut, lambda r: r >= GROS)
    c1, c0 = taux(bas, lambda r: r <= CATA), taux(aut, lambda r: r <= CATA)
    net = st.mean(x[2] for x in bas)
    m = len(bas) // 2
    h1 = st.mean(x[2] for x in bas[:m]) if m else 0.0
    h2 = st.mean(x[2] for x in bas[m:]) if m else 0.0
    print("   gros gains   %5.1f %% contre %5.1f %%  -> x%.2f" % (100 * g1, 100 * g0, g1 / g0 if g0 else 0))
    print("   catastrophes %5.1f %% contre %5.1f %%  -> x%.2f" % (100 * c1, 100 * c0, c1 / c0 if c0 else 0))
    print("   NET %+.2f %% · %+.0f EUR · moities %+.2f %% / %+.2f %%"
          % (100 * net, mise * net * len(bas), 100 * h1, 100 * h2))
    a = g0 > 0 and g1 / g0 >= RAPPORT_GAIN_MIN
    b = c0 > 0 and c1 / c0 <= RAPPORT_CATA_MAX
    d = net > 0 and h1 > 0 and h2 > 0
    print("   (a) gros gains >= %.1fx : %s · (b) catastrophes <= %.1fx : %s · (c) net positif partout : %s"
          % (RAPPORT_GAIN_MIN, "oui" if a else "NON", RAPPORT_CATA_MAX, "oui" if b else "NON",
             "oui" if d else "NON"))
    print("   -> %s" % ("CRITERE TENU" if (a and b and d) else "critere non atteint a ce stade"))
    print("   CRITERE, a %d tickets ou %d jours : les trois, sinon abandon." % (N_CRITERE, JOURS_CRITERE))


if __name__ == "__main__":
    rapport(sqlite3.connect("file:%s?mode=ro" % BASE, uri=True, timeout=60))
