"""JSON-RPC client for Robinhood Chain (read-only).

Verified behaviour of the public endpoint (2026-09-02): requires a non-default
User-Agent (python-urllib gets 403), batch requests return 429, ``eth_getLogs`` caps at
10 000 logs and times out beyond ~100k blocks. The client therefore never batches and
chunks log queries adaptively.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncIterator, Sequence

import httpx

from intel.db.connection import Database
from intel.providers.base import ProviderStatusRegistry
from intel.settings import Settings
from intel.utils.abi import hex_to_int
from intel.utils.ratelimit import RateLimiter
from intel.utils.retry import FatalError, RetryableError, retry_async

log = logging.getLogger(__name__)


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"rpc error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


class CallReverted(RpcError):
    pass


class LogQueryTooLarge(RpcError):
    pass


_TOO_LARGE_MARKERS = ("exceeds limit", "timed out", "too many", "query returned more", "range too large", "limit exceeded", "block range")


class RpcClient:
    name = "rpc"

    def __init__(self, settings: Settings, status: ProviderStatusRegistry, db: Database | None = None) -> None:
        self.settings = settings
        self.status = status
        self.db = db
        self.urls = [settings.rpc_url]
        if settings.rpc_fallback_url and settings.rpc_fallback_url not in self.urls:
            self.urls.append(settings.rpc_fallback_url)
        self._url_index = 0
        self.limiter = RateLimiter(settings.limits.rpc_rps, burst=int(max(1, settings.limits.rpc_rps)), name="rpc")
        self.sem = asyncio.Semaphore(settings.limits.rpc_concurrency)
        self._client = httpx.AsyncClient(
            timeout=settings.http_timeout,
            headers={"User-Agent": settings.user_agent, "Content-Type": "application/json"},
        )
        self._id = 0
        self._penalty = 2.0
        self._block_ts_cache: dict[int, int] = {}
        self._exact_ts: dict[int, int] = {}
        self._chain_id: int | None = None
        self.block_time_hint = 0.1  # seconds; Robinhood Chain measured ~0.10s

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ #
    async def request(self, method: str, params: Sequence[Any] = (), *, attempts: int = 5, timeout: float | None = None) -> Any:
        async def once() -> Any:
            self._id += 1
            payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": list(params)}
            url = self.urls[self._url_index % len(self.urls)]
            await self.limiter.acquire()
            async with self.sem:
                t0 = time.monotonic()
                try:
                    resp = await self._client.post(url, json=payload, timeout=timeout or self.settings.http_timeout)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    self.status.record_error(self.name, f"transport: {exc}")
                    self._rotate()
                    raise RetryableError(f"rpc transport error: {exc}") from exc
                latency = (time.monotonic() - t0) * 1000
            if resp.status_code == 429:
                # the public endpoint throttles per heavy query rather than per second: a long
                # pause does not buy more throughput, so keep the backoff short and bounded
                self._penalty = min(10.0, self._penalty * 1.3)
                self.limiter.penalize(self._penalty)
                self.status.record_error(self.name, "429", rate_limited=True)
                raise RetryableError("rpc 429", retry_after=self._penalty)
            if resp.status_code >= 500:
                self.status.record_error(self.name, f"http {resp.status_code}")
                self._rotate()
                raise RetryableError(f"rpc http {resp.status_code}")
            if resp.status_code >= 400:
                self.status.record_error(self.name, f"http {resp.status_code} {resp.text[:100]}")
                raise FatalError(f"rpc http {resp.status_code}: {resp.text[:200]}")
            try:
                body = resp.json()
            except ValueError as exc:
                self.status.record_error(self.name, "invalid json")
                raise RetryableError("rpc invalid json") from exc
            if "error" in body and body["error"]:
                err = body["error"]
                code = int(err.get("code", -1))
                msg = str(err.get("message", ""))
                low = msg.lower()
                if method == "eth_getLogs" and any(m in low for m in _TOO_LARGE_MARKERS):
                    self.status.record_ok(self.name, latency)
                    raise LogQueryTooLarge(code, msg, err.get("data"))
                if "revert" in low or code == 3:
                    self.status.record_ok(self.name, latency)
                    raise CallReverted(code, msg, err.get("data"))
                if code in (-32005, -32603) or "limit" in low or "capacity" in low:
                    self.status.record_error(self.name, msg, rate_limited=True)
                    raise RetryableError(f"rpc {msg}")
                # transient upstream failures behind the public gateway (observed:
                # 'Post "http://10.x:8547/rpc": dial tcp ... connection refused')
                if any(m in low for m in ("dial tcp", "connection refused", "connection reset", "upstream", "eof", "timeout", "temporarily", "unavailable", "bad gateway")):
                    self.status.record_error(self.name, msg[:120])
                    self._rotate()
                    raise RetryableError(f"rpc upstream: {msg[:120]}", retry_after=3.0)
                self.status.record_error(self.name, msg)
                raise RpcError(code, msg, err.get("data"))
            self.status.record_ok(self.name, latency)
            self._penalty = max(2.0, self._penalty * 0.9)  # decay the 429 penalty on success
            return body.get("result")

        return await retry_async(once, attempts=attempts, retry_on=(RetryableError,), label=f"rpc {method}")

    def _rotate(self) -> None:
        if len(self.urls) > 1:
            self._url_index += 1

    # ------------------------------------------------------------------ #
    async def chain_id(self) -> int:
        if self._chain_id is None:
            self._chain_id = int(await self.request("eth_chainId"), 16)
        return self._chain_id

    async def block_number(self) -> int:
        return int(await self.request("eth_blockNumber"), 16)

    async def get_block(self, number: int | str, full: bool = False) -> dict[str, Any] | None:
        tag = number if isinstance(number, str) else hex(number)
        return await self.request("eth_getBlockByNumber", [tag, full])

    async def block_timestamp(self, number: int) -> int:
        if number in self._block_ts_cache:
            return self._block_ts_cache[number]
        if self.db is not None:
            row = self.db.query_one("SELECT ts FROM block_timestamps WHERE chain_id=? AND block_number=?", (self.settings.chain_id, number))
            if row is not None:
                self._block_ts_cache[number] = int(row["ts"])
                return int(row["ts"])
        blk = await self.get_block(number)
        if blk is None:
            raise RpcError(-1, f"block {number} not found")
        ts = int(blk["timestamp"], 16)
        self.remember_block_timestamp(number, ts)
        return ts

    def remember_block_timestamp(self, number: int, ts: int) -> None:
        self._block_ts_cache[number] = ts
        self._exact_ts[number] = ts
        if len(self._block_ts_cache) > 50000:
            self._block_ts_cache.clear()
        if len(self._exact_ts) > 20000:
            self._exact_ts.clear()
        if self.db is not None:
            try:
                self.db.execute(
                    "INSERT OR IGNORE INTO block_timestamps(chain_id, block_number, ts) VALUES (?,?,?)",
                    (self.settings.chain_id, number, ts),
                )
            except Exception:
                log.debug("block ts persist failed", exc_info=True)

    async def block_timestamps(self, numbers: Sequence[int], *, max_gap: int = 10_000) -> dict[int, int]:
        """Resolve many block timestamps with at most one RPC call per ``max_gap`` blocks.

        Exact anchors (memory + ``block_timestamps`` table) bracket each requested block; if
        the bracket is narrower than ``max_gap`` the timestamp is linearly interpolated
        (block time ~0.1 s, error of a few seconds at most), otherwise the block itself is
        fetched and becomes a new anchor. Interpolated values are cached in memory only.
        """
        wanted = sorted(set(int(n) for n in numbers))
        out: dict[int, int] = {}
        if not wanted:
            return out
        anchors: dict[int, int] = {}
        if self.db is not None:
            rows = self.db.query(
                "SELECT block_number, ts FROM block_timestamps WHERE chain_id=? AND block_number BETWEEN ? AND ?",
                (self.settings.chain_id, wanted[0] - max_gap, wanted[-1] + max_gap),
            )
            for r in rows:
                anchors[int(r["block_number"])] = int(r["ts"])
        for n, ts in self._exact_ts.items():
            if wanted[0] - max_gap <= n <= wanted[-1] + max_gap:
                anchors[n] = ts
        keys = sorted(anchors)
        import bisect

        async def fetch_anchor(block: int) -> int | None:
            try:
                ts = await self.block_timestamp(block)
            except Exception as exc:
                log.debug("block timestamp fetch failed %d: %s", block, exc)
                return None
            anchors[block] = ts
            bisect.insort(keys, block)
            return ts

        last = wanted[-1]
        for n in wanted:
            if n in anchors:
                out[n] = anchors[n]
                continue
            if n in self._block_ts_cache:
                out[n] = self._block_ts_cache[n]
                continue
            i = bisect.bisect_left(keys, n)
            lo = keys[i - 1] if i > 0 else None
            hi = keys[i] if i < len(keys) else None
            if lo is None or n - lo > max_gap:
                # no usable anchor below: fetch this block exactly
                ts = await fetch_anchor(n)
                if ts is None:
                    if lo is not None:
                        out[n] = anchors[lo] + int((n - lo) * self.block_time_hint)
                    continue
                out[n] = ts
                continue
            if hi is None or hi - lo > max_gap:
                # fetch a forward anchor so the whole next max_gap span interpolates
                target = min(last, lo + max_gap)
                if target < n:
                    target = n
                ts = await fetch_anchor(target)
                if ts is None:
                    out[n] = anchors[lo] + int((n - lo) * self.block_time_hint)
                    continue
                if target == n:
                    out[n] = ts
                    continue
                hi = target
            frac = (n - lo) / (hi - lo)
            ts = int(anchors[lo] + frac * (anchors[hi] - anchors[lo]))
            out[n] = ts
            self._block_ts_cache[n] = ts
        return out

    async def block_by_timestamp(self, ts: int, *, head: int | None = None, tolerance_blocks: int = 50) -> int:
        """First block with timestamp >= ``ts`` via binary search (about 20 calls worst case).

        A first guess from the measured block time narrows the window so typical lookups
        need far fewer calls; anchors are cached in ``block_timestamps``.
        """
        head = head if head is not None else await self.block_number()
        head_ts = await self.block_timestamp(head)
        if ts >= head_ts:
            return head
        guess = head - int((head_ts - ts) / max(self.block_time_hint, 0.01))
        span = max(200_000, int(abs(head - guess) * 0.2))
        lo, hi = max(0, guess - span), min(head, guess + span)
        try:
            if not (await self.block_timestamp(lo) <= ts <= await self.block_timestamp(hi)):
                lo, hi = 0, head
        except Exception:
            lo, hi = 0, head
        while hi - lo > tolerance_blocks:
            mid = (lo + hi) // 2
            if await self.block_timestamp(mid) < ts:
                lo = mid + 1
            else:
                hi = mid
        return lo

    async def call(self, to: str, data: str, block: int | str = "latest", *, from_address: str | None = None) -> str:
        tag = block if isinstance(block, str) else hex(block)
        tx: dict[str, Any] = {"to": to, "data": data}
        if from_address:
            tx["from"] = from_address
        res = await self.request("eth_call", [tx, tag], attempts=3)
        return res if isinstance(res, str) else "0x"

    async def try_call(self, to: str, data: str, block: int | str = "latest", *, from_address: str | None = None) -> str | None:
        try:
            out = await self.call(to, data, block, from_address=from_address)
            return out if out and out != "0x" else None
        except (CallReverted, RpcError):
            return None
        except FatalError:
            return None

    async def get_code(self, address: str) -> str:
        return await self.request("eth_getCode", [address, "latest"])

    async def get_storage_at(self, address: str, slot: str, block: int | str = "latest") -> str:
        tag = block if isinstance(block, str) else hex(block)
        return await self.request("eth_getStorageAt", [address, slot, tag])

    async def get_transaction_receipt(self, tx_hash: str) -> dict[str, Any] | None:
        return await self.request("eth_getTransactionReceipt", [tx_hash])

    async def get_transaction(self, tx_hash: str) -> dict[str, Any] | None:
        return await self.request("eth_getTransactionByHash", [tx_hash])

    async def get_logs(
        self,
        *,
        address: str | list[str] | None,
        topics: Sequence[Any] | None,
        from_block: int,
        to_block: int,
        timeout: float | None = 90.0,
    ) -> list[dict[str, Any]]:
        flt: dict[str, Any] = {"fromBlock": hex(from_block), "toBlock": hex(to_block)}
        if address:
            flt["address"] = address
        if topics:
            flt["topics"] = list(topics)
        res = await self.request("eth_getLogs", [flt], attempts=3, timeout=timeout)
        return res or []

    async def iter_logs(
        self,
        *,
        address: str | list[str] | None,
        topics: Sequence[Any] | None,
        from_block: int,
        to_block: int,
        chunk: int = 20000,
        min_chunk: int = 250,
    ) -> AsyncIterator[tuple[int, int, list[dict[str, Any]]]]:
        """Yield ``(chunk_from, chunk_to, logs)`` walking forward.

        Chunk size adapts to observed log density (target ~4000 logs per call) so dense
        launch periods use small windows and quiet periods large ones. An over-large query
        is followed by a short cool-down because the public RPC weighs heavy queries.
        """
        target_logs = 4000
        cur = from_block
        size = max(min_chunk, chunk)
        while cur <= to_block:
            end = min(to_block, cur + size - 1)
            try:
                logs = await self.get_logs(address=address, topics=topics, from_block=cur, to_block=end)
            except LogQueryTooLarge:
                if size <= min_chunk:
                    raise
                size = max(min_chunk, size // 4)
                log.info("rpc getLogs chunk too large, shrinking to %d blocks", size)
                await asyncio.sleep(1.5)
                continue
            yield cur, end, logs
            used = end - cur + 1
            cur = end + 1
            n = len(logs)
            if n >= 2000:
                await asyncio.sleep(1.0)  # heavy result: let the weighted rate limit recover
            if n >= target_logs:
                density = n / max(1, used)  # logs per block over this chunk
                size = max(min_chunk, min(chunk, int(target_logs / max(density, 1e-9))))
            elif n < target_logs // 4 and size < chunk:
                size = min(chunk, size * 2)


def log_block_number(lg: dict[str, Any]) -> int:
    return int(lg["blockNumber"], 16) if isinstance(lg["blockNumber"], str) else int(lg["blockNumber"])


def log_index(lg: dict[str, Any]) -> int:
    v = lg.get("logIndex")
    return int(v, 16) if isinstance(v, str) else int(v or 0)


def hexint(v: Any) -> int | None:
    return hex_to_int(v) if isinstance(v, str) else (int(v) if v is not None else None)
