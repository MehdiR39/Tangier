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


MIN_ACCEPTABLE_RR = 1.5
DEFAULT_ATR_STOP_MULT = 2.0
DEFAULT_SWING_LOOKBACK = 30
DEFAULT_ENTRY_ZONE_LOWER_ATR = 0.5
DEFAULT_ENTRY_ZONE_UPPER_ATR = 0.2


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
    atr = float(last_bar.get("ATR", close * 0.02))   # 2% fallback if ATR missing
    sma_20 = float(last_bar.get("SMA_20", close))
    if not np.isfinite(atr) or atr <= 0:
        atr = close * 0.02

    swings = find_swing_levels(ohlcv, lookback=swing_lookback)
    swing_high = swings["swing_high"]
    swing_low = swings["swing_low"]

    if direction == "LONG":
        entry_low = close - DEFAULT_ENTRY_ZONE_LOWER_ATR * atr
        entry_high = close + DEFAULT_ENTRY_ZONE_UPPER_ATR * atr
        entry_mid = (entry_low + entry_high) / 2

        # Stop = max(ATR-based, slightly below swing_low)
        atr_stop = close - atr_stop_mult * atr
        swing_stop = (swing_low * 0.99) if swing_low else atr_stop
        stop = min(atr_stop, swing_stop)   # the lower of the two = safer stop

        # Targets
        target_1 = swing_high if (swing_high and swing_high > entry_mid) else None
        if target_1:
            reward = target_1 - entry_mid
            target_2 = entry_mid + 1.618 * reward
        else:
            target_2 = None

        risk = entry_mid - stop
        trigger = f"close > SMA_20 (${sma_20:.2f}) in next 2 bars"

    else:  # SHORT
        entry_high = close + DEFAULT_ENTRY_ZONE_LOWER_ATR * atr
        entry_low = close - DEFAULT_ENTRY_ZONE_UPPER_ATR * atr
        entry_mid = (entry_low + entry_high) / 2

        atr_stop = close + atr_stop_mult * atr
        swing_stop = (swing_high * 1.01) if swing_high else atr_stop
        stop = max(atr_stop, swing_stop)

        target_1 = swing_low if (swing_low and swing_low < entry_mid) else None
        if target_1:
            reward = entry_mid - target_1
            target_2 = entry_mid - 1.618 * reward
        else:
            target_2 = None

        risk = stop - entry_mid
        trigger = f"close < SMA_20 (${sma_20:.2f}) in next 2 bars"

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
