"""Blockscout client (Robinhood Chain explorer) with v2 + legacy v1 endpoints.

Verified 2026-09-02: ``https://robinhoodchain.blockscout.com`` sits behind a Cloudflare
managed challenge that rejects generic clients; a browser-like User-Agent passes.
Rate-limit headers reported ``x-ratelimit-limit: 180``. An ``apikey`` query parameter
is added when ``INTEL_BLOCKSCOUT_API_KEY`` is configured.
"""
from __future__ import annotations

import logging
from typing import Any

from intel.db.connection import Database
from intel.providers.base import HttpProvider, ProviderStatusRegistry
from intel.settings import Settings
from intel.utils.ratelimit import RateLimiter
from intel.utils.retry import FatalError

log = logging.getLogger(__name__)

TTL_CONTRACT = 6 * 3600
TTL_ADDRESS = 3600
TTL_TOKEN = 900


class BlockscoutClient(HttpProvider):
    name = "blockscout"

    def __init__(self, settings: Settings, status: ProviderStatusRegistry, db: Database | None = None) -> None:
        super().__init__(
            base_url=settings.blockscout_url,
            user_agent=settings.user_agent if "Mozilla" in settings.user_agent else f"Mozilla/5.0 (compatible; {settings.user_agent})",
            timeout=settings.http_timeout,
            limiter=RateLimiter(settings.limits.blockscout_rpm / 60.0, burst=5, name="blockscout"),
            concurrency=settings.limits.blockscout_concurrency,
            status=status,
            db=db,
            reserve_calls=settings.limits.blockscout_reserve_calls,
        )
        self.api_key = settings.blockscout_api_key
        self.enabled = bool(settings.blockscout_url)

    def _params(self, params: dict[str, Any] | None) -> dict[str, Any]:
        p = dict(params or {})
        if self.api_key:
            p["apikey"] = self.api_key
        return p

    async def get_v2(self, path: str, params: dict[str, Any] | None = None, *, essential: bool = False) -> Any:
        """``essential`` calls bypass the quota reserve (immutable data cached for hours)."""
        if not self.enabled:
            return None
        url = f"{self.base_url}/api/v2/{path.lstrip('/')}"
        return await self._request_json("GET", url, params=self._params(params), label=f"blockscout {path}", essential=essential)

    async def get_v1(self, params: dict[str, Any], *, essential: bool = False) -> Any:
        if not self.enabled:
            return None
        url = f"{self.base_url}/api"
        return await self._request_json("GET", url, params=self._params(params), label="blockscout v1", essential=essential)

    async def _paged(self, path: str, params: dict[str, Any] | None, max_pages: int, stop: Any = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_params: dict[str, Any] | None = None
        for _ in range(max(1, max_pages)):
            p = dict(params or {})
            if next_params:
                p.update(next_params)
            data = await self.get_v2(path, p)
            if not data or not isinstance(data, dict):
                break
            page = data.get("items") or []
            items.extend(page)
            if stop is not None and page and stop(page):
                break
            next_params = data.get("next_page_params")
            if not next_params:
                break
        return items

    # ---- tokens ---------------------------------------------------------- #
    async def token(self, address: str) -> dict[str, Any] | None:
        key = f"token:{address.lower()}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        data = await self.get_v2(f"tokens/{address}")
        if data:
            self._cache_set(key, data, TTL_TOKEN)
        return data

    async def token_counters(self, address: str) -> dict[str, Any] | None:
        return await self.get_v2(f"tokens/{address}/counters")

    async def token_holders(self, address: str, max_pages: int = 2) -> list[dict[str, Any]]:
        return await self._paged(f"tokens/{address}/holders", None, max_pages)

    async def token_transfers(self, address: str, max_pages: int = 1, stop_before_block: int | None = None) -> list[dict[str, Any]]:
        stop = (lambda page: stop_before_block is not None and min(int(i.get("block_number") or 0) for i in page) < stop_before_block)
        return await self._paged(f"tokens/{address}/transfers", None, max_pages, stop=stop)

    async def token_first_transfers(self, address: str, n: int = 50) -> list[dict[str, Any]]:
        """Earliest transfers via the legacy ``tokentx`` module (ascending)."""
        data = await self.get_v1({"module": "account", "action": "tokentx", "contractaddress": address, "startblock": 0, "endblock": 99999999, "page": 1, "offset": n, "sort": "asc"})
        if not data or str(data.get("status")) != "1" or not isinstance(data.get("result"), list):
            return []
        return data["result"]

    # ---- addresses / contracts ------------------------------------------ #
    async def address(self, address: str) -> dict[str, Any] | None:
        key = f"address:{address.lower()}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        data = await self.get_v2(f"addresses/{address}", essential=True)
        if data:
            self._cache_set(key, data, TTL_ADDRESS)
        return data

    async def smart_contract(self, address: str) -> dict[str, Any] | None:
        key = f"contract:{address.lower()}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        try:
            data = await self.get_v2(f"smart-contracts/{address}", essential=True)
        except FatalError:
            data = None
        if data:
            slim = {k: v for k, v in data.items() if k not in ("source_code", "additional_sources", "deployed_bytecode", "creation_bytecode", "file_path")}
            slim["deployed_bytecode"] = data.get("deployed_bytecode")
            self._cache_set(key, slim, TTL_CONTRACT)
            return slim
        return data

    async def address_token_transfers(self, address: str, token: str | None = None, max_pages: int = 2) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"type": "ERC-20"}
        if token:
            params["token"] = token
        return await self._paged(f"addresses/{address}/token-transfers", params, max_pages)

    async def address_transactions(self, address: str, max_pages: int = 1) -> list[dict[str, Any]]:
        return await self._paged(f"addresses/{address}/transactions", None, max_pages)

    async def address_tokens(self, address: str) -> list[dict[str, Any]]:
        return await self._paged(f"addresses/{address}/tokens", {"type": "ERC-20"}, 3)

    async def address_counters(self, address: str) -> dict[str, Any] | None:
        return await self.get_v2(f"addresses/{address}/counters")

    async def search(self, q: str) -> list[dict[str, Any]]:
        data = await self.get_v2("search", {"q": q})
        return (data or {}).get("items", []) if isinstance(data, dict) else []

    async def stats(self) -> dict[str, Any] | None:
        return await self.get_v2("stats")

    # ---- logs (v1 module, supports topic filters) ------------------------ #
    async def logs(self, address: str, topic0: str, topic1: str | None = None, from_block: int = 0, to_block: int | str = "latest") -> list[dict[str, Any]]:
        params: dict[str, Any] = {"module": "logs", "action": "getLogs", "fromBlock": from_block, "toBlock": to_block, "address": address, "topic0": topic0}
        if topic1:
            params["topic1"] = topic1
            params["topic0_1_opr"] = "and"
        data = await self.get_v1(params)
        if not data or not isinstance(data.get("result"), list):
            return []
        out = []
        for lg in data["result"]:
            out.append(
                {
                    "address": lg.get("address"),
                    "topics": lg.get("topics") or [],
                    "data": lg.get("data") or "0x",
                    "blockNumber": lg.get("blockNumber"),
                    "transactionHash": lg.get("transactionHash"),
                    "logIndex": lg.get("logIndex") or "0x0",
                    "timeStamp": lg.get("timeStamp"),
                }
            )
        return out
