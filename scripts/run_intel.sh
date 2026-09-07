#!/usr/bin/env bash
# Tangier Intel in Docker: build once, then run the engines (health on :8787).
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then
  echo "Missing .env file in project root (see .env.example)"
  exit 1
fi
docker compose build intel
docker compose up -d intel
docker compose logs -f intel
