#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test the $50-band rebalancing strategy in BULL / BEAR / CONSOLIDATION separately.

Regimes are labelled objectively from BTC (MA100 + 90d return); we take the
longest contiguous window of each type inside the 4-coin common history and run
the strategy (fresh $5000 = $1000 x4 + $1000 USDC) vs buy&hold in each.
"""
import os
import ssl
import json
import time
import datetime as dt
import urllib.request
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data_onchain")
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = {"User-Agent": "Mozilla/5.0"}
COINS = {"SOL": "SOLUSDT", "RENDER": "RENDERUSDT", "PENDLE": "PENDLEUSDT", "XRP": "XRPUSDT"}
ANCHOR, BAND, USDC0, FEE = 1000.0, 50.0, 1000.0, 0.001


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40, context=CTX) as r:
                return json.load(r)
        except Exception:
            time.sleep(1.0 * (2 ** i))
    return None


def daily(sym, limit=1000):
    d = get(f"https://data-api.binance.vision/api/v3/klines?symbol={sym}&interval=1d&limit={limit}")
    if not isinstance(d, list) or not d:
        return None
    idx = [dt.datetime.fromtimestamp(k[0] / 1000, dt.timezone.utc).strftime("%Y-%m-%d") for k in d]
    return pd.Series([float(k[4]) for k in d], index=pd.to_datetime(idx))


def regimes(btc):
    ma = btc.rolling(100, min_periods=50).mean(); r90 = btc.pct_change(90)
    reg = pd.Series("consolidation", index=btc.index)
    reg[(r90 > 0.30) & (btc > ma)] = "bull"
    reg[(r90 < -0.15) | ((btc < ma) & (r90 < 0))] = "bear"
    return reg


def run_band(px):
    coins = list(px.columns)
    units = {c: ANCHOR / px[c].iloc[0] for c in coins}
    usdc = USDC0; tot = []; trades = 0
    for _, row in px.iterrows():
        for c in coins:
            val = units[c] * row[c]
            if val - ANCHOR >= BAND:
                usdc += (val - ANCHOR) * (1 - FEE); units[c] = ANCHOR / row[c]; trades += 1
            elif ANCHOR - val >= BAND and usdc > 0:
                buy = min(ANCHOR - val, usdc); usdc -= buy
                units[c] += buy * (1 - FEE) / row[c]; trades += 1
        tot.append(usdc + sum(units[c] * row[c] for c in coins))
    return pd.Series(tot, index=px.index), trades


def run_hold(px):
    coins = list(px.columns)
    u = {c: ANCHOR / px[c].iloc[0] for c in coins}
    return pd.Series([USDC0 + sum(u[c] * row[c] for c in coins) for _, row in px.iterrows()], index=px.index)


def maxdd(eq):
    return (eq / eq.cummax() - 1).min()


# --- data --------------------------------------------------------------------
print("Fetching ...", flush=True)
series = {}
for n, s in COINS.items():
    r = daily(s)
    if r is None and n == "RENDER":
        r = daily("RNDRUSDT")
    series[n] = r
px = pd.DataFrame(series).dropna()
btc = pd.read_csv(os.path.join(OUT, "btc_daily.csv"), parse_dates=["date"]).set_index("date")["close"]
reg = regimes(btc).reindex(px.index).ffill()
print(f"Common window: {px.index.min().date()} -> {px.index.max().date()} ({len(px)}d)")
print("Regime mix:", ", ".join(f"{k}={v}" for k, v in reg.value_counts().items()))

# --- longest contiguous window per regime ------------------------------------
segs = []
cur = None; start = None; prev = None
for d, lab in reg.items():
    if lab != cur:
        if cur is not None:
            segs.append((cur, start, prev))
        cur = lab; start = d
    prev = d
segs.append((cur, start, prev))

best = {}
for lab, s, e in segs:
    if lab not in best or (e - s).days > (best[lab][1] - best[lab][0]).days:
        best[lab] = (s, e)

# --- run per regime ----------------------------------------------------------
print("\n" + "=" * 84)
print("STRATÉGIE BANDE $50 vs BUY&HOLD, PAR RÉGIME  (départ $5000 à chaque fois)")
print("=" * 84)
print(f"  {'Régime':<15}{'fenêtre':<26}{'j':>4}{'BTC':>7}{'Bande':>9}{'B&H':>9}{'gagnant':>12}")
panels = []
for lab in ["bull", "consolidation", "bear"]:
    if lab not in best:
        print(f"  {lab:<15} (aucune fenêtre continue)")
        continue
    s, e = best[lab]
    sub = px.loc[s:e]
    if len(sub) < 15:
        print(f"  {lab:<15} fenêtre trop courte ({len(sub)}j)")
        continue
    band_eq, trades = run_band(sub); hold_eq = run_hold(sub)
    bperf = band_eq.iloc[-1] / band_eq.iloc[0] - 1
    hperf = hold_eq.iloc[-1] / hold_eq.iloc[0] - 1
    btc_perf = btc.loc[s:e].iloc[-1] / btc.loc[s:e].iloc[0] - 1
    win = "BANDE" if band_eq.iloc[-1] > hold_eq.iloc[-1] else "hold"
    print(f"  {lab:<15}{str(s.date())+'→'+str(e.date()):<26}{len(sub):>4}"
          f"{btc_perf:>+7.0%}{bperf:>+9.0%}{hperf:>+9.0%}{win:>12}")
    panels.append((lab, sub, band_eq, hold_eq, bperf, hperf, trades))

# --- chart -------------------------------------------------------------------
if panels:
    fig, axes = plt.subplots(1, len(panels), figsize=(6 * len(panels), 5))
    if len(panels) == 1:
        axes = [axes]
    for ax, (lab, sub, band_eq, hold_eq, bperf, hperf, trades) in zip(axes, panels):
        ax.plot(band_eq.index, band_eq.values, color="green", lw=2, label=f"Bande ({bperf:+.0%})")
        ax.plot(hold_eq.index, hold_eq.values, color="gray", lw=1.6, ls="--", label=f"Hold ({hperf:+.0%})")
        ax.axhline(5000, color="black", lw=0.7, alpha=0.4)
        ax.set_title(f"{lab.upper()}  {sub.index.min().date()}→{sub.index.max().date()}\n{trades} trades")
        ax.legend(fontsize=8); ax.grid(alpha=0.3); ax.tick_params(axis="x", rotation=30, labelsize=7)
    fig.suptitle("Stratégie bande ±$50 vs Buy&Hold par régime — SOL/RENDER/PENDLE/XRP + USDC", fontsize=12)
    png = os.path.join(OUT, "band_by_regime.png"); fig.tight_layout(); fig.savefig(png, dpi=110)
    print(f"\nplot -> {png}")
