#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase 4a - Signal diagnostics.

Question: do the on-chain / sentiment signals actually PREDICT forward returns?
We measure the Information Coefficient (Spearman rank corr between a signal at
day t and the forward return t->t+h) BEFORE building any strategy.

  * Global/macro signals vs BTC forward returns (longest 2-cycle window):
        - Fear & Greed (expect NEGATIVE IC: greed -> lower fwd return)
        - Total DeFi TVL 30d trend (expect POSITIVE: risk-on)
        - Stablecoin supply 30d growth (dry powder)
        - BTC funding rate (expect NEGATIVE: froth -> lower fwd return)
  * Cross-sectional coin selection: per-coin TVL 30d growth vs that coin's
    forward return, pooled rank-IC across coins (does on-chain value pick coins?)

Everything reported all-sample AND split by regime; the user's rule is to judge
on CONSOLIDATION + BULL only (they exit before bears).
"""
import os
import ssl
import json
import time
import urllib.request
import datetime as dt
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data_onchain")
RAW = os.path.join(ROOT, "data_raw")
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = {"User-Agent": "Mozilla/5.0 (tangier)"}
HORIZONS = [7, 14, 30, 60, 90]


# --------------------------------------------------------------------------- #
def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                        timeout=40, context=CTX) as r:
                return json.load(r)
        except Exception:  # noqa
            time.sleep(1.5 * (2 ** i))
    raise RuntimeError("get failed: " + url)


def btc_daily():
    """BTCUSDT daily close from Binance (2017->now), cached to data_onchain."""
    cache = os.path.join(OUT, "btc_daily.csv")
    if os.path.exists(cache):
        s = pd.read_csv(cache, parse_dates=["date"]).set_index("date")["close"]
        return s
    rows, start = [], 1500000000000  # ~2017-07
    base = "https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=1000"
    while True:
        d = get(base + f"&startTime={start}")
        if not d:
            break
        for k in d:
            day = dt.datetime.fromtimestamp(k[0] / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
            rows.append([day, float(k[4])])
        start = d[-1][0] + 1
        if len(d) < 1000:
            break
        time.sleep(0.2)
    s = pd.DataFrame(rows, columns=["date", "close"]).drop_duplicates("date")
    s["date"] = pd.to_datetime(s["date"]); s = s.set_index("date")["close"].sort_index()
    s.reset_index().to_csv(cache, index=False)
    return s


def regimes(btc):
    """Label each day bull / consolidation / bear from BTC price."""
    ma = btc.rolling(100, min_periods=50).mean()
    r90 = btc.pct_change(90)
    reg = pd.Series("consolidation", index=btc.index)
    reg[(r90 > 0.30) & (btc > ma)] = "bull"
    reg[(r90 < -0.15) | ((btc < ma) & (r90 < 0))] = "bear"
    return reg


def spearman_ic(sig, fwd):
    """Spearman rank correlation over aligned, finite pairs."""
    d = pd.concat([sig, fwd], axis=1).dropna()
    if len(d) < 30:
        return np.nan, len(d)
    return d.iloc[:, 0].corr(d.iloc[:, 1], method="spearman"), len(d)


# --------------------------------------------------------------------------- #
print("Loading BTC daily ...", flush=True)
btc = btc_daily()
reg = regimes(btc)
print(f"  BTC {btc.index.min().date()} -> {btc.index.max().date()}  ({len(btc)} days)")
print(f"  regime days: " + ", ".join(f"{k}={v}" for k, v in reg.value_counts().items()))

# ---- global signals, all indexed to daily date -------------------------------
fng = pd.read_csv(os.path.join(OUT, "fear_greed.csv"), parse_dates=["date"]).set_index("date")["fng"]
tvl = pd.read_csv(os.path.join(OUT, "defi_tvl_total.csv"), parse_dates=["date"]).set_index("date")["tvl"]
stab = pd.read_csv(os.path.join(OUT, "stablecoin_supply.csv"), parse_dates=["date"]).set_index("date")["stablecoin_mcap"]
fund = pd.read_csv(os.path.join(OUT, "funding_rates.csv"), parse_dates=["date"])
btc_fund = fund[fund.coin == "BTC"].set_index("date")["funding_rate"]

signals = {
    "FearGreed (level)":       fng.reindex(btc.index).ffill(limit=3),
    "DeFiTVL 30d %chg":        tvl.reindex(btc.index).ffill(limit=3).pct_change(30),
    "Stablecoin 30d %chg":     stab.reindex(btc.index).ffill(limit=3).pct_change(30),
    "BTC funding (level)":     btc_fund.reindex(btc.index).ffill(limit=3),
    "BTC funding 7d avg":      btc_fund.reindex(btc.index).ffill(limit=3).rolling(7).mean(),
}

# forward log returns of BTC at each horizon
fwd = {h: np.log(btc.shift(-h) / btc) for h in HORIZONS}

print("\n" + "=" * 78)
print("GLOBAL SIGNAL -> BTC FORWARD-RETURN IC   (Spearman; conso+bull only)")
print("  positive IC = signal high -> higher future return")
print("=" * 78)
mask_cb = reg.isin(["consolidation", "bull"])
hdr = "  {:<24}".format("signal") + "".join(f"{'IC'+str(h)+'d':>9}" for h in HORIZONS) + f"{'n':>7}"
print(hdr)
diag = {}
for name, sig in signals.items():
    s = sig.where(mask_cb)
    ics = []
    n_last = 0
    for h in HORIZONS:
        ic, n = spearman_ic(s, fwd[h].where(mask_cb))
        ics.append(ic); n_last = n
    diag[name] = ics
    print("  {:<24}".format(name) + "".join(f"{ic:>9.3f}" if not np.isnan(ic) else f"{'-':>9}" for ic in ics) + f"{n_last:>7}")

print("\n" + "-" * 78)
print("SAME SIGNALS, BY REGIME (30d horizon) -- sanity: does the edge flip?")
print("-" * 78)
print("  {:<24}{:>12}{:>16}{:>10}".format("signal", "bull", "consolidation", "bear"))
for name, sig in signals.items():
    line = "  {:<24}".format(name)
    for rg in ["bull", "consolidation", "bear"]:
        m = reg == rg
        ic, n = spearman_ic(sig.where(m), fwd[30].where(m))
        line += f"{ic:>12.3f}" if not np.isnan(ic) else f"{'-':>12}"
        if rg == "consolidation":
            line = line  # keep spacing
    # fix spacing: rebuild cleanly
    vals = []
    for rg in ["bull", "consolidation", "bear"]:
        m = reg == rg
        ic, n = spearman_ic(sig.where(m), fwd[30].where(m))
        vals.append(f"{ic:.3f}" if not np.isnan(ic) else "-")
    print("  {:<24}{:>12}{:>16}{:>10}".format(name, vals[0], vals[1], vals[2]))

# --------------------------------------------------------------------------- #
# Cross-sectional: does per-coin on-chain VALUE pick winners?
# --------------------------------------------------------------------------- #
print("\n" + "=" * 78)
print("CROSS-SECTIONAL: per-coin TVL 30d-growth  ->  coin forward return")
print("  pooled Spearman rank-IC across coins (conso+bull); does value pick coins?")
print("=" * 78)

price = pd.read_csv(os.path.join(RAW, "broad_daily_close_current.csv"),
                    index_col=0, parse_dates=True)
ct = pd.read_csv(os.path.join(OUT, "chain_tvl.csv"), parse_dates=["date"])
tvl_wide = ct.pivot_table(index="date", columns="coin", values="tvl")
# coins present in BOTH price and chain-tvl
coins = [c for c in tvl_wide.columns if (c + "USDT") in price.columns]
print(f"  coins with TVL + price: {len(coins)} -> {coins}")

# align everything on the price calendar
px = price[[c + "USDT" for c in coins]].copy()
px.columns = coins
tv = tvl_wide[coins].reindex(px.index).ffill(limit=5)
reg_px = regimes(btc).reindex(px.index).ffill()

tvl_growth = tv.pct_change(30)                       # signal at t
mom_growth = px.pct_change(30)                        # price momentum (control)
for label, sig_wide in [("TVL 30d growth", tvl_growth), ("Price 30d mom (control)", mom_growth)]:
    print(f"\n  -- signal: {label} --")
    print("  {:>8}{:>12}{:>10}".format("horizon", "rankIC", "n_days"))
    for h in HORIZONS:
        fwd_wide = np.log(px.shift(-h) / px)
        daily_ic = []
        for day in px.index:
            if reg_px.get(day, "bear") not in ("consolidation", "bull"):
                continue
            s = sig_wide.loc[day]
            f = fwd_wide.loc[day]
            pair = pd.concat([s, f], axis=1).dropna()
            if len(pair) >= 5:
                daily_ic.append(pair.iloc[:, 0].corr(pair.iloc[:, 1], method="spearman"))
        if daily_ic:
            print("  {:>8}{:>12.3f}{:>10}".format(f"{h}d", float(np.nanmean(daily_ic)), len(daily_ic)))
        else:
            print("  {:>8}{:>12}{:>10}".format(f"{h}d", "-", 0))

print("\nDone. (IC ~ 0.03-0.05 is a weak but usable edge; ~0 = no edge; sign matters.)")
