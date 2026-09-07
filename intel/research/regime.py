"""Is the market's temperature observable BEFORE we bet, and does gating on it help?

The measurement that motivated this: the rule's lift is stable (2.0x - 2.6x) across the whole
history, but the base rate of tokens doubling fell from 24% to 12.6%, and a 2x lift on a 12.6%
base no longer covers costs. So the strategy is conditional, and the condition is the market.

The obvious indicator -- "what fraction of recent launches doubled" -- cannot be used: a token's
6 h outcome is only known 6 h later, and our sample is 150 scattered one-hour cohorts, so a
trailing window over it is mostly empty. What IS continuous and known at decision time is the
LAUNCH DENSITY: `pairs` holds every pool creation on the chain, so the number of pools born in
the preceding 24 h is computable at any block, live, with nothing to wait for.

The threshold is read on the older half and applied to the newer one. Choosing it after seeing
which periods paid is exactly how a rule gets fitted to the past.
"""
from __future__ import annotations

import bisect
import statistics
from typing import Any

BLOCKS_PER_HOUR = 36_000
WINDOW_H = 24


def launch_density(created_blocks: list[int], block: int, window_h: int = WINDOW_H) -> int:
    """pools created on the whole chain in the ``window_h`` before ``block`` -- known at that time"""
    lo = block - window_h * BLOCKS_PER_HOUR
    return bisect.bisect_left(created_blocks, block) - bisect.bisect_left(created_blocks, lo)


def attach(rows: list[dict[str, Any]], created_blocks: list[int],
           window_h: int = WINDOW_H) -> list[dict[str, Any]]:
    for r in rows:
        b = r.get("block") or r.get("created_block") or 0
        r["launch_density"] = launch_density(created_blocks, int(b), window_h)
    return rows


def quantile_table(rows: list[dict[str, Any]], field: str = "launch_density",
                   bins: int = 4) -> list[dict[str, Any]]:
    # sort on the value only: ties would otherwise fall through to comparing the row dicts
    vals = sorted(((r[field], r) for r in rows if r.get(field) is not None), key=lambda x: x[0])
    per = len(vals) // bins
    out = []
    for i in range(bins):
        lo = i * per
        hi = len(vals) if i == bins - 1 else (i + 1) * per
        grp = [r for _v, r in vals[lo:hi]]
        if not grp:
            continue
        sel = [r for r in grp if (r.get("trades_5m") or 0) >= 27]
        out.append({
            "bin": i + 1, "n": len(grp),
            "from": vals[lo][0], "to": vals[hi - 1][0],
            "base_x2": sum(1 for r in grp if r.get("hit_x2")) / len(grp),
            "rule_x2": (sum(1 for r in sel if r.get("hit_x2")) / len(sel)) if sel else 0.0,
            "n_rule": len(sel),
            "med_max6h": statistics.median([r.get("max_ret_6h") or 0.0 for r in grp]),
        })
    return out
