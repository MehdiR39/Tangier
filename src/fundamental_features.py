"""
Fundamental features — earnings timing + analyst recommendations.

Only features that are **point-in-time safe** (no look-ahead bias) :
- Days_To_Next_Earnings   — announcements are known weeks in advance
- Days_Since_Last_Earnings — historical fact
- Analyst_Buy_Ratio       — historical analyst ratings snapshot at date t

PE-based features deliberately skipped : yfinance exposes only current PE,
reconstructing historical PE point-in-time requires paid fundamentals data.
"""

import os
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _fetch_earnings_history(symbol: str) -> Optional[pd.DataFrame]:
    """
    Returns DataFrame with columns ['earnings_date'] sorted chronologically.
    Combines future calendar entry + historical earnings_dates from yfinance.
    """
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)

        dates = set()

        # Historical + upcoming (earnings_dates covers both)
        try:
            ed = t.earnings_dates  # DataFrame indexed by earnings date
            if ed is not None and not ed.empty:
                for ts in ed.index:
                    if pd.notna(ts):
                        dates.add(pd.Timestamp(ts).normalize().tz_localize(None))
        except Exception:
            pass

        # Calendar — upcoming earnings (may not be in earnings_dates yet)
        try:
            cal = t.calendar
            if cal:
                ed = cal.get("Earnings Date")
                if isinstance(ed, list):
                    for d in ed:
                        dates.add(pd.Timestamp(d).normalize())
                elif ed is not None:
                    dates.add(pd.Timestamp(ed).normalize())
        except Exception:
            pass

        if not dates:
            return None
        return pd.DataFrame({"earnings_date": sorted(dates)})

    except Exception as e:
        logger.debug(f"{symbol}: earnings fetch failed — {e}")
        return None


def _fetch_recommendations(symbol: str) -> Optional[pd.DataFrame]:
    """
    Returns DataFrame indexed by date with columns for the counts of
    strong buy / buy / hold / sell / strong sell at that snapshot.
    """
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        rec = t.recommendations
        if rec is None or rec.empty:
            return None

        # Schema of recommendations DataFrame varies; newer yf returns columns
        # period, strongBuy, buy, hold, sell, strongSell
        needed = {"strongBuy", "buy", "hold", "sell", "strongSell"}
        if not needed.issubset(set(rec.columns)):
            return None

        # period is "0m" (current), "-1m" (1 month ago), etc.
        # Map to actual dates. 'period' with 0m = today's snapshot.
        today = pd.Timestamp.utcnow().normalize().tz_localize(None)
        rows = []
        for _, r in rec.iterrows():
            period = str(r.get("period", ""))
            months_ago = 0
            if period.startswith("-") and period.endswith("m"):
                try:
                    months_ago = int(period[1:-1])
                except ValueError:
                    continue
            date = today - pd.DateOffset(months=months_ago)
            rows.append({
                "date": date,
                "strongBuy": int(r.get("strongBuy", 0) or 0),
                "buy": int(r.get("buy", 0) or 0),
                "hold": int(r.get("hold", 0) or 0),
                "sell": int(r.get("sell", 0) or 0),
                "strongSell": int(r.get("strongSell", 0) or 0),
            })
        df = pd.DataFrame(rows).sort_values("date").set_index("date")
        return df

    except Exception as e:
        logger.debug(f"{symbol}: recommendations fetch failed — {e}")
        return None


# ---------------------------------------------------------------------------
# Batch fetching with cache
# ---------------------------------------------------------------------------
def fetch_fundamentals_batch(
    symbols,
    cache_path: Optional[str] = None,
    max_workers: int = 10,
    refresh: bool = False,
) -> Dict[str, Dict[str, pd.DataFrame]]:
    """
    Returns {symbol: {"earnings": df, "recommendations": df}}.
    Caches to parquet-per-type for fast reuse.
    """
    symbols = list(dict.fromkeys(symbols))

    # Load from cache if available
    cache = {}
    if cache_path and os.path.exists(cache_path) and not refresh:
        try:
            combined = pd.read_parquet(cache_path)
            for sym, grp in combined.groupby("symbol"):
                kind_dfs = {}
                for kind, sub in grp.groupby("kind"):
                    sub = sub.drop(columns=["symbol", "kind"])
                    if kind == "earnings":
                        kind_dfs["earnings"] = sub.rename(columns={"value_0": "earnings_date"})[["earnings_date"]]
                    else:
                        kind_dfs["recommendations"] = sub.set_index("date_idx").drop(columns=[c for c in sub.columns if c.startswith("_")], errors="ignore")
                cache[sym] = kind_dfs
            logger.info(f"fundamentals: cache hit ({len(cache)} tickers)")
            missing = [s for s in symbols if s not in cache]
            if not missing:
                return {s: cache[s] for s in symbols if s in cache}
            symbols_to_fetch = missing
        except Exception as e:
            logger.warning(f"fundamentals cache read failed ({e}), refetching")
            symbols_to_fetch = symbols
    else:
        symbols_to_fetch = symbols

    def worker(sym):
        return sym, {
            "earnings": _fetch_earnings_history(sym),
            "recommendations": _fetch_recommendations(sym),
        }

    out = dict(cache)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(worker, s): s for s in symbols_to_fetch}
        for i, fut in enumerate(as_completed(futures), 1):
            sym, data = fut.result()
            out[sym] = data
            if i % 25 == 0:
                logger.info(f"fundamentals: {i}/{len(symbols_to_fetch)} fetched")

    # Save cache
    if cache_path:
        rows = []
        for sym, d in out.items():
            if d.get("earnings") is not None and not d["earnings"].empty:
                for date in d["earnings"]["earnings_date"]:
                    rows.append({"symbol": sym, "kind": "earnings",
                                 "value_0": pd.Timestamp(date), "date_idx": pd.Timestamp(date)})
            if d.get("recommendations") is not None and not d["recommendations"].empty:
                for date, r in d["recommendations"].iterrows():
                    rec = {"symbol": sym, "kind": "recommendations", "date_idx": pd.Timestamp(date),
                           "value_0": pd.Timestamp(date)}
                    for c in ["strongBuy", "buy", "hold", "sell", "strongSell"]:
                        rec[c] = int(r.get(c, 0))
                    rows.append(rec)
        if rows:
            df = pd.DataFrame(rows)
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            df.to_parquet(cache_path)
            logger.info(f"fundamentals: cached {len(df)} rows -> {cache_path}")

    return {s: out[s] for s in symbols if s in out}


# ---------------------------------------------------------------------------
# Feature computation (point-in-time safe)
# ---------------------------------------------------------------------------
def compute_earnings_features(
    ohlcv: pd.DataFrame,
    earnings_df: Optional[pd.DataFrame],
) -> pd.DataFrame:
    """
    Adds Days_To_Next_Earnings and Days_Since_Last_Earnings to the frame.
    If no earnings info, fills with NaN (will be handled downstream).
    """
    out = ohlcv.copy()
    out["Days_To_Next_Earnings"] = np.nan
    out["Days_Since_Last_Earnings"] = np.nan

    if earnings_df is None or earnings_df.empty:
        return out

    earnings_dates = pd.to_datetime(earnings_df["earnings_date"].values)

    # For each row date, find the next earnings >= date, and last earnings < date
    idx = pd.DatetimeIndex(out.index)
    for i, d in enumerate(idx):
        next_mask = earnings_dates >= d
        last_mask = earnings_dates < d
        if next_mask.any():
            next_date = earnings_dates[next_mask].min()
            out.iloc[i, out.columns.get_loc("Days_To_Next_Earnings")] = (next_date - d).days
        if last_mask.any():
            last_date = earnings_dates[last_mask].max()
            out.iloc[i, out.columns.get_loc("Days_Since_Last_Earnings")] = (d - last_date).days

    return out


def compute_analyst_features(
    ohlcv: pd.DataFrame,
    recs_df: Optional[pd.DataFrame],
) -> pd.DataFrame:
    """
    Adds Analyst_Buy_Ratio = (strongBuy+buy) / total at date t.
    Forward-filled from last known snapshot.
    """
    out = ohlcv.copy()
    out["Analyst_Buy_Ratio"] = np.nan
    out["Analyst_Total_Count"] = np.nan

    if recs_df is None or recs_df.empty:
        return out

    total = recs_df[["strongBuy", "buy", "hold", "sell", "strongSell"]].sum(axis=1)
    buy_ratio = (recs_df["strongBuy"] + recs_df["buy"]) / total.replace(0, np.nan)
    snapshot = pd.DataFrame({"buy_ratio": buy_ratio, "total": total})
    snapshot = snapshot.sort_index()

    # Reindex snapshot onto ohlcv dates with ffill (latest known snapshot <= t)
    snapshot.index = pd.DatetimeIndex(snapshot.index)
    ohlcv_idx = pd.DatetimeIndex(out.index)
    # Union then ffill, then pick ohlcv dates
    combined_idx = snapshot.index.union(ohlcv_idx)
    aligned = snapshot.reindex(combined_idx).sort_index().ffill()
    aligned = aligned.reindex(ohlcv_idx)

    out["Analyst_Buy_Ratio"] = aligned["buy_ratio"].values
    out["Analyst_Total_Count"] = aligned["total"].values
    return out


def attach_fundamentals_to_tickers(
    data_dict: Dict[str, pd.DataFrame],
    fundamentals: Dict[str, Dict[str, pd.DataFrame]],
) -> Dict[str, pd.DataFrame]:
    """
    Merge per-ticker fundamentals into each OHLCV frame.
    Drops columns that end up 100% NaN across the whole universe — this
    happens e.g. with yfinance's recommendations which only cover the last
    ~4 months (no overlap with older backtest data).
    """
    out = {}
    stats = {"with_earnings": 0, "with_recs": 0, "neither": 0}
    for sym, df in data_dict.items():
        f = fundamentals.get(sym, {})
        earn = f.get("earnings")
        recs = f.get("recommendations")
        tmp = compute_earnings_features(df, earn)
        tmp = compute_analyst_features(tmp, recs)
        out[sym] = tmp
        if earn is not None and not earn.empty:
            stats["with_earnings"] += 1
        if recs is not None and not recs.empty:
            stats["with_recs"] += 1
        if (earn is None or earn.empty) and (recs is None or recs.empty):
            stats["neither"] += 1

    # Drop fundamental columns with insufficient coverage (< 50% non-NaN
    # across the universe). Otherwise dropna() in feature engineering kills
    # all rows. This happens with yfinance recommendations which only span
    # ~4 months (vs 3+ years of OHLCV).
    fund_cols = ["Days_To_Next_Earnings", "Days_Since_Last_Earnings",
                 "Analyst_Buy_Ratio", "Analyst_Total_Count"]
    MIN_COVERAGE = 0.50

    dropped = []
    for col in fund_cols:
        total_rows = 0
        filled_rows = 0
        for df in out.values():
            if col in df.columns:
                total_rows += len(df)
                filled_rows += int(df[col].notna().sum())
        coverage = filled_rows / total_rows if total_rows else 0.0
        if coverage < MIN_COVERAGE:
            for df in out.values():
                if col in df.columns:
                    df.drop(columns=[col], inplace=True)
            dropped.append(f"{col} (coverage={coverage:.0%})")

    if dropped:
        logger.warning(
            f"fundamentals: dropped low-coverage columns: {dropped}"
        )
    logger.info(f"fundamentals attached: {stats}")
    return out
