"""Data retention: drop raw event history of dead scanner tokens and old dense snapshots.

Portfolio tokens and ACTIVE scanner tokens keep everything (their history is what the
metrics are built from). REJECTED / DORMANT scanner tokens are cheap to re-ingest if they
ever come back, so their transfers/swaps/trades/holders are removed after ``dead_token_days``.
Scores, alerts, decisions and token-level snapshots are never pruned (backtests need them).
"""
from __future__ import annotations

import logging
from typing import Any

from intel.context import IntelContext
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)

RAW_TABLES = ("transfers", "swap_events", "liquidity_events", "trades", "holders", "holder_snapshots", "holder_count_snapshots", "wallet_flows", "wallet_token_positions")


def prune(ctx: IntelContext) -> dict[str, Any]:
    cfg = ctx.config.section("retention")
    now = now_ts()
    dead_before = now - int(cfg.get("dead_token_days", 2)) * 86400
    stats: dict[str, Any] = {"tokens": 0}
    dead = [r["token_address"] for r in ctx.db.query(
        "SELECT c.token_address FROM scanner_candidates c LEFT JOIN portfolio_positions p ON p.chain_id=c.chain_id AND p.token_address=c.token_address AND p.active=1 "
        "WHERE c.chain_id=? AND p.token_address IS NULL AND c.status IN ('REJECTED','DORMANT') AND COALESCE(c.last_stage_ts, c.last_seen_ts) < ? "
        "AND c.token_address IN (SELECT DISTINCT token_address FROM transfers WHERE chain_id=?)",
        (ctx.chain_id, dead_before, ctx.chain_id),
    )]
    for token in dead:
        with ctx.db.transaction():
            for t in RAW_TABLES:
                col = "token_address" if t != "swap_events" and t != "liquidity_events" else None
                if col:
                    n = ctx.db.execute(f"DELETE FROM {t} WHERE chain_id=? AND token_address=?", (ctx.chain_id, token)).rowcount
                else:
                    n = ctx.db.execute(f"DELETE FROM {t} WHERE chain_id=? AND pair_id IN (SELECT pair_id FROM pairs WHERE chain_id=? AND token_address=?)", (ctx.chain_id, ctx.chain_id, token)).rowcount
                stats[t] = stats.get(t, 0) + n
            for name in ("transfers", "pools", "trades", "transfers_back", "transfers_fwd_start", "transfers_rebuilt"):
                ctx.db.execute("DELETE FROM sync_cursors WHERE name=?", (f"{name}:{token}",))
        stats["tokens"] += 1
    # dense snapshots: keep a rolling window for everyone (point-in-time metrics use recent data only)
    hs_before = now - int(cfg.get("holder_snapshot_days", 7)) * 86400
    ps_before = now - int(cfg.get("pair_snapshot_days", 14)) * 86400
    with ctx.db.transaction():
        stats["holder_snapshots_old"] = ctx.db.execute("DELETE FROM holder_snapshots WHERE chain_id=? AND ts<?", (ctx.chain_id, hs_before)).rowcount
        stats["pair_snapshots_old"] = ctx.db.execute(
            "DELETE FROM pair_snapshots WHERE chain_id=? AND ts<? AND token_address NOT IN (SELECT token_address FROM portfolio_positions WHERE chain_id=? AND active=1)", (ctx.chain_id, ps_before, ctx.chain_id)
        ).rowcount
    log.info("retention prune done: %s", stats)
    return stats
