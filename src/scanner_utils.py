"""
Scanner Utilities — metadata fetch + universe filters.

Fetches per-ticker metadata (sector, industry, market cap) via yfinance
and caches to parquet. Exposes helpers to filter a universe by liquidity,
sector, and market cap.
"""

import os
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Iterable

import pandas as pd

logger = logging.getLogger(__name__)

META_COLS = ["ticker", "shortName", "sector", "industry",
             "marketCap", "averageVolume", "currency"]


# ---------------------------------------------------------------------------
# Metadata fetching
# ---------------------------------------------------------------------------
def _fetch_one_meta(symbol: str) -> Optional[dict]:
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info or {}
    except Exception as e:
        logger.debug(f"{symbol}: info fetch failed — {e}")
        return None

    if not info.get("shortName") and not info.get("longName"):
        return None

    return {
        "ticker": symbol,
        "shortName": info.get("shortName") or info.get("longName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "marketCap": info.get("marketCap"),
        "averageVolume": info.get("averageVolume"),
        "currency": info.get("currency"),
    }


def fetch_metadata(
    symbols: Iterable[str],
    cache_path: Optional[str] = None,
    max_workers: int = 10,
    refresh: bool = False,
) -> pd.DataFrame:
    """
    Fetch metadata for a list of tickers in parallel and cache as parquet.
    Returns a DataFrame with columns META_COLS. Missing tickers are dropped.
    """
    symbols = list(dict.fromkeys(symbols))  # dedup, preserve order

    if cache_path and os.path.exists(cache_path) and not refresh:
        cached = pd.read_parquet(cache_path)
        missing = [s for s in symbols if s not in set(cached["ticker"])]
        if not missing:
            logger.info(f"metadata: cache hit ({len(cached)} rows)")
            return cached[cached["ticker"].isin(symbols)].reset_index(drop=True)
        logger.info(f"metadata: {len(missing)} tickers missing from cache, fetching...")
        fetch_list = missing
        existing = cached
    else:
        fetch_list = symbols
        existing = pd.DataFrame(columns=META_COLS)

    rows: List[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one_meta, s): s for s in fetch_list}
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            if r:
                rows.append(r)
            if i % 25 == 0:
                logger.info(f"metadata: {i}/{len(fetch_list)} fetched")

    new_df = pd.DataFrame(rows, columns=META_COLS)
    out = pd.concat([existing, new_df], ignore_index=True).drop_duplicates("ticker")

    if cache_path:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        out.to_parquet(cache_path)
        logger.info(f"metadata: saved {len(out)} rows to {cache_path}")

    return out[out["ticker"].isin(symbols)].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Liquidity (from OHLCV — no extra API call)
# ---------------------------------------------------------------------------
def dollar_volume(data: pd.DataFrame, window: int = 20) -> pd.Series:
    """Rolling avg dollar volume = Close * Volume, smoothed."""
    return (data["Close"] * data["Volume"]).rolling(window).mean()


def recent_dollar_volume(data: pd.DataFrame, window: int = 20) -> float:
    """Scalar — dollar-volume average over the last `window` bars."""
    dv = dollar_volume(data, window).dropna()
    return float(dv.iloc[-1]) if len(dv) else 0.0


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
def filter_universe(
    data_dict: Dict[str, pd.DataFrame],
    metadata: Optional[pd.DataFrame] = None,
    min_dollar_volume: Optional[float] = None,
    min_market_cap: Optional[float] = None,
    include_sectors: Optional[List[str]] = None,
    exclude_sectors: Optional[List[str]] = None,
) -> Dict[str, pd.DataFrame]:
    """
    Filter a universe in-place. Returns a new dict with only surviving tickers.

    min_dollar_volume — min 20-day avg USD volume (e.g. 50_000_000)
    min_market_cap    — in USD (e.g. 2_000_000_000 for > $2B)
    include_sectors   — whitelist (e.g. ["Technology", "Healthcare"])
    exclude_sectors   — blacklist
    """
    meta_by_ticker = {}
    if metadata is not None:
        meta_by_ticker = metadata.set_index("ticker").to_dict(orient="index")

    kept = {}
    drop_reasons: Dict[str, int] = {}

    def bump(reason: str):
        drop_reasons[reason] = drop_reasons.get(reason, 0) + 1

    for sym, df in data_dict.items():
        # Liquidity filter
        if min_dollar_volume is not None:
            if recent_dollar_volume(df) < min_dollar_volume:
                bump("illiquid")
                continue

        if meta_by_ticker:
            m = meta_by_ticker.get(sym, {})

            if min_market_cap is not None:
                mc = m.get("marketCap")
                if mc is None or mc < min_market_cap:
                    bump("small_cap")
                    continue

            sector = m.get("sector")
            if include_sectors is not None:
                if sector not in include_sectors:
                    bump("sector_not_included")
                    continue
            if exclude_sectors is not None and sector in exclude_sectors:
                bump("sector_excluded")
                continue

        kept[sym] = df

    logger.info(
        f"Filter: kept {len(kept)}/{len(data_dict)} tickers. "
        f"Dropped: {drop_reasons}"
    )
    return kept
