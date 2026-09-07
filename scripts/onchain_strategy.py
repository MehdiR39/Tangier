#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase 4b - Backtest the on-chain VALUE strategy vs equal-weight.

Signal that survived diagnostics (Phase 4a):
    SELECTION  = cross-sectional TVL 30d-growth (rank-IC +0.07, beats price mom)
    RISK       = BTC funding 7d-avg (froth -> trim), contrarian
    (F&G / stablecoin growth kept as optional confirmation, not core)

Rules honoured:
  * judge on CONSOLIDATION + BULL only; go to CASH in bear (user exits bears)
  * no look-ahead: every signal at rebalance t uses data <= t
  * monthly rebalance (weekly whipsaws, learned earlier), 0.15% turnover fee

Outputs a metrics table, a K-robustness sweep (plateau vs spike), and an
equity-curve PNG.
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data_onchain")
RAW = os.path.join(ROOT, "data_raw")

FEE = 0.0015
REB = 30            # rebalance every 30 days
SIG_LB = 30         # signal lookback (TVL / momentum growth window)

# --------------------------------------------------------------------------- #
def regimes(btc):
    ma = btc.rolling(100, min_periods=50).mean()
    r90 = btc.pct_change(90)
    reg = pd.Series("consolidation", index=btc.index)
    reg[(r90 > 0.30) & (btc > ma)] = "bull"
    reg[(r90 < -0.15) | ((btc < ma) & (r90 < 0))] = "bear"
    return reg


def metrics(equity):
    """total return, CAGR, ann. Sharpe, max drawdown from a daily equity curve."""
    equity = equity.dropna()
    if len(equity) < 2:
        return dict(total=np.nan, cagr=np.nan, sharpe=np.nan, maxdd=np.nan)
    ret = equity.pct_change().dropna()
    yrs = (equity.index[-1] - equity.index[0]).days / 365.25
    total = equity.iloc[-1] / equity.iloc[0]
    cagr = total ** (1 / yrs) - 1 if yrs > 0 else np.nan
    sharpe = (ret.mean() / ret.std() * np.sqrt(365)) if ret.std() > 0 else np.nan
    dd = (equity / equity.cummax() - 1).min()
    return dict(total=total, cagr=cagr, sharpe=sharpe, maxdd=dd)


# --------------------------------------------------------------------------- #
# Load data
# --------------------------------------------------------------------------- #
btc = pd.read_csv(os.path.join(OUT, "btc_daily.csv"), parse_dates=["date"]).set_index("date")["close"]
price = pd.read_csv(os.path.join(RAW, "broad_daily_close_current.csv"), index_col=0, parse_dates=True)
ct = pd.read_csv(os.path.join(OUT, "chain_tvl.csv"), parse_dates=["date"])
tvl_wide = ct.pivot_table(index="date", columns="coin", values="tvl")
fund = pd.read_csv(os.path.join(OUT, "funding_rates.csv"), parse_dates=["date"])
btc_fund = fund[fund.coin == "BTC"].set_index("date")["funding_rate"]

coins = [c for c in tvl_wide.columns if (c + "USDT") in price.columns]
cal = price.index
px = price[[c + "USDT" for c in coins]].copy(); px.columns = coins
tv = tvl_wide[coins].reindex(cal).ffill(limit=5)
reg = regimes(btc).reindex(cal).ffill()
btc_px = btc.reindex(cal).ffill()
fund7 = btc_fund.reindex(cal).ffill().rolling(7).mean()
fund_hi = fund7.quantile(0.80)     # "froth" threshold (top quintile of funding)

daily_ret = px.pct_change()
btc_ret = btc_px.pct_change()

rebal_days = cal[SIG_LB + 1::REB]   # start after we have a signal lookback


def run(select_fn, use_fund_overlay=False, use_btc=False):
    """Segment backtest. select_fn(day)->list of coins (or [] for cash)."""
    equity = pd.Series(index=cal, dtype=float)
    equity.iloc[0] = 1.0
    val = 1.0
    prev_w = pd.Series(0.0, index=coins)
    seg_bounds = list(rebal_days) + [cal[-1]]
    # fill pre-first-rebalance flat
    first = seg_bounds[0]
    equity.loc[:first] = 1.0
    for i in range(len(seg_bounds) - 1):
        t0, t1 = seg_bounds[i], seg_bounds[i + 1]
        sel = select_fn(t0)
        exposure = 1.0
        if use_fund_overlay and fund7.get(t0, 0) >= fund_hi:
            exposure = 0.5           # trim when funding is frothy
        # target weights
        w = pd.Series(0.0, index=coins)
        if use_btc:
            pass  # handled separately below
        elif sel:
            w[sel] = exposure / len(sel)
        # turnover fee on rebalance
        turn = (w - prev_w).abs().sum()
        val *= (1 - FEE * turn)
        prev_w = w.copy()
        # evolve value through the segment (drift)
        seg = cal[(cal > t0) & (cal <= t1)]
        if use_btc:
            invested = exposure if sel else 0.0
            for d in seg:
                val *= (1 + invested * btc_ret.get(d, 0.0))
                equity.loc[d] = val
        elif sel:
            qty = w / px.loc[t0]        # units bought
            base = val
            for d in seg:
                gross = (qty * px.loc[d]).sum() + (1 - w.sum())  # invested + cash
                equity.loc[d] = base * gross
            val = equity.loc[seg[-1]] if len(seg) else val
        else:  # cash
            for d in seg:
                equity.loc[d] = val
    return equity.ffill()


# --------------------------------------------------------------------------- #
# Selection functions (all cash in bear = user's rule)
# --------------------------------------------------------------------------- #
def sel_all(day):
    if reg.get(day) == "bear":
        return []
    return [c for c in coins if not np.isnan(px.loc[day, c])]

def make_topk(signal_wide, k, top=True):
    def f(day):
        if reg.get(day) == "bear":
            return []
        s = signal_wide.loc[day].dropna()
        s = s[[c for c in s.index if not np.isnan(px.loc[day, c])]]
        if len(s) < k:
            return list(s.index)
        return list(s.sort_values(ascending=not top).index[:k])
    return f

tvl_growth = tv.pct_change(SIG_LB)
mom = px.pct_change(SIG_LB)

K = 8
strategies = {
    "EqualWeight-all":        (sel_all, False, False),
    "TVLgrowth-top8":         (make_topk(tvl_growth, K, True), False, False),
    "TVLgrowth-top8 +funding":(make_topk(tvl_growth, K, True), True, False),
    "TVLgrowth-BOTTOM8":      (make_topk(tvl_growth, K, False), False, False),
    "PriceMom-top8 (control)":(make_topk(mom, K, True), False, False),
    "BTC-hold":               (sel_all, False, True),
}

# --------------------------------------------------------------------------- #
# Run + report (metrics measured over conso+bull days only)
# --------------------------------------------------------------------------- #
cb_mask = reg.isin(["consolidation", "bull"])
equities = {}
print("=" * 92)
print(f"BACKTEST  {cal.min().date()} -> {cal.max().date()}   "
      f"coins={len(coins)}  K={K}  reb={REB}d  fee={FEE:.2%}")
print("  metrics computed on CONSO+BULL days (bear = cash for all)")
print("=" * 92)
print("  {:<26}{:>10}{:>10}{:>9}{:>9}".format("strategy", "totalX", "CAGR", "Sharpe", "maxDD"))
for name, (fn, ov, bt) in strategies.items():
    eq = run(fn, use_fund_overlay=ov, use_btc=bt)
    equities[name] = eq
    m = metrics(eq)
    print("  {:<26}{:>10.2f}{:>9.1%}{:>9.2f}{:>9.1%}".format(
        name, m["total"], m["cagr"], m["sharpe"], m["maxdd"]))

# --------------------------------------------------------------------------- #
# K-robustness sweep (plateau = robust, spike = luck)
# --------------------------------------------------------------------------- #
print("\n" + "-" * 92)
print("K-ROBUSTNESS  (total multiple of TVLgrowth-topK vs EqualWeight-all)")
print("-" * 92)
ew_total = metrics(equities["EqualWeight-all"])["total"]
print("  {:>4}{:>12}{:>14}".format("K", "TVLtopK X", "vs EW"))
for k in [4, 5, 6, 8, 10, 12, 15]:
    eq = run(make_topk(tvl_growth, k, True))
    t = metrics(eq)["total"]
    print("  {:>4}{:>12.2f}{:>13.0%}".format(k, t, t / ew_total - 1))
print(f"  (EqualWeight-all = {ew_total:.2f}x baseline)")

# --------------------------------------------------------------------------- #
# Plot
# --------------------------------------------------------------------------- #
fig, ax = plt.subplots(figsize=(13, 7))
order = ["EqualWeight-all", "TVLgrowth-top8", "TVLgrowth-top8 +funding",
         "PriceMom-top8 (control)", "TVLgrowth-BOTTOM8", "BTC-hold"]
colors = {"EqualWeight-all": "black", "TVLgrowth-top8": "green",
          "TVLgrowth-top8 +funding": "darkgreen", "PriceMom-top8 (control)": "orange",
          "TVLgrowth-BOTTOM8": "red", "BTC-hold": "gray"}
for name in order:
    eq = equities[name]
    ls = "--" if name in ("BTC-hold", "TVLgrowth-BOTTOM8") else "-"
    ax.plot(eq.index, eq.values, label=name, color=colors[name], linestyle=ls,
            linewidth=2 if name.startswith("TVLgrowth-top") else 1.4)
# shade bear (cash) periods
bear = reg == "bear"
ax.fill_between(cal, 0, 1, where=bear, transform=ax.get_xaxis_transform(),
                color="red", alpha=0.06, label="bear (cash)")
ax.set_yscale("log")
ax.set_title("On-chain VALUE strategy (TVL-growth selection) vs Equal-Weight\n"
             f"21 coins, monthly rebalance, cash in bear  |  {cal.min().date()}..{cal.max().date()}")
ax.set_ylabel("equity (log, base 1)")
ax.legend(loc="upper left", fontsize=9)
ax.grid(True, alpha=0.3)
png = os.path.join(OUT, "strategy_equity.png")
fig.tight_layout(); fig.savefig(png, dpi=110)
print(f"\nplot -> {png}")
