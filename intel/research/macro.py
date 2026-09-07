"""Does the wider market's mood predict how generous launches are? ETH and BTC as the regime gauge.

Every internal regime candidate failed out of sample, and they all shared two weaknesses: they
were built from our own sparse cohorts, and they drifted with the chain's growth. The price of
ETH has neither problem -- it is continuous, external, known to the second, and the link between
majors' momentum and memecoin appetite is a standing observation, not a guess.

Hourly klines come from Binance's public endpoint (no key). For each launch, only candles that
CLOSED before the launch time are used: momentum over the previous 24 h and 7 d, and the price
against its own 30-day average. Nothing after the launch touches the feature.
"""
from __future__ import annotations

import bisect
import json
import statistics
import time
import urllib.request
from typing import Any

BINANCE = "https://api.binance.com/api/v3/klines"


def klines(symbol: str, start_ms: int, end_ms: int, interval: str = "1h") -> list[tuple[int, float]]:
    """(close_time_ms, close) for every candle in the range, paged 1000 at a time"""
    out: list[tuple[int, float]] = []
    cur = start_ms
    while cur < end_ms:
        url = (f"{BINANCE}?symbol={symbol}&interval={interval}&startTime={cur}"
               f"&endTime={end_ms}&limit=1000")
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        if not data:
            break
        for k in data:
            out.append((int(k[6]), float(k[4])))     # close time, close price
        cur = int(data[-1][6]) + 1
        time.sleep(0.2)
    return out


class Tape:
    def __init__(self, candles: list[tuple[int, float]]) -> None:
        self.t = [c[0] for c in candles]
        self.p = [c[1] for c in candles]

    def close_before(self, ts_ms: int) -> tuple[int, float] | None:
        i = bisect.bisect_left(self.t, ts_ms) - 1        # last candle that CLOSED before ts
        return (self.t[i], self.p[i]) if i >= 0 else None

    def features(self, ts_ms: int) -> dict[str, float | None]:
        now = self.close_before(ts_ms)
        if not now:
            return {}
        i = bisect.bisect_left(self.t, ts_ms) - 1

        def back(hours: int) -> float | None:
            j = i - hours
            return self.p[j] if j >= 0 else None

        p24, p168, = back(24), back(168)
        win30 = self.p[max(0, i - 720): i + 1]
        ma30 = statistics.mean(win30) if len(win30) >= 240 else None
        return {
            "ret_24h": (now[1] / p24 - 1) if p24 else None,
            "ret_7d": (now[1] / p168 - 1) if p168 else None,
            "vs_ma30": (now[1] / ma30 - 1) if ma30 else None,
        }


def attach(rows: list[dict[str, Any]], eth: Tape, btc: Tape, ts_of) -> int:
    """add eth_* / btc_* features to each row; returns how many rows had no timestamp"""
    missing = 0
    for r in rows:
        ts = ts_of(r)
        if not ts:
            missing += 1
            continue
        for name, tape in (("eth", eth), ("btc", btc)):
            for k, v in tape.features(int(ts) * 1000).items():
                r[f"{name}_{k}"] = v
    return missing
