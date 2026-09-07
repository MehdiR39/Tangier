"""Portfolio watcher: monitors configured contract addresses every cycle."""
from __future__ import annotations

import logging
from typing import Any

from intel.engines.pipeline import TokenPipeline
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)


def sync_positions(pipeline: TokenPipeline) -> list[dict[str, Any]]:
    ctx = pipeline.ctx
    positions = ctx.config.portfolio_positions
    ts = now_ts()
    with ctx.db.transaction():
        for p in positions:
            ctx.db.execute(
                "INSERT INTO portfolio_positions(chain_id, token_address, label, quantity, cost_basis_usd, entry_ts, active, notes, updated_ts) VALUES (?,?,?,?,?,?,1,?,?) "
                "ON CONFLICT(chain_id, token_address) DO UPDATE SET label=excluded.label, quantity=excluded.quantity, cost_basis_usd=excluded.cost_basis_usd, entry_ts=excluded.entry_ts, active=1, updated_ts=excluded.updated_ts",
                (ctx.chain_id, p["address"], p.get("label"), p.get("quantity"), p.get("cost_basis_usd"), p.get("entry_ts"), p.get("notes"), ts),
            )
        configured = [p["address"] for p in positions]
        if configured:
            ctx.db.execute(f"UPDATE portfolio_positions SET active=0, updated_ts=? WHERE chain_id=? AND token_address NOT IN ({','.join('?' for _ in configured)})", (ts, ctx.chain_id, *configured))
    return positions


async def run_portfolio_cycle(pipeline: TokenPipeline) -> dict[str, Any]:
    positions = sync_positions(pipeline)
    results: list[dict[str, Any]] = []
    errors = 0
    alerts_sent = 0
    # hold the priority flag for the whole cycle so the scanner / history loop cannot slip in
    # between two watched tokens (they wait until every position has been evaluated)
    pipeline.priority_waiting += 1
    try:
        for p in positions:
            try:
                r = await pipeline.process(p["address"], p.get("label") or p["address"][:10], is_portfolio=True, deep=True)
                results.append(r)
                alerts_sent += (r.get("alerts") or {}).get("sent", 0)
            except Exception as exc:  # noqa: BLE001
                errors += 1
                log.exception("portfolio token failed %s: %s", p.get("label"), exc)
    finally:
        pipeline.priority_waiting = max(0, pipeline.priority_waiting - 1)
    return {"tokens": len(positions), "errors": errors, "alerts_sent": alerts_sent, "results": results}
