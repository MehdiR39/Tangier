#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Toutes les metriques on-chain disponibles, testees de la meme facon.

Jusqu'ici une seule metrique avait ete essayee : la croissance des adresses actives. Le fichier
`coinmetrics.csv` en contient six, et rien ne dit que ce soit la bonne. On les passe toutes au meme
test -- ecart entre sextile haut et sextile bas sur trente jours, plus l'IC -- sur la periode de
calibration ET sur 2020-2021 qui n'a jamais servi.

Chaque metrique est testee en NIVEAU et en CROISSANCE 90 jours, dans les deux sens (haut et bas),
parce que rien ne dit a priori qu'une MVRV elevee soit bonne ou mauvaise.

Regle du projet : un signal se juge sur sa reproduction dans une periode jamais regardee, et sur le
nombre de periodes qui le portent -- pas sur sa moyenne.

Aucune position, aucun ordre : lecture de fichiers deja sur le disque.
"""
import os
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT, RAW = os.path.join(ROOT, "data_onchain"), os.path.join(ROOT, "data_raw")
REB, LB, K = 30, 90, 6


def charger(price_csv, start, end):
    price = pd.read_csv(os.path.join(RAW, price_csv), index_col=0, parse_dates=True)
    price = price.loc[(price.index >= start) & (price.index <= end)]
    cm = pd.read_csv(os.path.join(OUT, "coinmetrics.csv"), parse_dates=["date"])
    return price, cm


def evaluer(price, cm, metrique, mode):
    piv = cm[cm.metric == metrique].pivot_table(index="date", columns="coin", values="value")
    coins = [c for c in piv.columns if (c + "USDT") in price.columns]
    if len(coins) < 2 * K:
        return None
    cal = price.index
    px = price[[c + "USDT" for c in coins]].copy(); px.columns = coins
    base = piv[coins].reindex(cal).ffill(limit=7)
    sig = base.pct_change(LB) if mode == "croissance" else base
    ecarts, ics = [], []
    for t0 in cal[LB + 1::REB]:
        fin = t0 + pd.Timedelta(days=REB)
        if fin > cal[-1]:
            break
        t1 = cal[cal <= fin][-1]
        fwd = (px.loc[t1] / px.loc[t0] - 1)
        v = sig.loc[t0]
        comm = [c for c in coins if np.isfinite(v.get(c, np.nan)) and np.isfinite(fwd.get(c, np.nan))]
        if len(comm) < 2 * K:
            continue
        v2, f2 = v[comm], fwd[comm]
        o = v2.sort_values(ascending=False).index
        ecarts.append(f2[list(o[:K])].mean() - f2[list(o[-K:])].mean())
        ics.append(spearmanr(v2.values, f2.values).statistic)
    if len(ecarts) < 8:
        return None
    e = np.array(ecarts)
    return dict(n=len(e), ecart=e.mean(), med=np.median(e), pos=100 * (e > 0).mean(), ic=np.nanmean(ics))


p1, cm = charger("broad_2020_2026.csv", "2020-10-01", "2022-01-31")
p2, _ = charger("broad_daily_close_current.csv", "2022-01-01", "2026-07-31")
metriques = sorted(cm.metric.unique())

print("  %-16s %-11s | %-28s | %-28s" % ("metrique", "mode", "2020-2021  HORS ECHANTILLON", "2022-2026"))
print("  %-16s %-11s | %6s %8s %6s %7s | %6s %8s %6s %7s" % ("", "", "n", "ecart", "pos%", "IC", "n", "ecart", "pos%", "IC"))
print("  " + "-" * 96)
gardees = []
for m in metriques:
    for mode in ("croissance", "niveau"):
        a = evaluer(p1, cm, m, mode); b = evaluer(p2, cm, m, mode)
        if not a or not b:
            continue
        marque = ""
        if a["ecart"] > 0 and b["ecart"] > 0 and a["pos"] >= 50 and b["pos"] >= 50:
            marque = "  <== positif des deux cotes"
            gardees.append((m, mode, a, b))
        print("  %-16s %-11s | %6d %+7.1f%% %5.0f%% %+7.3f | %6d %+7.1f%% %5.0f%% %+7.3f%s" % (
            m, mode, a["n"], 100 * a["ecart"], a["pos"], a["ic"],
            b["n"], 100 * b["ecart"], b["pos"], b["ic"], marque))

print()
if gardees:
    print("  %d combinaison(s) positives dans les deux periodes ET portees par la majorite des periodes :" % len(gardees))
    for m, mode, a, b in gardees:
        print("    %s / %s" % (m, mode))
else:
    print("  AUCUNE metrique n'est positive des deux cotes avec la majorite des periodes.")
