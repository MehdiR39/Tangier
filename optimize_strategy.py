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


def _split_raw_train_valid(data: pd.DataFrame):
    """Chronological split on raw feature data (before labels/feature selection)."""
    test_start = getattr(config, 'TEST_START_DATE', None)
    if test_start and isinstance(data.index, pd.DatetimeIndex):
        test_start_ts = pd.Timestamp(test_start)
        train_data = data[data.index < test_start_ts]
        valid_data = data[data.index >= test_start_ts]
    else:
        split_idx = int(len(data) * (1 - config.TEST_SIZE))
        train_data = data.iloc[:split_idx]
        valid_data = data.iloc[split_idx:]
    return train_data, valid_data


def _apply_best_params_to_runtime(cfg, params: dict) -> dict:
    """Apply Optuna best params to runtime config used by walk-forward."""
    if not params:
        return {}

    key_map = {
        'stop_loss': 'STOP_LOSS',
        'take_profit': 'TAKE_PROFIT',
        'confidence_threshold': 'CONFIDENCE_THRESHOLD',
        'buy_threshold': 'BUY_THRESHOLD',
        'sell_threshold': 'SELL_THRESHOLD',
        'atr_threshold': 'ATR_THRESHOLD',
    }

    applied = {}
    for src_key, dst_key in key_map.items():
        if src_key in params and params[src_key] is not None:
            value = float(params[src_key])
            setattr(cfg, dst_key, value)
            applied[dst_key] = value

    # Apply tuned model parameters if present.
    lgbm_int_params = {
        'n_estimators', 'num_leaves', 'max_depth', 'min_data_in_leaf', 'bagging_freq'
    }
    xgb_int_params = {
        'n_estimators', 'max_depth'
    }

    def _cast_model_param(param_name: str, raw_value, int_keys: set):
        if isinstance(raw_value, (int, float)):
            return int(round(raw_value)) if param_name in int_keys else float(raw_value)
        return raw_value

    lgbm_updates = {}
    xgb_updates = {}
    for key, raw_value in params.items():
        if key.startswith('lgbm_'):
            param_name = key[len('lgbm_'):]
            lgbm_updates[param_name] = _cast_model_param(param_name, raw_value, lgbm_int_params)
        elif key.startswith('xgb_'):
            param_name = key[len('xgb_'):]
            xgb_updates[param_name] = _cast_model_param(param_name, raw_value, xgb_int_params)

    if lgbm_updates:
        current = dict(getattr(cfg, 'LGBM_PARAMS', {}) or {})
        current.update(lgbm_updates)
        setattr(cfg, 'LGBM_PARAMS', current)
        for k, v in lgbm_updates.items():
            applied[f"LGBM_PARAMS.{k}"] = v

    if xgb_updates:
        current = dict(getattr(cfg, 'XGB_PARAMS', {}) or {})
        current.update(xgb_updates)
        setattr(cfg, 'XGB_PARAMS', current)
        for k, v in xgb_updates.items():
            applied[f"XGB_PARAMS.{k}"] = v

    return applied


def _evaluate_validation_split(
    cfg,
    trainer,
    backtester,
    train_data: pd.DataFrame,
    valid_data: pd.DataFrame,
    selected_features: list,
    symbol: str,
    model_type: str,
):
    """Backtest one trained model on validation split with ATR/confidence filters."""
    X_valid = HyperparameterOptimizer._build_X(valid_data, selected_features)
    if len(X_valid) == 0:
        return None

    confidence = float(getattr(cfg, 'CONFIDENCE_THRESHOLD', 0.5))
    atr_threshold = float(getattr(cfg, 'ATR_THRESHOLD', 1.0))
    gate = HyperparameterOptimizer(cfg, backtester, trainer)

    signals = trainer.predict_signals(X_valid, confidence_threshold=confidence)
    signals = gate._apply_atr_filter(cfg, valid_data, X_valid.index, signals, atr_threshold, train_data)

    bt_data = valid_data.loc[X_valid.index]
    return backtester.backtest(
        bt_data,
        signals,
        symbol,
        model_type=model_type,
        stop_loss=float(getattr(cfg, 'STOP_LOSS', 0.05)),
        take_profit=float(getattr(cfg, 'TAKE_PROFIT', 0.15)),
    )


def _passes_optuna_gate(cfg, baseline_result, tuned_result) -> bool:
    """Only deploy tuned params if they beat baseline enough on validation."""
    if baseline_result is None or tuned_result is None:
        return False

    min_return_delta = float(getattr(cfg, 'OPTUNA_GATE_MIN_RETURN_DELTA_PCT', 0.0))
    min_sharpe_delta = float(getattr(cfg, 'OPTUNA_GATE_MIN_SHARPE_DELTA', -0.10))
    max_dd_delta = float(getattr(cfg, 'OPTUNA_GATE_MAX_DRAWDOWN_DELTA_PCT', 5.0))
    min_trades = int(getattr(cfg, 'OPTUNA_GATE_MIN_TRADES', 5))

    return_delta = float(tuned_result.total_return_pct) - float(baseline_result.total_return_pct)
    sharpe_delta = float(tuned_result.sharpe_ratio) - float(baseline_result.sharpe_ratio)
    dd_delta = float(tuned_result.max_drawdown) - float(baseline_result.max_drawdown)

    checks = {
        'return_delta_ok': return_delta >= min_return_delta,
        'sharpe_delta_ok': sharpe_delta >= min_sharpe_delta,
        'drawdown_delta_ok': dd_delta <= max_dd_delta,
        'min_trades_ok': int(tuned_result.num_trades) >= min_trades,
    }
    logger.info(
        "Validation gate deltas: return=%+.2f, sharpe=%+.3f, max_dd=%+.2f, trades=%+d",
        return_delta,
        sharpe_delta,
        dd_delta,
        int(tuned_result.num_trades) - int(baseline_result.num_trades),
    )
    logger.info(
        "Validation gate checks: %s",
        ", ".join([f"{k}={v}" for k, v in checks.items()])
    )
    return all(checks.values())


def optimize_single_coin(symbol: str, enable_hyperopt: bool = True,
                         enable_wf: bool = True, n_trials: int = 50,
                         trial_workers: int = 1):
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

        # 3. Split raw data first to avoid target/feature-selection leakage.
        train_data, valid_data = _split_raw_train_valid(data)
        if len(train_data) == 0 or len(valid_data) == 0:
            logger.error("Invalid split for optimization: empty train or validation set")
            return {'symbol': symbol, 'status': 'failed', 'reason': 'invalid_split'}

        # 4. Prepare training data on train side only.
        logger.info("Step 3: Preparing training data...")
        X_train, y_train, selected_features = model_trainer.prepare_data(train_data, symbol)
        X_valid = HyperparameterOptimizer._build_X(valid_data, selected_features)
        if len(X_train) == 0 or len(X_valid) == 0:
            logger.error("Invalid processed split for optimization: empty X_train or X_valid")
            return {'symbol': symbol, 'status': 'failed', 'reason': 'invalid_processed_split'}
        logger.info(f"  X_train: {X_train.shape}, X_valid: {X_valid.shape}")

        # 5. Train baseline model
        logger.info("Step 4: Training baseline model...")
        model_trainer.train(X_train, y_train, symbol)
        baseline_valid = _evaluate_validation_split(
            config,
            model_trainer,
            backtester,
            train_data,
            valid_data,
            selected_features,
            symbol,
            model_type="baseline_valid",
        )
        if baseline_valid is not None:
            logger.info(
                "  Baseline valid: Return=%.2f%%, Sharpe=%.3f, MaxDD=%.2f%%, Trades=%d",
                baseline_valid.total_return_pct,
                baseline_valid.sharpe_ratio,
                baseline_valid.max_drawdown,
                baseline_valid.num_trades,
            )

        # 6. Hyperparameter Optimization
        if enable_hyperopt:
            logger.info(
                f"\nStep 5: Hyperparameter optimization "
                f"({n_trials} trials, {max(1, int(trial_workers))} trial workers)..."
            )
            hp_optimizer = HyperparameterOptimizer(config, backtester, model_trainer)
            hp_results = hp_optimizer.optimize(
                train_data,
                valid_data,
                symbol,
                n_trials=n_trials,
                n_jobs=max(1, int(trial_workers))
            )
            hp_optimizer.save_best_params(symbol)

            logger.info(f"  Best Objective Score: {hp_results['best_score']:.4f}")
            for param, value in hp_results['best_params'].items():
                logger.info(f"    {param}: {value:.4f}")

            candidate_cfg = HyperparameterOptimizer._clone_config_namespace(config)
            candidate_applied = _apply_best_params_to_runtime(candidate_cfg, hp_results.get('best_params', {}))

            tuned_trainer = ModelTrainer(candidate_cfg)
            tuned_backtester = RobustBacktester(candidate_cfg)
            X_train_tuned, y_train_tuned, tuned_features = tuned_trainer.prepare_data(train_data, symbol)
            tuned_trainer.train(X_train_tuned, y_train_tuned, symbol)
            tuned_valid = _evaluate_validation_split(
                candidate_cfg,
                tuned_trainer,
                tuned_backtester,
                train_data,
                valid_data,
                tuned_features,
                symbol,
                model_type="tuned_valid",
            )
            if tuned_valid is not None:
                logger.info(
                    "  Tuned valid: Return=%.2f%%, Sharpe=%.3f, MaxDD=%.2f%%, Trades=%d",
                    tuned_valid.total_return_pct,
                    tuned_valid.sharpe_ratio,
                    tuned_valid.max_drawdown,
                    tuned_valid.num_trades,
                )

            use_gate = bool(getattr(config, 'OPTUNA_APPLY_VALIDATION_GATE', True))
            should_apply = bool(candidate_applied)
            if use_gate:
                should_apply = _passes_optuna_gate(config, baseline_valid, tuned_valid)
                logger.info("  Validation gate decision: %s", "APPLY_TUNED" if should_apply else "KEEP_BASELINE")

            if should_apply:
                applied_params = _apply_best_params_to_runtime(config, hp_results.get('best_params', {}))
                logger.info("  Applied optimized params to runtime config:")
                for key, value in applied_params.items():
                    logger.info(f"    {key}: {value:.4f}")
            else:
                logger.warning("  Tuned params rejected by validation gate; keeping baseline runtime config")

        # 7. Walk-Forward Validation
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

    total_workers = max(1, int(workers))
    symbol_workers = max(1, min(total_workers, len(symbols)))
    trial_workers = max(1, total_workers // symbol_workers) if enable_hyperopt else 1

    logger.info(
        f"Worker allocation: total={total_workers}, "
        f"symbol_workers={symbol_workers}, trial_workers_per_symbol={trial_workers}"
    )
    summaries = []

    if symbol_workers == 1:
        for symbol in symbols:
            summaries.append(
                optimize_single_coin(
                    symbol, enable_hyperopt, enable_wf, n_trials, trial_workers=trial_workers
                )
            )
    else:
        logger.info(f"Running optimization in parallel ({symbol_workers} symbol workers)")
        futures = {}
        with ProcessPoolExecutor(max_workers=symbol_workers) as executor:
            for symbol in symbols:
                futures[executor.submit(
                    optimize_single_coin,
                    symbol,
                    enable_hyperopt,
                    enable_wf,
                    n_trials,
                    trial_workers
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
    parser.add_argument('--model', type=str, default=None,
                        help='Model override (e.g. lgbm, xgboost, extra_trees, random_forest)')
    parser.add_argument('--no-hyperopt', action='store_true')
    parser.add_argument('--no-wf', action='store_true')
    parser.add_argument('--trials', type=int, default=50)
    parser.add_argument('--workers', type=int, default=1, help='Parallel workers across symbols')

    args = parser.parse_args()

    if args.model:
        try:
            from model_trainer import normalize_model_type
            model_name = normalize_model_type(args.model)
        except Exception:
            model_name = args.model.strip().lower()
        setattr(config, 'MODEL_TYPE', model_name)
        logger.info(f"Using CLI model override: MODEL_TYPE={model_name}")

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
