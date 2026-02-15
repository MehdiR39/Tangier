#!/usr/bin/env bash
set -euo pipefail

SYMBOL="${1:-AVAXUSDT}"
TRIALS="${2:-80}"

if [[ ! -f .env ]]; then
  echo "Missing .env file in project root"
  exit 1
fi

docker run --rm -it \
  --env-file .env \
  -v "$(pwd)":/app \
  -w /app \
  tangier-bot:latest \
  python optimize_strategy.py --symbol "$SYMBOL" --trials "$TRIALS"
