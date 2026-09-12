#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""La synthese : quel reglage est positif dans LES TROIS periodes independantes ?

  2018-06 -> 2020-10   bear 2018, reprise 2019, krach Covid   ~26 rebalancements
  2020-10 -> 2022-01   le bull                                ~12
  2022-01 -> 2026-07   bear, consolidation, reprise           ~52

Aucune n'a servi a calibrer quoi que ce soit : la metrique, la fenetre et K sont balayes, et on ne
retient que ce qui tient partout. Un balayage trouve toujours un maximum -- la seule question est
combien de reglages voisins le partagent.

Aucune position, aucun ordre.
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT, RAW = os.path.join(ROOT, "data_onchain"), os.path.join(ROOT, "data_raw")
FEE, PORTAGE, REB = 0.0015, 0.10, 30


def cagr(price, cm, metrique, LB, K):
    piv = cm[cm.metric == metrique].pivot_table(index="date", columns="coin", values="value")
    coins = [c for c in piv.columns if (c + "USDT") in price.columns]
    if len(coins) < 2 * K:
        return np.nan
    cal = price.index
    p = price[[c + "USDT" for c in coins]].copy(); p.columns = coins
    sig = piv[coins].reindex(cal).ffill(limit=7).pct_change(LB)
    bnds = list(cal[LB + 1::REB]) + [cal[-1]]
    if len(bnds) < 6:
        return np.nan
    val = 1.0; n = 0
    for i in range(len(bnds) - 1):
        t0, t1 = bnds[i], bnds[i + 1]
        v = sig.loc[t0].dropna()
        v = v[[c for c in v.index if np.isfinite(p.loc[t0, c])]]
        seg = cal[(cal > t0) & (cal <= t1)]
        if len(v) < 2 * K or not len(seg):
            continue
        o = v.sort_values(ascending=False).index
        haut, bas = list(o[:K]), list(o[-K:])
        val *= (1 - 2 * FEE)
        qh = (0.5 / K) / p.loc[t0, haut]; qb = (0.5 / K) / p.loc[t0, bas]
        base = val
        for j, d in enumerate(seg, 1):
            val = base * ((qh * p.loc[d, haut]).sum() + 1.0 - (qb * p.loc[d, bas]).sum()) * (1 - PORTAGE / 365) ** j
        n += 1
    if n < 6 or val <= 0:
        return np.nan
    ans = (cal[-1] - cal[LB + 1]).days / 365.25
    return val ** (1 / ans) - 1 if ans > 0 else np.nan


def prep(f, a, b):
    px = pd.read_csv(os.path.join(RAW, f), index_col=0, parse_dates=True)
    return px.loc[(px.index >= a) & (px.index <= b)]


cm = pd.read_csv(os.path.join(OUT, "coinmetrics.csv"), parse_dates=["date"])
P = [("2018-2020", prep("broad_2017_2021.csv", "2018-06-01", "2020-10-14")),
     ("2020-2021", prep("broad_2020_2026.csv", "2020-10-15", "2022-01-31")),
     ("2022-2026", prep("broad_daily_close_current.csv", "2022-01-01", "2026-07-31"))]

print("  CAGR long-short net (portage 10 %/an, frais 15 pb/jambe)")
print("  %-11s %4s %3s | %10s %10s %10s | %s" % ("metrique", "fen", "K", *[x[0] for x in P], "3/3"))
print("  " + "-" * 68)
trois = []
for metrique in ("TxCnt", "AdrActCnt", "TxTfrCnt"):
    for LB in (60, 90, 120, 180):
        for K in (4, 5, 6):
            v = [cagr(px, cm, metrique, LB, K) for _, px in P]
            if any(np.isnan(x) for x in v):
                continue
            ok = all(x > 0 for x in v)
            if ok:
                trois.append((metrique, LB, K, v))
            print("  %-11s %4d %3d | %+9.1f%% %+9.1f%% %+9.1f%% | %s" % (
                metrique, LB, K, 100 * v[0], 100 * v[1], 100 * v[2], "OUI" if ok else ""))
print()
print("  " + "#" * 66)
print("  Reglages positifs dans LES TROIS periodes : %d" % len(trois))
for m, lb, k, v in trois:
    print("    %-10s fenetre %3dj  K=%d   %+.1f%% / %+.1f%% / %+.1f%%" % (m, lb, k, 100 * v[0], 100 * v[1], 100 * v[2]))
