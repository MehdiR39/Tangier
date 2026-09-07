"""Point-in-time feature builder: everything the scorer needs for one token at ``as_of_ts``.

Only observations with ``ts <= as_of_ts`` are read, so the same function serves the
live engines (as_of = now) and the backtester (historical as_of). ``live=True`` unlocks
the full replayed holder table for exact concentration / new-lost holder counts.
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any

from intel.context import IntelContext
from intel.ingest.pools import PoolInfo, load_pools
from intel.ingest.security import latest_security
from intel.metrics import clustering, concentration as conc, holders as hmod, liquidity as lmod, market as mmod, narrative as nmod, smart_money as smmod, trading_quality as tq, whales as wmod
from intel.metrics.launch import compute_launch_profile, launch_history_complete
from intel.metrics.pricing import QuotePricer
from intel.utils.timeutil import WINDOWS_SECONDS, age_seconds

log = logging.getLogger(__name__)


def token_row(ctx: IntelContext, token: str) -> dict[str, Any] | None:
    r = ctx.db.query_one("SELECT * FROM tokens WHERE chain_id=? AND address=?", (ctx.chain_id, token.lower()))
    return dict(r) if r else None


def latest_launch_profile(ctx: IntelContext, token: str, as_of_ts: int) -> dict[str, Any] | None:
    r = ctx.db.query_one("SELECT * FROM launch_profiles WHERE chain_id=? AND token_address=? AND ts<=? ORDER BY ts DESC LIMIT 1", (ctx.chain_id, token.lower(), as_of_ts))
    return dict(r) if r else None


def latest_token_snapshot(ctx: IntelContext, token: str, as_of_ts: int, max_age: int = 1800) -> dict[str, Any] | None:
    r = ctx.db.query_one("SELECT * FROM token_snapshots WHERE chain_id=? AND token_address=? AND source='dexscreener' AND ts<=? ORDER BY ts DESC LIMIT 1", (ctx.chain_id, token.lower(), as_of_ts))
    if r is None or as_of_ts - int(r["ts"]) > max_age:
        return None
    return dict(r)


def latest_pair_rows(ctx: IntelContext, token: str, as_of_ts: int) -> list[dict[str, Any]]:
    t = ctx.db.scalar("SELECT MAX(ts) FROM pair_snapshots WHERE chain_id=? AND token_address=? AND ts<=?", (ctx.chain_id, token.lower(), as_of_ts))
    if t is None:
        return []
    rows = ctx.db.query(
        "SELECT ps.*, p.quote_symbol AS q_symbol, p.raw_json AS pair_raw FROM pair_snapshots ps LEFT JOIN pairs p ON p.chain_id=ps.chain_id AND p.pair_id=ps.pair_id WHERE ps.chain_id=? AND ps.token_address=? AND ps.ts=?",
        (ctx.chain_id, token.lower(), t),
    )
    return [dict(r) for r in rows]


async def build_token_metrics(ctx: IntelContext, token: str, as_of_ts: int, *, pricer: QuotePricer, live: bool = True, pools: dict[str, PoolInfo] | None = None, deep: bool = True, dex_pairs_norm: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    token = token.lower()
    flags: list[str] = []
    trow = token_row(ctx, token) or {}
    decimals = int(trow.get("decimals") or 18)
    total_supply_raw = int(trow["total_supply"]) if trow.get("total_supply") else None
    total_supply_float = (total_supply_raw / 10 ** decimals) if total_supply_raw else None
    pools = pools if pools is not None else load_pools(ctx, token)

    # ---- market ---------------------------------------------------------- #
    snap = latest_token_snapshot(ctx, token, as_of_ts)
    ret = mmod.returns(ctx, token, as_of_ts)
    flags += ret.get("quality_flags", [])
    price = ret.get("price_usd") or (snap or {}).get("price_usd")
    market_cap = (snap or {}).get("market_cap")
    fdv = (snap or {}).get("fdv")
    if market_cap is None and price and total_supply_float:
        market_cap = price * total_supply_float
        flags.append("mc_from_total_supply")
    if fdv is None and price and total_supply_float:
        fdv = price * total_supply_float
    liquidity_usd = (snap or {}).get("liquidity_usd")
    volume_24h = (snap or {}).get("volume_24h")
    if snap is None:
        flags.append("no_recent_market_snapshot")
    created_candidates = [c for c in (trow.get("creation_ts"), min((p.created_ts for p in pools.values() if p.created_ts), default=None)) if c]
    first_transfer_ts = ctx.db.scalar("SELECT MIN(ts) FROM transfers WHERE chain_id=? AND token_address=?", (ctx.chain_id, token))
    if first_transfer_ts:
        created_candidates.append(int(first_transfer_ts))
    created_ts = min(created_candidates) if created_candidates else None
    age = age_seconds(created_ts, as_of_ts)
    ath_info = mmod.ath(ctx, token, as_of_ts, total_supply_float)

    # ---- launch / asymmetry ----------------------------------------------- #
    if deep:
        launch = compute_launch_profile(ctx, token, as_of_ts, total_supply_float, ath_info, persist=live)
    else:
        lp = latest_launch_profile(ctx, token, as_of_ts)
        launch = {"raw_first_trade_price_usd": lp.get("raw_first_trade_price_usd"), "fmm_reached": bool(lp.get("fmm_reached")), "fmm_price_usd": lp.get("fmm_price_usd"), "fmm_market_cap": lp.get("fmm_market_cap"), "fmm_ts": lp.get("fmm_ts"), "raw_first_trade_ts": lp.get("raw_first_trade_ts"), "quality_flags": [], "evidence": {}} if lp else {"fmm_reached": False, "quality_flags": ["no_launch_profile"], "evidence": {}}
    flags += launch.get("quality_flags", [])
    asym = mmod.asymmetry_multiples(price, market_cap, launch.get("raw_first_trade_price_usd"), launch.get("fmm_price_usd") if launch.get("fmm_reached") else None, launch.get("fmm_market_cap"), ath_info.get("ath_price"))

    # ---- holders ---------------------------------------------------------- #
    # Replay-derived holder metrics are exact only with complete transfer history.
    history_complete = launch_history_complete(ctx, token)
    if not history_complete:
        flags.append("partial_transfer_history")
    hcfg = ctx.config.section("holders")
    series = hmod.holder_series(ctx, token, as_of_ts, prefer_replay=history_complete)
    growth = hmod.holder_growth(series, as_of_ts, hcfg.get("growth_windows"), hcfg.get("acceleration_window", "1h"))
    flags += growth.get("quality_flags", [])
    newlost = hmod.new_and_lost_holders(ctx, token, as_of_ts) if (live and history_complete) else {}
    divs = hmod.divergences(ret, growth, price_move=float(hcfg.get("divergence_price_move", 0.05)), holder_move=float(hcfg.get("divergence_holder_move", 0.03)))

    # ---- concentration / clusters ----------------------------------------- #
    exclude_kinds = set(ctx.config.get("concentration.exclude_kinds", []))
    use_full_replay = live and history_complete
    prefer_src = "rpc_replay" if history_complete else "blockscout"
    con = conc.concentration_at(ctx, token, as_of_ts, total_supply_raw, live=use_full_replay, exclude_kinds=exclude_kinds, prefer=prefer_src)
    flags += con.get("quality_flags", [])
    con_changes = conc.concentration_changes(ctx, token, as_of_ts, total_supply_raw, con, exclude_kinds, ctx.config.get("concentration.change_windows"), prefer=prefer_src)
    holders_list = conc.current_holder_balances(ctx, token, exclude_kinds) if use_full_replay else conc.snapshot_holder_balances(ctx, token, as_of_ts, exclude_kinds, prefer=prefer_src)[0]
    excluded_bal = sum(b for _a, b, ex in holders_list if ex)
    econ_supply = (total_supply_raw - excluded_bal) if total_supply_raw else sum(b for _a, b, ex in holders_list if not ex)
    clusters_info: dict[str, Any] = {}
    ccfg = ctx.config.section("clustering")
    if deep and holders_list:
        top_addrs = {a for a, _b, ex in sorted(holders_list, key=lambda x: -x[1]) if not ex}
        top_addrs = set(list(top_addrs)[:150])
        traders = {r["trader"] for r in ctx.db.query("SELECT DISTINCT trader FROM trades WHERE chain_id=? AND token_address=? AND ts>? AND ts<=? LIMIT 200", (ctx.chain_id, token, as_of_ts - 86400, as_of_ts))}
        clusters = clustering.cluster_token(ctx, token, as_of_ts, top_addrs | traders, persist=live)
        clusters_info = clustering.effective_concentration(holders_list, econ_supply, clusters, float(ccfg.get("high_confidence", 0.75)))
        clusters_info["n_clusters"] = len(clusters)
        clusters_info["top_clusters"] = [{"size": len(c.members), "confidence": round(c.confidence, 2), "evidence": c.evidence.get("edge_kinds")} for c in clusters[:5]]
    else:
        clusters_info = {"effective_top10_pct": None, "effective_top20_pct": None, "largest_cluster_pct": None, "n_high_confidence_clusters": None}

    # ---- whales ----------------------------------------------------------- #
    wcfg = ctx.config.section("whales")
    whales_list = wmod.define_whales(holders_list, econ_supply, price, decimals, wcfg) if holders_list else []
    wflows = wmod.whale_flows(ctx, token, whales_list, as_of_ts, decimals=decimals, price_usd=price, econ_supply=econ_supply, windows=wcfg.get("flow_windows"), persist=live) if whales_list else {"n_whales": 0, "wallets": [], "number_accumulating": 0, "number_distributing": 0}
    for w in ("5m", "1h", "6h", "24h"):
        wflows.setdefault(f"whale_netflow_{w}", None)
    wflows.setdefault("top10_netflow_1h", None)
    wflows.setdefault("top20_netflow_1h", None)
    wflows.setdefault("top10_netflow_24h", None)
    wflows.setdefault("top20_netflow_24h", None)
    top_distributing = wmod.top_wallet_distribution(wflows.get("wallets", []), "6h", float(ctx.config.get("alerts.top_wallet_distribution_pct", 0.20)))

    # ---- trading quality -------------------------------------------------- #
    tcfg = ctx.config.section("trading_quality")
    dex_txns_24h = None
    dex_txns_1h = None
    if snap is not None:
        pr = latest_pair_rows(ctx, token, as_of_ts)
        dex_txns_24h = sum((r.get("buys_24h") or 0) + (r.get("sells_24h") or 0) for r in pr) or None
        dex_txns_1h = sum((r.get("buys_1h") or 0) + (r.get("sells_1h") or 0) for r in pr) or None
    quality: dict[str, Any] = {}
    coverage_start = ctx.db.scalar("SELECT MIN(ts) FROM transfers WHERE chain_id=? AND token_address=?", (ctx.chain_id, token))
    for w in ("1h", "24h"):
        since = as_of_ts - WINDOWS_SECONDS[w]
        covered = coverage_start is not None and int(coverage_start) <= since
        trades = tq.load_trades(ctx, token, since, as_of_ts)
        # new/repeat buyers need the wallet's full trade history for this token
        first_ts = tq.first_trade_timestamps(ctx, token, {t["trader"] for t in trades}, as_of_ts) if (trades and history_complete) else None
        dex_txns = (dex_txns_24h if w == "24h" else dex_txns_1h) if covered else None
        quality[w] = tq.trading_quality(trades, first_trade_ts=first_ts, window_start=since, params=tcfg, dex_txns=dex_txns)
        if not covered:
            quality[w]["quality_flags"].append(f"trade_window_{w}_partial")
            flags.append(f"trade_window_{w}_partial")
    recent_buyers = [r["trader"] for r in ctx.db.query("SELECT trader, SUM(usd_value) AS v FROM trades WHERE chain_id=? AND token_address=? AND side='BUY' AND ts>? AND ts<=? GROUP BY trader ORDER BY v DESC LIMIT 40", (ctx.chain_id, token, as_of_ts - 86400, as_of_ts))]

    # ---- liquidity -------------------------------------------------------- #
    liq = lmod.liquidity_metrics(ctx, token, as_of_ts, pools, market_cap=market_cap, volume_24h=volume_24h)
    flags += liq.get("quality_flags", [])
    impact: dict[str, Any] = {"price_impact": {}, "price_impact_method": None}
    if deep and live:
        try:
            impact = await lmod.price_impact_estimates(ctx, token, pools, decimals, pricer, price_usd=price)
            flags += impact.get("quality_flags", [])
        except Exception as exc:
            log.info("price impact failed %s: %s", token[:10], exc)

    # ---- security / narrative / smart money ------------------------------- #
    sec = latest_security(ctx, token, as_of_ts)
    if sec is None:
        flags.append("security_unknown")
    pairs_norm = dex_pairs_norm or []
    if not pairs_norm and snap is not None:
        for r in latest_pair_rows(ctx, token, as_of_ts):
            raw = json.loads(r["pair_raw"]) if r.get("pair_raw") else {}
            pairs_norm.append({"websites": [], "socials": [], "image_url": None, "boosts_active": None, "quote_symbol": r.get("q_symbol"), "url": raw.get("url")})
    primary_quote_symbol = None
    if snap is not None:
        try:
            primary_pair = (json.loads(snap.get("raw_json") or "{}") or {}).get("primary_pair")
            primary_quote_symbol = ctx.db.scalar("SELECT quote_symbol FROM pairs WHERE chain_id=? AND pair_id=?", (ctx.chain_id, primary_pair)) if primary_pair else None
        except Exception:
            primary_quote_symbol = None
    narrative, narrative_ev = nmod.narrative_score(pairs_norm, quote_symbol=primary_quote_symbol, age_seconds=age)
    smcfg = ctx.config.section("smart_money")
    sm = smmod.token_smart_money(ctx, token, as_of_ts, recent_buyers, smcfg) if deep else {"smart_money_score": None, "smart_money_status": "UNKNOWN", "n_scored": 0, "n_unknown": 0, "smart_wallets": []}

    m: dict[str, Any] = {
        "token": token, "as_of_ts": as_of_ts, "symbol": trow.get("symbol"), "name": trow.get("name"), "decimals": decimals, "launchpad": trow.get("launchpad"),
        "total_supply": total_supply_float, "circulating_supply": None, "created_ts": created_ts, "token_age_seconds": age,
        "price_usd": price, "price_source": ret.get("price_source"), "market_cap": market_cap, "fdv": fdv, "liquidity_usd": liquidity_usd, "volume_24h": volume_24h,
        "returns": {k: v for k, v in ret.items() if k.startswith("return_")},
        "ath": ath_info, "launch": launch, "asymmetry": asym,
        "holders": {**growth, **newlost, "divergences": divs},
        "concentration": {**con, **con_changes, "econ_supply_float": econ_supply / 10 ** decimals if econ_supply else None},
        "clusters": clusters_info,
        "whales": {k: v for k, v in wflows.items() if k != "wallets"}, "whale_wallets": wflows.get("wallets", [])[:20], "top_wallet_distribution": top_distributing,
        "trading_quality": quality, "organic_volume_score": quality.get("24h", {}).get("organic_volume_score"),
        "liquidity": liq, "price_impact": impact.get("price_impact", {}), "price_impact_method": impact.get("price_impact_method"),
        "security": sec, "narrative": {"score": narrative, "evidence": narrative_ev}, "smart_money": sm,
        "quality_flags": sorted(set(flags)),
    }
    return m
