"""Signal scorecard: what happened to the price after each sent alert (for the daily digest).

Point-in-time by construction: the price at alert time comes from the snapshot stored just
before the alert; the later price from the latest snapshot at or before the horizon.
"""
from __future__ import annotations

import statistics
from typing import Any

from intel.context import IntelContext
from intel.utils.timeutil import WINDOWS_SECONDS, now_ts


def _price_before(ctx: IntelContext, token: str, ts: int, max_age: int = 1800) -> float | None:
    row = ctx.db.query_one(
        "SELECT price_usd, ts FROM token_snapshots WHERE chain_id=? AND token_address=? AND price_usd IS NOT NULL AND ts<=? ORDER BY ts DESC LIMIT 1",
        (ctx.chain_id, token, ts),
    )
    if row is None or ts - int(row["ts"]) > max_age:
        return None
    return float(row["price_usd"])


def alert_outcomes(ctx: IntelContext, *, since_ts: int, until_ts: int | None = None, horizons: tuple[str, ...] = ("1h", "6h", "24h")) -> list[dict[str, Any]]:
    """One row per sent alert with price change at each horizon (None when not yet reachable)."""
    until_ts = until_ts or now_ts()
    rows = ctx.db.query(
        "SELECT a.ts, a.kind, a.severity, a.action, a.token_address, COALESCE(t.symbol, substr(a.token_address,1,10)) AS symbol "
        "FROM alerts a LEFT JOIN tokens t ON t.chain_id=a.chain_id AND t.address=a.token_address "
        "WHERE a.sent=1 AND a.token_address IS NOT NULL AND a.kind!='daily_digest' AND a.ts>=? AND a.ts<=? ORDER BY a.ts",
        (since_ts, until_ts),
    )
    out: list[dict[str, Any]] = []
    now = now_ts()
    for r in rows:
        p0 = _price_before(ctx, r["token_address"], int(r["ts"]) + 120)
        d: dict[str, Any] = {"ts": int(r["ts"]), "kind": r["kind"], "severity": r["severity"], "action": r["action"], "token": r["token_address"], "symbol": r["symbol"], "price_at_alert": p0}
        for h in horizons:
            t1 = int(r["ts"]) + WINDOWS_SECONDS[h]
            if p0 is None or t1 > now:
                d[f"ret_{h}"] = None
                continue
            p1 = _price_before(ctx, r["token_address"], t1, max_age=max(1800, WINDOWS_SECONDS[h] // 4))
            d[f"ret_{h}"] = (p1 / p0 - 1.0) if p1 else None
        p_now = _price_before(ctx, r["token_address"], now, max_age=6 * 3600)
        d["ret_now"] = (p_now / p0 - 1.0) if (p0 and p_now) else None
        out.append(d)
    return out


def summarize_by_kind(outcomes: list[dict[str, Any]], horizon: str = "24h") -> dict[str, dict[str, Any]]:
    groups: dict[str, list[float]] = {}
    for o in outcomes:
        v = o.get(f"ret_{horizon}")
        if v is None:
            continue
        key = f"{o['kind']}/{o['action']}"
        groups.setdefault(key, []).append(v)
    return {
        k: {"n": len(v), "median": statistics.median(v), "hit_up": sum(1 for x in v if x > 0.05) / len(v), "worst": min(v), "best": max(v)}
        for k, v in groups.items()
    }


def format_scorecard(outcomes: list[dict[str, Any]], horizon: str = "24h", max_rows: int = 12) -> list[str]:
    """Telegram-ready lines (HTML-safe content, no tags) for the digest."""
    lines: list[str] = []
    done = [o for o in outcomes if o.get(f"ret_{horizon}") is not None]
    if not done:
        pending = sum(1 for o in outcomes if o.get("price_at_alert") is not None)
        return [f"• {pending} alerte(s) encore trop récentes pour un bilan à {horizon}"]
    summary = summarize_by_kind(done, horizon)
    for key, s in sorted(summary.items(), key=lambda kv: -kv[1]["n"]):
        lines.append(f"• {key}: n={s['n']} · médiane {s['median']:+.0%} à {horizon} · en hausse {s['hit_up']:.0%} · pire {s['worst']:+.0%} / meilleur {s['best']:+.0%}")
    # the individual movers, biggest first
    movers = sorted(done, key=lambda o: -abs(o[f"ret_{horizon}"]))[:max_rows]
    if movers:
        lines.append("Plus gros mouvements après alerte :")
        for o in movers:
            lines.append(f"   {o['symbol']} ({o['kind']} → {o['action']}) {o[f'ret_{horizon}']:+.0%} à {horizon}" + (f", {o['ret_now']:+.0%} aujourd'hui" if o.get("ret_now") is not None else ""))
    return lines
