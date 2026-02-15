"""
Multi-Model Comparison Script
Tests 5 different ML models on each symbol with proper train/test split.
Each model is independently trained, producing genuinely different results.
Exports all results to CSV and generates comparison visualizations.
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
from backtester import RobustBacktester, BacktestResults
from visualizer import Visualizer

import numpy as np
import pandas as pd

# ============================================================================
# LOGGING SETUP
# ============================================================================

log_filename = os.path.join(config.LOGS_DIR, f"compare_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Models to compare
MODEL_TYPES = ['lgbm', 'xgboost', 'random_forest', 'logistic_regression', 'neural_network']


def compare_models_for_symbol(symbol: str) -> list:
    """
    Train and test all 5 model types on one symbol.
    Uses the SAME train/test split for fair comparison.

    Args:
        symbol: Trading symbol

    Returns:
        List of BacktestResults (one per model)
    """
    logger.info(f"\n{'='*80}")
    logger.info(f"COMPARING MODELS FOR: {symbol}")
    logger.info(f"{'='*80}\n")

    # Initialize shared components
    data_manager = DataManager(config)
    feature_engineer = FeatureEngineer(config)
    backtester = RobustBacktester(config)

    # 1. Fetch and prepare data (shared across all models)
    logger.info("Step 1: Fetching data...")
    data = data_manager.fetch_data(symbol, config.BINANCE_INTERVAL, config.BINANCE_START_TIME)
    if data is None:
        logger.error(f"Failed to fetch data for {symbol}")
        return []
    data = data_manager.prepare_data(data, symbol)
    logger.info(f"  Data: {len(data)} candles")

    # 2. Engineer features (shared)
    logger.info("Step 2: Engineering features...")
    data = feature_engineer.engineer_features(data, symbol)
    logger.info(f"  Features: {len(data.columns)} columns, {len(data)} rows")

    # 3. Prepare training data (shared target creation and feature selection)
    logger.info("Step 3: Preparing training data...")
    base_trainer = ModelTrainer(config)
    X, y, selected_features = base_trainer.prepare_data(data, symbol)
    logger.info(f"  X shape: {X.shape}, y shape: {y.shape}")

    # 4. Chronological train/test split (shared)
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
        logger.error("Invalid train/test split: one side is empty")
        return []

    test_data = data.loc[X_test.index]
    logger.info(f"  Train: {len(X_train)} | Test: {len(X_test)}")

    # 5. Train and test each model independently
    results_list = []

    for model_type in MODEL_TYPES:
        logger.info(f"\n--- Training {model_type.upper()} ---")
        try:
            # Create a FRESH ModelTrainer for each model type
            trainer = ModelTrainer(config)
            # Re-use the same selected features
            trainer.feature_selector.selected_features = selected_features

            # Train on training data
            trainer.train(X_train, y_train, symbol, model_type=model_type)

            # Generate signals on test data
            signals = trainer.predict_signals(X_test)
            logger.info(f"  Signals: Buy={np.sum(signals==2)}, Hold={np.sum(signals==1)}, Sell={np.sum(signals==0)}")

            # Backtest
            result = backtester.backtest(test_data, signals, symbol, model_type=model_type)
            results_list.append(result)

            logger.info(f"  {model_type}: Return={result.total_return_pct:.2f}%, "
                        f"Sharpe={result.sharpe_ratio:.2f}, WinRate={result.win_rate:.1f}%")

        except Exception as e:
            logger.error(f"  Error with {model_type}: {str(e)}", exc_info=True)
            continue

    return results_list


def run_full_comparison(symbols: list = None):
    """
    Run model comparison across all symbols.
    Generates CSV with all results and comparison visualizations.
    """
    if symbols is None:
        symbols = config.SYMBOLS

    visualizer = Visualizer(config)
    all_results = []
    results_by_symbol = {}

    for symbol in symbols:
        try:
            symbol_results = compare_models_for_symbol(symbol)
            results_by_symbol[symbol] = symbol_results
            all_results.extend(symbol_results)

            # Generate comparison plots for this symbol
            if symbol_results and config.GENERATE_PLOTS:
                visualizer.plot_model_comparison(symbol_results, symbol)
                visualizer.plot_equity_comparison(symbol_results, symbol)

                # Plot detailed backtest for best model only
                best = max(symbol_results, key=lambda r: r.total_return_pct)
                visualizer.plot_backtest_summary(best)

        except Exception as e:
            logger.error(f"Error comparing models for {symbol}: {str(e)}", exc_info=True)
            continue

    # Generate portfolio summary
    if results_by_symbol and config.GENERATE_PLOTS:
        visualizer.plot_portfolio_summary(results_by_symbol)

    # Export all results to CSV (merge with existing file to avoid losing other symbols)
    if all_results:
        df_new = visualizer.create_results_table(all_results)
        csv_path = os.path.join(config.RESULTS_DIR, 'model_comparison_results.csv')

        if os.path.exists(csv_path):
            try:
                df_old = pd.read_csv(csv_path)
                current_symbols = set(df_new['Symbol'].unique())
                df_old_keep = df_old[~df_old['Symbol'].isin(current_symbols)] if 'Symbol' in df_old.columns else pd.DataFrame()
                df = pd.concat([df_old_keep, df_new], ignore_index=True)
                if {'Symbol', 'Model'}.issubset(df.columns):
                    df = df.drop_duplicates(subset=['Symbol', 'Model'], keep='last')
            except Exception as e:
                logger.warning(f"Could not merge previous CSV ({str(e)}). Overwriting with current run.")
                df = df_new
        else:
            df = df_new

        df.to_csv(csv_path, index=False)
        logger.info(f"\nResults saved to: {csv_path}")

        # Print evaluation period
        for symbol, results_list in results_by_symbol.items():
            if results_list and hasattr(results_list[0], 'dates') and len(results_list[0].dates) > 0:
                d = results_list[0].dates
                if not isinstance(d[0], int):
                    date_start = str(d[0])[:10]
                    date_end = str(d[-1])[:10]
                    try:
                        n_days = (pd.Timestamp(d[-1]) - pd.Timestamp(d[0])).days
                    except:
                        n_days = 'N/A'
                    print(f"\nEvaluation Period ({symbol}): {date_start} to {date_end} ({n_days} days)")
                break  # All symbols share similar period

        # Print summary table
        print("\n" + "=" * 120)
        print("MODEL COMPARISON RESULTS")
        print("=" * 120)
        print(df.to_string(index=False))
        print("=" * 120)

        # Print best model per symbol
        print("\nBEST MODEL PER SYMBOL:")
        print("-" * 60)
        for symbol, results_list in results_by_symbol.items():
            if results_list:
                best = max(results_list, key=lambda r: r.total_return_pct)
                print(f"  {symbol}: {best.model_type.upper()} "
                      f"(Return: {best.total_return_pct:.2f}%, Sharpe: {best.sharpe_ratio:.2f})")
        print("-" * 60)

    return all_results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Compare ML models for crypto trading")
    parser.add_argument('--symbols', type=str, default=None, help='Comma-separated symbols')

    args = parser.parse_args()

    symbols = args.symbols.split(',') if args.symbols else config.SYMBOLS

    config.print_config()
    results = run_full_comparison(symbols)

    logger.info(f"\nLog file: {log_filename}")
    logger.info("Comparison complete!")
