#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Current picks - what the alt-only VALUE model ranks highest RIGHT NOW.

SELECTION : cross-sectional TVL 30d-growth (validated rank-IC +0.07)
RISK flags: mcap/FDV (unlock overhang), revenue trend where available
TIMING    : current BTC regime + Fear&Greed + BTC funding (the "when")

Not advice - a ranking from on-chain activity. The regime block says whether
the model would even be deployed today (it goes to cash in bear).
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data_onchain")
RAW = os.path.join(ROOT, "data_raw")


def regimes(btc):
    ma = btc.rolling(100, min_periods=50).mean()
    r90 = btc.pct_change(90)
    reg = pd.Series("consolidation", index=btc.index)
    reg[(r90 > 0.30) & (btc > ma)] = "bull"
    reg[(r90 < -0.15) | ((btc < ma) & (r90 < 0))] = "bear"
    return reg


# ---- load -------------------------------------------------------------------
btc = pd.read_csv(os.path.join(OUT, "btc_daily.csv"), parse_dates=["date"]).set_index("date")["close"]
price = pd.read_csv(os.path.join(RAW, "broad_daily_close_current.csv"), index_col=0, parse_dates=True)
ct = pd.read_csv(os.path.join(OUT, "chain_tvl.csv"), parse_dates=["date"])
tvl = ct.pivot_table(index="date", columns="coin", values="tvl")
gk = pd.read_csv(os.path.join(OUT, "coingecko_snapshot.csv")).set_index("coin")
fng = pd.read_csv(os.path.join(OUT, "fear_greed.csv"), parse_dates=["date"]).set_index("date")["fng"]
fund = pd.read_csv(os.path.join(OUT, "funding_rates.csv"), parse_dates=["date"])
rev = pd.read_csv(os.path.join(OUT, "protocol_revenue.csv"), parse_dates=["date"])

coins = [c for c in tvl.columns if (c + "USDT") in price.columns]
tvl = tvl[coins].ffill(limit=5)

# ---- timing / regime block --------------------------------------------------
reg = regimes(btc)
cur_reg = reg.iloc[-1]
fng_now = int(fng.iloc[-1])
btc_fund7 = fund[fund.coin == "BTC"].set_index("date")["funding_rate"].rolling(7).mean().iloc[-1]

print("=" * 70)
print("TIMING  ('quand')  as of", btc.index[-1].date())
print("=" * 70)
print(f"  BTC regime        : {cur_reg.upper()}")
print(f"  Fear & Greed      : {fng_now}  "
      f"({'FEAR - prudence/accumulation' if fng_now < 45 else 'GREED - tendance' if fng_now > 55 else 'neutre'})")
print(f"  BTC funding (7d)  : {btc_fund7:+.4%}  "
      f"({'frothy - risque' if btc_fund7 > 0.0003 else 'calme/sain'})")
deploy = cur_reg in ("consolidation", "bull")
print(f"  -> modele deploye ?  {'OUI (conso/bull)' if deploy else 'NON - CASH (bear)'}")

# ---- selection: current TVL growth ranking ----------------------------------
tvl_g30 = tvl.iloc[-1] / tvl.shift(30).iloc[-1] - 1
tvl_g90 = tvl.iloc[-1] / tvl.shift(90).iloc[-1] - 1

rows = []
for c in coins:
    g30 = tvl_g30.get(c, np.nan)
    g90 = tvl_g90.get(c, np.nan)
    m2f = gk["mcap_to_fdv"].get(c, np.nan) if c in gk.index else np.nan
    athc = gk["ath_change_pct"].get(c, np.nan) if c in gk.index else np.nan
    # revenue 30d growth if we have it
    rg = np.nan
    if c in set(rev.coin):
        rc = rev[rev.coin == c].set_index("date")["revenue"].dropna()
        if len(rc) > 35:
            a, b = rc.iloc[-30:].mean(), rc.iloc[-60:-30].mean()
            rg = (a / b - 1) if b else np.nan
    rows.append([c, g30, g90, m2f, athc, rg])

df = pd.DataFrame(rows, columns=["coin", "tvl_g30", "tvl_g90",
                                 "mcap/fdv", "ath_chg%", "rev_g30"])
# "sustained" score: mean of 30d & 90d growth (kills dead-cat bounces)
df["score"] = df[["tvl_g30", "tvl_g90"]].mean(axis=1, skipna=False)
df = df.sort_values("score", ascending=False, na_position="last").reset_index(drop=True)

print("\n" + "=" * 74)
print("SELECTION  ('quoi')  - ranked by SUSTAINED TVL growth (mean of 30d & 90d)")
print("  mcap/fdv low = big unlocks ahead (dilution);  ath% = distance below peak")
print("=" * 74)
print("  {:>2} {:<6}{:>9}{:>9}{:>9}{:>10}{:>9}".format(
    "#", "coin", "score", "TVL30d", "TVL90d", "mcap/fdv", "ath%"))
for i, r in df.iterrows():
    def pf(x):
        return "-" if pd.isna(x) else f"{x:+.0%}"
    m2f = "-" if pd.isna(r["mcap/fdv"]) else f"{r['mcap/fdv']:.2f}"
    athv = "-" if pd.isna(r["ath_chg%"]) else f"{r['ath_chg%']:+.0f}%"
    star = " *" if i < 6 else ""
    print("  {:>2} {:<6}{:>9}{:>9}{:>9}{:>10}{:>9}{}".format(
        i + 1, r["coin"], pf(r["score"]), pf(r["tvl_g30"]), pf(r["tvl_g90"]),
        m2f, athv, star))

top6 = df.head(6)["coin"].tolist()
print("\n" + "=" * 70)
print(f"MODEL TOP-6 TODAY : {top6}")
if not deploy:
    print("  NOTE: regime = bear -> the model would hold CASH, not deploy.")
else:
    print(f"  regime {cur_reg} -> deploy equally across these 6 (~16.7% each).")
# unlock warnings among the picks
risky = df.head(6)[df.head(6)["mcap/fdv"] < 0.5]
if len(risky):
    print("  ⚠ unlock overhang (mcap/fdv<0.5): "
          + ", ".join(f"{r['coin']}({r['mcap/fdv']:.2f})" for _, r in risky.iterrows()))
