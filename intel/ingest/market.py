"""DexScreener market snapshots -> pairs / pair_snapshots / token_snapshots (append-only)."""
from __future__ import annotations

import json
import logging
from typing import Any

from intel.context import IntelContext
from intel.metrics.pricing import QuotePricer
from intel.providers.dexscreener import normalize_pair
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)
SOURCE = "dexscreener"


def _version_from_labels(labels: list[str]) -> str | None:
    for l in labels or []:
        if l.lower().startswith("v"):
            return l.lower()
    return None


def upsert_pair_from_dex(ctx: IntelContext, token: str, np: dict[str, Any], ts: int) -> None:
    ctx.db.execute(
        "INSERT INTO pairs(chain_id, pair_id, token_address, quote_address, quote_symbol, dex, version, created_ts, source, raw_json, first_seen_ts, updated_ts) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(chain_id, pair_id) DO UPDATE SET "
        "quote_address=COALESCE(pairs.quote_address, excluded.quote_address), quote_symbol=COALESCE(excluded.quote_symbol, pairs.quote_symbol), "
        "dex=COALESCE(excluded.dex, pairs.dex), version=COALESCE(excluded.version, pairs.version), created_ts=COALESCE(pairs.created_ts, excluded.created_ts), updated_ts=excluded.updated_ts",
        (
            ctx.chain_id, np["pair_id"], token, np["quote_address"] or None, np["quote_symbol"], np["dex"], _version_from_labels(np["labels"]),
            np["pair_created_ts"], SOURCE, json.dumps({"url": np["url"], "labels": np["labels"]}), ts, ts,
        ),
    )


def insert_pair_snapshot(ctx: IntelContext, token: str, np: dict[str, Any], ts: int, flags: list[str]) -> int | None:
    row = {
        "ts": ts, "chain_id": ctx.chain_id, "pair_id": np["pair_id"], "token_address": token, "source": SOURCE, "block_number": None,
        "price_usd": np["price_usd"], "price_native": np["price_native"],
        "liquidity_usd": np["liquidity_usd"], "liquidity_base": np["liquidity_base"], "liquidity_quote": np["liquidity_quote"],
        "fdv": np["fdv"], "market_cap": np["market_cap"],
        "vol_5m": np["vol_5m"], "vol_1h": np["vol_1h"], "vol_6h": np["vol_6h"], "vol_24h": np["vol_24h"],
        "buys_5m": np["buys_5m"], "sells_5m": np["sells_5m"], "buys_1h": np["buys_1h"], "sells_1h": np["sells_1h"],
        "buys_6h": np["buys_6h"], "sells_6h": np["sells_6h"], "buys_24h": np["buys_24h"], "sells_24h": np["sells_24h"],
        "pc_5m": np["pc_5m"], "pc_1h": np["pc_1h"], "pc_6h": np["pc_6h"], "pc_24h": np["pc_24h"],
        "quality_flags": json.dumps(flags), "raw_json": None,
    }
    return ctx.db.insert("pair_snapshots", row)


def aggregate_pairs(pairs: list[dict[str, Any]], meaningful_min_liq: float) -> dict[str, Any]:
    """Liquidity-weighted aggregation across a token's pools."""
    if not pairs:
        return {"price_usd": None, "liquidity_usd": None, "volume_24h": None, "fdv": None, "market_cap": None, "primary_pair": None, "n_pools": 0, "n_meaningful_pools": 0, "quality_flags": ["no_pairs"]}
    flags: list[str] = []
    with_liq = [p for p in pairs if p.get("liquidity_usd") is not None]
    primary = max(with_liq, key=lambda p: p["liquidity_usd"]) if with_liq else pairs[0]
    if not with_liq:
        flags.append("liquidity_missing")
    liq_total = sum(p["liquidity_usd"] for p in with_liq) if with_liq else None
    vol = [p["vol_24h"] for p in pairs if p.get("vol_24h") is not None]
    vol_total = sum(vol) if vol else None
    meaningful = [p for p in with_liq if p["liquidity_usd"] >= meaningful_min_liq]
    # liquidity-weighted price across meaningful pools (fallback primary)
    priced = [p for p in meaningful if p.get("price_usd")]
    if priced:
        w = sum(p["liquidity_usd"] for p in priced)
        price = sum(p["price_usd"] * p["liquidity_usd"] for p in priced) / w if w else primary.get("price_usd")
    else:
        price = primary.get("price_usd")
        if price is None:
            flags.append("price_missing")
    if primary.get("market_cap") is None:
        flags.append("market_cap_missing")
    largest_share = (primary["liquidity_usd"] / liq_total) if (liq_total and primary.get("liquidity_usd") is not None) else None
    return {
        "price_usd": price,
        "liquidity_usd": liq_total,
        "volume_24h": vol_total,
        "fdv": primary.get("fdv"),
        "market_cap": primary.get("market_cap"),
        "primary_pair": primary["pair_id"],
        "primary_quote": primary.get("quote_address"),
        "primary_quote_symbol": primary.get("quote_symbol"),
        "n_pools": len(pairs),
        "n_meaningful_pools": len(meaningful),
        "largest_pool_share": largest_share,
        "pair_created_ts": min((p["pair_created_ts"] for p in pairs if p.get("pair_created_ts")), default=None),
        "quality_flags": flags,
    }


async def snapshot_token_market(ctx: IntelContext, token: str, *, pricer: QuotePricer | None = None, ts: int | None = None, pairs_raw: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """Fetch (or reuse) DexScreener pairs for ``token`` and persist snapshots. Returns aggregate."""
    token = token.lower()
    ts = ts or now_ts()
    if pairs_raw is None:
        pairs_raw = await ctx.dex.token_pairs(token)
    norm = [normalize_pair(p) for p in pairs_raw]
    norm = [p for p in norm if p["pair_id"] and p["base_address"] == token]
    min_liq = float(ctx.config.get("liquidity.meaningful_pool_min_liquidity_usd", 5000.0))
    agg = aggregate_pairs(norm, min_liq)
    with ctx.db.transaction():
        for np in norm:
            upsert_pair_from_dex(ctx, token, np, ts)
            flags = []
            if np["liquidity_usd"] is None:
                flags.append("liquidity_missing")
            insert_pair_snapshot(ctx, token, np, ts, flags)
            if pricer is not None and np.get("quote_address"):
                # DexScreener priceNative = quote per token; implied quote USD = price_usd / price_native
                if np["price_usd"] and np["price_native"]:
                    pricer.set_current(np["quote_address"], np["price_usd"] / np["price_native"])
        ctx.db.insert(
            "token_snapshots",
            {
                "ts": ts, "chain_id": ctx.chain_id, "token_address": token, "source": SOURCE, "block_number": None,
                "price_usd": agg["price_usd"], "price_native": None, "market_cap": agg["market_cap"], "fdv": agg["fdv"],
                "circulating_supply": None, "total_supply": None,
                "liquidity_usd": agg["liquidity_usd"], "volume_24h": agg["volume_24h"], "holder_count": None,
                "quality_flags": json.dumps(agg["quality_flags"]),
                "raw_json": json.dumps({"primary_pair": agg["primary_pair"], "n_pools": agg["n_pools"], "largest_pool_share": agg["largest_pool_share"]}),
            },
        )
    agg["pairs"] = norm
    agg["ts"] = ts
    return agg


async def snapshot_quote_assets(ctx: IntelContext, quote_addresses: list[str], pricer: QuotePricer, ts: int | None = None) -> None:
    """Snapshot USD prices of non-stable quote assets (tokenised stocks, WETH) so historical
    trades can be priced point-in-time later."""
    ts = ts or now_ts()
    todo = []
    for q in dict.fromkeys(a.lower() for a in quote_addresses if a):
        meta = ctx.quote_asset(q)
        if meta and meta.get("kind") == "stable":
            continue
        todo.append(q)
    if not todo:
        return
    try:
        pairs = await ctx.dex.tokens(todo)
    except Exception as exc:
        log.warning("quote asset snapshot failed: %s", exc)
        return
    best: dict[str, dict[str, Any]] = {}
    for p in pairs:
        np = normalize_pair(p)
        base = np["base_address"]
        if base in todo and np.get("price_usd") and (base not in best or (np.get("liquidity_usd") or 0) > (best[base].get("liquidity_usd") or 0)):
            best[base] = np
    with ctx.db.transaction():
        for base, np in best.items():
            pricer.set_current(base, np["price_usd"])
            ctx.db.insert(
                "token_snapshots",
                {
                    "ts": ts, "chain_id": ctx.chain_id, "token_address": base, "source": SOURCE, "block_number": None,
                    "price_usd": np["price_usd"], "price_native": np["price_native"], "market_cap": np["market_cap"], "fdv": np["fdv"],
                    "circulating_supply": None, "total_supply": None, "liquidity_usd": np["liquidity_usd"], "volume_24h": np["vol_24h"], "holder_count": None,
                    "quality_flags": json.dumps(["quote_asset"]), "raw_json": None,
                },
            )
