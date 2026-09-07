#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Backtest the Coin Metrics signals that survived diagnostics.

Primary (clean) signal : active-address 90d growth (rank-IC +0.08, on par w/ TVL)
Honest test            : MVRV-timing overlay (IC looks huge but ~1 cycle, suspect)

19 CM coins, monthly rebalance, cash in bear, 0.15% turnover fee, conso+bull judged.
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data_onchain"); RAW = os.path.join(ROOT, "data_raw")
FEE, REB, LB = 0.0015, 30, 90


def regimes(btc):
    ma = btc.rolling(100, min_periods=50).mean(); r90 = btc.pct_change(90)
    reg = pd.Series("consolidation", index=btc.index)
    reg[(r90 > 0.30) & (btc > ma)] = "bull"
    reg[(r90 < -0.15) | ((btc < ma) & (r90 < 0))] = "bear"
    return reg


def metrics(eq):
    eq = eq.dropna(); ret = eq.pct_change().dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    total = eq.iloc[-1] / eq.iloc[0]
    return dict(total=total, cagr=total ** (1 / yrs) - 1 if yrs > 0 else np.nan,
                sharpe=ret.mean() / ret.std() * np.sqrt(365) if ret.std() > 0 else np.nan,
                maxdd=(eq / eq.cummax() - 1).min())


btc = pd.read_csv(os.path.join(OUT, "btc_daily.csv"), parse_dates=["date"]).set_index("date")["close"]
price = pd.read_csv(os.path.join(RAW, "broad_daily_close_current.csv"), index_col=0, parse_dates=True)
cm = pd.read_csv(os.path.join(OUT, "coinmetrics.csv"), parse_dates=["date"])
def wide(m): return cm[cm.metric == m].pivot_table(index="date", columns="coin", values="value")
adr, mvrv = wide("AdrActCnt"), wide("CapMVRVCur")

coins = [c for c in adr.columns if (c + "USDT") in price.columns]
cal = price.index
px = price[[c + "USDT" for c in coins]].copy(); px.columns = coins
reg = regimes(btc).reindex(cal).ffill()
adrg = adr[coins].reindex(cal).ffill(limit=5).pct_change(LB)
mom = px.pct_change(LB)
mvw = mvrv[[c for c in coins if c in mvrv.columns]].reindex(cal).ffill(limit=5)
mvmed = mvw.median(axis=1)                       # basket median MVRV
mv_hi = mvmed.rolling(365, min_periods=90).median()   # its own trailing median
btc_ret = btc.reindex(cal).ffill().pct_change()
rebal = cal[LB + 1::REB]


def run(select, overlay=False, use_btc=False):
    eq = pd.Series(index=cal, dtype=float); val = 1.0
    prev = pd.Series(0.0, index=coins); bnds = list(rebal) + [cal[-1]]
    eq.loc[:bnds[0]] = 1.0
    for i in range(len(bnds) - 1):
        t0, t1 = bnds[i], bnds[i + 1]; sel = select(t0)
        exp = 1.0
        if overlay and not np.isnan(mvmed.get(t0, np.nan)) and mvmed.get(t0) > mv_hi.get(t0, np.inf):
            exp = 0.5                                  # rich -> de-risk
        w = pd.Series(0.0, index=coins)
        if not use_btc and sel:
            w[sel] = exp / len(sel)
        val *= (1 - FEE * (w - prev).abs().sum()); prev = w.copy()
        seg = cal[(cal > t0) & (cal <= t1)]
        if use_btc:
            inv = exp if sel else 0.0
            for d in seg:
                val *= (1 + inv * btc_ret.get(d, 0.0)); eq.loc[d] = val
        elif sel:
            qty = w / px.loc[t0]; base = val
            for d in seg:
                eq.loc[d] = base * ((qty * px.loc[d]).sum() + (1 - w.sum()))
            val = eq.loc[seg[-1]] if len(seg) else val
        else:
            for d in seg:
                eq.loc[d] = val
    return eq.ffill()


def topk(sig, k, top=True):
    def f(day):
        if reg.get(day) == "bear":
            return []
        s = sig.loc[day].dropna(); s = s[[c for c in s.index if not np.isnan(px.loc[day, c])]]
        if len(s) < k:
            return list(s.index)
        return list(s.sort_values(ascending=not top).index[:k])
    return f

def sel_all(day):
    return [] if reg.get(day) == "bear" else [c for c in coins if not np.isnan(px.loc[day, c])]


K = 6
strat = {
    "EqualWeight-all":            (sel_all, False, False),
    "Adoption-top6":              (topk(adrg, K, True), False, False),
    "Adoption-top6 +MVRVtiming":  (topk(adrg, K, True), True, False),
    "Adoption-BOTTOM6":           (topk(adrg, K, False), False, False),
    "PriceMom-top6 (control)":    (topk(mom, K, True), False, False),
    "BTC-hold":                   (sel_all, False, True),
}
eqs = {}
print("=" * 90)
print(f"CM BACKTEST  {cal.min().date()}..{cal.max().date()}  coins={len(coins)}  K={K}  reb={REB}d  signal=AdrAct{LB}d")
print("=" * 90)
print("  {:<28}{:>9}{:>9}{:>8}{:>8}".format("strategy", "totalX", "CAGR", "Sharpe", "maxDD"))
for name, (fn, ov, bt) in strat.items():
    e = run(fn, overlay=ov, use_btc=bt); eqs[name] = e; m = metrics(e)
    print("  {:<28}{:>9.2f}{:>8.1%}{:>8.2f}{:>8.1%}".format(name, m["total"], m["cagr"], m["sharpe"], m["maxdd"]))

print("\n  K-robustness (Adoption-topK total multiple):")
for k in [4, 5, 6, 8, 10]:
    print("    K={:<3} {:.2f}x".format(k, metrics(run(topk(adrg, k, True)))["total"]))

fig, ax = plt.subplots(figsize=(13, 7))
col = {"EqualWeight-all": "black", "Adoption-top6": "green",
       "Adoption-top6 +MVRVtiming": "darkgreen", "Adoption-BOTTOM6": "red",
       "PriceMom-top6 (control)": "orange", "BTC-hold": "gray"}
for name in strat:
    ls = "--" if name in ("BTC-hold", "Adoption-BOTTOM6") else "-"
    ax.plot(eqs[name].index, eqs[name].values, label=name, color=col[name],
            linestyle=ls, linewidth=2 if name.startswith("Adoption-top") else 1.4)
ax.fill_between(cal, 0, 1, where=(reg == "bear"), transform=ax.get_xaxis_transform(),
                color="red", alpha=0.06)
ax.set_yscale("log"); ax.grid(True, alpha=0.3); ax.legend(loc="upper left", fontsize=9)
ax.set_title(f"Coin Metrics ADOPTION selection (active-address {LB}d growth) vs Equal-Weight\n"
             f"{len(coins)} coins, monthly, cash in bear  |  {cal.min().date()}..{cal.max().date()}")
ax.set_ylabel("equity (log)")
png = os.path.join(OUT, "cm_strategy_equity.png"); fig.tight_layout(); fig.savefig(png, dpi=110)
print(f"\nplot -> {png}")
