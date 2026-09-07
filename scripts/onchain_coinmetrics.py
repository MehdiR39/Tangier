#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Fetch per-coin native on-chain fundamentals from Coin Metrics (community, free).

Metrics (community tier, availability varies per asset):
  AdrActCnt     active addresses  (network adoption / Metcalfe)
  TxCnt         transactions/day  (usage)
  TxTfrCnt      transfer count
  CapMVRVCur    MVRV              (valuation: <1 = below cost basis)
  CapMrktCurUSD market cap        (for NVT-style ratios)
  SplyCur       current supply

Writes long-format -> data_onchain/coinmetrics.csv  [date, coin, metric, value]
Robust: reads each asset's catalog first, requests only metrics it actually
exposes (mixing an unavailable metric 400/403s the whole call).
"""
import os
import csv
import ssl
import json
import time
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data_onchain")
os.makedirs(OUT, exist_ok=True)
CM = "https://community-api.coinmetrics.io/v4"
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = {"User-Agent": "Mozilla/5.0 (tangier)"}

UNIVERSE = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK",
            "DOT", "LTC", "TRX", "ATOM", "UNI", "ETC", "XLM", "NEAR", "ALGO",
            "FIL", "VET", "ICP", "HBAR", "AAVE", "THETA", "AXS", "SAND", "MANA",
            "GRT", "CHZ", "ENJ", "ZEC", "EGLD", "XTZ", "IOTA", "KAVA", "ZIL", "QTUM"]
WANT = ["AdrActCnt", "TxCnt", "TxTfrCnt", "CapMVRVCur", "CapMrktCurUSD", "SplyCur"]


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                        timeout=45, context=CTX) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (2 ** i)); continue
            raise
        except Exception:  # noqa
            time.sleep(1.5 * (2 ** i))
    raise RuntimeError("get failed: " + url)


assets = [c.lower() for c in UNIVERSE]
want_set = set(assets)
print("Reading Coin Metrics catalog (per-asset metric availability) ...")
cat = get(CM + "/catalog/assets")   # full catalog; filter to our universe
avail = {a["asset"]: {m["metric"] for m in a.get("metrics", [])}
         for a in cat.get("data", []) if a["asset"] in want_set}

rows, cover = [], {}
for a in assets:
    mets = [m for m in WANT if m in avail.get(a, set())]
    if not mets:
        cover[a.upper()] = "none"
        continue
    try:
        url = (CM + "/timeseries/asset-metrics?assets=" + a +
               "&metrics=" + ",".join(mets) + "&frequency=1d&page_size=10000")
        d = get(url).get("data", [])
        for x in d:
            day = x["time"][:10]
            for m in mets:
                v = x.get(m)
                if v is not None:
                    rows.append([day, a.upper(), m, v])
        cover[a.upper()] = ",".join(m.replace("Cur", "").replace("Cnt", "")
                                    for m in mets)
        print(f"  {a.upper():<6} {len(d):>5} days   [{'+'.join(mets)}]", flush=True)
    except Exception as e:  # noqa
        cover[a.upper()] = f"ERR {type(e).__name__}"
        print(f"  {a.upper():<6} ERR {e}", flush=True)
    time.sleep(0.3)

rows.sort()
path = os.path.join(OUT, "coinmetrics.csv")
with open(path, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["date", "coin", "metric", "value"]); w.writerows(rows)

has_mvrv = [c for c in UNIVERSE if "MVRV" in cover.get(c, "")]
print(f"\n  wrote {len(rows)} rows -> {path}")
print(f"  coins with data: {sum(1 for c in UNIVERSE if cover.get(c) not in ('none', None) and not cover.get(c,'').startswith('ERR'))}/37")
print(f"  coins with MVRV: {len(has_mvrv)} -> {has_mvrv}")
