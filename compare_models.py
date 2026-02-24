"""
Multi-Model Comparison Script
Tests multiple ML models on each symbol with proper train/test split.
Each model is independently trained, producing genuinely different results.
Exports all results to CSV and generates comparison visualizations.
"""

import sys
import os
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'config'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import config as config
from data_manager import DataManager
from feature_engineer import FeatureEngineer
from model_trainer import ModelTrainer, SUPPORTED_MODEL_TYPES, normalize_model_type
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

# Models to compare by default.
MODEL_TYPES = SUPPORTED_MODEL_TYPES.copy()


def _split_raw_train_test(data: pd.DataFrame):
    """Chronological split on raw feature data (before target/feature selection)."""
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
    """Build inference matrix on test side using train-selected features only."""
    feature_cols = [c for c in selected_features if c in test_data.columns]
    if not feature_cols:
        return pd.DataFrame(index=test_data.index)
    X_test = test_data[feature_cols].copy()
    X_test = X_test.replace([np.inf, -np.inf], np.nan).dropna()
    return X_test


def _auto_allocate_workers(total_workers: int, n_symbols: int, n_models: int):
    """
    Auto-dispatch total workers across symbol-level and model-level parallelism.
    Chooses (symbol_workers, model_workers) maximizing utilization <= total_workers.
    """
    total_workers = max(1, int(total_workers))
    n_symbols = max(1, int(n_symbols))
    n_models = max(1, int(n_models))

    max_symbol_workers = min(n_symbols, total_workers)
    best_symbol_workers = 1
    best_model_workers = 1
    best_utilization = 1

    for symbol_workers in range(1, max_symbol_workers + 1):
        model_workers = min(n_models, max(1, total_workers // symbol_workers))
        utilization = symbol_workers * model_workers

        if utilization > best_utilization or (
            utilization == best_utilization and symbol_workers > best_symbol_workers
        ):
            best_symbol_workers = symbol_workers
            best_model_workers = model_workers
            best_utilization = utilization

    return best_symbol_workers, best_model_workers


def _normalize_model_list(raw_models: list) -> list:
    """Normalize aliases, validate against supported models, and deduplicate."""
    normalized = [normalize_model_type(m) for m in raw_models if m and str(m).strip()]
    invalid = [m for m in normalized if m not in MODEL_TYPES]
    if invalid:
        raise ValueError(
            f"Invalid models: {invalid}. Supported: {', '.join(MODEL_TYPES)}"
        )
    # Keep user order while removing duplicates.
    deduped = list(dict.fromkeys(normalized))
    return deduped


def _train_and_backtest_model(
    symbol: str,
    model_type: str,
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_test: pd.DataFrame,
    test_data: pd.DataFrame,
):
    """Train one model type and run backtest."""
    trainer = ModelTrainer(config)
    backtester = RobustBacktester(config)

    trainer.train(X_train, y_train, symbol, model_type=model_type)
    signals = trainer.predict_signals(X_test)

    result = backtester.backtest(test_data, signals, symbol, model_type=model_type)
    signal_stats = (
        f"Buy={np.sum(signals==2)}, Hold={np.sum(signals==1)}, Sell={np.sum(signals==0)}"
    )
    return result, signal_stats


def compare_models_for_symbol(symbol: str, model_workers: int = 1, model_types: list = None) -> list:
    """
    Train and test all 5 model types on one symbol.
    Uses the SAME train/test split for fair comparison.

    Args:
        symbol: Trading symbol

    Returns:
        List of BacktestResults (one per model)
    """
    if model_types is None:
        model_types = MODEL_TYPES
    model_types = _normalize_model_list(model_types)
    if not model_types:
        logger.error("No models selected for comparison")
        return []

    logger.info(f"\n{'='*80}")
    logger.info(f"COMPARING MODELS FOR: {symbol}")
    logger.info(f"Models: {', '.join(model_types)}")
    logger.info(f"{'='*80}\n")

    # Initialize shared components
    data_manager = DataManager(config)
    feature_engineer = FeatureEngineer(config)

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

    # 3. Chronological split on RAW data to avoid target/feature-selection leakage.
    train_data, test_data_raw = _split_raw_train_test(data)
    if len(train_data) == 0 or len(test_data_raw) == 0:
        logger.error("Invalid train/test split: one side is empty")
        return []

    # 4. Prepare training data using train side only.
    logger.info("Step 3: Preparing training data...")
    base_trainer = ModelTrainer(config)
    X_train, y_train, selected_features = base_trainer.prepare_data(train_data, symbol)
    X_test = _build_test_matrix(test_data_raw, selected_features)
    if len(X_train) == 0 or len(X_test) == 0:
        logger.error("Invalid processed split: empty X_train or X_test after feature filtering")
        return []

    test_data = test_data_raw.loc[X_test.index]
    logger.info(f"  X_train: {X_train.shape} | X_test: {X_test.shape}")

    # 5. Train and test each model independently
    results_list = []

    max_model_workers = max(1, min(int(model_workers), len(model_types)))
    if max_model_workers == 1:
        for model_type in model_types:
            logger.info(f"\n--- Training {model_type.upper()} ---")
            try:
                result, signal_stats = _train_and_backtest_model(
                    symbol, model_type, X_train, y_train, X_test, test_data
                )
                logger.info(f"  Signals: {signal_stats}")
                results_list.append(result)
                logger.info(
                    f"  {model_type}: Return={result.total_return_pct:.2f}%, "
                    f"Sharpe={result.sharpe_ratio:.2f}, WinRate={result.win_rate:.1f}%"
                )
            except Exception as e:
                if isinstance(e, ImportError):
                    logger.warning(f"  Skipping {model_type}: {str(e)}")
                else:
                    logger.error(f"  Error with {model_type}: {str(e)}", exc_info=True)
                continue
    else:
        logger.info(f"Running model comparison in parallel ({max_model_workers} workers)")
        futures = {}
        with ThreadPoolExecutor(max_workers=max_model_workers) as executor:
            for model_type in model_types:
                futures[executor.submit(
                    _train_and_backtest_model,
                    symbol, model_type, X_train, y_train, X_test, test_data
                )] = model_type

            for future in as_completed(futures):
                model_type = futures[future]
                logger.info(f"\n--- Training {model_type.upper()} ---")
                try:
                    result, signal_stats = future.result()
                    logger.info(f"  Signals: {signal_stats}")
                    results_list.append(result)
                    logger.info(
                        f"  {model_type}: Return={result.total_return_pct:.2f}%, "
                        f"Sharpe={result.sharpe_ratio:.2f}, WinRate={result.win_rate:.1f}%"
                    )
                except Exception as e:
                    if isinstance(e, ImportError):
                        logger.warning(f"  Skipping {model_type}: {str(e)}")
                    else:
                        logger.error(f"  Error with {model_type}: {str(e)}", exc_info=True)
                    continue

    return results_list


def run_full_comparison(symbols: list = None, symbol_workers: int = 1,
                        model_workers: int = 1, model_types: list = None):
    """
    Run model comparison across all symbols.
    Generates CSV with all results and comparison visualizations.
    """
    if symbols is None:
        symbols = config.SYMBOLS
    if model_types is None:
        model_types = MODEL_TYPES
    model_types = _normalize_model_list(model_types)

    logger.info(
        f"Worker allocation: symbol_workers={max(1, int(symbol_workers))}, "
        f"model_workers={max(1, int(model_workers))}, "
        f"max_parallel={max(1, int(symbol_workers)) * max(1, int(model_workers))}"
    )

    visualizer = Visualizer(config)
    all_results = []
    results_by_symbol = {}

    max_symbol_workers = max(1, min(int(symbol_workers), len(symbols)))
    if max_symbol_workers == 1:
        for symbol in symbols:
            try:
                symbol_results = compare_models_for_symbol(
                    symbol, model_workers=model_workers, model_types=model_types
                )
                results_by_symbol[symbol] = symbol_results
                all_results.extend(symbol_results)
            except Exception as e:
                logger.error(f"Error comparing models for {symbol}: {str(e)}", exc_info=True)
                continue
    else:
        logger.info(f"Running symbol comparison in parallel ({max_symbol_workers} workers)")
        futures = {}
        with ThreadPoolExecutor(max_workers=max_symbol_workers) as executor:
            for symbol in symbols:
                futures[executor.submit(
                    compare_models_for_symbol, symbol, model_workers, model_types
                )] = symbol

            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    symbol_results = future.result()
                    results_by_symbol[symbol] = symbol_results
                    all_results.extend(symbol_results)
                except Exception as e:
                    logger.error(f"Error comparing models for {symbol}: {str(e)}", exc_info=True)
                    continue

    # Generate per-symbol plots in main thread
    for symbol in symbols:
        symbol_results = results_by_symbol.get(symbol, [])
        if symbol_results and config.GENERATE_PLOTS:
            visualizer.plot_model_comparison(symbol_results, symbol)
            visualizer.plot_equity_comparison(symbol_results, symbol)

            # Plot detailed backtests. By default, save all candidate plots.
            plot_all_candidates = bool(getattr(config, 'COMPARE_PLOT_ALL_CANDIDATES', True))
            if plot_all_candidates:
                for result in symbol_results:
                    visualizer.plot_backtest_summary(result)
            else:
                best = max(symbol_results, key=lambda r: r.total_return_pct)
                visualizer.plot_backtest_summary(best)

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

        try:
            df.to_csv(csv_path, index=False)
            logger.info(f"\nResults saved to: {csv_path}")
        except PermissionError:
            fallback_csv = os.path.join(
                config.RESULTS_DIR,
                f"model_comparison_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            )
            df.to_csv(fallback_csv, index=False)
            logger.warning(
                f"Could not write {csv_path} (file locked). "
                f"Saved results to: {fallback_csv}"
            )

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
    parser.add_argument('--models', type=str, default=None,
                        help='Comma-separated model list (lgbm,xgboost,catboost,hist_gradient_boosting,extra_trees,random_forest,logistic_regression,neural_network)')
    parser.add_argument('--workers', type=int, default=1,
                        help='Total workers to auto-dispatch across symbols and models')
    parser.add_argument('--symbol-workers', type=int, default=None,
                        help='Optional manual override for symbol-level workers')
    parser.add_argument('--model-workers', type=int, default=None,
                        help='Optional manual override for model-level workers')

    args = parser.parse_args()

    symbols = args.symbols.split(',') if args.symbols else config.SYMBOLS
    selected_models = _normalize_model_list(
        args.models.split(',') if args.models else MODEL_TYPES
    )

    if args.symbol_workers is not None or args.model_workers is not None:
        symbol_workers = max(1, int(args.symbol_workers) if args.symbol_workers is not None else 1)
        model_workers = max(1, int(args.model_workers) if args.model_workers is not None else 1)
    else:
        symbol_workers, model_workers = _auto_allocate_workers(
            args.workers, len(symbols), len(selected_models)
        )

    config.print_config()
    results = run_full_comparison(
        symbols,
        symbol_workers=symbol_workers,
        model_workers=model_workers,
        model_types=selected_models,
    )

    logger.info(f"\nLog file: {log_filename}")
    logger.info("Comparison complete!")
