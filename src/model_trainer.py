"""
Model Training Module
Supports multiple ML models for multi-class signal prediction.
Includes proper train/test split, feature selection, and class imbalance handling.
"""

import pandas as pd
import numpy as np
import logging
import pickle
import os
from typing import Tuple, List, Dict, Optional
from sklearn.preprocessing import StandardScaler
from sklearn.feature_selection import RFE
from sklearn.model_selection import cross_val_score, TimeSeriesSplit
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.neural_network import MLPClassifier
try:
    import lightgbm as lgb
except Exception:
    lgb = None
try:
    import xgboost as xgb
except ImportError:
    xgb = None
try:
    import catboost as cb
except ImportError:
    cb = None
from imblearn.over_sampling import SMOTE

logger = logging.getLogger(__name__)


SUPPORTED_MODEL_TYPES = [
    'lgbm',
    'xgboost',
    'catboost',
    'hist_gradient_boosting',
    'extra_trees',
    'random_forest',
    'logistic_regression',
    'neural_network',
]

MODEL_TYPE_ALIASES = {
    'lightgbm': 'lgbm',
    'lgb': 'lgbm',
    'xgb': 'xgboost',
    'cat': 'catboost',
    'hgb': 'hist_gradient_boosting',
    'hist_gbm': 'hist_gradient_boosting',
    'histgb': 'hist_gradient_boosting',
    'extratrees': 'extra_trees',
    'et': 'extra_trees',
    'rf': 'random_forest',
    'randomforest': 'random_forest',
    'logreg': 'logistic_regression',
    'lr': 'logistic_regression',
    'mlp': 'neural_network',
    'nn': 'neural_network',
    'neural': 'neural_network',
}


def normalize_model_type(model_type: str) -> str:
    """Normalize model aliases to canonical internal names."""
    if model_type is None:
        return 'lgbm'
    raw = str(model_type).strip().lower()
    if not raw:
        return 'lgbm'
    return MODEL_TYPE_ALIASES.get(raw, raw)


def set_global_seed(seed: int = 42):
    """Set random seed for all libraries to ensure reproducibility."""
    import random
    random.seed(seed)
    np.random.seed(seed)
    os.environ['PYTHONHASHSEED'] = str(seed)
    try:
        import torch
        torch.manual_seed(seed)
    except ImportError:
        pass


class TargetCreator:
    """Creates trading targets for supervised learning."""

    def __init__(self, config):
        self.config = config
        logger.info("TargetCreator initialized")

    def create_targets(self, data: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        Create multi-class targets (0=Sell, 1=Hold, 2=Buy) based on FUTURE returns.
        Uses forward-looking returns to properly label what the model should predict.
        """
        method = str(getattr(self.config, 'TARGET_METHOD', 'percentile')).lower()
        if method == 'triple_barrier':
            labeled = self._create_targets_triple_barrier(data, symbol)
        elif method == 'tradable_payoff':
            labeled = self._create_targets_tradable_payoff(data, symbol)
        else:
            labeled = self._create_targets_percentile(data, symbol)

        # Log class distribution
        class_dist = labeled['Target'].value_counts().sort_index()
        logger.info(
            f"{symbol} - Target distribution: "
            f"Sell={class_dist.get(0, 0)}, Hold={class_dist.get(1, 0)}, Buy={class_dist.get(2, 0)}"
        )

        return labeled

    def _create_targets_percentile(self, data: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Legacy percentile-based target (kept for A/B comparison)."""
        data = data.copy()
        horizon = max(1, int(getattr(self.config, 'TARGET_HORIZON_BARS', 5)))

        # Calculate future return over a configurable horizon.
        future_return = data['Close'].pct_change(periods=horizon).shift(-horizon)

        # Use rolling percentile to create adaptive thresholds.
        min_periods = max(50, horizon * 2)
        rolling_percentile = future_return.rolling(
            window=self.config.TARGET_WINDOW, min_periods=min_periods
        ).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1] if len(x) > 1 else np.nan, raw=False)

        # Create target labels.
        data['Target'] = 1

        buy_condition = (rolling_percentile >= self.config.BUY_THRESHOLD)
        data.loc[buy_condition, 'Target'] = 2

        sell_condition = (rolling_percentile <= self.config.SELL_THRESHOLD)
        data.loc[sell_condition, 'Target'] = 0

        # Remove rows that rely on unavailable future bars.
        if len(data) > horizon:
            data = data.iloc[:-horizon]
        else:
            data = data.iloc[0:0]

        return data

    def _create_targets_triple_barrier(self, data: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        Triple-barrier labeling:
        - Upper barrier (Buy) and lower barrier (Sell) scaled by volatility.
        - Time barrier at TARGET_HORIZON_BARS.
        - If neither barrier is hit, fallback to terminal return with neutral band.
        """
        data = data.copy()
        n = len(data)
        horizon = max(1, int(getattr(self.config, 'TARGET_HORIZON_BARS', 12)))
        tp_mult = float(getattr(self.config, 'TARGET_TP_ATR_MULT', 2.0))
        sl_mult = float(getattr(self.config, 'TARGET_SL_ATR_MULT', 1.2))
        neutral_band = float(getattr(self.config, 'TARGET_NEUTRAL_BAND', 0.0015))
        min_atr_pct = float(getattr(self.config, 'TARGET_MIN_ATR_PCT', 0.002))

        if n <= horizon:
            data['Target'] = 1
            return data.iloc[0:0]

        close = data['Close'].to_numpy(dtype=float)
        high = data['High'].to_numpy(dtype=float)
        low = data['Low'].to_numpy(dtype=float)

        if 'ATR' in data.columns:
            atr_pct = (data['ATR'].to_numpy(dtype=float) / (np.abs(close) + 1e-10))
        else:
            # Fallback if ATR is missing.
            atr_pct = data['Log_Returns'].rolling(window=20).std().to_numpy(dtype=float)

        finite_vol = atr_pct[np.isfinite(atr_pct) & (atr_pct > 0)]
        default_vol = float(np.median(finite_vol)) if len(finite_vol) > 0 else min_atr_pct
        labels = np.ones(n, dtype=int)

        for i in range(n - horizon):
            entry = close[i]
            if not np.isfinite(entry) or entry <= 0:
                labels[i] = 1
                continue

            vol = atr_pct[i] if np.isfinite(atr_pct[i]) and atr_pct[i] > 0 else default_vol
            vol = max(vol, min_atr_pct)
            up_barrier = tp_mult * vol
            dn_barrier = sl_mult * vol
            label = 1

            end = min(n - 1, i + horizon)
            for j in range(i + 1, end + 1):
                up_ret = (high[j] - entry) / entry
                dn_ret = (low[j] - entry) / entry
                up_hit = up_ret >= up_barrier
                dn_hit = dn_ret <= -dn_barrier

                if up_hit and not dn_hit:
                    label = 2
                    break
                if dn_hit and not up_hit:
                    label = 0
                    break
                if up_hit and dn_hit:
                    # Ambiguous same-bar touch: resolve with close direction.
                    close_ret = (close[j] - entry) / entry
                    label = 2 if close_ret >= 0 else 0
                    break

            if label == 1:
                terminal_ret = (close[end] - entry) / entry
                if terminal_ret > neutral_band:
                    label = 2
                elif terminal_ret < -neutral_band:
                    label = 0

            labels[i] = label

        data['Target'] = labels
        data = data.iloc[:-horizon]
        return data

    def _create_targets_tradable_payoff(self, data: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        Tradable-aware labeling:
        - Entry at next bar open.
        - Exit by ATR-scaled TP/SL barriers or time horizon.
        - Net return includes fee/slippage proxy.
        """
        data = data.copy()
        n = len(data)

        horizon = max(1, int(getattr(self.config, 'TARGET_HORIZON_BARS', 12)))
        tp_mult = float(getattr(self.config, 'TARGET_TP_ATR_MULT', 2.0))
        sl_mult = float(getattr(self.config, 'TARGET_SL_ATR_MULT', 1.2))
        min_atr_pct = float(getattr(self.config, 'TARGET_MIN_ATR_PCT', 0.002))
        buy_thr = float(getattr(self.config, 'TARGET_NET_BUY_THRESHOLD', 0.004))
        sell_thr = float(getattr(self.config, 'TARGET_NET_SELL_THRESHOLD', -0.004))
        fee = float(getattr(self.config, 'TRADING_FEE', 0.001))
        slippage = float(getattr(self.config, 'SLIPPAGE', 0.0005))
        roundtrip_cost = 2.0 * (fee + slippage)

        if n <= (horizon + 1):
            data['Target'] = 1
            return data.iloc[0:0]

        open_ = data['Open'].to_numpy(dtype=float)
        close = data['Close'].to_numpy(dtype=float)
        high = data['High'].to_numpy(dtype=float)
        low = data['Low'].to_numpy(dtype=float)

        if 'ATR' in data.columns:
            atr_pct = (data['ATR'].to_numpy(dtype=float) / (np.abs(close) + 1e-10))
        else:
            atr_pct = data['Log_Returns'].rolling(window=20).std().to_numpy(dtype=float)

        finite_vol = atr_pct[np.isfinite(atr_pct) & (atr_pct > 0)]
        default_vol = float(np.median(finite_vol)) if len(finite_vol) > 0 else min_atr_pct
        labels = np.ones(n, dtype=int)

        for i in range(n - horizon - 1):
            entry = open_[i + 1]
            if not np.isfinite(entry) or entry <= 0:
                labels[i] = 1
                continue

            vol = atr_pct[i] if np.isfinite(atr_pct[i]) and atr_pct[i] > 0 else default_vol
            vol = max(vol, min_atr_pct)
            up_ret = tp_mult * vol
            dn_ret = sl_mult * vol

            end = min(n - 1, i + horizon)
            exit_price = close[end]
            for j in range(i + 1, end + 1):
                up_hit = high[j] >= entry * (1.0 + up_ret)
                dn_hit = low[j] <= entry * (1.0 - dn_ret)
                if up_hit and not dn_hit:
                    exit_price = entry * (1.0 + up_ret)
                    break
                if dn_hit and not up_hit:
                    exit_price = entry * (1.0 - dn_ret)
                    break
                if up_hit and dn_hit:
                    exit_price = entry * (1.0 + up_ret) if close[j] >= entry else entry * (1.0 - dn_ret)
                    break

            gross_ret = (exit_price - entry) / entry
            net_ret = gross_ret - roundtrip_cost
            if net_ret >= buy_thr:
                labels[i] = 2
            elif net_ret <= sell_thr:
                labels[i] = 0
            else:
                labels[i] = 1

        data['Target'] = labels
        data = data.iloc[: n - horizon - 1]
        return data


class FeatureSelector:
    """Selects the most important features to prevent overfitting."""

    def __init__(self, config):
        self.config = config
        self.selected_features = None
        logger.info("FeatureSelector initialized")

    def select_features(self, X: pd.DataFrame, y: pd.Series, method: str = None) -> List[str]:
        if method is None:
            method = self.config.FEATURE_SELECTION_METHOD

        logger.info(f"Selecting features using {method} method...")

        if method == "rfe":
            selected = self._rfe_selection(X, y)
        elif method == "importance":
            selected = self._importance_selection(X, y)
        elif method == "correlation":
            selected = self._correlation_selection(X, y)
        else:
            logger.warning(f"Unknown method {method}, using all features")
            selected = X.columns.tolist()

        self.selected_features = selected
        logger.info(f"Selected {len(selected)} features: {selected[:5]}...")
        return selected

    def _rfe_selection(self, X: pd.DataFrame, y: pd.Series) -> List[str]:
        seed = getattr(self.config, 'RANDOM_SEED', 42)
        if lgb is None:
            model = RandomForestClassifier(n_estimators=200, random_state=seed, n_jobs=-1)
        else:
            model = lgb.LGBMClassifier(n_estimators=100, random_state=seed, verbose=-1)
        n_select = min(self.config.N_FEATURES_TO_SELECT, X.shape[1])
        rfe = RFE(estimator=model, n_features_to_select=n_select, step=1)
        rfe.fit(X, y)
        return X.columns[rfe.support_].tolist()

    def _importance_selection(self, X: pd.DataFrame, y: pd.Series) -> List[str]:
        seed = getattr(self.config, 'RANDOM_SEED', 42)
        if lgb is None:
            model = RandomForestClassifier(n_estimators=200, random_state=seed, n_jobs=-1)
        else:
            model = lgb.LGBMClassifier(n_estimators=100, random_state=seed, verbose=-1)
        model.fit(X, y)
        importance = pd.DataFrame({
            'feature': X.columns,
            'importance': model.feature_importances_
        }).sort_values('importance', ascending=False)
        n_select = min(self.config.N_FEATURES_TO_SELECT, len(importance))
        return importance.head(n_select)['feature'].tolist()

    def _correlation_selection(self, X: pd.DataFrame, y: pd.Series) -> List[str]:
        correlations = pd.DataFrame({
            'feature': X.columns,
            'correlation': [abs(X[col].corr(y)) for col in X.columns]
        }).sort_values('correlation', ascending=False)
        n_select = min(self.config.N_FEATURES_TO_SELECT, len(correlations))
        return correlations.head(n_select)['feature'].tolist()


class ModelTrainer:
    """
    Trains ML models with feature selection and class imbalance handling.
    Supports: lgbm, xgboost, catboost, hist_gradient_boosting, extra_trees,
              random_forest, logistic_regression, neural_network
    """

    def __init__(self, config):
        self.config = config
        self.seed = getattr(config, 'RANDOM_SEED', 42)
        self.model = None
        self.entry_model = None
        self.direction_model = None
        self.entry_threshold_base = None
        self.direction_threshold_base = None
        self.scaler = StandardScaler()
        self.feature_selector = FeatureSelector(config)
        self.target_creator = TargetCreator(config)
        self.model_type = normalize_model_type(getattr(config, 'MODEL_TYPE', 'lgbm'))
        self.signal_decision_mode = str(getattr(config, 'SIGNAL_DECISION_MODE', 'legacy')).lower()
        # Set global seed for reproducibility
        set_global_seed(self.seed)
        logger.info(f"ModelTrainer initialized (model_type={self.model_type}, seed={self.seed})")

    def prepare_data(self, data: pd.DataFrame, symbol: str) -> Tuple[pd.DataFrame, pd.Series, List[str]]:
        """
        Prepare data for training: create targets, select features.
        Returns aligned X, y, and feature list.
        """
        # Create targets (uses future returns)
        data = self.target_creator.create_targets(data, symbol)

        # Separate features and target
        exclude_cols = ['Open', 'High', 'Low', 'Close', 'Volume', 'Returns', 'Log_Returns', 'Target']
        feature_cols = [col for col in data.columns if col not in exclude_cols]
        X = data[feature_cols]
        y = data['Target'].astype(int)

        # Remove rows with NaN features
        mask = X.notna().all(axis=1)
        X = X[mask]
        y = y[mask]

        if len(X) == 0:
            raise ValueError(f"{symbol}: No valid rows after feature NaN filtering")

        # Select features
        selected_features = self.feature_selector.select_features(X, y)
        if not selected_features:
            logger.warning("Feature selection returned empty set, falling back to all features")
            selected_features = X.columns.tolist()
        X = X[selected_features]

        logger.info(f"Data prepared: X shape {X.shape}, y shape {y.shape}")
        return X, y, selected_features

    def handle_class_imbalance(self, X: pd.DataFrame, y: pd.Series) -> Tuple[pd.DataFrame, pd.Series]:
        """Handle class imbalance using SMOTE."""
        if not self.config.USE_SMOTE:
            return X, y

        logger.info("Applying SMOTE for class imbalance...")
        class_counts = y.value_counts()
        if class_counts.empty or class_counts.min() < 2:
            logger.warning("SMOTE skipped: not enough minority samples")
            return X, y

        majority_count = class_counts.max()

        sampling_strategy = {}
        for class_label in class_counts.index:
            if class_counts[class_label] < majority_count:
                sampling_strategy[class_label] = majority_count

        if len(sampling_strategy) > 0:
            min_class_count = int(class_counts.min())
            k_neighbors = max(1, min(3, min_class_count - 1))
            smote = SMOTE(sampling_strategy=sampling_strategy, random_state=self.seed, k_neighbors=k_neighbors)
            X_balanced, y_balanced = smote.fit_resample(X, y)
        else:
            X_balanced, y_balanced = X, y

        logger.info(f"After SMOTE: {len(X_balanced)} samples")
        return pd.DataFrame(X_balanced, columns=X.columns), pd.Series(y_balanced)

    def train(self, X: pd.DataFrame, y: pd.Series, symbol: str = "Unknown",
              model_type: str = None) -> object:
        """
        Train a model of the specified type.

        Args:
            X: Feature matrix
            y: Target vector
            symbol: Trading symbol
            model_type: Override model type (default: self.model_type from config)

        Returns:
            Trained model
        """
        if model_type is not None:
            self.model_type = normalize_model_type(model_type)
        else:
            self.model_type = normalize_model_type(self.model_type)

        # Reset seed before each training for reproducibility
        set_global_seed(self.seed)

        logger.info(f"Training {self.model_type.upper()} model for {symbol}...")

        # Scale features FIRST on original data (so test data uses same scale)
        X_scaled_orig = pd.DataFrame(
            self.scaler.fit_transform(X),
            columns=X.columns
        )

        # Handle class imbalance AFTER scaling
        X_balanced, y_balanced = self.handle_class_imbalance(X_scaled_orig, y)

        X_scaled = X_balanced  # Already scaled

        # Train the appropriate model
        if self.model_type == 'lgbm':
            self.model = self._train_lgbm(X_scaled, y_balanced)
        elif self.model_type == 'xgboost':
            self.model = self._train_xgboost(X_scaled, y_balanced)
        elif self.model_type == 'catboost':
            self.model = self._train_catboost(X_scaled, y_balanced)
        elif self.model_type == 'hist_gradient_boosting':
            self.model = self._train_hist_gradient_boosting(X_scaled, y_balanced)
        elif self.model_type == 'extra_trees':
            self.model = self._train_extra_trees(X_scaled, y_balanced)
        elif self.model_type == 'random_forest':
            self.model = self._train_random_forest(X_scaled, y_balanced)
        elif self.model_type == 'logistic_regression':
            self.model = self._train_logistic_regression(X_scaled, y_balanced)
        elif self.model_type == 'neural_network':
            self.model = self._train_neural_network(X_scaled, y_balanced)
        else:
            logger.warning(f"Unknown model type '{self.model_type}', falling back to lgbm")
            self.model_type = 'lgbm'
            self.model = self._train_lgbm(X_scaled, y_balanced)

        # Time-aware CV score to reduce temporal leakage
        try:
            n_splits = 5 if len(X_scaled) >= 120 else 3
            cv = TimeSeriesSplit(n_splits=n_splits)
            cv_scores = cross_val_score(self.model, X_scaled, y_balanced, cv=cv, scoring='accuracy')
            logger.info(f"CV Accuracy (time-series): {cv_scores.mean():.4f} (+/- {cv_scores.std():.4f})")
        except Exception as e:
            logger.warning(f"CV scoring skipped: {str(e)}")

        if self.signal_decision_mode == 'two_stage':
            self._train_two_stage_heads(X_scaled_orig, y)

        return self.model

    def _train_two_stage_heads(self, X_scaled: pd.DataFrame, y: pd.Series):
        """Train entry and direction heads for two-stage signal decision."""
        self.entry_model = None
        self.direction_model = None
        self.entry_threshold_base = None
        self.direction_threshold_base = None
        y_series = pd.Series(y).astype(int).reset_index(drop=True)
        X_use = X_scaled.reset_index(drop=True)

        y_entry = (y_series != 1).astype(int)
        if y_entry.nunique() >= 2:
            self.entry_model = RandomForestClassifier(
                n_estimators=int(getattr(self.config, 'ENTRY_MODEL_N_ESTIMATORS', 300)),
                max_depth=6,
                min_samples_leaf=20,
                class_weight='balanced_subsample',
                random_state=self.seed,
                n_jobs=-1,
            )
            self.entry_model.fit(X_use, y_entry)
            # Calibrate entry threshold on training distribution only (causal at inference).
            try:
                entry_prob_train = self.entry_model.predict_proba(X_use)[:, 1]
                target_exposure = float(getattr(self.config, 'TARGET_TIME_IN_MARKET', 0.20))
                target_exposure = min(max(target_exposure, 0.01), 0.95)
                q = max(0.0, min(1.0, 1.0 - target_exposure))
                entry_thr = float(np.quantile(entry_prob_train, q))
                entry_thr_min = float(getattr(self.config, 'ENTRY_THRESHOLD_MIN', 0.45))
                entry_thr_max = float(getattr(self.config, 'ENTRY_THRESHOLD_MAX', 0.85))
                self.entry_threshold_base = float(np.clip(entry_thr, entry_thr_min, entry_thr_max))
            except Exception as e:
                logger.warning(f"Entry threshold calibration skipped: {str(e)}")
        else:
            logger.warning("Two-stage entry head skipped: single class in y_entry")

        direction_mask = (y_series != 1)
        if direction_mask.sum() >= 30:
            y_direction = (y_series[direction_mask] == 2).astype(int)
            if y_direction.nunique() >= 2:
                self.direction_model = RandomForestClassifier(
                    n_estimators=int(getattr(self.config, 'DIRECTION_MODEL_N_ESTIMATORS', 300)),
                    max_depth=8,
                    min_samples_leaf=10,
                    class_weight='balanced_subsample',
                    random_state=self.seed,
                    n_jobs=-1,
                )
                self.direction_model.fit(X_use.loc[direction_mask], y_direction)
                # Calibrate buy/sell threshold on training distribution only.
                try:
                    direction_prob_train = self.direction_model.predict_proba(X_use.loc[direction_mask])[:, 1]
                    target_buy_share = float(getattr(self.config, 'TARGET_BUY_SHARE_ON_ENTRY', 0.55))
                    target_buy_share = min(max(target_buy_share, 0.05), 0.95)
                    q = max(0.0, min(1.0, 1.0 - target_buy_share))
                    direction_thr = float(np.quantile(direction_prob_train, q))
                    dir_min = float(getattr(self.config, 'DIRECTION_THRESHOLD_MIN', 0.40))
                    dir_max = float(getattr(self.config, 'DIRECTION_THRESHOLD_MAX', 0.60))
                    self.direction_threshold_base = float(np.clip(direction_thr, dir_min, dir_max))
                except Exception as e:
                    logger.warning(f"Direction threshold calibration skipped: {str(e)}")
            else:
                logger.warning("Two-stage direction head skipped: single class in y_direction")
        else:
            logger.warning("Two-stage direction head skipped: insufficient non-hold samples")

        logger.info(
            "Two-stage calibrated thresholds: entry_base=%s, direction_base=%s",
            "None" if self.entry_threshold_base is None else f"{self.entry_threshold_base:.4f}",
            "None" if self.direction_threshold_base is None else f"{self.direction_threshold_base:.4f}",
        )

    def _train_lgbm(self, X, y):
        if lgb is None:
            raise ImportError(
                "lightgbm is not installed or its runtime dependencies are missing. "
                "Install lightgbm support in your environment to use model_type='lgbm'."
            )
        defaults = {
            'objective': 'multiclass',
            'num_class': 3,
            'n_estimators': 200,
            'learning_rate': 0.05,
            'num_leaves': 31,
            'max_depth': 7,
            'min_data_in_leaf': 20,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'lambda_l1': 1.0,
            'lambda_l2': 1.0,
            'verbose': -1,
            'random_state': self.seed,
        }
        cfg_params = getattr(self.config, 'LGBM_PARAMS', {}) or {}
        params = {**defaults, **cfg_params}
        params['random_state'] = self.seed

        model = lgb.LGBMClassifier(**params)
        model.fit(X, y)
        return model

    def _train_xgboost(self, X, y):
        if xgb is None:
            raise ImportError(
                "xgboost is not installed. Install it in requirements.txt and rebuild the Docker image "
                "if you want to use model_type='xgboost'."
            )
        defaults = {
            'objective': 'multi:softprob',
            'num_class': 3,
            'n_estimators': 300,
            'learning_rate': 0.05,
            'max_depth': 7,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'reg_alpha': 1.0,
            'reg_lambda': 1.0,
            'verbosity': 0,
            'eval_metric': 'mlogloss',
            'random_state': self.seed,
        }
        cfg_params = getattr(self.config, 'XGB_PARAMS', {}) or {}
        params = {**defaults, **cfg_params}
        params['random_state'] = self.seed
        params['objective'] = 'multi:softprob'
        params['num_class'] = 3

        model = xgb.XGBClassifier(**params)
        model.fit(X, y)
        return model

    def _train_catboost(self, X, y):
        if cb is None:
            raise ImportError(
                "catboost is not installed. Install it in requirements.txt and rebuild the Docker image "
                "if you want to use model_type='catboost'."
            )
        defaults = {
            'loss_function': 'MultiClass',
            'iterations': 400,
            'learning_rate': 0.05,
            'depth': 8,
            'l2_leaf_reg': 3.0,
            'random_seed': self.seed,
            'verbose': False,
            'allow_writing_files': False,
            'thread_count': -1,
        }
        cfg_params = getattr(self.config, 'CATBOOST_PARAMS', {}) or {}
        params = {**defaults, **cfg_params}
        params['random_seed'] = self.seed

        model = cb.CatBoostClassifier(**params)
        model.fit(X, y)
        return model

    def _train_hist_gradient_boosting(self, X, y):
        defaults = {
            'loss': 'log_loss',
            'learning_rate': 0.05,
            'max_iter': 300,
            'max_depth': 8,
            'max_leaf_nodes': 63,
            'min_samples_leaf': 20,
            'l2_regularization': 0.5,
            'random_state': self.seed,
        }
        cfg_params = getattr(self.config, 'HGB_PARAMS', {}) or {}
        params = {**defaults, **cfg_params}
        params['random_state'] = self.seed

        model = HistGradientBoostingClassifier(**params)
        model.fit(X, y)
        return model

    def _train_extra_trees(self, X, y):
        defaults = {
            'n_estimators': 500,
            'max_depth': None,
            'min_samples_split': 5,
            'min_samples_leaf': 2,
            'max_features': 'sqrt',
            'class_weight': 'balanced_subsample',
            'random_state': self.seed,
            'n_jobs': -1,
        }
        cfg_params = getattr(self.config, 'EXTRA_TREES_PARAMS', {}) or {}
        params = {**defaults, **cfg_params}
        params['random_state'] = self.seed

        model = ExtraTreesClassifier(**params)
        model.fit(X, y)
        return model

    def _train_random_forest(self, X, y):
        model = RandomForestClassifier(
            n_estimators=200, max_depth=15, min_samples_split=5,
            min_samples_leaf=2, random_state=self.seed, n_jobs=-1
        )
        model.fit(X, y)
        return model

    def _train_logistic_regression(self, X, y):
        model = LogisticRegression(
            max_iter=1000, random_state=self.seed, solver='lbfgs'
        )
        model.fit(X, y)
        return model

    def _train_neural_network(self, X, y):
        model = MLPClassifier(
            hidden_layer_sizes=(128, 64, 32), activation='relu', solver='adam',
            learning_rate_init=0.001, max_iter=500, random_state=self.seed,
            early_stopping=True, validation_fraction=0.1
        )
        model.fit(X, y)
        return model

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Generate prediction probabilities."""
        if self.model is None:
            raise ValueError("Model not trained yet")
        if X is None or len(X) == 0:
            return np.empty((0, 3))
        X_scaled = pd.DataFrame(
            self.scaler.transform(X),
            columns=X.columns,
            index=X.index
        )
        return self.model.predict_proba(X_scaled)

    def predict_signals(self, X: pd.DataFrame, confidence_threshold: float = None) -> np.ndarray:
        """
        Generate trading signals with confidence filtering.
        Returns: Array of signals (0=Sell, 1=Hold, 2=Buy)
        """
        if self.signal_decision_mode == 'two_stage':
            signals = self._predict_signals_two_stage(X, confidence_threshold=confidence_threshold)
            if len(signals) > 0:
                logger.info(
                    f"Signal distribution: Buy={np.sum(signals==2)}, "
                    f"Hold={np.sum(signals==1)}, Sell={np.sum(signals==0)} "
                    f"(mode=two_stage)"
                )
            return signals

        if confidence_threshold is None:
            confidence_threshold = self.config.CONFIDENCE_THRESHOLD
        margin_threshold = float(getattr(self.config, 'SIGNAL_MARGIN_THRESHOLD', 0.0))

        probabilities = self.predict(X)
        if len(probabilities) == 0:
            return np.array([], dtype=int)
        signals = np.argmax(probabilities, axis=1)

        # Apply confidence threshold: only keep Buy/Sell if confident enough
        # Also require enough probability margin to avoid low-conviction flips.
        for i in range(len(signals)):
            pred_class = signals[i]
            pred_prob = probabilities[i, pred_class]
            if pred_class != 1:
                second_prob = np.partition(probabilities[i], -2)[-2] if probabilities.shape[1] > 1 else 0.0
                margin = pred_prob - second_prob
                if pred_prob < confidence_threshold or margin < margin_threshold:
                    signals[i] = 1  # Revert to Hold if not confident in Buy/Sell

        logger.info(f"Signal distribution: Buy={np.sum(signals==2)}, "
                    f"Hold={np.sum(signals==1)}, Sell={np.sum(signals==0)} "
                    f"(threshold={confidence_threshold:.2f}, margin={margin_threshold:.2f})")

        return signals

    def _predict_signals_two_stage(self, X: pd.DataFrame, confidence_threshold: float = None) -> np.ndarray:
        """
        Two-stage decision:
        A) Entry (trade vs hold) with dynamic threshold targeting exposure.
        B) Direction (buy vs sell) only for rows selected by entry stage.
        """
        if self.entry_model is None or self.direction_model is None:
            logger.warning("Two-stage heads unavailable, falling back to legacy signal decision")
            # fallback to legacy behavior
            prev_mode = self.signal_decision_mode
            self.signal_decision_mode = 'legacy'
            out = self.predict_signals(X, confidence_threshold=confidence_threshold)
            self.signal_decision_mode = prev_mode
            return out

        if X is None or len(X) == 0:
            return np.array([], dtype=int)

        X_scaled = pd.DataFrame(
            self.scaler.transform(X),
            columns=X.columns,
            index=X.index
        )
        entry_prob = self.entry_model.predict_proba(X_scaled)[:, 1]
        direction_prob = self.direction_model.predict_proba(X_scaled)[:, 1]  # P(Buy | entry)

        if self.entry_threshold_base is not None and np.isfinite(self.entry_threshold_base):
            base_entry_thr = float(self.entry_threshold_base)
        else:
            base_entry_thr = float(getattr(self.config, 'TWO_STAGE_MIN_ENTRY_PROB', 0.45))
        entry_thr_min = float(getattr(self.config, 'ENTRY_THRESHOLD_MIN', 0.45))
        entry_thr_max = float(getattr(self.config, 'ENTRY_THRESHOLD_MAX', 0.85))
        base_entry_thr = min(max(base_entry_thr, entry_thr_min), entry_thr_max)

        if confidence_threshold is None:
            confidence_threshold = float(getattr(self.config, 'TWO_STAGE_MIN_ENTRY_PROB', 0.45))
        entry_floor = float(confidence_threshold)

        n = len(X)
        entry_thr = np.full(n, base_entry_thr, dtype=float)
        if 'Trend_Regime' in X.columns:
            trend = X['Trend_Regime'].to_numpy(dtype=float)
            bull_mult = float(getattr(self.config, 'BULL_ENTRY_THRESHOLD_MULT', 0.90))
            bear_mult = float(getattr(self.config, 'BEAR_ENTRY_THRESHOLD_MULT', 1.10))
            entry_thr = np.where(trend >= 0.5, entry_thr * bull_mult, entry_thr * bear_mult)

        if 'ATR_Pct_Z100' in X.columns:
            vol_z = X['ATR_Pct_Z100'].to_numpy(dtype=float)
            z_cut = float(getattr(self.config, 'HIGH_VOL_Z_THRESHOLD', 1.0))
            high_mult = float(getattr(self.config, 'HIGH_VOL_ENTRY_THRESHOLD_MULT', 1.05))
            low_mult = float(getattr(self.config, 'LOW_VOL_ENTRY_THRESHOLD_MULT', 0.95))
            entry_thr = np.where(vol_z >= z_cut, entry_thr * high_mult, entry_thr * low_mult)

        entry_thr = np.clip(entry_thr, entry_thr_min, entry_thr_max)
        enter_mask = (entry_prob >= entry_thr) & (entry_prob >= entry_floor)

        if self.direction_threshold_base is not None and np.isfinite(self.direction_threshold_base):
            base_direction_thr = float(self.direction_threshold_base)
        else:
            base_direction_thr = float(getattr(self.config, 'DIRECTION_BUY_PROB_THRESHOLD', 0.50))

        direction_thr = np.full(n, base_direction_thr, dtype=float)
        if 'Trend_Regime' in X.columns:
            trend = X['Trend_Regime'].to_numpy(dtype=float)
            bull_bias = float(getattr(self.config, 'BULL_DIRECTION_BIAS', -0.03))
            bear_bias = float(getattr(self.config, 'BEAR_DIRECTION_BIAS', 0.03))
            direction_thr = np.where(trend >= 0.5, direction_thr + bull_bias, direction_thr + bear_bias)

        dir_min = float(getattr(self.config, 'DIRECTION_THRESHOLD_MIN', 0.40))
        dir_max = float(getattr(self.config, 'DIRECTION_THRESHOLD_MAX', 0.60))
        direction_thr = np.clip(direction_thr, dir_min, dir_max)

        buy_candidate = enter_mask & (direction_prob >= direction_thr)
        sell_candidate = enter_mask & (~buy_candidate)

        # Long-only signal synthesis:
        # - Buy only when flat
        # - Sell only when a position is open
        # This avoids meaningless Sell spam while already flat.
        signals = np.ones(n, dtype=int)
        in_position = False
        for i in range(n):
            if (not in_position) and bool(buy_candidate[i]):
                signals[i] = 2
                in_position = True
            elif in_position and bool(sell_candidate[i]):
                signals[i] = 0
                in_position = False
        return signals

    def save_model(self, symbol: str) -> str:
        if self.model is None:
            raise ValueError("No model to save")
        model_path = os.path.join(self.config.MODELS_DIR, f"{symbol}_{self.model_type}_model.pkl")
        with open(model_path, 'wb') as f:
            pickle.dump({
                'model': self.model,
                'entry_model': self.entry_model,
                'direction_model': self.direction_model,
                'entry_threshold_base': self.entry_threshold_base,
                'direction_threshold_base': self.direction_threshold_base,
                'scaler': self.scaler,
                'selected_features': self.feature_selector.selected_features,
                'model_type': self.model_type,
                'signal_decision_mode': self.signal_decision_mode,
            }, f)
        logger.info(f"Model saved: {model_path}")
        return model_path

    def load_model(self, symbol: str) -> bool:
        model_path = os.path.join(self.config.MODELS_DIR, f"{symbol}_{self.model_type}_model.pkl")
        if not os.path.exists(model_path):
            # Try generic path
            model_path = os.path.join(self.config.MODELS_DIR, f"{symbol}_model.pkl")
        if not os.path.exists(model_path):
            logger.warning(f"Model file not found: {model_path}")
            return False
        try:
            with open(model_path, 'rb') as f:
                data = pickle.load(f)
                self.model = data['model']
                self.entry_model = data.get('entry_model', None)
                self.direction_model = data.get('direction_model', None)
                self.entry_threshold_base = data.get('entry_threshold_base', None)
                self.direction_threshold_base = data.get('direction_threshold_base', None)
                self.scaler = data['scaler']
                self.feature_selector.selected_features = data['selected_features']
                if 'model_type' in data:
                    self.model_type = data['model_type']
                if 'signal_decision_mode' in data:
                    self.signal_decision_mode = str(data['signal_decision_mode']).lower()
            logger.info(f"Model loaded: {model_path}")
            return True
        except Exception as e:
            logger.error(f"Error loading model: {str(e)}")
            return False

    def get_feature_importance(self, top_n: int = 20) -> pd.DataFrame:
        if self.model is None:
            raise ValueError("Model not trained yet")
        if hasattr(self.model, 'feature_importances_'):
            importance = pd.DataFrame({
                'feature': self.feature_selector.selected_features,
                'importance': self.model.feature_importances_
            }).sort_values('importance', ascending=False)
            return importance.head(top_n)
        else:
            logger.warning(f"{self.model_type} does not support feature_importances_")
            return pd.DataFrame({'feature': self.feature_selector.selected_features,
                                 'importance': [0] * len(self.feature_selector.selected_features)})
