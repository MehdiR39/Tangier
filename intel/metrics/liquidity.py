"""Liquidity metrics, LP event detection and price-impact estimation."""
from __future__ import annotations

import logging
from typing import Any

from intel.chain.constants import V4_QUOTE_EXACT_INPUT_SINGLE
from intel.chain.uniswap_v4 import cpmm_price_impact, virtual_reserves
from intel.context import IntelContext
from intel.ingest.pools import PoolInfo, latest_pool_state
from intel.metrics.market import liquidity_series, pct_change, robust_pct_change, value_at
from intel.metrics.pricing import QuotePricer
from intel.utils.abi import ZERO_ADDRESS, decode, encode_call
from intel.utils.timeutil import WINDOWS_SECONDS

log = logging.getLogger(__name__)


def liquidity_metrics(ctx: IntelContext, token: str, as_of_ts: int, pools: dict[str, PoolInfo], *, market_cap: float | None, volume_24h: float | None) -> dict[str, Any]:
    token = token.lower()
    series = liquidity_series(ctx, token, as_of_ts, lookback=8 * 86400)
    liq = value_at(series, as_of_ts, max_age=1800)
    out: dict[str, Any] = {"liquidity_usd": liq, "quality_flags": []}
    if liq is None:
        out["quality_flags"].append("liquidity_missing")
    out["liquidity_to_mc"] = (liq / market_cap) if (liq is not None and market_cap) else None
    # Medians, not point readings: the aggregate jumps whenever the provider returns a different
    # subset of pools, and a sell trigger must not fire on that.
    for w in ("5m", "1h", "6h", "24h"):
        out[f"liquidity_change_{w}"] = robust_pct_change(series, as_of_ts, w)
    out["volume_to_liquidity"] = (volume_24h / liq) if (volume_24h is not None and liq) else None
    out["volume_to_mc"] = (volume_24h / market_cap) if (volume_24h is not None and market_cap) else None
    # pool structure from the latest pair snapshots
    latest = ctx.db.query_one("SELECT MAX(ts) AS t FROM pair_snapshots WHERE chain_id=? AND token_address=? AND ts<=?", (ctx.chain_id, token, as_of_ts))
    pools_now: list[dict[str, Any]] = []
    if latest and latest["t"] and as_of_ts - int(latest["t"]) <= 1800:
        rows = ctx.db.query("SELECT p.pair_id, p.liquidity_usd, pr.quote_symbol, pr.quote_address, pr.hooks FROM pair_snapshots p LEFT JOIN pairs pr ON pr.chain_id=p.chain_id AND pr.pair_id=p.pair_id WHERE p.chain_id=? AND p.token_address=? AND p.ts=?", (ctx.chain_id, token, latest["t"]))
        pools_now = [dict(r) for r in rows]
    min_meaningful = float(ctx.config.get("liquidity.meaningful_pool_min_liquidity_usd", 5000.0))
    meaningful = [p for p in pools_now if (p.get("liquidity_usd") or 0) >= min_meaningful]
    out["number_of_pools"] = len(pools_now)
    out["number_of_meaningful_pools"] = len(meaningful)
    out["quote_assets"] = sorted({p.get("quote_symbol") or "?" for p in meaningful})
    total = sum((p.get("liquidity_usd") or 0) for p in pools_now)
    largest = max((p.get("liquidity_usd") or 0) for p in pools_now) if pools_now else 0
    out["largest_pool_share"] = (largest / total) if total else None
    out["single_pool_dependency"] = bool(out["largest_pool_share"] is not None and out["largest_pool_share"] >= float(ctx.config.get("liquidity.single_pool_dependency_pct", 0.9)))
    # LP events
    out.update(lp_event_metrics(ctx, pools, as_of_ts))
    # migration: a pool created within 24h now holding the largest share while an older pool shrank
    if len(pools_now) >= 2:
        created = {p.pair_id: p.created_ts for p in pools.values()}
        newest = max(pools_now, key=lambda p: created.get(p["pair_id"]) or 0)
        if created.get(newest["pair_id"]) and as_of_ts - created[newest["pair_id"]] <= 86400 and newest.get("liquidity_usd") == largest and (out.get("liquidity_change_24h") or 0) < 0:
            out["liquidity_migration"] = True
        else:
            out["liquidity_migration"] = False
    else:
        out["liquidity_migration"] = False
    return out


def lp_event_metrics(ctx: IntelContext, pools: dict[str, PoolInfo], as_of_ts: int) -> dict[str, Any]:
    out: dict[str, Any] = {"lp_added_1h": None, "lp_removed_1h": None, "lp_added_24h": None, "lp_removed_24h": None, "large_lp_addition": False, "large_lp_removal": False}
    if not pools:
        return out
    ids = list(pools.keys())
    for w in ("1h", "24h"):
        since = as_of_ts - WINDOWS_SECONDS[w]
        rows = ctx.db.query(
            f"SELECT pair_id, sender, liquidity_delta FROM liquidity_events WHERE chain_id=? AND pair_id IN ({','.join('?' for _ in ids)}) AND ts>? AND ts<=?",
            (ctx.chain_id, *ids, since, as_of_ts),
        )
        added = 0.0
        removed = 0.0
        for r in rows:
            lbl = ctx.system_label(r["sender"]) or ""
            if lbl.startswith("hook:"):
                continue  # hook fee re-hypothecation is not LP intent
            d = float(r["liquidity_delta"])
            if d > 0:
                added += d
            else:
                removed += -d
        out[f"lp_added_{w}"] = added
        out[f"lp_removed_{w}"] = removed
    # relative to current in-range liquidity of the deepest pool
    ref = 0.0
    for pid in ids:
        st = latest_pool_state(ctx, pid, as_of_ts)
        if st:
            ref = max(ref, float(st["liquidity"]))
    if ref > 0:
        add_pct = float(ctx.config.get("liquidity.lp_addition_alert_pct", 0.30))
        rem_pct = float(ctx.config.get("liquidity.lp_removal_alert_pct", 0.15))
        out["large_lp_addition"] = (out["lp_added_1h"] or 0) / ref >= add_pct
        out["large_lp_removal"] = (out["lp_removed_1h"] or 0) / ref >= rem_pct
        out["lp_removed_1h_pct"] = (out["lp_removed_1h"] or 0) / ref
        out["lp_added_1h_pct"] = (out["lp_added_1h"] or 0) / ref
    return out


async def price_impact_estimates(ctx: IntelContext, token: str, pools: dict[str, PoolInfo], token_decimals: int, pricer: QuotePricer, sizes_usd: list[float] | None = None, price_usd: float | None = None) -> dict[str, Any]:
    """Exact quotes via V4Quoter where possible; constant-product approximation otherwise."""
    sizes = sizes_usd or [float(x) for x in ctx.config.get("liquidity.price_impact_trade_sizes_usd", [100, 1000, 5000, 20000])]
    out: dict[str, Any] = {"price_impact": {}, "price_impact_method": None, "quality_flags": []}
    if not pools:
        out["quality_flags"].append("no_pools")
        return out
    # deepest pool by latest swap liquidity
    best: tuple[PoolInfo, dict[str, Any]] | None = None
    for p in pools.values():
        st = latest_pool_state(ctx, p.pair_id)
        if st and (best is None or int(st["liquidity"]) > int(best[1]["liquidity"])):
            best = (p, st)
    if best is None:
        out["quality_flags"].append("no_pool_state")
        return out
    pool, st = best
    qdec = pricer.decimals(pool.quote_address)
    qusd, qflags = pricer.usd_price(pool.quote_address)
    out["quality_flags"].extend(qflags)
    if qdec is None or not qusd:
        out["quality_flags"].append("quote_unpriced")
        return out
    quoters = [q for q in [ctx.config.get("contracts.v4_quoter")] + list(ctx.config.get("contracts.v4_quoter_fallbacks", [])) if q]
    key = (pool.currency0, pool.currency1, pool.fee or 0, pool.tick_spacing or 0, pool.hooks or ZERO_ADDRESS)
    zero_for_one = not pool.token_is_currency0  # buying token with quote
    ref_amount = int(1.0 / qusd * 10 ** qdec)  # $1 of quote

    async def quote(amount_in: int) -> int | None:
        data = encode_call(V4_QUOTE_EXACT_INPUT_SINGLE, [(key, zero_for_one, amount_in, b"")])
        for q in quoters:
            try:
                o = await ctx.rpc.call(q, data)
                return int(decode(["uint256", "uint256"], o)[0])
            except Exception:
                continue
        return None

    ref_out = await quote(ref_amount)
    if ref_out:
        ref_rate = ref_out / ref_amount
        for usd in sizes:
            amt = int(usd / qusd * 10 ** qdec)
            got = await quote(amt)
            out["price_impact"][f"buy_{int(usd)}"] = (1.0 - (got / amt) / ref_rate) if got else None
        out["price_impact_method"] = "v4_quoter"
        out["price_impact_pool"] = pool.pair_id
        return out
    # fallback: constant product on virtual reserves (approximation)
    r0, r1 = virtual_reserves(int(st["liquidity"]), int(st["sqrt_price_x96"]))
    reserve_token, reserve_quote = (r0, r1) if pool.token_is_currency0 else (r1, r0)
    for usd in sizes:
        amt = usd / qusd * 10 ** qdec
        out["price_impact"][f"buy_{int(usd)}"] = cpmm_price_impact(reserve_quote, reserve_token, amt)
    out["price_impact_method"] = "cpmm_virtual_reserves_approx"
    out["price_impact_pool"] = pool.pair_id
    out["quality_flags"].append("price_impact_approx")
    return out
