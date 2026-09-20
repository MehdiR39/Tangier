"""DE QUELLES VARIABLES LE MOTEUR PEUT-IL SE PASSER ? On mesure avant de coder.

Brancher `FORET 75s top 10 %` demande que le moteur produise ses 25 variables a 75 s. Trois groupes
posent un probleme, et il serait absurde d ecrire le code avant de savoir ce que chacun coute :

  img_l, img_centre, img_h    l image du jeton. Deja absente sur 49 % des tickets d ENTRAINEMENT
                              (1 679 sur 3 288) : le modele a appris avec la mediane a leur place.
  v1_robots, v1_part_robots   dependent d un etat GLOBAL et CHRONOLOGIQUE -- quels portefeuilles ont
                              deja ete vus dans des pools ANTERIEURS. Le moteur ne l a pas ; le
                              construire demande de rejouer tout l historique au demarrage.
  reg_moy_20                  le regime de marche, calcule sur les 20 derniers tickets clotures.

LA MESURE : on remplace chaque groupe par la MEDIANE D APPRENTISSAGE -- exactement ce que le
pipeline fait deja pour une valeur absente -- et on compte le pourcentage de DECISIONS qui changent.
Pas les probabilites : les decisions, parce que c est la seule chose qui achete ou non.

Si un groupe coute moins de ~1 %, on s en passe et on l ecrit dans l en-tete du modele. S il coute
plus, il faut le produire. La regle 10 du projet interdit de laisser une variable manquer en silence :
ici elle ne manque pas en silence, elle manque en connaissance de cause et avec son prix.
"""
from __future__ import annotations

import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DOSSIER = "/app/data/recherche/foret_gel75"

GROUPES = {
    "les 3 images": ["img_l", "img_centre", "img_h"],
    "les 2 robots": ["v1_robots", "v1_part_robots"],
    "le regime": ["reg_moy_20"],
    "images + robots": ["img_l", "img_centre", "img_h", "v1_robots", "v1_part_robots"],
    "images + robots + regime": ["img_l", "img_centre", "img_h", "v1_robots", "v1_part_robots",
                                 "reg_moy_20"],
}


def main() -> None:
    import joblib
    import foret_gel as G

    m = joblib.load(os.path.join(DOSSIER, "modele.pkl"))
    s = json.load(open(os.path.join(DOSSIER, "seuils.json"), encoding="utf-8"))
    rf, med, garde = m["rf"], m["med"], s["garde"]
    seuil = float(s["seuil10"])

    df, _ = G.table()
    X = df[garde].apply(pd.to_numeric, errors="coerce").astype(float).fillna(med).fillna(0.0)
    ref = rf.predict_proba(X)[:, 1] >= seuil
    print("%d tickets · seuil top 10 %% = %.4f · retenus de reference : %d"
          % (len(X), seuil, int(ref.sum())), flush=True)
    print()
    print("   %-28s %12s %14s %12s" % ("groupe remplace", "decisions", "retenus", "variables"))
    for nom, cols in GROUPES.items():
        cols = [c for c in cols if c in garde]
        if not cols:
            print("   %-28s  aucune de ces variables n est utilisee par le modele" % nom)
            continue
        Z = X.copy()
        for c in cols:
            Z[c] = float(med[c])
        d = rf.predict_proba(Z)[:, 1] >= seuil
        print("   %-28s %11.2f %% %13d %12d"
              % (nom, 100 * (d != ref).mean(), int(d.sum()), len(cols)), flush=True)
    print()
    print("   « decisions » = part des tickets ou l achat bascule. « retenus » = combien il en")
    print("   garderait (reference ci-dessus). Un groupe sous ~1 %% peut etre abandonne.")


if __name__ == "__main__":
    main()
