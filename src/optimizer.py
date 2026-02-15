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
from typing import Dict, Tuple
from datetime import datetime

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
                 symbol: str, n_trials: int = 50) -> Dict:
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

        logger.info(f"Starting optimization for {symbol} ({n_trials} trials)...")

        sampler = TPESampler(seed=42)
        pruner = MedianPruner()
        study = optuna.create_study(direction='maximize', sampler=sampler, pruner=pruner)

        # Keep a copy of baseline config values and restore after optimization
        baseline_cfg = {
            'BUY_THRESHOLD': getattr(self.config, 'BUY_THRESHOLD', 0.90),
            'SELL_THRESHOLD': getattr(self.config, 'SELL_THRESHOLD', 0.10),
            'CONFIDENCE_THRESHOLD': getattr(self.config, 'CONFIDENCE_THRESHOLD', 0.50),
            'ATR_THRESHOLD': getattr(self.config, 'ATR_THRESHOLD', 1.0),
            'USE_ATR_FILTER': getattr(self.config, 'USE_ATR_FILTER', False),
            'STOP_LOSS': getattr(self.config, 'STOP_LOSS', 0.05),
            'TAKE_PROFIT': getattr(self.config, 'TAKE_PROFIT', 0.10),
        }

        study.optimize(
            lambda trial: self._objective(trial, train_data, valid_data, symbol),
            n_trials=n_trials, show_progress_bar=True
        )

        for key, value in baseline_cfg.items():
            setattr(self.config, key, value)

        self.best_params = study.best_params
        self.best_score = study.best_value

        logger.info(f"Best Sharpe: {self.best_score:.4f}")
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

    def _apply_atr_filter(self, valid_frame: pd.DataFrame, x_index: pd.Index,
                          signals: np.ndarray, atr_threshold: float,
                          train_frame: pd.DataFrame) -> np.ndarray:
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

            self.config.BUY_THRESHOLD = buy_threshold
            self.config.SELL_THRESHOLD = sell_threshold
            self.config.CONFIDENCE_THRESHOLD = confidence_threshold
            self.config.ATR_THRESHOLD = atr_threshold

            # Recreate training targets/features with current thresholds, then retrain
            X_train, y_train, selected_features = self.model_trainer.prepare_data(train_data, symbol)
            if len(X_train) == 0:
                return -np.inf

            self.model_trainer.train(X_train, y_train, symbol)

            X_valid = self._build_X(valid_data, selected_features)
            if len(X_valid) == 0:
                return -np.inf

            signals = self.model_trainer.predict_signals(
                X_valid,
                confidence_threshold=confidence_threshold
            )

            signals = self._apply_atr_filter(valid_data, X_valid.index, signals, atr_threshold, train_data)

            bt_data = valid_data.loc[X_valid.index]

            # Backtest with these parameters (using the correct API)
            results = self.backtester.backtest(
                bt_data, signals, symbol,
                model_type="optuna_trial",
                stop_loss=stop_loss, take_profit=take_profit
            )

            sharpe = results.sharpe_ratio if np.isfinite(results.sharpe_ratio) else -np.inf
            if not np.isfinite(sharpe):
                return -np.inf

            # Light regularization to discourage near-zero trading activity
            trade_penalty = 0.0
            if results.num_trades < 5:
                trade_penalty = (5 - results.num_trades) * 0.05

            return sharpe - trade_penalty

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
                exclude_cols = ['Open', 'High', 'Low', 'Close', 'Volume', 'Returns', 'Log_Returns', 'Target']
                X_test = test_data_window[[c for c in features if c in test_data_window.columns]]
                X_test = X_test.dropna()

                if len(X_test) == 0:
                    continue

                # Generate signals
                signals = self.model_trainer.predict_signals(X_test)

                # Backtest
                bt_data = test_data_window.loc[X_test.index]
                bt_results = self.backtester.backtest(bt_data, signals, symbol, model_type="walk_forward")

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
