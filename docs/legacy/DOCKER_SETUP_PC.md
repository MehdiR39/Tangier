# Docker Setup (Mac -> PC)

## 1) On Mac (development machine)

1. Commit/push your latest code.
2. Make sure these files exist:
   - `Dockerfile`
   - `docker-compose.yml`
   - `.dockerignore`
   - `scripts/run_opt.sh`
   - `scripts/run_compare.sh`
   - `scripts/run_main.sh`
   - `scripts/run_live.sh`

## 2) On PC (compute/prod machine)

1. Install Docker Desktop.
2. Clone project repository.
3. Create `.env` in project root with Binance/Telegram keys.
4. Build image:

```bash
docker build -t tangier-bot:latest .
```

## 3) Run commands on PC

### Optimization

```bash
./scripts/run_opt.sh AVAXUSDT 120
```

### Compare models

```bash
./scripts/run_compare.sh "AVAXUSDT,LINKUSDT,BTCUSDT,ETHUSDT,SOLUSDT" 12
# Optional model filter:
# ./scripts/run_compare.sh "ETHUSDT" 12 "lgbm,xgboost"
```

### Main backtest

```bash
./scripts/run_main.sh AVAXUSDT lgbm
```

### Live trading

```bash
./scripts/run_live.sh
```

## 4) Safety notes for live

- Keep API keys only in `.env` on PC.
- Disable Binance withdrawals on API key.
- Whitelist PC IP in Binance API settings.
- Start with dry-run / paper setup first.
