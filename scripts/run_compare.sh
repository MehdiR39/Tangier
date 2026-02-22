#!/usr/bin/env bash
set -euo pipefail

SYMBOLS="${1:-AVAXUSDT,LINKUSDT,BTCUSDT,ETHUSDT,SOLUSDT}"
SYMBOL_WORKERS="${2:-1}"
MODEL_WORKERS="${3:-1}"

if [[ ! -f .env ]]; then
  echo "Missing .env file in project root"
  exit 1
fi

docker run --rm -it \
  --env-file .env \
  -v "$(pwd)":/app \
  -w /app \
  tangier-bot:latest \
  python compare_models.py \
    --symbols "$SYMBOLS" \
    --symbol-workers "$SYMBOL_WORKERS" \
    --model-workers "$MODEL_WORKERS"
