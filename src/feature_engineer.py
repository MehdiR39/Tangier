"""
Advanced Feature Engineering Module
Implements technical indicators with proper look-ahead bias mitigation
Uses pure pandas/numpy implementations (no talib dependency)
"""

import pandas as pd
import numpy as np
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# PURE PANDAS/NUMPY INDICATOR IMPLEMENTATIONS
# ============================================================================

def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (normalized 0-1)."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    return rs / (1 + rs)


def _stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
                k_period: int = 14, d_period: int = 3) -> Tuple[pd.Series, pd.Series]:
    """Stochastic Oscillator (%K and %D), normalized 0-1."""
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    stoch_k = (close - lowest_low) / (highest_high - lowest_low + 1e-10)
    stoch_d = stoch_k.rolling(window=d_period).mean()
    return stoch_k, stoch_d


def _macd(close: pd.Series, fast: int = 12, slow: int = 26,
          signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """MACD (Moving Average Convergence Divergence)."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _bollinger_bands(close: pd.Series, period: int = 20,
                     std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands (upper, middle, lower)."""
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return upper, middle, lower


def _atr(high: pd.Series, low: pd.Series, close: pd.Series,
         period: int = 14) -> pd.Series:
    """Average True Range."""
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.rolling(window=period).mean()


def _sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period).mean()


def _ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def _adx(high: pd.Series, low: pd.Series, close: pd.Series,
         period: int = 14) -> pd.Series:
    """Average Directional Index (normalized 0-1)."""
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    plus_dm = high - prev_high
    minus_dm = prev_low - low
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    atr_smooth = true_range.ewm(alpha=1.0 / period, min_periods=period).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1.0 / period, min_periods=period).mean() / (atr_smooth + 1e-10))
    minus_di = 100 * (minus_dm.ewm(alpha=1.0 / period, min_periods=period).mean() / (atr_smooth + 1e-10))
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10))
    adx = dx.ewm(alpha=1.0 / period, min_periods=period).mean()
    return adx / 100


def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume."""
    direction = np.sign(close.diff())
    direction.iloc[0] = 0
    return (volume * direction).cumsum()


def _roc(series: pd.Series, period: int = 12) -> pd.Series:
    """Rate of Change."""
    return series.pct_change(periods=period) * 100


def _mfi(high: pd.Series, low: pd.Series, close: pd.Series,
         volume: pd.Series, period: int = 14) -> pd.Series:
    """Money Flow Index (normalized 0-1)."""
    typical_price = (high + low + close) / 3
    money_flow = typical_price * volume
    delta = typical_price.diff()
    positive_flow = money_flow.where(delta > 0, 0.0).rolling(window=period).sum()
    negative_flow = money_flow.where(delta <= 0, 0.0).rolling(window=period).sum()
    return positive_flow / (positive_flow + negative_flow + 1e-10)


# ============================================================================
# FEATURE ENGINEER CLASS
# ============================================================================

class FeatureEngineer:
    """
    Generates technical indicators and features for machine learning.
    All indicators are properly lagged to prevent look-ahead bias.
    Uses pure pandas/numpy implementations (no talib required).
    """

    def __init__(self, config):
        self.config = config
        logger.info("FeatureEngineer initialized")

    def engineer_features(self, data: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Generate all features for the dataset."""
        data = data.copy()
        logger.info(f"Engineering features for {symbol}...")

        data = self._add_price_features(data)
        data = self._add_momentum_indicators(data)
        data = self._add_volatility_indicators(data)
        data = self._add_trend_indicators(data)
        data = self._add_volume_indicators(data)

        if getattr(self.config, "ENABLE_CANDLESTICK_PATTERNS", False):
            data = self._add_candlestick_patterns(data)

        if self.config.LAG_INDICATORS:
            data = self._lag_all_indicators(data)

        # Clean infinities and extreme values BEFORE dropping NaN
        data = self._clean_infinities(data)
        
        initial_len = len(data)
        data = data.dropna()
        logger.info(f"Dropped {initial_len - len(data)} NaN rows, {len(data)} remaining")
        logger.info(f"Generated {len(data.columns)} features for {symbol}")
        return data

    def _add_price_features(self, data: pd.DataFrame) -> pd.DataFrame:
        data['Returns'] = data['Close'].pct_change()
        data['Log_Returns'] = np.log(data['Close'] / data['Close'].shift(1))
        data['Price_Range'] = (data['High'] - data['Low']) / data['Close']
        hl_range = data['High'] - data['Low']
        data['Close_Position'] = (data['Close'] - data['Low']) / (hl_range + 1e-10)
        data['Open_Close_Ratio'] = data['Open'] / data['Close']
        return data

    def _add_momentum_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        data['RSI'] = _rsi(data['Close'], self.config.RSI_PERIOD)
        stoch_k, stoch_d = _stochastic(data['High'], data['Low'], data['Close'],
                                        k_period=self.config.STOCHASTIC_PERIOD)
        data['Stochastic_K'] = stoch_k
        data['Stochastic_D'] = stoch_d
        macd, macd_signal, macd_hist = _macd(data['Close'])
        data['MACD'] = macd
        data['MACD_Signal'] = macd_signal
        data['MACD_Hist'] = macd_hist
        for period in self.config.MOMENTUM_PERIODS:
            data[f'Momentum_{period}'] = data['Close'] - data['Close'].shift(period)
            data[f'Momentum_Pct_{period}'] = data['Close'].pct_change(periods=period)
        data['ROC'] = _roc(data['Close'], 12)
        return data

    def _add_volatility_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        upper, middle, lower = _bollinger_bands(data['Close'],
                                                 period=self.config.BOLLINGER_PERIOD,
                                                 std_dev=self.config.BOLLINGER_STD)
        data['BB_Upper'] = upper
        data['BB_Middle'] = middle
        data['BB_Lower'] = lower
        data['BB_Width'] = (upper - lower) / (middle + 1e-10)
        data['BB_Position'] = (data['Close'] - lower) / (upper - lower + 1e-10)
        data['ATR'] = _atr(data['High'], data['Low'], data['Close'], period=self.config.ATR_PERIOD)
        data['ATR_Pct'] = data['ATR'] / (data['Close'] + 1e-10)
        data['HV'] = data['Log_Returns'].rolling(window=20).std()
        hv_ma = data['HV'].rolling(window=50).mean()
        data['Volatility_Norm'] = data['HV'] / (hv_ma + 1e-10)
        return data

    def _add_trend_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        data['SMA_5'] = _sma(data['Close'], self.config.SMA_SHORT)
        data['SMA_20'] = _sma(data['Close'], self.config.SMA_MEDIUM)
        data['SMA_50'] = _sma(data['Close'], self.config.SMA_LONG)
        data['SMA_200'] = _sma(data['Close'], self.config.SMA_VERY_LONG)
        data['EMA_12'] = _ema(data['Close'], 12)
        data['EMA_26'] = _ema(data['Close'], 26)
        data['SMA_5_20_Cross'] = (data['SMA_5'] > data['SMA_20']).astype(int)
        data['SMA_20_50_Cross'] = (data['SMA_20'] > data['SMA_50']).astype(int)
        data['SMA_50_200_Cross'] = (data['SMA_50'] > data['SMA_200']).astype(int)
        data['Price_SMA20_Dist'] = (data['Close'] - data['SMA_20']) / (data['SMA_20'] + 1e-10)
        data['Price_SMA50_Dist'] = (data['Close'] - data['SMA_50']) / (data['SMA_50'] + 1e-10)
        data['ADX'] = _adx(data['High'], data['Low'], data['Close'], 14)
        return data

    def _add_volume_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        data['Volume_MA'] = data['Volume'].rolling(window=self.config.VOLUME_WINDOW).mean()
        data['Volume_Ratio'] = data['Volume'] / (data['Volume_MA'] + 1e-10)
        data['OBV'] = _obv(data['Close'], data['Volume'])
        data['OBV_EMA'] = _ema(data['OBV'], 20)
        data['VROC'] = _roc(data['Volume'], 12)
        data['MFI'] = _mfi(data['High'], data['Low'], data['Close'], data['Volume'], 14)
        return data

    def _add_candlestick_patterns(self, data: pd.DataFrame) -> pd.DataFrame:
        from src.candlestick_patterns import add_all_patterns
        return add_all_patterns(data)

    def _lag_all_indicators(self, data: pd.DataFrame, lag: int = 1) -> pd.DataFrame:
        exclude_cols = ['Open', 'High', 'Low', 'Close', 'Volume', 'Returns', 'Log_Returns']
        for col in data.columns:
            if col not in exclude_cols:
                data[col] = data[col].shift(lag)
        logger.info(f"Lagged all indicators by {lag} period(s)")
        return data

    def get_feature_list(self, data: pd.DataFrame) -> List[str]:
        exclude_cols = ['Open', 'High', 'Low', 'Close', 'Volume', 'Returns', 'Log_Returns', 'Target']
        return [col for col in data.columns if col not in exclude_cols]

    def _clean_infinities(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Replace infinity and extreme values with NaN.
        This allows them to be handled by dropna() later.
        """
        # Replace infinities with NaN
        data = data.replace([np.inf, -np.inf], np.nan)
        
        # Replace extreme values (> 1e10 or < -1e10) with NaN
        for col in data.columns:
            if data[col].dtype in ['float64', 'float32']:
                mask = (data[col].abs() > 1e10)
                data.loc[mask, col] = np.nan
        
        return data
