"""REENTRAINE LE MODELE DE PRODUCTION, toutes les 6 h, au format que le moteur sait lire.

MIDO, 20/09 : « on a pas de critere sur une strat moins bonne et tu veux le mettre sur celle-ci ? »
puis « on bascule en prod la meilleure et pas de critere d arret ». Il avait raison sur le fond :
le modele en service est fige au 15/09 et n a JAMAIS eu de critere d arret. Lui opposer une barre
que l installe n a jamais eu a franchir, c est proteger l installe parce qu il est installe.

CE QUE MESURE L ARBITRE (§3.166), sur les tickets que le moteur a REELLEMENT achetes et en euros
lus au portefeuille : la recette reentrainee garde 244 tickets sur 268 et fait passer le moteur de
-0,1248 a +0,0276 EUR/ticket. Ecart +0,1525, intervalle 95 % de -0,062 a +0,367, soit
**+63 EUR/jour, intervalle -26 a +153**. Non prouve (+1,42 sigma) -- mais le modele en place ne
l est pas davantage, et il perd. Les 24 tickets qu elle ecarte valent **-1,675 EUR piece**.

LA RECETTE, celle de `foret_marche` et rien d autre -- c est elle qui a ete mesuree :
    variables     les 18 de prix et de liquidite disponibles, SANS variable de cout (§3.157)
    modele        RandomForest, 300 arbres, min_samples_leaf = 20, random_state = 0
    cible         vidage : net_240 <= -50 % au cout applique
    seuil         quantile 0,80 des scores d ENTRAINEMENT, ecrit DANS le fichier

LE PIEGE QUI AURAIT TOUT CASSE EN SILENCE. La table de recherche nomme ses colonnes `px_n_lect`,
`px_vol`... ; le moteur produit `n_lect`, `vol`... Un modele exporte avec les noms de la recherche
aurait trouve CHAQUE variable absente et pris la branche par defaut a tous les coups, sans lever
la moindre erreur -- exactement la regle 10 du projet (train/serve skew). On exporte donc avec les
noms du MOTEUR, et on verifie la correspondance avant d ecrire.

ET ON VERIFIE L EXPORT. Le convertisseur d arbres sklearn -> JSON est rejoue contre sklearn sur
2 000 lignes : si une seule decision differe, on n ecrit pas. Ce fichier decide d argent reel.

Ecriture ATOMIQUE, et l ancien fichier est sauvegarde avant le premier remplacement.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sys
import time

import numpy as np
import pandas as pd

TABLE = "/app/data/recherche/tout/table.pkl"
CIBLE = os.environ.get("PROD_MODELE", "/app/data/recherche/balayage/foret_vidage_reentraine.json")
ORIGINAL = "/app/data/recherche/balayage/foret_vidage.json"
COUT = float(os.environ.get("COUT_MESURE", "0.0371"))
GARDE = 0.80
PAS_H = 6.0
TZ = dt.timezone(dt.timedelta(hours=2))
# recette -> nom que le MOTEUR produit. `q`, `V` sont deja identiques ; `px_A` devient `A`.
VARIABLES = ["px_n_lect", "px_ret_naiss", "px_dd_max", "px_depuis_min", "px_t_depuis_max", "px_vol",
             "q", "px_q_croiss", "px_ret_10", "px_ret_30", "px_ret_60", "px_ret_120",
             "px_q_croiss_30", "px_q_croiss_60", "px_lancements_10min", "px_heure", "V", "px_A"]


def nom_moteur(v: str) -> str:
    return v[3:] if v.startswith("px_") else v


def _arbre(t, i=0):
    """Un arbre sklearn -> la structure que `ensemble.Ensemble` sait descendre.

    Verifie contre sklearn le 19/09 : ecart max 8,7e-04 sur les probabilites, 100 % de decisions
    identiques. La verification est refaite A CHAQUE EXPORT par `verifier()` -- ce fichier decide
    d argent reel, on ne fait pas confiance a une mesure d avant-hier.
    """
    if t.children_left[i] == -1:
        v = t.value[i][0]
        return {"leaf_value": float(v[1] / v.sum()) if v.sum() else 0.0}
    return {"split_feature": int(t.feature[i]), "threshold": float(t.threshold[i]),
            "default_left": True, "missing_type": "None",
            "left_child": _arbre(t, t.children_left[i]),
            "right_child": _arbre(t, t.children_right[i])}


def verifier(chemin: str, X: pd.DataFrame, p_sklearn: np.ndarray, cols: list[str]) -> bool:
    """Le JSON ecrit redonne-t-il EXACTEMENT les decisions de sklearn ?"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ensemble import Ensemble
    m = Ensemble(chemin)
    p = np.array([m.probabilite({nom_moteur(c): float(X.iloc[i][c]) for c in cols})
                  for i in range(len(X))])
    ecart = float(np.abs(p - p_sklearn).max())
    d_json = (p <= m.seuil_p80)
    d_sk = (p_sklearn <= m.seuil_p80)
    identiques = float((d_json == d_sk).mean())
    print("   verification : ecart max %.2e · decisions identiques %.2f %% sur %d lignes"
          % (ecart, 100 * identiques, len(X)), flush=True)
    return ecart < 1e-2 and identiques == 1.0


def entrainer() -> None:
    import tout_table
    from sklearn.ensemble import RandomForestClassifier
    tout_table.main()
    df = pd.read_pickle(TABLE)
    df = df[df["eligible"] == 1].sort_values("t_dec").reset_index(drop=True)
    cols = [v for v in VARIABLES if v in df.columns and df[v].notna().sum() >= 100]
    X = df[cols].apply(pd.to_numeric, errors="coerce").astype(float)
    r = pd.to_numeric(df["ret_240"], errors="coerce").to_numpy(dtype=float)
    net = (1.0 + r) * (1.0 - COUT) - 1.0
    ok = np.isfinite(net)
    if ok.sum() < 1000:
        print("prod_reentraine: %d tickets avec resultat, trop peu -- on n ecrit rien" % ok.sum(),
              flush=True)
        return
    y = (net[ok] <= -0.5).astype(int)
    med = X[ok].median()
    XA = X[ok].fillna(med).fillna(0.0)
    rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=20, n_jobs=-1,
                                random_state=0).fit(XA, y)
    p_tr = rf.predict_proba(XA)[:, 1]
    seuil = float(np.quantile(p_tr, GARDE))

    d = {
        "feature_names": [nom_moteur(c) for c in cols],
        "n_modeles": 1,
        "sigmoide": False,                       # foret : les feuilles portent deja une proportion
        "seuil_p80": seuil,
        "medianes": {nom_moteur(c): float(med[c]) for c in cols},
        "entraine_sur": int(ok.sum()),
        "reentraine_le": dt.datetime.now(TZ).isoformat(timespec="seconds"),
        "recette": "foret_marche (§3.166) · RF 300 / feuille 20 · cible vidage · garde %.0f %%"
                   % (100 * GARDE),
        "modeles": [{"tree_info": [{"tree_structure": _arbre(e.tree_)} for e in rf.estimators_]}],
    }
    tmp = CIBLE + ".tmp"
    os.makedirs(os.path.dirname(CIBLE), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)

    ech = XA.sample(min(2000, len(XA)), random_state=1)
    if not verifier(tmp, ech, rf.predict_proba(ech)[:, 1], cols):
        os.remove(tmp)
        print("prod_reentraine: VERIFICATION ECHOUEE -- rien n a ete ecrit", flush=True)
        return
    # l original du 15/09 est garde une fois pour toutes, avant le premier remplacement
    sauve = ORIGINAL.replace(".json", "_fige_15-09.json")
    if os.path.exists(ORIGINAL) and not os.path.exists(sauve):
        shutil.copy2(ORIGINAL, sauve)
        print("prod_reentraine: original du 15/09 sauvegarde -> %s" % os.path.basename(sauve),
              flush=True)
    os.replace(tmp, CIBLE)
    print("prod_reentraine: ECRIT %s · %d tickets · %d variables · seuil %.4f"
          % (os.path.basename(CIBLE), d["entraine_sur"], len(cols), seuil), flush=True)


def main() -> None:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    while True:
        try:
            entrainer()
        except Exception as e:  # noqa: BLE001
            print("prod_reentraine: %s" % str(e)[:250], flush=True)
        time.sleep(PAS_H * 3600)


if __name__ == "__main__":
    main()
