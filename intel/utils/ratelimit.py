"""Async token-bucket rate limiter, one instance per data provider."""
from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Token bucket: ``rate`` tokens per second with ``burst`` capacity.

    ``acquire`` blocks until a token is available. Safe for use from many tasks.
    """

    def __init__(self, rate: float, burst: int | None = None, name: str = "") -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        self.rate = float(rate)
        self.capacity = float(burst if burst is not None else max(1, int(rate)))
        self._tokens = self.capacity
        self._last = time.monotonic()
        self._lock: asyncio.Lock | None = None
        self.name = name
        self.waits = 0

    def _get_lock(self) -> asyncio.Lock:
        # created lazily so the limiter can be built outside of a running loop
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
        self._last = now

    async def acquire(self, tokens: float = 1.0) -> None:
        async with self._get_lock():
            while True:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                need = (tokens - self._tokens) / self.rate
                self.waits += 1
                await asyncio.sleep(max(need, 0.01))

    async def __aenter__(self) -> "RateLimiter":
        await self.acquire()
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def penalize(self, seconds: float) -> None:
        """Drain the bucket after a 429 so callers back off for ``seconds``."""
        self._refill()
        self._tokens = -abs(seconds) * self.rate
