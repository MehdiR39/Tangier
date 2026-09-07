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
