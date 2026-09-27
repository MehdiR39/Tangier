# Quick Start Guide

Get up and running with the Advanced Crypto Trading Strategy in 5 minutes.

## 1. Installation

```bash
# Navigate to project directory
cd crypto_trading_strategy

# Install dependencies
pip install -r requirements.txt

# Install TA-Lib (if not already installed)
# Ubuntu/Debian:
sudo apt-get install ta-lib
pip install TA-Lib

# macOS:
brew install ta-lib
pip install TA-Lib
```

## 2. Configuration

Edit `config/config.py` to customize your strategy:

```python
# Symbols to trade
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]

# Risk management
STOP_LOSS = 0.05  # 5%
TAKE_PROFIT = 0.10  # 10%

# Model parameters
N_FEATURES_TO_SELECT = 20  # Use top 20 features
CONFIDENCE_THRESHOLD = 0.60  # Minimum confidence to trade
```

## 3. Run the Strategy

### Option A: Multi-Coin Strategy (Recommended)

```bash
python main.py
```

This will:
- Fetch data for all configured symbols
- Train LightGBM models
- Run backtests
- Generate portfolio analysis
- Export results to `results/` directory

### Option B: Single Coin Strategy

```python
# Edit main.py and modify the main() function:
results = run_single_coin_strategy("BTCUSDT", ...)
```

### Option C: Walk-Forward Validation

```python
# Edit main.py and uncomment:
results = run_walk_forward_validation(SYMBOLS[0])
```

## 4. Interpret Results

### Console Output

```
================================================================================
BACKTEST RESULTS - BTCUSDT
================================================================================

Capital:
  Initial:          $1.00
  Final (Strategy): $1.35
  Return:           35.00%

Benchmark (Buy & Hold):
  Return:           28.50%
  Outperformance:    6.50%

Trades:
  Total:              45
  Winning:            28
  Losing:             17
  Win Rate:         62.2%

Profitability:
  Avg Win:            2.50%
  Avg Loss:          -1.80%
  Profit Factor:      2.15

Risk Metrics:
  Max Drawdown:       8.50%
  DD Duration:        120 periods
  Sharpe Ratio:       1.45
  Calmar Ratio:       4.12

================================================================================
```

### Portfolio Summary

```
PORTFOLIO SUMMARY

Coins Analyzed: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT

Portfolio Metrics (Equal-Weighted):
  Total Return:          28.50%
  Sharpe Ratio:           1.35
  Calmar Ratio:           3.50
  Avg Win Rate:          58.0%
  Avg Profit Factor:      1.95
  Avg Max Drawdown:       9.20%
```

### Exported Files

Results are saved to `results/` directory:

- `individual_results.csv` - Performance metrics for each coin
- `portfolio_metrics.json` - Portfolio-level metrics
- `correlation_matrix.csv` - Correlation between coin returns

## 5. Customize Strategy

### Adjust Risk Management

```python
# In config/config.py

STOP_LOSS = 0.03  # Tighter stop loss
TAKE_PROFIT = 0.15  # Higher profit target
TRADING_FEE = 0.001  # 0.1% per trade
SLIPPAGE = 0.001  # 0.1% slippage
```

### Change Model Parameters

```python
LGBM_PARAMS = {
    "learning_rate": 0.05,  # Lower = more conservative
    "num_leaves": 31,  # Higher = more complex model
    "max_depth": 7,  # Deeper = more overfitting risk
}

N_FEATURES_TO_SELECT = 15  # Use fewer features for robustness
```

### Enable/Disable Features

```python
ENABLE_CANDLESTICK_PATTERNS = True  # Add pattern recognition
WALK_FORWARD_ENABLED = True  # Use walk-forward validation
USE_SMOTE = True  # Balance training data
USE_ATR_FILTER = True  # Filter signals by volatility
```

## 6. Common Issues & Solutions

### Issue: "ModuleNotFoundError: No module named 'lightgbm'"

**Solution:**
```bash
pip install lightgbm
```

### Issue: "No data available"

**Solution:**
- Check internet connection (Binance API)
- Verify symbol names: "BTCUSDT" not "BTC"
- Check `BINANCE_START_TIME` setting

### Issue: "Model not training"

**Solution:**
- Ensure at least 500 candles of data
- Check for NaN values: `data.isnull().sum()`
- Verify target distribution: `data['Target'].value_counts()`

### Issue: "Poor backtest results"

**Solution:**
1. Check feature engineering for data leakage
2. Verify signal generation logic
3. Analyze individual trades
4. Consider different market regimes
5. Run sensitivity analysis on parameters

## 7. Next Steps

### For Beginners
1. Run the strategy with default settings
2. Review the backtest results
3. Understand the portfolio metrics
4. Read the README.md for detailed explanations

### For Intermediate Users
1. Customize risk management parameters
2. Run walk-forward validation
3. Perform sensitivity analysis
4. Test on additional cryptocurrencies

### For Advanced Users
1. Modify feature engineering
2. Implement custom indicators
3. Add multi-timeframe analysis
4. Deploy to live trading (paper trading first!)

## 8. Performance Benchmarks

Expected performance ranges (after proper bias mitigation):

| Metric | Expected Range |
|--------|-----------------|
| Annual Return | 20-35% |
| Sharpe Ratio | 1.2-1.8 |
| Max Drawdown | 10-18% |
| Win Rate | 50-60% |
| Profit Factor | 1.5-2.5 |

**Note**: Actual results depend on market conditions and parameter tuning.

## 9. Logging

Check logs in `logs/` directory:

```bash
# View latest log
tail -f logs/strategy_*.log

# Search for errors
grep ERROR logs/strategy_*.log

# View specific symbol
grep BTCUSDT logs/strategy_*.log
```

## 10. Support

For detailed information:
- See `README.md` for comprehensive documentation
- Check `config/config.py` for all available parameters
- Review source code in `src/` directory for implementation details

---

**Happy Trading!** 🚀

Remember: Always test thoroughly before deploying with real capital.
