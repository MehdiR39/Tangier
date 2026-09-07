#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Verify data_onchain/ CSVs: spans, freshness, and a per-coin coverage matrix."""
import os
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data_onchain")

UNIVERSE = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK",
            "DOT", "LTC", "TRX", "ATOM", "UNI", "ETC", "XLM", "NEAR", "ALGO",
            "FIL", "VET", "ICP", "HBAR", "AAVE", "THETA", "AXS", "SAND", "MANA",
            "GRT", "CHZ", "ENJ", "ZEC", "EGLD", "XTZ", "IOTA", "KAVA", "ZIL", "QTUM"]


def span(df, col="date"):
    d = pd.to_datetime(df[col])
    return d.min().date(), d.max().date(), len(df)


print("=" * 72)
print("GLOBAL / TIME-SERIES FILES")
print("=" * 72)
for f in ["fear_greed.csv", "defi_tvl_total.csv", "stablecoin_supply.csv"]:
    p = os.path.join(OUT, f)
    if os.path.exists(p):
        df = pd.read_csv(p)
        lo, hi, n = span(df)
        print(f"  {f:<26} {n:>6} rows   {lo} -> {hi}")

print()
print("=" * 72)
print("PER-COIN SOURCES  (span per coin)")
print("=" * 72)

cov = {c: {"chain_tvl": "", "revenue": "", "funding": "", "gecko": ""}
       for c in UNIVERSE}

# chain tvl
ct = pd.read_csv(os.path.join(OUT, "chain_tvl.csv"))
for coin, g in ct.groupby("coin"):
    lo, hi, n = span(g)
    cov[coin]["chain_tvl"] = f"{lo}->{hi} ({n})"

# revenue
rv = pd.read_csv(os.path.join(OUT, "protocol_revenue.csv"))
for coin, g in rv.groupby("coin"):
    lo, hi, n = span(g)
    cov[coin]["revenue"] = f"{lo}->{hi} ({n})"

# funding
fd = pd.read_csv(os.path.join(OUT, "funding_rates.csv"))
fund_spans = []
for coin, g in fd.groupby("coin"):
    lo, hi, n = span(g)
    cov[coin]["funding"] = f"{lo}->{hi} ({n})"
    fund_spans.append((coin, lo, hi, n))

# gecko
gk = pd.read_csv(os.path.join(OUT, "coingecko_snapshot.csv"))
for coin in gk["coin"]:
    if coin in cov:
        cov[coin]["gecko"] = "yes"

print(f"  {'coin':<6}{'chain_tvl':<26}{'revenue':<26}{'funding':<22}{'gecko'}")
for c in UNIVERSE:
    r = cov[c]
    ct_s = r['chain_tvl'] or '-'
    rv_s = r['revenue'] or '-'
    fd_s = r['funding'] or '-'
    print(f"  {c:<6}{ct_s:<26}{rv_s:<26}{fd_s:<22}{r['gecko'] or '-'}")

print()
print("=" * 72)
print("FUNDING SPAN SUMMARY (is it deep enough to backtest?)")
print("=" * 72)
ns = [n for _, _, _, n in fund_spans]
print(f"  coins={len(fund_spans)}  min_days={min(ns)}  "
      f"max_days={max(ns)}  median_days={int(pd.Series(ns).median())}")
# show the 3 shortest and BTC/ETH
fund_spans.sort(key=lambda x: x[3])
print("  shortest:", [(c, n) for c, _, _, n in fund_spans[:4]])
for c, lo, hi, n in fund_spans:
    if c in ("BTC", "ETH"):
        print(f"  {c}: {lo} -> {hi}  ({n} days)")

print()
print("=" * 72)
print("COVERAGE COUNTS")
print("=" * 72)
have_tvl = sum(1 for c in UNIVERSE if cov[c]["chain_tvl"])
have_rev = sum(1 for c in UNIVERSE if cov[c]["revenue"])
have_fund = sum(1 for c in UNIVERSE if cov[c]["funding"])
print(f"  chain_tvl: {have_tvl}/37   revenue: {have_rev}/37   "
      f"funding: {have_fund}/37   gecko: {len(gk)}/37")
no_fund_value = [c for c in UNIVERSE
                 if not cov[c]["chain_tvl"] and not cov[c]["revenue"]]
print(f"  coins with NO on-chain value signal (tvl+rev both empty): {no_fund_value}")
