"""POUSSER LA MODELISATION -- a l interieur de la marche avant, jamais a cote.

MIDO, 19/09 00h45 : « avant de geler, peut-on pousser la modelisation ? feature selection avec RF,
toute autre idee ». Oui, a une condition qui decide de tout : CHAQUE choix (variables gardees,
taille des feuilles, cible) se fait sur les donnees ANTERIEURES a la coupe, et la barre du hasard
est refaite sur la procedure entiere, y compris le choix de la meilleure variante. Sinon on ne
pousse pas la modelisation, on fabrique un meilleur chiffre.

LES VARIANTES, cote a cote, meme protocole que marche_avant_tout.py (V1_SEUL, 9 fenetres, 30 %) :

  base        foret de gain, 300 arbres, feuilles 20            (la reference de §3.134)
  v1plus      + 12 variables de transactions supplementaires    (la famille qui porte 60 %)
  selection   + a chaque coupe, les 25 variables les plus utiles sur le passe, puis reentrainer
  feuilles    + taille de feuille choisie par le score HORS-SAC sur le passe (10 / 20 / 40)
  esperance   classer par le NET PREDIT (regression, cible bornee a [-1, +3]) et non par P(gain)
  recent      + poids exponentiel : un ticket d il y a 24 h pese moitie moins
  rang        moyenne de rang de la foret et d un boosting

LES 12 VARIABLES DE TRANSACTIONS EN PLUS, toutes a age <= 45 s, toutes causales :
  achats et SOL dans 25-35 s et 35-45 s, et leur ACCELERATION ; part des 3 plus gros acheteurs ;
  portefeuilles jamais vus dans un pool anterieur (nombre, part du SOL) ; age de la derniere vente ;
  plus grosse vente ; pression d achat rapportee au coffre (SOL achete / q, SOL vendu / q) ;
  acheteurs par SOL.

BARRE DU HASARD : NULLS marches avant avec les resultats permutes, ou l on retient a chaque fois
LA MEILLEURE des variantes -- c est le maximum sous permutation, pas un tirage par variante.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import statistics as st
import sys
from collections import defaultdict

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DOSSIER = "/app/data/recherche/tout"
V1 = "/app/data/recherche/v1_avant"
COUT = float(os.environ.get("COUT_MESURE", "0.0655"))
MISE = 20.0
PAS_H = 6
AGE_V1 = 45
EXCLUES = {"tg_poste"}
NULLS = int(os.environ.get("NULLS", "0"))
PARAMS = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=40,
              subsample=0.8, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0, verbose=-1)
VARIANTES = ("base", "v1plus", "selection", "feuilles", "esperance", "recent", "rang")


def net(r):
    return (1.0 + r) * (1.0 - COUT) - 1.0


# ----------------------------------------------------------------------------- v1 plus
def v1_plus() -> pd.DataFrame:
    cache = os.path.join(DOSSIER, "v1_plus.pkl")
    if os.path.exists(cache):
        return pd.read_pickle(cache)
    pools = []
    for f in sorted(glob.glob(os.path.join(V1, "*.jsonl"))):
        with open(f, encoding="utf-8") as fh:
            for ligne in fh:
                try:
                    d = json.loads(ligne)
                except Exception:  # noqa: BLE001
                    continue
                pools.append((float(d.get("naissance") or 0), d))
    pools.sort(key=lambda x: x[0])
    vus: set = set()
    feats = {}
    for _, d in pools:
        pair = d.get("pair")
        a_25_35 = a_35_45 = 0
        s_25_35 = s_35_45 = v_35_45 = 0.0
        par_acheteur: defaultdict[str, float] = defaultdict(float)
        nouveaux, sol_nouveaux, sa, sv = set(), 0.0, 0.0, 0.0
        derniere_vente, max_vente = None, 0.0
        acheteurs = set()
        for tx in d.get("tx") or []:
            try:
                age, parts = int(tx[0]), tx[2]
            except Exception:  # noqa: BLE001
                continue
            if age > AGE_V1:
                continue
            for p in parts or []:
                try:
                    q, dj, ds = str(p[0]), float(p[1]), float(p[2])
                except Exception:  # noqa: BLE001
                    continue
                if dj > 0 and ds < 0:
                    sa += -ds
                    par_acheteur[q] += -ds
                    acheteurs.add(q)
                    if q not in vus:
                        nouveaux.add(q)
                        sol_nouveaux += -ds
                    if 25 <= age < 35:
                        a_25_35 += 1
                        s_25_35 += -ds
                    elif 35 <= age <= 45:
                        a_35_45 += 1
                        s_35_45 += -ds
                elif dj < 0 and ds > 0:
                    sv += ds
                    derniere_vente = age
                    max_vente = max(max_vente, ds)
                    if 35 <= age <= 45:
                        v_35_45 += ds
        top3 = sum(sorted(par_acheteur.values(), reverse=True)[:3])
        feats[pair] = {
            "v1p_achats_25_35": a_25_35, "v1p_achats_35_45": a_35_45,
            "v1p_accel": a_35_45 - a_25_35,
            "v1p_sol_35_45": s_35_45, "v1p_sol_accel": s_35_45 - s_25_35,
            "v1p_ventes_sol_35_45": v_35_45,
            "v1p_top3_part": (top3 / sa) if sa > 0 else None,
            "v1p_nouveaux": len(nouveaux),
            "v1p_nouveaux_part": (sol_nouveaux / sa) if sa > 0 else None,
            "v1p_derniere_vente_age": (AGE_V1 - derniere_vente) if derniere_vente is not None else AGE_V1,
            "v1p_max_vente": max_vente,
            "v1p_acheteurs_par_sol": (len(acheteurs) / sa) if sa > 0 else None,
        }
        vus.update(acheteurs)
    x = pd.DataFrame.from_dict(feats, orient="index")
    x.to_pickle(cache)
    return x


# ----------------------------------------------------------------------------- marche avant
def marche(df: pd.DataFrame, cols: dict[str, list[str]], y_net: np.ndarray, t: np.ndarray,
           variantes=VARIANTES, verbeux=True) -> dict[str, np.ndarray]:
    y_gain = (y_net > 0).astype(int)
    y_reg = np.clip(y_net, -1.0, 3.0)
    tz = dt.timezone(dt.timedelta(hours=2))
    c = dt.datetime(2026, 9, 16, 0, 0, tzinfo=tz)
    fin = dt.datetime(2026, 9, 18, 18, 0, tzinfo=tz)
    tot = {v: [] for v in variantes}
    tot["temoin"] = []
    lignes = []
    while c < fin:
        c0, c1 = c.timestamp(), (c + dt.timedelta(hours=PAS_H)).timestamp()
        A, J = t < c0, (t >= c0) & (t < c1)
        if A.sum() < 150 or J.sum() < 20:
            c += dt.timedelta(hours=PAS_H)
            continue
        nets = y_net[J]
        n = len(nets)
        k30 = max(5, int(n * 0.3))
        res = {"temoin": nets}
        for v in variantes:
            X = df[cols["v1plus"] if v != "base" else cols["base"]]
            XA, XJ = X[A], X[J]
            med = XA.median()
            XA_f, XJ_f = XA.fillna(med).fillna(0.0), XJ.fillna(med).fillna(0.0)
            feuille, poids, garde = 20, None, list(X.columns)
            if v == "selection":
                rf0 = RandomForestClassifier(n_estimators=200, min_samples_leaf=20, n_jobs=-1, random_state=0).fit(XA_f, y_gain[A])
                garde = [g for _, g in sorted(zip(rf0.feature_importances_, garde), reverse=True)[:25]]
            if v == "feuilles":
                meilleur = None
                for fl in (10, 20, 40):
                    r = RandomForestClassifier(n_estimators=200, min_samples_leaf=fl, oob_score=True,
                                               n_jobs=-1, random_state=0).fit(XA_f, y_gain[A])
                    if meilleur is None or r.oob_score_ > meilleur[0]:
                        meilleur = (r.oob_score_, fl)
                feuille = meilleur[1]
            if v == "recent":
                age_h = (c0 - t[A]) / 3600.0
                poids = np.power(0.5, age_h / 24.0)
            if v == "esperance":
                rf = RandomForestRegressor(n_estimators=300, min_samples_leaf=feuille, n_jobs=-1, random_state=0)
                rf.fit(XA_f[garde], y_reg[A], sample_weight=poids)
                score = rf.predict(XJ_f[garde])
            else:
                rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=feuille, n_jobs=-1, random_state=0)
                rf.fit(XA_f[garde], y_gain[A], sample_weight=poids)
                score = rf.predict_proba(XJ_f[garde])[:, 1]
                if v == "rang":
                    bo = np.mean([lgb.LGBMClassifier(**PARAMS, random_state=s).fit(XA[garde], y_gain[A]).predict_proba(XJ[garde])[:, 1]
                                  for s in range(4)], axis=0)
                    score = pd.Series(score).rank().to_numpy() + pd.Series(bo).rank().to_numpy()
            res[v] = nets[np.argsort(-score, kind="stable")[:k30]]
        for k in tot:
            tot[k].extend(res[k].tolist())
        lignes.append((c.strftime("%d/%m %Hh"), n, {k: 100 * res[k].mean() for k in res}))
        c += dt.timedelta(hours=PAS_H)
    if verbeux:
        print("   %-11s %4s %8s | %s" % ("fenetre", "n", "temoin", " ".join("%9s" % v for v in variantes)))
        for lbl, n, r in lignes:
            print("   %-11s %4d %+7.2f%% | %s" % (lbl, n, r["temoin"], " ".join("%+8.2f%%" % r[v] for v in variantes)))
    return {k: np.array(v) for k, v in tot.items()}


def resume(tot: dict[str, np.ndarray]) -> None:
    print()
    print("TOUTE LA PERIODE, additionnee (30 % gardes)")
    for k, v in tot.items():
        if len(v) < 5:
            continue
        s = np.sort(v)
        print("   %-10s n=%4d  net %+6.2f %%/ticket = %+6.0f EUR · sans 3 meil. %+6.2f %% · gagnants %3.0f %% · cata %3.0f %%"
              % (k, len(v), 100 * v.mean(), MISE * v.sum(), 100 * s[:-3].mean(), 100 * (v > 0).mean(), 100 * (v < -0.5).mean()))


def main() -> None:
    df = pd.read_pickle(os.path.join(DOSSIER, "table.pkl"))
    variables = [v for v in df.attrs["VARIABLES"] if v not in EXCLUES]
    df = df[(df["eligible"] == 1) & df["ret_240"].notna() & df["v1_n_achats"].notna()]
    df = df.merge(v1_plus(), left_on="pair", right_index=True, how="left").sort_values("t_dec").reset_index(drop=True)
    plus = [c for c in df.columns if c.startswith("v1p_")]
    X = df[variables + plus].apply(pd.to_numeric, errors="coerce").astype(float)
    base = [v for v in variables if X[v].notna().sum() >= 100 and X[v].nunique(dropna=True) >= 2]
    cols = {"base": base, "v1plus": base + [p for p in plus if X[p].notna().sum() >= 100 and X[p].nunique(dropna=True) >= 2]}
    for k in cols:
        df[cols[k]] = X[cols[k]]
    y_net = net(df["ret_240"].to_numpy())
    t = df["t_dec"].to_numpy()
    print("%d tickets avec transactions · base %d variables · v1plus %d · cout %.2f pt"
          % (len(df), len(cols["base"]), len(cols["v1plus"]), 100 * COUT))
    print()
    tot = marche(df, cols, y_net, t)
    resume(tot)
    vrai = max(tot[v].mean() for v in VARIANTES)
    meilleure = max(VARIANTES, key=lambda v: tot[v].mean())
    print()
    print("meilleure variante : %s (%+.2f %%)" % (meilleure, 100 * vrai))

    if NULLS:
        print()
        print("BARRE DU HASARD : %d marches avant, resultats permutes, en retenant a chaque fois LA MEILLEURE variante" % NULLS)
        rng = np.random.default_rng(19)
        maxs = []
        for k in range(NULLS):
            yp = y_net[rng.permutation(len(y_net))]
            tp = marche(df, cols, yp, t, verbeux=False)
            m = max(tp[v].mean() for v in VARIANTES)
            maxs.append(m)
            print("   hasard %2d : meilleure variante %+.2f %%" % (k + 1, 100 * m), flush=True)
        barre = float(np.quantile(maxs, 0.95))
        print("   -> barre (95e centile) %+.2f %% · vrai %+.2f %% -> %s"
              % (100 * barre, 100 * vrai, "AU-DESSUS" if vrai > barre else "EN DESSOUS"))


if __name__ == "__main__":
    main()
