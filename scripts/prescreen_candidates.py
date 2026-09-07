#!/usr/bin/env python3
"""
Fast pre-screen for candidate models on a strict holdout split.
Goal: avoid expensive Optuna runs on low-activity / low-robustness candidates.
"""

import argparse
import os
import sys
from datetime import datetime

import pandas as pd

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, "config"))
sys.path.insert(0, os.path.join(ROOT_DIR, "src"))

import config as base_config
from data_manager import DataManager
from feature_engineer import FeatureEngineer
from model_trainer import normalize_model_type
from strict_oos_eval import clone_config, run_baseline_holdout, to_metrics_dict


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def main():
    parser = argparse.ArgumentParser(description="Pre-screen candidate models before expensive optimization")
    parser.add_argument("--symbol", type=str, required=True, help="Trading symbol, e.g. INJUSDT")
    parser.add_argument(
        "--models",
        type=str,
        default="random_forest,extra_trees,xgboost,lgbm,logistic_regression,hist_gradient_boosting",
        help="Comma-separated candidate models",
    )
    parser.add_argument("--interval", type=str, default=None, help="Binance interval override (e.g. 1h, 4h, 1d)")
    parser.add_argument("--valid-start", type=str, default="2024-01-01")
    parser.add_argument("--holdout-start", type=str, default="2025-01-01")
    parser.add_argument("--dev-start", type=str, default=None)
    parser.add_argument("--min-return-pct", type=float, default=0.0)
    parser.add_argument("--min-trades", type=int, default=8)
    parser.add_argument("--min-time-in-market-pct", type=float, default=10.0)
    parser.add_argument("--min-bull-capture", type=float, default=0.15)
    args = parser.parse_args()

    symbol = args.symbol.strip().upper()
    models = [normalize_model_type(m.strip()) for m in args.models.split(",") if m.strip()]
    if not models:
        raise ValueError("No models provided")

    cfg_data = clone_config(base_config)
    if args.interval:
        cfg_data.BINANCE_INTERVAL = str(args.interval).strip()
        interval = cfg_data.BINANCE_INTERVAL
        if interval.endswith("m"):
            mins = max(1.0, float(interval[:-1]))
            bars_per_day = 1440.0 / mins
            cfg_data.ANNUAL_PERIODS = int(365 * bars_per_day)
        elif interval.endswith("h"):
            hours = max(1.0, float(interval[:-1]))
            bars_per_day = 24.0 / hours
            cfg_data.ANNUAL_PERIODS = int(365 * bars_per_day)
        elif interval.endswith("d"):
            days = max(1.0, float(interval[:-1]))
            cfg_data.ANNUAL_PERIODS = int(365 / days)
        elif interval.endswith("w"):
            weeks = max(1.0, float(interval[:-1]))
            cfg_data.ANNUAL_PERIODS = int(52 / weeks)
        elif interval.endswith("M"):
            months = max(1.0, float(interval[:-1]))
            cfg_data.ANNUAL_PERIODS = int(12 / months)
    data_manager = DataManager(cfg_data)
    feature_engineer = FeatureEngineer(cfg_data)

    data = data_manager.fetch_data(symbol, cfg_data.BINANCE_INTERVAL, cfg_data.BINANCE_START_TIME)
    if data is None or len(data) == 0:
        raise RuntimeError(f"Failed to fetch data for {symbol}")
    data = data_manager.prepare_data(data, symbol)
    data = feature_engineer.engineer_features(data, symbol)
    if not isinstance(data.index, pd.DatetimeIndex):
        data.index = pd.to_datetime(data.index, errors="coerce")
        data = data[data.index.notna()]

    valid_start = pd.Timestamp(args.valid_start)
    holdout_start = pd.Timestamp(args.holdout_start)
    dev_start = pd.Timestamp(args.dev_start) if args.dev_start else None

    if dev_start is not None:
        data = data[data.index >= dev_start]

    dev_data = data[data.index < holdout_start]
    holdout_data = data[data.index >= holdout_start]
    if len(dev_data) == 0 or len(holdout_data) == 0:
        raise ValueError(f"Invalid split sizes: dev={len(dev_data)}, holdout={len(holdout_data)}")

    rows = []
    for model in models:
        cfg_model = clone_config(base_config)
        cfg_model.MODEL_TYPE = normalize_model_type(model)
        if args.interval:
            cfg_model.BINANCE_INTERVAL = str(args.interval).strip()
            cfg_model.ANNUAL_PERIODS = cfg_data.ANNUAL_PERIODS
        try:
            result = run_baseline_holdout(symbol, cfg_model, dev_data, holdout_data)
            metrics = to_metrics_dict(result, cfg_model)

            bull_bh = _safe_float(metrics.get("bull_regime_bh_return_pct", 0.0))
            bull_capture = metrics.get("bull_capture_ratio", None)
            bull_capture_ok = True
            if bull_bh > 0 and args.min_bull_capture > 0:
                bull_capture_ok = bull_capture is not None and float(bull_capture) >= float(args.min_bull_capture)

            checks = {
                "return_ok": _safe_float(metrics.get("return_pct", 0.0)) >= float(args.min_return_pct),
                "trades_ok": int(metrics.get("num_trades", 0)) >= int(args.min_trades),
                "time_in_market_ok": _safe_float(metrics.get("time_in_market_pct", 0.0)) >= float(args.min_time_in_market_pct),
                "bull_capture_ok": bool(bull_capture_ok),
            }
            passed = all(checks.values())

            score = (
                _safe_float(metrics.get("return_pct", 0.0))
                + 0.35 * _safe_float(metrics.get("outperformance_pct", 0.0))
                + 12.0 * (_safe_float(metrics.get("time_in_market_pct", 0.0)) / 100.0)
                + 0.30 * int(metrics.get("num_trades", 0))
            )

            rows.append({
                "symbol": symbol,
                "model": model,
                "status": "ok",
                "passed": bool(passed),
                "score": float(score),
                "return_pct": _safe_float(metrics.get("return_pct", 0.0)),
                "buy_hold_pct": _safe_float(metrics.get("buy_hold_pct", 0.0)),
                "outperformance_pct": _safe_float(metrics.get("outperformance_pct", 0.0)),
                "sharpe": _safe_float(metrics.get("sharpe", 0.0)),
                "max_drawdown_pct": _safe_float(metrics.get("max_drawdown_pct", 0.0)),
                "num_trades": int(metrics.get("num_trades", 0)),
                "time_in_market_pct": _safe_float(metrics.get("time_in_market_pct", 0.0)),
                "bull_capture_ratio": float(bull_capture) if bull_capture is not None else None,
                "bull_regime_bh_return_pct": bull_bh,
                "bull_regime_strategy_return_pct": _safe_float(metrics.get("bull_regime_strategy_return_pct", 0.0)),
                "check_return_ok": checks["return_ok"],
                "check_trades_ok": checks["trades_ok"],
                "check_time_ok": checks["time_in_market_ok"],
                "check_bull_capture_ok": checks["bull_capture_ok"],
            })
        except Exception as e:
            rows.append({
                "symbol": symbol,
                "model": model,
                "status": "failed",
                "passed": False,
                "score": float("-inf"),
                "error": str(e),
            })

    df = pd.DataFrame(rows).sort_values(by=["passed", "score"], ascending=[False, False])
    os.makedirs(base_config.RESULTS_DIR, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_stamp = os.path.join(base_config.RESULTS_DIR, f"{symbol}_prescreen_{stamp}.csv")
    out_latest = os.path.join(base_config.RESULTS_DIR, f"{symbol}_prescreen_latest.csv")
    df.to_csv(out_stamp, index=False)
    df.to_csv(out_latest, index=False)

    print("\n" + "=" * 80)
    print("PRESCREEN SUMMARY")
    print("=" * 80)
    print(f"Symbol: {symbol}")
    print(
        f"Rules: return>={args.min_return_pct:.2f}% | trades>={args.min_trades} | "
        f"time_in_market>={args.min_time_in_market_pct:.1f}% | "
        f"bull_capture>={args.min_bull_capture:.2f} (if bull regime exists)"
    )
    for _, row in df.iterrows():
        if row.get("status") != "ok":
            print(f"{row['model']}: FAILED")
            continue
        print(
            f"{row['model']}: passed={bool(row['passed'])} | "
            f"ret={_safe_float(row.get('return_pct', 0.0)):.2f}% | "
            f"sharpe={_safe_float(row.get('sharpe', 0.0)):.2f} | "
            f"trades={int(row.get('num_trades', 0))} | "
            f"time={_safe_float(row.get('time_in_market_pct', 0.0)):.1f}% | "
            f"bull_capture={row.get('bull_capture_ratio')}"
        )
    passed_models = df[(df["status"] == "ok") & (df["passed"] == True)]["model"].tolist()
    print("-" * 80)
    print(f"Passed models: {', '.join(passed_models) if passed_models else '(none)'}")
    print(f"Saved: {out_stamp}")
    print(f"Latest: {out_latest}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
