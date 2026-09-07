"""Shared HTTP plumbing: per-provider rate limiting, retries, status tracking, caching."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from intel.db.connection import Database
from intel.utils.ratelimit import RateLimiter
from intel.utils.retry import FatalError, RetryableError, retry_async
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)


class BudgetExhausted(Exception):
    """Provider quota nearly used up; non-essential call skipped (caller degrades gracefully)."""


@dataclass
class ProviderState:
    provider: str
    last_ok_ts: int | None = None
    last_error_ts: int | None = None
    last_error: str | None = None
    consecutive_errors: int = 0
    calls_total: int = 0
    calls_failed: int = 0
    rate_limited_count: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    budget_remaining: int | None = None
    budget_reset_ts: int | None = None

    @property
    def avg_latency_ms(self) -> float | None:
        if not self.latencies_ms:
            return None
        return sum(self.latencies_ms) / len(self.latencies_ms)

    @property
    def healthy(self) -> bool:
        return self.consecutive_errors < 5

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "healthy": self.healthy,
            "last_ok_ts": self.last_ok_ts,
            "last_error_ts": self.last_error_ts,
            "last_error": self.last_error,
            "consecutive_errors": self.consecutive_errors,
            "calls_total": self.calls_total,
            "calls_failed": self.calls_failed,
            "rate_limited_count": self.rate_limited_count,
            "avg_latency_ms": round(self.avg_latency_ms, 1) if self.avg_latency_ms is not None else None,
            "budget_remaining": self.budget_remaining,
            "budget_reset_ts": self.budget_reset_ts,
        }


class ProviderStatusRegistry:
    """Data-source status monitoring; persisted to ``provider_status`` for health checks."""

    def __init__(self, db: Database | None = None) -> None:
        self.db = db
        self._states: dict[str, ProviderState] = {}

    def state(self, provider: str) -> ProviderState:
        if provider not in self._states:
            self._states[provider] = ProviderState(provider)
        return self._states[provider]

    def record_ok(self, provider: str, latency_ms: float) -> None:
        s = self.state(provider)
        s.calls_total += 1
        s.consecutive_errors = 0
        s.last_ok_ts = now_ts()
        s.latencies_ms.append(latency_ms)
        if len(s.latencies_ms) > 200:
            del s.latencies_ms[:100]
        self._persist(s)

    def record_error(self, provider: str, error: str, *, rate_limited: bool = False) -> None:
        s = self.state(provider)
        s.calls_total += 1
        s.calls_failed += 1
        s.consecutive_errors += 1
        s.last_error_ts = now_ts()
        s.last_error = error[:500]
        if rate_limited:
            s.rate_limited_count += 1
        self._persist(s)

    def record_budget(self, provider: str, remaining: int | None, reset_ts: int | None) -> None:
        s = self.state(provider)
        s.budget_remaining = remaining
        s.budget_reset_ts = reset_ts

    def _persist(self, s: ProviderState) -> None:
        if self.db is None:
            return
        try:
            self.db.execute(
                "INSERT INTO provider_status(provider,last_ok_ts,last_error_ts,last_error,consecutive_errors,calls_total,calls_failed,rate_limited_count,avg_latency_ms,updated_ts) "
                "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(provider) DO UPDATE SET last_ok_ts=excluded.last_ok_ts,last_error_ts=excluded.last_error_ts,"
                "last_error=excluded.last_error,consecutive_errors=excluded.consecutive_errors,calls_total=excluded.calls_total,calls_failed=excluded.calls_failed,"
                "rate_limited_count=excluded.rate_limited_count,avg_latency_ms=excluded.avg_latency_ms,updated_ts=excluded.updated_ts",
                (s.provider, s.last_ok_ts, s.last_error_ts, s.last_error, s.consecutive_errors, s.calls_total, s.calls_failed, s.rate_limited_count, s.avg_latency_ms, now_ts()),
            )
        except Exception:  # never let monitoring break ingestion
            log.debug("provider status persist failed", exc_info=True)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {k: v.as_dict() for k, v in self._states.items()}


class HttpProvider:
    """Base class: rate-limited, retried, status-tracked JSON HTTP calls with quota awareness."""

    name = "http"

    def __init__(
        self,
        *,
        base_url: str,
        user_agent: str,
        timeout: float,
        limiter: RateLimiter,
        concurrency: int,
        status: ProviderStatusRegistry,
        db: Database | None = None,
        extra_headers: dict[str, str] | None = None,
        reserve_calls: int = 0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.limiter = limiter
        self.sem = asyncio.Semaphore(max(1, concurrency))
        self.status = status
        self.db = db
        self.reserve_calls = reserve_calls
        self.budget_remaining: int | None = None
        self.budget_reset_ts: int | None = None
        headers = {"User-Agent": user_agent, "Accept": "application/json"}
        if extra_headers:
            headers.update(extra_headers)
        self._client = httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True)

    async def close(self) -> None:
        await self._client.aclose()

    def budget_ok(self, essential: bool) -> bool:
        if self.budget_remaining is None or essential:
            return True
        if self.budget_reset_ts and now_ts() >= self.budget_reset_ts:
            self.budget_remaining = None
            return True
        return self.budget_remaining > self.reserve_calls

    def _track_budget(self, resp: httpx.Response) -> None:
        rem = resp.headers.get("x-ratelimit-remaining")
        reset = resp.headers.get("x-ratelimit-reset")
        if rem is not None:
            try:
                self.budget_remaining = int(rem)
                self.budget_reset_ts = now_ts() + int(float(reset)) if reset else None
                self.status.record_budget(self.name, self.budget_remaining, self.budget_reset_ts)
            except ValueError:
                pass

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        attempts: int = 4,
        allow_404: bool = True,
        label: str = "",
        essential: bool = False,
    ) -> Any:
        if not self.budget_ok(essential):
            raise BudgetExhausted(f"{self.name} budget reserve reached (remaining={self.budget_remaining})")

        async def once() -> Any:
            await self.limiter.acquire()
            async with self.sem:
                t0 = time.monotonic()
                try:
                    resp = await self._client.request(method, url, params=params, json=json_body)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    self.status.record_error(self.name, f"transport: {exc}")
                    raise RetryableError(f"{self.name} transport error: {exc}") from exc
                latency = (time.monotonic() - t0) * 1000
            self._track_budget(resp)
            if resp.status_code == 429:
                ra = _retry_after(resp)
                self.limiter.penalize(ra)
                self.status.record_error(self.name, "429 rate limited", rate_limited=True)
                if self.budget_remaining is not None and self.budget_remaining <= 0:
                    raise FatalError(f"{self.name} quota exhausted until reset")
                raise RetryableError(f"{self.name} 429", retry_after=ra)
            if resp.status_code >= 500:
                self.status.record_error(self.name, f"{resp.status_code} {resp.text[:120]}")
                raise RetryableError(f"{self.name} {resp.status_code}")
            if resp.status_code == 404 and allow_404:
                self.status.record_ok(self.name, latency)
                return None
            if resp.status_code == 403 and "cf-mitigated" in {k.lower() for k in resp.headers.keys()}:
                self.status.record_error(self.name, "403 cloudflare challenge (check User-Agent / API key)")
                raise FatalError(f"{self.name} blocked by Cloudflare challenge")
            if resp.status_code >= 400:
                self.status.record_error(self.name, f"{resp.status_code} {resp.text[:120]}")
                raise FatalError(f"{self.name} {resp.status_code}: {resp.text[:200]}")
            try:
                data = resp.json()
            except json.JSONDecodeError as exc:
                self.status.record_error(self.name, "invalid json")
                raise RetryableError(f"{self.name} invalid JSON") from exc
            self.status.record_ok(self.name, latency)
            return data

        return await retry_async(once, attempts=attempts, label=label or f"{self.name} {url}")

    # ---- immutable-result cache --------------------------------------- #
    def _cache_get(self, key: str) -> Any:
        if self.db is None:
            return None
        return self.db.cache_get(f"{self.name}:{key}", now_ts())

    def _cache_set(self, key: str, value: Any, ttl: int | None) -> None:
        if self.db is None:
            return
        self.db.cache_set(f"{self.name}:{key}", value, now_ts(), ttl)


def _retry_after(resp: httpx.Response) -> float:
    ra = resp.headers.get("retry-after")
    try:
        return max(1.0, float(ra)) if ra else 5.0
    except ValueError:
        return 5.0
