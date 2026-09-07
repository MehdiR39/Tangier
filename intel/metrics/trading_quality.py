"""Trading quality and the heuristic ORGANIC_VOLUME_SCORE (0-100).

High turnover is not demand. The score starts at 100 and is reduced by evidence of
churn, same-block round trips, repetitive sizes, wallet-concentrated volume and volume
that DexScreener reports but on-chain reconstruction cannot account for. It is a
heuristic flag for probable bot / wash behaviour — never a proof of wash trading.
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Any

from intel.context import IntelContext


def size_bucket(usd: float, tolerance: float = 0.002) -> int:
    """Bucket a USD size with *relative* precision: values within ``tolerance`` share a key."""
    import math
    return int(round(math.log(max(usd, 1e-9)) / math.log(1.0 + tolerance)))


def _percentile(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    k = min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))
    return s[k]


def trading_quality(trades: list[dict[str, Any]], *, first_trade_ts: dict[str, int] | None = None, window_start: int | None = None, params: dict[str, Any] | None = None, dex_txns: int | None = None) -> dict[str, Any]:
    """``trades``: rows with trader, side, usd_value, block_number, ts, quality_flags(list|json)."""
    p = params or {}
    buys = [t for t in trades if t["side"] == "BUY"]
    sells = [t for t in trades if t["side"] == "SELL"]
    rts = [t for t in trades if t["side"] == "ROUNDTRIP"]
    buyers = {t["trader"] for t in buys}
    sellers = {t["trader"] for t in sells}
    traders = buyers | sellers | {t["trader"] for t in rts}
    usd = [float(t["usd_value"]) for t in buys + sells if t.get("usd_value")]
    volume = sum(usd)
    out: dict[str, Any] = {
        "buy_count": len(buys), "sell_count": len(sells), "buy_sell_ratio": (len(buys) / len(sells)) if sells else (float(len(buys)) if buys else None),
        "unique_buyers": len(buyers), "unique_sellers": len(sellers), "unique_traders": len(traders),
        "median_trade_usd": statistics.median(usd) if usd else None, "p90_trade_usd": _percentile(usd, 0.9), "volume_usd": volume,
        "volume_per_unique_trader": (volume / len(traders)) if traders else None,
        "quality_flags": [],
    }
    # new vs repeat buyers (needs each trader's first-ever trade timestamp)
    if first_trade_ts is not None and window_start is not None:
        new = {a for a in buyers if first_trade_ts.get(a, 0) >= window_start}
        out["new_buyers"] = len(new)
        out["repeat_buyers"] = len(buyers) - len(new)
    else:
        out["new_buyers"] = None
        out["repeat_buyers"] = None
        out["quality_flags"].append("new_buyers_unavailable")
    # churn: wallets that both bought and sold within the window
    churners = buyers & sellers
    out["wallet_churn"] = (len(churners) / len(traders)) if traders else None
    # round trips: explicit same-tx round trips + same-block buy & sell by the same wallet
    by_block_wallet: dict[tuple[int, str], set[str]] = defaultdict(set)
    for t in buys + sells:
        by_block_wallet[(int(t["block_number"]), t["trader"])].add(t["side"])
    same_block = sum(1 for sides in by_block_wallet.values() if len(sides) == 2)
    n_trades = len(buys) + len(sells) + len(rts)
    out["same_block_roundtrips"] = same_block + len(rts)
    out["round_trip_ratio"] = ((same_block * 2 + len(rts)) / n_trades) if n_trades else None
    # repetitive sizes: share of trades whose rounded usd size occurs >= 3 times
    tol = float(p.get("repetitive_size_tolerance", 0.002))
    sizes = Counter()
    for v in usd:
        if v > 0:
            sizes[size_bucket(v, tol)] += 1
    rep = sum(c for c in sizes.values() if c >= 3)
    out["repetitive_size_share"] = (rep / len(usd)) if usd else None
    # volume concentration by wallet
    vol_by_wallet: Counter = Counter()
    for t in buys + sells:
        if t.get("usd_value"):
            vol_by_wallet[t["trader"]] += float(t["usd_value"])
    top = vol_by_wallet.most_common(5)
    out["top1_wallet_volume_share"] = (top[0][1] / volume) if (top and volume) else None
    out["top5_wallet_volume_share"] = (sum(v for _, v in top) / volume) if (top and volume) else None
    # DexScreener cross-check
    if dex_txns is not None and n_trades:
        out["dex_txns_to_onchain_ratio"] = dex_txns / n_trades
    else:
        out["dex_txns_to_onchain_ratio"] = None
    out["organic_volume_score"], out["organic_explain"] = organic_volume_score(out, p)
    return out


def organic_volume_score(m: dict[str, Any], p: dict[str, Any]) -> tuple[float | None, list[str]]:
    if not m.get("unique_traders"):
        return None, ["no_trades"]
    score = 100.0
    why: list[str] = []
    rt = m.get("round_trip_ratio") or 0.0
    thr = float(p.get("round_trip_ratio_threshold", 0.4))
    if rt > 0.05:
        pen = float(p.get("same_block_roundtrip_penalty", 15)) * min(2.0, rt / thr)
        score -= pen
        why.append(f"round_trip_ratio={rt:.2f} (-{pen:.0f})")
    rep = m.get("repetitive_size_share") or 0.0
    if rep > 0.25:
        pen = float(p.get("repetitive_size_penalty", 15)) * min(2.0, rep / 0.5)
        score -= pen
        why.append(f"repetitive_sizes={rep:.2f} (-{pen:.0f})")
    top1 = m.get("top1_wallet_volume_share") or 0.0
    thr_top = float(p.get("top_wallet_volume_share_threshold", 0.35))
    if top1 > thr_top:
        pen = float(p.get("wallet_volume_concentration_penalty", 25)) * min(2.0, top1 / thr_top)
        score -= pen
        why.append(f"top1_wallet_volume_share={top1:.2f} (-{pen:.0f})")
    churn = m.get("wallet_churn") or 0.0
    if churn > 0.5:
        pen = float(p.get("churn_penalty", 20)) * min(1.5, churn / 0.5)
        score -= pen
        why.append(f"wallet_churn={churn:.2f} (-{pen:.0f})")
    vpt = m.get("volume_per_unique_trader") or 0.0
    thr_v = float(p.get("volume_per_trader_usd_threshold", 25000.0))
    if vpt > thr_v:
        pen = 10.0 * min(2.0, vpt / thr_v)
        score -= pen
        why.append(f"volume_per_trader=${vpt:,.0f} (-{pen:.0f})")
    if m["unique_traders"] < 10:
        pen = float(p.get("low_unique_trader_penalty", 25))
        score -= pen
        why.append(f"unique_traders={m['unique_traders']} (-{pen:.0f})")
    ratio = m.get("dex_txns_to_onchain_ratio")
    if ratio is not None and ratio > 2.5:
        score -= 10
        why.append(f"dex_txns/onchain={ratio:.1f} (-10)")
    return max(0.0, min(100.0, score)), why


def load_trades(ctx: IntelContext, token: str, since_ts: int, as_of_ts: int) -> list[dict[str, Any]]:
    rows = ctx.db.query(
        "SELECT tx_hash, trader, side, usd_value, block_number, ts, price_usd, token_amount_float, quality_flags FROM trades WHERE chain_id=? AND token_address=? AND ts>? AND ts<=? ORDER BY ts",
        (ctx.chain_id, token.lower(), since_ts, as_of_ts),
    )
    return [dict(r) for r in rows]


def first_trade_timestamps(ctx: IntelContext, token: str, traders: set[str], as_of_ts: int) -> dict[str, int]:
    if not traders:
        return {}
    out: dict[str, int] = {}
    lst = list(traders)
    for i in range(0, len(lst), 500):
        chunk = lst[i: i + 500]
        rows = ctx.db.query(
            f"SELECT trader, MIN(ts) AS t FROM trades WHERE chain_id=? AND token_address=? AND ts<=? AND trader IN ({','.join('?' for _ in chunk)}) GROUP BY trader",
            (ctx.chain_id, token.lower(), as_of_ts, *chunk),
        )
        for r in rows:
            out[r["trader"]] = int(r["t"])
    return out
