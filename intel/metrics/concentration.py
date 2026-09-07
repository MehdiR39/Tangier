"""Holder concentration: top-N shares, HHI, Gini — excluding system addresses.

Denominator for ``*_pct`` is the *economic* supply (total supply minus balances held by
excluded addresses: LP custodian, burn, launchpad, hooks, treasury, bridges, contracts).
``*_pct_total`` uses the raw total supply. Separate addresses are NOT assumed to be
separate actors: see ``intel.metrics.clustering`` for effective concentration.
"""
from __future__ import annotations

from typing import Any, Iterable

from intel.context import IntelContext
from intel.utils.timeutil import WINDOWS_SECONDS

TOP_N = (1, 5, 10, 20, 50)


def gini(values: list[float]) -> float | None:
    vals = sorted(v for v in values if v >= 0)
    n = len(vals)
    if n < 2:
        return None
    total = sum(vals)
    if total <= 0:
        return None
    cum = 0.0
    weighted = 0.0
    for i, v in enumerate(vals, start=1):
        cum += v
        weighted += i * v
    return (2.0 * weighted) / (n * total) - (n + 1.0) / n


def hhi(shares: Iterable[float]) -> float:
    return float(sum(s * s for s in shares))


def concentration(holders: list[tuple[str, int, bool]], total_supply: int | None, top_n: Iterable[int] = TOP_N) -> dict[str, Any]:
    """``holders``: (address, balance_raw, excluded). Balances in raw units."""
    excluded_bal = sum(b for _a, b, ex in holders if ex)
    econ = sorted((b for _a, b, ex in holders if not ex and b > 0), reverse=True)
    econ_supply = (total_supply - excluded_bal) if total_supply else sum(econ)
    out: dict[str, Any] = {"n_holders_economic": len(econ), "excluded_supply_pct": (excluded_bal / total_supply) if total_supply else None, "quality_flags": []}
    if econ_supply <= 0 or not econ:
        for n in top_n:
            out[f"top{n}_pct"] = None
            out[f"top{n}_pct_total"] = None
        out["hhi"] = None
        out["gini"] = None
        out["quality_flags"].append("no_economic_holders")
        return out
    for n in top_n:
        s = sum(econ[:n])
        out[f"top{n}_pct"] = s / econ_supply
        out[f"top{n}_pct_total"] = (s / total_supply) if total_supply else None
    shares = [b / econ_supply for b in econ]
    out["hhi"] = hhi(shares)
    out["gini"] = gini([float(b) for b in econ])
    return out


def economic_exclusion(ctx: IntelContext, address: str, is_contract: int | None, system_label: str | None, exclude_kinds: set[str]) -> bool:
    label = system_label or ctx.system_label(address)
    if label:
        kind = label.split(":", 1)[0]
        return kind in exclude_kinds
    if is_contract and "contract" in exclude_kinds:
        return True
    return False


def current_holder_balances(ctx: IntelContext, token: str, exclude_kinds: set[str]) -> list[tuple[str, int, bool]]:
    rows = ctx.db.query(
        "SELECT address, balance, is_contract, system_label FROM holders WHERE chain_id=? AND token_address=? AND CAST(balance AS INTEGER) > 0",
        (ctx.chain_id, token.lower()),
    )
    return [(r["address"], int(r["balance"]), economic_exclusion(ctx, r["address"], r["is_contract"], r["system_label"], exclude_kinds)) for r in rows]


def snapshot_holder_balances(ctx: IntelContext, token: str, as_of_ts: int, exclude_kinds: set[str], max_age: int = 3 * 3600, *, prefer: str = "rpc_replay") -> tuple[list[tuple[str, int, bool]], int | None, str | None]:
    """Top-N balances from the latest holder_snapshots batch not after ``as_of_ts``.

    ``prefer`` selects the source when both exist in the window: ``rpc_replay`` (exact at a
    block, valid with complete history) or ``blockscout`` (explorer top page, valid always).
    """
    latest = ctx.db.query_one(
        "SELECT ts, source FROM holder_snapshots WHERE chain_id=? AND token_address=? AND ts<=? AND ts>=? ORDER BY CASE source WHEN ? THEN 0 ELSE 1 END, ts DESC LIMIT 1",
        (ctx.chain_id, token.lower(), as_of_ts, as_of_ts - max_age, prefer),
    )
    if latest is None or as_of_ts - int(latest["ts"]) > max_age:
        return [], None, None
    rows = ctx.db.query(
        "SELECT h.address, h.balance, h.system_label, w.is_contract FROM holder_snapshots h LEFT JOIN wallets w ON w.chain_id=h.chain_id AND w.address=h.address "
        "WHERE h.chain_id=? AND h.token_address=? AND h.ts=? AND h.source=?",
        (ctx.chain_id, token.lower(), latest["ts"], latest["source"]),
    )
    return [(r["address"], int(r["balance"]), economic_exclusion(ctx, r["address"], r["is_contract"], r["system_label"], exclude_kinds)) for r in rows], int(latest["ts"]), latest["source"]


def concentration_at(ctx: IntelContext, token: str, as_of_ts: int, total_supply: int | None, *, live: bool, exclude_kinds: set[str], prefer: str = "rpc_replay") -> dict[str, Any]:
    if live:
        holders = current_holder_balances(ctx, token, exclude_kinds)
        res = concentration(holders, total_supply)
        res["source"] = "rpc_replay_full"
        return res
    holders, ts, src = snapshot_holder_balances(ctx, token, as_of_ts, exclude_kinds, prefer=prefer)
    res = concentration(holders, total_supply)
    res["source"] = src
    if holders:
        res["quality_flags"].append("topn_only")
    return res


def concentration_changes(ctx: IntelContext, token: str, as_of_ts: int, total_supply: int | None, current: dict[str, Any], exclude_kinds: set[str], windows: list[str] | None = None, prefer: str = "rpc_replay") -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for w in windows or ["1h", "6h", "24h"]:
        past_holders, _ts, _src = snapshot_holder_balances(ctx, token, as_of_ts - WINDOWS_SECONDS[w], exclude_kinds, max_age=max(1800, WINDOWS_SECONDS[w] // 2), prefer=prefer)
        past = concentration(past_holders, total_supply) if past_holders else None
        for n in (10, 20):
            key = f"top{n}_pct"
            out[f"{key}_change_{w}"] = (current.get(key) - past.get(key)) if (past and current.get(key) is not None and past.get(key) is not None) else None
    return out
