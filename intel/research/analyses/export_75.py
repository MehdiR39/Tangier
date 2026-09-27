"""EXPORTE LA FORET 75s AU FORMAT DU MOTEUR -- inversee, verifiee, prete a brancher.

MIDO, 20/09 : « oui je valide » -- brancher `FORET 75s top 10 %`, apres qu il ait fait remarquer que
mes totaux ne voulaient rien dire tant que les lignes ne partaient pas ensemble. Sur periode commune
(depuis le 20/09 02h15) : top 10 % **+0,462 EUR/ticket sur 92 tickets (+42,5)**, top 5 % **-0,164
sur 24**. Meme modele fige, seul le curseur differe : le seuil a 5 % est trop serre, et c est le
troisieme signe dans la meme journee que le cinquieme le plus confiant est mauvais (VIDAGE 5 % pire
des neuf cases, top 5 % du 75s sous le top 20 % hier soir).

LE PIEGE QUI AURAIT TOUT INVERSE. Le moteur decide avec `risque <= seuil` : il suppose un score ou
BAS = BON (c est une probabilite de VIDAGE). La foret 75s predit `P(GAGNANT)` : HAUT = BON. Branchee
telle quelle, elle aurait achete exactement ce qu il faut eviter. On exporte donc **1 - p** : la
comparaison du moteur redevient juste sans toucher a son code. Pour une foret (`sigmoide: false`)
c est exact -- la moyenne de (1 - feuille) vaut 1 - la moyenne des feuilles.
Le seuil exporte est donc `1 - seuil10` = 1 - 0,7996 = 0,2004.

LES IMAGES. Le modele utilise `img_l`, `img_centre`, `img_h` -- 0 % d importance hors echantillon, et
**absentes sur 49 % des tickets d entrainement** (1 679 images sur 3 288). Le moteur passera la
mediane d apprentissage, exactement comme le pipeline de recherche l a fait pour la moitie des
lignes. Ce n est pas un contournement, c est le traitement d origine ; et on MESURE ici combien de
decisions changent quand on les remplace par la mediane.

VERIFICATION, a chaque export : le JSON est rejoue contre sklearn sur 2 000 lignes, et rien n est
ecrit si une seule decision differe.

Lecture seule sur le modele gele : on ne le reentraine pas, on le traduit.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DOSSIER = "/app/data/recherche/foret_gel75"
CIBLE = os.environ.get("MODELE_75", "/app/data/recherche/balayage/foret_75s_top10.json")
GARDE = "seuil10"                  # on branche le top 10 %, valide par Mido le 20/09


def _arbre(t, i=0):
    """sklearn -> structure lisible par `ensemble.Ensemble`, avec les feuilles INVERSEES.

    `leaf_value = 1 - P(gagnant)`, pour que le `risque <= seuil` du moteur garde bien les plus
    prometteurs. Sans cette inversion le moteur acheterait le contraire de ce que le modele
    recommande, et rien dans les journaux ne le dirait.
    """
    if t.children_left[i] == -1:
        v = t.value[i][0]
        p = float(v[1] / v.sum()) if v.sum() else 0.0
        return {"leaf_value": 1.0 - p}
    return {"split_feature": int(t.feature[i]), "threshold": float(t.threshold[i]),
            "default_left": True, "missing_type": "None",
            "left_child": _arbre(t, t.children_left[i]),
            "right_child": _arbre(t, t.children_right[i])}


def main() -> None:
    import joblib
    from ensemble import Ensemble

    m = joblib.load(os.path.join(DOSSIER, "modele.pkl"))
    s = json.load(open(os.path.join(DOSSIER, "seuils.json"), encoding="utf-8"))
    rf, med, garde = m["rf"], m["med"], s["garde"]
    seuil_direct = float(s[GARDE])
    d = {
        "feature_names": list(garde),
        "n_modeles": 1,
        "sigmoide": False,
        # le moteur fait `score <= seuil` ; on lui donne 1 - p et 1 - seuil.
        "seuil_p80": 1.0 - seuil_direct,
        "medianes": {k: float(med[k]) for k in garde},
        "entraine_sur": int(s.get("n_entrainement") or 0),
        "sens": "INVERSE : leaf_value = 1 - P(gagnant). Le moteur garde score <= seuil.",
        "seuil_direct": seuil_direct,
        "recette": "foret_gel75 gelee le 18/09 23h10 · RF 300 / feuille 20 · cible GAGNANT NET"
                   " · top 10 pour cent, seuil " + GARDE,
        "modeles": [{"tree_info": [{"tree_structure": _arbre(e.tree_)} for e in rf.estimators_]}],
    }
    tmp = CIBLE + ".tmp"
    os.makedirs(os.path.dirname(CIBLE), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)

    # --- verification contre sklearn, sur de vraies lignes
    import foret_gel as G
    df, _ = G.table()
    X = df[garde].apply(pd.to_numeric, errors="coerce").astype(float).fillna(med).fillna(0.0)
    X = X.sample(min(2000, len(X)), random_state=1)
    p_sk = rf.predict_proba(X)[:, 1]
    E = Ensemble(tmp)
    p_json = np.array([E.probabilite({c: float(X.iloc[i][c]) for c in garde}) for i in range(len(X))])
    ecart = float(np.abs((1.0 - p_json) - p_sk).max())
    d_sk = p_sk >= seuil_direct                 # sklearn : on garde les plus SURS
    d_js = p_json <= E.seuil_p80                # moteur : on garde les scores BAS
    identiques = float((d_sk == d_js).mean())
    print("   verification : ecart max %.2e · decisions identiques %.2f %% sur %d lignes"
          % (ecart, 100 * identiques, len(X)), flush=True)
    if ecart > 1e-2 or identiques < 1.0:
        os.remove(tmp)
        print("export_75: VERIFICATION ECHOUEE -- rien n a ete ecrit", flush=True)
        return

    # --- ce que coute de ne PAS avoir les images : on les remplace par la mediane et on compte
    img = [c for c in garde if c.startswith("img_")]
    if img:
        Z = X.copy()
        for c in img:
            Z[c] = float(med[c])
        p_med = rf.predict_proba(Z)[:, 1]
        change = float(((p_sk >= seuil_direct) != (p_med >= seuil_direct)).mean())
        print("   images remplacees par la mediane : %.2f %% des decisions changent (%d variables)"
              % (100 * change, len(img)), flush=True)

    os.replace(tmp, CIBLE)
    print("export_75: ECRIT %s · %d variables · seuil direct %.4f -> seuil moteur %.4f"
          % (os.path.basename(CIBLE), len(garde), seuil_direct, d["seuil_p80"]), flush=True)


if __name__ == "__main__":
    main()
