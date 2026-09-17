"""ENSEMBLE DE MODELES, PRE-ENREGISTRE le 17/09 a 23h30 UTC (18/09 01h30 Paris).

POURQUOI. LightGBM tire au sort 80 % des lignes et 70 % des variables a chaque arbre : deux
entrainements sur les MEMES donnees avec la MEME recette donnent deux modeles differents. Mesure
du 18/09 sur 96 entrainements identiques, appliques aux memes 1 568 tickets vivants :

    un seul modele      de -252 a +348 EUR · ecart-type 117 EUR · 30 % des tirages PERDENT
    ensemble de 12      de  +38 a +190 EUR · ecart-type  54 EUR · 8 sur 8 positifs

Le modele en service est donc UN TIRAGE parmi ceux-la, et il se trouve etre au-dessus de la
moyenne (+140 EUR contre +66 de moyenne). Ce n est pas une qualite de la strategie, c est de la
chance -- et c est aussi pourquoi aucun chiffre ne tenait en place : je comparais des tirages.

CE QUE L ENSEMBLE APPORTE, ET CE QU IL N APPORTE PAS. Il ne cherche pas a gagner plus : son gain
de moyenne (+66 -> +125 EUR) reste dans le bruit. Il supprime une LOTERIE qu on subissait sans le
savoir. La reduction d ecart-type, elle, n est pas une decouverte mais de l arithmetique : moyenner
douze tirages divise l ecart-type par racine de douze.

CE QUI NE CHANGE PAS. Le modele en service continue de decider, seul, exactement comme avant. Cet
ensemble est note EN PARALLELE sur les variables deja enregistrees par `papier_combo` -- il ne
touche ni le collecteur, ni les tests geles en cours. C est un rejeu, pas une mise en production.

CRITERE, FIGE : au premier atteint de 1 000 tickets posterieurs au gel ou de 21 jours, l ensemble
doit faire MIEUX que le modele en service sur EXACTEMENT les memes tickets. La comparaison est
appariee -- meme marche, memes jetons, seul le score change -- et c est la seule question qui
compte : la loterie coutait-elle de l argent ?
"""
from __future__ import annotations

import json
import math
import os
import sqlite3

GEL_ENSEMBLE = 1789687800.0        # 17/09/2026 23h30 UTC = 18/09 01h30 Paris
CHEMIN = os.environ.get("ENSEMBLE_VIDAGE", "/app/data/recherche/balayage/ensemble_vidage.json")
CHEMIN_FORET = os.environ.get("FORET_VIDAGE", "/app/data/recherche/balayage/foret_vidage.json")
N_CRITERE, JOURS_CRITERE = 1000, 21
ZERO = 1e-35


def _feuille(noeud, x):
    """Descendre un arbre. Copie volontaire de `arbres.py` : ce module doit pouvoir etre lu seul."""
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


class Ensemble:
    """Douze modeles, une moyenne. Le seuil est le 80e centile de cette moyenne, calcule sur les
    donnees d apprentissage -- jamais sur celles qui le jugeront.

    Deux formats de fichier, et la difference n est pas cosmetique :
      - BOOSTING (`sigmoide` absent ou vrai) : les feuilles sont des scores qui s ADDITIONNENT
        dans un modele, et la sigmoide s applique a leur somme. On moyenne ensuite les
        probabilites, pas les scores bruts -- les deux donnent des resultats differents.
      - FORET (`sigmoide` faux) : chaque feuille porte deja une proportion de classe, et le modele
        est la MOYENNE de ses arbres. Aucune sigmoide, aucune somme.
    Une foret ne sait pas non plus traiter une valeur absente : elle a ete entrainee sur des
    donnees ou les trous avaient ete remplaces par la mediane d apprentissage, qu on transporte
    donc avec elle (`medianes`).
    """

    def __init__(self, chemin: str = CHEMIN) -> None:
        d = json.load(open(chemin, encoding="utf-8"))
        self.variables = d["feature_names"]
        self.seuil_p80 = d["seuil_p80"]
        self.sigmoide = bool(d.get("sigmoide", True))
        self.medianes = d.get("medianes") or {}
        self.modeles = [[t["tree_structure"] for t in m["tree_info"]] for m in d["modeles"]]

    def probabilite(self, valeurs: dict) -> float:
        x = []
        for v in self.variables:
            a = valeurs.get(v)
            if a is None or (isinstance(a, float) and math.isnan(a)):
                a = self.medianes.get(v)           # vide pour un boosting : le NaN passe tel quel
            x.append(float("nan") if a is None else float(a))
        total = 0.0
        for arbres in self.modeles:
            if self.sigmoide:
                total += 1.0 / (1.0 + math.exp(-sum(_feuille(t, x) for t in arbres)))
            else:
                total += sum(_feuille(t, x) for t in arbres) / len(arbres)
        return total / len(self.modeles)


def rapport(ici: sqlite3.Connection, mise: float = 25.0, cout: float = 0.0262) -> None:
    """L ensemble contre le modele en service, sur EXACTEMENT les memes tickets."""
    modeles = []
    for nom, chemin in (("ENSEMBLE de 12", CHEMIN), ("FORET ALEATOIRE", CHEMIN_FORET)):
        try:
            modeles.append((nom, Ensemble(chemin)))
        except FileNotFoundError:
            print("\n%s : fichier absent (%s)" % (nom, chemin))
    if not modeles:
        return
    rows = ici.execute("""SELECT d.risque, d.variables, i.brut_240 FROM decision d
                          JOIN issue i ON i.pair=d.pair WHERE d.eligible=1 AND i.brut_240 IS NOT NULL
                          AND d.risque IS NOT NULL AND d.variables IS NOT NULL AND d.t_dec >= ?
                          ORDER BY d.t_dec""", (GEL_ENSEMBLE,)).fetchall()
    print("\nENSEMBLE DE 12 MODELES · PRE-ENREGISTRE le 18/09 a 01h30 Paris")
    print("   %d ticket(s) depuis le gel, sur les %d du critere" % (len(rows), N_CRITERE))
    if rows:
        serv = []
        autres = {nom: [] for nom, _ in modeles}
        for risque, var, brut in rows:
            net = min(brut - cout, 3.0)
            f = json.loads(var)
            if risque <= 0.2694:
                serv.append(net)
            for nom, m in modeles:
                if m.probabilite(f) <= m.seuil_p80:
                    autres[nom].append(net)
        for nom, v in [("modele en service", serv)] + [(n, autres[n]) for n, _ in modeles]:
            if v:
                print("   %-20s n=%4d · %+7.2f %% · %+7.0f EUR"
                      % (nom, len(v), 100 * sum(v) / len(v), mise * sum(v)))
        for nom, _ in modeles:
            if serv and autres[nom]:
                ecart = mise * (sum(autres[nom]) - sum(serv))
                print("   -> %-18s %+7.0f EUR contre le modele en service · %s"
                      % (nom, ecart, "MIEUX" if ecart > 0 else "moins bien"))
    print("   CRITERE : faire mieux que le modele en service sur les memes tickets, a %d tickets ou %d jours."
          % (N_CRITERE, JOURS_CRITERE))


if __name__ == "__main__":
    rapport(sqlite3.connect("file:/app/db/papier_combo.sqlite?mode=ro", uri=True, timeout=30))
