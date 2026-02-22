"""
Configuration file for the Crypto Trading Strategy
Centralized parameter management for easy tuning and experimentation
"""

import os
from datetime import datetime, timedelta

# ============================================================================
# PROJECT SETTINGS
# ============================================================================

PROJECT_NAME = "Advanced Crypto Trading Strategy"
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
MODELS_DIR = os.path.join(PROJECT_DIR, "models")
RESULTS_DIR = os.path.join(PROJECT_DIR, "results")
LOGS_DIR = os.path.join(PROJECT_DIR, "logs")

# Create directories if they don't exist
for directory in [DATA_DIR, MODELS_DIR, RESULTS_DIR, LOGS_DIR]:
    os.makedirs(directory, exist_ok=True)

# ============================================================================
# DATA COLLECTION SETTINGS
# ============================================================================

# Cryptocurrency symbols to test
SYMBOLS = ["AVAXUSDT"]

# Binance API settings
BINANCE_INTERVAL = "4h"  # Daily candles
BINANCE_START_TIME = "4 years ago UTC"  # Historical data period (used only if dates below are None)

# Fixed date ranges (set to None to use BINANCE_START_TIME instead)
DATA_START_DATE = "2022-01-01"   # Start of all data
DATA_END_DATE = "2026-02-12"     # End of all data
TEST_START_DATE = "2024-01-01"   # Start of test period (everything before = training)
# Test ends at DATA_END_DATE automatically

# Data validation settings
MIN_CANDLES = 500  # Minimum number of candles required
MAX_PRICE_GAP = 0.50  # Maximum acceptable price gap between candles (50% - relaxed for all coins)
MAX_VOLUME_SPIKE = 20.0  # Maximum acceptable volume spike multiplier (relaxed)

# ============================================================================
# FEATURE ENGINEERING SETTINGS
# ============================================================================

# Technical indicator parameters
RSI_PERIOD = 14
BOLLINGER_PERIOD = 20
BOLLINGER_STD = 2
ATR_PERIOD = 14
STOCHASTIC_PERIOD = 14

# Moving average periods
SMA_SHORT = 5
SMA_MEDIUM = 20
SMA_LONG = 50
SMA_VERY_LONG = 200

# Momentum periods
MOMENTUM_PERIODS = [3, 5, 10]

# Volume analysis
VOLUME_WINDOW = 20

# Pattern detection
ENABLE_CANDLESTICK_PATTERNS = True
TOP_N_PATTERNS = 15  # Use only top 15 most important patterns

# ============================================================================
# MULTI-TIMEFRAME SETTINGS
# ============================================================================

# Primary timeframe (for signal generation)
PRIMARY_TIMEFRAME = "4h"

# Confirmation timeframe (for trend validation)
CONFIRMATION_TIMEFRAME = "1d"

# Trend confirmation parameters
TREND_SMA_SHORT = 50
TREND_SMA_LONG = 200
TREND_CONFIRMATION_REQUIRED = True

# ============================================================================
# REPRODUCIBILITY
# ============================================================================

RANDOM_SEED = 42  # Global seed for reproducible results

# ============================================================================
# MODEL TRAINING SETTINGS
# ============================================================================

# Model type
MODEL_TYPE = "lgbm"  # Options: lgbm, xgboost, catboost, hist_gradient_boosting, extra_trees, random_forest, logistic_regression, neural_network

# LightGBM parameters
LGBM_PARAMS = {
    "objective": "multiclass",
    "num_class": 3,
    "metric": "multi_logloss",
    "learning_rate": 0.05,
    "num_leaves": 31,
    "max_depth": 7,
    "min_data_in_leaf": 20,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "lambda_l1": 1.0,
    "lambda_l2": 1.0,
    "verbose": -1,
}

# XGBoost parameters
XGB_PARAMS = {
    "objective": "multi:softprob",
    "num_class": 3,
    "n_estimators": 300,
    "learning_rate": 0.05,
    "max_depth": 7,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_alpha": 1.0,
    "reg_lambda": 1.0,
    "verbosity": 0,
    "eval_metric": "mlogloss",
}

# CatBoost parameters
CATBOOST_PARAMS = {
    "loss_function": "MultiClass",
    "iterations": 400,
    "learning_rate": 0.05,
    "depth": 8,
    "l2_leaf_reg": 3.0,
    "verbose": False,
    "allow_writing_files": False,
}

# Histogram Gradient Boosting parameters
HGB_PARAMS = {
    "loss": "log_loss",
    "learning_rate": 0.05,
    "max_iter": 300,
    "max_depth": 8,
    "max_leaf_nodes": 63,
    "min_samples_leaf": 20,
    "l2_regularization": 0.5,
}

# Extra Trees parameters
EXTRA_TREES_PARAMS = {
    "n_estimators": 500,
    "max_features": "sqrt",
    "min_samples_split": 5,
    "min_samples_leaf": 2,
    "class_weight": "balanced_subsample",
}

# Feature selection
FEATURE_SELECTION_METHOD = "rfe"  # Options: "rfe", "importance", "correlation"
N_FEATURES_TO_SELECT = 20
FEATURE_IMPORTANCE_THRESHOLD = 0.01

# Class imbalance handling
USE_SMOTE = True
SMOTE_RATIO = 0.5

# Train-test split (used as fallback if TEST_START_DATE is None)
TEST_SIZE = 0.2
VALIDATION_SIZE = 0.1

# ============================================================================
# SIGNAL GENERATION SETTINGS
# ============================================================================

# Target creation for training
TARGET_WINDOW = 150  # Rolling window for target creation
BUY_THRESHOLD = 0.70  # Percentile threshold for buy signals
SELL_THRESHOLD = 0.08  # Percentile threshold for sell signals
TARGET_METHOD = "triple_barrier"  # Options: "percentile", "triple_barrier"
TARGET_HORIZON_BARS = 12  # Label horizon (2h bars => 24h)
TARGET_NEUTRAL_BAND = 0.0015  # Neutral zone if no barrier is hit

# Triple-barrier target settings
TARGET_TP_ATR_MULT = 2.0
TARGET_SL_ATR_MULT = 1.2
TARGET_MIN_ATR_PCT = 0.002

# Signal filtering
USE_ATR_FILTER = True
ATR_THRESHOLD = 1.0  # Multiples of ATR for signal filtering

# Signal confidence scoring
USE_SIGNAL_CONFIDENCE = True
CONFIDENCE_THRESHOLD = 0.50  # Minimum confidence to take a trade
SIGNAL_MARGIN_THRESHOLD = 0.08  # Min (top_prob - second_prob) for Buy/Sell

# ============================================================================
# BACKTESTING SETTINGS
# ============================================================================

# Initial capital
INITIAL_CAPITAL = 1.0

# Trading costs
TRADING_FEE = 0.001  # 0.1% per trade (typical for Binance)
SLIPPAGE = 0.0005  # 0.05% average slippage

# Risk management
STOP_LOSS = 0.05  # 5% stop loss
TAKE_PROFIT = 0.15  # 10% take profit

# Position sizing
POSITION_SIZE = 1.0  # Full capital per trade (can be adjusted for risk management)
MAX_CONCURRENT_POSITIONS = 1  # Maximum number of open positions

# ============================================================================
# WALK-FORWARD VALIDATION SETTINGS
# ============================================================================

WALK_FORWARD_ENABLED = True
WALK_FORWARD_TRAIN_PERIOD = 252 * 4  # ~1 year of 4h candles
WALK_FORWARD_TEST_PERIOD = 63 * 4  # ~3 months of 4h candles
WALK_FORWARD_STEP = 63 * 4  # Step forward by 3 months

# ============================================================================
# BACKTESTING BIAS MITIGATION
# ============================================================================

# Use next candle's open price for entries (prevents look-ahead bias)
USE_NEXT_OPEN_FOR_ENTRY = True

# Include slippage in backtest calculations
INCLUDE_SLIPPAGE = True

# Lag all indicators by one period (prevents look-ahead bias)
LAG_INDICATORS = True

# ============================================================================
# PORTFOLIO SETTINGS
# ============================================================================

# Portfolio allocation
PORTFOLIO_ALLOCATION = "equal"  # Options: "equal", "risk_parity", "performance_weighted"

# Portfolio rebalancing
REBALANCE_FREQUENCY = "monthly"  # Options: "daily", "weekly", "monthly"

# ============================================================================
# PERFORMANCE METRICS
# ============================================================================

# Risk-free rate for Sharpe ratio calculation (annual)
RISK_FREE_RATE = 0.05

# Annualization factor for metrics
ANNUAL_PERIODS = 252 * 6  # 6 trading sessions per day (4h candles)

# ============================================================================
# LOGGING AND MONITORING
# ============================================================================

LOG_LEVEL = "INFO"  # Options: "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
LOG_TO_FILE = True
LOG_TO_CONSOLE = True

# ============================================================================
# SENSITIVITY ANALYSIS SETTINGS
# ============================================================================

SENSITIVITY_ANALYSIS_ENABLED = True

# Parameters to test
SENSITIVITY_PARAMS = {
    "STOP_LOSS": [0.03, 0.05, 0.07, 0.10],
    "TAKE_PROFIT": [0.05, 0.10, 0.15, 0.20],
    "ATR_THRESHOLD": [0.5, 1.0, 1.5, 2.0],
    "CONFIDENCE_THRESHOLD": [0.50, 0.60, 0.70, 0.80],
}

# ============================================================================
# OPTUNA OBJECTIVE SETTINGS
# ============================================================================

# Objective mode:
# - "robust_windows": score trial on multiple validation windows (recommended)
# - "single_split": legacy score on one validation block
OPTUNA_OBJECTIVE_MODE = "robust_windows"

# Robust objective windowing
OPTUNA_VALID_WINDOWS = 5
OPTUNA_MIN_WINDOW_SAMPLES = 120

# Robust objective weights
# Score = w_sharpe*median_sharpe + w_return*median_return
#         + w_outperf*median_outperformance
#         - w_dd*worst_drawdown - w_stability*return_std + w_activity*active_ratio
OPTUNA_WEIGHT_SHARPE = 1.0
OPTUNA_WEIGHT_RETURN = 0.04
OPTUNA_WEIGHT_OUTPERFORMANCE = 0.03
OPTUNA_WEIGHT_DRAWDOWN = 0.02
OPTUNA_WEIGHT_STABILITY = 0.03
OPTUNA_WEIGHT_ACTIVITY = 0.5

# Minimum activity constraints inside Optuna objective
OPTUNA_MIN_TOTAL_TRADES = 10
OPTUNA_MIN_ACTIVE_RATIO = 0.40

# Return viability controls (percentage points):
# - OPTUNA_MIN_RETURN_PCT is the target return level for optimization.
# - Trials below this target are penalized (not automatically rejected).
# - OPTUNA_MIN_RETURN_HARD_FLOOR_PCT is a hard reject floor for very poor trials.
OPTUNA_MIN_RETURN_PCT = 0.0
OPTUNA_MIN_RETURN_HARD_FLOOR_PCT = -12.0
OPTUNA_RETURN_SHORTFALL_PENALTY = 0.15

# Tune model-level hyperparameters inside Optuna objective.
OPTUNA_TUNE_MODEL_PARAMS = True

# ============================================================================
# OUTPUT SETTINGS
# ============================================================================

# Save models
SAVE_MODELS = True

# Save backtest results
SAVE_BACKTEST_RESULTS = True

# Generate plots
GENERATE_PLOTS = True
COMPARE_PLOT_ALL_CANDIDATES = False  # In compare_models, save detailed backtest plot for best model only

# Export results to CSV
EXPORT_TO_CSV = True

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def get_date_range(start_str: str = None, end_str: str = None):
    """
    Parse date range strings and return datetime objects.
    
    Args:
        start_str: Start date string (e.g., "2 years ago UTC")
        end_str: End date string (default: today)
    
    Returns:
        Tuple of (start_date, end_date) as datetime objects
    """
    if end_str is None:
        end_date = datetime.utcnow()
    else:
        end_date = datetime.fromisoformat(end_str)
    
    if start_str is None:
        start_date = end_date - timedelta(days=730)  # 2 years
    elif "year" in start_str.lower():
        years = int(start_str.split()[0])
        start_date = end_date - timedelta(days=365 * years)
    elif "month" in start_str.lower():
        months = int(start_str.split()[0])
        start_date = end_date - timedelta(days=30 * months)
    else:
        start_date = datetime.fromisoformat(start_str)
    
    return start_date, end_date


def print_config():
    """Print current configuration settings."""
    print("\n" + "=" * 80)
    print(f"PROJECT: {PROJECT_NAME}")
    print("=" * 80)
    print(f"Symbols: {', '.join(SYMBOLS)}")
    print(f"Timeframe: {BINANCE_INTERVAL}")
    if DATA_START_DATE and TEST_START_DATE:
        print(f"Training Period: {DATA_START_DATE} to {TEST_START_DATE}")
        print(f"Test Period:     {TEST_START_DATE} to {DATA_END_DATE}")
    else:
        print(f"Data: {BINANCE_START_TIME} | Test Size: {TEST_SIZE*100:.0f}%")
    print(f"Model: {MODEL_TYPE}")
    print(f"Features: {N_FEATURES_TO_SELECT}")
    print(f"Stop Loss: {STOP_LOSS*100:.1f}%")
    print(f"Take Profit: {TAKE_PROFIT*100:.1f}%")
    print(f"Trading Fee: {TRADING_FEE*100:.2f}%")
    print(f"Slippage: {SLIPPAGE*100:.2f}%")
    print(f"Seed: {RANDOM_SEED}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    print_config()
