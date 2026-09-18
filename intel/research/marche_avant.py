"""MARCHE AVANT : reentrainer toutes les 6 heures, trier fort, additionner TOUTES les fenetres.

MIDO, 18/09 23h15 : « si on fait -0,71 % sur une journee compliquee c est pas mal non ? »

Relatif a la fenetre, oui : le hasard faisait -15 %. Mais 38 tickets et une seule fenetre ne
disent pas ce que la regle vaut. La bonne question : sur TOUTE la periode, une foret (et
l ensemble) reentraines regulierement et tries fort, ca donne quoi, fenetre apres fenetre ?

PROTOCOLE. Coupes toutes les 6 h du 16/09 00h au 18/09 18h (Paris). A chaque coupe : entrainer sur
grande table + carnet papier AVANT la coupe (meme recette que les fichiers en service), juger les
6 h qui suivent, garder les 30 % (et 50 %) les moins risques selon le modele frais. Puis additionner
tous les tickets juges : c est un seul carnet en marche avant, jamais une fenetre choisie.

CE QU ON REGARDE : le net total en euros a 20 EUR de mise, le net par ticket, sans les 3 meilleurs
tickets de TOUTE la periode, le signe de chaque fenetre, et le temoin (tout prendre) fenetre par
fenetre. Cout 6,55, multiplicatif.

Une regle qui gagne sur une fenetre et perd sur les autres n est pas une regle : c est une fenetre.
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ensemble as E  # noqa: E402

COMBO = os.environ.get("COMBO_DB", "/app/db/papier_combo.sqlite")
GRANDE = "/app/data/recherche/balayage/table.pkl"
COUT = float(os.environ.get("COUT_MESURE", "0.0655"))
MISE = 20.0
PAS_H = 6
PARAMS = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=80,
              subsample=0.8, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0, verbose=-1)
N_MODELES = int(os.environ.get("N_MODELES", "6"))     # 6 graines suffisent en marche avant (temps)


def net(r):
    return (1.0 + r) * (1.0 - COUT) - 1.0


def carnet(variables):
    c = sqlite3.connect("file:%s?mode=ro" % COMBO, uri=True)
    rows = []
    for t, var, b in c.execute(
            "SELECT d.t_dec, d.variables, i.brut_240 FROM decision d JOIN issue i ON i.pair = d.pair"
            " WHERE d.eligible = 1 AND i.brut_240 IS NOT NULL"):
        try:
            v = json.loads(var or "{}")
        except Exception:  # noqa: BLE001
            v = {}
        r = {"t": t, "brut": b}
        for k in variables:
            x = v.get(k)
            r[k] = float(x) if x is not None else np.nan
        rows.append(r)
    return pd.DataFrame(rows).sort_values("t").reset_index(drop=True)


def main() -> None:
    variables = E.Ensemble(E.CHEMIN).variables
    grande = pd.read_pickle(GRANDE).rename(columns={"brut_240": "brut"})
    grande = grande[grande["brut"].notna()][variables + ["brut"]]
    cb = carnet(variables)
    debut = dt.datetime(2026, 9, 16, 0, 0, tzinfo=dt.timezone(dt.timedelta(hours=2)))
    fin = dt.datetime(2026, 9, 18, 18, 0, tzinfo=dt.timezone(dt.timedelta(hours=2)))
    coupes = []
    t = debut
    while t < fin:
        coupes.append(t.timestamp())
        t += dt.timedelta(hours=PAS_H)
    print("marche avant : %d coupes de %d h · cout %.2f pt · mise %.0f EUR" % (len(coupes), PAS_H, 100 * COUT, MISE))
    print()
    print("   %-16s %5s %8s | %8s %8s | %8s %8s" % ("fenetre", "n", "temoin", "foret30", "foret50", "ens30", "ens50"))
    tot = {k: [] for k in ("temoin", "foret30", "foret50", "ens30", "ens50")}
    for c0 in coupes:
        c1 = c0 + PAS_H * 3600
        A = pd.concat([grande, cb[cb["t"] < c0][variables + ["brut"]]], ignore_index=True)
        J = cb[(cb["t"] >= c0) & (cb["t"] < c1)].reset_index(drop=True)
        if len(J) < 20:
            continue
        y = (A["brut"] <= -0.5).astype(int).to_numpy()
        X = A[variables].astype(float)
        med = X.median()
        rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=20, n_jobs=-1, random_state=0).fit(X.fillna(med), y)
        boosts = [lgb.LGBMClassifier(**PARAMS, random_state=s).fit(X, y) for s in range(N_MODELES)]
        XJ = J[variables].astype(float)
        p_rf = rf.predict_proba(XJ.fillna(med))[:, 1]
        p_en = np.mean([m.predict_proba(XJ)[:, 1] for m in boosts], axis=0)
        nets = net(J["brut"].to_numpy())
        res = {"temoin": nets}
        for nom, p in (("foret", p_rf), ("ens", p_en)):
            o = np.argsort(p, kind="stable")
            res[nom + "30"] = nets[o[:max(5, int(len(J) * 0.3))]]
            res[nom + "50"] = nets[o[:max(5, len(J) // 2)]]
        for k in tot:
            tot[k].extend(res[k].tolist())
        lbl = dt.datetime.fromtimestamp(c0, dt.timezone(dt.timedelta(hours=2))).strftime("%d/%m %Hh")
        print("   %-16s %5d %+7.2f%% | %+7.2f%% %+7.2f%% | %+7.2f%% %+7.2f%%" % (
            lbl, len(J), 100 * nets.mean(), 100 * res["foret30"].mean(), 100 * res["foret50"].mean(),
            100 * res["ens30"].mean(), 100 * res["ens50"].mean()), flush=True)
    print()
    print("TOUTE LA PERIODE, additionnee")
    for k, v in tot.items():
        v = np.array(v)
        if len(v) == 0:
            continue
        s = np.sort(v)
        print("   %-8s n=%4d  net %+6.2f %%/ticket  = %+7.0f EUR  · sans 3 meilleurs %+6.2f %%  · gagnants %3.0f %%  · cata %3.0f %%"
              % (k, len(v), 100 * v.mean(), MISE * v.sum(), 100 * s[:-3].mean(), 100 * (v > 0).mean(), 100 * (v < -0.5).mean()))


if __name__ == "__main__":
    main()
