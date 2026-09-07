#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Rank a user list of coins by "best cards for the next bull" (fundamental quality
+ adoption + low dilution). NOT a moonshot predictor - it tilts odds & flags traps.

Factors (percentile-ranked across the list, then weighted):
  Adoption   0.30  TVL trend (chain 30d growth / protocol 7d change) - validated signal
  Dilution   0.25  mcap/FDV   (high = few unlocks left = good)
  Revenue    0.15  revenue/mcap (real cash-flow yield)
  Upside     0.15  smaller mcap = more room to run (log)
  Momentum   0.15  price 30d change

Data: CoinGecko (mcap/FDV/ATH/momentum, universal) + DefiLlama (TVL, revenue).
Stdlib only.
"""
import sys
import ssl
import json
import math
import time
import urllib.request

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = {"User-Agent": "Mozilla/5.0 (tangier-rank)"}

COINS = sys.argv[1].split(",") if len(sys.argv) > 1 else [
    "ZRO", "PENDLE", "LINK", "AVAX", "SKY", "SOL", "ETH", "INJ", "RENDER",
    "ONDO", "SUI", "KAS", "DOGE", "AAVE", "TAO", "UNI", "HYPE"]
COINS = [c.strip().upper() for c in COINS]

W = {"adoption": 0.30, "dilution": 0.25, "revenue": 0.15, "upside": 0.15, "momentum": 0.15}


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                        timeout=40, context=CTX) as r:
                return json.load(r)
        except Exception:  # noqa
            time.sleep(1.2 * (2 ** i))
    return None


# --------------------------------------------------------------------------- #
# 1) CoinGecko: universal market data (match by symbol, pick highest mcap)
# --------------------------------------------------------------------------- #
print("Fetching CoinGecko ...", flush=True)
cg = {}
for page in (1, 2):
    d = get("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd"
            f"&order=market_cap_desc&per_page=250&page={page}"
            "&price_change_percentage=7d,30d")
    for x in (d or []):
        s = (x.get("symbol") or "").upper()
        if s in COINS and (s not in cg or (x.get("market_cap") or 0) > (cg[s].get("market_cap") or 0)):
            cg[s] = x
    time.sleep(2)

# --------------------------------------------------------------------------- #
# 2) DefiLlama: protocols (symbol->tvl/change_7d/slug) and chains (tokenSymbol)
# --------------------------------------------------------------------------- #
print("Fetching DefiLlama ...", flush=True)
protos = get("https://api.llama.fi/protocols") or []
proto_by_sym = {}
for p in protos:
    s = (p.get("symbol") or "").upper()
    if s in COINS and (p.get("tvl") or 0) > (proto_by_sym.get(s, {}).get("tvl") or 0):
        proto_by_sym[s] = p

chains = get("https://api.llama.fi/v2/chains") or []
chain_by_sym = {}
for c in chains:
    s = (c.get("tokenSymbol") or "").upper()
    if s in COINS:
        chain_by_sym[s] = c


def tvl_trend(sym):
    """(tvl_usd, trend_pct, horizon_label). Chain 30d growth, else protocol 7d."""
    if sym in chain_by_sym:               # L1 token -> chain TVL + 30d growth
        name = chain_by_sym[sym].get("name")
        tvl = chain_by_sym[sym].get("tvl")
        hist = get("https://api.llama.fi/v2/historicalChainTvl/"
                   + urllib.parse.quote(name)) if name else None
        if hist and len(hist) > 31:
            now, past = hist[-1]["tvl"], hist[-31]["tvl"]
            return tvl, (now / past - 1 if past else None), "30d"
        return tvl, None, "30d"
    if sym in proto_by_sym:               # protocol token -> protocol TVL + 7d change
        p = proto_by_sym[sym]
        return p.get("tvl"), (p.get("change_7d") or 0) / 100.0, "7d"
    return None, None, "-"


def revenue30(sym):
    if sym not in proto_by_sym:
        return None
    slug = proto_by_sym[sym].get("slug")
    d = get(f"https://api.llama.fi/summary/fees/{slug}?dataType=dailyRevenue")
    if isinstance(d, dict):
        return d.get("total30d")
    return None


import urllib.parse
rows = {}
for s in COINS:
    m = cg.get(s, {})
    mcap = m.get("market_cap")
    fdv = m.get("fully_diluted_valuation")
    tvl, trend, hz = tvl_trend(s)
    rev = revenue30(s)
    rows[s] = {
        "mcap": mcap, "fdv": fdv,
        "m2f": (mcap / fdv if mcap and fdv else None),
        "ath": m.get("ath_change_percentage"),
        "mom": m.get("price_change_percentage_30d_in_currency"),
        "tvl": tvl, "trend": trend, "hz": hz, "rev": rev,
        "rev_yield": (rev * 12 / mcap if rev and mcap else (0.0 if rev == 0 else None)),
        "resolved": bool(m),
    }
    time.sleep(0.2)


# --------------------------------------------------------------------------- #
# 3) score: percentile-rank each factor across the list
# --------------------------------------------------------------------------- #
def pctl(values):
    """dict coin->value (None allowed) -> dict coin->0..100 percentile (higher=better)."""
    have = {k: v for k, v in values.items() if v is not None}
    out = {}
    if not have:
        return {k: 50.0 for k in values}
    order = sorted(have, key=lambda k: have[k])
    n = len(order)
    for i, k in enumerate(order):
        out[k] = (i / (n - 1) * 100) if n > 1 else 100.0
    return out


adoption = pctl({s: rows[s]["trend"] for s in COINS})
dilution = pctl({s: rows[s]["m2f"] for s in COINS})
revenue = pctl({s: rows[s]["rev_yield"] for s in COINS})
upside = pctl({s: (-math.log(rows[s]["mcap"]) if rows[s]["mcap"] else None) for s in COINS})
momentum = pctl({s: rows[s]["mom"] for s in COINS})

DEF = {"adoption": 50, "revenue": 20, "momentum": 50, "dilution": 50, "upside": 50}
final = []
for s in COINS:
    sc = {
        "adoption": adoption.get(s, DEF["adoption"]),
        "dilution": dilution.get(s, DEF["dilution"]),
        "revenue": revenue.get(s, DEF["revenue"]),
        "upside": upside.get(s, DEF["upside"]),
        "momentum": momentum.get(s, DEF["momentum"]),
    }
    total = sum(W[k] * sc[k] for k in W)
    final.append((total, s, sc))
final.sort(reverse=True)


# --------------------------------------------------------------------------- #
# 4) print
# --------------------------------------------------------------------------- #
def fmt_usd(v):
    if not v:
        return "-"
    if v >= 1e9:
        return f"${v/1e9:.1f}B"
    if v >= 1e6:
        return f"${v/1e6:.0f}M"
    return f"${v/1e3:.0f}k"


print("\n" + "=" * 100)
print("CLASSEMENT — meilleures cartes pour le prochain bull (score /100)")
print("=" * 100)
print(f"{'#':<3}{'Coin':<7}{'SCORE':<7}{'Adopt':<6}{'Dilut':<6}{'Rev':<5}{'Size':<6}{'Mom':<5}"
      f"{'mcap':<8}{'m/FDV':<7}{'TVL':<8}{'TVLΔ':<8}{'rev30j':<8}")
for rank, (total, s, sc) in enumerate(final, 1):
    r = rows[s]
    trend_s = (f"{r['trend']*100:+.0f}%{r['hz']}" if r["trend"] is not None else "-")
    m2f = f"{r['m2f']:.2f}" if r["m2f"] else "-"
    print(f"{rank:<3}{s:<7}{total:<7.0f}"
          f"{sc['adoption']:<6.0f}{sc['dilution']:<6.0f}{sc['revenue']:<5.0f}"
          f"{sc['upside']:<6.0f}{sc['momentum']:<5.0f}"
          f"{fmt_usd(r['mcap']):<8}{m2f:<7}{fmt_usd(r['tvl']):<8}{trend_s:<8}{fmt_usd(r['rev']):<8}")

print("\nRED FLAGS:")
for total, s, sc in final:
    r = rows[s]; flags = []
    if r["m2f"] is not None and r["m2f"] < 0.40:
        flags.append(f"⚠️ unlocks lourds (mcap/FDV {r['m2f']:.2f})")
    if r["rev"] == 0 or r["rev"] is None:
        if s in proto_by_sym or s in chain_by_sym:
            if not r["rev"]:
                flags.append("pas de revenue capté")
    if r["trend"] is not None and r["trend"] < -0.20:
        flags.append(f"TVL en chute ({r['trend']*100:+.0f}%)")
    if r["tvl"] is None:
        flags.append("pas de data on-chain (DeFi)")
    if not r["resolved"]:
        flags.append("NON RÉSOLU sur CoinGecko")
    if flags:
        print(f"  {s:<7} " + " | ".join(flags))
print("\nPondération:", ", ".join(f"{k}={int(v*100)}%" for k, v in W.items()))
print("Note: TVLΔ = croissance TVL (30d pour L1, 7d pour protocoles). "
      "Classement = qualité/adoption/dilution, PAS une prédiction de x20.")
