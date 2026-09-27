#!/usr/bin/env python3
"""
Strict out-of-sample validation:
1) Tune on dev_train/dev_valid.
2) Retrain on full dev (train+valid) with tuned params.
3) Evaluate once on untouched holdout.
"""

import argparse
import copy
import json
import logging
import os
import sys
from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, "config"))
sys.path.insert(0, os.path.join(ROOT_DIR, "src"))

import config as base_config
from backtester import RobustBacktester
from data_manager import DataManager
from feature_engineer import FeatureEngineer
from model_trainer import ModelTrainer, normalize_model_type
from optimizer import HyperparameterOptimizer
from visualizer import Visualizer


def to_builtin(value):
    if isinstance(value, dict):
        return {str(k): to_builtin(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_builtin(v) for v in value]
    if isinstance(value, tuple):
        return [to_builtin(v) for v in value]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def setup_logging(logs_dir: str) -> logging.Logger:
    os.makedirs(logs_dir, exist_ok=True)
    log_file = os.path.join(logs_dir, f"strict_oos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )
    logger = logging.getLogger(__name__)
    logger.info("Log file: %s", log_file)
    return logger


def clone_config(config_obj) -> SimpleNamespace:
    data = {}
    for name in dir(config_obj):
        if name.startswith("_"):
            continue
        value = getattr(config_obj, name)
        if callable(value):
            continue
        try:
            data[name] = copy.deepcopy(value)
        except Exception:
            data[name] = value
    return SimpleNamespace(**data)


def apply_best_params(cfg, params: dict) -> dict:
    if not params:
        return {}

    key_map = {
        "stop_loss": "STOP_LOSS",
        "take_profit": "TAKE_PROFIT",
        "confidence_threshold": "CONFIDENCE_THRESHOLD",
        "buy_threshold": "BUY_THRESHOLD",
        "sell_threshold": "SELL_THRESHOLD",
        "atr_threshold": "ATR_THRESHOLD",
    }

    applied = {}
    for src_key, dst_key in key_map.items():
        if src_key in params and params[src_key] is not None:
            value = float(params[src_key])
            setattr(cfg, dst_key, value)
            applied[dst_key] = value

    lgbm_int_params = {"n_estimators", "num_leaves", "max_depth", "min_data_in_leaf", "bagging_freq"}
    xgb_int_params = {"n_estimators", "max_depth"}

    def cast_model_param(param_name: str, raw_value, int_keys: set):
        if isinstance(raw_value, (int, float)):
            return int(round(raw_value)) if param_name in int_keys else float(raw_value)
        return raw_value

    lgbm_updates = {}
    xgb_updates = {}
    for key, raw_value in params.items():
        if key.startswith("lgbm_"):
            p = key[len("lgbm_") :]
            lgbm_updates[p] = cast_model_param(p, raw_value, lgbm_int_params)
        elif key.startswith("xgb_"):
            p = key[len("xgb_") :]
            xgb_updates[p] = cast_model_param(p, raw_value, xgb_int_params)

    if lgbm_updates:
        current = dict(getattr(cfg, "LGBM_PARAMS", {}) or {})
        current.update(lgbm_updates)
        setattr(cfg, "LGBM_PARAMS", current)
        for k, v in lgbm_updates.items():
            applied[f"LGBM_PARAMS.{k}"] = v

    if xgb_updates:
        current = dict(getattr(cfg, "XGB_PARAMS", {}) or {})
        current.update(xgb_updates)
        setattr(cfg, "XGB_PARAMS", current)
        for k, v in xgb_updates.items():
            applied[f"XGB_PARAMS.{k}"] = v

    return applied


def extract_best_params(payload) -> dict:
    """Extract a flat best_params dict from nested report/params JSON shapes."""
    if not isinstance(payload, dict):
        return {}

    allowed = {
        "stop_loss",
        "take_profit",
        "confidence_threshold",
        "buy_threshold",
        "sell_threshold",
        "atr_threshold",
    }

    direct = {}
    for key, value in payload.items():
        if key in allowed or key.startswith("lgbm_") or key.startswith("xgb_"):
            direct[key] = value
    if direct:
        return direct

    # Try known wrappers first.
    for wrapper in ("best_params", "optimization", "params"):
        if wrapper in payload:
            nested = extract_best_params(payload.get(wrapper))
            if nested:
                return nested

    # Fallback deep search.
    for value in payload.values():
        nested = extract_best_params(value)
        if nested:
            return nested
    return {}


def _build_position_mask(result) -> np.ndarray:
    n = len(getattr(result, "data_used", []))
    if n <= 0:
        return np.array([], dtype=bool)
    mask = np.zeros(n, dtype=bool)
    for trade in getattr(result, "trades", []) or []:
        try:
            entry = int(trade.get("entry_idx", -1))
            exit_ = int(trade.get("exit_idx", -1))
        except Exception:
            continue
        if entry < 0 or exit_ < entry:
            continue
        entry = max(0, min(n - 1, entry))
        exit_ = max(0, min(n - 1, exit_))
        mask[entry:exit_ + 1] = True
    return mask


def _compound_return_pct(returns: np.ndarray) -> float:
    if returns is None or len(returns) == 0:
        return 0.0
    clean = np.asarray(returns, dtype=float)
    clean = clean[np.isfinite(clean)]
    if len(clean) == 0:
        return 0.0
    return float((np.prod(1.0 + clean) - 1.0) * 100.0)


def compute_activity_metrics(result, cfg) -> dict:
    n = len(getattr(result, "data_used", []))
    if n <= 1:
        return {
            "time_in_market_pct": 0.0,
            "bull_capture_ratio": None,
            "bull_regime_bh_return_pct": 0.0,
            "bull_regime_strategy_return_pct": 0.0,
        }

    mask = _build_position_mask(result)
    time_in_market_pct = float(np.mean(mask.astype(float)) * 100.0) if len(mask) > 0 else 0.0

    data_used = result.data_used
    if "Close" not in data_used.columns:
        return {
            "time_in_market_pct": time_in_market_pct,
            "bull_capture_ratio": None,
            "bull_regime_bh_return_pct": 0.0,
            "bull_regime_strategy_return_pct": 0.0,
        }

    close = data_used["Close"].to_numpy(dtype=float)
    n = min(n, len(close))
    if n <= 1:
        return {
            "time_in_market_pct": time_in_market_pct,
            "bull_capture_ratio": None,
            "bull_regime_bh_return_pct": 0.0,
            "bull_regime_strategy_return_pct": 0.0,
        }

    lookback = max(5, int(getattr(cfg, "REGIME_LOOKBACK_BARS", 30)))
    bull_thresh = float(getattr(cfg, "REGIME_BULL_THRESHOLD", 0.08))

    roll_ret = pd.Series(close).pct_change(periods=lookback).fillna(0.0).to_numpy(dtype=float)
    bull_mask = roll_ret >= bull_thresh
    if len(bull_mask) != n:
        bull_mask = bull_mask[:n]

    capital = np.asarray(getattr(result, "capital_history", []), dtype=float)
    m = min(n, len(capital))
    if m <= 1:
        return {
            "time_in_market_pct": time_in_market_pct,
            "bull_capture_ratio": None,
            "bull_regime_bh_return_pct": 0.0,
            "bull_regime_strategy_return_pct": 0.0,
        }

    close = close[:m]
    bull_mask = bull_mask[:m]
    strat_bar_ret = np.zeros(m, dtype=float)
    bh_bar_ret = np.zeros(m, dtype=float)
    strat_bar_ret[1:] = capital[1:m] / (capital[:m - 1] + 1e-12) - 1.0
    bh_bar_ret[1:] = close[1:m] / (close[:m - 1] + 1e-12) - 1.0

    bull_bh_return_pct = _compound_return_pct(bh_bar_ret[bull_mask])
    bull_strat_return_pct = _compound_return_pct(strat_bar_ret[bull_mask])
    bull_capture_ratio = None
    if bull_bh_return_pct > 0:
        bull_capture_ratio = float(bull_strat_return_pct / (bull_bh_return_pct + 1e-10))

    return {
        "time_in_market_pct": time_in_market_pct,
        "bull_capture_ratio": bull_capture_ratio,
        "bull_regime_bh_return_pct": float(bull_bh_return_pct),
        "bull_regime_strategy_return_pct": float(bull_strat_return_pct),
    }


def to_metrics_dict(result, cfg) -> dict:
    metrics = {
        "return_pct": float(result.total_return_pct),
        "buy_hold_pct": float(result.buy_hold_return_pct),
        "outperformance_pct": float(result.outperformance_pct),
        "sharpe": float(result.sharpe_ratio),
        "max_drawdown_pct": float(result.max_drawdown),
        "num_trades": int(result.num_trades),
        "win_rate_pct": float(result.win_rate),
        "profit_factor": float(result.profit_factor),
    }
    metrics.update(compute_activity_metrics(result, cfg))
    return metrics


def deployment_gate(
    baseline_metrics: dict,
    tuned_metrics: dict,
    min_return_delta_pct: float = 0.0,
    min_sharpe_delta: float = -0.10,
    max_drawdown_delta_pct: float = 5.0,
    min_trades: int = 5,
    min_time_in_market_pct: float = 0.0,
    min_bull_capture_ratio: float = 0.0,
) -> dict:
    """Decide whether tuned params should replace baseline on holdout."""
    return_delta = float(tuned_metrics["return_pct"]) - float(baseline_metrics["return_pct"])
    sharpe_delta = float(tuned_metrics["sharpe"]) - float(baseline_metrics["sharpe"])
    drawdown_delta = float(tuned_metrics["max_drawdown_pct"]) - float(baseline_metrics["max_drawdown_pct"])
    tuned_trades = int(tuned_metrics["num_trades"])
    tuned_time_in_market = float(tuned_metrics.get("time_in_market_pct", 0.0))
    bull_capture = tuned_metrics.get("bull_capture_ratio", None)
    bull_bh_return = float(tuned_metrics.get("bull_regime_bh_return_pct", 0.0))

    if bull_bh_return > 0 and min_bull_capture_ratio > 0:
        bull_capture_ok = bool(bull_capture is not None and float(bull_capture) >= float(min_bull_capture_ratio))
    else:
        bull_capture_ok = True

    checks = {
        "return_delta_ok": bool(return_delta >= float(min_return_delta_pct)),
        "sharpe_delta_ok": bool(sharpe_delta >= float(min_sharpe_delta)),
        "drawdown_delta_ok": bool(drawdown_delta <= float(max_drawdown_delta_pct)),
        "min_trades_ok": bool(tuned_trades >= int(min_trades)),
        "time_in_market_ok": bool(tuned_time_in_market >= float(min_time_in_market_pct)),
        "bull_capture_ok": bool(bull_capture_ok),
    }
    deploy_tuned = all(checks.values())
    return {
        "rules": {
            "min_return_delta_pct": float(min_return_delta_pct),
            "min_sharpe_delta": float(min_sharpe_delta),
            "max_drawdown_delta_pct": float(max_drawdown_delta_pct),
            "min_trades": int(min_trades),
            "min_time_in_market_pct": float(min_time_in_market_pct),
            "min_bull_capture_ratio": float(min_bull_capture_ratio),
        },
        "deltas": {
            "return_pct": float(return_delta),
            "sharpe": float(sharpe_delta),
            "max_drawdown_pct": float(drawdown_delta),
            "num_trades": int(tuned_trades - int(baseline_metrics["num_trades"])),
            "time_in_market_pct": float(tuned_time_in_market - float(baseline_metrics.get("time_in_market_pct", 0.0))),
        },
        "checks": checks,
        "deploy_tuned": bool(deploy_tuned),
    }


def run_baseline_holdout(symbol: str, cfg, dev_data: pd.DataFrame, holdout_data: pd.DataFrame):
    trainer = ModelTrainer(cfg)
    backtester = RobustBacktester(cfg)
    gate = HyperparameterOptimizer(cfg, backtester, trainer)

    X_dev, y_dev, selected_features = trainer.prepare_data(dev_data, symbol)
    trainer.train(X_dev, y_dev, symbol)

    X_hold = HyperparameterOptimizer._build_X(holdout_data, selected_features)
    if len(X_hold) == 0:
        raise ValueError("No valid holdout rows for baseline inference")

    confidence_threshold = float(getattr(cfg, "CONFIDENCE_THRESHOLD", 0.50))
    signals = trainer.predict_signals(X_hold, confidence_threshold=confidence_threshold)

    atr_threshold = float(getattr(cfg, "ATR_THRESHOLD", 1.0))
    signals = gate._apply_atr_filter(cfg, holdout_data, X_hold.index, signals, atr_threshold, dev_data)

    bt_data = holdout_data.loc[X_hold.index]
    result = backtester.backtest(
        bt_data,
        signals,
        symbol,
        model_type=f"{cfg.MODEL_TYPE}_baseline_oos",
        stop_loss=float(getattr(cfg, "STOP_LOSS", 0.05)),
        take_profit=float(getattr(cfg, "TAKE_PROFIT", 0.15)),
    )
    return result


def run_tuned_holdout(
    symbol: str,
    cfg,
    train_data: pd.DataFrame,
    valid_data: pd.DataFrame,
    dev_data: pd.DataFrame,
    holdout_data: pd.DataFrame,
    trials: int,
    workers: int,
    fixed_best_params: dict = None,
):
    base_trainer = ModelTrainer(cfg)
    base_backtester = RobustBacktester(cfg)
    optimizer = HyperparameterOptimizer(cfg, base_backtester, base_trainer)

    if fixed_best_params is None:
        hp = optimizer.optimize(train_data, valid_data, symbol, n_trials=trials, n_jobs=workers)
        best_params = hp.get("best_params", {}) or {}
    else:
        best_params = dict(fixed_best_params)
        hp = {"best_params": best_params, "best_score": float("nan"), "trials": 0}

    tuned_cfg = clone_config(cfg)
    tuned_cfg.MODEL_TYPE = cfg.MODEL_TYPE
    applied = apply_best_params(tuned_cfg, best_params)

    tuned_trainer = ModelTrainer(tuned_cfg)
    tuned_backtester = RobustBacktester(tuned_cfg)
    tuned_gate = HyperparameterOptimizer(tuned_cfg, tuned_backtester, tuned_trainer)

    X_dev, y_dev, selected_features = tuned_trainer.prepare_data(dev_data, symbol)
    tuned_trainer.train(X_dev, y_dev, symbol)

    X_hold = HyperparameterOptimizer._build_X(holdout_data, selected_features)
    if len(X_hold) == 0:
        raise ValueError("No valid holdout rows for tuned inference")

    confidence_threshold = float(getattr(tuned_cfg, "CONFIDENCE_THRESHOLD", 0.50))
    signals = tuned_trainer.predict_signals(X_hold, confidence_threshold=confidence_threshold)
    atr_threshold = float(getattr(tuned_cfg, "ATR_THRESHOLD", 1.0))
    signals = tuned_gate._apply_atr_filter(tuned_cfg, holdout_data, X_hold.index, signals, atr_threshold, dev_data)

    bt_data = holdout_data.loc[X_hold.index]
    tuned_result = tuned_backtester.backtest(
        bt_data,
        signals,
        symbol,
        model_type=f"{tuned_cfg.MODEL_TYPE}_strict_oos",
        stop_loss=float(getattr(tuned_cfg, "STOP_LOSS", 0.05)),
        take_profit=float(getattr(tuned_cfg, "TAKE_PROFIT", 0.15)),
    )
    return hp, tuned_cfg, applied, tuned_result


def main():
    parser = argparse.ArgumentParser(description="Strict OOS validation (tune on dev, test on holdout)")
    parser.add_argument("--symbol", type=str, required=True, help="Trading pair, e.g. SOLUSDT")
    parser.add_argument("--model", type=str, default="random_forest", help="Model type to validate")
    parser.add_argument("--interval", type=str, default=None, help="Binance interval override (e.g. 1h, 4h, 1d)")
    parser.add_argument("--valid-start", type=str, default="2024-01-01", help="Validation start date (YYYY-MM-DD)")
    parser.add_argument("--holdout-start", type=str, default="2025-01-01", help="Holdout start date (YYYY-MM-DD)")
    parser.add_argument("--dev-start", type=str, default=None, help="Optional dev start date (YYYY-MM-DD)")
    parser.add_argument("--trials", type=int, default=40, help="Optuna trials on dev split")
    parser.add_argument("--workers", type=int, default=8, help="Parallel Optuna workers")
    parser.add_argument("--objective-mode", type=str, default=None, help="Override OPTUNA objective mode")
    parser.add_argument("--skip-hyperopt", action="store_true", help="Skip Optuna and use provided params")
    parser.add_argument("--best-params-file", type=str, default=None, help="Path to JSON containing best_params")
    parser.add_argument("--best-params-json", type=str, default=None, help="Inline JSON object for best_params")
    parser.add_argument("--gate-min-return-delta", type=float, default=0.0, help="Min tuned-baseline return delta to deploy tuned")
    parser.add_argument("--gate-min-sharpe-delta", type=float, default=-0.10, help="Min tuned-baseline Sharpe delta to deploy tuned")
    parser.add_argument("--gate-max-dd-delta", type=float, default=5.0, help="Max tuned-baseline drawdown delta to deploy tuned")
    parser.add_argument("--gate-min-trades", type=int, default=5, help="Min tuned trades to deploy tuned")
    parser.add_argument("--gate-min-time-in-market-pct", type=float, default=10.0, help="Min tuned time-in-market %% to deploy tuned")
    parser.add_argument("--gate-min-bull-capture", type=float, default=0.15, help="Min tuned bull capture ratio when bull regime exists")
    parser.add_argument("--opt-min-time-in-market", type=float, default=None, help="Override OPTUNA minimum time-in-market ratio (0-1)")
    parser.add_argument("--opt-time-penalty", type=float, default=None, help="Override OPTUNA time-in-market penalty weight")
    parser.add_argument("--opt-min-bull-capture", type=float, default=None, help="Override OPTUNA minimum bull capture ratio")
    parser.add_argument("--opt-bull-capture-penalty", type=float, default=None, help="Override OPTUNA bull capture penalty weight")
    parser.add_argument("--no-plots", action="store_true", help="Disable plot generation")
    args = parser.parse_args()

    logger = setup_logging(base_config.LOGS_DIR)
    symbol = args.symbol.strip().upper()

    cfg = clone_config(base_config)
    cfg.MODEL_TYPE = normalize_model_type(args.model)
    if args.interval:
        cfg.BINANCE_INTERVAL = str(args.interval).strip()
        # Keep Sharpe annualization coherent with the chosen interval.
        interval = cfg.BINANCE_INTERVAL
        if interval.endswith("m"):
            mins = max(1.0, float(interval[:-1]))
            bars_per_day = 1440.0 / mins
            cfg.ANNUAL_PERIODS = int(365 * bars_per_day)
        elif interval.endswith("h"):
            hours = max(1.0, float(interval[:-1]))
            bars_per_day = 24.0 / hours
            cfg.ANNUAL_PERIODS = int(365 * bars_per_day)
        elif interval.endswith("d"):
            days = max(1.0, float(interval[:-1]))
            cfg.ANNUAL_PERIODS = int(365 / days)
        elif interval.endswith("w"):
            weeks = max(1.0, float(interval[:-1]))
            cfg.ANNUAL_PERIODS = int(52 / weeks)
        elif interval.endswith("M"):
            months = max(1.0, float(interval[:-1]))
            cfg.ANNUAL_PERIODS = int(12 / months)
    if args.objective_mode:
        cfg.OPTUNA_OBJECTIVE_MODE = str(args.objective_mode).strip().lower()
    if args.no_plots:
        cfg.GENERATE_PLOTS = False
    if args.opt_min_time_in_market is not None:
        cfg.OPTUNA_MIN_TIME_IN_MARKET = float(args.opt_min_time_in_market)
        cfg.OPTUNA_RETURN_FIRST_MIN_TIME_IN_MARKET = float(args.opt_min_time_in_market)
    if args.opt_time_penalty is not None:
        cfg.OPTUNA_TIME_IN_MARKET_PENALTY = float(args.opt_time_penalty)
        cfg.OPTUNA_RETURN_FIRST_TIME_IN_MARKET_PENALTY = float(args.opt_time_penalty)
    if args.opt_min_bull_capture is not None:
        cfg.OPTUNA_MIN_BULL_CAPTURE_RATIO = float(args.opt_min_bull_capture)
        cfg.OPTUNA_RETURN_FIRST_MIN_BULL_CAPTURE_RATIO = float(args.opt_min_bull_capture)
    if args.opt_bull_capture_penalty is not None:
        cfg.OPTUNA_BULL_CAPTURE_PENALTY = float(args.opt_bull_capture_penalty)
        cfg.OPTUNA_RETURN_FIRST_BULL_CAPTURE_PENALTY = float(args.opt_bull_capture_penalty)

    logger.info("Strict OOS config: symbol=%s, model=%s, trials=%s, workers=%s", symbol, cfg.MODEL_TYPE, args.trials, args.workers)
    logger.info("Split dates: valid_start=%s, holdout_start=%s, dev_start=%s", args.valid_start, args.holdout_start, args.dev_start)

    valid_start = pd.Timestamp(args.valid_start)
    holdout_start = pd.Timestamp(args.holdout_start)
    dev_start = pd.Timestamp(args.dev_start) if args.dev_start else None
    if holdout_start <= valid_start:
        raise ValueError("holdout_start must be strictly after valid_start")

    data_manager = DataManager(cfg)
    feature_engineer = FeatureEngineer(cfg)

    data = data_manager.fetch_data(symbol, cfg.BINANCE_INTERVAL, cfg.BINANCE_START_TIME)
    if data is None or len(data) == 0:
        raise RuntimeError(f"Failed to fetch data for {symbol}")

    data = data_manager.prepare_data(data, symbol)
    data = feature_engineer.engineer_features(data, symbol)
    if not isinstance(data.index, pd.DatetimeIndex):
        data.index = pd.to_datetime(data.index, errors="coerce")
        data = data[data.index.notna()]

    if dev_start is not None:
        data = data[data.index >= dev_start]

    train_data = data[data.index < valid_start]
    valid_data = data[(data.index >= valid_start) & (data.index < holdout_start)]
    holdout_data = data[data.index >= holdout_start]
    dev_data = data[data.index < holdout_start]

    if len(train_data) == 0 or len(valid_data) == 0 or len(holdout_data) == 0:
        raise ValueError(
            f"Invalid split sizes: train={len(train_data)}, valid={len(valid_data)}, holdout={len(holdout_data)}"
        )

    logger.info("Data sizes: train=%s, valid=%s, dev=%s, holdout=%s", len(train_data), len(valid_data), len(dev_data), len(holdout_data))
    logger.info("Date ranges: train[%s -> %s], valid[%s -> %s], holdout[%s -> %s]",
                str(train_data.index.min())[:19], str(train_data.index.max())[:19],
                str(valid_data.index.min())[:19], str(valid_data.index.max())[:19],
                str(holdout_data.index.min())[:19], str(holdout_data.index.max())[:19])

    baseline_result = run_baseline_holdout(symbol, cfg, dev_data, holdout_data)
    fixed_best_params = None
    if args.best_params_file:
        with open(args.best_params_file, "r", encoding="utf-8-sig") as f:
            payload = json.load(f)
        fixed_best_params = extract_best_params(payload)
        if not fixed_best_params:
            raise ValueError(
                f"Could not extract best_params from file: {args.best_params_file}"
            )
    elif args.best_params_json:
        payload = json.loads(args.best_params_json)
        fixed_best_params = extract_best_params(payload) if isinstance(payload, dict) else {}
        if not fixed_best_params and isinstance(payload, dict):
            fixed_best_params = payload
        if not fixed_best_params:
            raise ValueError("Could not parse best params from --best-params-json")
    elif args.skip_hyperopt:
        raise ValueError("--skip-hyperopt requires --best-params-file or --best-params-json")

    hp, tuned_cfg, applied_params, tuned_result = run_tuned_holdout(
        symbol=symbol,
        cfg=cfg,
        train_data=train_data,
        valid_data=valid_data,
        dev_data=dev_data,
        holdout_data=holdout_data,
        trials=max(1, int(args.trials)),
        workers=max(1, int(args.workers)),
        fixed_best_params=fixed_best_params,
    )

    baseline_metrics = to_metrics_dict(baseline_result, cfg)
    tuned_metrics = to_metrics_dict(tuned_result, tuned_cfg)
    gate = deployment_gate(
        baseline_metrics=baseline_metrics,
        tuned_metrics=tuned_metrics,
        min_return_delta_pct=args.gate_min_return_delta,
        min_sharpe_delta=args.gate_min_sharpe_delta,
        max_drawdown_delta_pct=args.gate_max_dd_delta,
        min_trades=args.gate_min_trades,
        min_time_in_market_pct=args.gate_min_time_in_market_pct,
        min_bull_capture_ratio=args.gate_min_bull_capture,
    )
    selected_strategy = "tuned" if gate["deploy_tuned"] else "baseline"
    selected_metrics = tuned_metrics if gate["deploy_tuned"] else baseline_metrics

    quality_checks = {
        "positive_return": bool(tuned_result.total_return_pct > 0),
        "beats_buy_hold": bool(tuned_result.outperformance_pct > 0),
        "positive_sharpe": bool(tuned_result.sharpe_ratio > 0),
        "drawdown_under_35pct": bool(tuned_result.max_drawdown <= 35.0),
        "at_least_10_trades": bool(tuned_result.num_trades >= 10),
        "time_in_market_over_10pct": bool(float(tuned_metrics.get("time_in_market_pct", 0.0)) >= 10.0),
    }
    is_solid = (
        quality_checks["positive_return"]
        and quality_checks["positive_sharpe"]
        and quality_checks["drawdown_under_35pct"]
        and quality_checks["at_least_10_trades"]
        and quality_checks["time_in_market_over_10pct"]
    )

    report = {
        "symbol": symbol,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "model": tuned_cfg.MODEL_TYPE,
        "split": {
            "valid_start": args.valid_start,
            "holdout_start": args.holdout_start,
            "dev_start": args.dev_start,
            "train_rows": int(len(train_data)),
            "valid_rows": int(len(valid_data)),
            "holdout_rows": int(len(holdout_data)),
        },
        "optimization": {
            "trials_requested": int(args.trials),
            "workers": int(args.workers),
            "objective_mode": str(getattr(tuned_cfg, "OPTUNA_OBJECTIVE_MODE", "unknown")),
            "best_score": float(hp.get("best_score", 0.0)) if np.isfinite(float(hp.get("best_score", 0.0))) else None,
            "best_params": hp.get("best_params", {}) or {},
            "applied_params": applied_params,
        },
        "holdout_baseline": baseline_metrics,
        "holdout_tuned": tuned_metrics,
        "deployment_gate": gate,
        "selected_strategy": selected_strategy,
        "selected_metrics": selected_metrics,
        "delta_tuned_minus_baseline": {
            "return_pct": tuned_metrics["return_pct"] - baseline_metrics["return_pct"],
            "outperformance_pct": tuned_metrics["outperformance_pct"] - baseline_metrics["outperformance_pct"],
            "sharpe": tuned_metrics["sharpe"] - baseline_metrics["sharpe"],
            "max_drawdown_pct": tuned_metrics["max_drawdown_pct"] - baseline_metrics["max_drawdown_pct"],
            "num_trades": tuned_metrics["num_trades"] - baseline_metrics["num_trades"],
            "time_in_market_pct": tuned_metrics.get("time_in_market_pct", 0.0) - baseline_metrics.get("time_in_market_pct", 0.0),
            "bull_capture_ratio": (
                float(tuned_metrics["bull_capture_ratio"]) - float(baseline_metrics["bull_capture_ratio"])
                if tuned_metrics.get("bull_capture_ratio") is not None and baseline_metrics.get("bull_capture_ratio") is not None
                else None
            ),
        },
        "quality_checks": quality_checks,
        "verdict": "solid_on_holdout" if is_solid else "not_solid_yet",
    }

    plots = {}
    if getattr(tuned_cfg, "GENERATE_PLOTS", True):
        visualizer = Visualizer(tuned_cfg)
        plots["baseline"] = visualizer.plot_backtest_summary(baseline_result)
        plots["tuned"] = visualizer.plot_backtest_summary(tuned_result)
        report["plots"] = plots

    os.makedirs(tuned_cfg.RESULTS_DIR, exist_ok=True)
    report_path = os.path.join(tuned_cfg.RESULTS_DIR, f"{symbol}_{tuned_cfg.MODEL_TYPE}_strict_oos_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(to_builtin(report), f, indent=2)

    print("\n" + "=" * 80)
    print("STRICT OOS SUMMARY")
    print("=" * 80)
    print(f"Symbol: {symbol} | Model: {tuned_cfg.MODEL_TYPE}")
    print(f"Split: train<{args.valid_start} | valid[{args.valid_start},{args.holdout_start}) | holdout>={args.holdout_start}")
    print(
        f"Baseline holdout: Return={baseline_metrics['return_pct']:.2f}% | "
        f"B&H={baseline_metrics['buy_hold_pct']:.2f}% | Sharpe={baseline_metrics['sharpe']:.2f} | "
        f"MaxDD={baseline_metrics['max_drawdown_pct']:.2f}% | Trades={baseline_metrics['num_trades']} | "
        f"TimeInMkt={baseline_metrics.get('time_in_market_pct', 0.0):.1f}%"
    )
    print(
        f"Tuned holdout:    Return={tuned_metrics['return_pct']:.2f}% | "
        f"B&H={tuned_metrics['buy_hold_pct']:.2f}% | Sharpe={tuned_metrics['sharpe']:.2f} | "
        f"MaxDD={tuned_metrics['max_drawdown_pct']:.2f}% | Trades={tuned_metrics['num_trades']} | "
        f"TimeInMkt={tuned_metrics.get('time_in_market_pct', 0.0):.1f}%"
    )
    print(
        f"Delta tuned-baseline: Return={report['delta_tuned_minus_baseline']['return_pct']:+.2f}% | "
        f"Outperf={report['delta_tuned_minus_baseline']['outperformance_pct']:+.2f}% | "
        f"Sharpe={report['delta_tuned_minus_baseline']['sharpe']:+.2f}"
    )
    print(f"Deployment gate: {'DEPLOY TUNED' if gate['deploy_tuned'] else 'KEEP BASELINE'} (selected={selected_strategy})")
    print(f"Verdict: {report['verdict']}")
    print(f"Report: {report_path}")
    if plots:
        print(f"Plots: baseline={plots['baseline']} | tuned={plots['tuned']}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
