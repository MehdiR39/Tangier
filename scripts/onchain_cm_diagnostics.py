#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Do the Coin Metrics signals predict returns? (IC diagnostics, conso+bull.)

Selection signals (cross-sectional rank-IC of signal(t) vs coin fwd return):
    AdrActCnt 30d/90d growth   adoption momentum  (expect + )
    TxCnt      30d growth       usage momentum     (expect + )
Value/timing signals:
    MVRV level (cross-sectional, expect - : cheap outperforms) -- value-trap risk
    MVRV z-score vs own 1y history (cheap-vs-self, expect - ) -- cleaner value
    MVRV within-coin time-series corr with fwd return (buy low MVRV) -- timing

Baselines for reference (measured earlier, different coin set):
    TVL 30d growth rank-IC ~ +0.07 ;  price momentum ~ 0
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data_onchain")
RAW = os.path.join(ROOT, "data_raw")
HOR = [7, 14, 30, 60, 90]


def regimes(btc):
    ma = btc.rolling(100, min_periods=50).mean()
    r90 = btc.pct_change(90)
    reg = pd.Series("consolidation", index=btc.index)
    reg[(r90 > 0.30) & (btc > ma)] = "bull"
    reg[(r90 < -0.15) | ((btc < ma) & (r90 < 0))] = "bear"
    return reg


def xs_ic(sig_wide, fwd_wide, mask, sign=1):
    """mean daily cross-sectional Spearman rank-IC over masked days."""
    ics = []
    idx = sig_wide.index[mask.reindex(sig_wide.index).fillna(False).values]
    for day in idx:
        s = sign * sig_wide.loc[day]
        f = fwd_wide.loc[day]
        p = pd.concat([s, f], axis=1).dropna()
        if len(p) >= 5:
            ics.append(p.iloc[:, 0].corr(p.iloc[:, 1], method="spearman"))
    return (np.nanmean(ics) if ics else np.nan), len(ics)


# --- load --------------------------------------------------------------------
btc = pd.read_csv(os.path.join(OUT, "btc_daily.csv"), parse_dates=["date"]).set_index("date")["close"]
price = pd.read_csv(os.path.join(RAW, "broad_daily_close_current.csv"), index_col=0, parse_dates=True)
cm = pd.read_csv(os.path.join(OUT, "coinmetrics.csv"), parse_dates=["date"])

def wide(metric):
    return cm[cm.metric == metric].pivot_table(index="date", columns="coin", values="value")

adr = wide("AdrActCnt"); txc = wide("TxCnt"); mvrv = wide("CapMVRVCur")

coins = [c for c in adr.columns if (c + "USDT") in price.columns]
cal = price.index
px = price[[c + "USDT" for c in coins]].copy(); px.columns = coins
reg = regimes(btc).reindex(cal).ffill()
cb = reg.isin(["consolidation", "bull"])

adr = adr[coins].reindex(cal).ffill(limit=5)
txc = txc[[c for c in coins if c in txc.columns]].reindex(cal).ffill(limit=5)
mv = mvrv[[c for c in coins if c in mvrv.columns]].reindex(cal).ffill(limit=5)

fwd = {h: np.log(px.shift(-h) / px) for h in HOR}

print("=" * 82)
print(f"Coin Metrics signal diagnostics   coins={len(coins)}  {cal.min().date()}..{cal.max().date()}")
print("  cross-sectional rank-IC vs forward return, CONSO+BULL only")
print("=" * 82)

signals = {
    "AdrAct 30d growth (+)":  (adr.pct_change(30), 1),
    "AdrAct 90d growth (+)":  (adr.pct_change(90), 1),
    "TxCnt  30d growth (+)":  (txc.pct_change(30), 1),
    "MVRV level  (cheap +)":  (mv, -1),                       # sign -1: low MVRV
    "MVRV z-1y   (cheap +)":  ((mv - mv.rolling(365, min_periods=90).mean())
                              / mv.rolling(365, min_periods=90).std(), -1),
}
hdr = "  {:<24}".format("signal") + "".join(f"{'IC'+str(h)+'d':>9}" for h in HOR) + f"{'n':>7}"
print(hdr)
for name, (sig, sgn) in signals.items():
    line = "  {:<24}".format(name)
    n_last = 0
    for h in HOR:
        ic, n = xs_ic(sig, fwd[h], cb, sign=sgn); n_last = n
        line += f"{ic:>9.3f}" if not np.isnan(ic) else f"{'-':>9}"
    print(line + f"{n_last:>7}")

# --- MVRV within-coin timing (pooled) ---------------------------------------
print("\n" + "-" * 82)
print("MVRV as WITHIN-COIN timing (pooled corr of MVRV level vs fwd return)")
print("  negative = high MVRV -> lower future return (sell rich / buy cheap)")
print("-" * 82)
print("  {:<10}".format("horizon") + "".join(f"{str(h)+'d':>10}" for h in HOR))
line = "  {:<10}".format("corr")
for h in HOR:
    cs = []
    for c in mv.columns:
        d = pd.concat([mv[c].where(cb), fwd[h][c].where(cb)], axis=1).dropna()
        if len(d) > 60:
            cs.append(d.iloc[:, 0].corr(d.iloc[:, 1], method="spearman"))
    line += f"{np.nanmean(cs):>10.3f}" if cs else f"{'-':>10}"
print(line)

# --- MVRV level by regime (30d) ---------------------------------------------
print("\n  MVRV within-coin corr by regime (30d):")
for rg in ["bull", "consolidation", "bear"]:
    m = reg == rg
    cs = []
    for c in mv.columns:
        d = pd.concat([mv[c].where(m), fwd[30][c].where(m)], axis=1).dropna()
        if len(d) > 40:
            cs.append(d.iloc[:, 0].corr(d.iloc[:, 1], method="spearman"))
    v = f"{np.nanmean(cs):+.3f}" if cs else "-"
    print(f"    {rg:<15} {v}   (coins={len(cs)})")

print("\n(rank-IC: ~0.03-0.05 weak-usable, ~0 none, sign must match the thesis)")
