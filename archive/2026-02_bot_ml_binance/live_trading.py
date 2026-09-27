"""
Live Trading Script for Tangier Strategy
Executes trades from model signals with optional real order execution.
"""

import argparse
import os
import sys
import logging
import json
import time
import pandas as pd
from datetime import datetime

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'config'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import config as config
from data_manager import DataManager
from feature_engineer import FeatureEngineer
from model_trainer import ModelTrainer, normalize_model_type
from live_utils import BinanceClient, TradeExecutor, StateManager, TelegramNotifier


EXCLUDE_FEATURE_COLS = ['Open', 'High', 'Low', 'Close', 'Volume', 'Returns', 'Log_Returns', 'Target']


def setup_logging():
    """Setup logging configuration."""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format))

    log_file = os.path.join(config.LOGS_DIR, f"live_trading_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format))

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    if root_logger.handlers:
        root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    return log_file


logger = logging.getLogger(__name__)


def normalize_symbol(raw_symbol: str) -> str:
    """Accept INJ/USDT or INJUSDT and return Binance format."""
    return str(raw_symbol).strip().upper().replace('/', '')


def interval_to_minutes(interval: str) -> float:
    """Convert Binance interval string (e.g. 4h) to minutes."""
    raw = str(interval).strip()
    if not raw:
        return 0.0
    unit = raw[-1]
    try:
        value = float(raw[:-1])
    except ValueError:
        return 0.0

    if unit == 'm':
        return value
    if unit == 'h':
        return value * 60.0
    if unit == 'd':
        return value * 1440.0
    if unit == 'w':
        return value * 10080.0
    if unit == 'M':
        return value * 43200.0
    return 0.0


def _resolve_app_path(raw_path: str) -> str:
    if not raw_path:
        return ''
    path = str(raw_path).strip()
    if path.startswith('/app/'):
        path = path[len('/app/'):]
    return path


def _extract_optimized_params(payload) -> dict:
    """
    Extract optimization params even from nested/corrupted JSON shapes.
    Supports keys used by runtime and xgb/lgbm prefixed keys.
    """
    if not isinstance(payload, dict):
        return {}

    allowed = {
        'stop_loss', 'take_profit', 'confidence_threshold',
        'buy_threshold', 'sell_threshold', 'atr_threshold'
    }
    direct = {}
    for key, value in payload.items():
        if key in allowed or key.startswith('xgb_') or key.startswith('lgbm_'):
            direct[key] = value
    if direct:
        return direct

    for value in payload.values():
        nested = _extract_optimized_params(value)
        if nested:
            return nested
    return {}


def _apply_best_params_to_runtime(cfg, params: dict) -> dict:
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

    lgbm_int_params = {'n_estimators', 'num_leaves', 'max_depth', 'min_data_in_leaf', 'bagging_freq'}
    xgb_int_params = {'n_estimators', 'max_depth'}

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
        for key, value in lgbm_updates.items():
            applied[f"LGBM_PARAMS.{key}"] = value

    if xgb_updates:
        current = dict(getattr(cfg, 'XGB_PARAMS', {}) or {})
        current.update(xgb_updates)
        setattr(cfg, 'XGB_PARAMS', current)
        for key, value in xgb_updates.items():
            applied[f"XGB_PARAMS.{key}"] = value

    return applied


def _split_raw_train_eval(data: pd.DataFrame):
    """Chronological split on raw feature data."""
    test_start = getattr(config, 'TEST_START_DATE', None)
    if test_start and isinstance(data.index, pd.DatetimeIndex):
        test_start_ts = pd.Timestamp(test_start)
        train_data = data[data.index < test_start_ts]
        eval_data = data[data.index >= test_start_ts]
    else:
        split_idx = int(len(data) * (1 - config.TEST_SIZE))
        train_data = data.iloc[:split_idx]
        eval_data = data.iloc[split_idx:]
    return train_data, eval_data


def configure_live_strategy(symbol: str, model_override: str = None,
                            optimized: bool = True, strategy_file: str = None) -> dict:
    """
    Configure runtime model/params for live trading.
    Priority:
    1) --model CLI override
    2) strict_oos_best_by_symbol.csv best row for symbol
    3) config MODEL_TYPE
    Params source:
    - selected strict OOS report if selected_strategy=tuned
    - fallback results/{symbol}_best_params.json
    """
    info = {
        'symbol': symbol,
        'model_type': None,
        'params_source': None,
        'selected_strategy': None,
        'applied_params': {},
    }

    if model_override:
        chosen_model = normalize_model_type(model_override)
    else:
        chosen_model = normalize_model_type(getattr(config, 'MODEL_TYPE', 'lgbm'))

    best_csv = os.path.join(config.RESULTS_DIR, 'strict_oos_best_by_symbol.csv')
    best_row = None
    if os.path.exists(best_csv):
        try:
            df_best = pd.read_csv(best_csv)
            df_symbol = df_best[df_best['symbol'].astype(str).str.upper() == symbol]
            if len(df_symbol) > 0:
                if model_override:
                    df_match = df_symbol[
                        df_symbol['model'].astype(str).str.lower() == chosen_model
                    ]
                    best_row = df_match.iloc[0] if len(df_match) > 0 else None
                else:
                    best_row = df_symbol.iloc[0]

                if best_row is not None:
                    if not model_override and isinstance(best_row.get('model', None), str):
                        chosen_model = normalize_model_type(best_row['model'])
                    info['selected_strategy'] = str(best_row.get('selected_strategy', '')).strip().lower() or None
        except Exception as e:
            logger.warning(f"Could not read strict_oos_best_by_symbol.csv: {str(e)}")

    setattr(config, 'MODEL_TYPE', chosen_model)
    info['model_type'] = chosen_model

    if not optimized:
        return info

    report_path = ''
    if strategy_file:
        report_path = _resolve_app_path(strategy_file)
    elif best_row is not None and isinstance(best_row.get('report_path', None), str):
        report_path = _resolve_app_path(best_row['report_path'])
    else:
        report_path = os.path.join(config.RESULTS_DIR, f"{symbol}_{chosen_model}_strict_oos_report.json")

    report = None
    if report_path and os.path.exists(report_path):
        try:
            with open(report_path, 'r', encoding='utf-8-sig') as f:
                report = json.load(f)
            info['params_source'] = report_path
            report_model = normalize_model_type(report.get('model', chosen_model))
            setattr(config, 'MODEL_TYPE', report_model)
            info['model_type'] = report_model
            if not info['selected_strategy']:
                info['selected_strategy'] = str(report.get('selected_strategy', '')).strip().lower() or None
        except Exception as e:
            logger.warning(f"Could not read report {report_path}: {str(e)}")

    if report is not None and info['selected_strategy'] == 'tuned':
        params_source = report.get('optimization', {}).get('best_params', {})
        extracted = _extract_optimized_params(params_source)
        applied = _apply_best_params_to_runtime(config, extracted)
        if applied:
            info['applied_params'] = applied
            return info
    elif report is not None and info['selected_strategy'] == 'baseline':
        return info

    fallback_path = os.path.join(config.RESULTS_DIR, f"{symbol}_best_params.json")
    if os.path.exists(fallback_path):
        try:
            with open(fallback_path, 'r', encoding='utf-8-sig') as f:
                fallback = json.load(f)
            extracted = _extract_optimized_params(fallback.get('best_params', {}))
            applied = _apply_best_params_to_runtime(config, extracted)
            if applied:
                info['params_source'] = fallback_path
                info['applied_params'] = applied
        except Exception as e:
            logger.warning(f"Could not read fallback params {fallback_path}: {str(e)}")

    return info


def apply_atr_filter(data: pd.DataFrame, atr_period: int = 14, atr_threshold: float = 1.0) -> pd.DataFrame:
    """Apply ATR-based signal filter."""
    data = data.copy()

    prev_close = data['Close'].shift(1)
    tr1 = data['High'] - data['Low']
    tr2 = (data['High'] - prev_close).abs()
    tr3 = (data['Low'] - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    data['ATR'] = true_range.rolling(window=atr_period).mean()
    data['SMA_20'] = data['Close'].rolling(window=20).mean()
    data['Filtered_Signal'] = 1

    buy_condition = (
        (data['Predicted_Signal'] == 2) &
        (data['Close'] > data['SMA_20']) &
        ((data['Open'] - data['SMA_20']).abs() > atr_threshold * data['ATR'])
    )
    sell_condition = (
        (data['Predicted_Signal'] == 0) &
        (data['Close'] < data['SMA_20']) &
        ((data['Open'] - data['SMA_20']).abs() > atr_threshold * data['ATR'])
    )
    data.loc[buy_condition, 'Filtered_Signal'] = 2
    data.loc[sell_condition, 'Filtered_Signal'] = 0
    return data.dropna(subset=['ATR', 'SMA_20'])


def _build_inference_matrix(data: pd.DataFrame, selected_features: list) -> pd.DataFrame:
    feature_cols = [col for col in data.columns if col not in EXCLUDE_FEATURE_COLS]
    X = data[feature_cols].copy()
    if selected_features:
        selected = [col for col in selected_features if col in X.columns]
        X = X[selected] if selected else X.iloc[:, 0:0]
    X = X.replace([float('inf'), float('-inf')], pd.NA).dropna()
    return X


def _ensure_model_loaded(model_trainer: ModelTrainer, data: pd.DataFrame, symbol: str, auto_train: bool) -> bool:
    if model_trainer.load_model(symbol):
        return True
    if not auto_train:
        return False

    logger.warning(f"Model for {symbol}/{model_trainer.model_type} not found. Training automatically...")
    train_data, _ = _split_raw_train_eval(data)
    if len(train_data) == 0:
        logger.error("Auto-train failed: empty training split")
        return False

    X_train, y_train, _ = model_trainer.prepare_data(train_data, symbol)
    if len(X_train) == 0:
        logger.error("Auto-train failed: empty X_train")
        return False
    model_trainer.train(X_train, y_train, symbol, model_type=model_trainer.model_type)
    model_trainer.save_model(symbol)
    return model_trainer.load_model(symbol)


def run_live_trading(symbol: str, dry_run: bool = False, model_override: str = None,
                     optimized: bool = True, strategy_file: str = None,
                     auto_train_model: bool = True, trade_proportion: float = 1.0) -> bool:
    """
    Run one live trading cycle for a symbol.

    Returns:
        True when cycle completed successfully, False otherwise.
    """
    notifier = None
    symbol = normalize_symbol(symbol)

    strategy_info = configure_live_strategy(
        symbol=symbol,
        model_override=model_override,
        optimized=optimized,
        strategy_file=strategy_file,
    )

    logger.info(f"\n{'='*80}")
    logger.info(f"LIVE TRADING - {symbol}")
    logger.info(f"Dry Run: {dry_run}")
    logger.info(f"Model: {strategy_info['model_type']}")
    if strategy_info.get('params_source'):
        logger.info(f"Params source: {strategy_info['params_source']}")
    if strategy_info.get('applied_params'):
        logger.info(f"Applied optimized params: {strategy_info['applied_params']}")
    logger.info(f"{'='*80}\n")

    try:
        executor = None
        binance_client = None
        if not dry_run:
            binance_client = BinanceClient()
            executor = TradeExecutor(binance_client, config)

        state_file = os.path.join(config.RESULTS_DIR, f"trade_state_{symbol}.json")
        state_manager = StateManager(state_file)
        notifier = TelegramNotifier()
        data_manager = DataManager(config)
        feature_engineer = FeatureEngineer(config)
        model_trainer = ModelTrainer(config)
    except Exception as e:
        logger.error(f"Error initializing components: {str(e)}")
        return False

    trade_state = state_manager.load_state()
    logger.info(f"Loaded state: {trade_state}")

    try:
        logger.info(f"Fetching data for {symbol}...")
        # In live mode we always want latest candles; do not cap to backtest end date.
        if getattr(config, 'DATA_END_DATE', None):
            logger.info(f"Ignoring DATA_END_DATE={config.DATA_END_DATE} for live data fetch")
            setattr(config, 'DATA_END_DATE', None)
        data = data_manager.fetch_data(symbol)
        if data is None:
            logger.error(f"Failed to fetch data for {symbol}")
            return False

        data = data_manager.prepare_data(data, symbol)
        logger.info("Engineering features...")
        data = feature_engineer.engineer_features(data, symbol)

        logger.info("Loading/training model...")
        if not _ensure_model_loaded(model_trainer, data, symbol, auto_train=auto_train_model):
            logger.error(f"Failed to load or train model for {symbol}")
            return False

        logger.info("Generating predictions...")
        selected_features = []
        if hasattr(model_trainer.feature_selector, 'selected_features'):
            selected_features = model_trainer.feature_selector.selected_features or []

        X = _build_inference_matrix(data, selected_features)
        if len(X) == 0:
            logger.error("No valid inference rows after feature filtering")
            return False

        confidence_threshold = float(getattr(config, 'CONFIDENCE_THRESHOLD', 0.45))
        signals = model_trainer.predict_signals(X, confidence_threshold=confidence_threshold)
        data = data.loc[X.index].copy()
        data['Predicted_Signal'] = signals

        decision_mode = str(getattr(config, 'SIGNAL_DECISION_MODE', 'legacy')).lower()
        disable_two_stage_atr = bool(getattr(config, 'DISABLE_POST_ATR_GATE_IN_TWO_STAGE', True))
        use_post_atr = bool(getattr(config, 'USE_ATR_FILTER', False))
        if decision_mode == 'two_stage' and disable_two_stage_atr:
            use_post_atr = False

        if use_post_atr:
            logger.info("Applying ATR filter...")
            atr_period = int(getattr(config, 'ATR_PERIOD', 14))
            atr_threshold = float(getattr(config, 'ATR_THRESHOLD', 1.0))
            data = apply_atr_filter(data, atr_period=atr_period, atr_threshold=atr_threshold)
            if len(data) == 0:
                logger.error("No rows left after ATR filter")
                return False
            latest_row = data.iloc[-1]
            latest_signal = int(latest_row['Filtered_Signal'])
        else:
            latest_row = data.iloc[-1]
            latest_signal = int(latest_row['Predicted_Signal'])
        latest_price = float(latest_row['Close'])

        logger.info(f"Latest Signal: {latest_signal} (0=Sell, 1=Hold, 2=Buy)")
        logger.info(f"Latest Price: {latest_price:.6f}")

        if not dry_run:
            usdt_balance = binance_client.get_balance('USDT')
            crypto_asset = symbol.replace('USDT', '')
            crypto_balance = binance_client.get_balance(crypto_asset)
        else:
            usdt_balance = 1000.0
            crypto_balance = 0.5

        logger.info(f"USDT Balance: {usdt_balance:.2f}")
        logger.info(f"{symbol} Balance: {crypto_balance:.6f}")

        if trade_state.get("order_pending", False):
            entry_price = float(trade_state.get("price_start", 0))
            if entry_price <= 0:
                logger.warning("Invalid open position state; resetting")
                trade_state["order_pending"] = False
                trade_state["price_start"] = 0
                state_manager.save_state(trade_state)
                return True

            pct_change = (latest_price - entry_price) / entry_price
            logger.info(f"Position open at {entry_price:.6f}, current {latest_price:.6f}, PnL={pct_change:.2%}")

            if pct_change <= -float(config.STOP_LOSS):
                logger.info(f"Stop loss triggered ({pct_change:.2%})")
                if not dry_run:
                    order = executor.execute_trade('SELL', symbol, 1.0)
                    logger.info(f"SELL order: {order}")
                    if not order:
                        logger.error("SELL order failed; state unchanged")
                        return False
                trade_state["order_pending"] = False
                trade_state["cumulative_pnl"] = float(trade_state.get("cumulative_pnl", 0)) + pct_change * 100
                trade_state["total_trades"] = int(trade_state.get("total_trades", 0)) + 1
                trade_state["price_start"] = 0
                trade_state["cooldown_counter"] = 5
                state_manager.save_state(trade_state)
                notifier.send_message(f"[STOP LOSS] {symbol}\nPrice: {latest_price:.6f}\nPnL: {pct_change:.2%}")

            elif pct_change >= float(config.TAKE_PROFIT):
                logger.info(f"Take profit triggered ({pct_change:.2%})")
                if not dry_run:
                    order = executor.execute_trade('SELL', symbol, 1.0)
                    logger.info(f"SELL order: {order}")
                    if not order:
                        logger.error("SELL order failed; state unchanged")
                        return False
                trade_state["order_pending"] = False
                trade_state["cumulative_pnl"] = float(trade_state.get("cumulative_pnl", 0)) + pct_change * 100
                trade_state["total_trades"] = int(trade_state.get("total_trades", 0)) + 1
                trade_state["price_start"] = 0
                trade_state["cooldown_counter"] = 5
                state_manager.save_state(trade_state)
                notifier.send_message(f"[TAKE PROFIT] {symbol}\nPrice: {latest_price:.6f}\nPnL: {pct_change:.2%}")

            elif latest_signal == 0:
                logger.info("Sell signal received")
                if not dry_run:
                    order = executor.execute_trade('SELL', symbol, 1.0)
                    logger.info(f"SELL order: {order}")
                    if not order:
                        logger.error("SELL order failed; state unchanged")
                        return False
                trade_state["order_pending"] = False
                trade_state["cumulative_pnl"] = float(trade_state.get("cumulative_pnl", 0)) + pct_change * 100
                trade_state["total_trades"] = int(trade_state.get("total_trades", 0)) + 1
                trade_state["price_start"] = 0
                trade_state["cooldown_counter"] = 5
                state_manager.save_state(trade_state)
                notifier.send_message(f"[SELL SIGNAL] {symbol}\nPrice: {latest_price:.6f}\nPnL: {pct_change:.2%}")

        else:
            cooldown = int(trade_state.get("cooldown_counter", 0))
            if cooldown > 0:
                logger.info(f"Cooldown active: {cooldown} period(s) remaining")
                trade_state["cooldown_counter"] = cooldown - 1
                state_manager.save_state(trade_state)
            elif latest_signal == 2 and usdt_balance > 10:
                logger.info("Buy signal received")
                if not dry_run:
                    order = executor.execute_trade('BUY', symbol, trade_proportion)
                    logger.info(f"BUY order: {order}")
                    if not order:
                        logger.error("BUY order failed; state unchanged")
                        return False
                trade_state["order_pending"] = True
                trade_state["price_start"] = latest_price
                state_manager.save_state(trade_state)
                notifier.send_message(
                    f"[BUY SIGNAL] {symbol}\nPrice: {latest_price:.6f}\nTotal Trades: {trade_state.get('total_trades', 0)}"
                )

        logger.info(f"Trading State: {trade_state}")
        logger.info(f"{'='*80}\n")
        return True

    except Exception as e:
        logger.error(f"Error in live trading: {str(e)}", exc_info=True)
        if notifier is not None:
            notifier.send_message(f"[LIVE ERROR] {symbol}: {str(e)}")
        return False


def parse_args():
    parser = argparse.ArgumentParser(description="Live trading runner")
    parser.add_argument('--symbol', type=str, default='INJUSDT', help='Trading symbol (INJUSDT or INJ/USDT)')
    parser.add_argument('--model', type=str, default=None, help='Model override (default: best strict OOS)')
    parser.add_argument('--dry-run', action='store_true', help='Simulate orders only (no real execution)')
    parser.add_argument('--execute-live', action='store_true', help='Execute real Binance market orders')
    parser.add_argument('--no-optimized', action='store_true', help='Do not load optimized params')
    parser.add_argument('--strategy-file', type=str, default=None, help='Optional strict OOS report JSON path')
    parser.add_argument('--no-auto-train', action='store_true', help='Fail if model file is missing')
    parser.add_argument('--loop-minutes', type=float, default=0.0, help='Run continuously every N minutes (0=once)')
    parser.add_argument('--auto-loop', action='store_true', help='Use loop interval from BINANCE_INTERVAL')
    parser.add_argument('--once', action='store_true', help='Run one cycle only and exit')
    parser.add_argument('--trade-proportion', type=float, default=1.0, help='Fraction of balance to trade on BUY (0-1)')
    return parser.parse_args()


if __name__ == "__main__":
    log_file = setup_logging()
    logger.info(f"Log file: {log_file}")
    config.print_config()

    args = parse_args()
    symbol = normalize_symbol(args.symbol)
    dry_run = not args.execute_live
    if args.dry_run:
        dry_run = True

    trade_proportion = max(0.01, min(1.0, float(args.trade_proportion)))
    loop_minutes = float(args.loop_minutes)
    if args.once:
        loop_minutes = 0.0
    elif args.auto_loop and loop_minutes <= 0:
        loop_minutes = interval_to_minutes(getattr(config, 'BINANCE_INTERVAL', ''))
        if loop_minutes > 0:
            logger.info(
                f"Auto-loop enabled from BINANCE_INTERVAL={getattr(config, 'BINANCE_INTERVAL', '')} "
                f"-> every {loop_minutes:.2f} minute(s)"
            )
        else:
            logger.warning("Auto-loop requested but BINANCE_INTERVAL could not be parsed; running once")

    try:
        if loop_minutes > 0:
            logger.info(f"Starting loop mode every {loop_minutes:.2f} minute(s)")
            while True:
                run_live_trading(
                    symbol=symbol,
                    dry_run=dry_run,
                    model_override=args.model,
                    optimized=not args.no_optimized,
                    strategy_file=args.strategy_file,
                    auto_train_model=not args.no_auto_train,
                    trade_proportion=trade_proportion,
                )
                sleep_seconds = max(1, int(loop_minutes * 60))
                logger.info(f"Sleeping {sleep_seconds}s before next cycle")
                time.sleep(sleep_seconds)
        else:
            run_live_trading(
                symbol=symbol,
                dry_run=dry_run,
                model_override=args.model,
                optimized=not args.no_optimized,
                strategy_file=args.strategy_file,
                auto_train_model=not args.no_auto_train,
                trade_proportion=trade_proportion,
            )
    except KeyboardInterrupt:
        logger.info("Live trading interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
