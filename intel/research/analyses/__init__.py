"""ANALYSES PONCTUELLES, rangees ici le 27/09/2026 — aucune ne tourne en continu, rien n en depend.

Ce sont les etudes qui ont produit les mesures du journal. Elles ont ete deplacees de
`intel/research/` sans etre modifiees, sauf sur un point : chaque `os.path.dirname(os.path.abspath(
__file__))` a recu un `os.path.dirname` de plus, pour qu elles calculent EXACTEMENT les memes chemins
qu avant (elles se croient toujours dans `intel/research/`).

Lancement : `python -m intel.research.analyses.<nom>` (le journal les cite parfois sous l ancien
nom `intel.research.<nom>`). Ce fichier met `intel/research/` et ce dossier dans le chemin
d import, pour que leurs `from arbres import ...` et imports entre analyses fonctionnent comme avant.
"""
import os as _os
import sys as _sys

for _d in (_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
           _os.path.dirname(_os.path.abspath(__file__))):
    if _d not in _sys.path:
        _sys.path.insert(0, _d)
