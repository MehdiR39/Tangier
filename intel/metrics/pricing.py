"""Quote-asset USD pricing with explicit data-quality flags.

Source priority: configured stables (fixed 1.0) > our own DexScreener snapshots of the
quote token nearest to the requested timestamp > current DexScreener price (flagged
``quote_price_approx``). Missing prices return ``None`` — never zero.
"""
from __future__ import annotations

import logging
from typing import Any

from intel.context import IntelContext

log = logging.getLogger(__name__)

NEAREST_WINDOW_SECONDS = 2 * 3600


class QuotePricer:
    def __init__(self, ctx: IntelContext) -> None:
        self.ctx = ctx
        self._current: dict[str, float] = {}
        self._decimals: dict[str, int] = {}
        for addr, meta in ctx.config.quote_assets.items():
            if meta.get("decimals") is not None:
                self._decimals[addr] = int(meta["decimals"])

    def set_current(self, quote_address: str, price_usd: float | None, decimals: int | None = None) -> None:
        if price_usd is not None and price_usd > 0:
            self._current[quote_address.lower()] = float(price_usd)
        if decimals is not None:
            self._decimals[quote_address.lower()] = int(decimals)

    def decimals(self, quote_address: str) -> int | None:
        return self._decimals.get(quote_address.lower())

    def usd_price(self, quote_address: str | None, ts: int | None = None) -> tuple[float | None, list[str]]:
        """Return (price, flags)."""
        if not quote_address:
            return None, ["quote_unknown"]
        addr = quote_address.lower()
        meta = self.ctx.quote_asset(addr)
        if meta and meta.get("kind") == "stable":
            return float(meta.get("usd", 1.0)), []
        if ts is not None:
            row = self.ctx.db.query_one(
                "SELECT price_usd, ts FROM token_snapshots WHERE chain_id=? AND token_address=? AND price_usd IS NOT NULL AND ts<=? ORDER BY ts DESC LIMIT 1",
                (self.ctx.chain_id, addr, ts),
            )
            if row is not None and ts - int(row["ts"]) <= NEAREST_WINDOW_SECONDS:
                return float(row["price_usd"]), []
            row2 = self.ctx.db.query_one(
                "SELECT price_usd, ts FROM token_snapshots WHERE chain_id=? AND token_address=? AND price_usd IS NOT NULL AND ts>? ORDER BY ts ASC LIMIT 1",
                (self.ctx.chain_id, addr, ts),
            )
            if row2 is not None and int(row2["ts"]) - ts <= NEAREST_WINDOW_SECONDS:
                return float(row2["price_usd"]), ["quote_price_forward_fill"]
        cur = self._current.get(addr)
        if cur is not None:
            return cur, ["quote_price_approx"] if ts is not None else []
        row = self.ctx.db.query_one(
            "SELECT price_usd FROM token_snapshots WHERE chain_id=? AND token_address=? AND price_usd IS NOT NULL ORDER BY ts DESC LIMIT 1",
            (self.ctx.chain_id, addr),
        )
        if row is not None:
            return float(row["price_usd"]), ["quote_price_approx"]
        return None, ["quote_price_missing"]


def safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def as_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
