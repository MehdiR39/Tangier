"""Market metrics: point-in-time prices, returns, ATH, asymmetry multiples.

Every function takes ``as_of_ts`` and only reads observations with ``ts <= as_of_ts``.
"""
from __future__ import annotations

import logging
import statistics
from typing import Any

from intel.context import IntelContext
from intel.utils.timeutil import WINDOWS_SECONDS

log = logging.getLogger(__name__)

MC_LEVELS = {"100k": 100_000.0, "500k": 500_000.0, "1m": 1_000_000.0}
X_TARGETS = (10, 50, 100, 500, 1000)


def price_at(ctx: IntelContext, token: str, ts: int, *, max_age: int = 1800) -> tuple[float | None, str | None, int | None]:
    """Latest known USD price not after ``ts``: DexScreener snapshot or reconstructed trade."""
    token = token.lower()
    snap = ctx.db.query_one(
        "SELECT price_usd, ts FROM token_snapshots WHERE chain_id=? AND token_address=? AND price_usd IS NOT NULL AND ts<=? ORDER BY ts DESC LIMIT 1",
        (ctx.chain_id, token, ts),
    )
    trade = ctx.db.query_one(
        "SELECT price_usd, ts FROM trades WHERE chain_id=? AND token_address=? AND price_usd IS NOT NULL AND side IN ('BUY','SELL') AND ts<=? ORDER BY ts DESC, log_index DESC LIMIT 1",
        (ctx.chain_id, token, ts),
    )
    cands: list[tuple[int, float, str]] = []
    if snap is not None and ts - int(snap["ts"]) <= max_age:
        cands.append((int(snap["ts"]), float(snap["price_usd"]), "dexscreener"))
    if trade is not None and ts - int(trade["ts"]) <= max_age:
        cands.append((int(trade["ts"]), float(trade["price_usd"]), "rpc_trade"))
    if not cands:
        return None, None, None
    best = max(cands, key=lambda c: c[0])
    return best[1], best[2], best[0]


def returns(ctx: IntelContext, token: str, as_of_ts: int, windows: list[str] | None = None) -> dict[str, Any]:
    """Own-history returns; falls back to DexScreener priceChange when history is too short."""
    windows = windows or ["5m", "15m", "1h", "6h", "24h", "7d"]
    out: dict[str, Any] = {}
    flags: list[str] = []
    p_now, src_now, _ = price_at(ctx, token, as_of_ts)
    latest_pair = ctx.db.query_one(
        "SELECT pc_5m, pc_1h, pc_6h, pc_24h, ts FROM pair_snapshots WHERE chain_id=? AND token_address=? AND ts<=? ORDER BY liquidity_usd DESC, ts DESC LIMIT 1",
        (ctx.chain_id, token.lower(), as_of_ts),
    )
    dex_pc = {"5m": "pc_5m", "1h": "pc_1h", "6h": "pc_6h", "24h": "pc_24h"}
    for w in windows:
        secs = WINDOWS_SECONDS[w]
        val = None
        if p_now is not None:
            p_then, _, ts_then = price_at(ctx, token, as_of_ts - secs, max_age=max(600, secs // 2))
            if p_then:
                val = p_now / p_then - 1.0
        if val is None and latest_pair is not None and w in dex_pc and latest_pair[dex_pc[w]] is not None and as_of_ts - int(latest_pair["ts"]) <= 900:
            val = float(latest_pair[dex_pc[w]]) / 100.0
            flags.append(f"return_{w}_from_dexscreener")
        out[f"return_{w}"] = val
    out["price_usd"] = p_now
    out["price_source"] = src_now
    out["quality_flags"] = flags
    return out


def ath(ctx: IntelContext, token: str, as_of_ts: int, total_supply_float: float | None) -> dict[str, Any]:
    token = token.lower()
    r1 = ctx.db.query_one("SELECT MAX(price_usd) AS p FROM token_snapshots WHERE chain_id=? AND token_address=? AND ts<=?", (ctx.chain_id, token, as_of_ts))
    r2 = ctx.db.query_one(
        "SELECT MAX(price_usd) AS p FROM trades WHERE chain_id=? AND token_address=? AND side IN ('BUY','SELL') AND ts<=? AND usd_value>=25 "
        "AND quality_flags NOT LIKE '%mismatch%' AND quality_flags NOT LIKE '%multi_quote%' AND quality_flags NOT LIKE '%quote_price_missing%'",
        (ctx.chain_id, token, as_of_ts),
    )
    cands = [(float(r["p"]), src) for r, src in ((r1, "dexscreener"), (r2, "rpc_trade")) if r is not None and r["p"] is not None]
    if not cands:
        return {"ath_price": None, "ath_ts": None, "ath_market_cap": None, "ath_source": None}
    price, src = max(cands, key=lambda c: c[0])
    if src == "dexscreener":
        row = ctx.db.query_one("SELECT ts FROM token_snapshots WHERE chain_id=? AND token_address=? AND price_usd=? AND ts<=? ORDER BY ts LIMIT 1", (ctx.chain_id, token, price, as_of_ts))
    else:
        row = ctx.db.query_one("SELECT ts FROM trades WHERE chain_id=? AND token_address=? AND price_usd=? AND ts<=? ORDER BY ts LIMIT 1", (ctx.chain_id, token, price, as_of_ts))
    return {"ath_price": price, "ath_ts": int(row["ts"]) if row else None, "ath_market_cap": price * total_supply_float if total_supply_float else None, "ath_source": src}


def asymmetry_multiples(price: float | None, market_cap: float | None, raw_first_price: float | None, fmm_price: float | None, fmm_market_cap: float | None, ath_price: float | None) -> dict[str, float | None]:
    def ratio(a: float | None, b: float | None) -> float | None:
        return (a / b) if (a is not None and b not in (None, 0)) else None

    out: dict[str, float | None] = {
        "x_from_raw_launch": ratio(price, raw_first_price),
        "x_from_first_meaningful_market": ratio(price, fmm_price),
        "launch_to_ath_x": ratio(ath_price, raw_first_price),
        "first_market_to_ath_x": ratio(ath_price, fmm_price),
        "drawdown_from_ath": (1.0 - price / ath_price) if (price is not None and ath_price) else None,
    }
    for name, level in MC_LEVELS.items():
        out[f"x_from_{name}_mc"] = ratio(market_cap, level)
    for x in X_TARGETS:
        out[f"mc_required_x{x}"] = market_cap * x if market_cap is not None else None
    out["fmm_market_cap"] = fmm_market_cap
    return out


def liquidity_series(ctx: IntelContext, token: str, as_of_ts: int, lookback: int = 86400) -> list[tuple[int, float]]:
    rows = ctx.db.query(
        "SELECT ts, liquidity_usd FROM token_snapshots WHERE chain_id=? AND token_address=? AND liquidity_usd IS NOT NULL AND ts<=? AND ts>=? ORDER BY ts",
        (ctx.chain_id, token.lower(), as_of_ts, as_of_ts - lookback),
    )
    return [(int(r["ts"]), float(r["liquidity_usd"])) for r in rows]


def value_at(series: list[tuple[int, float]], ts: int, max_age: int | None = None) -> float | None:
    best = None
    for t, v in series:
        if t <= ts:
            best = (t, v)
        else:
            break
    if best is None:
        return None
    if max_age is not None and ts - best[0] > max_age:
        return None
    return best[1]


def pct_change(series: list[tuple[int, float]], as_of_ts: int, window: str) -> float | None:
    now = value_at(series, as_of_ts)
    then = value_at(series, as_of_ts - WINDOWS_SECONDS[window], max_age=max(600, WINDOWS_SECONDS[window] // 2))
    if now is None or then in (None, 0):
        return None
    return now / then - 1.0


def median_at(series: list[tuple[int, float]], ts: int, half_window: int = 900) -> float | None:
    """Median of the readings around ``ts``, or None when nothing was measured nearby."""
    vals = [v for t, v in series if abs(t - ts) <= half_window and v is not None]
    return statistics.median(vals) if vals else None


def robust_pct_change(series: list[tuple[int, float]], as_of_ts: int, window: str, half_window: int = 900) -> float | None:
    """Change between two medians rather than two readings.

    Aggregated liquidity is measured by summing whatever pools a provider returns, and that set
    varies from call to call: PAIR (2026-09-04, 16 pools) oscillated between 258k and 645k every
    few minutes. A point-to-point comparison read one of those dips as a 51 % collapse and sold a
    position that then doubled. A median over a window ignores the oscillation.
    """
    now = median_at(series, as_of_ts, half_window)
    then = median_at(series, as_of_ts - WINDOWS_SECONDS[window], half_window)
    if now is None or then in (None, 0):
        return None
    return now / then - 1.0
