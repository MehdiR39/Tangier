#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PER-COIN timing:  do on-chain indicators say "enter / exit THIS coin" ?

Not portfolio selection - single-asset market timing. For each coin we build an
in/out (invested vs cash) rule from its own on-chain data and compare to simply
holding that coin (buy & hold). No look-ahead: signal at t-1 sets position for t;
0.15% fee per switch; thresholds are TRAILING (rolling), never full-sample.

Rules tested per coin:
  MVRV-timer     : IN when MVRV < its trailing 1y median (cheap vs own history),
                   OUT when rich   -> contrarian (diagnostics: high MVRV -> low fwd)
  Adoption-timer : IN when active-address 30d growth > 0 (network still growing),
                   OUT when shrinking -> trend filter
  Combo          : IN when adoption rising AND not-euphoric (MVRV < 1.3x trail med)

Reported: per-coin table + aggregate (does timing beat B&H on return? on drawdown?).
"""
import os
import ssl
import json
import time
import datetime as dt
import urllib.request
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data_onchain")
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = {"User-Agent": "Mozilla/5.0 (tangier)"}
FEE = 0.0015


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                        timeout=40, context=CTX) as r:
                return json.load(r)
        except Exception:  # noqa
            time.sleep(1.2 * (2 ** i))
    return None


def binance_daily(sym):
    rows, start = [], 1500000000000
    base = f"https://data-api.binance.vision/api/v3/klines?symbol={sym}&interval=1d&limit=1000"
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
        time.sleep(0.15)
    if not rows:
        return None
    s = pd.DataFrame(rows, columns=["date", sym]).drop_duplicates("date")
    s["date"] = pd.to_datetime(s["date"])
    return s.set_index("date")[sym]


# --- load CM signals ---------------------------------------------------------
cm = pd.read_csv(os.path.join(OUT, "coinmetrics.csv"), parse_dates=["date"])
def wide(m): return cm[cm.metric == m].pivot_table(index="date", columns="coin", values="value")
adr, mvrv = wide("AdrActCnt"), wide("CapMVRVCur")
coins = sorted([c for c in mvrv.columns if mvrv[c].notna().sum() > 400])

# --- prices (cache full daily history per coin) ------------------------------
cache = os.path.join(OUT, "prices_daily_cm.csv")
if os.path.exists(cache):
    px = pd.read_csv(cache, parse_dates=["date"]).set_index("date")
else:
    series = {}
    for c in coins:
        s = binance_daily(c + "USDT")
        if s is not None and len(s) > 400:
            series[c] = s
            print(f"  price {c}: {len(s)} days", flush=True)
    px = pd.DataFrame(series)
    px.index.name = "date"
    px.reset_index().to_csv(cache, index=False)
coins = [c for c in coins if c in px.columns]

cal = px.index
adrN = adr[coins].reindex(cal).ffill(limit=7)
mvN = mvrv[coins].reindex(cal).ffill(limit=7)


def equity_from_pos(ret, pos):
    """pos in {0,1} (already lagged); apply fee on switches; return equity."""
    switch = pos.diff().abs().fillna(0)
    r = pos * ret - switch * FEE
    return (1 + r.fillna(0)).cumprod()


def maxdd(eq):
    return (eq / eq.cummax() - 1).min()


def sharpe(eq):
    r = eq.pct_change().dropna()
    return r.mean() / r.std() * np.sqrt(365) if r.std() > 0 else np.nan


rules = ["MVRV-timer", "Adoption-timer", "Combo"]
agg = {r: {"beat_ret": 0, "cut_dd": 0, "beat_sharpe": 0, "ret_ratio": [],
           "dd_bh": [], "dd_rule": [], "n": 0} for r in rules}
per_coin = []

for c in coins:
    ret = px[c].pct_change()
    mv = mvN[c]
    med = mv.rolling(365, min_periods=120).median()
    g30 = adrN[c].pct_change(30)

    sig = {
        "MVRV-timer":     (mv < med),
        "Adoption-timer": (g30 > 0),
        "Combo":          ((g30 > 0) & (mv < 1.3 * med)),
    }
    valid = mv.notna() & med.notna() & g30.notna()
    if valid.sum() < 300:
        continue
    # fair comparison: B&H and every rule start on the SAME first valid day
    first = valid.idxmax()
    ret_w = ret.loc[first:]
    bh = (1 + ret_w.fillna(0)).cumprod()
    row = {"coin": c, "days": int(valid.sum()), "BH": bh.iloc[-1], "BH_dd": maxdd(bh)}
    for r in rules:
        pos = sig[r].astype(float).shift(1).fillna(0).loc[first:]
        eq = equity_from_pos(ret_w, pos)
        row[r] = eq.iloc[-1]
        row[r + "_dd"] = maxdd(eq)
        row[r + "_inmkt"] = pos.mean()
        a = agg[r]; a["n"] += 1
        a["ret_ratio"].append(eq.iloc[-1] / bh.iloc[-1] if bh.iloc[-1] > 0 else np.nan)
        a["dd_bh"].append(maxdd(bh)); a["dd_rule"].append(maxdd(eq))
        if eq.iloc[-1] > bh.iloc[-1]:
            a["beat_ret"] += 1
        if maxdd(eq) > maxdd(bh):   # less negative = smaller drawdown
            a["cut_dd"] += 1
        if sharpe(eq) > sharpe(bh):
            a["beat_sharpe"] += 1
    per_coin.append(row)

# --- report ------------------------------------------------------------------
print("\n" + "=" * 94)
print("PER-COIN TIMING vs BUY&HOLD  (full history; in/out to cash)")
print("=" * 94)
print("  {:<6}{:>7}{:>8}{:>10}{:>10}{:>10}{:>9}".format(
    "coin", "days", "B&H", "MVRVtim", "Adopt", "Combo", "%inMkt"))
for row in sorted(per_coin, key=lambda x: -x["BH"]):
    print("  {:<6}{:>7}{:>8.2f}{:>10.2f}{:>10.2f}{:>10.2f}{:>8.0%}".format(
        row["coin"], row["days"], row["BH"], row["MVRV-timer"],
        row["Adoption-timer"], row["Combo"], row["Adoption-timer_inmkt"]))

print("\n" + "=" * 94)
print("AGGREGATE: does on-chain timing help the AVERAGE coin?")
print("=" * 94)
print("  {:<18}{:>10}{:>14}{:>16}{:>14}".format(
    "rule", "n_coins", "beats B&H ret", "cuts drawdown", "beats Sharpe"))
for r in rules:
    a = agg[r]; n = a["n"]
    print("  {:<18}{:>10}{:>13}{:>16}{:>14}".format(
        r, n, f"{a['beat_ret']}/{n}", f"{a['cut_dd']}/{n}", f"{a['beat_sharpe']}/{n}"))
print("\n  medians:")
for r in rules:
    a = agg[r]
    print(f"    {r:<16} return ratio (timed/B&H) = {np.nanmedian(a['ret_ratio']):.2f}x   "
          f"maxDD  B&H {np.nanmedian(a['dd_bh']):+.0%} -> rule {np.nanmedian(a['dd_rule']):+.0%}")
print("\n(ratio<1 = timing costs return; cuts-drawdown high = timing lowers risk.)")
