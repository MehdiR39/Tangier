"""
Visualization Module
Creates coherent, self-explanatory charts for backtesting results.
All plots use ACTUAL backtest data (entry/exit prices from trades).
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.gridspec as gridspec
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Style settings
plt.style.use('seaborn-v0_8-darkgrid')
COLORS = {
    'buy': '#2ecc71',
    'sell': '#e74c3c',
    'hold': '#95a5a6',
    'price': '#2c3e50',
    'equity': '#3498db',
    'buyhold': '#e67e22',
    'drawdown': '#c0392b',
    'tp': '#27ae60',
    'sl': '#e74c3c',
}


class Visualizer:
    """Creates all visualizations for the trading strategy."""

    def __init__(self, config):
        self.config = config
        self.output_dir = getattr(config, 'RESULTS_DIR', 'results')
        os.makedirs(self.output_dir, exist_ok=True)
        logger.info("Visualizer initialized")

    @staticmethod
    def _sanitize_trades(trades: List[Dict], data_len: int) -> List[Dict]:
        if not trades:
            return []

        ordered = sorted(trades, key=lambda t: (int(t.get('entry_idx', -1)), int(t.get('exit_idx', -1))))
        sanitized = []
        last_exit_idx = -1

        for trade in ordered:
            entry_idx = int(trade.get('entry_idx', -1))
            exit_idx = int(trade.get('exit_idx', -1))

            if entry_idx < 0 or exit_idx < 0 or entry_idx >= data_len:
                continue

            exit_idx = min(exit_idx, data_len - 1)
            if exit_idx < entry_idx:
                continue

            if entry_idx <= last_exit_idx:
                continue

            normalized = dict(trade)
            normalized['entry_idx'] = entry_idx
            normalized['exit_idx'] = exit_idx
            sanitized.append(normalized)
            last_exit_idx = exit_idx

        return sanitized

    def _compute_mark_to_market_equity(self, data: pd.DataFrame, trades: List[Dict]) -> np.ndarray:
        closes = data['Close'].to_numpy(dtype=float)
        n = len(closes)
        if n == 0:
            return np.array([])

        fee = float(getattr(self.config, 'TRADING_FEE', 0.001))
        equity = np.zeros(n, dtype=float)
        capital = float(getattr(self.config, 'INITIAL_CAPITAL', 10000))

        trade_idx = 0
        in_position = False
        units = 0.0

        for candle_idx in range(n):
            while trade_idx < len(trades) and trades[trade_idx]['entry_idx'] == candle_idx:
                entry_price = float(trades[trade_idx]['entry_price'])
                if not in_position and entry_price > 0:
                    units = (capital * (1 - fee)) / entry_price
                    in_position = True
                break

            if in_position:
                equity[candle_idx] = units * closes[candle_idx]
            else:
                equity[candle_idx] = capital

            while trade_idx < len(trades) and trades[trade_idx]['exit_idx'] == candle_idx:
                if in_position:
                    capital = units * closes[candle_idx] * (1 - fee)
                    equity[candle_idx] = capital
                    units = 0.0
                    in_position = False
                trade_idx += 1

        return equity

    def plot_backtest_summary(self, results, save: bool = True) -> str:
        """
        Create a comprehensive 4-panel backtest summary:
        1. Price chart with ACTUAL trade entry/exit markers
        2. Equity curve vs Buy & Hold
        3. Drawdown chart
        4. Trade P&L distribution

        Args:
            results: BacktestResults dataclass
            save: Whether to save the figure

        Returns:
            Path to saved figure
        """
        fig = plt.figure(figsize=(20, 16))
        gs = gridspec.GridSpec(4, 1, height_ratios=[3, 2, 1, 1], hspace=0.3)

        data = results.data_used
        trades = self._sanitize_trades(results.trades, len(data))

        # Determine date axis - prefer results.dates (preserved from original data)
        if hasattr(results, 'dates') and len(results.dates) > 0 and not isinstance(results.dates[0], int):
            x_axis = pd.DatetimeIndex(results.dates[:len(data)])
            use_dates = True
        elif hasattr(data, 'index') and isinstance(data.index, pd.DatetimeIndex):
            x_axis = data.index
            use_dates = True
        elif 'Date' in data.columns:
            x_axis = pd.to_datetime(data['Date'])
            use_dates = True
        else:
            x_axis = np.arange(len(data))
            use_dates = False

        # ---- Panel 1: Price + Actual Trade Markers ----
        ax1 = fig.add_subplot(gs[0])
        ax1.plot(x_axis, data['Close'].values, color=COLORS['price'], linewidth=0.8, alpha=0.8, label='Close Price')

        # Plot ACTUAL entry/exit points from trades
        for trade in trades:
            entry_i = trade['entry_idx']
            exit_i = trade['exit_idx']
            if entry_i < len(x_axis):
                ax1.scatter(x_axis[entry_i], trade['entry_price'],
                           marker='^', color=COLORS['buy'], s=60, zorder=5, edgecolors='black', linewidths=0.5)
            if exit_i < len(x_axis):
                color = '#2980b9' if trade['pnl_pct'] > 0 else COLORS['sl']
                ax1.scatter(x_axis[exit_i], trade['exit_price'],
                           marker='v', color=color, s=60, zorder=5, edgecolors='black', linewidths=0.5)

        # Add SMA if available
        if 'SMA_20' in data.columns:
            ax1.plot(x_axis, data['SMA_20'].values, color='orange', linewidth=0.6, alpha=0.5, label='SMA 20')
        if 'SMA_50' in data.columns:
            ax1.plot(x_axis, data['SMA_50'].values, color='purple', linewidth=0.6, alpha=0.5, label='SMA 50')

        # Custom legend
        from matplotlib.lines import Line2D
        legend_elements = [
            Line2D([0], [0], color=COLORS['price'], lw=1, label='Close Price'),
            Line2D([0], [0], marker='^', color='w', markerfacecolor=COLORS['buy'],
                   markersize=10, label=f'Long Entry ({len(trades)} trades)'),
            Line2D([0], [0], marker='v', color='w', markerfacecolor='#2980b9',
                   markersize=10, label='Profitable Exit (Sell)'),
            Line2D([0], [0], marker='v', color='w', markerfacecolor=COLORS['sl'],
                   markersize=10, label='Loss Exit (Sell)'),
        ]
        ax1.legend(handles=legend_elements, loc='upper left', fontsize=9)

        # Date range in title
        if use_dates:
            date_start = x_axis.iloc[0] if hasattr(x_axis, 'iloc') else x_axis[0]
            date_end = x_axis.iloc[-1] if hasattr(x_axis, 'iloc') else x_axis[-1]
            title_dates = f" | {str(date_start)[:10]} to {str(date_end)[:10]}"
        else:
            title_dates = f" | {len(data)} candles"

        ax1.set_title(f"{results.symbol} - {results.model_type.upper()} | "
                       f"Return: {results.total_return_pct:.1f}% vs B&H: {results.buy_hold_return_pct:.1f}% | "
                       f"Sharpe: {results.sharpe_ratio:.2f}{title_dates}",
                       fontsize=13, fontweight='bold')
        ax1.set_ylabel('Price (USDT)')
        ax1.grid(True, alpha=0.3)
        if use_dates:
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            ax1.xaxis.set_major_locator(mdates.AutoDateLocator())
            plt.setp(ax1.xaxis.get_majorticklabels(), rotation=30, ha='right', fontsize=8)

        # ---- Panel 2: Equity Curve vs Buy & Hold ----
        ax2 = fig.add_subplot(gs[1])
        cap_hist = self._compute_mark_to_market_equity(data, trades)
        if len(cap_hist) == 0:
            cap_hist = np.array(results.capital_history)
        bh_hist = np.array(results.buy_hold_history)

        # Align x-axis lengths
        eq_x = x_axis[:len(cap_hist)] if len(x_axis) >= len(cap_hist) else np.arange(len(cap_hist))
        bh_x = x_axis[:len(bh_hist)] if len(x_axis) >= len(bh_hist) else np.arange(len(bh_hist))

        ax2.plot(eq_x, cap_hist, color=COLORS['equity'], linewidth=1.2, label=f'Strategy ({results.total_return_pct:.1f}%)')
        ax2.plot(bh_x, bh_hist, color=COLORS['buyhold'], linewidth=1.2, alpha=0.7, label=f'Buy & Hold ({results.buy_hold_return_pct:.1f}%)')
        ax2.axhline(y=self.config.INITIAL_CAPITAL, color='gray', linestyle='--', alpha=0.5, label='Initial Capital')
        ax2.set_title('Equity Curve vs Buy & Hold', fontsize=11, fontweight='bold')
        ax2.set_ylabel('Capital (USDT)')
        ax2.legend(loc='upper left', fontsize=9)
        ax2.grid(True, alpha=0.3)
        if use_dates:
            ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            ax2.xaxis.set_major_locator(mdates.AutoDateLocator())
            plt.setp(ax2.xaxis.get_majorticklabels(), rotation=30, ha='right', fontsize=8)

        # ---- Panel 3: Drawdown ----
        ax3 = fig.add_subplot(gs[2])
        cummax = np.maximum.accumulate(cap_hist)
        drawdown = (cap_hist - cummax) / (cummax + 1e-10) * 100
        dd_x = x_axis[:len(drawdown)] if len(x_axis) >= len(drawdown) else np.arange(len(drawdown))
        ax3.fill_between(dd_x, drawdown, 0, color=COLORS['drawdown'], alpha=0.4)
        ax3.plot(dd_x, drawdown, color=COLORS['drawdown'], linewidth=0.8)
        ax3.set_title(f'Drawdown (Max: {results.max_drawdown:.1f}%)', fontsize=11, fontweight='bold')
        ax3.set_ylabel('Drawdown %')
        ax3.grid(True, alpha=0.3)
        if use_dates:
            ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            ax3.xaxis.set_major_locator(mdates.AutoDateLocator())
            plt.setp(ax3.xaxis.get_majorticklabels(), rotation=30, ha='right', fontsize=8)

        # ---- Panel 4: Trade P&L Distribution ----
        ax4 = fig.add_subplot(gs[3])
        if trades:
            pnl_pcts = [t['pnl_pct'] for t in trades]
            colors_bar = [COLORS['buy'] if p > 0 else COLORS['sell'] for p in pnl_pcts]
            ax4.bar(range(len(pnl_pcts)), pnl_pcts, color=colors_bar, alpha=0.7, width=0.8)
            ax4.axhline(y=0, color='black', linewidth=0.5)
            ax4.set_title(f'Individual Trade P&L | Win Rate: {results.win_rate:.1f}% | '
                          f'Avg Win: {results.avg_win:.2f}% | Avg Loss: {results.avg_loss:.2f}%',
                          fontsize=11, fontweight='bold')
            ax4.set_ylabel('P&L %')
            ax4.set_xlabel('Trade #')
        else:
            ax4.text(0.5, 0.5, 'No trades executed', ha='center', va='center', fontsize=14)
            ax4.set_title('Trade P&L Distribution', fontsize=11, fontweight='bold')

        ax4.grid(True, alpha=0.3)

        plt.tight_layout()

        if save:
            filepath = os.path.join(self.output_dir, f"{results.symbol}_{results.model_type}_backtest.png")
            fig.savefig(filepath, dpi=150, bbox_inches='tight')
            plt.close(fig)
            logger.info(f"Backtest summary saved: {filepath}")
            return filepath
        else:
            plt.show()
            return ""

    def plot_model_comparison(self, all_results: List, symbol: str, save: bool = True) -> str:
        """
        Compare multiple models for one symbol.
        Shows bar charts of key metrics for each model.

        Args:
            all_results: List of BacktestResults (one per model)
            symbol: Trading symbol
            save: Whether to save

        Returns:
            Path to saved figure
        """
        if not all_results:
            logger.warning("No results to compare")
            return ""

        fig, axes = plt.subplots(2, 3, figsize=(18, 10))
        fig.suptitle(f'{symbol} - Model Comparison', fontsize=16, fontweight='bold')

        model_names = [r.model_type for r in all_results]
        colors = plt.cm.Set2(np.linspace(0, 1, len(model_names)))

        # Metrics to plot
        metrics = [
            ('Total Return %', [r.total_return_pct for r in all_results]),
            ('Sharpe Ratio', [r.sharpe_ratio for r in all_results]),
            ('Win Rate %', [r.win_rate for r in all_results]),
            ('Max Drawdown %', [r.max_drawdown for r in all_results]),
            ('Profit Factor', [r.profit_factor for r in all_results]),
            ('Num Trades', [r.num_trades for r in all_results]),
        ]

        for idx, (title, values) in enumerate(metrics):
            ax = axes[idx // 3][idx % 3]
            bars = ax.bar(model_names, values, color=colors, edgecolor='black', linewidth=0.5)
            ax.set_title(title, fontsize=12, fontweight='bold')
            ax.set_ylabel(title)

            # Add value labels on bars
            for bar, val in zip(bars, values):
                ax.text(bar.get_x() + bar.get_width() / 2., bar.get_height(),
                       f'{val:.2f}', ha='center', va='bottom', fontsize=9)

            ax.tick_params(axis='x', rotation=30)
            ax.grid(True, alpha=0.3, axis='y')

        plt.tight_layout()

        if save:
            filepath = os.path.join(self.output_dir, f"{symbol}_model_comparison.png")
            fig.savefig(filepath, dpi=150, bbox_inches='tight')
            plt.close(fig)
            logger.info(f"Model comparison saved: {filepath}")
            return filepath
        else:
            plt.show()
            return ""

    def plot_equity_comparison(self, all_results: List, symbol: str, save: bool = True) -> str:
        """
        Overlay equity curves of all models for one symbol.

        Args:
            all_results: List of BacktestResults
            symbol: Trading symbol
            save: Whether to save

        Returns:
            Path to saved figure
        """
        if not all_results:
            return ""

        fig, ax = plt.subplots(figsize=(16, 8))
        colors = plt.cm.tab10(np.linspace(0, 1, len(all_results) + 1))

        # Determine date axis from first result
        use_dates = False
        x_axis = None
        if hasattr(all_results[0], 'dates') and len(all_results[0].dates) > 0 and not isinstance(all_results[0].dates[0], int):
            x_axis = pd.DatetimeIndex(all_results[0].dates)
            use_dates = True

        for i, r in enumerate(all_results):
            cap = np.array(r.capital_history)
            if use_dates:
                x = x_axis[:len(cap)] if len(x_axis) >= len(cap) else np.arange(len(cap))
            else:
                x = np.arange(len(cap))
            ax.plot(x, cap, color=colors[i], linewidth=1.2,
                    label=f'{r.model_type} ({r.total_return_pct:.1f}%)')

        # Buy & Hold
        if all_results[0].buy_hold_history:
            bh = np.array(all_results[0].buy_hold_history)
            if use_dates:
                x_bh = x_axis[:len(bh)] if len(x_axis) >= len(bh) else np.arange(len(bh))
            else:
                x_bh = np.arange(len(bh))
            ax.plot(x_bh, bh, color='black', linewidth=1.5, linestyle='--',
                    label=f'Buy & Hold ({all_results[0].buy_hold_return_pct:.1f}%)')

        ax.axhline(y=self.config.INITIAL_CAPITAL, color='gray', linestyle=':', alpha=0.5)
        # Date range for title
        if use_dates:
            date_str = f" | {str(x_axis[0])[:10]} to {str(x_axis[-1])[:10]}"
        else:
            date_str = ""
        ax.set_title(f'{symbol} - Equity Curves Comparison (All Models){date_str}', fontsize=14, fontweight='bold')
        ax.set_xlabel('Date' if use_dates else 'Candle Index')
        ax.set_ylabel('Capital (USDT)')
        ax.legend(loc='upper left', fontsize=10)
        ax.grid(True, alpha=0.3)
        if use_dates:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha='right', fontsize=8)

        plt.tight_layout()

        if save:
            filepath = os.path.join(self.output_dir, f"{symbol}_equity_comparison.png")
            fig.savefig(filepath, dpi=150, bbox_inches='tight')
            plt.close(fig)
            logger.info(f"Equity comparison saved: {filepath}")
            return filepath
        else:
            plt.show()
            return ""

    def plot_portfolio_summary(self, all_results_by_symbol: Dict[str, List], save: bool = True) -> str:
        """
        Create a portfolio-level summary across all symbols and models.

        Args:
            all_results_by_symbol: Dict of {symbol: [BacktestResults per model]}
            save: Whether to save

        Returns:
            Path to saved figure
        """
        # Find best model per symbol
        best_results = {}
        for symbol, results_list in all_results_by_symbol.items():
            if results_list:
                best = max(results_list, key=lambda r: r.total_return_pct)
                best_results[symbol] = best

        if not best_results:
            return ""

        fig, axes = plt.subplots(1, 3, figsize=(18, 6))
        fig.suptitle('Portfolio Summary - Best Model per Symbol', fontsize=14, fontweight='bold')

        symbols = list(best_results.keys())
        returns = [best_results[s].total_return_pct for s in symbols]
        sharpes = [best_results[s].sharpe_ratio for s in symbols]
        models = [best_results[s].model_type for s in symbols]

        # Returns
        colors = [COLORS['buy'] if r > 0 else COLORS['sell'] for r in returns]
        bars = axes[0].bar(symbols, returns, color=colors, edgecolor='black', linewidth=0.5)
        for bar, val, model in zip(bars, returns, models):
            axes[0].text(bar.get_x() + bar.get_width() / 2., bar.get_height(),
                        f'{val:.1f}%\n({model})', ha='center', va='bottom', fontsize=8)
        axes[0].set_title('Return % (Best Model)', fontweight='bold')
        axes[0].axhline(y=0, color='black', linewidth=0.5)
        axes[0].grid(True, alpha=0.3, axis='y')

        # Sharpe
        bars = axes[1].bar(symbols, sharpes, color='steelblue', edgecolor='black', linewidth=0.5)
        for bar, val in zip(bars, sharpes):
            axes[1].text(bar.get_x() + bar.get_width() / 2., bar.get_height(),
                        f'{val:.2f}', ha='center', va='bottom', fontsize=9)
        axes[1].set_title('Sharpe Ratio (Best Model)', fontweight='bold')
        axes[1].axhline(y=0, color='black', linewidth=0.5)
        axes[1].grid(True, alpha=0.3, axis='y')

        # Win Rate
        win_rates = [best_results[s].win_rate for s in symbols]
        bars = axes[2].bar(symbols, win_rates, color='teal', edgecolor='black', linewidth=0.5)
        for bar, val in zip(bars, win_rates):
            axes[2].text(bar.get_x() + bar.get_width() / 2., bar.get_height(),
                        f'{val:.1f}%', ha='center', va='bottom', fontsize=9)
        axes[2].set_title('Win Rate % (Best Model)', fontweight='bold')
        axes[2].axhline(y=50, color='gray', linestyle='--', alpha=0.5)
        axes[2].grid(True, alpha=0.3, axis='y')

        plt.tight_layout()

        if save:
            filepath = os.path.join(self.output_dir, "portfolio_summary.png")
            fig.savefig(filepath, dpi=150, bbox_inches='tight')
            plt.close(fig)
            logger.info(f"Portfolio summary saved: {filepath}")
            return filepath
        else:
            plt.show()
            return ""

    def create_results_table(self, all_results: List) -> pd.DataFrame:
        """
        Create a comprehensive results table for all models and symbols.

        Args:
            all_results: List of BacktestResults

        Returns:
            DataFrame with all results
        """
        rows = []
        for r in all_results:
            rows.append({
                'Symbol': r.symbol,
                'Model': r.model_type,
                'Return %': round(r.total_return_pct, 2),
                'B&H Return %': round(r.buy_hold_return_pct, 2),
                'Outperformance %': round(r.outperformance_pct, 2),
                'Sharpe': round(r.sharpe_ratio, 2),
                'Calmar': round(r.calmar_ratio, 2),
                'Max DD %': round(r.max_drawdown, 2),
                'Win Rate %': round(r.win_rate, 1),
                'Profit Factor': round(r.profit_factor, 2),
                'Trades': r.num_trades,
                'Avg Trade %': round(r.avg_trade_return, 2),
                'Avg Win %': round(r.avg_win, 2),
                'Avg Loss %': round(r.avg_loss, 2),
            })

        df = pd.DataFrame(rows)
        return df
