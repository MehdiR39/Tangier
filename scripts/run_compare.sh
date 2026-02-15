#!/usr/bin/env bash
set -euo pipefail

SYMBOLS="${1:-AVAXUSDT,LINKUSDT,BTCUSDT,ETHUSDT,SOLUSDT}"

if [[ ! -f .env ]]; then
  echo "Missing .env file in project root"
  exit 1
fi

docker run --rm -it \
  --env-file .env \
  -v "$(pwd)":/app \
  -w /app \
  tangier-bot:latest \
  python compare_models.py --symbols "$SYMBOLS"
