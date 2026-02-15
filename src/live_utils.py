"""
Live Trading Utilities
Handles Binance API integration, trade execution, and state management
"""

import os
import json
import logging
import requests
from typing import Dict, Optional, Tuple
from binance.client import Client
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


class BinanceClient:
    """Wrapper for Binance API client."""
    
    def __init__(self):
        """Initialize Binance client with API credentials."""
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        
        if not api_key or not api_secret:
            raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET must be set in .env file")
        
        self.client = Client(api_key, api_secret)
        logger.info("Binance client initialized")
    
    def get_balance(self, asset: str) -> float:
        """
        Get balance of a specific asset.
        
        Args:
            asset: Asset symbol (e.g., 'USDT', 'SOL')
        
        Returns:
            Balance amount
        """
        try:
            balance_info = self.client.get_asset_balance(asset=asset)
            if balance_info is None:
                logger.warning(f"Asset {asset} not found in account")
                return 0.0
            
            balance = float(balance_info['free'])
            logger.info(f"{asset} balance: {balance:.4f}")
            return balance
        except Exception as e:
            logger.error(f"Error getting balance for {asset}: {str(e)}")
            return 0.0
    
    def get_lot_size(self, symbol: str) -> Tuple[float, float, float]:
        """
        Get lot size constraints for a symbol.
        
        Args:
            symbol: Trading pair (e.g., 'SOLUSDT')
        
        Returns:
            Tuple of (min_qty, max_qty, step_size)
        """
        try:
            info = self.client.get_symbol_info(symbol)
            if not info or 'filters' not in info:
                logger.warning(f"Symbol info not available for {symbol}")
                return 0.0, float('inf'), 0.0
            for filt in info['filters']:
                if filt['filterType'] == 'LOT_SIZE':
                    return (
                        float(filt['minQty']),
                        float(filt['maxQty']),
                        float(filt['stepSize'])
                    )
            logger.warning(f"LOT_SIZE filter not found for {symbol}")
            return 0.0, float('inf'), 0.0
        except Exception as e:
            logger.error(f"Error getting lot size for {symbol}: {str(e)}")
            return 0.0, float('inf'), 0.0
    
    def get_current_price(self, symbol: str) -> float:
        """
        Get current price of a symbol.
        
        Args:
            symbol: Trading pair
        
        Returns:
            Current price
        """
        try:
            ticker = self.client.get_symbol_ticker(symbol=symbol)
            price = float(ticker['price'])
            logger.info(f"{symbol} current price: {price:.2f}")
            return price
        except Exception as e:
            logger.error(f"Error getting price for {symbol}: {str(e)}")
            return 0.0
    
    def execute_buy_order(self, symbol: str, quantity: float) -> Dict:
        """
        Execute a market buy order.
        
        Args:
            symbol: Trading pair
            quantity: Amount to buy
        
        Returns:
            Order response
        """
        try:
            order = self.client.order_market_buy(symbol=symbol, quantity=quantity)
            logger.info(f"BUY order executed: {symbol} x {quantity}")
            return order
        except Exception as e:
            logger.error(f"Error executing BUY order: {str(e)}")
            return {}
    
    def execute_sell_order(self, symbol: str, quantity: float) -> Dict:
        """
        Execute a market sell order.
        
        Args:
            symbol: Trading pair
            quantity: Amount to sell
        
        Returns:
            Order response
        """
        try:
            order = self.client.order_market_sell(symbol=symbol, quantity=quantity)
            logger.info(f"SELL order executed: {symbol} x {quantity}")
            return order
        except Exception as e:
            logger.error(f"Error executing SELL order: {str(e)}")
            return {}


class TradeExecutor:
    """Handles trade execution with position sizing and risk management."""
    
    def __init__(self, binance_client: BinanceClient, config):
        """
        Initialize TradeExecutor.
        
        Args:
            binance_client: BinanceClient instance
            config: Configuration object
        """
        self.client = binance_client
        self.config = config
        logger.info("TradeExecutor initialized")
    
    def execute_trade(
        self,
        signal: str,
        symbol: str,
        proportion: float = 1.0
    ) -> Dict:
        """
        Execute a trade based on signal.
        
        Args:
            signal: 'BUY' or 'SELL'
            symbol: Trading pair
            proportion: Proportion of balance to use (0-1)
        
        Returns:
            Order response
        """
        logger.info(f"Executing {signal} for {symbol}")
        
        if signal == 'BUY':
            return self._execute_buy(symbol, proportion)
        elif signal == 'SELL':
            return self._execute_sell(symbol, proportion)
        else:
            logger.warning(f"Unknown signal: {signal}")
            return {}
    
    def _execute_buy(self, symbol: str, proportion: float) -> Dict:
        """Execute a buy order."""
        base_asset = 'USDT'
        
        # Get available balance
        balance = self.client.get_balance(base_asset)
        amount_to_trade = balance * proportion * 0.995  # 0.5% buffer
        
        # Get lot size constraints
        min_qty, max_qty, step_size = self.client.get_lot_size(symbol)
        
        # Get current price
        price = self.client.get_current_price(symbol)
        if price == 0:
            logger.error(f"Could not get price for {symbol}")
            return {}
        
        # Calculate quantity
        quantity = amount_to_trade / price
        
        # Adjust to step size
        if step_size > 0:
            adjusted_quantity = round((quantity // step_size) * step_size, 8)
        else:
            adjusted_quantity = round(quantity, 8)
        
        # Validate quantity
        if adjusted_quantity < min_qty:
            logger.warning(f"Quantity {adjusted_quantity} below minimum {min_qty}")
            adjusted_quantity = min_qty
        elif adjusted_quantity > max_qty:
            logger.warning(f"Quantity {adjusted_quantity} above maximum {max_qty}")
            adjusted_quantity = max_qty
        
        if adjusted_quantity <= 0:
            logger.error("Invalid quantity for BUY order")
            return {}
        
        logger.info(f"Executing BUY: {symbol} x {adjusted_quantity} at {price:.2f}")
        return self.client.execute_buy_order(symbol, adjusted_quantity)
    
    def _execute_sell(self, symbol: str, proportion: float) -> Dict:
        """Execute a sell order."""
        # Get crypto balance
        crypto_asset = symbol.replace('USDT', '')
        balance = self.client.get_balance(crypto_asset)
        
        if balance <= 0:
            logger.warning(f"No {crypto_asset} balance to sell")
            return {}
        
        # Get lot size constraints
        min_qty, max_qty, step_size = self.client.get_lot_size(symbol)
        
        # Calculate quantity
        quantity = balance * proportion
        
        # Adjust to step size
        if step_size > 0:
            adjusted_quantity = round((quantity // step_size) * step_size, 8)
        else:
            adjusted_quantity = round(quantity, 8)
        
        # Validate quantity
        if adjusted_quantity < min_qty:
            logger.warning(f"Quantity {adjusted_quantity} below minimum {min_qty}")
            adjusted_quantity = min_qty
        elif adjusted_quantity > max_qty:
            logger.warning(f"Quantity {adjusted_quantity} above maximum {max_qty}")
            adjusted_quantity = max_qty
        
        if adjusted_quantity <= 0:
            logger.error("Invalid quantity for SELL order")
            return {}
        
        logger.info(f"Executing SELL: {symbol} x {adjusted_quantity}")
        return self.client.execute_sell_order(symbol, adjusted_quantity)


class StateManager:
    """Manages trading state persistence."""
    
    def __init__(self, state_file: str = "trade_state.json"):
        """
        Initialize StateManager.
        
        Args:
            state_file: Path to state file
        """
        self.state_file = state_file
        logger.info(f"StateManager initialized with file: {state_file}")
    
    def load_state(self) -> Dict:
        """
        Load trading state from file.
        
        Returns:
            State dictionary
        """
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                logger.info("State loaded from file")
                return state
        except Exception as e:
            logger.warning(f"Error loading state: {str(e)}")
        
        # Return default state
        return {
            "order_pending": False,
            "price_start": 0,
            "price_end": 0,
            "total_trades": 0,
            "cumulative_pnl": 0,
            "cooldown_counter": 0,
            "last_signal": None,
            "last_trade_time": None
        }
    
    def save_state(self, state: Dict) -> bool:
        """
        Save trading state to file.
        
        Args:
            state: State dictionary
        
        Returns:
            True if successful
        """
        try:
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
            logger.info("State saved to file")
            return True
        except Exception as e:
            logger.error(f"Error saving state: {str(e)}")
            return False


class TelegramNotifier:
    """Sends notifications via Telegram."""
    
    def __init__(self):
        """Initialize TelegramNotifier."""
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram credentials not configured")
    
    def send_message(self, message: str, parse_mode: str = 'Markdown') -> bool:
        """
        Send message via Telegram.
        
        Args:
            message: Message text
            parse_mode: 'Markdown' or 'HTML'
        
        Returns:
            True if successful
        """
        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram not configured, skipping notification")
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": parse_mode
            }
            
            response = requests.post(url, data=payload, timeout=10)
            response.raise_for_status()
            
            logger.info("Telegram message sent")
            return True
        except Exception as e:
            logger.error(f"Error sending Telegram message: {str(e)}")
            return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Test Binance client
    try:
        client = BinanceClient()
        balance = client.get_balance('USDT')
        print(f"USDT Balance: {balance}")
    except Exception as e:
        print(f"Error: {str(e)}")
