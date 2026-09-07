"""Backtesting: forward returns, MFE/MAE and survival for every persisted score.

Scores are computed point-in-time (``as_of_ts``); this module only *evaluates* them
against what happened afterwards. Optional replay recomputes scores at historical
snapshot times through the same feature builder with ``live=False`` so new weights can
be tested without leakage.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import statistics
from typing import Any

from intel import MODEL_VERSION
from intel.context import IntelContext
from intel.metrics.market import price_at
from intel.utils.timeutil import WINDOWS_SECONDS, now_ts

log = logging.getLogger(__name__)


def _price_path(ctx: IntelContext, token: str, start: int, end: int) -> list[tuple[int, float]]:
    rows = ctx.db.query(
        "SELECT ts, price_usd FROM token_snapshots WHERE chain_id=? AND token_address=? AND price_usd IS NOT NULL AND ts>? AND ts<=? "
        "UNION ALL SELECT ts, price_usd FROM trades WHERE chain_id=? AND token_address=? AND price_usd IS NOT NULL AND side IN ('BUY','SELL') AND usd_value>=5 AND ts>? AND ts<=? ORDER BY ts",
        (ctx.chain_id, token, start, end, ctx.chain_id, token, start, end),
    )
    return [(int(r["ts"]), float(r["price_usd"])) for r in rows]


def evaluate_score_row(ctx: IntelContext, row: dict[str, Any], horizons: list[str], retention: float, now: int) -> dict[str, Any]:
    token = row["token_address"]
    t0 = int(row["as_of_ts"])
    p0, _src, _ = price_at(ctx, token, t0, max_age=1800)
    out: dict[str, Any] = {"score_id": row["id"], "token": token, "as_of_ts": t0, "moonshot": row["moonshot"], "state": row["state"], "hard_filter_pass": row["hard_filter_pass"], "price0": p0, "model_version": row["model_version"]}
    liq0 = ctx.db.scalar("SELECT liquidity_usd FROM token_snapshots WHERE chain_id=? AND token_address=? AND liquidity_usd IS NOT NULL AND ts<=? ORDER BY ts DESC LIMIT 1", (ctx.chain_id, token, t0))
    for h in horizons:
        secs = WINDOWS_SECONDS[h]
        t1 = t0 + secs
        if t1 > now or p0 is None:
            out[f"fwd_{h}"] = None
            out[f"mfe_{h}"] = None
            out[f"mae_{h}"] = None
            continue
        p1, _, _ = price_at(ctx, token, t1, max_age=max(1800, secs // 4))
        out[f"fwd_{h}"] = (p1 / p0 - 1.0) if p1 else None
        path = _price_path(ctx, token, t0, t1)
        if path:
            hi = max(p for _, p in path)
            lo = min(p for _, p in path)
            out[f"mfe_{h}"] = hi / p0 - 1.0
            out[f"mae_{h}"] = lo / p0 - 1.0
        else:
            out[f"mfe_{h}"] = None
            out[f"mae_{h}"] = None
    # survival at 7d (or the longest horizon available)
    t7 = t0 + WINDOWS_SECONDS["7d"]
    if t7 <= now:
        liq7 = ctx.db.scalar("SELECT liquidity_usd FROM token_snapshots WHERE chain_id=? AND token_address=? AND liquidity_usd IS NOT NULL AND ts<=? AND ts>? ORDER BY ts DESC LIMIT 1", (ctx.chain_id, token, t7, t7 - 86400))
        rugged = ctx.db.query_one("SELECT 1 FROM state_transitions WHERE chain_id=? AND token_address=? AND ts>? AND ts<=? AND to_state IN ('REJECTED','SECURITY_RISK','THESIS_BREAK')", (ctx.chain_id, token, t0, t7)) is not None
        liq_ok = (liq0 is not None and liq7 is not None and liq7 >= retention * liq0)
        out["survived_7d"] = bool(liq_ok and not rugged)
        out["rugged_7d"] = bool(rugged or (liq0 and liq7 is not None and liq7 < 0.2 * liq0))
    else:
        out["survived_7d"] = None
        out["rugged_7d"] = None
    return out


def run_backtest(ctx: IntelContext, *, token: str | None = None, since_ts: int | None = None, model_version: str | None = None, out_dir: str | None = None, min_spacing: int = 3600) -> dict[str, Any]:
    horizons = list(ctx.config.get("backtest.horizons", ["1h", "6h", "24h", "3d", "7d"]))
    retention = float(ctx.config.get("backtest.survival_liquidity_retention", 0.5))
    now = now_ts()
    sql = "SELECT id, token_address, as_of_ts, moonshot, state, hard_filter_pass, model_version, survival, traction, asymmetry, distribution, organic_volume, rug_risk, narrative FROM token_scores WHERE chain_id=?"
    params: list[Any] = [ctx.chain_id]
    if token:
        sql += " AND token_address=?"
        params.append(token.lower())
    if since_ts:
        sql += " AND as_of_ts>=?"
        params.append(since_ts)
    if model_version:
        sql += " AND model_version=?"
        params.append(model_version)
    sql += " ORDER BY token_address, as_of_ts"
    rows = [dict(r) for r in ctx.db.query(sql, params)]
    # thin to one observation per token per min_spacing to avoid autocorrelated duplicates
    thinned: list[dict[str, Any]] = []
    last: dict[str, int] = {}
    for r in rows:
        if r["token_address"] not in last or int(r["as_of_ts"]) - last[r["token_address"]] >= min_spacing:
            thinned.append(r)
            last[r["token_address"]] = int(r["as_of_ts"])
    results = [dict(evaluate_score_row(ctx, r, horizons, retention, now), **{k: r[k] for k in ("survival", "traction", "asymmetry", "distribution", "organic_volume", "rug_risk", "narrative")}) for r in thinned]
    summary = summarize(results, horizons)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        stamp = now
        csv_path = os.path.join(out_dir, f"intel_backtest_{stamp}.csv")
        if results:
            with open(csv_path, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(results[0].keys()))
                w.writeheader()
                w.writerows(results)
        with open(os.path.join(out_dir, f"intel_backtest_{stamp}_summary.json"), "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=1, default=str)
        summary["csv"] = csv_path
    return summary


def summarize(results: list[dict[str, Any]], horizons: list[str]) -> dict[str, Any]:
    def bucket(v: float | None) -> str:
        if v is None:
            return "na"
        return f"{int(v // 10) * 10:02d}-{int(v // 10) * 10 + 9:02d}"

    out: dict[str, Any] = {"n": len(results), "model_version": MODEL_VERSION, "by_moonshot_decile": {}, "by_state": {}, "components_ic": {}}
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        groups.setdefault(bucket(r.get("moonshot")), []).append(r)
    for g, rs in sorted(groups.items()):
        entry: dict[str, Any] = {"n": len(rs)}
        for h in horizons:
            vals = [r[f"fwd_{h}"] for r in rs if r.get(f"fwd_{h}") is not None]
            if vals:
                entry[f"fwd_{h}_median"] = round(statistics.median(vals), 4)
                entry[f"fwd_{h}_mean"] = round(sum(vals) / len(vals), 4)
                entry[f"fwd_{h}_hit50"] = round(sum(1 for v in vals if v >= 0.5) / len(vals), 3)
                entry[f"fwd_{h}_n"] = len(vals)
            mfe = [r[f"mfe_{h}"] for r in rs if r.get(f"mfe_{h}") is not None]
            mae = [r[f"mae_{h}"] for r in rs if r.get(f"mae_{h}") is not None]
            if mfe:
                entry[f"mfe_{h}_median"] = round(statistics.median(mfe), 4)
            if mae:
                entry[f"mae_{h}_median"] = round(statistics.median(mae), 4)
        surv = [r["survived_7d"] for r in rs if r.get("survived_7d") is not None]
        rug = [r["rugged_7d"] for r in rs if r.get("rugged_7d") is not None]
        if surv:
            entry["survival_rate_7d"] = round(sum(surv) / len(surv), 3)
        if rug:
            entry["rug_rate_7d"] = round(sum(rug) / len(rug), 3)
        out["by_moonshot_decile"][g] = entry
    by_state: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_state.setdefault(r.get("state") or "?", []).append(r)
    for st, rs in by_state.items():
        vals = [r["fwd_24h"] for r in rs if r.get("fwd_24h") is not None]
        out["by_state"][st] = {"n": len(rs), "fwd_24h_median": round(statistics.median(vals), 4) if vals else None}
    # rank correlation of each component with 24h forward return (Spearman via ranks)
    for comp in ("moonshot", "survival", "traction", "asymmetry", "distribution", "organic_volume", "rug_risk", "narrative"):
        pairs = [(r[comp], r["fwd_24h"]) for r in results if r.get(comp) is not None and r.get("fwd_24h") is not None]
        out["components_ic"][comp] = round(spearman(pairs), 3) if len(pairs) >= 8 else None
    return out


def spearman(pairs: list[tuple[float, float]]) -> float:
    def ranks(vals: list[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    xs = ranks([p[0] for p in pairs])
    ys = ranks([p[1] for p in pairs])
    n = len(pairs)
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs) ** 0.5
    vy = sum((y - my) ** 2 for y in ys) ** 0.5
    return cov / (vx * vy) if vx and vy else 0.0


async def replay_scores(ctx: IntelContext, token: str, *, step_seconds: int = 3600, since_ts: int | None = None, until_ts: int | None = None) -> int:
    """Recompute scores at historical timestamps using only data available then (no alerts)."""
    from intel.alerts.dedup import AlertDeduper
    from intel.engines.pipeline import TokenPipeline
    from intel.metrics.pricing import QuotePricer

    token = token.lower()
    first = ctx.db.scalar("SELECT MIN(ts) FROM token_snapshots WHERE chain_id=? AND token_address=?", (ctx.chain_id, token))
    if first is None:
        return 0
    start = max(int(first), since_ts or 0)
    end = min(until_ts or now_ts(), now_ts())
    pipeline = TokenPipeline(ctx, QuotePricer(ctx), AlertDeduper(ctx.db, ctx.config.section("alerts"), ctx.chain_id), None)
    label = ctx.db.scalar("SELECT symbol FROM tokens WHERE chain_id=? AND address=?", (ctx.chain_id, token)) or token[:10]
    n = 0
    t = start
    while t <= end:
        await pipeline.evaluate(token, label, is_portfolio=False, deep=False, as_of_ts=t)
        n += 1
        t += step_seconds
    return n
