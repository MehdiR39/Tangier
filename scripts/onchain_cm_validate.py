#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
OUT-OF-SAMPLE validation of the adoption-selection signal on the 2020-2021 bull.

The 2.62x result was on 2022-2026. If active-address-growth selection is REAL,
it must also work on the *earlier, independent* 2020-2021 bull (broad_2020_2026.csv),
which the signal was never tuned on. This is the test that killed momentum before.
"""
import os
import sys
import numpy as np
import pandas as pd

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
    eq = eq.dropna()
    if len(eq) < 5:
        return dict(total=np.nan, cagr=np.nan, sharpe=np.nan, maxdd=np.nan)
    ret = eq.pct_change().dropna(); yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    total = eq.iloc[-1] / eq.iloc[0]
    return dict(total=total, cagr=total ** (1 / yrs) - 1 if yrs > 0 else np.nan,
                sharpe=ret.mean() / ret.std() * np.sqrt(365) if ret.std() > 0 else np.nan,
                maxdd=(eq / eq.cummax() - 1).min())


def backtest(price_csv, start, end, label):
    btc = pd.read_csv(os.path.join(OUT, "btc_daily.csv"), parse_dates=["date"]).set_index("date")["close"]
    price = pd.read_csv(os.path.join(RAW, price_csv), index_col=0, parse_dates=True)
    price = price.loc[(price.index >= start) & (price.index <= end)]
    cm = pd.read_csv(os.path.join(OUT, "coinmetrics.csv"), parse_dates=["date"])
    adr = cm[cm.metric == "AdrActCnt"].pivot_table(index="date", columns="coin", values="value")

    coins = [c for c in adr.columns if (c + "USDT") in price.columns]
    cal = price.index
    px = price[[c + "USDT" for c in coins]].copy(); px.columns = coins
    reg = regimes(btc).reindex(cal).ffill()
    adrg = adr[coins].reindex(cal).ffill(limit=7).pct_change(LB)
    mom = px.pct_change(LB)
    btc_ret = btc.reindex(cal).ffill().pct_change()
    rebal = cal[LB + 1::REB] if len(cal) > LB + 1 else cal[:0]

    def run(select, use_btc=False):
        eq = pd.Series(index=cal, dtype=float); val = 1.0
        prev = pd.Series(0.0, index=coins); bnds = list(rebal) + [cal[-1]]
        if not len(rebal):
            return eq.fillna(1.0)
        eq.loc[:bnds[0]] = 1.0
        for i in range(len(bnds) - 1):
            t0, t1 = bnds[i], bnds[i + 1]; sel = select(t0)
            w = pd.Series(0.0, index=coins)
            if not use_btc and sel:
                w[sel] = 1.0 / len(sel)
            val *= (1 - FEE * (w - prev).abs().sum()); prev = w.copy()
            seg = cal[(cal > t0) & (cal <= t1)]
            if use_btc:
                inv = 1.0 if sel else 0.0
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
            return list(s.index) if len(s) < k else list(s.sort_values(ascending=not top).index[:k])
        return f

    def sel_all(day):
        return [] if reg.get(day) == "bear" else [c for c in coins if not np.isnan(px.loc[day, c])]

    print(f"\n{'='*78}\n{label}   {cal.min().date()}..{cal.max().date()}   "
          f"coins={len(coins)}  (adoption data available)\n{'='*78}")
    reg_days = reg.reindex(cal).value_counts().to_dict()
    print(f"  regime mix: " + ", ".join(f"{k}={v}" for k, v in reg_days.items()))
    print("  {:<26}{:>9}{:>9}{:>8}{:>8}".format("strategy", "totalX", "CAGR", "Sharpe", "maxDD"))
    res = {}
    for name, (fn, bt) in {
        "EqualWeight-all":   (sel_all, False),
        "Adoption-top6":     (topk(adrg, 6, True), False),
        "Adoption-top4":     (topk(adrg, 4, True), False),
        "Adoption-BOTTOM6":  (topk(adrg, 6, False), False),
        "PriceMom-top6":     (topk(mom, 6, True), False),
        "BTC-hold":          (sel_all, True),
    }.items():
        m = metrics(run(fn, use_btc=bt)); res[name] = m
        print("  {:<26}{:>9.2f}{:>8.1%}{:>8.2f}{:>8.1%}".format(
            name, m["total"], m["cagr"], m["sharpe"], m["maxdd"]))
    return res


# 2020-2021 bull  (OUT-OF-SAMPLE: independent of the 2022-2026 result)
r1 = backtest("broad_2020_2026.csv", "2020-10-01", "2022-01-31", "OUT-OF-SAMPLE  2020-2021 bull")
# 2022-2026 (in-sample reference, same as main run)
r2 = backtest("broad_daily_close_current.csv", "2022-01-01", "2026-07-31", "IN-SAMPLE  2022-2026 (reference)")

print("\n" + "#" * 78)
print("VERDICT: does adoption-top6 beat EqualWeight AND BTC in BOTH periods?")
print("#" * 78)
for tag, r in [("2020-2021", r1), ("2022-2026", r2)]:
    a = r["Adoption-top6"]["total"]; ew = r["EqualWeight-all"]["total"]; bt = r["BTC-hold"]["total"]
    print(f"  {tag}:  adoption={a:.2f}x   EW={ew:.2f}x   BTC={bt:.2f}x   "
          f"-> beats EW: {'YES' if a>ew else 'NO'} | beats BTC: {'YES' if a>bt else 'NO'}")
