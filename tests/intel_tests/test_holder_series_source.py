"""Holder series source selection: explorer counts win while transfer history is partial."""
from intel.context import IntelContext
from intel.db.connection import Database
from intel.metrics.holders import holder_series
from intel.metrics.launch import launch_history_complete
from intel.providers.base import ProviderStatusRegistry
from intel.settings import IntelConfig, Settings

TOKEN = "0x" + "cc" * 20


def _ctx() -> IntelContext:
    ctx = IntelContext.__new__(IntelContext)
    ctx.settings = Settings.load(db_path=":memory:", telegram_dry_run=True)
    ctx.config = IntelConfig()
    ctx.db = Database(":memory:")
    ctx.status = ProviderStatusRegistry(ctx.db)
    ctx.rpc = ctx.blockscout = ctx.dex = None  # type: ignore[assignment]
    return ctx


def test_prefers_explorer_when_history_partial_and_replay_when_complete():
    ctx = _ctx()
    for ts, src, n in [(1000, "rpc_replay", 240), (1000, "blockscout", 6004), (2000, "rpc_replay", 250), (2000, "blockscout", 6010)]:
        ctx.db.insert("holder_count_snapshots", {"ts": ts, "chain_id": ctx.chain_id, "token_address": TOKEN, "source": src, "block_number": None, "holder_count": n, "holder_count_ex_system": n, "transfers_count": None, "quality_flags": "[]"})
    ctx.db.insert("tokens", {"chain_id": ctx.chain_id, "address": TOKEN, "first_seen_ts": 1, "updated_ts": 1, "creation_block": 100})
    # only a transfer from block 5000 is known: history is partial
    ctx.db.insert("transfers", {"chain_id": ctx.chain_id, "tx_hash": "0x1", "log_index": 0, "block_number": 5000, "ts": 900, "token_address": TOKEN, "from_address": "0x" + "1" * 40, "to_address": "0x" + "2" * 40, "value": "1", "source": "rpc"})
    assert launch_history_complete(ctx, TOKEN) is False
    s = holder_series(ctx, TOKEN, 2500, prefer_replay=False)
    assert [x[1] for x in s] == [6004, 6010] and all(x[3] == "blockscout" for x in s)
    # a mint from 0x0 makes the history complete -> replay series preferred
    ctx.db.insert("transfers", {"chain_id": ctx.chain_id, "tx_hash": "0x0", "log_index": 0, "block_number": 100, "ts": 100, "token_address": TOKEN, "from_address": "0x" + "0" * 40, "to_address": "0x" + "2" * 40, "value": "1", "source": "rpc"})
    assert launch_history_complete(ctx, TOKEN) is True
    s2 = holder_series(ctx, TOKEN, 2500, prefer_replay=True)
    assert [x[1] for x in s2] == [240, 250]
