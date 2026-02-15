"""
Improved Data Manager with Multi-Coin Support and Validation
Handles data retrieval, validation, and preprocessing for multiple cryptocurrencies
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
import os

logger = logging.getLogger(__name__)


class DataValidator:
    """Validates data quality and detects anomalies."""
    
    @staticmethod
    def validate_data(data: pd.DataFrame, symbol: str, config) -> Tuple[bool, str]:
        """
        Validate data quality.
        
        Args:
            data: DataFrame with OHLCV data
            symbol: Trading symbol
            config: Configuration object
        
        Returns:
            Tuple of (is_valid, message)
        """
        # Check minimum candles
        if len(data) < config.MIN_CANDLES:
            return False, f"{symbol}: Insufficient data ({len(data)} < {config.MIN_CANDLES})"
        
        # Check for NaN values
        nan_count = data.isnull().sum().sum()
        if nan_count > 0:
            return False, f"{symbol}: Contains {nan_count} NaN values"
        
        # Check for price gaps
        price_changes = data['Close'].pct_change().abs()
        max_gap = price_changes.max()
        if max_gap > config.MAX_PRICE_GAP:
            return False, f"{symbol}: Price gap too large ({max_gap:.2%})"
        
        # Check for volume spikes
        volume_ma = data['Volume'].rolling(20).mean()
        volume_ratio = data['Volume'] / volume_ma
        max_spike = volume_ratio.max()
        if max_spike > config.MAX_VOLUME_SPIKE:
            logger.warning(f"{symbol}: Large volume spike detected ({max_spike:.1f}x)")
        
        # Check for duplicate timestamps
        if data.index.duplicated().any():
            return False, f"{symbol}: Duplicate timestamps found"
        
        # Check if data is sorted chronologically
        if not data.index.is_monotonic_increasing:
            return False, f"{symbol}: Data not sorted chronologically"
        
        return True, f"{symbol}: Data validation passed ({len(data)} candles)"
    
    @staticmethod
    def remove_outliers(data: pd.DataFrame, column: str, std_threshold: float = 5) -> pd.DataFrame:
        """
        Remove statistical outliers from a column.
        
        Args:
            data: DataFrame
            column: Column name to clean
            std_threshold: Number of standard deviations for outlier detection
        
        Returns:
            Cleaned DataFrame
        """
        data = data.copy()
        mean = data[column].mean()
        std = data[column].std()
        
        mask = np.abs((data[column] - mean) / std) <= std_threshold
        removed = (~mask).sum()
        
        if removed > 0:
            logger.warning(f"Removed {removed} outliers from {column}")
            data = data[mask]
        
        return data


class DataManager:
    """
    Manages data retrieval, validation, and preprocessing for multiple cryptocurrencies.
    Incorporates all bias mitigation strategies.
    """
    
    def __init__(self, config):
        """
        Initialize DataManager.
        
        Args:
            config: Configuration object
        """
        self.config = config
        self.validator = DataValidator()
        self.data_cache = {}
        logger.info("DataManager initialized")
    
    def fetch_data(self, symbol: str, interval: str = None, start_time: str = None) -> Optional[pd.DataFrame]:
        """
        Fetch historical data from Binance (simulated with cached data).
        In production, integrate with actual Binance API.
        
        Args:
            symbol: Trading symbol (e.g., 'BTCUSDT')
            interval: Candle interval (default from config)
            start_time: Start time (default from config)
        
        Returns:
            DataFrame with OHLCV data or None if fetch fails
        """
        if interval is None:
            interval = self.config.BINANCE_INTERVAL
        if start_time is None:
            start_time = self.config.BINANCE_START_TIME
        
        # Use fixed dates from config if available
        data_start = getattr(self.config, 'DATA_START_DATE', None)
        data_end = getattr(self.config, 'DATA_END_DATE', None)
        if data_start:
            start_time = data_start
        
        # Check cache first
        cache_key = f"{symbol}_{interval}_{data_start}_{data_end}_{start_time}"
        if cache_key in self.data_cache:
            logger.info(f"Loading {symbol} from cache")
            return self.data_cache[cache_key].copy()
        
        try:
            logger.info(f"Fetching {symbol} data from Binance (interval: {interval}, start: {start_time})")
            
            # Try to fetch from Binance API
            try:
                from binance.client import Client
                import os
                from dotenv import load_dotenv
                
                # Load environment variables from .env file
                load_dotenv()
                
                api_key = os.getenv('BINANCE_API_KEY')
                api_secret = os.getenv('BINANCE_API_SECRET')
                
                if api_key and api_secret:
                    client = Client(api_key, api_secret)
                    klines = client.get_historical_klines(symbol, interval, start_time)
                    
                    # Convert to DataFrame
                    data = pd.DataFrame(klines, columns=[
                        'Date', 'Open', 'High', 'Low', 'Close', 'Volume',
                        'Close_time', 'Quote_asset_volume', 'Number_of_trades',
                        'Taker_buy_base', 'Taker_buy_quote', 'Ignore'
                    ])
                    
                    # Keep only OHLCV columns
                    data = data[['Date', 'Open', 'High', 'Low', 'Close', 'Volume']]
                    
                    # Convert types
                    data['Date'] = pd.to_datetime(data['Date'], unit='ms')
                    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                        data[col] = pd.to_numeric(data[col])
                    
                    data.set_index('Date', inplace=True)
                    
                    # Filter by fixed date range if specified
                    if data_start:
                        data = data[data.index >= pd.Timestamp(data_start)]
                    if data_end:
                        data = data[data.index <= pd.Timestamp(data_end)]

                    if data.empty:
                        raise RuntimeError(
                            f"No candles returned for {symbol} in range {data_start} -> {data_end}"
                        )
                    
                    logger.info(f"Successfully fetched {len(data)} candles from Binance "
                                f"({str(data.index[0])[:10]} to {str(data.index[-1])[:10]})")
                else:
                    raise RuntimeError(
                        "Binance API keys not found in .env file. "
                        "Create a .env file with BINANCE_API_KEY and BINANCE_API_SECRET"
                    )
            
            except ImportError:
                raise RuntimeError(
                    "python-binance not installed. "
                    "Install with: pip install python-binance python-dotenv"
                )
            except Exception as e:
                raise RuntimeError(
                    f"Could not fetch {symbol} from Binance: {str(e)}. "
                    "Make sure your API keys are valid and you have internet access."
                ) from e
            
            # Validate data
            is_valid, message = self.validator.validate_data(data, symbol, self.config)
            if not is_valid:
                logger.error(message)
                return None
            
            logger.info(message)
            
            # Cache the data
            self.data_cache[cache_key] = data.copy()
            
            return data
        
        except Exception as e:
            logger.error(f"Error fetching {symbol}: {str(e)}")
            return None

    
    def prepare_data(self, data: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        Prepare data for feature engineering.
        
        Args:
            data: Raw OHLCV data
            symbol: Trading symbol
        
        Returns:
            Prepared DataFrame
        """
        data = data.copy()
        
        # Ensure numeric types
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            data[col] = pd.to_numeric(data[col], errors='coerce')
        
        # Remove any NaN values
        data = data.dropna()
        
        # Remove outliers
        data = self.validator.remove_outliers(data, 'Volume', std_threshold=5)

        if data.empty:
            raise ValueError(f"{symbol}: dataset became empty after preprocessing")
        
        # Sort by date (ensure chronological order)
        data = data.sort_index()
        
        logger.info(f"{symbol}: Data prepared ({len(data)} candles)")
        
        return data
    
    def fetch_multiple_coins(self, symbols: List[str] = None) -> Dict[str, pd.DataFrame]:
        """
        Fetch data for multiple cryptocurrencies.
        
        Args:
            symbols: List of symbols (default from config)
        
        Returns:
            Dictionary of {symbol: DataFrame}
        """
        if symbols is None:
            symbols = self.config.SYMBOLS
        
        data_dict = {}
        
        for symbol in symbols:
            logger.info(f"Processing {symbol}...")
            
            # Fetch data
            raw_data = self.fetch_data(symbol)
            if raw_data is None:
                logger.warning(f"Skipping {symbol} due to fetch error")
                continue
            
            # Prepare data
            prepared_data = self.prepare_data(raw_data, symbol)
            
            data_dict[symbol] = prepared_data
        
        logger.info(f"Successfully loaded {len(data_dict)} coins")
        
        return data_dict
    
    def save_data(self, data: pd.DataFrame, symbol: str) -> str:
        """
        Save data to CSV file.
        
        Args:
            data: DataFrame to save
            symbol: Trading symbol
        
        Returns:
            Path to saved file
        """
        filepath = os.path.join(self.config.DATA_DIR, f"{symbol}_data.csv")
        data.to_csv(filepath)
        logger.info(f"Data saved: {filepath}")
        return filepath
    
    def load_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        Load data from CSV file.
        
        Args:
            symbol: Trading symbol
        
        Returns:
            DataFrame or None if file not found
        """
        filepath = os.path.join(self.config.DATA_DIR, f"{symbol}_data.csv")
        
        if not os.path.exists(filepath):
            logger.warning(f"Data file not found: {filepath}")
            return None
        
        data = pd.read_csv(filepath, index_col='Date', parse_dates=True)
        logger.info(f"Data loaded: {filepath}")
        return data
    
    def split_data(self, data: pd.DataFrame, test_size: float = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Split data into train and test sets.
        Uses fixed TEST_START_DATE from config if available, otherwise falls back to TEST_SIZE.
        
        Args:
            data: Full dataset
            test_size: Test set size (default from config)
        
        Returns:
            Tuple of (train_data, test_data)
        """
        test_start = getattr(self.config, 'TEST_START_DATE', None)
        
        if test_start and isinstance(data.index, pd.DatetimeIndex):
            # Use fixed date split
            test_start_ts = pd.Timestamp(test_start)
            train_data = data[data.index < test_start_ts]
            test_data = data[data.index >= test_start_ts]

            if len(train_data) > 0 and len(test_data) > 0:
                logger.info(f"Data split by date ({test_start}): "
                            f"{len(train_data)} train ({str(train_data.index[0])[:10]} to {str(train_data.index[-1])[:10]}), "
                            f"{len(test_data)} test ({str(test_data.index[0])[:10]} to {str(test_data.index[-1])[:10]})")
            else:
                logger.warning(f"Data split by date ({test_start}) produced empty side: "
                               f"train={len(train_data)}, test={len(test_data)}")
        else:
            # Fallback to percentage split
            if test_size is None:
                test_size = self.config.TEST_SIZE
            split_idx = int(len(data) * (1 - test_size))
            train_data = data.iloc[:split_idx]
            test_data = data.iloc[split_idx:]
            logger.info(f"Data split: {len(train_data)} train, {len(test_data)} test")
        
        return train_data, test_data
    
    def get_walk_forward_splits(self, data: pd.DataFrame) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
        """
        Generate walk-forward validation splits.
        
        Args:
            data: Full dataset
        
        Returns:
            List of (train_data, test_data) tuples
        """
        if not self.config.WALK_FORWARD_ENABLED:
            return [(data, data)]
        
        splits = []
        train_period = self.config.WALK_FORWARD_TRAIN_PERIOD
        test_period = self.config.WALK_FORWARD_TEST_PERIOD
        step = self.config.WALK_FORWARD_STEP
        
        for i in range(0, len(data) - train_period - test_period, step):
            train_end = i + train_period
            test_end = train_end + test_period
            
            if test_end > len(data):
                break
            
            train_data = data.iloc[i:train_end]
            test_data = data.iloc[train_end:test_end]
            
            splits.append((train_data, test_data))
        
        logger.info(f"Generated {len(splits)} walk-forward splits")
        
        return splits


if __name__ == "__main__":
    # Example usage
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'config'))
    from config import *
    
    logging.basicConfig(level=logging.INFO)
    
    manager = DataManager(sys.modules[__name__])
    data_dict = manager.fetch_multiple_coins()
    
    for symbol, data in data_dict.items():
        print(f"\n{symbol}:")
        print(f"  Shape: {data.shape}")
        print(f"  Date range: {data.index[0]} to {data.index[-1]}")
        print(f"  Price range: ${data['Close'].min():.2f} - ${data['Close'].max():.2f}")
