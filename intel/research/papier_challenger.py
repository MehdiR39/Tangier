"""LE FLUX SCORE DU CHALLENGER, en direct — la piece qui manque pour pouvoir adopter un modele.

POURQUOI IL EXISTE. Un modele reentraine ne peut PAS etre mis en production tel quel, et la raison
n est pas le modele : c est LA PAUSE. Elle doit voir le flux ENTIER de sa bande -- tous les tickets
de bande qui cloturent, pas seulement ceux qu on achete -- sinon elle observe moins de clotures, se
releve plus vite et prend plus de tickets que la regle mesuree (c est le blocage circulaire du
18/09, et c est ecrit dans `modele_rapide.pause_ouverte`).

Or ce flux n existe nulle part pour un modele frais : `papier_combo.sqlite` ne stocke que les scores
du modele EN SERVICE. Adopter un challenger sans ce carnet ferait tourner sa bande SANS pause --
c est-a-dire la version qui perd **106 EUR/jour** (mesure du 26/09 sur 3 032 tickets).

CE QUE FAIT CE MODULE : rien de neuf. Il est une SECONDE INSTANCE de `papier_combo`, avec un autre
modele et une autre base, exactement comme `papier_large` est une seconde instance de
`papier_gd_direct`. Module a part pour que le gardien le voie sous son propre nom et le relance s il
tombe -- les trois instances papier sont mortes le 18/09 a 9h14 sans que personne ne le voie
(§3.149). Aucun ordre, aucune cle, aucune ecriture ailleurs que dans sa propre base.

LE MODELE LU EST `modele_dump.json`, JAMAIS `modele.json`. Les deux formats sont incompatibles :
`arbres.Modele` (que ce carnet et le moteur utilisent, faute de LightGBM dans le conteneur) lit un
`dump_model()`, tandis que `modele.json` est un `save_model()`. Le gel ecrit les deux ; ici on prend
le dump. Voir `challenger.geler`, qui verifie en plus que le dump porte les VRAIS noms de variables
-- sans quoi le modele serait muet en silence.

QUEL CHALLENGER ? Le plus recent de `CHALLENGERS`, ou celui que `CHALLENGER_DIR` designe.

Lancement : python -m intel.research.papier_challenger
"""
from __future__ import annotations

import json
import os
import sys

DOSSIER = os.environ.get("CHALLENGERS", "/app/data/recherche/challengers")


def _choisi() -> str:
    """Le dossier du challenger a scorer, et il doit etre EXPLICITE dans les logs.

    Si on se trompe de gel, tout le carnet est faux sans que rien ne le signale : on affiche donc
    lequel on a pris, avec sa date et son numero d essai.
    """
    d = os.environ.get("CHALLENGER_DIR")
    if not d:
        if not os.path.isdir(DOSSIER):
            raise SystemExit("aucun challenger gele dans %s — `challenger.py --geler` d abord" % DOSSIER)
        gels = sorted(x for x in os.listdir(DOSSIER)
                      if os.path.exists(os.path.join(DOSSIER, x, "modele_dump.json")))
        if not gels:
            raise SystemExit("aucun gel exploitable dans %s (il faut `modele_dump.json`)" % DOSSIER)
        d = os.path.join(DOSSIER, gels[-1])
    meta = json.load(open(os.path.join(d, "meta.json")))
    print("papier_challenger : gel du %s, essai n°%s, bande [%.4f ; %.4f]"
          % (meta.get("gel_lisible", "?"), meta.get("essai", "?"),
             meta["bande"][0], meta["bande"][1]), flush=True)
    return d


CHOISI = _choisi()
os.environ["MODELE_VIDAGE"] = os.path.join(CHOISI, "modele_dump.json")
os.environ.setdefault("PAPIER_COMBO_DB", "/app/db/papier_challenger.sqlite")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from papier_combo import main  # noqa: E402

if __name__ == "__main__":
    main()
