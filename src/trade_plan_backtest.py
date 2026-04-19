"""
Trade plan backtester — simulates entry / stop / target / max-hold on
every historical signal, then aggregates P&L.

The point is to answer EMPIRICALLY, not by intuition:
  - Which TRIGGER works best?  (immediate / SMA_20 / breakout-N)
  - Which STOP works best?     (1.5 / 2 / 3 ATR, or swing-low)
  - Which TARGET works best?   (swing-high, 2×ATR, 3×ATR, none)

Each simulate_trade() run walks bar-by-bar forward from the signal, honoring
the trigger (entry not taken if never confirmed) and stop/target (whichever
hits first). Exit at max_hold_bars if neither.

Output: pandas DataFrame of per-trade rows and a summary table.
"""

import logging
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ============================================================
# Trigger functions — return a boolean mask on the bar window
# ============================================================
def trigger_immediate(ohlcv_forward: pd.DataFrame, signal_close: float, direction: str) -> Optional[int]:
    """Entry immediately at next bar's open."""
    if len(ohlcv_forward) == 0:
        return None
    return 0


def trigger_sma20_cross(ohlcv_forward: pd.DataFrame, signal_close: float, direction: str,
                        sma_20: float) -> Optional[int]:
    """Entry when close crosses above (LONG) / below (SHORT) SMA_20."""
    for i in range(len(ohlcv_forward)):
        close = float(ohlcv_forward["Close"].iloc[i])
        if direction == "LONG" and close > sma_20:
            return i
        if direction == "SHORT" and close < sma_20:
            return i
    return None


def trigger_breakout_n(ohlcv_forward: pd.DataFrame, signal_close: float, direction: str,
                       n: int, history: pd.DataFrame) -> Optional[int]:
    """Entry when close breaks above (LONG) the high of last n bars (from signal date)."""
    if len(history) < n:
        return None
    if direction == "LONG":
        breakout_level = float(history["High"].tail(n).max())
        for i in range(len(ohlcv_forward)):
            if float(ohlcv_forward["Close"].iloc[i]) > breakout_level:
                return i
    else:
        breakout_level = float(history["Low"].tail(n).min())
        for i in range(len(ohlcv_forward)):
            if float(ohlcv_forward["Close"].iloc[i]) < breakout_level:
                return i
    return None


# ============================================================
# Stop & target level calculators
# ============================================================
def stop_atr(entry: float, atr: float, direction: str, mult: float) -> float:
    return entry - mult * atr if direction == "LONG" else entry + mult * atr


def stop_swing(entry: float, swing_low: float, swing_high: float, direction: str,
               fallback_atr: float) -> float:
    if direction == "LONG":
        return swing_low * 0.99 if swing_low > 0 else entry - 2 * fallback_atr
    return swing_high * 1.01 if swing_high > 0 else entry + 2 * fallback_atr


def target_swing(entry: float, swing_low: float, swing_high: float, direction: str) -> Optional[float]:
    if direction == "LONG":
        return swing_high if swing_high > entry else None
    return swing_low if swing_low < entry else None


def target_atr(entry: float, atr: float, direction: str, mult: float) -> float:
    return entry + mult * atr if direction == "LONG" else entry - mult * atr


# ============================================================
# Core simulator
# ============================================================
def simulate_trade(
    ohlcv: pd.DataFrame,
    signal_idx: int,
    direction: str,
    trigger_fn: Callable,
    stop_fn: Callable,
    target_fn: Optional[Callable],
    max_hold_bars: int = 10,
    trigger_window: int = 3,
    fee_bps: float = 5.0,
) -> Optional[dict]:
    """
    Simulate one trade on historical data.

    Args:
        ohlcv: full OHLCV DataFrame with ATR column
        signal_idx: index position of the signal bar
        direction: "LONG" or "SHORT"
        trigger_fn: callable (ohlcv_forward, signal_close, direction, ctx) -> entry_bar_offset or None
        stop_fn: callable (entry, atr, direction, ctx) -> stop_price
        target_fn: callable (entry, atr, direction, ctx) -> target_price or None
        max_hold_bars: max bars held after entry
        trigger_window: # bars to wait for trigger confirmation
        fee_bps: one-way fee in bps

    Returns:
        dict with fields or None if trade never entered
    """
    if signal_idx >= len(ohlcv) - 2:
        return None

    signal_close = float(ohlcv["Close"].iloc[signal_idx])

    # History for context (up to signal_idx inclusive)
    history = ohlcv.iloc[: signal_idx + 1]
    atr = float(history["ATR"].iloc[-1]) if "ATR" in history.columns else signal_close * 0.02
    if not np.isfinite(atr) or atr <= 0:
        atr = signal_close * 0.02
    sma_20 = float(history["Close"].tail(20).mean()) if len(history) >= 20 else signal_close

    # Swing levels from last 30 bars before signal
    lookback = history.tail(30)
    swing_low = float(lookback["Low"].min())
    swing_high = float(lookback["High"].max())

    # ---- Find trigger
    window_end = min(signal_idx + 1 + trigger_window, len(ohlcv))
    forward = ohlcv.iloc[signal_idx + 1 : window_end]

    entry_offset = trigger_fn(forward, signal_close, direction,
                              sma_20=sma_20, history=history)
    if entry_offset is None:
        return {"entered": False, "exit_reason": "no_trigger"}

    entry_bar = signal_idx + 1 + entry_offset
    entry_price = float(ohlcv["Close"].iloc[entry_bar])

    # ---- Compute stop + target
    stop_price = stop_fn(entry_price, atr, direction,
                         swing_low=swing_low, swing_high=swing_high)
    target_price = target_fn(entry_price, atr, direction,
                              swing_low=swing_low, swing_high=swing_high) \
                    if target_fn else None

    # ---- Walk forward until stop / target / max_hold
    exit_price = None
    exit_reason = "time"
    exit_bar = entry_bar
    for k in range(1, max_hold_bars + 1):
        bar_idx = entry_bar + k
        if bar_idx >= len(ohlcv):
            break
        bar = ohlcv.iloc[bar_idx]
        high, low = float(bar["High"]), float(bar["Low"])

        if direction == "LONG":
            if low <= stop_price:
                exit_price = stop_price
                exit_reason = "stop"
                exit_bar = bar_idx
                break
            if target_price is not None and high >= target_price:
                exit_price = target_price
                exit_reason = "target"
                exit_bar = bar_idx
                break
        else:
            if high >= stop_price:
                exit_price = stop_price
                exit_reason = "stop"
                exit_bar = bar_idx
                break
            if target_price is not None and low <= target_price:
                exit_price = target_price
                exit_reason = "target"
                exit_bar = bar_idx
                break

    if exit_price is None:
        exit_bar = min(entry_bar + max_hold_bars, len(ohlcv) - 1)
        exit_price = float(ohlcv["Close"].iloc[exit_bar])
        exit_reason = "time"

    # ---- P&L with fees
    fee = fee_bps / 10_000.0
    if direction == "LONG":
        gross = exit_price / entry_price - 1
    else:
        gross = entry_price / exit_price - 1
    net = gross - 2 * fee

    return {
        "entered": True,
        "direction": direction,
        "entry_bar": entry_bar,
        "exit_bar": exit_bar,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "stop_price": stop_price,
        "target_price": target_price,
        "atr": atr,
        "gross_return": gross,
        "net_return": net,
        "exit_reason": exit_reason,
        "bars_held": exit_bar - entry_bar,
    }


# ============================================================
# Batch: run a full backtest across signals × variants
# ============================================================
def backtest_variant(
    signals: List[Tuple[str, int, str]],  # (ticker, signal_idx, direction)
    data_dict: Dict[str, pd.DataFrame],
    trigger_fn: Callable,
    stop_fn: Callable,
    target_fn: Optional[Callable],
    max_hold_bars: int = 10,
    trigger_window: int = 3,
    fee_bps: float = 5.0,
) -> pd.DataFrame:
    """Run simulate_trade for every signal, return per-trade results."""
    rows = []
    for ticker, idx, direction in signals:
        ohlcv = data_dict.get(ticker)
        if ohlcv is None:
            continue
        r = simulate_trade(
            ohlcv, idx, direction,
            trigger_fn, stop_fn, target_fn,
            max_hold_bars=max_hold_bars,
            trigger_window=trigger_window,
            fee_bps=fee_bps,
        )
        if r is not None:
            r["ticker"] = ticker
            r["signal_idx"] = idx
            rows.append(r)
    return pd.DataFrame(rows)


def summarize(results: pd.DataFrame, variant_name: str) -> dict:
    """
    Aggregate summary metrics for one variant.

    NOTE on totals: we do NOT compound sequentially (that would assume infinite
    capital reinvested in every trade). Instead we report the **sum** of
    net returns, which is meaningful if you risk a FIXED fraction of capital
    per trade (e.g. 1% per trade -> total P&L = fixed_frac × sum).
    """
    entered = results[results["entered"]]
    if entered.empty:
        return {
            "variant": variant_name,
            "n_signals": len(results),
            "n_entered": 0,
            "fill_rate": 0.0,
            "hit_rate": np.nan,
            "avg_win": np.nan,
            "avg_loss": np.nan,
            "expectancy": np.nan,
            "sum_returns": 0.0,
            "median_return": np.nan,
            "profit_factor": np.nan,
            "avg_bars_held": np.nan,
        }
    wins = entered[entered["net_return"] > 0]
    losses = entered[entered["net_return"] <= 0]
    expectancy = float(entered["net_return"].mean())
    sum_returns = float(entered["net_return"].sum())
    median_return = float(entered["net_return"].median())
    profit_factor = (
        float(wins["net_return"].sum() / abs(losses["net_return"].sum()))
        if len(losses) and losses["net_return"].sum() != 0 else np.nan
    )
    return {
        "variant": variant_name,
        "n_signals": len(results),
        "n_entered": len(entered),
        "fill_rate": round(len(entered) / len(results), 3),
        "hit_rate": round((entered["net_return"] > 0).mean(), 3),
        "avg_win": round(wins["net_return"].mean(), 4) if len(wins) else np.nan,
        "avg_loss": round(losses["net_return"].mean(), 4) if len(losses) else np.nan,
        "expectancy": round(expectancy, 5),
        "sum_returns": round(sum_returns, 3),
        "median_return": round(median_return, 5),
        "profit_factor": round(profit_factor, 2) if profit_factor == profit_factor else np.nan,
        "avg_bars_held": round(entered["bars_held"].mean(), 1),
    }
