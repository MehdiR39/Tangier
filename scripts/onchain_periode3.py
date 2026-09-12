#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Troisieme periode, jamais regardee : 2018-2020.

Les deux periodes existantes ne suffisaient pas -- 2020-2021 ne compte que douze rebalancements, et
le balayage de robustesse y donnait des ecarts de 90 points entre reglages voisins, ce qui empeche
de distinguer un signal absent d'un echantillon trop court.

2018-06 -> 2020-10 apporte le creux du bear 2018, la reprise 2019 et le krach Covid : des regimes
absents des deux autres periodes, et environ vingt-huit rebalancements. Le panier est plus etroit
(huit a douze actifs selon la date), donc K=4.

On mesure la MEME chose que pour les autres periodes, sans rien reajuster.

Aucune position, aucun ordre.
"""
import os
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT, RAW = os.path.join(ROOT, "data_onchain"), os.path.join(ROOT, "data_raw")
FEE, PORTAGE, REB = 0.0015, 0.10, 30


def prep(price_csv, start, end):
    px = pd.read_csv(os.path.join(RAW, price_csv), index_col=0, parse_dates=True)
    return px.loc[(px.index >= start) & (px.index <= end)]


def mesurer(price, cm, metrique, LB, K):
    piv = cm[cm.metric == metrique].pivot_table(index="date", columns="coin", values="value")
    coins = [c for c in piv.columns if (c + "USDT") in price.columns]
    if len(coins) < 2 * K:
        return None
    cal = price.index
    p = price[[c + "USDT" for c in coins]].copy(); p.columns = coins
    sig = piv[coins].reindex(cal).ffill(limit=7).pct_change(LB)
    bnds = list(cal[LB + 1::REB]) + [cal[-1]]
    if len(bnds) < 6:
        return None
    val = 1.0; ecarts = []; ics = []; n = 0
    for i in range(len(bnds) - 1):
        t0, t1 = bnds[i], bnds[i + 1]
        v = sig.loc[t0].dropna()
        v = v[[c for c in v.index if np.isfinite(p.loc[t0, c])]]
        seg = cal[(cal > t0) & (cal <= t1)]
        if len(v) < 2 * K or not len(seg):
            continue
        o = v.sort_values(ascending=False).index
        haut, bas = list(o[:K]), list(o[-K:])
        fwd = (p.loc[seg[-1]] / p.loc[t0] - 1)
        ecarts.append(fwd[haut].mean() - fwd[bas].mean())
        comm = [c for c in v.index if np.isfinite(fwd.get(c, np.nan))]
        if len(comm) > 3:
            ics.append(spearmanr(v[comm].values, fwd[comm].values).statistic)
        val *= (1 - 2 * FEE)
        qh = (0.5 / K) / p.loc[t0, haut]; qb = (0.5 / K) / p.loc[t0, bas]
        base = val
        for j, d in enumerate(seg, 1):
            val = base * ((qh * p.loc[d, haut]).sum() + 1.0 - (qb * p.loc[d, bas]).sum()) * (1 - PORTAGE / 365) ** j
        n += 1
    if n < 6:
        return None
    ans = (cal[-1] - cal[LB + 1]).days / 365.25
    e = np.array(ecarts)
    return dict(n=n, cagr=(val ** (1 / ans) - 1) if val > 0 and ans > 0 else -1.0,
                ecart=e.mean(), pos=100 * (e > 0).mean(), ic=np.nanmean(ics), coins=len(coins))


cm = pd.read_csv(os.path.join(OUT, "coinmetrics.csv"), parse_dates=["date"])
p3 = prep("broad_2017_2021.csv", "2018-06-01", "2020-10-14")

print("  TROISIEME PERIODE 2018-06 -> 2020-10, jamais regardee")
print("  long-short net, portage 10 %/an, K=4\n")
print("  %-12s %6s | %6s %8s %7s %8s %7s" % ("metrique", "fenetre", "rebal", "CAGR", "ecart", "pos%", "IC"))
print("  " + "-" * 62)
bilan = {}
for metrique in ("TxCnt", "AdrActCnt", "TxTfrCnt"):
    ok = 0; tot = 0
    for LB in (45, 60, 90, 120):
        r = mesurer(p3, cm, metrique, LB, 4)
        if not r:
            print("  %-12s %6d | donnees insuffisantes" % (metrique, LB)); continue
        tot += 1; ok += r["cagr"] > 0
        print("  %-12s %6d | %6d %+7.1f%% %+6.1f%% %7.0f%% %+7.3f" % (
            metrique, LB, r["n"], 100 * r["cagr"], 100 * r["ecart"], r["pos"], r["ic"]))
    bilan[metrique] = (ok, tot)
    print()
print("  " + "#" * 60)
for m, (ok, tot) in bilan.items():
    print("  %-12s positif sur %d/%d fenetres de la 3e periode" % (m, ok, tot))
