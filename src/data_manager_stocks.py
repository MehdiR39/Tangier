"""
Stock Data Manager — yfinance batch downloader for the stock scanner.

Mirrors the interface of DataManager (fetch_data / prepare_data /
fetch_multiple_coins) so it can plug into the existing FeatureEngineer
and ModelTrainer without modification.
"""

import os
import logging
from typing import Dict, List, Optional

import pandas as pd
import numpy as np

from src.data_manager import DataValidator

logger = logging.getLogger(__name__)


class StockDataManager:
    """
    Downloads OHLCV for a list of stock tickers via yfinance.
    Caches to data/stocks/<TICKER>_<interval>.parquet to avoid re-downloads.
    """

    def __init__(self, config):
        self.config = config
        self.validator = DataValidator()
        self.data_cache: Dict[str, pd.DataFrame] = {}
        self.cache_dir = os.path.join(config.DATA_DIR, "stocks")
        os.makedirs(self.cache_dir, exist_ok=True)
        logger.info("StockDataManager initialized")

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------
    def fetch_data(
        self,
        symbol: str,
        interval: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        use_disk_cache: bool = True,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch a single ticker. Returns DataFrame indexed by Date with columns
        Open, High, Low, Close, Volume — matching the crypto DataManager.
        """
        try:
            import yfinance as yf
        except ImportError:
            raise RuntimeError(
                "yfinance not installed. Add `yfinance>=0.2.40` to requirements.txt."
            )

        interval = interval or getattr(self.config, "STOCK_INTERVAL", "1d")
        start = start or getattr(self.config, "DATA_START_DATE", None)
        end = end or getattr(self.config, "DATA_END_DATE", None)

        mem_key = f"{symbol}_{interval}_{start}_{end}"
        if mem_key in self.data_cache:
            return self.data_cache[mem_key].copy()

        disk_path = os.path.join(self.cache_dir, f"{symbol}_{interval}.parquet")
        if use_disk_cache and os.path.exists(disk_path):
            try:
                data = pd.read_parquet(disk_path)
                self.data_cache[mem_key] = data.copy()
                logger.info(f"{symbol}: loaded from disk cache ({len(data)} rows)")
                return data
            except Exception as e:
                logger.warning(f"{symbol}: disk cache read failed ({e}), refetching")

        try:
            logger.info(
                f"Fetching {symbol} from yfinance (interval={interval}, "
                f"{start} -> {end})"
            )
            df = yf.download(
                symbol,
                start=start,
                end=end,
                interval=interval,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            if df is None or df.empty:
                logger.warning(f"{symbol}: empty response from yfinance")
                return None

            # yfinance sometimes returns a MultiIndex (level 0 = field,
            # level 1 = ticker). Flatten it for single-ticker calls.
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
            df.index.name = "Date"
            df = df.dropna()

            if use_disk_cache:
                try:
                    df.to_parquet(disk_path)
                except Exception as e:
                    logger.warning(f"{symbol}: failed to write cache ({e})")

            self.data_cache[mem_key] = df.copy()
            return df

        except Exception as e:
            logger.error(f"{symbol}: fetch failed — {e}")
            return None

    # ------------------------------------------------------------------
    # Prepare (same contract as DataManager.prepare_data)
    # ------------------------------------------------------------------
    def prepare_data(self, data: pd.DataFrame, symbol: str) -> pd.DataFrame:
        data = data.copy()
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            data[col] = pd.to_numeric(data[col], errors="coerce")
        data = data.dropna().sort_index()

        if data.empty:
            raise ValueError(f"{symbol}: dataset became empty after preprocessing")

        # Stocks have legitimate large volume spikes on earnings — keep them
        # but warn on extreme outliers.
        if len(data) > 30:
            vol_z = (data["Volume"] - data["Volume"].mean()) / (data["Volume"].std() + 1e-10)
            n_outliers = int((vol_z.abs() > 10).sum())
            if n_outliers:
                logger.info(f"{symbol}: {n_outliers} extreme volume bars kept")

        logger.info(f"{symbol}: prepared ({len(data)} rows)")
        return data

    # ------------------------------------------------------------------
    # Batch
    # ------------------------------------------------------------------
    def fetch_universe(
        self,
        symbols: Optional[List[str]] = None,
        min_rows: Optional[int] = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch + prepare all tickers. Drops tickers with insufficient history.
        """
        symbols = symbols or getattr(self.config, "STOCK_UNIVERSE", [])
        min_rows = min_rows or getattr(self.config, "MIN_CANDLES", 250)

        out: Dict[str, pd.DataFrame] = {}
        skipped: List[str] = []

        for i, sym in enumerate(symbols, 1):
            raw = self.fetch_data(sym)
            if raw is None or len(raw) < min_rows:
                skipped.append(sym)
                continue
            try:
                out[sym] = self.prepare_data(raw, sym)
            except Exception as e:
                logger.warning(f"{sym}: prepare failed ({e})")
                skipped.append(sym)

            if i % 25 == 0:
                logger.info(f"Progress: {i}/{len(symbols)} tickers fetched")

        logger.info(
            f"Universe loaded: {len(out)} ok / {len(skipped)} skipped "
            f"(need >= {min_rows} rows)"
        )
        if skipped:
            logger.debug(f"Skipped tickers: {skipped}")
        return out

    # ------------------------------------------------------------------
    # Universe helpers
    # ------------------------------------------------------------------
    @staticmethod
    def sp500_tickers() -> List[str]:
        """
        Pulls the current S&P 500 constituent list from Wikipedia.
        Cheap, no auth. Replace `.` with `-` for yfinance (BRK.B -> BRK-B).
        """
        import urllib.request
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (stock-scanner bot)"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        from io import StringIO
        tables = pd.read_html(StringIO(html))
        tickers = tables[0]["Symbol"].astype(str).str.replace(".", "-", regex=False)
        return tickers.tolist()


if __name__ == "__main__":
    # Quick smoke test
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import config

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    dm = StockDataManager(config)
    df = dm.fetch_data("AAPL", interval="1d", start="2023-01-01", end="2026-01-01")
    print(df.tail() if df is not None else "no data")
