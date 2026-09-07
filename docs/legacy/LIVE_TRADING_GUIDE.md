# Live Trading Guide for Tangier Strategy

## Overview

The Tangier trading strategy now includes both **backtesting** and **live trading** capabilities. This guide explains how to set up and run live trading.

## Architecture

```
tangier/
├── main.py                    # Backtesting orchestrator
├── live_trading.py            # Live trading orchestrator
├── config/config.py           # Configuration
├── src/
│   ├── data_manager.py       # Data fetching
│   ├── feature_engineer.py   # Feature engineering
│   ├── model_trainer.py      # Model training
│   ├── backtester.py         # Backtesting engine
│   ├── portfolio_analyzer.py # Portfolio analysis
│   └── live_utils.py         # Live trading utilities
├── models/                    # Trained models
├── results/                   # Backtest results
└── logs/                      # Trading logs
```

## Prerequisites

### 1. Install Dependencies

```bash
pip install -r requirements.txt
pip install python-binance python-dotenv
```

### 2. Setup Binance API Keys

Create a `.env` file in the tangier folder:

```
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_secret_key_here
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
```

### 3. Train a Model

Before live trading, you need a trained model:

```bash
python main.py
```

This will:
- Fetch historical data
- Engineer features
- Train a LightGBM model
- Save the model to `models/` directory
- Run backtests

## Live Trading Setup

### Step 1: Verify Model Training

Check that a model exists:

```bash
ls models/
```

You should see a folder with your trained model.

### Step 2: Configure Live Trading

Edit `config/config.py` to set:

```python
# Risk Management
STOP_LOSS = 0.05          # 5% stop loss
TAKE_PROFIT = 0.10        # 10% take profit
TRADING_FEE = 0.001       # 0.1% trading fee

# Trading Parameters
SYMBOLS = ["SOLUSDT"]     # Symbol to trade
BINANCE_INTERVAL = "4h"   # Candle interval

# Live Trading
LIVE_TRADING_ENABLED = True
DRY_RUN = True            # Set to False for real trading
```

### Step 3: Run Live Trading (Dry Run First!)

**Always start with dry run mode:**

```bash
python live_trading.py
```

The script will:
- Fetch latest data
- Generate predictions
- Apply ATR filtering
- Simulate trades (no real money)
- Log everything to `logs/`

### Step 4: Monitor the Logs

```bash
tail -f logs/live_trading_*.log
```

### Step 5: Enable Real Trading

Once you're confident, edit `live_trading.py`:

```python
if __name__ == "__main__":
    symbol = SYMBOLS[0]
    dry_run = False  # Change to False for real trading
    run_live_trading(symbol, dry_run=dry_run)
```

## Live Trading Components

### BinanceClient

Handles Binance API interactions:

```python
from src.live_utils import BinanceClient

client = BinanceClient()
balance = client.get_balance('USDT')
price = client.get_current_price('SOLUSDT')
order = client.execute_buy_order('SOLUSDT', 1.0)
```

### TradeExecutor

Executes trades with position sizing:

```python
from src.live_utils import TradeExecutor

executor = TradeExecutor(binance_client, config)
order = executor.execute_trade('BUY', 'SOLUSDT', proportion=1.0)
```

### StateManager

Persists trading state:

```python
from src.live_utils import StateManager

state_mgr = StateManager('trade_state.json')
state = state_mgr.load_state()
state_mgr.save_state(state)
```

### TelegramNotifier

Sends alerts via Telegram:

```python
from src.live_utils import TelegramNotifier

notifier = TelegramNotifier()
notifier.send_message("🟢 BUY signal triggered!")
```

## Trading Logic

### Signal Generation

1. **Fetch Data**: Get latest OHLCV data from Binance
2. **Engineer Features**: Calculate 50+ technical indicators
3. **Predict**: Use trained LightGBM model
4. **Filter**: Apply ATR filter to reduce false signals

### Entry Conditions

- Model predicts BUY (signal = 2)
- Price above 20-period SMA
- ATR filter confirms signal
- USDT balance > $10
- No cooldown active

### Exit Conditions

- **Stop Loss**: Price drops 5% from entry
- **Take Profit**: Price rises 10% from entry
- **Sell Signal**: Model predicts SELL (signal = 0)

### Cooldown Period

After exiting a trade, there's a 5-candle cooldown period to avoid whipsaws.

## State Management

Trading state is saved to `trade_state_{symbol}.json`:

```json
{
  "order_pending": false,
  "price_start": 0,
  "price_end": 0,
  "total_trades": 5,
  "cumulative_pnl": 2.35,
  "cooldown_counter": 0,
  "last_signal": "SELL",
  "last_trade_time": "2026-01-11 12:00:00"
}
```

## Telegram Notifications

Get real-time alerts for:
- BUY signals
- SELL signals
- Stop loss triggered
- Take profit hit
- Errors

Setup Telegram:

1. Create a bot with @BotFather on Telegram
2. Get your chat ID
3. Add to `.env`:

```
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

## Scheduling Live Trading

### Option 1: Windows Task Scheduler

Create a batch file `run_live_trading.bat`:

```batch
@echo off
cd /d "C:\path\to\tangier"
call venv\Scripts\activate
python live_trading.py
```

Schedule it to run every 4 hours (or your candle interval).

### Option 2: Linux Cron

```bash
# Run every 4 hours
0 */4 * * * cd /path/to/tangier && python live_trading.py
```

### Option 3: Docker Container

Create `Dockerfile`:

```dockerfile
FROM python:3.11
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
CMD ["python", "live_trading.py"]
```

Run:

```bash
docker build -t tangier-trading .
docker run -e BINANCE_API_KEY=xxx -e BINANCE_API_SECRET=yyy tangier-trading
```

## Risk Management

### Position Sizing

- Start with small positions (1-2% of capital)
- Use the `proportion` parameter to control size
- Gradually increase as you gain confidence

### Stop Loss & Take Profit

Configure in `config.py`:

```python
STOP_LOSS = 0.05      # 5% stop loss
TAKE_PROFIT = 0.10    # 10% take profit
```

### Monitoring

- Check logs daily
- Monitor Telegram alerts
- Review trade history weekly
- Adjust parameters if needed

## Troubleshooting

### Error: "BINANCE_API_KEY not found"

**Solution**: Create `.env` file with API keys

### Error: "Model not found"

**Solution**: Run `python main.py` first to train a model

### Error: "Insufficient balance"

**Solution**: Ensure you have enough USDT balance

### Error: "Invalid quantity"

**Solution**: Check lot size constraints for the symbol

### Trades not executing

**Solution**: 
- Check if `dry_run=True` in `live_trading.py`
- Verify Binance API keys are correct
- Check internet connection

### No signals generated

**Solution**:
- Verify model is trained
- Check if features are calculated correctly
- Review ATR filter thresholds

## Performance Metrics

Monitor these metrics:

| Metric | Target |
|--------|--------|
| Win Rate | > 50% |
| Profit Factor | > 1.5 |
| Sharpe Ratio | > 1.0 |
| Max Drawdown | < 20% |
| Cumulative P&L | > 0% |

## Best Practices

1. **Start Small**: Trade with small positions initially
2. **Monitor Closely**: Watch the first few trades carefully
3. **Use Dry Run**: Test thoroughly before real trading
4. **Diversify**: Trade multiple coins to reduce risk
5. **Retrain Monthly**: Update model with fresh data
6. **Document Trades**: Keep records for analysis
7. **Have a Plan**: Know your exit strategy before entering

## Advanced: Multi-Coin Trading

Trade multiple coins simultaneously:

```python
SYMBOLS = ["SOLUSDT", "ETHUSDT", "BTCUSDT"]

for symbol in SYMBOLS:
    run_live_trading(symbol, dry_run=False)
```

Each coin gets its own state file and model.

## Support & Debugging

### Enable Debug Logging

Edit `live_trading.py`:

```python
logging.basicConfig(level=logging.DEBUG)
```

### Check Logs

```bash
tail -f logs/live_trading_*.log
```

### Test Components

```python
# Test Binance connection
from src.live_utils import BinanceClient
client = BinanceClient()
print(client.get_balance('USDT'))

# Test Telegram
from src.live_utils import TelegramNotifier
notifier = TelegramNotifier()
notifier.send_message("Test message")
```

## Important Warnings

⚠️ **DISCLAIMER**: Cryptocurrency trading involves substantial risk. Past performance does not guarantee future results.

- **Start with paper trading** (dry run mode)
- **Use small positions** until you're confident
- **Never risk more than you can afford to lose**
- **Monitor your trades closely**
- **Have a stop loss on every trade**
- **Don't over-leverage**

## Next Steps

1. ✅ Setup Binance API keys
2. ✅ Train a model with `python main.py`
3. ✅ Run dry run: `python live_trading.py`
4. ✅ Monitor logs and Telegram alerts
5. ✅ Enable real trading once confident
6. ✅ Monitor performance daily
7. ✅ Retrain model monthly

---

**Version**: 1.0  
**Last Updated**: January 2026  
**Status**: Production Ready
