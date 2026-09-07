"""First-meaningful-market heuristic and launch profile persistence.

The raw first on-chain print of a launchpad token (Doppler auction, seed liquidity) is
not a tradable reference. We therefore store the raw first trade separately and define
the FIRST MEANINGFUL MARKET as the first time bucket from which, for ``persistence``
consecutive buckets, cumulative unique traders, trade count, net quote inflow and pool
liquidity all exceed configurable minimums. Its VWAP is ``first_meaningful_market_price``.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any

from intel import MODEL_VERSION
from intel.context import IntelContext
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FMMParams:
    bucket_seconds: int = 300
    min_unique_traders: int = 25
    min_trades: int = 50
    min_cum_quote_inflow_usd: float = 10000.0
    min_liquidity_usd: float = 20000.0
    persistence_buckets: int = 3

    @classmethod
    def from_config(cls, ctx: IntelContext) -> "FMMParams":
        c = ctx.config.section("first_meaningful_market")
        return cls(
            bucket_seconds=int(c.get("bucket_seconds", 300)),
            min_unique_traders=int(c.get("min_unique_traders", 25)),
            min_trades=int(c.get("min_trades", 50)),
            min_cum_quote_inflow_usd=float(c.get("min_cum_quote_inflow_usd", 10000.0)),
            min_liquidity_usd=float(c.get("min_liquidity_usd", 20000.0)),
            persistence_buckets=int(c.get("persistence_buckets", 3)),
        )


@dataclass
class FMMResult:
    reached: bool
    ts: int | None
    price_usd: float | None
    bucket_index: int | None
    raw_first_trade_ts: int | None
    raw_first_trade_price_usd: float | None
    raw_first_trade_price_native: float | None
    evidence: dict[str, Any]
    quality_flags: list[str]


def _liquidity_at(series: list[tuple[int, float]] | None, ts: int) -> float | None:
    if not series:
        return None
    best = None
    for t, v in series:
        if t <= ts:
            best = v
        else:
            break
    return best


def first_meaningful_market(trades: list[dict[str, Any]], params: FMMParams, liquidity_series: list[tuple[int, float]] | None = None) -> FMMResult:
    """``trades`` rows need: ts, trader, side (BUY/SELL), usd_value, price_usd, token_amount_float, price_native."""
    flags: list[str] = []
    rows = [t for t in trades if t.get("ts") is not None and t.get("side") in ("BUY", "SELL")]
    rows.sort(key=lambda t: (t["ts"], t.get("log_index") or 0))
    if not rows:
        return FMMResult(False, None, None, None, None, None, None, {"reason": "no_trades"}, ["no_trades"])
    first = next((t for t in rows if t.get("price_usd")), rows[0])
    raw_ts = int(first["ts"])
    t0 = int(rows[0]["ts"])
    if liquidity_series is None:
        flags.append("fmm_liquidity_proxy_inflow")
    buckets: dict[int, list[dict[str, Any]]] = {}
    for t in rows:
        buckets.setdefault((int(t["ts"]) - t0) // params.bucket_seconds, []).append(t)
    traders: set[str] = set()
    n_trades = 0
    inflow = 0.0
    run = 0
    run_start: int | None = None
    max_bucket = max(buckets)
    evidence: dict[str, Any] = {}
    for b in range(0, max_bucket + 1):
        for t in buckets.get(b, []):
            traders.add(t["trader"])
            n_trades += 1
            usd = t.get("usd_value") or 0.0
            inflow += usd if t["side"] == "BUY" else -usd
        bucket_end = t0 + (b + 1) * params.bucket_seconds
        liq = _liquidity_at(liquidity_series, bucket_end)
        liq_ok = (liq >= params.min_liquidity_usd) if liq is not None else (inflow >= params.min_liquidity_usd)
        ok = len(traders) >= params.min_unique_traders and n_trades >= params.min_trades and inflow >= params.min_cum_quote_inflow_usd and liq_ok
        if ok:
            if run == 0:
                run_start = b
            run += 1
            if run >= params.persistence_buckets:
                assert run_start is not None
                bucket_trades = [t for t in buckets.get(run_start, []) if t.get("price_usd") and t.get("token_amount_float")]
                if not bucket_trades:
                    # fall back to the first priced trade at/after the bucket
                    later = [t for bb in range(run_start, max_bucket + 1) for t in buckets.get(bb, []) if t.get("price_usd")]
                    bucket_trades = later[:1]
                if not bucket_trades:
                    flags.append("fmm_unpriced")
                    return FMMResult(False, None, None, None, raw_ts, first.get("price_usd"), first.get("price_native"), {"reason": "unpriced"}, flags)
                vol = sum(t["token_amount_float"] for t in bucket_trades)
                vwap = sum(t["price_usd"] * t["token_amount_float"] for t in bucket_trades) / vol if vol else bucket_trades[0]["price_usd"]
                fmm_ts = t0 + run_start * params.bucket_seconds
                evidence = {"bucket_index": run_start, "unique_traders": len(traders), "trades": n_trades, "cum_inflow_usd": round(inflow, 2), "liquidity_usd": liq, "persistence": run}
                return FMMResult(True, fmm_ts, vwap, run_start, raw_ts, first.get("price_usd"), first.get("price_native"), evidence, flags)
        else:
            run = 0
            run_start = None
    evidence = {"unique_traders": len(traders), "trades": n_trades, "cum_inflow_usd": round(inflow, 2), "reason": "thresholds_not_met"}
    return FMMResult(False, None, None, None, raw_ts, first.get("price_usd"), first.get("price_native"), evidence, flags)


def load_trades_for_launch(ctx: IntelContext, token: str, as_of_ts: int, limit: int = 200_000) -> list[dict[str, Any]]:
    rows = ctx.db.query(
        "SELECT ts, log_index, trader, side, usd_value, price_usd, price_native, token_amount_float FROM trades WHERE chain_id=? AND token_address=? AND ts<=? ORDER BY ts, log_index LIMIT ?",
        (ctx.chain_id, token.lower(), as_of_ts, limit),
    )
    return [dict(r) for r in rows]


def launch_history_complete(ctx: IntelContext, token: str) -> bool:
    """True when ingested transfers start at the token's creation (mint from 0x0 seen, or the
    earliest ingested block is not after the creation block). Otherwise the first trade we
    know is NOT the raw launch print and the FMM heuristic must not be trusted."""
    token = token.lower()
    # a backward backfill in progress leaves a gap between its cursor and the forward start
    fwd_start = ctx.db.cursor_get(f"transfers_fwd_start:{token}")
    back = ctx.db.cursor_get(f"transfers_back:{token}")
    if fwd_start is not None and back is not None and int(back) < int(fwd_start) - 1:
        return False
    if fwd_start is not None and back is not None:
        rebuilt = ctx.db.cursor_get(f"transfers_rebuilt:{token}")
        if rebuilt is None or int(rebuilt) < int(fwd_start) - 1:
            return False  # gap closed but balances not rebuilt yet
    # Coverage must reach the creation block. A mint from 0x0 inside the window is NOT proof:
    # tokenised stocks and some launchpads mint continuously (seen on TSM: mints every day).
    row = ctx.db.query_one("SELECT creation_block FROM tokens WHERE chain_id=? AND address=?", (ctx.chain_id, token))
    first = ctx.db.scalar("SELECT MIN(block_number) FROM transfers WHERE chain_id=? AND token_address=?", (ctx.chain_id, token))
    if first is None:
        return False
    creation = int(row["creation_block"]) if row and row["creation_block"] else None
    if creation is None:
        earliest_pool = ctx.db.scalar("SELECT MIN(created_block) FROM pairs WHERE chain_id=? AND token_address=? AND created_block IS NOT NULL", (ctx.chain_id, token))
        if earliest_pool is None:
            return False
        creation = int(earliest_pool)
    return int(first) <= creation + 5


def compute_launch_profile(ctx: IntelContext, token: str, as_of_ts: int, total_supply_float: float | None, ath_info: dict[str, Any], *, persist: bool = True) -> dict[str, Any]:
    params = FMMParams.from_config(ctx)
    trades = load_trades_for_launch(ctx, token, as_of_ts)
    from intel.metrics.market import liquidity_series  # local import to avoid cycles

    liq = liquidity_series(ctx, token, as_of_ts, lookback=30 * 86400) or None
    complete = launch_history_complete(ctx, token)
    if complete:
        res = first_meaningful_market(trades, params, liq)
    else:
        res = FMMResult(False, None, None, None, None, None, None, {"reason": "launch_history_incomplete", "n_trades": len(trades)}, ["launch_history_incomplete"])
    profile = {
        "raw_first_trade_ts": res.raw_first_trade_ts,
        "raw_first_trade_price_usd": res.raw_first_trade_price_usd,
        "raw_first_trade_price_native": res.raw_first_trade_price_native,
        "fmm_reached": res.reached,
        "fmm_ts": res.ts,
        "fmm_price_usd": res.price_usd,
        "fmm_market_cap": (res.price_usd * total_supply_float) if (res.price_usd and total_supply_float) else None,
        "evidence": res.evidence,
        "params": asdict(params),
        "quality_flags": res.quality_flags,
        "n_trades_considered": len(trades),
    }
    if persist:
        ctx.db.insert("launch_profiles", {
            "ts": now_ts(), "chain_id": ctx.chain_id, "token_address": token.lower(), "source": "rpc_reconstruction", "model_version": MODEL_VERSION,
            "raw_first_trade_ts": res.raw_first_trade_ts, "raw_first_trade_block": None, "raw_first_trade_price_usd": res.raw_first_trade_price_usd, "raw_first_trade_price_native": res.raw_first_trade_price_native,
            "fmm_ts": res.ts, "fmm_block": None, "fmm_price_usd": res.price_usd, "fmm_price_native": None, "fmm_market_cap": profile["fmm_market_cap"], "fmm_reached": int(res.reached),
            "ath_price_usd": ath_info.get("ath_price"), "ath_ts": ath_info.get("ath_ts"), "ath_market_cap": ath_info.get("ath_market_cap"),
            "heuristic_params_json": json.dumps(asdict(params)), "quality_flags": json.dumps(res.quality_flags + [f"evidence:{json.dumps(res.evidence)}"]),
        })
    return profile
