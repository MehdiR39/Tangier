"""
Portfolio Analysis Module
Aggregates and analyzes results across multiple coins and models.
"""

import pandas as pd
import numpy as np
import logging
import os
from typing import Dict, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PortfolioMetrics:
    """Portfolio-level metrics."""
    symbols: List[str]
    total_return_pct: float
    portfolio_sharpe: float
    portfolio_calmar: float
    avg_win_rate: float
    avg_profit_factor: float
    max_drawdown: float
    correlation_matrix: pd.DataFrame
    individual_results: Dict


class PortfolioAnalyzer:
    """Analyzes portfolio performance across multiple coins."""

    def __init__(self, config):
        self.config = config
        logger.info("PortfolioAnalyzer initialized")

    def aggregate_results(self, results_dict: Dict) -> PortfolioMetrics:
        """
        Aggregate backtest results from multiple coins.

        Args:
            results_dict: Dictionary of {symbol: BacktestResults}

        Returns:
            PortfolioMetrics object
        """
        if not results_dict:
            return PortfolioMetrics(
                symbols=[], total_return_pct=0, portfolio_sharpe=0,
                portfolio_calmar=0, avg_win_rate=0, avg_profit_factor=0,
                max_drawdown=0, correlation_matrix=pd.DataFrame(),
                individual_results={}
            )

        symbols = list(results_dict.keys())
        returns = []
        sharpes = []
        calmars = []
        win_rates = []
        profit_factors = []
        drawdowns = []

        for s in symbols:
            r = results_dict[s]
            returns.append(r.total_return_pct / 100)
            sharpes.append(r.sharpe_ratio if not np.isnan(r.sharpe_ratio) else 0)
            calmars.append(r.calmar_ratio if not np.isnan(r.calmar_ratio) else 0)
            win_rates.append(r.win_rate if not np.isnan(r.win_rate) else 0)
            profit_factors.append(r.profit_factor if not np.isnan(r.profit_factor) else 0)
            drawdowns.append(r.max_drawdown if not np.isnan(r.max_drawdown) else 0)

        correlation_matrix = self._compute_correlation_matrix(results_dict, symbols)

        return PortfolioMetrics(
            symbols=symbols,
            total_return_pct=np.mean(returns) * 100 if returns else 0,
            portfolio_sharpe=np.mean(sharpes) if sharpes else 0,
            portfolio_calmar=np.mean(calmars) if calmars else 0,
            avg_win_rate=np.mean(win_rates) if win_rates else 0,
            avg_profit_factor=np.mean(profit_factors) if profit_factors else 0,
            max_drawdown=np.mean(drawdowns) if drawdowns else 0,
            correlation_matrix=correlation_matrix,
            individual_results=results_dict
        )

    def _compute_correlation_matrix(self, results_dict, symbols):
        """Compute correlation matrix from capital histories."""
        try:
            capital_histories = {}
            for s in symbols:
                ch = results_dict[s].capital_history
                if ch and len(ch) > 1:
                    capital_histories[s] = ch

            if len(capital_histories) < 2:
                return pd.DataFrame()

            min_len = min(len(v) for v in capital_histories.values())
            returns_data = {}
            for s, ch in capital_histories.items():
                arr = np.array(ch[:min_len])
                returns_data[s] = np.diff(arr) / (arr[:-1] + 1e-10)

            return pd.DataFrame(returns_data).corr()
        except Exception as e:
            logger.warning(f"Could not compute correlation: {str(e)}")
            return pd.DataFrame()

    def print_portfolio_summary(self, metrics: PortfolioMetrics):
        """Print portfolio summary."""
        print("\n" + "=" * 100)
        print("PORTFOLIO SUMMARY")
        print("=" * 100)
        print(f"Coins: {', '.join(metrics.symbols)}")
        print(f"  Total Return:      {metrics.total_return_pct:>8.2f}%")
        print(f"  Sharpe Ratio:      {metrics.portfolio_sharpe:>8.2f}")
        print(f"  Calmar Ratio:      {metrics.portfolio_calmar:>8.2f}")
        print(f"  Avg Win Rate:      {metrics.avg_win_rate:>7.1f}%")
        print(f"  Avg Profit Factor: {metrics.avg_profit_factor:>8.2f}")
        print(f"  Max Drawdown:      {metrics.max_drawdown:>8.2f}%")

        for symbol in metrics.symbols:
            if symbol in metrics.individual_results:
                r = metrics.individual_results[symbol]
                print(f"\n  {symbol}: Return={r.total_return_pct:.2f}%, "
                      f"Sharpe={r.sharpe_ratio:.2f}, WinRate={r.win_rate:.1f}%")

        if not metrics.correlation_matrix.empty:
            print(f"\nCorrelation Matrix:")
            print(metrics.correlation_matrix.round(3))
        print("=" * 100)

    def save_results(self, metrics: PortfolioMetrics, output_dir: str = None):
        """Save portfolio results to CSV."""
        if output_dir is None:
            output_dir = self.config.RESULTS_DIR

        rows = []
        for symbol in metrics.symbols:
            if symbol in metrics.individual_results:
                r = metrics.individual_results[symbol]
                rows.append({
                    'Symbol': symbol,
                    'Return %': r.total_return_pct,
                    'Sharpe': r.sharpe_ratio,
                    'Win Rate %': r.win_rate,
                    'Max DD %': r.max_drawdown,
                    'Profit Factor': r.profit_factor,
                    'Trades': r.num_trades
                })

        if rows:
            df = pd.DataFrame(rows)
            path = os.path.join(output_dir, 'portfolio_results.csv')
            df.to_csv(path, index=False)
            logger.info(f"Portfolio results saved to {path}")

        if not metrics.correlation_matrix.empty:
            corr_path = os.path.join(output_dir, 'correlation_matrix.csv')
            metrics.correlation_matrix.to_csv(corr_path)
            logger.info(f"Correlation matrix saved to {corr_path}")
