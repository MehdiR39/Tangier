"""Holder growth, acceleration and price/holder divergences (point-in-time)."""
from __future__ import annotations

from typing import Any

from intel.context import IntelContext
from intel.utils.timeutil import WINDOWS_SECONDS


def holder_series(ctx: IntelContext, token: str, as_of_ts: int, lookback: int = 8 * 86400, *, prefer_replay: bool = True) -> list[tuple[int, int, int | None, str]]:
    """(ts, holder_count, holder_count_ex_system, source).

    RPC replay counts are exact only when the token's transfer history is complete; with a
    partial window they undercount (holders that never moved are invisible), so callers
    pass ``prefer_replay=False`` and the explorer (Blockscout) series is used instead.
    """
    rows = ctx.db.query(
        "SELECT ts, holder_count, holder_count_ex_system, source FROM holder_count_snapshots WHERE chain_id=? AND token_address=? AND ts<=? AND ts>=? AND holder_count IS NOT NULL ORDER BY ts",
        (ctx.chain_id, token.lower(), as_of_ts, as_of_ts - lookback),
    )
    replay = [(int(r["ts"]), int(r["holder_count"]), r["holder_count_ex_system"], r["source"]) for r in rows if r["source"].startswith("rpc")]
    explorer = [(int(r["ts"]), int(r["holder_count"]), r["holder_count_ex_system"], r["source"]) for r in rows if not r["source"].startswith("rpc")]
    if prefer_replay and replay:
        return replay
    if explorer:
        return explorer
    return replay


def _at(series: list[tuple[int, int, int | None, str]], ts: int, max_age: int) -> int | None:
    best = None
    for row in series:
        if row[0] <= ts:
            best = row
        else:
            break
    if best is None or ts - best[0] > max_age:
        return None
    return best[1]


def holder_growth(series: list[tuple[int, int, int | None, str]], as_of_ts: int, windows: list[str] | None = None, acceleration_window: str = "1h") -> dict[str, Any]:
    windows = windows or ["5m", "1h", "6h", "24h"]
    out: dict[str, Any] = {"holder_count": None, "quality_flags": []}
    now = _at(series, as_of_ts, 3600)
    if now is None:
        out["quality_flags"].append("holder_count_stale_or_missing")
        for w in windows:
            out[f"new_holders_{w}"] = None
            out[f"holder_growth_rate_{w}"] = None
        out["holder_growth_acceleration"] = None
        out["source"] = None
        return out
    out["holder_count"] = now
    out["source"] = series[-1][3] if series else None
    for w in windows:
        secs = WINDOWS_SECONDS[w]
        then = _at(series, as_of_ts - secs, max(900, secs // 2))
        if then is None:
            out[f"net_holder_growth_{w}"] = None
            out[f"holder_growth_rate_{w}"] = None
        else:
            out[f"net_holder_growth_{w}"] = now - then
            out[f"holder_growth_rate_{w}"] = (now / then - 1.0) if then else None
    # acceleration: growth in the latest window vs the preceding window of the same length
    secs = WINDOWS_SECONDS[acceleration_window]
    t1 = _at(series, as_of_ts - secs, max(900, secs // 2))
    t2 = _at(series, as_of_ts - 2 * secs, max(900, secs // 2))
    if t1 is not None and t2 is not None:
        g_recent = now - t1
        g_prev = t1 - t2
        out["holder_growth_acceleration"] = (g_recent - g_prev) / max(1, abs(g_prev)) if g_prev != 0 else (float(g_recent) if g_recent else 0.0)
        out["holder_growth_recent"] = g_recent
        out["holder_growth_previous"] = g_prev
    else:
        out["holder_growth_acceleration"] = None
    return out


def new_and_lost_holders(ctx: IntelContext, token: str, as_of_ts: int, windows: list[str] | None = None) -> dict[str, Any]:
    """Exact new/lost counts from the replayed holders table (valid for as_of ≈ now only)."""
    windows = windows or ["5m", "1h", "6h", "24h"]
    out: dict[str, Any] = {}
    for w in windows:
        since = as_of_ts - WINDOWS_SECONDS[w]
        new = ctx.db.scalar(
            "SELECT COUNT(*) FROM holders WHERE chain_id=? AND token_address=? AND is_system=0 AND first_seen_ts>=? AND first_seen_ts<=? AND CAST(balance AS INTEGER)>0",
            (ctx.chain_id, token.lower(), since, as_of_ts), 0,
        )
        lost = ctx.db.scalar(
            "SELECT COUNT(*) FROM holders WHERE chain_id=? AND token_address=? AND is_system=0 AND last_change_ts>=? AND last_change_ts<=? AND CAST(balance AS INTEGER)<=0",
            (ctx.chain_id, token.lower(), since, as_of_ts), 0,
        )
        out[f"new_holders_{w}"] = int(new)
        out[f"lost_holders_{w}"] = int(lost)
    return out


def divergences(ret: dict[str, Any], growth: dict[str, Any], *, price_move: float = 0.05, holder_move: float = 0.03) -> list[str]:
    """Named divergences between price and holder behaviour over 6h/24h."""
    out: list[str] = []
    for w in ("6h", "24h"):
        r = ret.get(f"return_{w}")
        h = growth.get(f"holder_growth_rate_{w}")
        if r is None or h is None:
            continue
        if r <= -price_move and h >= holder_move:
            out.append(f"price_down_holders_up_{w}")
        if abs(r) < price_move and (growth.get("holder_growth_acceleration") or 0) > 0.5 and h >= holder_move:
            out.append(f"price_flat_holders_accelerating_{w}")
        if r >= price_move and h <= -holder_move:
            out.append(f"price_up_holders_down_{w}")
    return out
