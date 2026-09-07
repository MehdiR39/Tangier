"""Cleaning rules for price series, explicit and counted. Nothing is silently dropped.

Why this exists: a handful of corrupted prints in token_snapshots (a price of 1e-20 followed by a
normal one) produced a "mean return" of +6e17 %, and any statistic built on a mean was garbage.
Medians survive that; means, expectancies and book simulations do not.

Every rule below is written so that its effect can be printed. A cleaning step that cannot say
how many rows it removed is a bias waiting to be discovered later.

Rules, in order:
  1. NON-POSITIVE and NON-FINITE prices are removed.
  2. ISOLATED SPIKES: an observation whose price differs from BOTH neighbours by more than
     SPIKE_FACTOR, in the same direction, is a bad print, not a move -- a real move persists
     for at least one more observation. Removed.
  3. RESIDUAL JUMPS: after spike removal, a series still showing a single-step move beyond
     JUMP_FACTOR is flagged. Such tokens are EXCLUDED and counted; capping would hide real
     moonshots and keeping them would let one print dominate every average.
  4. STALE runs: identical price repeated more than MAX_FLAT observations in a row means the
     feed stopped, not the market. The flat tail is cut.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

SPIKE_FACTOR = 5.0      # x5 up or down against both neighbours, reverting: a bad print
JUMP_FACTOR = 100.0     # a genuine x100 between two 12-minute prints does not happen in a
                        # book you can trade; it is a print from another pool or a decimals slip
MAX_FLAT = 12           # ~2.4 h of an unchanged price at 12-minute cadence


def clean_series(points: Sequence[tuple[int, float, Any]]) -> tuple[list[tuple], dict[str, int]]:
    """``points`` are (ts, price, payload...) sorted by ts. Returns (kept, counts)."""
    stats = {"in": len(points), "nonpos": 0, "spike": 0, "flat_cut": 0, "excluded": 0}
    pts = [p for p in points if p[1] is not None and p[1] > 0 and math.isfinite(p[1])]
    stats["nonpos"] = len(points) - len(pts)
    if len(pts) < 3:
        return list(pts), stats

    keep = []
    for i, p in enumerate(pts):
        if 0 < i < len(pts) - 1:
            prev, nxt = pts[i - 1][1], pts[i + 1][1]
            up = p[1] > prev * SPIKE_FACTOR and p[1] > nxt * SPIKE_FACTOR
            down = p[1] * SPIKE_FACTOR < prev and p[1] * SPIKE_FACTOR < nxt
            if up or down:
                stats["spike"] += 1
                continue
        keep.append(p)

    for a, b in zip(keep, keep[1:]):
        r = b[1] / a[1]
        if r > JUMP_FACTOR or r < 1.0 / JUMP_FACTOR:
            stats["excluded"] = 1
            return [], stats

    # cut a flat tail: the feed froze
    n = len(keep)
    j = n - 1
    while j > 0 and keep[j][1] == keep[j - 1][1]:
        j -= 1
    if n - 1 - j > MAX_FLAT:
        stats["flat_cut"] = n - 1 - (j + 1)
        keep = keep[: j + 2]
    return keep, stats


def summarize(all_stats: list[dict[str, int]]) -> dict[str, int]:
    out = {"series": len(all_stats)}
    for k in ("in", "nonpos", "spike", "flat_cut", "excluded"):
        out[k] = sum(s.get(k, 0) for s in all_stats)
    return out
