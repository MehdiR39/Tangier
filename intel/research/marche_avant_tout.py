"""UNE FORET SUR TOUT : les 107 variables de toutes les sources, en marche avant.

MIDO, 18/09 23h40 : « on a construit une foret en croisant toutes nos variables, toutes les donnees
recuperees, reseau, prix, image ? » Non. Les modeles en service et ceux reentraines ce soir
n utilisent que 19 variables de PRIX. Le balayage large a croise les 107 variables par coupes et
paires, jamais dans un modele. Ce module comble ce trou.

DEUX CIBLES, PARCE QUE LA PERTE EST DANS LE CORPS. Trois fois ce soir, supprimer les catastrophes
n a pas suffi (22 % -> 7 % de catastrophes, net presque inchange). Un modele de VIDAGE trie la
queue. On entraine donc AUSSI un modele de GAIN : P(net_240 > 0), et on garde les tickets les plus
probables. Si l information existe quelque part dans les 107 variables, c est ce modele-la qui la
verra.

PROTOCOLE, identique a marche_avant.py : coupes toutes les 6 h du 16/09 00h au 18/09 18h ; a chaque
coupe on entraine sur les tickets ANTERIEURS de la table unique (pas de grande table ici : elle
n a pas ces variables), on juge les 6 h suivantes, on garde 30 % et 50 %, on additionne tout.
Foret : 300 arbres, feuilles >= 20, trous a la mediane d apprentissage. Boosting : 6 graines,
PARAMS de grand_balayage_ml. Cout 6,55, multiplicatif.

FUITES : `tg_poste` exclu (connu apres 45 s). Les cibles viennent de df.attrs["CIBLES"] et ne
sont jamais dans X. Les compteurs historiques de la table ne comptent que les jetons nes avant.

A LA FIN : les 15 variables les plus utiles de la foret de GAIN sur la derniere coupe, par
famille -- pour savoir OU l information est, si elle est quelque part.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DOSSIER = "/app/data/recherche/tout"
COUT = float(os.environ.get("COUT_MESURE", "0.0655"))
MISE = 20.0
PAS_H = 6
EXCLUES = {"tg_poste"}
PARAMS = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=40,
              subsample=0.8, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0, verbose=-1)
N_MODELES = 6


def net(r):
    return (1.0 + r) * (1.0 - COUT) - 1.0


def main() -> None:
    df = pd.read_pickle(os.path.join(DOSSIER, "table.pkl"))
    variables = [v for v in df.attrs["VARIABLES"] if v not in EXCLUES]
    df = df[(df["eligible"] == 1) & df["ret_240"].notna()].sort_values("t_dec").reset_index(drop=True)
    # V1_SEUL=1 : ne garder que les tickets qui ONT des donnees de transactions, pour que la foret
    # ne voie jamais de trous combles a la mediane sur la famille qu elle prefere (le collecteur v1
    # s arrete quand son quota Helius est atteint : 18/09 couvert jusqu a 9h seulement)
    if os.environ.get("V1_SEUL") == "1" and "v1_n_achats" in df.columns:
        df = df[df["v1_n_achats"].notna()].reset_index(drop=True)
        print("V1_SEUL : %d tickets avec donnees de transactions" % len(df))
    # MELANGE=<graine> : la LOI DU MAXIMUM pour la marche avant. On permute les RESULTATS entre
    # tickets (variables intactes) et on refait toute la marche avant : ce que la foret de gain
    # « trouve » alors est ce qu elle fabrique toute seule. A comparer au +1,05 % reel.
    if os.environ.get("MELANGE"):
        g = np.random.default_rng(int(os.environ["MELANGE"]))
        df["ret_240"] = df["ret_240"].to_numpy()[g.permutation(len(df))]
    RAPIDE = os.environ.get("RAPIDE") == "1"        # seulement la foret de gain (pour les tirages)
    X_all = df[variables].apply(pd.to_numeric, errors="coerce").astype(float)
    # une variable constante ou vide sur toute la table n apprend rien et fait planter la foret
    garde = [v for v in variables if X_all[v].notna().sum() >= 100 and X_all[v].nunique(dropna=True) >= 2]
    X_all = X_all[garde]
    y_net = net(df["ret_240"].to_numpy())
    y_vid = (df["ret_240"] <= -0.5).astype(int).to_numpy()
    y_gain = (y_net > 0).astype(int)
    t = df["t_dec"].to_numpy()
    print("table unique : %d tickets executables · %d variables retenues sur %d · cout %.2f pt"
          % (len(df), len(garde), len(variables), 100 * COUT))
    print()

    tz = dt.timezone(dt.timedelta(hours=2))
    c = dt.datetime(2026, 9, 16, 0, 0, tzinfo=tz)
    fin = dt.datetime(2026, 9, 18, 18, 0, tzinfo=tz)
    tot = {k: [] for k in ("temoin", "vid_foret30", "vid_foret50", "gain_foret30", "gain_foret50",
                           "gain_boost30", "gain_boost50")}
    print("   %-11s %4s %8s | %8s %8s | %8s %8s | %8s %8s" % (
        "fenetre", "n", "temoin", "vidF30", "vidF50", "gainF30", "gainF50", "gainB30", "gainB50"))
    derniere_rf = None
    while c < fin:
        c0, c1 = c.timestamp(), (c + dt.timedelta(hours=PAS_H)).timestamp()
        A = t < c0
        J = (t >= c0) & (t < c1)
        if A.sum() < 150 or J.sum() < 20:
            c += dt.timedelta(hours=PAS_H)
            continue
        XA, XJ = X_all[A], X_all[J]
        med = XA.median()
        XA_f, XJ_f = XA.fillna(med).fillna(0.0), XJ.fillna(med).fillna(0.0)
        rf_g = RandomForestClassifier(n_estimators=300, min_samples_leaf=20, n_jobs=-1, random_state=0).fit(XA_f, y_gain[A])
        derniere_rf = rf_g
        p_g = rf_g.predict_proba(XJ_f)[:, 1]
        if RAPIDE:
            p_v, p_b = p_g, p_g
        else:
            rf_v = RandomForestClassifier(n_estimators=300, min_samples_leaf=20, n_jobs=-1, random_state=0).fit(XA_f, y_vid[A])
            bo = [lgb.LGBMClassifier(**PARAMS, random_state=s).fit(XA, y_gain[A]) for s in range(N_MODELES)]
            p_v = rf_v.predict_proba(XJ_f)[:, 1]
            p_b = np.mean([m.predict_proba(XJ)[:, 1] for m in bo], axis=0)
        nets = y_net[J]
        n = len(nets)
        k30, k50 = max(5, int(n * 0.3)), max(5, n // 2)
        res = {"temoin": nets,
               "vid_foret30": nets[np.argsort(p_v, kind="stable")[:k30]],
               "vid_foret50": nets[np.argsort(p_v, kind="stable")[:k50]],
               "gain_foret30": nets[np.argsort(-p_g, kind="stable")[:k30]],
               "gain_foret50": nets[np.argsort(-p_g, kind="stable")[:k50]],
               "gain_boost30": nets[np.argsort(-p_b, kind="stable")[:k30]],
               "gain_boost50": nets[np.argsort(-p_b, kind="stable")[:k50]]}
        for k in tot:
            tot[k].extend(res[k].tolist())
        print("   %-11s %4d %+7.2f%% | %+7.2f%% %+7.2f%% | %+7.2f%% %+7.2f%% | %+7.2f%% %+7.2f%%" % (
            c.strftime("%d/%m %Hh"), n, 100 * nets.mean(),
            100 * res["vid_foret30"].mean(), 100 * res["vid_foret50"].mean(),
            100 * res["gain_foret30"].mean(), 100 * res["gain_foret50"].mean(),
            100 * res["gain_boost30"].mean(), 100 * res["gain_boost50"].mean()), flush=True)
        c += dt.timedelta(hours=PAS_H)

    print()
    print("TOUTE LA PERIODE, additionnee")
    for k, v in tot.items():
        v = np.array(v)
        if len(v) < 5:
            continue
        s = np.sort(v)
        print("   %-13s n=%4d  net %+6.2f %%/ticket = %+7.0f EUR · sans 3 meil. %+6.2f %% · gagnants %3.0f %% · cata %3.0f %%"
              % (k, len(v), 100 * v.mean(), MISE * v.sum(), 100 * s[:-3].mean(), 100 * (v > 0).mean(), 100 * (v < -0.5).mean()))

    if derniere_rf is not None:
        print()
        print("OU EST L INFORMATION ? les 15 variables les plus utiles de la foret de GAIN (derniere coupe)")
        imp = sorted(zip(derniere_rf.feature_importances_, garde), reverse=True)[:15]
        for i, v in imp:
            print("   %-28s %.3f   famille %s" % (v, i, v.split("_")[0]))
        fam = {}
        for i, v in zip(derniere_rf.feature_importances_, garde):
            fam[v.split("_")[0]] = fam.get(v.split("_")[0], 0.0) + i
        print("   par famille :", " · ".join("%s %.0f%%" % (k, 100 * v) for k, v in sorted(fam.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
