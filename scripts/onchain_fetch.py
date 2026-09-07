#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
On-chain / fundamental data collector for the Tangier crypto study.

Pulls ONLY free, no-API-key, historical (=> backtestable) sources and writes
tidy CSVs into data_onchain/.

Sources
-------
  * alternative.me      -> Fear & Greed index (full daily history)
  * DefiLlama           -> total DeFi TVL, per-chain TVL, per-protocol
                           fees/revenue, total stablecoin supply
  * Binance Futures      -> funding rates per perp (leverage/sentiment)
  * CoinGecko (free)     -> current fundamentals snapshot (mcap, FDV,
                           supply, volume, ATH) for the value/unlock factor

Everything is written long-format where possible so the analysis notebook can
pivot freely. Each module is independently re-runnable via --only.

Usage
-----
  python scripts/onchain_fetch.py                # run everything
  python scripts/onchain_fetch.py --only fng,tvl # subset
"""

import os
import sys
import csv
import json
import time
import ssl
import argparse
import datetime as dt
import urllib.request
import urllib.error
import urllib.parse

# --------------------------------------------------------------------------- #
# Paths / config
# --------------------------------------------------------------------------- #
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data_onchain")
os.makedirs(OUT, exist_ok=True)

# Our 37-coin universe (base tickers, no USDT)
UNIVERSE = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK",
            "DOT", "LTC", "TRX", "ATOM", "UNI", "ETC", "XLM", "NEAR", "ALGO",
            "FIL", "VET", "ICP", "HBAR", "AAVE", "THETA", "AXS", "SAND", "MANA",
            "GRT", "CHZ", "ENJ", "ZEC", "EGLD", "XTZ", "IOTA", "KAVA", "ZIL", "QTUM"]

# Coins that ARE L1/L2 chains on DefiLlama  ->  DefiLlama chain name
CHAIN_MAP = {
    "ETH": "Ethereum", "BNB": "BSC", "SOL": "Solana", "AVAX": "Avalanche",
    "ADA": "Cardano", "DOT": "Polkadot", "TRX": "Tron", "ATOM": "Cosmos",
    "NEAR": "Near", "ALGO": "Algorand", "ICP": "ICP", "HBAR": "Hedera",
    "EGLD": "MultiversX", "XTZ": "Tezos", "KAVA": "Kava", "ZIL": "Zilliqa",
    "FIL": "Filecoin", "XLM": "Stellar", "IOTA": "IOTA", "ETC": "Ethereum Classic",
    "VET": "Vechain", "QTUM": "Qtum",
}

# Coins that are DeFi protocols  ->  DefiLlama protocol slug (fees/revenue)
PROTO_MAP = {
    "UNI": "uniswap", "AAVE": "aave", "LINK": "chainlink", "GRT": "the-graph",
    "AXS": "axie-infinity", "SAND": "the-sandbox", "MANA": "decentraland",
    "ENJ": "enjin", "CHZ": "chiliz",
}

# Binance perp symbol overrides (base -> full symbol); default is BASE+USDT
FUNDING_SYMBOLS = {c: c + "USDT" for c in UNIVERSE}

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

UA = {"User-Agent": "Mozilla/5.0 (research; tangier-onchain)"}


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #
def get(url, tries=4, pause=1.5):
    """GET json with retry + exponential backoff on 429/5xx/timeouts."""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=40, context=CTX) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(pause * (2 ** i))
                continue
            raise
        except Exception as e:  # noqa
            last = e
            time.sleep(pause * (2 ** i))
    raise last


def ts_to_day(ts):
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).strftime("%Y-%m-%d")


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return len(rows)


# --------------------------------------------------------------------------- #
# Modules
# --------------------------------------------------------------------------- #
def fetch_fear_greed():
    """Full-history Fear & Greed index (daily)."""
    d = get("https://api.alternative.me/fng/?limit=0")
    rows = []
    for x in d["data"]:
        rows.append([ts_to_day(x["timestamp"]), int(x["value"]),
                     x["value_classification"]])
    rows.sort()
    n = write_csv(os.path.join(OUT, "fear_greed.csv"),
                  ["date", "fng", "classification"], rows)
    span = f"{rows[0][0]}..{rows[-1][0]}" if rows else "-"
    return {"file": "fear_greed.csv", "rows": n, "span": span}


def fetch_total_tvl():
    """Total DeFi TVL across all chains (daily history)."""
    d = get("https://api.llama.fi/v2/historicalChainTvl")
    rows = [[ts_to_day(x["date"]), round(x["tvl"], 2)] for x in d]
    rows.sort()
    n = write_csv(os.path.join(OUT, "defi_tvl_total.csv"),
                  ["date", "tvl"], rows)
    span = f"{rows[0][0]}..{rows[-1][0]}" if rows else "-"
    return {"file": "defi_tvl_total.csv", "rows": n, "span": span}


def fetch_stablecoins():
    """Total stablecoin market cap (dry powder proxy), daily history."""
    d = get("https://stablecoins.llama.fi/stablecoincharts/all")
    rows = []
    for x in d:
        cap = x.get("totalCirculatingUSD", {})
        val = cap.get("peggedUSD") if isinstance(cap, dict) else cap
        if val is None:
            continue
        rows.append([ts_to_day(x["date"]), round(float(val), 2)])
    rows.sort()
    n = write_csv(os.path.join(OUT, "stablecoin_supply.csv"),
                  ["date", "stablecoin_mcap"], rows)
    span = f"{rows[0][0]}..{rows[-1][0]}" if rows else "-"
    return {"file": "stablecoin_supply.csv", "rows": n, "span": span}


def fetch_chain_tvl():
    """Per-chain TVL history for our L1/L2 coins (long format)."""
    rows, ok, miss = [], [], []
    for coin, chain in CHAIN_MAP.items():
        try:
            d = get("https://api.llama.fi/v2/historicalChainTvl/" +
                    urllib.parse.quote(chain))
            if not isinstance(d, list) or not d:
                miss.append(f"{coin}({chain})")
                continue
            for x in d:
                rows.append([ts_to_day(x["date"]), coin, chain,
                             round(x["tvl"], 2)])
            ok.append(coin)
        except Exception as e:  # noqa
            miss.append(f"{coin}({chain}:{type(e).__name__})")
        time.sleep(0.4)
    rows.sort()
    n = write_csv(os.path.join(OUT, "chain_tvl.csv"),
                  ["date", "coin", "chain", "tvl"], rows)
    return {"file": "chain_tvl.csv", "rows": n,
            "covered": ok, "missing": miss}


def fetch_protocol_revenue():
    """Per-protocol daily fees & revenue for our DeFi tokens (long format)."""
    rows, ok, miss = [], [], []
    for coin, slug in PROTO_MAP.items():
        got = False
        series = {}
        for dtype, key in [("dailyFees", "fees"), ("dailyRevenue", "revenue")]:
            try:
                d = get(f"https://api.llama.fi/summary/fees/{slug}"
                        f"?dataType={dtype}")
                chart = d.get("totalDataChart") or []
                for ts, val in chart:
                    day = ts_to_day(ts)
                    series.setdefault(day, {})[key] = val
                if chart:
                    got = True
            except Exception:  # noqa
                pass
            time.sleep(0.4)
        if got:
            for day in sorted(series):
                rows.append([day, coin,
                             series[day].get("fees", ""),
                             series[day].get("revenue", "")])
            ok.append(coin)
        else:
            miss.append(f"{coin}({slug})")
    rows.sort()
    n = write_csv(os.path.join(OUT, "protocol_revenue.csv"),
                  ["date", "coin", "fees", "revenue"], rows)
    return {"file": "protocol_revenue.csv", "rows": n,
            "covered": ok, "missing": miss}


def fetch_funding(max_pages=12):
    """Binance perp funding rates resampled to daily mean (long format).

    Pages FORWARD from Binance-perp inception using startTime so we get the
    full multi-year history, not just the most recent window.
    """
    # 2019-09-01 UTC in ms (Binance USD-M perps launched ~Sept 2019)
    START_MS = 1567296000000
    rows, ok, miss = [], [], []
    for coin, sym in FUNDING_SYMBOLS.items():
        try:
            all_pts, start = [], START_MS
            for _ in range(max_pages):
                url = ("https://fapi.binance.com/fapi/v1/fundingRate"
                       f"?symbol={sym}&startTime={start}&limit=1000")
                d = get(url, tries=2)
                if not isinstance(d, list) or not d:
                    break
                all_pts += d
                start = int(d[-1]["fundingTime"]) + 1
                if len(d) < 1000:
                    break
                time.sleep(0.25)
            if not all_pts:
                miss.append(coin)
                continue
            # daily mean of the (usually 3/day) funding prints
            daily = {}
            for p in all_pts:
                day = ts_to_day(int(p["fundingTime"]) // 1000)
                daily.setdefault(day, []).append(float(p["fundingRate"]))
            for day in sorted(daily):
                v = sum(daily[day]) / len(daily[day])
                rows.append([day, coin, f"{v:.8f}"])
            ok.append(coin)
        except Exception:  # noqa
            miss.append(coin)
        time.sleep(0.2)
    rows.sort()
    n = write_csv(os.path.join(OUT, "funding_rates.csv"),
                  ["date", "coin", "funding_rate"], rows)
    return {"file": "funding_rates.csv", "rows": n,
            "covered": ok, "missing": miss}


def fetch_coingecko_snapshot():
    """Current fundamentals snapshot: mcap, FDV, supply, volume, ATH."""
    want = {c.lower() for c in UNIVERSE}
    rows, seen = [], set()
    for page in (1, 2):
        d = get("https://api.coingecko.com/api/v3/coins/markets"
                "?vs_currency=usd&order=market_cap_desc"
                f"&per_page=250&page={page}&sparkline=false")
        if not isinstance(d, list):
            break
        for x in d:
            sym = (x.get("symbol") or "").lower()
            if sym in want and sym not in seen:
                seen.add(sym)
                mcap = x.get("market_cap") or 0
                fdv = x.get("fully_diluted_valuation") or 0
                rows.append([
                    sym.upper(),
                    x.get("current_price") or "",
                    mcap, fdv,
                    round(mcap / fdv, 4) if fdv else "",   # circ/FDV = unlock proxy
                    x.get("circulating_supply") or "",
                    x.get("total_supply") or "",
                    x.get("total_volume") or "",
                    x.get("ath") or "",
                    x.get("ath_change_percentage") or "",
                ])
        time.sleep(2.0)
    rows.sort()
    miss = sorted(want - seen)
    n = write_csv(os.path.join(OUT, "coingecko_snapshot.csv"),
                  ["coin", "price", "mcap", "fdv", "mcap_to_fdv",
                   "circ_supply", "total_supply", "vol24h", "ath",
                   "ath_change_pct"], rows)
    return {"file": "coingecko_snapshot.csv", "rows": n,
            "missing_from_top500": [m.upper() for m in miss]}


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
MODULES = {
    "fng": ("Fear & Greed", fetch_fear_greed),
    "tvl_total": ("Total DeFi TVL", fetch_total_tvl),
    "stables": ("Stablecoin supply", fetch_stablecoins),
    "chain_tvl": ("Per-chain TVL", fetch_chain_tvl),
    "revenue": ("Protocol fees/revenue", fetch_protocol_revenue),
    "funding": ("Funding rates", fetch_funding),
    "gecko": ("CoinGecko snapshot", fetch_coingecko_snapshot),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="",
                    help="comma list: " + ",".join(MODULES))
    args = ap.parse_args()
    pick = [k.strip() for k in args.only.split(",") if k.strip()] or list(MODULES)

    manifest = {}
    for key in pick:
        if key not in MODULES:
            print(f"  ?? unknown module '{key}' (skip)")
            continue
        label, fn = MODULES[key]
        print(f"[{key}] {label} ...", flush=True)
        try:
            info = fn()
            manifest[key] = info
            extra = ""
            if "covered" in info:
                extra = f"  covered={len(info['covered'])} missing={len(info['missing'])}"
            print(f"    OK  {info.get('file','')}  rows={info.get('rows','?')}"
                  f"  {info.get('span','')}{extra}", flush=True)
            if info.get("missing"):
                print(f"    miss: {info['missing']}", flush=True)
        except Exception as e:  # noqa
            manifest[key] = {"error": f"{type(e).__name__}: {e}"}
            print(f"    ERR {e}", flush=True)

    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print("\nmanifest -> data_onchain/manifest.json")


if __name__ == "__main__":
    main()
