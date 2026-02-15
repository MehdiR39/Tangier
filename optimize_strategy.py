"""
Automatic Strategy Optimization Script
Runs hyperparameter optimization and walk-forward validation.
"""

import sys
import os
import logging
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed

# Add paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'config'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import config as config
from data_manager import DataManager
from feature_engineer import FeatureEngineer
from model_trainer import ModelTrainer
from backtester import RobustBacktester
from optimizer import HyperparameterOptimizer, WalkForwardValidator
import pandas as pd

# Setup logging
log_filename = os.path.join(config.LOGS_DIR, f"optimization_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def optimize_single_coin(symbol: str, enable_hyperopt: bool = True,
                         enable_wf: bool = True, n_trials: int = 50):
    """Run optimization for a single cryptocurrency."""
    logger.info(f"\n{'='*80}")
    logger.info(f"OPTIMIZATION: {symbol}")
    logger.info(f"{'='*80}\n")

    try:
        # Initialize components with config MODULE
        data_manager = DataManager(config)
        feature_engineer = FeatureEngineer(config)
        model_trainer = ModelTrainer(config)
        backtester = RobustBacktester(config)

        # 1. Fetch data
        logger.info("Step 1: Fetching data...")
        data = data_manager.fetch_data(symbol, config.BINANCE_INTERVAL, config.BINANCE_START_TIME)
        if data is None:
            logger.error(f"Failed to fetch data for {symbol}")
            return {'symbol': symbol, 'status': 'failed', 'reason': 'data_fetch_failed'}
        data = data_manager.prepare_data(data, symbol)
        logger.info(f"  Data: {len(data)} candles")

        # 2. Engineer features
        logger.info("Step 2: Engineering features...")
        data = feature_engineer.engineer_features(data, symbol)
        logger.info(f"  Features: {len(data.columns)} columns")

        # 3. Prepare training data
        logger.info("Step 3: Preparing training data...")
        X, y, selected_features = model_trainer.prepare_data(data, symbol)
        logger.info(f"  X shape: {X.shape}, y shape: {y.shape}")

        # 3b. Chronological train/validation split to avoid in-sample optimization
        test_start = getattr(config, 'TEST_START_DATE', None)
        if test_start and isinstance(X.index, pd.DatetimeIndex):
            test_start_ts = pd.Timestamp(test_start)
            X_train = X[X.index < test_start_ts]
            X_valid = X[X.index >= test_start_ts]
            y_train = y[y.index < test_start_ts]
            y_valid = y[y.index >= test_start_ts]
        else:
            split_idx = int(len(X) * (1 - config.TEST_SIZE))
            X_train, X_valid = X.iloc[:split_idx], X.iloc[split_idx:]
            y_train, y_valid = y.iloc[:split_idx], y.iloc[split_idx:]

        if len(X_train) == 0 or len(X_valid) == 0:
            logger.error("Invalid split for optimization: empty train or validation set")
            return {'symbol': symbol, 'status': 'failed', 'reason': 'invalid_split'}

        valid_data = data.loc[X_valid.index]

        # 4. Train baseline model
        logger.info("Step 4: Training baseline model...")
        model_trainer.train(X_train, y_train, symbol)

        # 5. Hyperparameter Optimization
        if enable_hyperopt:
            logger.info(f"\nStep 5: Hyperparameter optimization ({n_trials} trials)...")
            hp_optimizer = HyperparameterOptimizer(config, backtester, model_trainer)
            train_data = data.loc[X_train.index]
            hp_results = hp_optimizer.optimize(train_data, valid_data, symbol, n_trials=n_trials)
            hp_optimizer.save_best_params(symbol)

            logger.info(f"  Best Sharpe: {hp_results['best_score']:.4f}")
            for param, value in hp_results['best_params'].items():
                logger.info(f"    {param}: {value:.4f}")

        # 6. Walk-Forward Validation
        if enable_wf:
            logger.info(f"\nStep 6: Walk-forward validation...")
            wf_validator = WalkForwardValidator(config, model_trainer, backtester)
            wf_results = wf_validator.validate(data, feature_engineer, symbol)
            wf_validator.save_results(symbol)

            logger.info(f"  Windows: {len(wf_results['windows'])}")
            logger.info(f"  Avg Return: {wf_results['average_return']:.2f}%")
            logger.info(f"  Avg Sharpe: {wf_results['average_sharpe']:.4f}")

        logger.info(f"\nOptimization complete for {symbol}")
        return {'symbol': symbol, 'status': 'ok'}

    except Exception as e:
        logger.error(f"Error optimizing {symbol}: {str(e)}", exc_info=True)
        return {'symbol': symbol, 'status': 'failed', 'reason': str(e)}


def optimize_multi_coin(symbols: list = None, enable_hyperopt: bool = True,
                        enable_wf: bool = True, n_trials: int = 50, workers: int = 1):
    """Run optimization for multiple cryptocurrencies."""
    if symbols is None:
        symbols = config.SYMBOLS

    logger.info(f"\n{'='*80}")
    logger.info(f"MULTI-COIN STRATEGY OPTIMIZATION")
    logger.info(f"Symbols: {', '.join(symbols)}")
    logger.info(f"{'='*80}\n")

    max_workers = max(1, min(int(workers), len(symbols)))
    summaries = []

    if max_workers == 1:
        for symbol in symbols:
            summaries.append(optimize_single_coin(symbol, enable_hyperopt, enable_wf, n_trials))
    else:
        logger.info(f"Running optimization in parallel ({max_workers} workers)")
        futures = {}
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            for symbol in symbols:
                futures[executor.submit(
                    optimize_single_coin, symbol, enable_hyperopt, enable_wf, n_trials
                )] = symbol
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    summaries.append(future.result())
                except Exception as e:
                    logger.error(f"Error optimizing {symbol}: {str(e)}", exc_info=True)
                    summaries.append({'symbol': symbol, 'status': 'failed', 'reason': str(e)})

    logger.info(f"\nAll optimizations complete. Results: {config.RESULTS_DIR}")
    ok = len([s for s in summaries if s and s.get('status') == 'ok'])
    fail = len(symbols) - ok
    logger.info(f"Optimization summary: success={ok}, failed={fail}")
    return summaries


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Optimize crypto trading strategy")
    parser.add_argument('--symbol', type=str, default=None)
    parser.add_argument('--symbols', type=str, default=None)
    parser.add_argument('--no-hyperopt', action='store_true')
    parser.add_argument('--no-wf', action='store_true')
    parser.add_argument('--trials', type=int, default=50)
    parser.add_argument('--workers', type=int, default=1, help='Parallel workers across symbols')

    args = parser.parse_args()

    if args.symbol:
        symbols = [args.symbol]
    elif args.symbols:
        symbols = args.symbols.split(',')
    else:
        symbols = config.SYMBOLS

    optimize_multi_coin(
        symbols,
        not args.no_hyperopt,
        not args.no_wf,
        args.trials,
        workers=max(1, args.workers),
    )
