from intel.db.connection import Database


def test_migrations_apply_and_are_idempotent():
    db = Database(":memory:")
    versions = [r["version"] for r in db.query("SELECT version FROM schema_migrations ORDER BY version")]
    assert versions == [1, 2, 3, 4, 5, 6]
    assert db.migrate() == []  # second run applies nothing
    tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ["tokens", "token_snapshots", "pairs", "pair_snapshots", "holders", "holder_snapshots", "wallets", "wallet_token_positions",
              "wallet_flows", "transfers", "trades", "contract_security", "token_scores", "alerts", "portfolio_positions", "discovery_events"]:
        assert t in tables, t


def test_insert_ignore_and_cursor_cache():
    db = Database(":memory:")
    row = {"chain_id": 4663, "tx_hash": "0xab", "log_index": 1, "block_number": 10, "ts": 1, "token_address": "0x1", "from_address": "0xa", "to_address": "0xb", "value": "5", "source": "rpc"}
    assert db.insert_many("transfers", [row, row]) == 1
    assert db.insert_many("transfers", [row]) == 0
    db.cursor_set("transfers:0x1", 10, 1)
    assert db.cursor_get("transfers:0x1") == 10
    db.cache_set("k", {"a": 1}, now_ts=100, ttl_seconds=10)
    assert db.cache_get("k", 105) == {"a": 1}
    assert db.cache_get("k", 111) is None


def test_transaction_rollback():
    db = Database(":memory:")
    try:
        with db.transaction():
            db.insert("sync_cursors", {"name": "x", "block_number": 1, "ts": 1, "updated_ts": 1})
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert db.cursor_get("x") is None


def test_retention_prunes_a_token_the_scanner_never_filed():
    """The T+1 watcher buys pools the scanner never sees; their raw events must still expire.

    Until 2026-09-07 "dead" meant "a scanner candidate marked REJECTED or DORMANT", so tokens that
    never became candidates were kept for ever and the database outgrew what a backup can copy.
    """
    import time

    from intel.db.retention import prune

    class _Ctx:
        chain_id = 4663
        db = Database(":memory:")

        @staticmethod
        def config_section():
            return {}

    from intel.settings import IntelConfig
    ctx = _Ctx()
    ctx.config = IntelConfig()
    old = int(time.time()) - 30 * 86400
    for i, (addr, ts, alive) in enumerate((("0x" + "aa" * 20, old, False), ("0x" + "bb" * 20, old, True))):
        ctx.db.insert("transfers", {"chain_id": ctx.chain_id, "token_address": addr, "block_number": 1, "log_index": 0,
                                    "tx_hash": f"0x{i:064d}", "from_address": "0x" + "00" * 20,
                                    "to_address": "0x" + "22" * 20, "value": "1", "ts": ts, "source": "rpc"})
        ctx.db.insert("pairs", {"chain_id": ctx.chain_id, "pair_id": "0x" + addr[2:6] * 16, "token_address": addr,
                                "quote_address": "0x" + "00" * 20, "first_seen_ts": ts, "updated_ts": ts, "source": "test"})
        ctx.db.insert("swap_events", {"chain_id": ctx.chain_id, "pair_id": "0x" + addr[2:6] * 16,
                                      "tx_hash": f"0x{i + 10:064d}", "log_index": 0, "block_number": 2,
                                      "ts": int(time.time()) - 60 if alive else old, "source": "rpc",
                                      "sender": "0x" + "44" * 20, "amount0": "1", "amount1": "1",
                                      "sqrt_price_x96": "1", "liquidity": "1"})
    prune(ctx)
    left = {r["token_address"] for r in ctx.db.query("SELECT DISTINCT token_address FROM transfers")}
    assert "0x" + "aa" * 20 not in left, "un token sans activité ni position doit être purgé"
    assert "0x" + "bb" * 20 in left, "un pool qui échange encore doit être gardé"
