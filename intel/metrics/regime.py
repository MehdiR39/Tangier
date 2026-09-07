"""Market weather: BTC regime as a global risk switch for buy decisions.

The user's own July 2026 study (data_onchain/) concluded that selection signals only pay in
consolidation/bull regimes and that deploying in a bear regime destroys the edge. Memecoins
are the high-beta end of the same market: a day like 2026-09-03 (average ×1.23 across 535
tradeable launches) and a risk-off day are not the same game.

Source: Binance public daily klines (no key, same endpoint as scripts/daily_report.py).
Cached in ``api_cache`` so a failure never blocks the engine — unknown regime = permissive.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from intel.context import IntelContext
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)

CACHE_KEY = "regime:btc"
CACHE_TTL = 3600


def _sma(v: list[float], n: int) -> float | None:
    return sum(v[-n:]) / n if len(v) >= n else None


def _pct(v: list[float], n: int) -> float | None:
    return (v[-1] / v[-1 - n] - 1) if (len(v) > n and v[-1 - n]) else None


def classify(closes: list[float]) -> tuple[str, dict[str, Any]]:
    """bull / consolidation / bear, using the rule from the user's daily report."""
    if len(closes) < 100:
        return "unknown", {"reason": "not enough history"}
    ma100 = _sma(closes, 100)
    r90 = _pct(closes, 90)
    r30 = _pct(closes, 30)
    price = closes[-1]
    ev = {"price": price, "ma100": ma100, "return_90d": r90, "return_30d": r30}
    if r90 is None or ma100 is None:
        return "unknown", ev
    if r90 > 0.30 and price > ma100:
        return "bull", ev
    if r90 < -0.15 or (price < ma100 and r90 < 0):
        return "bear", ev
    return "consolidation", ev


async def btc_regime(ctx: IntelContext, *, force: bool = False) -> dict[str, Any]:
    cached = None if force else ctx.db.cache_get(CACHE_KEY, now_ts())
    if cached:
        return cached
    out: dict[str, Any] = {"regime": "unknown", "ts": now_ts(), "evidence": {}}
    try:
        async with httpx.AsyncClient(timeout=25, headers={"User-Agent": ctx.settings.user_agent}) as cli:
            r = await cli.get("https://data-api.binance.vision/api/v3/klines", params={"symbol": "BTCUSDT", "interval": "1d", "limit": 200})
            r.raise_for_status()
            closes = [float(k[4]) for k in r.json()]
        regime, ev = classify(closes)
        out = {"regime": regime, "ts": now_ts(), "evidence": ev}
    except Exception as exc:  # noqa: BLE001 - never let the weather break the engine
        log.warning("BTC regime unavailable: %s", exc)
        out["evidence"] = {"error": str(exc)[:120]}
    ctx.db.cache_set(CACHE_KEY, out, now_ts(), CACHE_TTL)
    return out


def cached_regime(ctx: IntelContext) -> str:
    """Last known regime without any network call ('unknown' when never fetched)."""
    c = ctx.db.cache_get(CACHE_KEY, now_ts())
    return (c or {}).get("regime", "unknown")


def buying_allowed(ctx: IntelContext) -> tuple[bool, str]:
    """Global risk switch used by the decision layer."""
    cfg = ctx.config.section("decisions")
    if not cfg.get("regime_gate_enabled", True):
        return True, "garde-fou de marché désactivé"
    regime = cached_regime(ctx)
    blocked = set(cfg.get("regime_block", ["bear"]))
    if regime in blocked:
        return False, "marché en tendance baissière (BTC) : pas de nouvel achat"
    return True, f"marché {regime}"
