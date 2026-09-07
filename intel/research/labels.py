"""Forward outcomes for each observation. Nothing here may read a price at or before the entry.

Entry is the price of the FIRST TRADE STRICTLY AFTER the observation block, never the price
observed at the decision instant: a printed price is somebody else's fill, and a strategy that
buys at it is buying in the past. Every multiple below is measured against that fill.

A multiple that cannot be sold is not a multiple. So each xN records the quote volume actually
traded in the 30 minutes after the level is first touched; the backtest converts that to euros
where the quote asset's decimals are known and refuses the exit when the ticket is too large a
share of it. Raw quote units are stored rather than dollars because token decimals are unreadable
for many pools, and dropping those pools is precisely the bias this dataset exists to remove.
"""
from __future__ import annotations

from typing import Any

from intel.research.features import BLOCKS_PER_MIN, price_from_sqrt, virtual_quote

LEVELS = [2.0, 3.0, 5.0, 10.0, 20.0, 50.0]
HORIZONS_MIN = {"1h": 60, "3h": 180, "6h": 360, "24h": 1440}
SELL_WINDOW_MIN = 30


def label(tape, t_min: float) -> dict[str, Any] | None:
    """outcomes after ``t_min``; returns None when there was no fill available at all"""
    if tape.t0 is None:
        return None
    b = tape.t0 + int(t_min * BLOCKS_PER_MIN)
    after = [s for s in tape.swaps if s[0] > b]
    if not after:
        return None                       # bought and nobody ever traded again -> handled by caller
    entry_block = after[0][0]
    entry = price_from_sqrt(after[0][1], tape.is_c0)
    if entry <= 0:
        return None

    path = [(s[0], price_from_sqrt(s[1], tape.is_c0), s) for s in after]
    path = [(blk, p, s) for blk, p, s in path if p > 0]
    if not path:
        return None

    out: dict[str, Any] = {"pair_id": tape.pool["pair_id"], "t_min": t_min}

    for name, mins in HORIZONS_MIN.items():
        stop = entry_block + mins * BLOCKS_PER_MIN
        seg = [p for blk, p, _ in path if blk <= stop]
        out["max_ret_" + name] = (max(seg) / entry) if seg else 0.0

    # first touch of each level inside 6 h, with the drawdown suffered on the way
    stop6 = entry_block + HORIZONS_MIN["6h"] * BLOCKS_PER_MIN
    seg6 = [(blk, p) for blk, p, _ in path if blk <= stop6]
    low = entry
    touched: dict[float, tuple[int, float]] = {}
    for blk, p in seg6:
        low = min(low, p)
        for lv in LEVELS:
            if lv not in touched and p / entry >= lv:
                touched[lv] = (blk, low / entry - 1.0)
    for lv in LEVELS:
        key = f"x{lv:g}"
        hit = lv in touched
        out["hit_" + key] = 1 if hit else 0
        if lv in (2.0, 5.0, 10.0, 20.0, 50.0):
            out["t_to_" + key] = ((touched[lv][0] - entry_block) / BLOCKS_PER_MIN) if hit else None
        out["dd_before_" + key] = touched[lv][1] if hit else None
        # Can it be sold there? Quote volume traded in the half hour after the level is touched.
        # Recorded for EVERY level, including x2: when it was missing for a level, the backtest
        # read the absent column as a volume of zero, refused the exit on participation grounds and
        # silently fell through to the horizon -- which is why "sell all at x2" returned exactly
        # the same figure as "hold 6 h" and was never actually tested.
        if hit:
            blk = touched[lv][0]
            vol = sum(abs(s[4] if tape.is_c0 else s[3])
                      for bb, _p, s in path
                      if blk < bb <= blk + SELL_WINDOW_MIN * BLOCKS_PER_MIN)
            out["sellvol_" + key] = float(vol)
        else:
            out["sellvol_" + key] = None

    stop6_price = [(blk, p) for blk, p, _ in path if blk <= stop6]
    out["ret_6h"] = (stop6_price[-1][1] / entry) if stop6_price else 0.0
    # Selling at the horizon is a trade like any other and needs somebody on the other side. This
    # is the quote volume traded in the half hour BEFORE the exit; without it the book was closing
    # every held position at the last printed price, which is the mistake that made an earlier
    # backtest look profitable.
    if stop6_price:
        end_blk = stop6_price[-1][0]
        out["exit_vol_6h"] = float(sum(
            abs(s[4] if tape.is_c0 else s[3]) for bb, _p, s in path
            if end_blk - SELL_WINDOW_MIN * BLOCKS_PER_MIN <= bb <= end_blk))
    else:
        out["exit_vol_6h"] = 0.0

    last_block = path[-1][0]
    horizon_end = tape.t0 + 1440 * BLOCKS_PER_MIN
    out["dead"] = 1 if last_block < horizon_end - 60 * BLOCKS_PER_MIN else 0

    # rug: the pool's quote-side depth collapses to a tenth of its own peak and stays there
    depths = [virtual_quote(s[2], s[1], tape.is_c0) for _blk, _p, s in path]
    peak = max(depths) if depths else 0.0
    out["rug"] = 1 if (peak > 0 and depths[-1] < 0.10 * peak) else 0
    out["entry_price"] = entry
    out["entry_block"] = entry_block
    return out


def zero_label(tape, t_min: float) -> dict[str, Any]:
    """the position could never be sold: every outcome is zero, and it must still be counted"""
    d: dict[str, Any] = {"pair_id": tape.pool["pair_id"], "t_min": t_min}
    for name in HORIZONS_MIN:
        d["max_ret_" + name] = 0.0
    for lv in LEVELS:
        key = f"x{lv:g}"
        d["hit_" + key] = 0
        if lv in (2.0, 5.0, 10.0, 20.0, 50.0):
            d["t_to_" + key] = None
        d["dd_before_" + key] = None
        d["sellvol_" + key] = None
    d["ret_6h"] = 0.0
    d["exit_vol_6h"] = 0.0
    d["dead"] = 1
    d["rug"] = 0
    d["entry_price"] = None
    d["entry_block"] = None
    return d
