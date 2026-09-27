"""
Main Script - Crypto Trading Strategy
Runs the full pipeline: data -> features -> train/test -> backtest -> visualize
Properly handles config passing, train/test split, and data alignment.
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
from model_trainer import ModelTrainer, SUPPORTED_MODEL_TYPES
from backtester import RobustBacktester, BacktestResults
from visualizer import Visualizer

import numpy as np
import pandas as pd

# ============================================================================
# LOGGING SETUP
# ============================================================================

log_filename = os.path.join(config.LOGS_DIR, f"main_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def _split_raw_train_test(data: pd.DataFrame):
    """Chronological split on raw feature data (before labels/feature selection)."""
    test_start = getattr(config, 'TEST_START_DATE', None)
    if test_start and isinstance(data.index, pd.DatetimeIndex):
        test_start_ts = pd.Timestamp(test_start)
        train_data = data[data.index < test_start_ts]
        test_data = data[data.index >= test_start_ts]
    else:
        split_idx = int(len(data) * (1 - config.TEST_SIZE))
        train_data = data.iloc[:split_idx]
        test_data = data.iloc[split_idx:]
    return train_data, test_data


def _build_test_matrix(test_data: pd.DataFrame, selected_features: list) -> pd.DataFrame:
    feature_cols = [c for c in selected_features if c in test_data.columns]
    if not feature_cols:
        return pd.DataFrame(index=test_data.index)
    X_test = test_data[feature_cols].copy()
    X_test = X_test.replace([np.inf, -np.inf], np.nan).dropna()
    return X_test


# ============================================================================
# SINGLE COIN PIPELINE
# ============================================================================

def run_single_coin(symbol: str, model_type: str = None) -> BacktestResults:
    """
    Run the full pipeline for a single coin with proper train/test split.

    Args:
        symbol: Trading symbol (e.g., 'BTCUSDT')
        model_type: Model type override (default: from config)

    Returns:
        BacktestResults
    """
    if model_type is None:
        model_type = config.MODEL_TYPE

    logger.info(f"\n{'='*80}")
    logger.info(f"RUNNING: {symbol} with {model_type.upper()}")
    logger.info(f"{'='*80}\n")

    # Initialize components with config MODULE (not sys.modules)
    data_manager = DataManager(config)
    feature_engineer = FeatureEngineer(config)
    model_trainer = ModelTrainer(config)
    backtester = RobustBacktester(config)

    # 1. Fetch and prepare data
    logger.info("Step 1: Fetching data...")
    data = data_manager.fetch_data(symbol, config.BINANCE_INTERVAL, config.BINANCE_START_TIME)
    if data is None:
        raise ValueError(f"Failed to fetch data for {symbol}")
    data = data_manager.prepare_data(data, symbol)
    logger.info(f"  Data: {len(data)} candles")

    # 2. Engineer features
    logger.info("Step 2: Engineering features...")
    data = feature_engineer.engineer_features(data, symbol)
    logger.info(f"  Features: {len(data.columns)} columns, {len(data)} rows after NaN removal")

    # 3. Split raw data first to avoid leakage.
    train_data, test_data_raw = _split_raw_train_test(data)
    if len(train_data) == 0 or len(test_data_raw) == 0:
        raise ValueError("Invalid train/test split: one side is empty")

    # 4. Prepare training data on train side only.
    logger.info("Step 3: Preparing training data...")
    X_train, y_train, selected_features = model_trainer.prepare_data(train_data, symbol)
    X_test = _build_test_matrix(test_data_raw, selected_features)
    if len(X_train) == 0 or len(X_test) == 0:
        raise ValueError("Invalid processed split: empty X_train or X_test")

    # Get aligned test rows for backtesting
    test_data = test_data_raw.loc[X_test.index]

    if len(X_test) > 0 and isinstance(X_test.index, pd.DatetimeIndex):
        logger.info(f"  Train: {len(X_train)} samples ({str(X_train.index[0])[:10]} to {str(X_train.index[-1])[:10]})")
        logger.info(f"  Test:  {len(X_test)} samples ({str(X_test.index[0])[:10]} to {str(X_test.index[-1])[:10]})")
    else:
        logger.info(f"  Train: {len(X_train)} samples | Test: {len(X_test)} samples")

    # 5. Train model
    logger.info(f"Step 4: Training {model_type.upper()} model...")
    model_trainer.train(X_train, y_train, symbol, model_type=model_type)

    # 6. Generate signals on TEST data only (no data leakage!)
    logger.info("Step 5: Generating signals on test data...")
    signals = model_trainer.predict_signals(X_test)
    logger.info(f"  Signals: Buy={np.sum(signals==2)}, Hold={np.sum(signals==1)}, Sell={np.sum(signals==0)}")

    # 7. Backtest on test data with aligned signals
    logger.info("Step 6: Backtesting...")
    results = backtester.backtest(test_data, signals, symbol, model_type=model_type)

    # 8. Save model
    if config.SAVE_MODELS:
        model_trainer.save_model(symbol)

    return results


# ============================================================================
# MULTI-COIN PIPELINE
# ============================================================================

def run_multi_coin(symbols: list = None, model_type: str = None):
    """
    Run the pipeline for multiple coins.

    Args:
        symbols: List of symbols (default: from config)
        model_type: Model type override
    """
    if symbols is None:
        symbols = config.SYMBOLS

    all_results = {}
    visualizer = Visualizer(config)

    for symbol in symbols:
        try:
            results = run_single_coin(symbol, model_type)
            all_results[symbol] = results

            # Generate backtest summary plot
            if config.GENERATE_PLOTS:
                visualizer.plot_backtest_summary(results)

        except Exception as e:
            logger.error(f"Error processing {symbol}: {str(e)}", exc_info=True)
            continue

    # Print summary
    if all_results:
        # Print evaluation period
        for symbol, r in all_results.items():
            if hasattr(r, 'dates') and len(r.dates) > 0 and not isinstance(r.dates[0], int):
                date_start = str(r.dates[0])[:10]
                date_end = str(r.dates[-1])[:10]
                try:
                    n_days = (pd.Timestamp(r.dates[-1]) - pd.Timestamp(r.dates[0])).days
                except:
                    n_days = 'N/A'
                print(f"\nEvaluation Period: {date_start} to {date_end} ({n_days} days)")
                break

        print("\n" + "=" * 100)
        print("RESULTS SUMMARY")
        print("=" * 100)
        print(f"{'Symbol':<12} {'Model':<15} {'Return %':>10} {'B&H %':>10} {'Sharpe':>8} "
              f"{'MaxDD %':>8} {'WinRate':>8} {'Trades':>8}")
        print("-" * 100)
        for symbol, r in all_results.items():
            print(f"{r.symbol:<12} {r.model_type:<15} {r.total_return_pct:>10.2f} "
                  f"{r.buy_hold_return_pct:>10.2f} {r.sharpe_ratio:>8.2f} "
                  f"{r.max_drawdown:>8.2f} {r.win_rate:>7.1f}% {r.num_trades:>8}")
        print("=" * 100)

    return all_results


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Crypto Trading Strategy")
    parser.add_argument('--symbol', type=str, default=None, help='Single symbol to test')
    parser.add_argument('--symbols', type=str, default=None, help='Comma-separated symbols')
    parser.add_argument(
        '--model',
        type=str,
        default=None,
        help=f"Model type ({', '.join(SUPPORTED_MODEL_TYPES)})"
    )

    args = parser.parse_args()

    # Print config
    config.print_config()

    # Determine symbols
    if args.symbol:
        symbols = [args.symbol]
    elif args.symbols:
        symbols = args.symbols.split(',')
    else:
        symbols = config.SYMBOLS

    # Run
    results = run_multi_coin(symbols, args.model)

    logger.info(f"\nLog file: {log_filename}")
    logger.info("Done!")
