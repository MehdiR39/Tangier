"""Uniswap v4 pool resolution and PoolManager event ingestion (Swap / ModifyLiquidity)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from intel.chain.constants import TOPIC_V4_INITIALIZE, TOPIC_V4_MODIFY_LIQUIDITY, TOPIC_V4_SWAP
from intel.chain.uniswap_v4 import PoolInitialize, decode_initialize, decode_modify_liquidity, decode_swap
from intel.context import IntelContext
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PoolInfo:
    pair_id: str
    token_address: str
    quote_address: str
    token_is_currency0: bool
    hooks: str | None
    fee: int | None
    tick_spacing: int | None
    created_block: int | None
    created_ts: int | None
    currency0: str
    currency1: str


def load_pools(ctx: IntelContext, token: str) -> dict[str, PoolInfo]:
    rows = ctx.db.query("SELECT * FROM pairs WHERE chain_id=? AND token_address=? AND currency0 IS NOT NULL", (ctx.chain_id, token.lower()))
    out: dict[str, PoolInfo] = {}
    for r in rows:
        out[r["pair_id"]] = PoolInfo(
            pair_id=r["pair_id"], token_address=token.lower(), quote_address=r["quote_address"],
            token_is_currency0=bool(r["token_is_currency0"]), hooks=r["hooks"], fee=r["fee"], tick_spacing=r["tick_spacing"],
            created_block=r["created_block"], created_ts=r["created_ts"], currency0=r["currency0"], currency1=r["currency1"],
        )
    return out


def store_pool_init(ctx: IntelContext, token: str, init: PoolInitialize, created_ts: int | None, source: str) -> PoolInfo:
    token = token.lower()
    token_is_c0 = init.currency0 == token
    quote = init.currency1 if token_is_c0 else init.currency0
    ts = now_ts()
    ctx.db.execute(
        "INSERT INTO pairs(chain_id, pair_id, token_address, quote_address, dex, version, hooks, fee, tick_spacing, currency0, currency1, token_is_currency0, created_ts, created_block, source, raw_json, first_seen_ts, updated_ts) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(chain_id, pair_id) DO UPDATE SET "
        "quote_address=excluded.quote_address, hooks=excluded.hooks, fee=excluded.fee, tick_spacing=excluded.tick_spacing, currency0=excluded.currency0, currency1=excluded.currency1, "
        "token_is_currency0=excluded.token_is_currency0, created_block=excluded.created_block, created_ts=COALESCE(excluded.created_ts, pairs.created_ts), dex=COALESCE(pairs.dex,'uniswap'), version=COALESCE(pairs.version,'v4'), updated_ts=excluded.updated_ts",
        (
            ctx.chain_id, init.pool_id, token, quote, "uniswap", "v4", init.hooks, init.fee, init.tick_spacing, init.currency0, init.currency1, int(token_is_c0),
            created_ts, init.block_number, source, json.dumps({"sqrt_price_x96": str(init.sqrt_price_x96), "tick": init.tick, "tx": init.tx_hash}), ts, ts,
        ),
    )
    return PoolInfo(init.pool_id, token, quote, token_is_c0, init.hooks, init.fee, init.tick_spacing, init.block_number, created_ts, init.currency0, init.currency1)


async def resolve_pool(ctx: IntelContext, token: str, pair_id: str, *, from_block: int = 0, created_ts: int | None = None) -> PoolInfo | None:
    """Find the Initialize event for ``pair_id``.

    Order: (1) narrow RPC window around the DexScreener creation timestamp (cheap, exact),
    (2) Blockscout v1 logs with topic filter (quota-aware), (3) bounded full RPC scan.
    """
    token = token.lower()
    pm = ctx.pool_manager
    logs: list[dict[str, Any]] = []
    if created_ts is None:
        row = ctx.db.query_one("SELECT created_ts FROM pairs WHERE chain_id=? AND pair_id=?", (ctx.chain_id, pair_id))
        created_ts = int(row["created_ts"]) if row and row["created_ts"] else None
    if created_ts:
        try:
            head = await ctx.rpc.block_number()
            approx = await ctx.rpc.block_by_timestamp(int(created_ts) - 30, head=head)
            window = 40_000
            logs = await ctx.rpc.get_logs(address=pm, topics=[TOPIC_V4_INITIALIZE, pair_id], from_block=max(0, approx - 2_000), to_block=min(head, approx + window))
            if not logs:
                logs = await ctx.rpc.get_logs(address=pm, topics=[TOPIC_V4_INITIALIZE, pair_id], from_block=max(0, approx - window), to_block=min(head, approx + 4 * window))
        except Exception as exc:
            log.info("rpc windowed Initialize lookup failed for %s: %s", pair_id[:10], exc)
    if not logs:
        try:
            logs = await ctx.blockscout.logs(pm, TOPIC_V4_INITIALIZE, topic1=pair_id, from_block=from_block)
        except Exception as exc:
            log.info("blockscout Initialize lookup failed for %s: %s", pair_id[:10], exc)
    if not logs:
        try:
            head = await ctx.rpc.block_number()
            start = max(from_block, head - int(ctx.config.get("engine.backfill_max_blocks", 4_500_000)))
            async for _a, _b, chunk in ctx.rpc.iter_logs(address=pm, topics=[TOPIC_V4_INITIALIZE, pair_id], from_block=start, to_block=head, chunk=100_000):
                if chunk:
                    logs = chunk
                    break
        except Exception as exc:
            log.warning("rpc Initialize scan failed for %s: %s", pair_id[:10], exc)
    if not logs:
        return None
    init = decode_initialize(logs[0])
    if token not in (init.currency0, init.currency1):
        log.warning("pool %s does not contain token %s", pair_id[:10], token)
        return None
    created_ts = None
    if logs[0].get("timeStamp"):
        created_ts = int(logs[0]["timeStamp"], 16) if str(logs[0]["timeStamp"]).startswith("0x") else int(logs[0]["timeStamp"])
    else:
        try:
            created_ts = await ctx.rpc.block_timestamp(init.block_number)
        except Exception:
            created_ts = None
    return store_pool_init(ctx, token, init, created_ts, "blockscout" if logs[0].get("timeStamp") else "rpc")


async def ensure_pools(ctx: IntelContext, token: str, pair_ids: list[str], created_ts: dict[str, int | None] | None = None) -> dict[str, PoolInfo]:
    pools = load_pools(ctx, token)
    for pid in pair_ids:
        pid = pid.lower()
        if pid in pools or len(pid) != 66:
            continue
        info = await resolve_pool(ctx, token, pid, created_ts=(created_ts or {}).get(pid))
        if info:
            pools[pid] = info
    return pools


async def ingest_pool_events(ctx: IntelContext, token: str, pools: dict[str, PoolInfo], to_block: int | None = None, *, from_block: int | None = None, update_cursor: bool = True) -> dict[str, int]:
    """Ingest Swap + ModifyLiquidity events for the token's pools since the last cursor.

    ``update_cursor=False`` ingests an explicit historical range (backward backfill) without
    moving the forward cursor.
    """
    token = token.lower()
    if not pools:
        return {"swaps": 0, "liquidity": 0}
    head = to_block if to_block is not None else await ctx.rpc.block_number()
    cursor_name = f"pools:{token}"
    if from_block is not None:
        start = int(from_block)
    else:
        cur = ctx.db.cursor_get(cursor_name)
        if cur is None:
            earliest = min((p.created_block for p in pools.values() if p.created_block), default=None)
            lookback = int(ctx.config.get("engine.trade_lookback_blocks", 900_000))
            start = max(earliest or 0, head - lookback)
        else:
            start = int(cur) + 1
    if start > head:
        return {"swaps": 0, "liquidity": 0}
    pool_ids = list(pools.keys())
    chunk = int(ctx.config.get("engine.rpc_log_chunk_blocks", 20000))
    n_swaps = n_liq = 0
    async for a, b, logs in ctx.rpc.iter_logs(address=ctx.pool_manager, topics=[[TOPIC_V4_SWAP, TOPIC_V4_MODIFY_LIQUIDITY], pool_ids], from_block=start, to_block=head, chunk=chunk):
        if logs:
            blocks = sorted({int(l["blockNumber"], 16) for l in logs})
            ts_map = await ctx.rpc.block_timestamps(blocks)
            swap_rows: list[dict[str, Any]] = []
            liq_rows: list[dict[str, Any]] = []
            for lg in logs:
                t0 = lg["topics"][0].lower()
                if t0 == TOPIC_V4_SWAP:
                    ev = decode_swap(lg)
                    swap_rows.append({
                        "chain_id": ctx.chain_id, "tx_hash": ev.tx_hash, "log_index": ev.log_index, "block_number": ev.block_number, "ts": ts_map.get(ev.block_number),
                        "pair_id": ev.pool_id, "sender": ev.sender, "amount0": str(ev.amount0), "amount1": str(ev.amount1),
                        "sqrt_price_x96": str(ev.sqrt_price_x96), "liquidity": str(ev.liquidity), "tick": ev.tick, "fee": ev.fee, "source": "rpc",
                    })
                elif t0 == TOPIC_V4_MODIFY_LIQUIDITY:
                    ev2 = decode_modify_liquidity(lg)
                    liq_rows.append({
                        "chain_id": ctx.chain_id, "tx_hash": ev2.tx_hash, "log_index": ev2.log_index, "block_number": ev2.block_number, "ts": ts_map.get(ev2.block_number),
                        "pair_id": ev2.pool_id, "sender": ev2.sender, "tick_lower": ev2.tick_lower, "tick_upper": ev2.tick_upper,
                        "liquidity_delta": str(ev2.liquidity_delta), "salt": ev2.salt, "source": "rpc",
                    })
            with ctx.db.transaction():
                n_swaps += ctx.db.insert_many("swap_events", swap_rows)
                n_liq += ctx.db.insert_many("liquidity_events", liq_rows)
                if update_cursor:
                    ctx.db.cursor_set(cursor_name, b, now_ts())
        elif update_cursor:
            ctx.db.cursor_set(cursor_name, b, now_ts())
    log.info("pool events ingested token=%s swaps=%d liquidity=%d range=%d-%d", token[:10], n_swaps, n_liq, start, head)
    return {"swaps": n_swaps, "liquidity": n_liq, "from_block": start, "to_block": head}


def latest_pool_state(ctx: IntelContext, pair_id: str, as_of_ts: int | None = None) -> dict[str, Any] | None:
    sql = "SELECT block_number, ts, sqrt_price_x96, liquidity, tick FROM swap_events WHERE chain_id=? AND pair_id=?"
    params: list[Any] = [ctx.chain_id, pair_id]
    if as_of_ts is not None:
        sql += " AND ts<=?"
        params.append(as_of_ts)
    sql += " ORDER BY block_number DESC, log_index DESC LIMIT 1"
    row = ctx.db.query_one(sql, params)
    return dict(row) if row else None
