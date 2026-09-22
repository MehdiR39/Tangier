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
    # CE QU IL FALLAIT MESURER : LES EUROS, pas le nombre de decisions qui basculent.
    # MIDO : « il me semble que tu disais que l image n apporte rien dans ce modele ? ». Il a
    # raison, et ca demolit le chiffre precedent. Si une variable n apporte RIEN a la prediction
    # -- l importance par permutation des images est de 0 % -- alors les decisions qu elle fait
    # basculer changent AU HASARD, et un basculement aleatoire ne coute rien en esperance.
    # « combien de decisions changent » et « combien ca coute » sont deux grandeurs differentes,
    # et je mesurais la premiere en parlant de la seconde.
    COUT, MISE = 0.0371, 20.0
    r = pd.to_numeric(df["ret_240"], errors="coerce").to_numpy(dtype=float)
    net = MISE * ((1.0 + r) * (1.0 - COUT) - 1.0)
    ok = pd.notna(pd.Series(net))
    base = float(net[ref & ok.to_numpy()].mean())
    print("   reference : %+0.3f EUR/ticket sur %d retenus"
          % (base, int((ref & ok.to_numpy()).sum())))
    print()
    print("   %-28s %11s %10s %12s %9s"
          % ("groupe remplace", "decisions", "retenus", "EUR/ticket", "ecart"))
    for nom, cols in GROUPES.items():
        cols = [c for c in cols if c in garde]
        if not cols:
            continue
        Z = X.copy()
        for c in cols:
            Z[c] = float(med[c])
        d = rf.predict_proba(Z)[:, 1] >= seuil
        sel = d & ok.to_numpy()
        e = float(net[sel].mean()) if sel.sum() else float("nan")
        print("   %-28s %10.2f %% %10d %+12.3f %+9.3f"
              % (nom, 100 * (d != ref).mean(), int(d.sum()), e, e - base), flush=True)
    print()
    print("   « decisions » = part des achats qui basculent. « EUR/ticket » = ce que la selection")
    print("   RAPPORTE alors. C est la derniere colonne qui decide, pas la premiere : une variable")
    print("   sans pouvoir predictif fait basculer des decisions sans changer le resultat.")


if __name__ == "__main__":
    main()
