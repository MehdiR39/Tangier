"""REENTRAINER L ENSEMBLE DE 12 ET LA FORET JUSQU A UNE HEURE DONNEE, ET JUGER APRES.

MIDO, 18/09 22h45 : « entraine 12 modeles ». Le meme test que `reentrainer.py` pour le modele
seul, applique aux deux gels ENSEMBLE de 12 et FORET ALEATOIRE.

CE QUI REND LA COMPARAISON HONNETE, et qui a failli ne pas l etre. L ensemble et la foret en service
ont ete entraines sur la GRANDE table de `grand_balayage` : 27 135 lignes du 09/09 au 15/09 05h47.
Le carnet papier `papier_combo` ne commence que le 15/09 14h24 -- les deux ne se recouvrent pas.
Reentrainer sur le seul carnet papier (2 200 tickets) aurait confondu « plus recent » avec « dix
fois moins de donnees ». On reentraine donc sur GRANDE TABLE + carnet papier jusqu a la coupe :
strictement plus de donnees, strictement plus recentes, meme recette.

LA RECETTE, lue dans les fichiers en service :
  - ensemble : 12 boostings LightGBM (PARAMS de grand_balayage_ml, 300 arbres) qui ne different
    que par la graine ; moyenne des PROBABILITES ; seuil = 80e centile de cette moyenne sur les
    donnees d apprentissage ;
  - foret : RandomForest de 300 arbres, trous remplaces par la mediane d apprentissage, moyenne
    des proportions de classe ; meme seuil. (min_samples_leaf n est pas enregistre dans le
    fichier : 20 ici, dit tel quel.)
  - cible : vidage = brut_240 <= -0,50. Memes 19 variables.

DEUX COUPES : avant 18h00 Paris -> apres 18h (la question) ; avant 12h00 -> 12h-18h (plus de poids).
Sur la fenetre de jugement : en service contre frais, a EFFECTIF EGAL (le k que garde l ensemble
en service, puis 50 % et 30 %), cout 6,55, et un tirage au hasard de k tickets 4 000 fois.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ensemble as E  # noqa: E402

COMBO = os.environ.get("COMBO_DB", "/app/db/papier_combo.sqlite")
GRANDE = "/app/data/recherche/balayage/table.pkl"
COUT = float(os.environ.get("COUT_MESURE", "0.0655"))
PARAMS = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=80,
              subsample=0.8, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0, verbose=-1)
N_MODELES = 12
rng = np.random.default_rng(12)


def paris(h: int) -> float:
    return dt.datetime(2026, 9, 18, h - 2, 0, tzinfo=dt.timezone.utc).timestamp()


def net(r):
    return (1.0 + r) * (1.0 - COUT) - 1.0


def carnet(variables: list[str]) -> pd.DataFrame:
    c = sqlite3.connect("file:%s?mode=ro" % COMBO, uri=True)
    rows = []
    for t, var, b in c.execute(
            "SELECT d.t_dec, d.variables, i.brut_240 FROM decision d JOIN issue i ON i.pair = d.pair"
            " WHERE d.eligible = 1 AND i.brut_240 IS NOT NULL"):
        try:
            v = json.loads(var or "{}")
        except Exception:  # noqa: BLE001
            v = {}
        r = {"t": t, "brut": b, "_var": v}
        for k in variables:
            x = v.get(k)
            r[k] = float(x) if x is not None else np.nan
        rows.append(r)
    return pd.DataFrame(rows).sort_values("t").reset_index(drop=True)


def entrainer(X: pd.DataFrame, y: np.ndarray):
    """Rend (scoreur ensemble, seuil, scoreur foret, seuil)."""
    boosts = [lgb.LGBMClassifier(**PARAMS, random_state=s).fit(X, y) for s in range(N_MODELES)]

    def p_ens(Z: pd.DataFrame) -> np.ndarray:
        return np.mean([m.predict_proba(Z)[:, 1] for m in boosts], axis=0)

    med = X.median()
    rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=20, n_jobs=-1, random_state=0)
    rf.fit(X.fillna(med), y)

    def p_rf(Z: pd.DataFrame) -> np.ndarray:
        return rf.predict_proba(Z.fillna(med))[:, 1]

    return p_ens, float(np.quantile(p_ens(X), 0.80)), p_rf, float(np.quantile(p_rf(X), 0.80))


def stats(y: np.ndarray) -> str:
    if len(y) < 5:
        return "n=%d trop peu" % len(y)
    s = np.sort(y)
    return "n=%3d  net %+6.2f %%  sans3 %+6.2f %%  gagnants %3.0f %%  cata %3.0f %%" % (
        len(y), 100 * y.mean(), 100 * s[:-3].mean(), 100 * (y > 0).mean(), 100 * (y < -0.5).mean())


def coupe(grande: pd.DataFrame, cb: pd.DataFrame, variables: list[str], t_fin: float, t_max: float,
          titre: str, ens_srv: E.Ensemble, for_srv: E.Ensemble) -> None:
    A = pd.concat([grande[variables + ["brut"]], cb[cb["t"] < t_fin][variables + ["brut"]]], ignore_index=True)
    J = cb[(cb["t"] >= t_fin) & (cb["t"] < t_max)].reset_index(drop=True)
    if len(J) < 20:
        print("%s : %d tickets de jugement, trop peu" % (titre, len(J)))
        return
    y_tr = (A["brut"] <= -0.5).astype(int).to_numpy()
    p_ens, s_ens, p_rf, s_rf = entrainer(A[variables].astype(float), y_tr)
    XJ = J[variables].astype(float)
    frais = {"ENSEMBLE frais": p_ens(XJ), "FORET fraiche": p_rf(XJ)}
    srv = {"ENSEMBLE en service": np.array([ens_srv.probabilite(v) for v in J["_var"]]),
           "FORET en service": np.array([for_srv.probabilite(v) for v in J["_var"]])}
    y_j = (J["brut"] <= -0.5).astype(int).to_numpy()
    nets = net(J["brut"].to_numpy())

    print("=" * 100)
    print(titre)
    print("   entraine sur %d lignes (grande table %d + carnet %d) · juge sur %d · vidages %.1f %%"
          % (len(A), len(grande), len(A) - len(grande), len(J), 100 * y_j.mean()))
    for nom, p in list(srv.items()) + list(frais.items()):
        try:
            print("   AUC vidage %-22s %.3f" % (nom, roc_auc_score(y_j, p)))
        except Exception:  # noqa: BLE001
            pass
    print("   temoin (tout prendre)              %s" % stats(nets))
    k_srv = int((srv["ENSEMBLE en service"] <= ens_srv.seuil_p80).sum())
    for lbl, k in (("effectif garde par l ensemble en service", k_srv), ("50 % gardes", len(J) // 2),
                   ("30 % gardes", int(len(J) * 0.3))):
        if k < 5:
            continue
        print("   -- %s (k=%d) --" % (lbl, k))
        tir = np.array([nets[rng.choice(len(J), k, replace=False)].mean() for _ in range(4000)])
        for nom, p in list(srv.items()) + list(frais.items()):
            m = np.argsort(p, kind="stable")[:k]
            print("   %-24s %s   bat le hasard %3.0f %%" % (nom, stats(nets[m]), 100 * (tir < nets[m].mean()).mean()))
        print("   %-24s moyenne %+6.2f %%" % ("hasard (k tickets)", 100 * tir.mean()))
    print()


def main() -> None:
    ens_srv, for_srv = E.Ensemble(E.CHEMIN), E.Ensemble(E.CHEMIN_FORET)
    variables = ens_srv.variables
    grande = pd.read_pickle(GRANDE).rename(columns={"brut_240": "brut"})
    grande = grande[grande["brut"].notna()]
    cb = carnet(variables)
    print("grande table %d lignes (09->15/09) · carnet papier %d tickets · %d variables · cout %.2f pt"
          % (len(grande), len(cb), len(variables), 100 * COUT))
    print()
    coupe(grande, cb, variables, paris(18), 9e18,
          "COUPE 18h00 : entraine AVANT 18h, juge APRES 18h (la question posee)", ens_srv, for_srv)
    coupe(grande, cb, variables, paris(12), paris(18),
          "COUPE 12h00 : entraine AVANT midi, juge midi -> 18h (plus de poids)", ens_srv, for_srv)


if __name__ == "__main__":
    main()
