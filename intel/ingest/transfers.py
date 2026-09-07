"""ERC-20 Transfer ingestion (RPC ground truth) with incremental balance replay.

Idempotent: transfers are keyed by (tx_hash, log_index); a cursor per token records the
last fully ingested block. Balances in ``holders`` are replayed from transfers so the
holder distribution at *any* historical block can be reconstructed. During ingestion a
``holder_count_snapshots`` row (source ``rpc_replay``) is emitted every
``snapshot_interval_blocks`` so backtests never use holder counts from the future.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from intel.chain.constants import TOPIC_TRANSFER
from intel.context import IntelContext
from intel.utils.abi import topic_to_address
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)

SNAPSHOT_INTERVAL_BLOCKS = 6000  # ~10 minutes at 0.1s blocks


class BalanceBook:
    """In-memory replayed balances for one token."""

    def __init__(self, ctx: IntelContext, token: str) -> None:
        self.ctx = ctx
        self.token = token.lower()
        self.balances: dict[str, int] = {}
        self.first_seen: dict[str, tuple[int, int | None]] = {}
        self.dirty: set[str] = set()
        self._load()

    def _load(self) -> None:
        rows = self.ctx.db.query("SELECT address, balance, first_seen_block, first_seen_ts FROM holders WHERE chain_id=? AND token_address=?", (self.ctx.chain_id, self.token))
        for r in rows:
            self.balances[r["address"]] = int(r["balance"])
            self.first_seen[r["address"]] = (r["first_seen_block"] or 0, r["first_seen_ts"])

    def apply(self, frm: str, to: str, value: int, block: int, ts: int | None) -> None:
        if value == 0 and frm == to:
            return
        if frm != "0x0000000000000000000000000000000000000000":
            self.balances[frm] = self.balances.get(frm, 0) - value
            self.dirty.add(frm)
            self.first_seen.setdefault(frm, (block, ts))
        if to != "0x0000000000000000000000000000000000000000":
            self.balances[to] = self.balances.get(to, 0) + value
            self.dirty.add(to)
            self.first_seen.setdefault(to, (block, ts))

    def holder_counts(self, min_balance: int = 1) -> tuple[int, int]:
        total = 0
        ex_system = 0
        for a, b in self.balances.items():
            if b >= min_balance:
                total += 1
                if not self.ctx.is_system(a):
                    ex_system += 1
        return total, ex_system

    def flush(self, block: int, ts: int | None) -> int:
        if not self.dirty:
            return 0
        rows = []
        for a in self.dirty:
            fs = self.first_seen.get(a, (block, ts))
            label = self.ctx.system_label(a)
            rows.append((self.ctx.chain_id, self.token, a, str(self.balances.get(a, 0)), fs[0], fs[1], block, ts, int(label is not None), label))
        self.ctx.db.executemany(
            "INSERT INTO holders(chain_id, token_address, address, balance, first_seen_block, first_seen_ts, last_change_block, last_change_ts, is_system, system_label) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(chain_id, token_address, address) DO UPDATE SET balance=excluded.balance, "
            "last_change_block=excluded.last_change_block, last_change_ts=excluded.last_change_ts, is_system=excluded.is_system, system_label=excluded.system_label",
            rows,
        )
        n = len(self.dirty)
        self.dirty.clear()
        return n


def _decode_transfer(lg: dict[str, Any]) -> tuple[str, str, int] | None:
    topics = lg.get("topics") or []
    if len(topics) < 3:
        return None  # ERC-721 style or malformed
    data = lg.get("data") or "0x"
    if len(data) < 66:
        return None
    return topic_to_address(topics[1]), topic_to_address(topics[2]), int(data[2:66], 16)


async def ingest_transfers(ctx: IntelContext, token: str, *, to_block: int | None = None, from_block: int | None = None, min_balance_units: int = 1) -> dict[str, Any]:
    token = token.lower()
    head = to_block if to_block is not None else await ctx.rpc.block_number()
    cursor_name = f"transfers:{token}"
    cur = ctx.db.cursor_get(cursor_name)
    if from_block is not None and cur is None:
        start = from_block
    elif cur is not None:
        start = int(cur) + 1
    else:
        tok = ctx.db.query_one("SELECT creation_block FROM tokens WHERE chain_id=? AND address=?", (ctx.chain_id, token))
        creation = tok["creation_block"] if tok and tok["creation_block"] else None
        lookback = int(ctx.config.get("engine.backfill_max_blocks", 4_500_000))
        start = max(creation or 0, head - lookback)
    if start > head:
        return {"transfers": 0, "from_block": start, "to_block": head}
    if cur is None and ctx.db.cursor_get(f"transfers_fwd_start:{token}") is None:
        ctx.db.cursor_set(f"transfers_fwd_start:{token}", start, now_ts())  # where forward history begins
    book = BalanceBook(ctx, token)
    chunk = int(ctx.config.get("engine.rpc_log_chunk_blocks", 20000))
    n_rows = 0
    next_snapshot = (start // SNAPSHOT_INTERVAL_BLOCKS + 1) * SNAPSHOT_INTERVAL_BLOCKS
    last_ts: int | None = None
    async for a, b, logs in ctx.rpc.iter_logs(address=token, topics=[TOPIC_TRANSFER], from_block=start, to_block=head, chunk=chunk):
        rows: list[tuple[Any, ...]] = []
        if logs:
            blocks = sorted({int(l["blockNumber"], 16) for l in logs})
            ts_map = await ctx.rpc.block_timestamps(blocks)
            logs.sort(key=lambda l: (int(l["blockNumber"], 16), int(l.get("logIndex") or "0x0", 16)))
            for lg in logs:
                dec = _decode_transfer(lg)
                if dec is None:
                    continue
                frm, to, value = dec
                bn = int(lg["blockNumber"], 16)
                ts = ts_map.get(bn)
                last_ts = ts or last_ts
                rows.append((ctx.chain_id, lg["transactionHash"].lower(), int(lg.get("logIndex") or "0x0", 16), bn, ts, token, frm, to, str(value), "rpc"))
        with ctx.db.transaction():
            if rows:
                # idempotency: only rows not already stored are inserted AND replayed
                existing = {
                    (r["tx_hash"], int(r["log_index"]))
                    for r in ctx.db.query(
                        "SELECT tx_hash, log_index FROM transfers WHERE chain_id=? AND token_address=? AND block_number BETWEEN ? AND ?",
                        (ctx.chain_id, token, a, b),
                    )
                }
                new_rows = [r for r in rows if (r[1], r[2]) not in existing]
                if new_rows:
                    ctx.db.executemany(
                        "INSERT OR IGNORE INTO transfers(chain_id, tx_hash, log_index, block_number, ts, token_address, from_address, to_address, value, source) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        new_rows,
                    )
                    n_rows += len(new_rows)
                    for r in new_rows:
                        book.apply(r[6], r[7], int(r[8]), int(r[3]), r[4])
            # periodic point-in-time holder-count snapshots
            while next_snapshot <= b:
                exists = ctx.db.query_one(
                    "SELECT 1 FROM holder_count_snapshots WHERE chain_id=? AND token_address=? AND source='rpc_replay' AND block_number=?",
                    (ctx.chain_id, token, next_snapshot),
                )
                if exists is None:
                    total, exs = book.holder_counts(min_balance_units)
                    snap_ts = (await ctx.rpc.block_timestamps([next_snapshot])).get(next_snapshot) or last_ts
                    ctx.db.insert("holder_count_snapshots", {
                        "ts": snap_ts or now_ts(), "chain_id": ctx.chain_id, "token_address": token, "source": "rpc_replay", "block_number": next_snapshot,
                        "holder_count": total, "holder_count_ex_system": exs, "transfers_count": None, "quality_flags": json.dumps([]),
                    })
                next_snapshot += SNAPSHOT_INTERVAL_BLOCKS
            book.flush(b, last_ts)
            ctx.db.cursor_set(cursor_name, b, now_ts())
    total, exs = book.holder_counts(min_balance_units)
    log.info("transfers ingested token=%s new=%d range=%d-%d holders=%d ex_system=%d", token[:10], n_rows, start, head, total, exs)
    return {"transfers": n_rows, "from_block": start, "to_block": head, "holder_count": total, "holder_count_ex_system": exs}


def rebuild_balances(ctx: IntelContext, token: str, *, emit_snapshots: bool = True, batch: int = 50_000) -> dict[str, Any]:
    """Recompute ``holders`` from scratch by replaying every stored transfer in order.

    Used after a backward backfill (history was partial when balances were first replayed).
    Point-in-time ``holder_count_snapshots`` (source ``rpc_replay``) are regenerated too.
    """
    token = token.lower()
    with ctx.db.transaction():
        ctx.db.execute("DELETE FROM holders WHERE chain_id=? AND token_address=?", (ctx.chain_id, token))
        if emit_snapshots:
            ctx.db.execute("DELETE FROM holder_count_snapshots WHERE chain_id=? AND token_address=? AND source='rpc_replay'", (ctx.chain_id, token))
    book = BalanceBook(ctx, token)
    n = 0
    offset = 0
    last_block: int | None = None
    last_ts: int | None = None
    next_snapshot: int | None = None
    snap_rows: list[dict[str, Any]] = []
    while True:
        rows = ctx.db.query(
            "SELECT from_address, to_address, value, block_number, ts FROM transfers WHERE chain_id=? AND token_address=? ORDER BY block_number, log_index LIMIT ? OFFSET ?",
            (ctx.chain_id, token, batch, offset),
        )
        if not rows:
            break
        for r in rows:
            bn = int(r["block_number"])
            if next_snapshot is None:
                next_snapshot = (bn // SNAPSHOT_INTERVAL_BLOCKS + 1) * SNAPSHOT_INTERVAL_BLOCKS
            while emit_snapshots and next_snapshot <= bn:
                total, exs = book.holder_counts()
                snap_rows.append({"ts": last_ts or r["ts"] or now_ts(), "chain_id": ctx.chain_id, "token_address": token, "source": "rpc_replay", "block_number": next_snapshot, "holder_count": total, "holder_count_ex_system": exs, "transfers_count": None, "quality_flags": json.dumps([])})
                next_snapshot += SNAPSHOT_INTERVAL_BLOCKS
            book.apply(r["from_address"], r["to_address"], int(r["value"]), bn, r["ts"])
            last_block, last_ts = bn, r["ts"]
            n += 1
        offset += len(rows)
    with ctx.db.transaction():
        if last_block is not None:
            book.flush(last_block, last_ts)
        if snap_rows:
            ctx.db.insert_many("holder_count_snapshots", snap_rows, ignore=False)
    total, exs = book.holder_counts()
    log.info("balances rebuilt token=%s transfers=%d holders=%d ex_system=%d snapshots=%d", token[:10], n, total, exs, len(snap_rows))
    return {"transfers_replayed": n, "holder_count": total, "holder_count_ex_system": exs, "snapshots": len(snap_rows)}


async def backfill_backward(ctx: IntelContext, token: str, *, max_blocks: int | None = None) -> dict[str, Any]:
    """Ingest transfers from the token's creation up to the first block already stored, then
    rebuild balances. Resumable via cursor ``transfers_back:<token>``; a no-op when complete.

    ``max_blocks`` bounds one call (status ``partial`` until the gap is closed) so the
    scheduler can spread a heavy launch-period backfill over many quiet cycles.
    """
    token = token.lower()
    trow = ctx.db.query_one("SELECT creation_block FROM tokens WHERE chain_id=? AND address=?", (ctx.chain_id, token))
    creation = int(trow["creation_block"]) if trow and trow["creation_block"] else None
    if creation is None:
        earliest_pool = ctx.db.scalar("SELECT MIN(created_block) FROM pairs WHERE chain_id=? AND token_address=? AND created_block IS NOT NULL", (ctx.chain_id, token))
        creation = int(earliest_pool) - 5000 if earliest_pool else None
    fwd_start = ctx.db.cursor_get(f"transfers_fwd_start:{token}")
    if fwd_start is None:
        fwd_start = ctx.db.scalar("SELECT MIN(block_number) FROM transfers WHERE chain_id=? AND token_address=?", (ctx.chain_id, token))
    if creation is None or fwd_start is None:
        return {"status": "unknown_creation" if creation is None else "no_forward_data", "transfers": 0}
    fwd_start = int(fwd_start)
    cursor_name = f"transfers_back:{token}"
    rebuilt_name = f"transfers_rebuilt:{token}"
    gap_end = fwd_start - 1
    cur = ctx.db.cursor_get(cursor_name)
    if fwd_start <= creation + 5 or (cur is not None and int(cur) >= gap_end):
        rebuilt = ctx.db.cursor_get(rebuilt_name)
        if cur is not None and (rebuilt is None or int(rebuilt) < gap_end):
            stats = rebuild_balances(ctx, token)  # gap closed earlier but the rebuild did not run
            ctx.db.cursor_set(rebuilt_name, gap_end, now_ts())
            return {"status": "filled", "transfers": 0, "from_block": creation, "to_block": gap_end, **stats}
        return {"status": "complete", "transfers": 0}
    start = int(cur) + 1 if cur is not None else creation
    end = min(gap_end, start + int(max_blocks) - 1) if max_blocks else gap_end
    n = 0
    chunk = int(ctx.config.get("engine.rpc_log_chunk_blocks", 10000))
    if start <= end:
        async for a, b, logs in ctx.rpc.iter_logs(address=token, topics=[TOPIC_TRANSFER], from_block=start, to_block=end, chunk=chunk):
            rows = []
            if logs:
                blocks = sorted({int(l["blockNumber"], 16) for l in logs})
                ts_map = await ctx.rpc.block_timestamps(blocks)
                for lg in logs:
                    dec = _decode_transfer(lg)
                    if dec is None:
                        continue
                    frm, to, value = dec
                    bn = int(lg["blockNumber"], 16)
                    rows.append((ctx.chain_id, lg["transactionHash"].lower(), int(lg.get("logIndex") or "0x0", 16), bn, ts_map.get(bn), token, frm, to, str(value), "rpc"))
            with ctx.db.transaction():
                if rows:
                    before = ctx.db._conn.total_changes
                    ctx.db.executemany(
                        "INSERT OR IGNORE INTO transfers(chain_id, tx_hash, log_index, block_number, ts, token_address, from_address, to_address, value, source) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        rows,
                    )
                    n += ctx.db._conn.total_changes - before
                ctx.db.cursor_set(cursor_name, b, now_ts())
    if end < gap_end:
        log.info("backward backfill token=%s partial range=%d-%d new=%d remaining=%d blocks", token[:10], start, end, n, gap_end - end)
        return {"status": "partial", "transfers": n, "from_block": start, "to_block": end, "remaining_blocks": gap_end - end}
    stats = rebuild_balances(ctx, token)
    ctx.db.cursor_set(rebuilt_name, gap_end, now_ts())
    log.info("backward backfill token=%s range=%d-%d new=%d", token[:10], start, end, n)
    return {"status": "filled", "transfers": n, "from_block": creation, "to_block": end, **stats}


def holder_count_at(ctx: IntelContext, token: str, as_of_ts: int, max_age_seconds: int = 3600) -> tuple[int | None, int | None, str | None]:
    """Point-in-time holder count (total, ex-system, source) from snapshots not after ``as_of_ts``."""
    row = ctx.db.query_one(
        "SELECT holder_count, holder_count_ex_system, source, ts FROM holder_count_snapshots WHERE chain_id=? AND token_address=? AND ts<=? ORDER BY ts DESC LIMIT 1",
        (ctx.chain_id, token.lower(), as_of_ts),
    )
    if row is None or as_of_ts - int(row["ts"]) > max_age_seconds:
        return None, None, None
    return row["holder_count"], row["holder_count_ex_system"], row["source"]
