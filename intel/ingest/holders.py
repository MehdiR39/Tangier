"""Holder snapshots: Blockscout top holders / counters (indexed) and RPC replay (ground truth)."""
from __future__ import annotations

import json
import logging
from typing import Any

from intel.context import IntelContext
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)


async def snapshot_holders_blockscout(ctx: IntelContext, token: str, *, pages: int | None = None, ts: int | None = None) -> dict[str, Any]:
    token = token.lower()
    ts = ts or now_ts()
    pages = pages or int(ctx.config.get("engine.top_holders_pages", 2))
    out: dict[str, Any] = {"holder_count": None, "transfers_count": None, "top": []}
    try:
        counters = await ctx.blockscout.token_counters(token)
    except Exception as exc:
        log.warning("blockscout counters failed %s: %s", token[:10], exc)
        counters = None
    if counters:
        try:
            out["holder_count"] = int(counters.get("token_holders_count")) if counters.get("token_holders_count") is not None else None
            out["transfers_count"] = int(counters.get("transfers_count")) if counters.get("transfers_count") is not None else None
        except (TypeError, ValueError):
            pass
    try:
        items = await ctx.blockscout.token_holders(token, max_pages=pages)
    except Exception as exc:
        log.warning("blockscout holders failed %s: %s", token[:10], exc)
        items = []
    rows = []
    wallet_rows = []
    for rank, it in enumerate(items, start=1):
        addr = (it.get("address") or {}).get("hash", "").lower()
        if not addr:
            continue
        bal = int(it.get("value") or 0)
        label = ctx.system_label(addr)
        is_contract = (it.get("address") or {}).get("is_contract")
        name = (it.get("address") or {}).get("name")
        if label is None and is_contract and name:
            # auto-label well-known infrastructure by verified contract name
            low = name.lower()
            for key, lbl in (("poolmanager", "lp:uniswap_v4_pool_manager"), ("airlock", "launchpad:doppler_airlock"), ("initializer", "hook:doppler_initializer"),
                             ("migrator", "launchpad:migrator"), ("locker", "treasury:fee_locker"), ("router", "router:contract"), ("settler", "router:settler"),
                             ("positionmanager", "lp:position_manager"), ("timelock", "treasury:timelock"), ("governor", "treasury:governance"), ("governance", "treasury:governance")):
                if key in low:
                    label = lbl
                    ctx.add_system_address(addr, label)
                    break
        rows.append({
            "ts": ts, "chain_id": ctx.chain_id, "token_address": token, "source": "blockscout", "block_number": None,
            "address": addr, "balance": str(bal), "balance_float": None, "rank": rank, "is_system": int(label is not None), "system_label": label,
        })
        wallet_rows.append((ctx.chain_id, addr, int(bool(is_contract)) if is_contract is not None else None, name, label.split(":", 1)[0] if label else None, ts))
        out["top"].append({"address": addr, "balance": bal, "is_contract": is_contract, "name": name, "label": label})
    with ctx.db.transaction():
        if out["holder_count"] is not None:
            ctx.db.insert("holder_count_snapshots", {
                "ts": ts, "chain_id": ctx.chain_id, "token_address": token, "source": "blockscout", "block_number": None,
                "holder_count": out["holder_count"], "holder_count_ex_system": None, "transfers_count": out["transfers_count"], "quality_flags": json.dumps([]),
            })
        if rows:
            ctx.db.insert_many("holder_snapshots", rows, ignore=False)
        if wallet_rows:
            ctx.db.executemany(
                "INSERT INTO wallets(chain_id, address, is_contract, label, system_kind, updated_ts) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(chain_id, address) DO UPDATE SET is_contract=COALESCE(excluded.is_contract, wallets.is_contract), label=COALESCE(excluded.label, wallets.label), "
                "system_kind=COALESCE(excluded.system_kind, wallets.system_kind), updated_ts=excluded.updated_ts",
                wallet_rows,
            )
            # propagate contract flags into holders table for concentration exclusion
            ctx.db.executemany(
                "UPDATE holders SET is_contract=? WHERE chain_id=? AND token_address=? AND address=? AND is_contract IS NULL",
                [(w[2], ctx.chain_id, token, w[1]) for w in wallet_rows if w[2] is not None],
            )
    return out


def snapshot_holders_replay(ctx: IntelContext, token: str, *, block_number: int | None, ts: int | None = None, top_n: int | None = None, min_balance_units: int = 1) -> dict[str, Any]:
    """Persist top-N + counts from the replayed ``holders`` table (source ``rpc_replay``)."""
    token = token.lower()
    ts = ts or now_ts()
    top_n = top_n or int(ctx.config.get("engine.holder_snapshot_top_n", 100))
    rows = ctx.db.query(
        "SELECT address, balance, is_system, system_label, is_contract FROM holders WHERE chain_id=? AND token_address=? AND CAST(balance AS INTEGER) > 0",
        (ctx.chain_id, token),
    )
    holders = [(r["address"], int(r["balance"]), bool(r["is_system"]), r["system_label"], r["is_contract"]) for r in rows if int(r["balance"]) >= min_balance_units]
    holders.sort(key=lambda x: -x[1])
    total = len(holders)
    ex_system = sum(1 for h in holders if not h[2])
    snap_rows = []
    for rank, (addr, bal, is_sys, label, _ic) in enumerate(holders[:top_n], start=1):
        snap_rows.append({
            "ts": ts, "chain_id": ctx.chain_id, "token_address": token, "source": "rpc_replay", "block_number": block_number,
            "address": addr, "balance": str(bal), "balance_float": None, "rank": rank, "is_system": int(is_sys), "system_label": label,
        })
    from intel.metrics.launch import launch_history_complete  # local import to avoid cycles

    flags = [] if launch_history_complete(ctx, token) else ["partial_transfer_history"]
    with ctx.db.transaction():
        ctx.db.insert("holder_count_snapshots", {
            "ts": ts, "chain_id": ctx.chain_id, "token_address": token, "source": "rpc_replay", "block_number": block_number,
            "holder_count": total, "holder_count_ex_system": ex_system, "transfers_count": None, "quality_flags": json.dumps(flags),
        })
        if snap_rows:
            ctx.db.insert_many("holder_snapshots", snap_rows, ignore=False)
    return {"holder_count": total, "holder_count_ex_system": ex_system, "top": holders[:top_n], "quality_flags": flags}


async def label_top_holders(ctx: IntelContext, token: str, addresses: list[str]) -> None:
    """Fill ``is_contract`` / names for addresses we have not classified yet (cached Blockscout lookups)."""
    token = token.lower()
    todo = []
    for a in addresses:
        row = ctx.db.query_one("SELECT is_contract FROM wallets WHERE chain_id=? AND address=?", (ctx.chain_id, a))
        if row is None or row["is_contract"] is None:
            todo.append(a)
    for a in todo[:40]:
        try:
            info = await ctx.blockscout.address(a)
        except Exception:
            info = None
        if not info:
            continue
        is_contract = int(bool(info.get("is_contract")))
        name = info.get("name")
        label = ctx.system_label(a)
        ctx.db.execute(
            "INSERT INTO wallets(chain_id, address, is_contract, label, system_kind, updated_ts) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(chain_id, address) DO UPDATE SET is_contract=excluded.is_contract, label=COALESCE(excluded.label, wallets.label), updated_ts=excluded.updated_ts",
            (ctx.chain_id, a, is_contract, name, label.split(":", 1)[0] if label else None, now_ts()),
        )
        ctx.db.execute("UPDATE holders SET is_contract=? WHERE chain_id=? AND token_address=? AND address=?", (is_contract, ctx.chain_id, token, a))
