# Tangier Intel — quickstart

Read-only portfolio watcher + moonshot scanner for Robinhood Chain (chain_id 4663).
Architecture, reuse decisions and open questions: [docs/INTEL_ARCHITECTURE.md](docs/INTEL_ARCHITECTURE.md).

## Run locally (Windows, conda env `qrt`)

```bat
C:\Users\Osiris\miniconda3\envs\qrt\python.exe -m pip install -r requirements-intel.txt
set PYTHONIOENCODING=utf-8
C:\Users\Osiris\miniconda3\envs\qrt\python.exe -m pytest tests\intel_tests

REM one-off checks
C:\Users\Osiris\miniconda3\envs\qrt\python.exe -m intel telegram-test
C:\Users\Osiris\miniconda3\envs\qrt\python.exe -m intel --dry-run evaluate --token 0xd18528b39da6464b3662c331a52181ecb15b1e18 --portfolio

REM backfill history for the portfolio tokens (idempotent, resumable)
C:\Users\Osiris\miniconda3\envs\qrt\python.exe -m intel backfill

REM continuous engines (portfolio every 60 s, scanner every 120 s, health on :8787)
scripts\run_intel.bat
```

## Deployment in place (2026-09-02)

The engine runs as the Docker service `tangier-intel` (`restart: unless-stopped`, health on
http://localhost:8787/health, logs `logs/intel.log`). Alerts go to the existing Telegram chat
from `.env`.

**The live database lives in the Docker volume `intel_db`, not in `./data`.** A WAL-mode
SQLite file on a Windows bind mount opened from both the container and the host corrupted
within hours on day one. Rules: never open the live file from Windows; run commands inside
the container; read static copies for analysis.

```bash
docker compose logs -f intel                                   # follow the engine
docker compose restart intel                                   # restart after editing config/intel.yaml
docker compose stop intel                                      # pause alerts
docker compose exec intel python -m intel status               # any CLI command, inside the container
docker compose exec intel python -m intel alerts --last 30
docker compose exec intel python -m intel snapshot             # -> data/intel_snapshot.sqlite (safe to open on the host)
docker compose exec intel python -m intel import-tables --src /app/data/recovered.sqlite   # recovery
```

Automatic online backups are written every 6 h to `data/backups/` (last 4 kept). At
startup the engine runs an integrity check; a corrupt file is quarantined
(`*.corrupt-<stamp>`) and the latest good backup is restored automatically.
`scripts/run_intel.bat` (host mode) must not run at the same time as the container.

## Run in Docker

```bash
cp .env.example .env   # fill TELEGRAM_* (and optionally INTEL_RPC_URL / INTEL_BLOCKSCOUT_API_KEY)
scripts/run_intel.sh   # builds Dockerfile.intel and starts the `intel` service
curl localhost:8787/health
```

## Decision mode (default since 2026-09-02 evening)

`decisions.telegram_mode: decisions` — the user only receives **ACHÈTE** (20 € virtual line,
with the exit plan) and **VENDS TOUT / VENDS LA MOITIÉ** messages, plus the morning digest.
All other alerts are still evaluated and stored (scorecard, audit) but not sent. The virtual
book (`positions`, `decisions` tables) applies: buy on CANDIDATE in an accumulation/confirmed
breakout state with moonshot ≥ 70; sell half on DISTRIBUTION or at x3; sell all on
THESIS_BREAK, confirmed SECURITY_RISK, liquidity −50 % in 24 h, −50 % stop or −35 % trailing
stop after a half exit. User-held tokens are tracked as PORTFOLIO positions from the first
observed price (set `quantity` + `cost_basis_usd` in `config/intel.yaml` for a real entry).
Nothing is ever executed. Switch back with `telegram_mode: alerts` or `both`.

## What arrives on Telegram

* **One daily digest** (07:00 UTC by default, `alerts.daily_digest_hour_utc`): portfolio states and
  actions, top scanner candidates, alert counts, provider health. `python -m intel digest` sends it now.
* **Event alerts only**, deduplicated with cooldowns (`alerts.cooldown_seconds`):
  portfolio token changes state (DISTRIBUTION, THESIS_BREAK, SECURITY_RISK, EXTENDED, BREAKOUT…),
  liquidity drops more than `alerts.lp_drop_pct` in 1h, whale selling/accumulation beyond
  thresholds, holder-growth acceleration, price/holder divergences, moonshot score moving by
  `material_score_delta` points; scanner tokens only when they pass the hard filters with
  moonshot ≥ `scanner_alert_min_moonshot`, cross `scanner.moonshot_alert_threshold`, or turn
  EXTENDED / DISTRIBUTION / SECURITY_RISK.
* No message means nothing material happened. Every candidate alert, sent or suppressed, is in
  the `alerts` table (`python -m intel alerts`).

## Commands

| Command | Purpose |
|---|---|
| `python -m intel run [--once] [--portfolio-only|--scanner-only]` | run engines continuously |
| `python -m intel backfill [--token ADDR] [--blocks N]` | ingest historical transfers/swaps/trades |
| `python -m intel evaluate --token ADDR [--portfolio] [--shallow]` | full pipeline once, prints metrics/scores/state |
| `python -m intel status` | health, provider budgets, last runs, portfolio states |
| `python -m intel alerts --last 30` | recent alerts (sent and suppressed, with reasons) |
| `python -m intel backtest [--token ADDR] [--replay ADDR]` | forward returns / MFE / MAE / survival by score decile |
| `python -m intel telegram-test` | send a test message |
| `python -m intel digest [--print-only]` | send (or print) the daily summary now (includes the alert scorecard) |
| `python -m intel scorecard [--days 3] [--horizon 24h]` | price outcome after each sent alert, per kind and per token |
| `python -m intel migrate` | apply pending migrations |

Global flags: `--dry-run` (log alerts instead of sending), `--db PATH`.

## Configuration

* Secrets and endpoints: `.env` (see `.env.example`, `INTEL_*` variables).
* Tunables: `config/intel.yaml` — portfolio contract addresses (never tickers), weights,
  hard filters, first-meaningful-market heuristic, scanner stages, alert cooldowns.
  Anything omitted falls back to `intel/settings.py::DEFAULT_CONFIG`. Point `INTEL_CONFIG`
  at another YAML to run with different tunables (e.g. a smaller `engine.backfill_max_blocks`
  window on the public RPC).

## First run on the public RPC

The public endpoint weights heavy `eth_getLogs` queries, so the launch-to-date backfill of a
busy token takes tens of minutes. Run `python -m intel backfill` once (resumable; it stores a
cursor per token), or start `run` directly: each cycle ingests up to
`engine.max_blocks_per_cycle` blocks and catches up over a few cycles. Until the launch
history is complete, launch profiles carry the flag `launch_history_incomplete` and the
first-meaningful-market multiples stay `null` (never guessed).

## Alert example (Telegram, HTML)

```
🚨 TAIWAN — DISTRIBUTION

MC: $842.0k | -6.2% 1h | -11.0% 24h
LP: $261.0k | -2.1% 1h | liq/mc 31.0%
Holders: 1,411 | +4.8% 6h | +9.1% 24h
Top20 ex-system: 21.4% → 25.8% (effective 27.1%)
Whale net flow 1h: -$41.2k | 24h: -$120.4k (1↑ 4↓)
...
Moonshot: 74 → 61  (A70 T55 S62 D48 N60)
State: ACCUMULATION → DISTRIBUTION

WHY:
3 top wallets sold >= 20% in 6h while effective concentration increased

ACTION: DO_NOT_ADD
```
