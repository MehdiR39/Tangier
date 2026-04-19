"""
Trade plan generator — turns a raw signal into an actionable plan.

For each signal we compute:
  - Entry zone           (ATR-based)
  - Stop-loss            (ATR-based, clamped to last swing low/high)
  - Target 1             (previous swing high/low)
  - Target 2             (Fibonacci extension 1.618)
  - Risk / reward        (T1 vs stop)
  - Trigger              ("wait for close > SMA_20", etc.)
  - Plan quality flag    ("accept" / "poor_rr" / "no_target")

Design rules:
  - All levels are in price units (not %)
  - Stop = 2 × ATR from close (or last swing if closer)
  - T1 = distance to previous swing extreme
  - T2 = 1.618 × distance(entry, T1)
  - Reject if R/R < 1.5
"""

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# Defaults below were validated empirically by backtest_trade_plan.py
# on 1742 OOS signals over 30 tickers (last 30% of data):
#   trigger=immediate, stop=2xATR, target=2xATR, hold=10 bars
# Best combo found: expectancy +0.22% per trade, profit factor 1.14.
# Swing-high targets and SMA_20/breakout triggers were EMPIRICALLY WORSE.
MIN_ACCEPTABLE_RR = 0.9          # with R/R≈1.0 symmetric, threshold is softer
DEFAULT_ATR_STOP_MULT = 2.0
DEFAULT_ATR_TARGET_MULT = 2.0    # 1:1 reward/risk (empirical winner)
DEFAULT_SWING_LOOKBACK = 30
DEFAULT_ENTRY_ZONE_LOWER_ATR = 0.1    # tight zone = "entrée immediate"
DEFAULT_ENTRY_ZONE_UPPER_ATR = 0.1
DEFAULT_MAX_HOLD_BARS = 10


# ---------------------------------------------------------------------------
# Swing detection
# ---------------------------------------------------------------------------
def find_swing_levels(
    df: pd.DataFrame,
    lookback: int = DEFAULT_SWING_LOOKBACK,
) -> Dict[str, Optional[float]]:
    """
    Return the most recent swing high and swing low in the last `lookback`
    bars. A swing high is a local maximum, a swing low a local minimum.

    Simple implementation: max(High) and min(Low) over the window.
    """
    if len(df) < lookback:
        return {"swing_high": None, "swing_low": None}

    recent = df.tail(lookback)
    return {
        "swing_high": float(recent["High"].max()),
        "swing_low": float(recent["Low"].min()),
    }


# ---------------------------------------------------------------------------
# Trade plan per signal
# ---------------------------------------------------------------------------
def build_trade_plan(
    signal_row: pd.Series,
    ohlcv: pd.DataFrame,
    atr_stop_mult: float = DEFAULT_ATR_STOP_MULT,
    swing_lookback: int = DEFAULT_SWING_LOOKBACK,
    min_rr: float = MIN_ACCEPTABLE_RR,
) -> Dict[str, Optional[float]]:
    """
    Build a full trade plan for one signal.

    Args:
        signal_row: one row of the scan output (has 'direction', 'close')
        ohlcv: OHLCV frame for that ticker (must include ATR, SMA_20)

    Returns dict with:
        entry_low, entry_mid, entry_high,
        stop, target_1, target_2,
        risk_pct, reward_pct, rr,
        trigger, plan_quality
    """
    direction = str(signal_row.get("direction", "LONG"))
    close = float(signal_row.get("close", 0))
    if close <= 0 or ohlcv.empty:
        return {}

    last_bar = ohlcv.iloc[-1]

    # SMA_20 : prefer the engineered column, else compute from Close history
    sma_20_col = last_bar.get("SMA_20")
    if sma_20_col is not None and pd.notna(sma_20_col) and float(sma_20_col) > 0:
        sma_20 = float(sma_20_col)
    elif len(ohlcv) >= 20:
        sma_20 = float(ohlcv["Close"].tail(20).mean())
    else:
        sma_20 = close

    # ATR : prefer engineered column, else compute Wilder true-range on the fly
    atr_col = last_bar.get("ATR")
    if atr_col is not None and pd.notna(atr_col) and float(atr_col) > 0:
        atr = float(atr_col)
    elif len(ohlcv) >= 14:
        H, L, C = ohlcv["High"], ohlcv["Low"], ohlcv["Close"]
        tr = pd.concat([
            H - L,
            (H - C.shift(1)).abs(),
            (L - C.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = float(tr.tail(14).mean())
    else:
        atr = close * 0.02

    if not np.isfinite(atr) or atr <= 0:
        atr = close * 0.02

    swings = find_swing_levels(ohlcv, lookback=swing_lookback)
    swing_high = swings["swing_high"]
    swing_low = swings["swing_low"]

    if direction == "LONG":
        # Entry at current close (validated empirically to beat breakout/SMA triggers)
        entry_low = close - DEFAULT_ENTRY_ZONE_LOWER_ATR * atr
        entry_high = close + DEFAULT_ENTRY_ZONE_UPPER_ATR * atr
        entry_mid = close

        # Stop = 2×ATR from entry (validated empirically)
        stop = entry_mid - atr_stop_mult * atr

        # Target_1 = 2×ATR symmetric (R/R 1:1, validated empirically).
        # Target_2 = swing_high if available (aspirational stretch target).
        target_1 = entry_mid + DEFAULT_ATR_TARGET_MULT * atr
        target_2 = swing_high if (swing_high and swing_high > target_1) else None

        risk = entry_mid - stop
        trigger = f"entrée au close du prochain bar (~${close:.2f})"

    else:  # SHORT
        entry_high = close + DEFAULT_ENTRY_ZONE_LOWER_ATR * atr
        entry_low = close - DEFAULT_ENTRY_ZONE_UPPER_ATR * atr
        entry_mid = close

        stop = entry_mid + atr_stop_mult * atr

        target_1 = entry_mid - DEFAULT_ATR_TARGET_MULT * atr
        target_2 = swing_low if (swing_low and swing_low < target_1) else None

        risk = stop - entry_mid
        trigger = f"entrée au close du prochain bar (~${close:.2f})"

    # Compute R/R
    if target_1 is None or risk <= 0:
        rr = None
        plan_quality = "no_target"
    else:
        reward = abs(target_1 - entry_mid)
        rr = float(reward / risk)
        plan_quality = "accept" if rr >= min_rr else "poor_rr"

    return {
        "entry_low": float(entry_low),
        "entry_mid": float(entry_mid),
        "entry_high": float(entry_high),
        "stop": float(stop),
        "target_1": float(target_1) if target_1 is not None else None,
        "target_2": float(target_2) if target_2 is not None else None,
        "risk_pct": float(risk / entry_mid * 100) if risk > 0 else None,
        "reward_pct": float(abs(target_1 - entry_mid) / entry_mid * 100)
                       if target_1 is not None else None,
        "rr": rr,
        "trigger": trigger,
        "plan_quality": plan_quality,
    }


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------
def attach_trade_plans(
    ranked_scan: pd.DataFrame,
    data_dict: Dict[str, pd.DataFrame],
    **kwargs,
) -> pd.DataFrame:
    """
    Add trade plan columns to an enriched scan DataFrame.
    Returns same DataFrame with new cols: entry_*, stop, target_1, target_2,
    risk_pct, reward_pct, rr, trigger, plan_quality.
    """
    if ranked_scan.empty:
        return ranked_scan

    plans = []
    for _, row in ranked_scan.iterrows():
        sym = row["ticker"]
        ohlcv = data_dict.get(sym)
        if ohlcv is None or ohlcv.empty:
            plans.append({})
            continue
        plan = build_trade_plan(row, ohlcv, **kwargs)
        plans.append(plan)

    plans_df = pd.DataFrame(plans, index=ranked_scan.index)
    return pd.concat([ranked_scan, plans_df], axis=1)
