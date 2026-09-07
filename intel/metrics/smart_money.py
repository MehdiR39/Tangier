"""Smart-money scoring from a wallet's *observed* cross-token history. UNKNOWN until enough data."""
from __future__ import annotations

import statistics
from typing import Any

from intel.context import IntelContext
from intel.utils.timeutil import WINDOWS_SECONDS


def wallet_history_features(ctx: IntelContext, wallet: str, as_of_ts: int, params: dict[str, Any], memo: dict[str, Any] | None = None) -> dict[str, Any]:
    """``memo`` caches per-token values that do not depend on the wallet, across one evaluation.

    Without it a token's first-trade timestamp is re-queried once per wallet examined: profiled
    2026-09-04, 1 835 SQLite queries and 2.1 s for a single token's smart-money section.
    """
    memo = {} if memo is None else memo
    early_h = int(params.get("early_entry_hours", 6))
    success_x = float(params.get("success_multiple", 2.0))
    rows = ctx.db.query(
        "SELECT token_address, side, ts, usd_value, token_amount_float, price_usd FROM trades WHERE chain_id=? AND trader=? AND ts<=? AND side IN ('BUY','SELL') ORDER BY ts",
        (ctx.chain_id, wallet, as_of_ts),
    )
    by_token: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_token.setdefault(r["token_address"], []).append(dict(r))
    closed_returns: list[float] = []
    realized = 0.0
    early_success = 0
    early_total = 0
    rug_exposure = 0
    low_cap_success = 0
    for token, ts_rows in by_token.items():
        bought = sum(t["token_amount_float"] or 0 for t in ts_rows if t["side"] == "BUY")
        sold = sum(t["token_amount_float"] or 0 for t in ts_rows if t["side"] == "SELL")
        buy_usd = sum(t["usd_value"] or 0 for t in ts_rows if t["side"] == "BUY")
        sell_usd = sum(t["usd_value"] or 0 for t in ts_rows if t["side"] == "SELL")
        first_buy = next((t for t in ts_rows if t["side"] == "BUY"), None)
        if first_buy is None:
            continue
        if bought > 0 and sold >= 0.8 * bought and buy_usd > 0:
            ret = sell_usd / buy_usd - 1.0
            closed_returns.append(ret)
            realized += sell_usd - buy_usd
        # early entry: bought within early_h hours of the token's first observed trade (as of then)
        key = f"t0:{token}"
        if key not in memo:
            memo[key] = ctx.db.scalar("SELECT MIN(ts) FROM trades WHERE chain_id=? AND token_address=? AND ts<=?", (ctx.chain_id, token, as_of_ts))
        t0 = memo[key]
        if t0 is not None and first_buy["ts"] - int(t0) <= early_h * 3600 and first_buy.get("price_usd"):
            early_total += 1
            peak = ctx.db.scalar(
                "SELECT MAX(price_usd) FROM trades WHERE chain_id=? AND token_address=? AND ts>? AND ts<=?",
                (ctx.chain_id, token, first_buy["ts"], min(as_of_ts, first_buy["ts"] + WINDOWS_SECONDS["7d"])),
            )
            if peak and peak >= success_x * first_buy["price_usd"]:
                early_success += 1
                low_cap_success += 1
        # rug exposure: token later rejected/thesis-broken (as known at as_of)
        st = ctx.db.query_one("SELECT to_state FROM state_transitions WHERE chain_id=? AND token_address=? AND ts>? AND ts<=? AND to_state IN ('REJECTED','SECURITY_RISK','THESIS_BREAK') LIMIT 1", (ctx.chain_id, token, first_buy["ts"], as_of_ts))
        if st is not None:
            rug_exposure += 1
    n_tokens = len(by_token)
    return {
        "tokens_observed": n_tokens,
        "closed_positions": len(closed_returns),
        "hit_rate": (sum(1 for r in closed_returns if r > 0) / len(closed_returns)) if closed_returns else None,
        "median_return": statistics.median(closed_returns) if closed_returns else None,
        "realized_pnl_usd": realized if closed_returns else None,
        "early_entries": early_total,
        "early_entry_success_rate": (early_success / early_total) if early_total else None,
        "rug_exposure_rate": (rug_exposure / n_tokens) if n_tokens else None,
        "successful_low_cap_entries": low_cap_success,
    }


def smart_money_score(f: dict[str, Any], params: dict[str, Any]) -> tuple[float | None, list[str]]:
    if f["tokens_observed"] < int(params.get("min_tokens_observed", 5)) or f["closed_positions"] < int(params.get("min_closed_positions", 3)):
        return None, [f"insufficient history (tokens={f['tokens_observed']}, closed={f['closed_positions']})"]
    score = 50.0
    why: list[str] = []
    if f["hit_rate"] is not None:
        score += (f["hit_rate"] - 0.5) * 60
        why.append(f"hit_rate={f['hit_rate']:.2f}")
    if f["median_return"] is not None:
        score += max(-20.0, min(20.0, f["median_return"] * 20))
        why.append(f"median_return={f['median_return']:+.2f}")
    if f["early_entry_success_rate"] is not None:
        score += (f["early_entry_success_rate"] - 0.3) * 30
        why.append(f"early_success={f['early_entry_success_rate']:.2f}")
    if f["rug_exposure_rate"] is not None:
        score -= f["rug_exposure_rate"] * 30
        why.append(f"rug_exposure={f['rug_exposure_rate']:.2f}")
    return max(0.0, min(100.0, score)), why


def token_smart_money(ctx: IntelContext, token: str, as_of_ts: int, recent_buyers: list[str], params: dict[str, Any]) -> dict[str, Any]:
    """Aggregate smart-money presence among recent buyers. UNKNOWN when no buyer has enough history."""
    scored: list[tuple[str, float]] = []
    unknown = 0
    memo: dict[str, Any] = {}
    for w in recent_buyers[:40]:
        f = wallet_history_features(ctx, w, as_of_ts, params, memo)
        s, _ = smart_money_score(f, params)
        if s is None:
            unknown += 1
        else:
            scored.append((w, s))
    if not scored:
        return {"smart_money_score": None, "smart_money_status": "UNKNOWN", "n_scored": 0, "n_unknown": unknown, "smart_wallets": []}
    avg = sum(s for _, s in scored) / len(scored)
    smart = [w for w, s in scored if s >= 70]
    return {"smart_money_score": avg, "smart_money_status": "SCORED", "n_scored": len(scored), "n_unknown": unknown, "smart_wallets": smart[:10]}
