"""Exponential backoff with jitter for async callables."""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Awaitable, Callable, Iterable, TypeVar

T = TypeVar("T")
log = logging.getLogger(__name__)


class RetryableError(Exception):
    """Raise to signal that an operation may be retried (e.g. 429/5xx/timeouts)."""

    def __init__(self, msg: str, retry_after: float | None = None) -> None:
        super().__init__(msg)
        self.retry_after = retry_after


class FatalError(Exception):
    """Raise to abort retries immediately (e.g. 4xx that will never succeed)."""


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = 5,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    retry_on: Iterable[type[BaseException]] = (RetryableError, asyncio.TimeoutError, OSError),
    label: str = "",
) -> T:
    retry_on = tuple(retry_on)
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return await fn()
        except FatalError:
            raise
        except retry_on as exc:  # type: ignore[misc]
            last = exc
            if i == attempts - 1:
                break
            delay = min(max_delay, base_delay * (2 ** i)) * (0.5 + random.random())
            ra = getattr(exc, "retry_after", None)
            if ra:
                delay = max(delay, float(ra))
            log.warning("retry label=%s attempt=%d/%d delay=%.2fs err=%s", label, i + 1, attempts, delay, exc)
            await asyncio.sleep(delay)
    assert last is not None
    raise last
