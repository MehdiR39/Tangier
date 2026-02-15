"""
Live Trading Script for Tangier Strategy
Executes real-time trades based on model predictions with risk management
"""

import sys
import os
import logging
import json
import pandas as pd
import numpy as np
from datetime import datetime

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'config'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import config as config
from data_manager import DataManager
from feature_engineer import FeatureEngineer
from model_trainer import ModelTrainer
from live_utils import BinanceClient, TradeExecutor, StateManager, TelegramNotifier


# ============================================================================
# LOGGING SETUP
# ============================================================================

def setup_logging():
    """Setup logging configuration."""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format))
    
    # File handler
    log_file = os.path.join(config.LOGS_DIR, f"live_trading_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format))
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Avoid duplicate handlers on repeated runs
    if root_logger.handlers:
        root_logger.handlers.clear()

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    return log_file


logger = logging.getLogger(__name__)


# ============================================================================
# SIGNAL FILTERING
# ============================================================================

def apply_atr_filter(data: pd.DataFrame, atr_period: int = 14, atr_threshold: float = 1.0) -> pd.DataFrame:
    """
    Apply ATR-based filter to signals.
    
    Args:
        data: DataFrame with OHLCV and Predicted_Signal
        atr_period: ATR period
        atr_threshold: ATR threshold multiplier
    
    Returns:
        DataFrame with Filtered_Signal column
    """
    data = data.copy()
    
    # Calculate ATR and SMA with pandas (no TA-Lib dependency)
    prev_close = data['Close'].shift(1)
    tr1 = data['High'] - data['Low']
    tr2 = (data['High'] - prev_close).abs()
    tr3 = (data['Low'] - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    data['ATR'] = true_range.rolling(window=atr_period).mean()
    data['SMA_20'] = data['Close'].rolling(window=20).mean()
    
    # Initialize filtered signal as Hold
    data['Filtered_Signal'] = 1
    
    # Apply buy condition
    buy_condition = (
        (data['Predicted_Signal'] == 2) &
        (data['Close'] > data['SMA_20']) &
        (abs(data['Open'] - data['SMA_20']) > atr_threshold * data['ATR'])
    )
    data.loc[buy_condition, 'Filtered_Signal'] = 2
    
    # Apply sell condition
    sell_condition = (
        (data['Predicted_Signal'] == 0) &
        (data['Close'] < data['SMA_20']) &
        (abs(data['Open'] - data['SMA_20']) > atr_threshold * data['ATR'])
    )
    data.loc[sell_condition, 'Filtered_Signal'] = 0
    
    return data.dropna(subset=['ATR', 'SMA_20'])


# ============================================================================
# MAIN LIVE TRADING FUNCTION
# ============================================================================

def run_live_trading(symbol: str, dry_run: bool = False):
    """
    Run live trading for a symbol.
    
    Args:
        symbol: Trading symbol (e.g., 'SOLUSDT')
        dry_run: If True, don't execute real trades
    """
    logger.info(f"\n{'='*80}")
    logger.info(f"LIVE TRADING - {symbol}")
    logger.info(f"Dry Run: {dry_run}")
    logger.info(f"{'='*80}\n")
    
    # Initialize components
    try:
        if not dry_run:
            binance_client = BinanceClient()
            executor = TradeExecutor(binance_client, config)
        
        state_manager = StateManager(f"trade_state_{symbol}.json")
        notifier = TelegramNotifier()
        data_manager = DataManager(config)
        feature_engineer = FeatureEngineer(config)
        model_trainer = ModelTrainer(config)
        
    except Exception as e:
        logger.error(f"Error initializing components: {str(e)}")
        return
    
    # Load trading state
    trade_state = state_manager.load_state()
    logger.info(f"Loaded state: {trade_state}")
    
    try:
        # Fetch latest data
        logger.info(f"Fetching data for {symbol}...")
        data = data_manager.fetch_data(symbol)
        if data is None:
            logger.error(f"Failed to fetch data for {symbol}")
            return
        
        # Prepare data
        data = data_manager.prepare_data(data, symbol)
        
        # Engineer features
        logger.info("Engineering features...")
        data = feature_engineer.engineer_features(data, symbol)
        
        # Load trained model
        logger.info("Loading trained model...")
        if not model_trainer.load_model(symbol):
            logger.error(f"Failed to load model for {symbol}")
            return
        
        # Generate predictions
        logger.info("Generating predictions...")
        X = data[[col for col in data.columns if col not in 
                 ['Open', 'High', 'Low', 'Close', 'Volume', 'Returns', 'Log_Returns', 'Target']]]
        
        # Ensure we have the right features
        if hasattr(model_trainer.feature_selector, 'selected_features') and \
           model_trainer.feature_selector.selected_features:
            X = X[model_trainer.feature_selector.selected_features]
        
        signals = model_trainer.predict_signals(X)
        data['Predicted_Signal'] = signals
        
        # Apply ATR filter
        logger.info("Applying ATR filter...")
        data = apply_atr_filter(data, atr_period=14, atr_threshold=1.0)
        
        # Get latest signal
        latest_row = data.iloc[-1]
        latest_signal = latest_row['Filtered_Signal']
        latest_price = latest_row['Close']
        
        logger.info(f"Latest Signal: {latest_signal} (0=Sell, 1=Hold, 2=Buy)")
        logger.info(f"Latest Price: {latest_price:.2f}")
        
        # Get balances
        if not dry_run:
            usdt_balance = binance_client.get_balance('USDT')
            crypto_asset = symbol.replace('USDT', '')
            crypto_balance = binance_client.get_balance(crypto_asset)
        else:
            usdt_balance = 1000  # Simulated balance
            crypto_balance = 0.5  # Simulated balance
        
        logger.info(f"USDT Balance: {usdt_balance:.2f}")
        logger.info(f"{symbol} Balance: {crypto_balance:.4f}")
        
        # Trade logic
        if trade_state["order_pending"]:
            # Position is open, check exit conditions
            pct_change = (latest_price - trade_state["price_start"]) / trade_state["price_start"]
            
            logger.info(f"Position open at {trade_state['price_start']:.2f}, current: {latest_price:.2f}")
            logger.info(f"Profit/Loss: {pct_change:.2%}")
            
            # Check stop loss
            if pct_change <= -config.STOP_LOSS:
                logger.info(f"Stop loss triggered ({pct_change:.2%})")
                
                if not dry_run:
                    order = executor.execute_trade('SELL', symbol, 1.0)
                    logger.info(f"SELL order: {order}")
                
                # Update state
                trade_state["order_pending"] = False
                trade_state["cumulative_pnl"] += pct_change * 100
                trade_state["total_trades"] += 1
                trade_state["price_start"] = 0
                trade_state["cooldown_counter"] = 5  # Cooldown period
                state_manager.save_state(trade_state)
                
                # Notify
                message = f"🔴 STOP LOSS TRIGGERED\n{symbol}\nPrice: {latest_price:.2f}\nP&L: {pct_change:.2%}"
                notifier.send_message(message)
            
            # Check take profit
            elif pct_change >= config.TAKE_PROFIT:
                logger.info(f"Take profit triggered ({pct_change:.2%})")
                
                if not dry_run:
                    order = executor.execute_trade('SELL', symbol, 1.0)
                    logger.info(f"SELL order: {order}")
                
                # Update state
                trade_state["order_pending"] = False
                trade_state["cumulative_pnl"] += pct_change * 100
                trade_state["total_trades"] += 1
                trade_state["price_start"] = 0
                trade_state["cooldown_counter"] = 5
                state_manager.save_state(trade_state)
                
                # Notify
                message = f"🟢 TAKE PROFIT HIT\n{symbol}\nPrice: {latest_price:.2f}\nP&L: {pct_change:.2%}"
                notifier.send_message(message)
            
            # Check sell signal
            elif latest_signal == 0:
                logger.info("Sell signal received")
                
                if not dry_run:
                    order = executor.execute_trade('SELL', symbol, 1.0)
                    logger.info(f"SELL order: {order}")
                
                # Update state
                trade_state["order_pending"] = False
                trade_state["cumulative_pnl"] += pct_change * 100
                trade_state["total_trades"] += 1
                trade_state["price_start"] = 0
                trade_state["cooldown_counter"] = 5
                state_manager.save_state(trade_state)
                
                # Notify
                message = f"🔴 SELL SIGNAL\n{symbol}\nPrice: {latest_price:.2f}\nP&L: {pct_change:.2%}"
                notifier.send_message(message)
        
        else:
            # No position open, check entry conditions
            if trade_state["cooldown_counter"] > 0:
                logger.info(f"Cooldown active: {trade_state['cooldown_counter']} periods remaining")
                trade_state["cooldown_counter"] -= 1
                state_manager.save_state(trade_state)
            
            elif latest_signal == 2 and usdt_balance > 10:
                logger.info("Buy signal received")
                
                if not dry_run:
                    order = executor.execute_trade('BUY', symbol, 1.0)
                    logger.info(f"BUY order: {order}")
                
                # Update state
                trade_state["order_pending"] = True
                trade_state["price_start"] = latest_price
                state_manager.save_state(trade_state)
                
                # Notify
                message = f"🟢 BUY SIGNAL\n{symbol}\nPrice: {latest_price:.2f}\nTotal Trades: {trade_state['total_trades']}"
                notifier.send_message(message)
        
        logger.info(f"\nTrading State: {trade_state}")
        logger.info(f"{'='*80}\n")
    
    except Exception as e:
        logger.error(f"Error in live trading: {str(e)}", exc_info=True)
        notifier.send_message(f"⚠️ Live trading error: {str(e)}")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    # Setup logging
    log_file = setup_logging()
    logger.info(f"Log file: {log_file}")
    
    # Print configuration
    config.print_config()
    
    # Run live trading
    symbol = config.SYMBOLS[0] if config.SYMBOLS else "SOLUSDT"
    dry_run = True  # Set to False for real trading
    
    try:
        run_live_trading(symbol, dry_run=dry_run)
    except KeyboardInterrupt:
        logger.info("Live trading interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
