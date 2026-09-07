"""DexScreener client. Market-data input only; never treated as ground truth.

Verified 2026-09-02: chain slug is ``robinhood``; pairs are Uniswap v4 pools whose
``pairAddress`` is the 32-byte PoolId. Documented limits: 300 req/min for pair/token
endpoints, 60 req/min for profiles/boosts.
"""
from __future__ import annotations

import logging
from typing import Any

from intel.db.connection import Database
from intel.providers.base import HttpProvider, ProviderStatusRegistry
from intel.settings import Settings
from intel.utils.ratelimit import RateLimiter

log = logging.getLogger(__name__)


class DexScreenerClient(HttpProvider):
    name = "dexscreener"

    def __init__(self, settings: Settings, status: ProviderStatusRegistry, db: Database | None = None) -> None:
        super().__init__(
            base_url=settings.dexscreener_url,
            user_agent=settings.user_agent,
            timeout=settings.http_timeout,
            limiter=RateLimiter(settings.limits.dexscreener_rpm / 60.0, burst=10, name="dexscreener"),
            concurrency=settings.limits.dexscreener_concurrency,
            status=status,
            db=db,
        )
        self.chain = settings.dexscreener_chain
        self._profiles_limiter = RateLimiter(settings.limits.dexscreener_profiles_rpm / 60.0, burst=3, name="dexscreener-profiles")

    def _only_chain(self, pairs: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        return [p for p in (pairs or []) if isinstance(p, dict) and p.get("chainId") == self.chain]

    async def token_pairs(self, token_address: str) -> list[dict[str, Any]]:
        data = await self._request_json("GET", f"{self.base_url}/token-pairs/v1/{self.chain}/{token_address}", label="dexscreener token-pairs")
        return self._only_chain(data if isinstance(data, list) else [])

    async def tokens(self, addresses: list[str]) -> list[dict[str, Any]]:
        """Best pair per token, up to 30 addresses per call (batched automatically)."""
        out: list[dict[str, Any]] = []
        uniq = list(dict.fromkeys(a.lower() for a in addresses))
        for i in range(0, len(uniq), 30):
            chunk = uniq[i: i + 30]
            data = await self._request_json("GET", f"{self.base_url}/tokens/v1/{self.chain}/{','.join(chunk)}", label="dexscreener tokens")
            out.extend(self._only_chain(data if isinstance(data, list) else []))
        return out

    async def pair(self, pair_id: str) -> dict[str, Any] | None:
        data = await self._request_json("GET", f"{self.base_url}/latest/dex/pairs/{self.chain}/{pair_id}", label="dexscreener pair")
        if not isinstance(data, dict):
            return None
        pairs = self._only_chain(data.get("pairs") or ([data["pair"]] if data.get("pair") else []))
        return pairs[0] if pairs else None

    async def search(self, query: str) -> list[dict[str, Any]]:
        data = await self._request_json("GET", f"{self.base_url}/latest/dex/search", params={"q": query}, label="dexscreener search")
        return self._only_chain((data or {}).get("pairs") if isinstance(data, dict) else [])

    async def _profiles_call(self, path: str) -> list[dict[str, Any]]:
        await self._profiles_limiter.acquire()
        data = await self._request_json("GET", f"{self.base_url}/{path}", label=f"dexscreener {path}")
        return [d for d in (data if isinstance(data, list) else []) if isinstance(d, dict) and d.get("chainId") == self.chain]

    async def token_profiles_latest(self) -> list[dict[str, Any]]:
        return await self._profiles_call("token-profiles/latest/v1")

    async def token_boosts_latest(self) -> list[dict[str, Any]]:
        return await self._profiles_call("token-boosts/latest/v1")

    async def token_boosts_top(self) -> list[dict[str, Any]]:
        return await self._profiles_call("token-boosts/top/v1")


# --------------------------------------------------------------------------- #
# normalisation helpers
# --------------------------------------------------------------------------- #
def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def normalize_pair(p: dict[str, Any]) -> dict[str, Any]:
    """Flatten a DexScreener pair object into our pair_snapshot column names."""
    txns = p.get("txns") or {}
    vol = p.get("volume") or {}
    pc = p.get("priceChange") or {}
    liq = p.get("liquidity") or {}
    base = p.get("baseToken") or {}
    quote = p.get("quoteToken") or {}
    info = p.get("info") or {}

    def tx(win: str, side: str) -> int | None:
        w = txns.get(win) or {}
        v = w.get(side)
        return int(v) if v is not None else None

    return {
        "pair_id": str(p.get("pairAddress") or "").lower(),
        "dex": p.get("dexId"),
        "labels": p.get("labels") or [],
        "url": p.get("url"),
        "base_address": str(base.get("address") or "").lower(),
        "base_symbol": base.get("symbol"),
        "base_name": base.get("name"),
        "quote_address": str(quote.get("address") or "").lower(),
        "quote_symbol": quote.get("symbol"),
        "price_usd": _f(p.get("priceUsd")),
        "price_native": _f(p.get("priceNative")),
        "liquidity_usd": _f(liq.get("usd")),
        "liquidity_base": _f(liq.get("base")),
        "liquidity_quote": _f(liq.get("quote")),
        "fdv": _f(p.get("fdv")),
        "market_cap": _f(p.get("marketCap")),
        "vol_5m": _f(vol.get("m5")),
        "vol_1h": _f(vol.get("h1")),
        "vol_6h": _f(vol.get("h6")),
        "vol_24h": _f(vol.get("h24")),
        "buys_5m": tx("m5", "buys"), "sells_5m": tx("m5", "sells"),
        "buys_1h": tx("h1", "buys"), "sells_1h": tx("h1", "sells"),
        "buys_6h": tx("h6", "buys"), "sells_6h": tx("h6", "sells"),
        "buys_24h": tx("h24", "buys"), "sells_24h": tx("h24", "sells"),
        "pc_5m": _f(pc.get("m5")), "pc_1h": _f(pc.get("h1")), "pc_6h": _f(pc.get("h6")), "pc_24h": _f(pc.get("h24")),
        "pair_created_ts": int(p["pairCreatedAt"] // 1000) if p.get("pairCreatedAt") else None,
        "websites": [w.get("url") for w in (info.get("websites") or []) if isinstance(w, dict)],
        "socials": [{"type": s.get("type"), "url": s.get("url")} for s in (info.get("socials") or []) if isinstance(s, dict)],
        "image_url": info.get("imageUrl"),
        "boosts_active": ((p.get("boosts") or {}).get("active") if isinstance(p.get("boosts"), dict) else None),
    }
