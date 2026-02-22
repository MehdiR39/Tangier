#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-AVAXUSDT}"
TRIALS="${2:-80}"
WORKERS="${3:-1}"

if [[ ! -f .env ]]; then
  echo "Missing .env file in project root"
  exit 1
fi

if [[ "$TARGET" == *","* ]]; then
  SYMBOL_ARGS=(--symbols "$TARGET")
else
  SYMBOL_ARGS=(--symbol "$TARGET")
fi

docker run --rm -it \
  --env-file .env \
  -v "$(pwd)":/app \
  -w /app \
  tangier-bot:latest \
  python optimize_strategy.py \
    "${SYMBOL_ARGS[@]}" \
    --trials "$TRIALS" \
    --workers "$WORKERS"
