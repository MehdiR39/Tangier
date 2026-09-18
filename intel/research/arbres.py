"""Evaluer un modele LightGBM exporte en JSON, sans LightGBM (le conteneur ne l a pas).

`booster.dump_model()` decrit chaque arbre : variable, seuil, cote par defaut pour les valeurs absentes,
feuilles. La somme des feuilles donne le score brut ; la sigmoide, la probabilite. Verifie contre
LightGBM lui-meme avant usage (papier_combo_modele.py) : ecart maximal attendu < 1e-9.
"""
from __future__ import annotations

import json
import math

ZERO = 1e-35


def _feuille(noeud, x):
    while "leaf_value" not in noeud:
        v = x[noeud["split_feature"]]
        absent = v is None or (isinstance(v, float) and math.isnan(v))
        mt = noeud.get("missing_type", "None")
        if mt == "NaN":
            gauche = noeud["default_left"] if absent else v <= noeud["threshold"]
        elif mt == "Zero":
            gauche = noeud["default_left"] if (absent or abs(v) <= ZERO) else v <= noeud["threshold"]
        else:
            gauche = (0.0 if absent else v) <= noeud["threshold"]
        noeud = noeud["left_child"] if gauche else noeud["right_child"]
    return noeud["leaf_value"]


class Modele:
    def __init__(self, chemin: str):
        d = json.load(open(chemin, encoding="utf-8"))
        self.variables = d["feature_names"]
        self.arbres = [t["tree_structure"] for t in d["tree_info"]]
        self.seuil_p80 = d.get("seuil_p80")

    def probabilite(self, valeurs: dict) -> float:
        x = [valeurs.get(v) for v in self.variables]
        x = [float("nan") if (a is None) else float(a) for a in x]
        brut = sum(_feuille(t, x) for t in self.arbres)
        return 1.0 / (1.0 + math.exp(-brut))
