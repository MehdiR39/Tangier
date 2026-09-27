"""LE SIGNAL TIENT-IL SUR LA VUE TRONQUEE, celle qu on aura vraiment a 45 s ?

LA QUESTION DE MIDO, 19/09 : « si on n a pas la donnee, tu l as testee sur une donnee fausse ? »
Non -- la donnee est vraie, mais elle n est pas DISPONIBLE. §3.155 prouve que ce qui se passe dans
les 45 premieres secondes predit la suite. Ce que le moteur peut VOIR a 45 s est autre chose :
l index des transactions retarde d une dizaine de secondes (5 pools sur 6 incomplets, 122
transactions manquantes en median), et ce qui manque, ce sont les DERNIERES.

D OU CE TEST, qui ne demande aucune collecte nouvelle. On recalcule exactement les memes 16
variables en ne gardant que les transactions d age <= T, pour T de 20 a 45 s, et on refait tourner
la meme marche avant. Tronquer a 30 s, c est justement la vue qu on aurait en interrogeant a 45 s
avec 15 s de retard d index.

  si le signal tient a 30-35 s  -> la vue tronquee suffit : on decide a 45 s comme aujourd hui,
                                   on entraine sur la vue tronquee, et rien d autre ne bouge
  s il s ecroule                -> tout se joue dans les dernieres secondes ; il faudra retarder la
                                   decision, donc remesurer le cout d entree (§3.152)

PROTOCOLE identique a foret_vidage_plus.py -- marche avant par coupes de 6 h du 16/09 au 18/09 18h,
entrainement sur tout ce qui precede, on garde 80 % (le seuil p80 de la foret en service, fixe
d avance), cout 2,98 pt, cible vidage = net <= -50 %. SEULE la troncature varie. Les variables sont
relues depuis `v1_avant`, pas depuis la table : la table les a deja figees a 45 s.

BARRE DU HASARD sur le MEILLEUR des troncatures essayees -- en ecarts-types, pas en euros bruts :
comparer des cellules d effectifs differents en euros revient a choisir la plus petite, l erreur
corrigee ce matin dans flux_severite_t.py.
"""
from __future__ import annotations

import collections
import datetime as dt
import glob
import json
import os
import statistics as st
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

warnings.filterwarnings("ignore")
DOSSIER = "/app/data/recherche/tout"
V1 = "/app/data/recherche/v1_avant"
COUT = float(os.environ.get("COUT_MESURE", "0.0298"))
MISE = 20.0
GARDE = 0.80
RECURRENT = 5
NULLS = int(os.environ.get("NULLS", "40"))
AGES = [20, 25, 30, 35, 40, 45]


def net(r):
    return (1.0 + r) * (1.0 - COUT) - 1.0


def charger():
    """Les pools de v1_avant, tries par naissance -- l ordre compte pour l historique des robots."""
    pools = []
    for f in sorted(glob.glob(os.path.join(V1, "*.jsonl"))):
        with open(f, encoding="utf-8") as fh:
            for ligne in fh:
                try:
                    d = json.loads(ligne)
                except Exception:  # noqa: BLE001
                    continue
                if d.get("tx"):
                    pools.append((float(d.get("naissance") or 0), d))
    pools.sort(key=lambda x: x[0])
    return pools


def variables(pools, age_max):
    """Les 16 variables, calculees en ne gardant que les transactions d age <= age_max.

    L historique des portefeuilles (`vus`) est reconstruit dans l ordre chronologique et mis a jour
    APRES chaque pool : un robot est recurrent parce qu il a ete vu sur des pools NES AVANT.
    """
    vus = collections.defaultdict(set)
    feats = {}
    for _, d in pools:
        pair = d.get("pair")
        achats, ventes = [], []
        acheteurs, vendeurs = set(), set()
        premier, robots, sol_robots = None, 0, 0.0
        sol_par_wallet = collections.defaultdict(float)
        for tx in d.get("tx") or []:
            try:
                age, parts = int(tx[0]), tx[2]
            except Exception:  # noqa: BLE001
                continue
            if age > age_max:
                continue
            for p in parts or []:
                try:
                    q, dj, ds = str(p[0]), float(p[1]), float(p[2])
                except Exception:  # noqa: BLE001
                    continue
                sol_par_wallet[q] += ds
                if dj > 0 and ds < 0:
                    achats.append(-ds)
                    acheteurs.add(q)
                    if premier is None:
                        premier = age
                    if len(vus[q]) >= RECURRENT:
                        robots += 1
                        sol_robots += -ds
                elif dj < 0 and ds > 0:
                    ventes.append(ds)
                    vendeurs.add(q)
        sans = [v for q, v in sol_par_wallet.items() if v > 0 and q not in acheteurs]
        sa, sv = sum(achats), sum(ventes)
        gini = None
        if len(achats) >= 2 and sa > 0:
            a = sorted(achats)
            n = len(a)
            gini = 2 * sum((i + 1) * x for i, x in enumerate(a)) / (n * sa) - (n + 1) / n
        feats[pair] = {
            "v1_n_achats": len(achats), "v1_n_ventes": len(ventes),
            "v1_acheteurs": len(acheteurs), "v1_vendeurs": len(vendeurs),
            "v1_sol_achats": sa, "v1_sol_ventes": sv,
            "v1_ratio_ventes": (sv / sa) if sa > 0 else None,
            "v1_premier_achat": premier,
            "v1_achat_median": st.median(achats) if achats else None,
            "v1_achat_max": max(achats) if achats else None,
            "v1_gini_achats": gini, "v1_robots": robots,
            "v1_part_robots": (sol_robots / sa) if sa > 0 else None,
            "v1_vendeurs_sans_achat": len(sans), "v1_sol_sans_achat": sum(sans),
            "v1_part_sans_achat": (sum(sans) / sv) if sv > 0 else None,
        }
        for q in acheteurs:
            vus[q].add(pair)
    return pd.DataFrame.from_dict(feats, orient="index")


def main() -> None:
    base = pd.read_pickle(os.path.join(DOSSIER, "table.pkl"))
    base = base[(base["eligible"] == 1) & base["ret_240"].notna()]
    base = base[["pair", "t_dec", "ret_240"]].sort_values("t_dec").reset_index(drop=True)
    pools = charger()
    print("%d pools relus depuis v1_avant · %d tickets eligibles · cout %.2f pt · on garde %.0f %%"
          % (len(pools), len(base), 100 * COUT, 100 * GARDE))
    print()

    tz = dt.timezone(dt.timedelta(hours=2))
    DEBUT = dt.datetime(2026, 9, 16, 0, 0, tzinfo=tz)
    FIN = dt.datetime(2026, 9, 18, 18, 0, tzinfo=tz)

    jeux = {}
    for age in AGES:
        x = variables(pools, age)
        df = base.merge(x, left_on="pair", right_index=True, how="inner")
        cols = [c for c in x.columns if df[c].notna().sum() >= 100
                and pd.to_numeric(df[c], errors="coerce").nunique(dropna=True) >= 2]
        jeux[age] = (df.reset_index(drop=True), cols)
        print("   %2d s : %4d tickets · %2d variables utilisables" % (age, len(df), len(cols)))

    def marche(age, perm=None):
        df, cols = jeux[age]
        y = net(df["ret_240"].to_numpy(dtype=float))
        if perm is not None:
            y = y[perm]
        v = (y <= -0.5).astype(int)
        t = df["t_dec"].to_numpy()
        X = df[cols].apply(pd.to_numeric, errors="coerce").astype(float)
        gardes, tem = [], []
        c = DEBUT
        while c < FIN:
            c0, c1 = c.timestamp(), (c + dt.timedelta(hours=6)).timestamp()
            A, J = t < c0, (t >= c0) & (t < c1)
            c += dt.timedelta(hours=6)
            if A.sum() < 150 or J.sum() < 20:
                continue
            nets = y[J]
            tem.extend(nets.tolist())
            med = X[A].median()
            rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=20, n_jobs=-1,
                                        random_state=0).fit(X[A].fillna(med).fillna(0), v[A])
            p = rf.predict_proba(X[J].fillna(med).fillna(0))[:, 1]
            k = max(5, int(len(nets) * GARDE))
            gardes.extend(nets[np.argsort(p, kind="stable")[:k]].tolist())
        return np.array(gardes), np.array(tem)

    print()
    print("   %-9s %6s %11s %11s %12s %9s" %
          ("vu jusqu a", "n", "EUR/tick", "vs temoin", "sans 3 meil.", "ecarts-t"))
    res = {}
    for age in AGES:
        g, tem = marche(age)
        if len(g) < 20:
            continue
        sigma = MISE * np.concatenate([g, tem]).std(ddof=1)
        n, k = len(tem), len(g)
        bruit = sigma * np.sqrt((n - k) / (n * k)) if 0 < k < n else np.inf
        d = MISE * (g.mean() - tem.mean())
        s = np.sort(g)
        res[age] = d / bruit
        print("   %-9s %6d %+10.3f %+10.3f %+11.3f %+8.2f"
              % ("%d s" % age, k, MISE * g.mean(), d, MISE * (s[:-3].mean() - tem.mean()), d / bruit))

    if NULLS and res:
        print()
        print("BARRE DU HASARD : %d marches avant permutees, on retient LE MEILLEUR des %d troncatures"
              % (NULLS, len(AGES)))
        rng = np.random.default_rng(41)
        maxs = []
        for i in range(NULLS):
            m = []
            for age in AGES:
                df, _ = jeux[age]
                g, tem = marche(age, rng.permutation(len(df)))
                if len(g) < 20:
                    continue
                sigma = MISE * np.concatenate([g, tem]).std(ddof=1)
                n, k = len(tem), len(g)
                b = sigma * np.sqrt((n - k) / (n * k)) if 0 < k < n else np.inf
                m.append(MISE * (g.mean() - tem.mean()) / b)
            if m:
                maxs.append(max(m))
            if (i + 1) % 10 == 0:
                print("   %d/%d · max hasard %+0.2f ecarts-types" % (i + 1, NULLS, max(maxs)), flush=True)
        meilleur = max(res, key=res.get)
        ks = sum(1 for x in maxs if x >= res[meilleur])
        print("   -> meilleure troncature %d s a %+.2f sigma · %d tirages sur %d font aussi bien (p ~ %.3f)"
              % (meilleur, res[meilleur], ks, len(maxs), (ks + 1) / (len(maxs) + 1)))


if __name__ == "__main__":
    main()
