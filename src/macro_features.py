"""
Macro regime features — merged into every ticker's feature frame.

Adds:
  - VIX level & pct-change                 (volatility regime)
  - US 10y (^TNX) level, yield curve slope (^TNX - ^IRX)
  - Market breadth = % of universe above its SMA_50 (cross-sectional)
  - SPY momentum (1m, 3m)                  (market beta proxy)

These are the same for every ticker at date t → they act as a shared
'context' that the ML model can use to condition its predictions.
"""

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


MACRO_TICKERS = {
    "vix": "^VIX",
    "tnx": "^TNX",   # 10-year Treasury yield
    "irx": "^IRX",   # 3-month T-bill yield
    "spy": "SPY",
}


def fetch_macro_series(start: Optional[str] = None,
                       end: Optional[str] = None) -> pd.DataFrame:
    """
    Download daily series for VIX, TNX, IRX, SPY. Returns a DataFrame
    indexed by date with one column per metric.
    """
    import yfinance as yf

    frames = {}
    for key, sym in MACRO_TICKERS.items():
        df = yf.download(sym, start=start, end=end, interval="1d",
                         auto_adjust=True, progress=False, threads=False)
        if df is None or df.empty:
            logger.warning(f"macro: {sym} empty response")
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        frames[key] = df["Close"].rename(key)

    if not frames:
        raise RuntimeError("macro: no series downloaded")

    out = pd.concat(frames.values(), axis=1).sort_index()
    out.index.name = "Date"
    return out


def build_macro_features(macro: pd.DataFrame) -> pd.DataFrame:
    """Derive regime features from the raw macro series."""
    feat = pd.DataFrame(index=macro.index)

    if "vix" in macro:
        feat["VIX_Level"] = macro["vix"]
        feat["VIX_Pct_5d"] = macro["vix"].pct_change(5)
        feat["VIX_Regime_High"] = (macro["vix"] > macro["vix"].rolling(60).mean()).astype(int)

    if "tnx" in macro:
        feat["TNX_Level"] = macro["tnx"]
        feat["TNX_Chg_5d"] = macro["tnx"].diff(5)

    if "tnx" in macro and "irx" in macro:
        feat["YieldCurve_Slope"] = macro["tnx"] - macro["irx"]
        feat["YieldCurve_Inverted"] = (feat["YieldCurve_Slope"] < 0).astype(int)

    if "spy" in macro:
        feat["SPY_Ret_20d"] = macro["spy"].pct_change(20)
        feat["SPY_Ret_60d"] = macro["spy"].pct_change(60)
        feat["SPY_Above_SMA200"] = (macro["spy"] > macro["spy"].rolling(200).mean()).astype(int)

    return feat


def compute_breadth(data_dict: Dict[str, pd.DataFrame],
                    sma_period: int = 50) -> pd.Series:
    """
    Market breadth = fraction of tickers trading above their SMA_{sma_period}
    at each date. One scalar per date, across the universe.
    """
    above_flags = []
    for sym, df in data_dict.items():
        if len(df) < sma_period + 1:
            continue
        sma = df["Close"].rolling(sma_period).mean()
        above = (df["Close"] > sma).astype(float)
        above.name = sym
        above_flags.append(above)

    if not above_flags:
        return pd.Series(dtype=float, name="Breadth")

    wide = pd.concat(above_flags, axis=1)
    breadth = wide.mean(axis=1).rename("Breadth_Pct_Above_SMA50")
    return breadth


def attach_macro_to_tickers(
    data_dict: Dict[str, pd.DataFrame],
    macro_feats: pd.DataFrame,
    breadth: Optional[pd.Series] = None,
) -> Dict[str, pd.DataFrame]:
    """
    Left-join macro features (+ breadth) into each ticker's OHLCV frame.
    Macro columns are forward-filled to tolerate date misalignment
    (e.g. VIX vs stock calendars are close but not identical).
    """
    to_merge = macro_feats.copy()
    if breadth is not None:
        to_merge = to_merge.join(breadth, how="outer")
    to_merge = to_merge.sort_index().ffill()

    out = {}
    for sym, df in data_dict.items():
        merged = df.join(to_merge, how="left").ffill()
        # Fill any leading NaN (before macro starts) with 0-ish — the training
        # step will drop rows with NaN features anyway.
        out[sym] = merged
    logger.info(
        f"macro: attached {len(to_merge.columns)} macro features to "
        f"{len(out)} tickers"
    )
    return out
