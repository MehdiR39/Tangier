"""
Robust Backtester Module
Uses the exact proven backtesting logic from the user's backtesting_func.py
Simulates trading with realistic conditions: fees, slippage, stop-loss, take-profit.
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class BacktestResults:
    """Stores all backtest results in a structured format."""
    symbol: str = ""
    model_type: str = ""
    total_return_pct: float = 0.0
    buy_hold_return_pct: float = 0.0
    outperformance_pct: float = 0.0
    sharpe_ratio: float = 0.0
    calmar_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    num_trades: int = 0
    avg_trade_return: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    capital_history: list = field(default_factory=list)
    buy_hold_history: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    signals_used: np.ndarray = field(default_factory=lambda: np.array([]))
    data_used: pd.DataFrame = field(default_factory=pd.DataFrame)
    dates: list = field(default_factory=list)


class RobustBacktester:
    """
    Backtester using exact logic from user's proven backtesting_func.py
    Signals: 0=Sell, 1=Hold, 2=Buy
    
    Capital tracking:
    - At entry: capital *= (1 - fee)
    - At exit: capital *= (close * (1 - fee)) / entry_price
    - Capital history shows actual capital at each candle
    """

    def __init__(self, config):
        self.config = config
        self.fee = getattr(config, 'TRADING_FEE', 0.001)
        self.slippage = getattr(config, 'SLIPPAGE', 0.0)
        self.stop_loss = getattr(config, 'STOP_LOSS', 0.05)
        self.take_profit = getattr(config, 'TAKE_PROFIT', 0.15)
        self.initial_capital = getattr(config, 'INITIAL_CAPITAL', 10000)
        self.use_next_open_for_entry = getattr(config, 'USE_NEXT_OPEN_FOR_ENTRY', False)
        self.include_slippage = getattr(config, 'INCLUDE_SLIPPAGE', False)
        self.annual_periods = getattr(config, 'ANNUAL_PERIODS', 252)
        logger.info(
            f"RobustBacktester initialized (fee={self.fee}, slippage={self.slippage}, "
            f"SL={self.stop_loss}, TP={self.take_profit}, next_open={self.use_next_open_for_entry})"
        )

    def backtest(self, data: pd.DataFrame, signals: np.ndarray, symbol: str,
                 model_type: str = "unknown",
                 stop_loss: float = None, take_profit: float = None) -> BacktestResults:
        """
        Run a backtest on aligned data and signals.
        Uses exact logic from user's backtesting_func.py

        Args:
            data: OHLCV DataFrame (must contain Open, High, Low, Close)
            signals: Array of signals (0=Sell, 1=Hold, 2=Buy), same length as data
            symbol: Trading symbol
            model_type: Model type name for results
            stop_loss: Override stop loss (default: from config)
            take_profit: Override take profit (default: from config)

        Returns:
            BacktestResults dataclass
        """
        if stop_loss is None:
            stop_loss = self.stop_loss
        if take_profit is None:
            take_profit = self.take_profit

        # Ensure alignment
        n = min(len(data), len(signals))
        if n == 0:
            logger.warning(f"Backtesting {symbol} ({model_type}): empty data/signals")
            return BacktestResults(
                symbol=symbol,
                model_type=model_type,
                total_return_pct=0.0,
                buy_hold_return_pct=0.0,
                outperformance_pct=0.0,
                sharpe_ratio=0.0,
                calmar_ratio=0.0,
                max_drawdown=0.0,
                win_rate=0.0,
                profit_factor=0.0,
                num_trades=0,
                avg_trade_return=0.0,
                avg_win=0.0,
                avg_loss=0.0,
                max_consecutive_wins=0,
                max_consecutive_losses=0,
                capital_history=[],
                buy_hold_history=[],
                trades=[],
                signals_used=np.array([]),
                data_used=pd.DataFrame(),
                dates=[]
            )
        
        df_raw = data.iloc[:n].copy()
        signals = np.asarray(signals[:n])

        valid_mask = df_raw['Close'].notna().to_numpy()
        df_raw = df_raw.loc[valid_mask]
        signals = signals[valid_mask]

        if hasattr(df_raw.index, 'to_pydatetime'):
            dates = df_raw.index.tolist()
        else:
            dates = list(range(len(df_raw)))

        df = df_raw.reset_index(drop=True)
        if len(df) == 0:
            logger.warning(f"Backtesting {symbol} ({model_type}): no valid Close prices")
            return BacktestResults(symbol=symbol, model_type=model_type)

        logger.info(f"Backtesting {symbol} ({model_type}): {len(df)} candles, SL={stop_loss:.2%}, TP={take_profit:.2%}")

        # Initialize state (exact logic from backtesting_func.py)
        capital = self.initial_capital
        position_open = False
        entry_price = None
        entry_idx = 0
        pending_entry_idx = None
        pending_entry_price = None
        
        capital_history = []
        trade_profits = []
        trades = []
        
        # Buy & Hold benchmark
        buy_hold_capital = self.initial_capital
        initial_price = df['Close'].iloc[0]
        if initial_price <= 0:
            logger.warning(f"Backtesting {symbol} ({model_type}): invalid initial price {initial_price}")
            return BacktestResults(symbol=symbol, model_type=model_type)
        buy_hold_history = []

        # Process each candle (exact logic from backtesting_func.py)
        for idx, row in df.iterrows():
            close = row['Close']
            signal = signals[idx]
            just_entered = False

            # Buy and Hold update
            buy_hold_capital = self.initial_capital * (close / initial_price)
            buy_hold_history.append(buy_hold_capital)

            # Execute pending delayed entry (next candle open)
            if not position_open and pending_entry_idx is not None and idx == pending_entry_idx:
                entry_price = pending_entry_price
                entry_idx = idx
                capital *= (1 - self.fee)
                position_open = True
                just_entered = True
                pending_entry_idx = None
                pending_entry_price = None

            # Check for entry signal
            if not position_open and pending_entry_idx is None and signal == 2:
                if self.use_next_open_for_entry and idx + 1 < len(df):
                    raw_entry = float(df['Open'].iloc[idx + 1])
                    pending_entry_idx = idx + 1
                else:
                    raw_entry = close
                    pending_entry_idx = None

                exec_entry = raw_entry * (1 + self.slippage) if self.include_slippage else raw_entry

                if self.use_next_open_for_entry and idx + 1 < len(df):
                    pending_entry_price = exec_entry
                else:
                    entry_price = exec_entry
                    entry_idx = idx
                    capital *= (1 - self.fee)
                    position_open = True
                    just_entered = True

            # Check for exit conditions
            if position_open and not just_entered:
                pct_change = (close - entry_price) / entry_price
                exit_condition = (
                    pct_change <= -stop_loss or
                    pct_change >= take_profit or
                    signal == 0
                )

                if exit_condition:
                    raw_exit = close
                    exec_exit = raw_exit * (1 - self.slippage) if self.include_slippage else raw_exit
                    capital *= (exec_exit * (1 - self.fee)) / entry_price
                    trade_profit = (exec_exit / entry_price - 1) - 2 * self.fee
                    trade_profits.append(trade_profit)
                    
                    # Record trade
                    trades.append({
                        'entry_idx': entry_idx,
                        'exit_idx': idx,
                        'entry_price': entry_price,
                        'exit_price': exec_exit,
                        'pnl_pct': trade_profit * 100,
                        'reason': 'stop_loss' if pct_change <= -stop_loss else ('take_profit' if pct_change >= take_profit else 'sell_signal')
                    })
                    
                    position_open = False
                    entry_price = None

            # Record capital at this candle
            capital_history.append(capital)

        # Close open position at the end (exact logic from backtesting_func.py)
        if position_open:
            final_price = df['Close'].iloc[-1]
            exec_final = final_price * (1 - self.slippage) if self.include_slippage else final_price
            capital *= (exec_final * (1 - self.fee)) / entry_price
            trade_profit = (exec_final / entry_price - 1) - 2 * self.fee
            trade_profits.append(trade_profit)
            
            trades.append({
                'entry_idx': entry_idx,
                'exit_idx': len(df) - 1,
                'entry_price': entry_price,
                'exit_price': exec_final,
                'pnl_pct': trade_profit * 100,
                'reason': 'end_of_data'
            })

        # Calculate metrics (exact logic from backtesting_func.py)
        capital_history = np.array(capital_history)
        returns = np.diff(capital_history) / capital_history[:-1] if len(capital_history) > 1 else np.array([0])

        peak = np.maximum.accumulate(capital_history)
        drawdowns = (peak - capital_history) / peak
        max_drawdown = np.max(drawdowns) if len(drawdowns) > 0 else 0

        sharpe = (np.mean(returns) / np.std(returns) * np.sqrt(self.annual_periods)) if np.std(returns) > 0 else 0.0
        
        # Total returns
        total_return = (capital / self.initial_capital - 1) * 100
        buy_hold_return = (buy_hold_capital / self.initial_capital - 1) * 100

        # Calmar ratio
        calmar = (total_return / 100) / (max_drawdown + 1e-10) if max_drawdown > 0 else 0

        # Trade statistics
        num_trades = len(trade_profits)
        if num_trades > 0:
            win_rate = np.mean([p > 0 for p in trade_profits]) * 100
            avg_trade_return = np.mean(trade_profits) * 100
            
            wins = [p for p in trade_profits if p > 0]
            losses = [p for p in trade_profits if p < 0]
            avg_win = np.mean(wins) * 100 if wins else 0
            avg_loss = np.mean(losses) * 100 if losses else 0
            
            # Profit factor
            total_wins = sum(w for w in wins)
            total_losses = abs(sum(l for l in losses))
            profit_factor = total_wins / (total_losses + 1e-10) if total_losses > 0 else 0
            
            # Consecutive wins/losses
            max_consecutive_wins = self._max_consecutive(trade_profits, True)
            max_consecutive_losses = self._max_consecutive(trade_profits, False)
        else:
            win_rate = 0
            avg_trade_return = 0
            avg_win = 0
            avg_loss = 0
            profit_factor = 0
            max_consecutive_wins = 0
            max_consecutive_losses = 0

        results = BacktestResults(
            symbol=symbol,
            model_type=model_type,
            total_return_pct=total_return,
            buy_hold_return_pct=buy_hold_return,
            outperformance_pct=total_return - buy_hold_return,
            sharpe_ratio=sharpe,
            calmar_ratio=calmar,
            max_drawdown=max_drawdown * 100,
            win_rate=win_rate,
            profit_factor=profit_factor,
            num_trades=num_trades,
            avg_trade_return=avg_trade_return,
            avg_win=avg_win,
            avg_loss=avg_loss,
            max_consecutive_wins=max_consecutive_wins,
            max_consecutive_losses=max_consecutive_losses,
            capital_history=capital_history.tolist(),
            buy_hold_history=buy_hold_history,
            trades=trades,
            signals_used=signals,
            data_used=df,
            dates=dates
        )

        return results

    @staticmethod
    def _max_consecutive(returns, is_wins):
        """Calculate max consecutive wins or losses."""
        if not returns:
            return 0
        max_count = 0
        current_count = 0
        for r in returns:
            if (is_wins and r > 0) or (not is_wins and r < 0):
                current_count += 1
                max_count = max(max_count, current_count)
            else:
                current_count = 0
        return max_count
