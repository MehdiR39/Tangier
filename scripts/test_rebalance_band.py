#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Quick test: $50-band rebalancing around a $1000-per-coin anchor.

Portfolio: $1000 each in SOL, RENDER, PENDLE, XRP + $1000 USDC (=$5000).
Rule: whenever a coin's value rises >= anchor+50 -> sell the excess into USDC;
      whenever it falls <= anchor-50 -> buy from USDC (if any) back to anchor.
Compared to buy & hold of the identical starting portfolio.
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
ANCHOR, BAND, USDC0 = 1000.0, 50.0, 1000.0
FEE = 0.001   # 0.1% per trade


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
    idx = [dt.datetime.utcfromtimestamp(k[0] / 1000).strftime("%Y-%m-%d") for k in d]
    return pd.Series([float(k[4]) for k in d], index=pd.to_datetime(idx))


print("Fetching prices ...", flush=True)
series = {}
for name, sym in COINS.items():
    s = daily(sym)
    if s is None and name == "RENDER":
        s = daily("RNDRUSDT")
    series[name] = s
    print(f"  {name:<7} {len(s) if s is not None else 0} days")
px = pd.DataFrame(series).dropna()
print(f"Common window: {px.index.min().date()} -> {px.index.max().date()} ({len(px)} days)")

coins = list(px.columns)


def run_band():
    units = {c: ANCHOR / px[c].iloc[0] for c in coins}
    usdc = USDC0
    tot, trades, fees = [], 0, 0.0
    for _, row in px.iterrows():
        for c in coins:
            val = units[c] * row[c]
            if val - ANCHOR >= BAND:                      # take profit to stable
                excess = val - ANCHOR
                usdc += excess * (1 - FEE); fees += excess * FEE
                units[c] = ANCHOR / row[c]; trades += 1
            elif ANCHOR - val >= BAND and usdc > 0:       # buy the dip from stable
                buy = min(ANCHOR - val, usdc)
                usdc -= buy; units[c] += buy * (1 - FEE) / row[c]
                fees += buy * FEE; trades += 1
        tot.append(usdc + sum(units[c] * row[c] for c in coins))
    return pd.Series(tot, index=px.index), usdc, trades, fees, units


def run_hold():
    units = {c: ANCHOR / px[c].iloc[0] for c in coins}
    tot = [USDC0 + sum(units[c] * row[c] for c in coins) for _, row in px.iterrows()]
    return pd.Series(tot, index=px.index)


band_eq, usdc_end, trades, fees, units_end = run_band()
hold_eq = run_hold()


def stats(eq):
    ret = eq.pct_change().dropna()
    dd = (eq / eq.cummax() - 1).min()
    return eq.iloc[-1], eq.iloc[-1] / eq.iloc[0] - 1, dd, (ret.mean() / ret.std() * np.sqrt(365) if ret.std() else 0)


b = stats(band_eq); h = stats(hold_eq)
print("\n" + "=" * 68)
print(f"RESULTAT  ($5000 depart: $1000 x4 crypto + $1000 USDC)  {px.index.min().date()}..{px.index.max().date()}")
print("=" * 68)
print(f"  {'':<22}{'valeur fin':>12}{'perf':>9}{'maxDD':>9}{'Sharpe':>8}")
print(f"  {'Stratégie bande $50':<22}{b[0]:>11.0f}${b[1]:>+8.0%}{b[2]:>8.0%}{b[3]:>8.2f}")
print(f"  {'Buy & Hold (identique)':<22}{h[0]:>11.0f}${h[1]:>+8.0%}{h[2]:>8.0%}{h[3]:>8.2f}")
print(f"\n  Trades: {trades}  |  frais payés: ${fees:.0f}  |  USDC final: ${usdc_end:.0f}")
print(f"  Alloc finale crypto: " + ", ".join(f"{c}=${units_end[c]*px[c].iloc[-1]:.0f}" for c in coins))
print(f"  -> la stratégie {'BAT' if b[0] > h[0] else 'PERD contre'} le buy&hold "
      f"de ${abs(b[0]-h[0]):.0f} ({(b[0]/h[0]-1):+.1%})")

fig, ax = plt.subplots(figsize=(12, 6))
ax.plot(band_eq.index, band_eq.values, label=f"Stratégie bande $50 (fin ${b[0]:.0f})", color="green", lw=2)
ax.plot(hold_eq.index, hold_eq.values, label=f"Buy & Hold (fin ${h[0]:.0f})", color="gray", lw=1.6, ls="--")
ax.axhline(5000, color="black", lw=0.8, alpha=0.5)
ax.set_title(f"Rebalancing bande ±$50 vs Buy&Hold — SOL/RENDER/PENDLE/XRP + USDC\n"
             f"{px.index.min().date()} → {px.index.max().date()}  |  {trades} trades")
ax.set_ylabel("valeur portefeuille ($)"); ax.legend(); ax.grid(alpha=0.3)
png = os.path.join(OUT, "band_strategy.png"); fig.tight_layout(); fig.savefig(png, dpi=110)
print(f"\nplot -> {png}")
