"""Transfer ingestion is idempotent and replays balances exactly; timestamps interpolate cheaply."""
import asyncio

import pytest

from intel.chain.constants import TOPIC_TRANSFER
from intel.context import IntelContext
from intel.db.connection import Database
from intel.ingest.transfers import BalanceBook, ingest_transfers
from intel.providers.base import ProviderStatusRegistry
from intel.providers.rpc import RpcClient
from intel.settings import IntelConfig, Settings

TOKEN = "0x" + "aa" * 20
A = "0x" + "11" * 20
B = "0x" + "22" * 20
PM = "0x8366a39cc670b4001a1121b8f6a443a643e40951"


def _log(block: int, idx: int, frm: str, to: str, value: int, tx: str):
    return {
        "address": TOKEN, "topics": [TOPIC_TRANSFER, "0x" + "0" * 24 + frm[2:], "0x" + "0" * 24 + to[2:]],
        "data": "0x" + value.to_bytes(32, "big").hex(), "blockNumber": hex(block), "logIndex": hex(idx), "transactionHash": tx,
    }


class StubRpc:
    """Serves a fixed log set and linear timestamps (block * 0.1s) without network."""

    def __init__(self, logs):
        self._logs = logs
        self.calls = 0
        self.block_time_hint = 0.1

    async def block_number(self):
        return 10_000

    async def iter_logs(self, *, address, topics, from_block, to_block, chunk=20000, min_chunk=250):
        self.calls += 1
        yield from_block, to_block, [l for l in self._logs if from_block <= int(l["blockNumber"], 16) <= to_block]

    async def block_timestamps(self, numbers, **kw):
        return {int(n): 1_700_000_000 + int(n) // 10 for n in numbers}

    async def block_timestamp(self, n):
        return 1_700_000_000 + n // 10


def _ctx(logs) -> IntelContext:
    settings = Settings.load(db_path=":memory:", telegram_dry_run=True)
    db = Database(":memory:")
    ctx = IntelContext.__new__(IntelContext)
    ctx.settings = settings
    ctx.config = IntelConfig()
    ctx.db = db
    ctx.status = ProviderStatusRegistry(db)
    ctx.rpc = StubRpc(logs)  # type: ignore[assignment]
    ctx.blockscout = None  # type: ignore[assignment]
    ctx.dex = None  # type: ignore[assignment]
    return ctx


def test_ingest_transfers_idempotent_and_balances_exact():
    logs = [
        _log(100, 0, "0x" + "0" * 40, PM, 1000, "0xmint"),      # mint to pool manager (system)
        _log(200, 1, PM, A, 300, "0xbuyA"),
        _log(300, 2, PM, B, 200, "0xbuyB"),
        _log(400, 3, A, PM, 100, "0xsellA"),
        _log(500, 4, B, A, 50, "0xgift"),
    ]
    ctx = _ctx(logs)
    ctx.db.insert("tokens", {"chain_id": ctx.chain_id, "address": TOKEN, "first_seen_ts": 1, "updated_ts": 1, "creation_block": 50})
    r1 = asyncio.run(ingest_transfers(ctx, TOKEN, to_block=10_000, from_block=50))
    assert r1["transfers"] == 5
    bal = {row["address"]: int(row["balance"]) for row in ctx.db.query("SELECT address, balance FROM holders WHERE token_address=?", (TOKEN,))}
    assert bal[A] == 300 - 100 + 50 and bal[B] == 200 - 50 and bal[PM] == 1000 - 300 - 200 + 100
    assert r1["holder_count"] == 3 and r1["holder_count_ex_system"] == 2  # PM is system
    assert ctx.db.cursor_get(f"transfers:{TOKEN}") == 10_000
    # second run: cursor advanced, nothing new, balances unchanged
    r2 = asyncio.run(ingest_transfers(ctx, TOKEN, to_block=10_000))
    assert r2["transfers"] == 0
    bal2 = {row["address"]: int(row["balance"]) for row in ctx.db.query("SELECT address, balance FROM holders WHERE token_address=?", (TOKEN,))}
    assert bal2 == bal
    # forcing a re-ingest of an already stored range must not double-apply balances
    ctx.db.execute("DELETE FROM sync_cursors WHERE name=?", (f"transfers:{TOKEN}",))
    r3 = asyncio.run(ingest_transfers(ctx, TOKEN, to_block=10_000, from_block=50))
    assert r3["transfers"] == 0
    bal3 = {row["address"]: int(row["balance"]) for row in ctx.db.query("SELECT address, balance FROM holders WHERE token_address=?", (TOKEN,))}
    assert bal3 == bal
    # point-in-time holder-count snapshots were emitted at 6000-block boundaries
    snaps = ctx.db.query("SELECT block_number, holder_count FROM holder_count_snapshots WHERE token_address=? ORDER BY block_number", (TOKEN,))
    assert [s["block_number"] for s in snaps] == [6000]
    assert snaps[0]["holder_count"] == 3


def test_backward_backfill_completes_history_and_rebuilds_balances():
    from intel.ingest.transfers import backfill_backward
    from intel.metrics.launch import launch_history_complete

    logs = [
        _log(60, 0, "0x" + "0" * 40, PM, 1000, "0xmint"),   # creation-era mint
        _log(90, 1, PM, A, 400, "0xearlyA"),                  # early buy (before the forward window)
        _log(7000, 2, A, PM, 100, "0xsellA"),                 # inside forward window
        _log(7100, 3, PM, B, 50, "0xbuyB"),
    ]
    ctx = _ctx(logs)
    ctx.db.insert("tokens", {"chain_id": ctx.chain_id, "address": TOKEN, "first_seen_ts": 1, "updated_ts": 1, "creation_block": 55})
    # forward ingestion started mid-life: only blocks >= 6500 known
    asyncio.run(ingest_transfers(ctx, TOKEN, to_block=10_000, from_block=6500))
    assert not launch_history_complete(ctx, TOKEN)
    partial = {r["address"]: int(r["balance"]) for r in ctx.db.query("SELECT address, balance FROM holders WHERE token_address=?", (TOKEN,))}
    assert partial[A] == -100  # partial history: unseen prior balance
    # bounded call: covers only part of the gap -> still incomplete, balances not rebuilt yet
    part = asyncio.run(backfill_backward(ctx, TOKEN, max_blocks=3000))
    assert part["status"] == "partial" and part["transfers"] == 2 and part["remaining_blocks"] > 0
    assert not launch_history_complete(ctx, TOKEN)
    assert {r["address"]: int(r["balance"]) for r in ctx.db.query("SELECT address, balance FROM holders WHERE token_address=?", (TOKEN,))}[A] == -100
    res = asyncio.run(backfill_backward(ctx, TOKEN))
    assert res["status"] == "filled" and res["transfers"] == 0
    assert launch_history_complete(ctx, TOKEN)
    bal = {r["address"]: int(r["balance"]) for r in ctx.db.query("SELECT address, balance FROM holders WHERE token_address=?", (TOKEN,))}
    assert bal[A] == 300 and bal[B] == 50 and bal[PM] == 1000 - 400 + 100 - 50
    # forward cursor untouched, backward cursor recorded, snapshots regenerated in block order
    assert ctx.db.cursor_get(f"transfers:{TOKEN}") == 10_000
    assert ctx.db.cursor_get(f"transfers_back:{TOKEN}") == 6499  # up to the forward start (block 6500)
    snaps = [r["block_number"] for r in ctx.db.query("SELECT block_number FROM holder_count_snapshots WHERE token_address=? AND source='rpc_replay' ORDER BY block_number", (TOKEN,))]
    assert snaps == [6000]
    # idempotent
    assert asyncio.run(backfill_backward(ctx, TOKEN))["status"] == "complete"


def test_balance_book_counts_and_flush():
    ctx = _ctx([])
    book = BalanceBook(ctx, TOKEN)
    book.apply("0x" + "0" * 40, A, 10, 1, 100)
    book.apply(A, B, 4, 2, 101)
    total, exs = book.holder_counts()
    assert (total, exs) == (2, 2)
    assert book.flush(2, 101) == 2
    row = ctx.db.query_one("SELECT balance, first_seen_block FROM holders WHERE address=?", (A,))
    assert int(row["balance"]) == 6 and row["first_seen_block"] == 1


def test_block_timestamps_interpolate_with_few_calls():
    settings = Settings.load(db_path=":memory:", telegram_dry_run=True)
    rpc = RpcClient(settings, ProviderStatusRegistry(None), None)
    calls = []

    async def fake_block_timestamp(n):
        calls.append(n)
        return 1_700_000_000 + n // 10

    rpc.block_timestamp = fake_block_timestamp  # type: ignore[method-assign]
    numbers = list(range(1_000_000, 1_030_000, 7))  # 30k-block span -> ~4 anchors with max_gap 10k
    out = asyncio.run(rpc.block_timestamps(numbers, max_gap=10_000))
    assert len(out) == len(numbers)
    assert len(calls) <= 6
    for n in numbers[::500]:
        assert abs(out[n] - (1_700_000_000 + n // 10)) <= 2
