#!/usr/bin/env bash
set -euo pipefail

SYMBOLS="${1:-AVAXUSDT,LINKUSDT,BTCUSDT,ETHUSDT,SOLUSDT}"
WORKERS="${2:-1}"
MODELS="${3:-}"

if [[ ! -f .env ]]; then
  echo "Missing .env file in project root"
  exit 1
fi

CMD=(
  docker run --rm -it
  --env-file .env
  -v "$(pwd)":/app
  -w /app
  tangier-bot:latest
  python compare_models.py
  --symbols "$SYMBOLS"
  --workers "$WORKERS"
)

if [[ -n "$MODELS" ]]; then
  CMD+=(--models "$MODELS")
fi

"${CMD[@]}"
