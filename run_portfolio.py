"""
Portfolio Multi-Crypto Script
Selects the best model per crypto, allocates capital, and simulates a diversified portfolio.

Usage:
    python run_portfolio.py
    python run_portfolio.py --allocation risk_parity
    python run_portfolio.py --symbols BTCUSDT,ETHUSDT,SOLUSDT,AVAXUSDT,XRPUSDT
"""

import sys
import os
import logging
from datetime import datetime

# Add paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'config'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import config as config
from data_manager import DataManager
from feature_engineer import FeatureEngineer
from model_trainer import ModelTrainer
from backtester import RobustBacktester
from visualizer import Visualizer

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

# ============================================================================
# LOGGING SETUP
# ============================================================================

log_filename = os.path.join(config.LOGS_DIR, f"portfolio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Models to test
MODEL_TYPES = ['lgbm', 'xgboost', 'random_forest', 'logistic_regression', 'neural_network']


# ============================================================================
# STEP 1: FIND BEST MODEL PER CRYPTO
# ============================================================================

def find_best_models(symbols: list) -> dict:
    """
    Run all 5 models on each crypto and return the best model per crypto.

    If a model_comparison_results.csv already exists, it reads from there.
    Otherwise, it runs the full comparison.

    Returns:
        Dict of {symbol: {'model_type': str, 'results': BacktestResults}}
    """
    csv_path = os.path.join(config.RESULTS_DIR, 'model_comparison_results.csv')

    # Check if comparison results already exist
    if os.path.exists(csv_path):
        logger.info(f"Found existing comparison results: {csv_path}")
        df = pd.read_csv(csv_path)

        # Check if all requested symbols are in the CSV
        existing_symbols = set(df['Symbol'].unique())
        requested_symbols = set(symbols)

        if requested_symbols.issubset(existing_symbols):
            logger.info("All symbols found in existing results. Using cached data.")
            best_models = {}
            for symbol in symbols:
                sym_df = df[df['Symbol'] == symbol]
                if 'Win Rate %' in sym_df.columns:
                    sym_df = sym_df.copy()
                    sym_df['Win Rate %'] = sym_df['Win Rate %'].where(sym_df['Win Rate %'] <= 100, sym_df['Win Rate %'] / 100)
                best_row = sym_df.loc[sym_df['Sharpe'].idxmax()]
                best_models[symbol] = {
                    'model_type': best_row['Model'],
                    'return': best_row['Return %'],
                    'sharpe': best_row['Sharpe'],
                    'win_rate': best_row['Win Rate %'],
                    'max_dd': best_row['Max DD %'],
                    'trades': best_row['Trades'],
                }
            return best_models
        else:
            missing = requested_symbols - existing_symbols
            logger.info(f"Missing symbols in CSV: {missing}. Running full comparison.")

    # Run full comparison for all symbols
    logger.info("Running model comparison for all symbols...")
    best_models = {}
    all_results_rows = []

    for symbol in symbols:
        logger.info(f"\n{'='*60}")
        logger.info(f"TESTING ALL MODELS FOR: {symbol}")
        logger.info(f"{'='*60}")

        data_manager = DataManager(config)
        feature_engineer = FeatureEngineer(config)
        backtester = RobustBacktester(config)

        # Fetch and prepare data
        data = data_manager.fetch_data(symbol, config.BINANCE_INTERVAL, config.BINANCE_START_TIME)
        if data is None:
            logger.error(f"Failed to fetch data for {symbol}, skipping")
            continue
        data = data_manager.prepare_data(data, symbol)
        data = feature_engineer.engineer_features(data, symbol)

        # Prepare training data (shared)
        base_trainer = ModelTrainer(config)
        X, y, selected_features = base_trainer.prepare_data(data, symbol)

        # Train/test split
        test_start = getattr(config, 'TEST_START_DATE', None)
        if test_start and isinstance(X.index, pd.DatetimeIndex):
            test_start_ts = pd.Timestamp(test_start)
            X_train = X[X.index < test_start_ts]
            X_test = X[X.index >= test_start_ts]
            y_train = y[y.index < test_start_ts]
            y_test = y[y.index >= test_start_ts]
        else:
            split_idx = int(len(X) * (1 - config.TEST_SIZE))
            X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
            y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

        if len(X_train) == 0 or len(X_test) == 0:
            logger.error(f"Invalid split for {symbol}: empty train or test set")
            continue

        test_data = data.loc[X_test.index]

        best_sharpe = -np.inf
        best_model_info = None

        for model_type in MODEL_TYPES:
            try:
                trainer = ModelTrainer(config)
                trainer.feature_selector.selected_features = selected_features
                trainer.train(X_train, y_train, symbol, model_type=model_type)
                signals = trainer.predict_signals(X_test)
                result = backtester.backtest(test_data, signals, symbol, model_type=model_type)

                all_results_rows.append({
                    'Symbol': symbol, 'Model': model_type,
                    'Return %': round(result.total_return_pct, 2),
                    'B&H Return %': round(result.buy_hold_return_pct, 2),
                    'Outperformance %': round(result.outperformance_pct, 2),
                    'Sharpe': round(result.sharpe_ratio, 2),
                    'Max DD %': round(result.max_drawdown, 2),
                    'Win Rate %': round(result.win_rate, 1),
                    'Profit Factor': round(result.profit_factor, 2),
                    'Trades': result.num_trades,
                    'Avg Trade %': round(result.avg_trade_return, 2),
                    'Avg Win %': round(result.avg_win, 2),
                    'Avg Loss %': round(result.avg_loss, 2),
                })

                if result.sharpe_ratio > best_sharpe:
                    best_sharpe = result.sharpe_ratio
                    best_model_info = {
                        'model_type': model_type,
                        'return': result.total_return_pct,
                        'sharpe': result.sharpe_ratio,
                        'win_rate': result.win_rate,
                        'max_dd': result.max_drawdown,
                        'trades': result.num_trades,
                    }

                logger.info(f"  {model_type}: Return={result.total_return_pct:.2f}%, Sharpe={result.sharpe_ratio:.2f}")

            except Exception as e:
                logger.error(f"  {model_type} failed: {str(e)}")
                continue

        if best_model_info:
            best_models[symbol] = best_model_info
            logger.info(f"  >> BEST: {best_model_info['model_type'].upper()} (Sharpe={best_sharpe:.2f})")

    # Save comparison results
    if all_results_rows:
        df = pd.DataFrame(all_results_rows)
        df.to_csv(csv_path, index=False)
        logger.info(f"Comparison results saved to {csv_path}")

    return best_models


# ============================================================================
# STEP 2: ALLOCATE CAPITAL
# ============================================================================

def allocate_capital(best_models: dict, method: str = 'equal',
                     total_capital: float = None) -> dict:
    """
    Allocate capital across cryptos.

    Args:
        best_models: Dict from find_best_models()
        method: 'equal', 'risk_parity', or 'performance_weighted'
        total_capital: Total capital (default from config)

    Returns:
        Dict of {symbol: allocated_capital}
    """
    if total_capital is None:
        total_capital = config.INITIAL_CAPITAL

    symbols = list(best_models.keys())
    n = len(symbols)

    if n == 0:
        return {}

    if method == 'equal':
        weight = 1.0 / n
        allocation = {s: total_capital * weight for s in symbols}

    elif method == 'risk_parity':
        # Inverse of max drawdown (lower DD = more capital)
        drawdowns = {s: max(best_models[s]['max_dd'], 1.0) for s in symbols}
        inv_dd = {s: 1.0 / drawdowns[s] for s in symbols}
        total_inv = sum(inv_dd.values())
        allocation = {s: total_capital * (inv_dd[s] / total_inv) for s in symbols}

    elif method == 'performance_weighted':
        # Weight by Sharpe ratio (only positive Sharpe, minimum weight for negative)
        sharpes = {}
        for s in symbols:
            sh = best_models[s]['sharpe']
            sharpes[s] = max(sh, 0.1)  # Minimum weight
        total_sh = sum(sharpes.values())
        allocation = {s: total_capital * (sharpes[s] / total_sh) for s in symbols}

    else:
        logger.warning(f"Unknown allocation method '{method}', using equal")
        weight = 1.0 / n
        allocation = {s: total_capital * weight for s in symbols}

    logger.info(f"\nCapital Allocation ({method}):")
    for s, cap in allocation.items():
        pct = cap / total_capital * 100
        logger.info(f"  {s}: {cap:.4f} ({pct:.1f}%) - Model: {best_models[s]['model_type']}")

    return allocation


# ============================================================================
# STEP 3: RUN PORTFOLIO BACKTEST
# ============================================================================

def run_portfolio_backtest(symbols: list, best_models: dict,
                           allocation: dict) -> dict:
    """
    Run individual backtests for each crypto with its best model,
    then aggregate into a portfolio equity curve.

    Returns:
        Dict with portfolio results and individual results
    """
    individual_results = {}

    for symbol in symbols:
        if symbol not in best_models:
            continue

        model_type = best_models[symbol]['model_type']
        capital = allocation[symbol]

        logger.info(f"\n--- {symbol} with {model_type.upper()} (capital: {capital:.4f}) ---")

        try:
            data_manager = DataManager(config)
            feature_engineer = FeatureEngineer(config)
            backtester = RobustBacktester(config)
            # Override initial capital for this crypto's allocation
            backtester.initial_capital = capital

            # Full pipeline
            data = data_manager.fetch_data(symbol, config.BINANCE_INTERVAL, config.BINANCE_START_TIME)
            data = data_manager.prepare_data(data, symbol)
            data = feature_engineer.engineer_features(data, symbol)

            trainer = ModelTrainer(config)
            X, y, selected_features = trainer.prepare_data(data, symbol)

            test_start = getattr(config, 'TEST_START_DATE', None)
            if test_start and isinstance(X.index, pd.DatetimeIndex):
                test_start_ts = pd.Timestamp(test_start)
                X_train = X[X.index < test_start_ts]
                X_test = X[X.index >= test_start_ts]
                y_train = y[y.index < test_start_ts]
            else:
                split_idx = int(len(X) * (1 - config.TEST_SIZE))
                X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
                y_train = y.iloc[:split_idx]
            test_data = data.loc[X_test.index]

            trainer.train(X_train, y_train, symbol, model_type=model_type)
            signals = trainer.predict_signals(X_test)
            result = backtester.backtest(test_data, signals, symbol, model_type=model_type)

            individual_results[symbol] = result
            logger.info(f"  Return: {result.total_return_pct:.2f}%, Sharpe: {result.sharpe_ratio:.2f}")

        except Exception as e:
            logger.error(f"  Error: {str(e)}", exc_info=True)
            continue

    # Aggregate portfolio equity curve
    portfolio = aggregate_portfolio(individual_results, allocation)

    return {
        'individual': individual_results,
        'portfolio': portfolio,
        'allocation': allocation,
        'best_models': best_models,
    }


def aggregate_portfolio(individual_results: dict, allocation: dict) -> dict:
    """
    Aggregate individual equity curves into a portfolio curve.
    """
    if not individual_results:
        return {}

    # Find the common length (shortest equity curve)
    min_len = min(len(r.capital_history) for r in individual_results.values())

    # Sum equity curves
    portfolio_curve = np.zeros(min_len)
    buyhold_curve = np.zeros(min_len)

    # Get dates from first result that has them
    dates = []
    for symbol, result in individual_results.items():
        cap_hist = np.array(result.capital_history[:min_len])
        bh_hist = np.array(result.buy_hold_history[:min_len])
        portfolio_curve += cap_hist
        buyhold_curve += bh_hist
        if not dates and hasattr(result, 'dates') and len(result.dates) > 0:
            dates = result.dates[:min_len]

    total_capital = sum(allocation.values())
    total_return = (portfolio_curve[-1] - total_capital) / total_capital * 100
    bh_return = (buyhold_curve[-1] - total_capital) / total_capital * 100

    # Portfolio metrics
    cummax = np.maximum.accumulate(portfolio_curve)
    drawdown = (portfolio_curve - cummax) / (cummax + 1e-10)
    max_dd = abs(np.min(drawdown)) * 100

    # Sharpe
    if len(portfolio_curve) > 1:
        returns = np.diff(portfolio_curve) / (portfolio_curve[:-1] + 1e-10)
        annual_periods = getattr(config, 'ANNUAL_PERIODS', 252)
        sharpe = np.mean(returns) / (np.std(returns) + 1e-10) * np.sqrt(annual_periods)
    else:
        sharpe = 0

    return {
        'equity_curve': portfolio_curve.tolist(),
        'buyhold_curve': buyhold_curve.tolist(),
        'total_return': total_return,
        'buyhold_return': bh_return,
        'outperformance': total_return - bh_return,
        'max_drawdown': max_dd,
        'sharpe': sharpe,
        'total_capital': total_capital,
        'dates': dates,
    }


# ============================================================================
# STEP 4: VISUALIZE PORTFOLIO
# ============================================================================

def plot_portfolio(results: dict, allocation_method: str, save: bool = True) -> str:
    """
    Create a comprehensive portfolio visualization:
    1. Portfolio equity curve vs Buy & Hold
    2. Individual crypto equity curves
    3. Capital allocation pie chart
    4. Performance summary table
    """
    portfolio = results['portfolio']
    individual = results['individual']
    best_models = results['best_models']
    allocation = results['allocation']

    fig = plt.figure(figsize=(22, 18))
    gs = gridspec.GridSpec(3, 2, height_ratios=[2, 2, 1.5], hspace=0.35, wspace=0.3)

    total_capital = portfolio['total_capital']

    # ---- Panel 1: Portfolio Equity Curve (top left, spanning full width) ----
    ax1 = fig.add_subplot(gs[0, :])
    eq = np.array(portfolio['equity_curve'])
    bh = np.array(portfolio['buyhold_curve'])

    # Use dates if available
    import matplotlib.dates as mdates
    dates = portfolio.get('dates', [])
    use_dates = len(dates) > 0 and not isinstance(dates[0], int)
    if use_dates:
        x_axis = pd.DatetimeIndex(dates[:len(eq)])
    else:
        x_axis = np.arange(len(eq))

    ax1.plot(x_axis, eq, color='#2980b9', linewidth=2, label=f"Portfolio ({portfolio['total_return']:.1f}%)")
    ax1.plot(x_axis[:len(bh)], bh, color='#e67e22', linewidth=1.5, linestyle='--',
             label=f"Buy & Hold All ({portfolio['buyhold_return']:.1f}%)")
    ax1.axhline(y=total_capital, color='gray', linestyle=':', alpha=0.5, label='Initial Capital')

    # Fill between to show outperformance
    ax1.fill_between(x_axis, eq, bh[:len(eq)], where=(eq > bh[:len(eq)]), color='#2ecc71', alpha=0.15, label='Outperformance')
    ax1.fill_between(x_axis, eq, bh[:len(eq)], where=(eq < bh[:len(eq)]), color='#e74c3c', alpha=0.15, label='Underperformance')

    # Date range for title
    if use_dates:
        date_range_str = f" | {str(x_axis[0])[:10]} to {str(x_axis[-1])[:10]}"
    else:
        date_range_str = ""

    ax1.set_title(f"PORTFOLIO MULTI-CRYPTO | Return: {portfolio['total_return']:.1f}% vs B&H: {portfolio['buyhold_return']:.1f}% | "
                  f"Sharpe: {portfolio['sharpe']:.2f} | Max DD: {portfolio['max_drawdown']:.1f}% | "
                  f"Allocation: {allocation_method.upper()}{date_range_str}",
                  fontsize=14, fontweight='bold')
    ax1.set_ylabel('Capital (USDT)')
    ax1.set_xlabel('Date' if use_dates else 'Candle Index')
    ax1.legend(loc='upper left', fontsize=10)
    ax1.grid(True, alpha=0.3)
    if use_dates:
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        ax1.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.setp(ax1.xaxis.get_majorticklabels(), rotation=30, ha='right', fontsize=8)

    # ---- Panel 2: Individual Equity Curves (middle left) ----
    ax2 = fig.add_subplot(gs[1, 0])
    colors = plt.cm.Set1(np.linspace(0, 1, len(individual)))

    for i, (symbol, result) in enumerate(individual.items()):
        cap = np.array(result.capital_history)
        model = best_models[symbol]['model_type']
        if use_dates:
            x_ind = x_axis[:len(cap)] if len(x_axis) >= len(cap) else np.arange(len(cap))
        else:
            x_ind = np.arange(len(cap))
        ax2.plot(x_ind, cap, color=colors[i], linewidth=1.2,
                 label=f"{symbol} [{model}] ({result.total_return_pct:.1f}%)")

    ax2.axhline(y=total_capital / len(individual), color='gray', linestyle=':', alpha=0.5)
    ax2.set_title('Individual Crypto Performance (Best Model Each)', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Capital (USDT)')
    ax2.set_xlabel('Date' if use_dates else 'Candle Index')
    ax2.legend(loc='best', fontsize=8)
    ax2.grid(True, alpha=0.3)
    if use_dates:
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        ax2.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.setp(ax2.xaxis.get_majorticklabels(), rotation=30, ha='right', fontsize=8)

    # ---- Panel 3: Drawdown (middle right) ----
    ax3 = fig.add_subplot(gs[1, 1])
    cummax = np.maximum.accumulate(eq)
    dd = (eq - cummax) / (cummax + 1e-10) * 100
    dd_x = x_axis[:len(dd)] if use_dates and len(x_axis) >= len(dd) else range(len(dd))
    ax3.fill_between(dd_x, dd, 0, color='#c0392b', alpha=0.4)
    ax3.plot(dd_x, dd, color='#c0392b', linewidth=0.8)
    ax3.set_title(f"Portfolio Drawdown (Max: {portfolio['max_drawdown']:.1f}%)",
                  fontsize=12, fontweight='bold')
    ax3.set_ylabel('Drawdown %')
    ax3.set_xlabel('Date' if use_dates else 'Candle Index')
    ax3.grid(True, alpha=0.3)
    if use_dates:
        ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        ax3.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.setp(ax3.xaxis.get_majorticklabels(), rotation=30, ha='right', fontsize=8)

    # ---- Panel 4: Allocation Pie Chart (bottom left) ----
    ax4 = fig.add_subplot(gs[2, 0])
    labels = []
    sizes = []
    pie_colors = plt.cm.Set2(np.linspace(0, 1, len(allocation)))

    for symbol, cap in allocation.items():
        pct = cap / total_capital * 100
        model = best_models[symbol]['model_type']
        labels.append(f"{symbol}\n{model}\n({pct:.1f}%)")
        sizes.append(cap)

    wedges, texts, autotexts = ax4.pie(sizes, labels=labels, colors=pie_colors,
                                        autopct='', startangle=90, textprops={'fontsize': 9})
    ax4.set_title(f'Capital Allocation ({allocation_method.upper()})', fontsize=12, fontweight='bold')

    # ---- Panel 5: Performance Summary Table (bottom right) ----
    ax5 = fig.add_subplot(gs[2, 1])
    ax5.axis('off')

    table_data = [['Crypto', 'Model', 'Return %', 'Sharpe', 'Win Rate', 'Trades', 'Max DD %']]
    for symbol, result in individual.items():
        model = best_models[symbol]['model_type']
        table_data.append([
            symbol, model,
            f"{result.total_return_pct:.1f}%",
            f"{result.sharpe_ratio:.2f}",
            f"{result.win_rate:.1f}%",
            str(result.num_trades),
            f"{result.max_drawdown:.1f}%"
        ])

    # Add portfolio total row
    table_data.append([
        'PORTFOLIO', allocation_method,
        f"{portfolio['total_return']:.1f}%",
        f"{portfolio['sharpe']:.2f}",
        '-',
        '-',
        f"{portfolio['max_drawdown']:.1f}%"
    ])

    table = ax5.table(cellText=table_data, loc='center', cellLoc='center')
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.5)

    # Style header row
    for j in range(len(table_data[0])):
        table[0, j].set_facecolor('#2c3e50')
        table[0, j].set_text_props(color='white', fontweight='bold')

    # Style portfolio total row
    last_row = len(table_data) - 1
    for j in range(len(table_data[0])):
        table[last_row, j].set_facecolor('#ecf0f1')
        table[last_row, j].set_text_props(fontweight='bold')

    ax5.set_title('Performance Summary', fontsize=12, fontweight='bold', pad=20)

    plt.tight_layout()

    if save:
        filepath = os.path.join(config.RESULTS_DIR, f"portfolio_{allocation_method}.png")
        fig.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close(fig)
        logger.info(f"Portfolio chart saved: {filepath}")
        return filepath
    else:
        plt.show()
        return ""


# ============================================================================
# STEP 5: EXPORT RESULTS
# ============================================================================

def export_portfolio_results(results: dict, allocation_method: str):
    """Export portfolio results to CSV."""
    portfolio = results['portfolio']
    individual = results['individual']
    best_models = results['best_models']
    allocation = results['allocation']

    rows = []
    for symbol, result in individual.items():
        model = best_models[symbol]['model_type']
        rows.append({
            'Symbol': symbol,
            'Best Model': model,
            'Allocated Capital': round(allocation[symbol], 4),
            'Allocation %': round(allocation[symbol] / portfolio['total_capital'] * 100, 1),
            'Return %': round(result.total_return_pct, 2),
            'B&H Return %': round(result.buy_hold_return_pct, 2),
            'Outperformance %': round(result.outperformance_pct, 2),
            'Sharpe': round(result.sharpe_ratio, 2),
            'Max DD %': round(result.max_drawdown, 2),
            'Win Rate %': round(result.win_rate, 1),
            'Trades': result.num_trades,
        })

    # Add portfolio total
    rows.append({
        'Symbol': 'PORTFOLIO',
        'Best Model': allocation_method,
        'Allocated Capital': round(portfolio['total_capital'], 4),
        'Allocation %': 100.0,
        'Return %': round(portfolio['total_return'], 2),
        'B&H Return %': round(portfolio['buyhold_return'], 2),
        'Outperformance %': round(portfolio['outperformance'], 2),
        'Sharpe': round(portfolio['sharpe'], 2),
        'Max DD %': round(portfolio['max_drawdown'], 2),
        'Win Rate %': '-',
        'Trades': '-',
    })

    df = pd.DataFrame(rows)
    csv_path = os.path.join(config.RESULTS_DIR, f"portfolio_{allocation_method}_results.csv")
    df.to_csv(csv_path, index=False)
    logger.info(f"Portfolio results saved: {csv_path}")

    return df


# ============================================================================
# MAIN
# ============================================================================

def run_portfolio(symbols: list = None, allocation_method: str = 'equal'):
    """
    Full portfolio pipeline:
    1. Find best model per crypto
    2. Allocate capital
    3. Run portfolio backtest
    4. Visualize and export
    """
    if symbols is None:
        symbols = config.SYMBOLS

    logger.info(f"\n{'='*80}")
    logger.info(f"PORTFOLIO MULTI-CRYPTO SIMULATION")
    logger.info(f"Symbols: {', '.join(symbols)}")
    logger.info(f"Allocation: {allocation_method}")
    logger.info(f"{'='*80}\n")

    # Step 1: Find best models
    logger.info("STEP 1: Finding best model per crypto...")
    best_models = find_best_models(symbols)

    if not best_models:
        logger.error("No valid models found. Exiting.")
        return

    print("\n" + "=" * 70)
    print("BEST MODEL PER CRYPTO (by Sharpe ratio)")
    print("=" * 70)
    print(f"{'Crypto':<12} {'Model':<22} {'Return %':>10} {'Sharpe':>8} {'Win Rate':>10}")
    print("-" * 70)
    for symbol, info in best_models.items():
        print(f"{symbol:<12} {info['model_type']:<22} {info['return']:>10.2f} "
              f"{info['sharpe']:>8.2f} {info['win_rate']:>9.1f}%")
    print("=" * 70)

    # Step 2: Allocate capital
    logger.info("\nSTEP 2: Allocating capital...")
    allocation = allocate_capital(best_models, method=allocation_method)

    # Step 3: Run portfolio backtest
    logger.info("\nSTEP 3: Running portfolio backtest...")
    results = run_portfolio_backtest(symbols, best_models, allocation)

    if not results['portfolio']:
        logger.error("Portfolio backtest failed. Exiting.")
        return

    # Step 4: Visualize
    logger.info("\nSTEP 4: Generating visualizations...")
    plot_portfolio(results, allocation_method)

    # Step 5: Export
    logger.info("\nSTEP 5: Exporting results...")
    df = export_portfolio_results(results, allocation_method)

    # Print final summary
    p = results['portfolio']
    print("\n" + "=" * 70)
    print("PORTFOLIO RESULTS")
    print("=" * 70)
    print(df.to_string(index=False))
    print("=" * 70)
    print(f"\nPortfolio Return:    {p['total_return']:.2f}%")
    print(f"Buy & Hold Return:   {p['buyhold_return']:.2f}%")
    print(f"Outperformance:      {p['outperformance']:.2f}%")
    print(f"Portfolio Sharpe:    {p['sharpe']:.2f}")
    print(f"Portfolio Max DD:    {p['max_drawdown']:.2f}%")
    print(f"Allocation Method:   {allocation_method}")

    # Print evaluation period
    dates = p.get('dates', [])
    if dates and not isinstance(dates[0], int):
        date_start = str(dates[0])[:10]
        date_end = str(dates[-1])[:10]
        n_days = (dates[-1] - dates[0]).days if hasattr(dates[-1], 'days') else 'N/A'
        try:
            n_days = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days
        except:
            n_days = 'N/A'
        print(f"Evaluation Period:   {date_start} to {date_end} ({n_days} days)")
    print("=" * 70)

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run multi-crypto portfolio simulation")
    parser.add_argument('--symbols', type=str, default=None,
                        help='Comma-separated symbols (default: from config)')
    parser.add_argument('--allocation', type=str, default='equal',
                        choices=['equal', 'risk_parity', 'performance_weighted'],
                        help='Capital allocation method (default: equal)')

    args = parser.parse_args()

    symbols = args.symbols.split(',') if args.symbols else config.SYMBOLS

    run_portfolio(symbols, args.allocation)

    logger.info(f"\nLog file: {log_filename}")
    logger.info("Portfolio simulation complete!")
