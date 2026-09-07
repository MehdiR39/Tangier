"""UTC time helpers. Everything internal is an integer unix timestamp (seconds, UTC)."""
from __future__ import annotations

import datetime as dt

WINDOWS_SECONDS: dict[str, int] = {
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "6h": 21600,
    "24h": 86400,
    "3d": 3 * 86400,
    "7d": 7 * 86400,
}


def now_ts() -> int:
    return int(dt.datetime.now(dt.timezone.utc).timestamp())


def to_iso(ts: int | float | None) -> str | None:
    if ts is None:
        return None
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str | None) -> int | None:
    """Parse an ISO-8601 string (as returned by Blockscout) to a UTC unix timestamp."""
    if not s:
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return int(d.timestamp())


def window_seconds(window: str) -> int:
    try:
        return WINDOWS_SECONDS[window]
    except KeyError as exc:
        raise ValueError(f"unknown window '{window}'") from exc


def age_seconds(created_ts: int | None, as_of: int | None = None) -> int | None:
    if created_ts is None:
        return None
    return max(0, (as_of if as_of is not None else now_ts()) - int(created_ts))


def humanize_seconds(seconds: int | float | None) -> str:
    if seconds is None:
        return "?"
    seconds = int(seconds)
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"
