"""
Hyperparameter Optimization Module
Uses Optuna to find optimal trading parameters.
Walk-forward validation to prevent overfitting.
"""

import pandas as pd
import numpy as np
import logging
import json
import os
import copy
from typing import Dict, Tuple
from datetime import datetime
from types import SimpleNamespace

logger = logging.getLogger(__name__)


class HyperparameterOptimizer:
    """
    Optimizes trading strategy hyperparameters using Optuna.
    Tests: stop_loss, take_profit, buy/sell thresholds, ATR filter.
    """

    def __init__(self, config, backtester, model_trainer):
        self.config = config
        self.backtester = backtester
        self.model_trainer = model_trainer
        self.best_params = None
        self.best_score = -np.inf
        logger.info("HyperparameterOptimizer initialized")

    def optimize(self, train_data: pd.DataFrame, valid_data: pd.DataFrame,
                 symbol: str, n_trials: int = 50, n_jobs: int = 1) -> Dict:
        """Run hyperparameter optimization."""
        if train_data is None or valid_data is None or len(train_data) == 0 or len(valid_data) == 0:
            logger.error(f"Optimization skipped for {symbol}: empty train/valid data")
            return {'best_params': {}, 'best_score': 0, 'trials': 0}

        try:
            import optuna
            from optuna.pruners import MedianPruner
            from optuna.samplers import TPESampler
        except ImportError:
            logger.error("optuna not installed. Run: pip install optuna")
            return {'best_params': {}, 'best_score': 0, 'trials': 0}

        effective_trials = max(1, int(n_trials))
        effective_jobs = max(1, min(int(n_jobs), effective_trials))
        objective_mode = str(getattr(self.config, 'OPTUNA_OBJECTIVE_MODE', 'robust_windows')).lower()
        logger.info(
            f"Starting optimization for {symbol} "
            f"({effective_trials} trials, {effective_jobs} trial workers, mode={objective_mode})..."
        )

        sampler = TPESampler(seed=42)
        pruner = MedianPruner()
        study = optuna.create_study(direction='maximize', sampler=sampler, pruner=pruner)

        study.optimize(
            lambda trial: self._objective(trial, train_data, valid_data, symbol),
            n_trials=effective_trials,
            n_jobs=effective_jobs,
            show_progress_bar=(effective_jobs == 1)
        )

        self.best_params = study.best_params
        self.best_score = study.best_value

        logger.info(f"Best Objective Score: {self.best_score:.4f}")
        logger.info(f"Best Params: {self.best_params}")

        return {
            'best_params': self.best_params,
            'best_score': self.best_score,
            'trials': len(study.trials)
        }

    @staticmethod
    def _build_X(frame: pd.DataFrame, features: list) -> pd.DataFrame:
        exclude_cols = ['Open', 'High', 'Low', 'Close', 'Volume', 'Returns', 'Log_Returns', 'Target']
        available = [col for col in features if col in frame.columns and col not in exclude_cols]
        if not available:
            return pd.DataFrame(index=frame.index)
        X = frame[available].copy()
        X = X.replace([np.inf, -np.inf], np.nan).dropna()
        return X

    @staticmethod
    def _clone_config_namespace(config_obj):
        data = {}
        for name in dir(config_obj):
            if name.startswith('_'):
                continue
            value = getattr(config_obj, name)
            if callable(value):
                continue
            try:
                data[name] = copy.deepcopy(value)
            except Exception:
                data[name] = value
        return SimpleNamespace(**data)

    def _apply_atr_filter(self, cfg, valid_frame: pd.DataFrame, x_index: pd.Index,
                          signals: np.ndarray, atr_threshold: float,
                          train_frame: pd.DataFrame) -> np.ndarray:
        if len(signals) == 0:
            return signals

        if not getattr(cfg, 'USE_ATR_FILTER', False):
            return signals

        if 'ATR' not in valid_frame.columns or 'Close' not in valid_frame.columns:
            return signals

        aligned = valid_frame.loc[x_index]
        atr_pct = aligned['ATR'] / (aligned['Close'].abs() + 1e-10)

        if 'ATR' in train_frame.columns and 'Close' in train_frame.columns:
            train_atr_pct = (train_frame['ATR'] / (train_frame['Close'].abs() + 1e-10)).replace([np.inf, -np.inf], np.nan).dropna()
            base_level = float(train_atr_pct.median()) if len(train_atr_pct) > 0 else float(atr_pct.median())
        else:
            base_level = float(atr_pct.median())

        if not np.isfinite(base_level) or base_level <= 0:
            return signals

        volatility_gate = atr_pct >= (base_level * atr_threshold)
        filtered = signals.copy()
        for idx in range(len(filtered)):
            if filtered[idx] != 1 and not bool(volatility_gate.iloc[idx]):
                filtered[idx] = 1
        return filtered

    def _evaluate_single_validation(self, cfg, model_trainer, backtester, train_data,
                                    valid_data, selected_features, symbol,
                                    confidence_threshold, atr_threshold,
                                    stop_loss, take_profit):
        X_valid = self._build_X(valid_data, selected_features)
        if len(X_valid) == 0:
            return -np.inf

        signals = model_trainer.predict_signals(
            X_valid,
            confidence_threshold=confidence_threshold
        )
        signals = self._apply_atr_filter(
            cfg, valid_data, X_valid.index, signals, atr_threshold, train_data
        )

        bt_data = valid_data.loc[X_valid.index]
        results = backtester.backtest(
            bt_data, signals, symbol,
            model_type="optuna_trial",
            stop_loss=stop_loss, take_profit=take_profit
        )

        sharpe = results.sharpe_ratio if np.isfinite(results.sharpe_ratio) else -np.inf
        if not np.isfinite(sharpe):
            return -np.inf

        # Light regularization to discourage near-zero trading activity.
        trade_penalty = 0.0
        if results.num_trades < 5:
            trade_penalty = (5 - results.num_trades) * 0.05

        w_return = float(getattr(cfg, 'OPTUNA_WEIGHT_RETURN', 0.04))
        w_outperf = float(getattr(cfg, 'OPTUNA_WEIGHT_OUTPERFORMANCE', 0.03))
        single_score = (
            sharpe
            + w_return * float(results.total_return_pct)
            + w_outperf * float(results.outperformance_pct)
            - trade_penalty
        )
        return single_score

    def _evaluate_robust_windows(self, cfg, model_trainer, backtester, train_data,
                                 valid_data, selected_features, symbol,
                                 confidence_threshold, atr_threshold,
                                 stop_loss, take_profit):
        """
        Score one trial on multiple disjoint validation windows.
        This reduces sensitivity to one lucky validation segment.
        """
        X_valid = self._build_X(valid_data, selected_features)
        if len(X_valid) == 0:
            return -np.inf

        requested_windows = int(getattr(cfg, 'OPTUNA_VALID_WINDOWS', 5))
        min_window_samples = int(getattr(cfg, 'OPTUNA_MIN_WINDOW_SAMPLES', 120))

        max_windows_by_size = max(1, len(X_valid) // max(1, min_window_samples))
        n_windows = max(1, min(requested_windows, max_windows_by_size))

        # Use contiguous disjoint windows to sample different market segments.
        split_positions = [pos for pos in np.array_split(np.arange(len(X_valid)), n_windows) if len(pos) > 0]
        if not split_positions:
            return -np.inf

        fold_returns = []
        fold_outperf = []
        fold_sharpes = []
        fold_dds = []
        fold_trades = []

        for pos in split_positions:
            x_idx = X_valid.index[pos]
            x_fold = X_valid.loc[x_idx]
            if len(x_fold) == 0:
                continue

            signals = model_trainer.predict_signals(
                x_fold,
                confidence_threshold=confidence_threshold
            )
            signals = self._apply_atr_filter(
                cfg, valid_data, x_idx, signals, atr_threshold, train_data
            )

            bt_data = valid_data.loc[x_idx]
            results = backtester.backtest(
                bt_data, signals, symbol,
                model_type="optuna_trial_window",
                stop_loss=stop_loss, take_profit=take_profit
            )

            fold_returns.append(float(results.total_return_pct))
            fold_outperf.append(float(results.outperformance_pct))
            fold_sharpes.append(float(results.sharpe_ratio) if np.isfinite(results.sharpe_ratio) else 0.0)
            fold_dds.append(float(results.max_drawdown))
            fold_trades.append(float(results.num_trades))

        if len(fold_returns) == 0:
            return -np.inf

        returns = np.array(fold_returns, dtype=float)
        outperf = np.array(fold_outperf, dtype=float)
        sharpes = np.array(fold_sharpes, dtype=float)
        dds = np.array(fold_dds, dtype=float)
        trades = np.array(fold_trades, dtype=float)

        median_return = float(np.median(returns))
        median_outperf = float(np.median(outperf))
        median_sharpe = float(np.median(sharpes))
        return_std = float(np.std(returns))
        worst_dd = float(np.max(dds))
        active_ratio = float(np.mean(trades > 0))
        total_trades = float(np.sum(trades))

        # Weights are in native metric units (return and DD in percentage points).
        w_sharpe = float(getattr(cfg, 'OPTUNA_WEIGHT_SHARPE', 1.0))
        w_return = float(getattr(cfg, 'OPTUNA_WEIGHT_RETURN', 0.04))
        w_outperf = float(getattr(cfg, 'OPTUNA_WEIGHT_OUTPERFORMANCE', 0.03))
        w_dd = float(getattr(cfg, 'OPTUNA_WEIGHT_DRAWDOWN', 0.02))
        w_stability = float(getattr(cfg, 'OPTUNA_WEIGHT_STABILITY', 0.03))
        w_activity = float(getattr(cfg, 'OPTUNA_WEIGHT_ACTIVITY', 0.5))

        score = (
            w_sharpe * median_sharpe
            + w_return * median_return
            + w_outperf * median_outperf
            - w_dd * worst_dd
            - w_stability * return_std
            + w_activity * active_ratio
        )

        min_total_trades = float(getattr(cfg, 'OPTUNA_MIN_TOTAL_TRADES', max(6, len(split_positions) * 2)))
        min_active_ratio = float(getattr(cfg, 'OPTUNA_MIN_ACTIVE_RATIO', 0.40))
        if total_trades < min_total_trades:
            score -= (min_total_trades - total_trades) * 0.05
        if active_ratio < min_active_ratio:
            score -= (min_active_ratio - active_ratio) * 1.0

        return score

    def _objective(self, trial, train_data, valid_data, symbol):
        """Objective function for Optuna."""
        try:
            stop_loss = trial.suggest_float('stop_loss', 0.02, 0.10, step=0.01)
            take_profit = trial.suggest_float('take_profit', 0.05, 0.30, step=0.05)
            confidence_threshold = trial.suggest_float('confidence_threshold', 0.40, 0.80, step=0.05)
            buy_threshold = trial.suggest_float('buy_threshold', 0.80, 0.98, step=0.02)
            sell_threshold = trial.suggest_float('sell_threshold', 0.02, 0.20, step=0.02)
            atr_threshold = trial.suggest_float('atr_threshold', 0.50, 2.00, step=0.10)

            if sell_threshold >= buy_threshold:
                return -np.inf

            # Trial-local config/model/backtester to allow safe parallel Optuna workers.
            trial_cfg = self._clone_config_namespace(self.config)
            trial_cfg.BUY_THRESHOLD = buy_threshold
            trial_cfg.SELL_THRESHOLD = sell_threshold
            trial_cfg.CONFIDENCE_THRESHOLD = confidence_threshold
            trial_cfg.ATR_THRESHOLD = atr_threshold
            trial_cfg.STOP_LOSS = stop_loss
            trial_cfg.TAKE_PROFIT = take_profit
            trial_cfg.USE_ATR_FILTER = getattr(self.config, 'USE_ATR_FILTER', False)

            # Optional model-level hyperparameter tuning.
            tune_model_params = bool(getattr(trial_cfg, 'OPTUNA_TUNE_MODEL_PARAMS', True))
            model_type = str(getattr(trial_cfg, 'MODEL_TYPE', 'lgbm')).lower()
            if tune_model_params and model_type == 'lgbm':
                lgbm_params = copy.deepcopy(getattr(trial_cfg, 'LGBM_PARAMS', {}) or {})
                lgbm_params.update({
                    'n_estimators': trial.suggest_int('lgbm_n_estimators', 150, 700, step=50),
                    'learning_rate': trial.suggest_float('lgbm_learning_rate', 0.01, 0.15, log=True),
                    'num_leaves': trial.suggest_int('lgbm_num_leaves', 16, 128, step=8),
                    'max_depth': trial.suggest_int('lgbm_max_depth', 3, 12),
                    'min_data_in_leaf': trial.suggest_int('lgbm_min_data_in_leaf', 10, 80, step=5),
                    'feature_fraction': trial.suggest_float('lgbm_feature_fraction', 0.60, 1.00, step=0.05),
                    'bagging_fraction': trial.suggest_float('lgbm_bagging_fraction', 0.60, 1.00, step=0.05),
                    'bagging_freq': trial.suggest_int('lgbm_bagging_freq', 1, 10),
                    'lambda_l1': trial.suggest_float('lgbm_lambda_l1', 1e-3, 10.0, log=True),
                    'lambda_l2': trial.suggest_float('lgbm_lambda_l2', 1e-3, 10.0, log=True),
                })
                lgbm_params['objective'] = 'multiclass'
                lgbm_params['num_class'] = 3
                trial_cfg.LGBM_PARAMS = lgbm_params
            elif tune_model_params and model_type == 'xgboost':
                xgb_params = copy.deepcopy(getattr(trial_cfg, 'XGB_PARAMS', {}) or {})
                xgb_params.update({
                    'n_estimators': trial.suggest_int('xgb_n_estimators', 150, 700, step=50),
                    'learning_rate': trial.suggest_float('xgb_learning_rate', 0.01, 0.15, log=True),
                    'max_depth': trial.suggest_int('xgb_max_depth', 3, 12),
                    'subsample': trial.suggest_float('xgb_subsample', 0.60, 1.00, step=0.05),
                    'colsample_bytree': trial.suggest_float('xgb_colsample_bytree', 0.60, 1.00, step=0.05),
                    'min_child_weight': trial.suggest_float('xgb_min_child_weight', 1.0, 15.0),
                    'gamma': trial.suggest_float('xgb_gamma', 0.0, 2.0),
                    'reg_alpha': trial.suggest_float('xgb_reg_alpha', 1e-3, 10.0, log=True),
                    'reg_lambda': trial.suggest_float('xgb_reg_lambda', 1e-3, 10.0, log=True),
                })
                xgb_params['objective'] = 'multi:softprob'
                xgb_params['num_class'] = 3
                xgb_params['eval_metric'] = 'mlogloss'
                trial_cfg.XGB_PARAMS = xgb_params

            trial_model_trainer = self.model_trainer.__class__(trial_cfg)
            trial_backtester = self.backtester.__class__(trial_cfg)

            # Recreate training targets/features with current thresholds, then retrain
            X_train, y_train, selected_features = trial_model_trainer.prepare_data(train_data, symbol)
            if len(X_train) == 0:
                return -np.inf

            trial_model_trainer.train(X_train, y_train, symbol)
            objective_mode = str(getattr(trial_cfg, 'OPTUNA_OBJECTIVE_MODE', 'robust_windows')).lower()
            if objective_mode == 'single_split':
                return self._evaluate_single_validation(
                    trial_cfg, trial_model_trainer, trial_backtester, train_data, valid_data,
                    selected_features, symbol, confidence_threshold, atr_threshold,
                    stop_loss, take_profit
                )
            return self._evaluate_robust_windows(
                trial_cfg, trial_model_trainer, trial_backtester, train_data, valid_data,
                selected_features, symbol, confidence_threshold, atr_threshold,
                stop_loss, take_profit
            )

        except Exception as e:
            logger.warning(f"Trial failed: {str(e)}")
            return -np.inf

    def save_best_params(self, symbol: str, output_dir: str = None):
        """Save best parameters to JSON."""
        if output_dir is None:
            output_dir = self.config.RESULTS_DIR
        path = os.path.join(output_dir, f'{symbol}_best_params.json')
        with open(path, 'w') as f:
            json.dump({
                'symbol': symbol,
                'timestamp': datetime.now().isoformat(),
                'best_params': self.best_params,
                'best_score': float(self.best_score)
            }, f, indent=2)
        logger.info(f"Best parameters saved to {path}")


class WalkForwardValidator:
    """
    Walk-forward validation to prevent overfitting.
    Trains on historical data, tests on future data, rolls forward.
    """

    def __init__(self, config, model_trainer, backtester):
        self.config = config
        self.model_trainer = model_trainer
        self.backtester = backtester
        self.results = []
        logger.info("WalkForwardValidator initialized")

    def _apply_atr_filter(self, valid_frame: pd.DataFrame, x_index: pd.Index,
                          signals: np.ndarray, atr_threshold: float,
                          train_frame: pd.DataFrame) -> np.ndarray:
        """Apply the same ATR gating used during hyperparameter optimization."""
        if len(signals) == 0:
            return signals

        if not getattr(self.config, 'USE_ATR_FILTER', False):
            return signals

        if 'ATR' not in valid_frame.columns or 'Close' not in valid_frame.columns:
            return signals

        aligned = valid_frame.loc[x_index]
        atr_pct = aligned['ATR'] / (aligned['Close'].abs() + 1e-10)

        if 'ATR' in train_frame.columns and 'Close' in train_frame.columns:
            train_atr_pct = (train_frame['ATR'] / (train_frame['Close'].abs() + 1e-10)).replace([np.inf, -np.inf], np.nan).dropna()
            base_level = float(train_atr_pct.median()) if len(train_atr_pct) > 0 else float(atr_pct.median())
        else:
            base_level = float(atr_pct.median())

        if not np.isfinite(base_level) or base_level <= 0:
            return signals

        volatility_gate = atr_pct >= (base_level * atr_threshold)
        filtered = signals.copy()
        for idx in range(len(filtered)):
            if filtered[idx] != 1 and not bool(volatility_gate.iloc[idx]):
                filtered[idx] = 1
        return filtered

    def validate(self, data: pd.DataFrame, feature_engineer, symbol: str,
                 train_size: int = 2000, test_size: int = 500,
                 step_size: int = 250) -> Dict:
        """
        Run walk-forward validation.

        Args:
            data: Full OHLCV dataset WITH features already engineered
            feature_engineer: FeatureEngineer instance (for feature list)
            symbol: Trading symbol
            train_size: Training window size
            test_size: Testing window size
            step_size: Roll-forward step

        Returns:
            Dict with validation results
        """
        logger.info(f"Walk-forward validation for {symbol}...")
        logger.info(f"  Train: {train_size}, Test: {test_size}, Step: {step_size}")

        results = []
        total = len(data)

        for start in range(0, total - train_size - test_size, step_size):
            train_end = start + train_size
            test_end = train_end + test_size

            if test_end > total:
                break

            window_num = len(results) + 1
            logger.info(f"  Window {window_num}: Train [{start}:{train_end}], Test [{train_end}:{test_end}]")

            try:
                train_data = data.iloc[start:train_end]
                test_data_window = data.iloc[train_end:test_end]

                # Prepare training data
                X_train, y_train, features = self.model_trainer.prepare_data(train_data, symbol)
                self.model_trainer.train(X_train, y_train, symbol)

                # Prepare test data (use same features)
                X_test = test_data_window[[c for c in features if c in test_data_window.columns]]
                X_test = X_test.dropna()

                if len(X_test) == 0:
                    continue

                # Generate signals
                confidence_threshold = float(getattr(self.config, 'CONFIDENCE_THRESHOLD', 0.50))
                atr_threshold = float(getattr(self.config, 'ATR_THRESHOLD', 1.0))
                stop_loss = float(getattr(self.config, 'STOP_LOSS', 0.05))
                take_profit = float(getattr(self.config, 'TAKE_PROFIT', 0.10))

                signals = self.model_trainer.predict_signals(
                    X_test,
                    confidence_threshold=confidence_threshold
                )
                signals = self._apply_atr_filter(
                    test_data_window, X_test.index, signals, atr_threshold, train_data
                )

                # Backtest
                bt_data = test_data_window.loc[X_test.index]
                bt_results = self.backtester.backtest(
                    bt_data,
                    signals,
                    symbol,
                    model_type="walk_forward",
                    stop_loss=stop_loss,
                    take_profit=take_profit
                )

                results.append({
                    'window': window_num,
                    'train_period': f"{start}-{train_end}",
                    'test_period': f"{train_end}-{test_end}",
                    'return': bt_results.total_return_pct,
                    'sharpe': bt_results.sharpe_ratio,
                    'max_dd': bt_results.max_drawdown,
                    'trades': bt_results.num_trades,
                    'win_rate': bt_results.win_rate
                })

            except Exception as e:
                logger.warning(f"  Window {window_num} failed: {str(e)}")
                continue

        self.results = results

        if results:
            avg_return = np.mean([r['return'] for r in results])
            avg_sharpe = np.mean([r['sharpe'] for r in results])
            avg_dd = np.mean([r['max_dd'] for r in results])
            logger.info(f"  Avg Return={avg_return:.2f}%, Avg Sharpe={avg_sharpe:.4f}, Avg DD={avg_dd:.2f}%")

        return {
            'windows': results,
            'average_return': np.mean([r['return'] for r in results]) if results else 0,
            'average_sharpe': np.mean([r['sharpe'] for r in results]) if results else 0,
            'average_max_dd': np.mean([r['max_dd'] for r in results]) if results else 0
        }

    def save_results(self, symbol: str, output_dir: str = None):
        """Save walk-forward results to CSV."""
        if output_dir is None:
            output_dir = self.config.RESULTS_DIR
        if not self.results:
            return
        path = os.path.join(output_dir, f'{symbol}_walk_forward_results.csv')
        pd.DataFrame(self.results).to_csv(path, index=False)
        logger.info(f"Walk-forward results saved to {path}")
