"""Whale definition and flow tracking (balance deltas from transfers, USD flows from trades)."""
from __future__ import annotations

import json
import logging
from typing import Any

from intel.context import IntelContext
from intel.utils.timeutil import WINDOWS_SECONDS, now_ts

log = logging.getLogger(__name__)


def define_whales(holders: list[tuple[str, int, bool]], econ_supply: int, price_usd: float | None, decimals: int, params: dict[str, Any]) -> list[tuple[str, int]]:
    """Whales = economic holders above a USD position AND (supply share OR ownership percentile)."""
    econ = sorted(((a, b) for a, b, ex in holders if not ex and b > 0), key=lambda x: -x[1])
    if not econ or econ_supply <= 0:
        return []
    min_usd = float(params.get("min_position_usd", 5000.0))
    min_pct = float(params.get("min_supply_pct", 0.0025))
    pctl = float(params.get("ownership_percentile", 0.99))
    max_tracked = int(params.get("max_tracked", 50))
    cutoff_rank = max(1, int(round(len(econ) * (1 - pctl))))
    out = []
    for rank, (a, b) in enumerate(econ, start=1):
        usd = (b / 10 ** decimals) * price_usd if price_usd else None
        share = b / econ_supply
        usd_ok = usd is None or usd >= min_usd  # unknown price: do not exclude on USD
        if usd_ok and (share >= min_pct or rank <= cutoff_rank):
            out.append((a, b))
        if len(out) >= max_tracked:
            break
    return out


def wallet_window_flows(ctx: IntelContext, token: str, address: str, as_of_ts: int, window: str) -> dict[str, Any]:
    since = as_of_ts - WINDOWS_SECONDS[window]
    tin = ctx.db.scalar("SELECT COALESCE(SUM(CAST(value AS REAL)),0) FROM transfers WHERE chain_id=? AND token_address=? AND to_address=? AND ts>? AND ts<=?", (ctx.chain_id, token, address, since, as_of_ts), 0.0)
    tout = ctx.db.scalar("SELECT COALESCE(SUM(CAST(value AS REAL)),0) FROM transfers WHERE chain_id=? AND token_address=? AND from_address=? AND ts>? AND ts<=?", (ctx.chain_id, token, address, since, as_of_ts), 0.0)
    row = ctx.db.query_one(
        "SELECT COALESCE(SUM(CASE WHEN side='BUY' THEN usd_value END),0) AS gb, COALESCE(SUM(CASE WHEN side='SELL' THEN usd_value END),0) AS gs, "
        "SUM(CASE WHEN side='BUY' THEN 1 ELSE 0 END) AS nb, SUM(CASE WHEN side='SELL' THEN 1 ELSE 0 END) AS ns FROM trades WHERE chain_id=? AND token_address=? AND trader=? AND ts>? AND ts<=?",
        (ctx.chain_id, token, address, since, as_of_ts),
    )
    gb = float(row["gb"] or 0) if row else 0.0
    gs = float(row["gs"] or 0) if row else 0.0
    return {"balance_delta": float(tin) - float(tout), "gross_buy_usd": gb, "gross_sell_usd": gs, "net_buy_usd": gb - gs, "buy_count": int(row["nb"] or 0) if row else 0, "sell_count": int(row["ns"] or 0) if row else 0}


def entry_estimate(ctx: IntelContext, token: str, address: str, as_of_ts: int) -> dict[str, Any]:
    row = ctx.db.query_one(
        "SELECT MIN(ts) AS first_ts, SUM(usd_value) AS usd, SUM(token_amount_float) AS amt FROM trades WHERE chain_id=? AND token_address=? AND trader=? AND side='BUY' AND ts<=?",
        (ctx.chain_id, token, address, as_of_ts),
    )
    if not row or row["first_ts"] is None:
        return {"entry_ts": None, "avg_entry_price_usd": None, "cost_basis_usd": None}
    amt = float(row["amt"] or 0)
    usd = float(row["usd"] or 0)
    return {"entry_ts": int(row["first_ts"]), "avg_entry_price_usd": (usd / amt) if amt and usd else None, "cost_basis_usd": usd or None}


def whale_flows(ctx: IntelContext, token: str, whales: list[tuple[str, int]], as_of_ts: int, *, decimals: int, price_usd: float | None, econ_supply: int, windows: list[str] | None = None, persist: bool = True) -> dict[str, Any]:
    token = token.lower()
    windows = windows or ["5m", "1h", "6h", "24h"]
    per_wallet: list[dict[str, Any]] = []
    agg: dict[str, Any] = {f"whale_netflow_{w}": 0.0 for w in windows}
    agg.update({"number_accumulating": 0, "number_distributing": 0, "n_whales": len(whales)})
    top10 = {a for a, _ in whales[:10]}
    top20 = {a for a, _ in whales[:20]}
    agg["top10_netflow_24h"] = 0.0
    agg["top20_netflow_24h"] = 0.0
    agg["top10_netflow_1h"] = 0.0
    agg["top20_netflow_1h"] = 0.0
    scale = 10 ** decimals
    rows_flows: list[dict[str, Any]] = []
    rows_pos: list[dict[str, Any]] = []
    for addr, bal in whales:
        w: dict[str, Any] = {"address": addr, "current_balance": bal, "balance_float": bal / scale, "supply_pct": (bal / econ_supply) if econ_supply else None, "usd_value": (bal / scale * price_usd) if price_usd else None}
        for win in windows:
            f = wallet_window_flows(ctx, token, addr, as_of_ts, win)
            w[f"balance_delta_{win}"] = f["balance_delta"] / scale
            w[f"net_buy_usd_{win}"] = f["net_buy_usd"]
            w[f"gross_buy_usd_{win}"] = f["gross_buy_usd"]
            w[f"gross_sell_usd_{win}"] = f["gross_sell_usd"]
            prev = bal - f["balance_delta"]
            w[f"position_change_pct_{win}"] = (f["balance_delta"] / prev) if prev > 0 else None
            agg[f"whale_netflow_{win}"] += f["net_buy_usd"]
            if win in ("1h", "24h"):
                if addr in top10:
                    agg[f"top10_netflow_{win}"] += f["net_buy_usd"]
                if addr in top20:
                    agg[f"top20_netflow_{win}"] += f["net_buy_usd"]
            rows_flows.append({
                "ts": as_of_ts, "chain_id": ctx.chain_id, "token_address": token, "address": addr, "window": win, "source": "rpc_reconstruction", "block_number": None,
                "gross_buy_usd": f["gross_buy_usd"], "gross_sell_usd": f["gross_sell_usd"], "net_buy_usd": f["net_buy_usd"], "buy_count": f["buy_count"], "sell_count": f["sell_count"],
                "balance_delta": str(int(f["balance_delta"])), "balance_delta_float": f["balance_delta"] / scale, "position_change_pct": w[f"position_change_pct_{win}"], "is_whale": 1,
            })
        d24 = w.get("balance_delta_24h") or 0.0
        if d24 > 0 and (w.get("position_change_pct_24h") or 0) > 0.02:
            agg["number_accumulating"] += 1
        elif d24 < 0 and (w.get("position_change_pct_24h") or 0) < -0.02:
            agg["number_distributing"] += 1
        w.update(entry_estimate(ctx, token, addr, as_of_ts))
        per_wallet.append(w)
        rows_pos.append({
            "ts": as_of_ts, "chain_id": ctx.chain_id, "token_address": token, "address": addr, "source": "rpc_replay", "block_number": None,
            "balance": str(bal), "balance_float": bal / scale, "supply_pct": w["supply_pct"], "usd_value": w["usd_value"],
            "cost_basis_usd": w.get("cost_basis_usd"), "avg_entry_price_usd": w.get("avg_entry_price_usd"), "realized_pnl_usd": None, "entry_ts": w.get("entry_ts"), "quality_flags": json.dumps([]),
        })
    if persist and (rows_flows or rows_pos):
        with ctx.db.transaction():
            ctx.db.insert_many("wallet_flows", rows_flows, ignore=False)
            ctx.db.insert_many("wallet_token_positions", rows_pos, ignore=False)
    agg["wallets"] = per_wallet
    return agg


def top_wallet_distribution(per_wallet: list[dict[str, Any]], window: str = "1h", min_pct: float = 0.20) -> list[dict[str, Any]]:
    """Whales that reduced their position by >= min_pct in the window."""
    return [w for w in per_wallet if (w.get(f"position_change_pct_{window}") or 0) <= -min_pct]
