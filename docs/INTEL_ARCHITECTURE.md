# Tangier Intel — architecture, reuse map and open questions

Read-only crypto intelligence for Robinhood Chain (chain_id 4663): a **portfolio watcher**
for tokens you hold and a **moonshot scanner** for newly launched low-cap tokens. Nothing in
`intel/` signs or submits transactions; no private key is ever read.

## 1. What existed before (repository map)

| Area | Existing component | Verdict |
|---|---|---|
| ML trading bot | `main.py`, `live_trading.py`, `src/*` (Binance klines → features → model → backtest) | untouched; unrelated to on-chain monitoring |
| Config | `config/config.py` (flat constants), `.env` via `python-dotenv` | **reused**: same `.env` file and variable names (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`), same `logs/` directory convention |
| Telegram | `src/live_utils.TelegramNotifier` (requests, Markdown) and `scripts/daily_report.send_telegram` (HTML, plain-text fallback, 4096 truncation) | **ported** the daily_report behaviour to async httpx in `intel/alerts/telegram.py` |
| HTTP retry | `scripts/onchain_fetch.get` (exp. backoff on 429/5xx) | **generalised** in `intel/utils/retry.py` + per-provider token buckets |
| Scheduler | none (Windows Task Scheduler `.bat` + `while True` loop in `live_trading.py`) | **new** asyncio scheduler; `scripts/run_intel.bat` follows the existing `.bat` convention |
| Database | none (CSV/JSON files) | **new** SQLite (WAL) with versioned SQL migrations |
| Logging | `logging.basicConfig` with `asctime - name - level - message` | **same format**, plus rotating file and optional JSON |
| Docker | `Dockerfile` (ML deps), `docker-compose.yml` | **extended**: `Dockerfile.intel` (slim) and an `intel` service with health check |
| Tests | none | **new** `tests/intel_tests` (pytest) |

## 2. Verified facts about the chain (2026-09-02)

* RPC `https://rpc.mainnet.chain.robinhood.com`: chain id `0x1237` (4663), block time **~0.10 s**,
  `eth_getLogs` caps at 10 000 logs, ~50k-block windows are fine, 200k blocks time out,
  **batch JSON-RPC returns 429**, generic User-Agents get 403. Rate limiting is weighted:
  an over-large `getLogs` probe is typically followed by a 429, so the client sizes log
  windows from observed density (~4000 logs per call) and cools down after an overflow.
  Expect a full launch-to-date backfill of a busy token (~500k transfers) to take tens of
  minutes on the public endpoint; a production RPC (`INTEL_RPC_URL`) removes this.
* Explorer: `https://robinhoodchain.blockscout.com` (v2 + legacy v1 API). Behind a Cloudflare
  managed challenge for non-browser clients; a browser-like User-Agent passes. Reports
  `x-ratelimit-limit: 180` with a multi-hour reset → treated as a **quota**, not a rate.
* DexScreener chain slug `robinhood`; pairs are **Uniswap v4 pools** (`pairAddress` = 32-byte PoolId).
* Uniswap v4 `PoolManager` = `0x8366a39cc670b4001a1121b8f6a443a643e40951` (verified via Swap events).
  Swap deltas are the swapper's balance deltas (negative = paid into pool) — confirmed against Transfer logs.
* SAYLORMOON and TAIWAN are **EIP-1167 clones of `DopplerERC20V1`** launched through the Doppler
  `Airlock` (`0xeb7c…0862`); their launch pool has a Doppler hook, dynamic fee and
  "rehype" fee re-hypothecation: **one app trade emits three Swap events** (user + 2 hook swaps).
  PAIR is an unverified non-Doppler contract.
* Robinhood app trades route through `RobinHoodSettler` → `EntryPoint` (ERC-4337): `tx.from`
  is a bundler. The economic trader is the address whose net token balance changed in the tx.

## 3. Package layout (`intel/`)

```
intel/
  settings.py        env + YAML config (DEFAULT_CONFIG deep-merged with config/intel.yaml)
  context.py         service container (db, rpc, blockscout, dexscreener, status registry)
  logging_setup.py   structured logging (key=value or JSON)
  health.py          /health and /status HTTP endpoints
  cli.py, __main__   python -m intel {run,backfill,evaluate,status,alerts,telegram-test,backtest,migrate}
  utils/             abi (pure-python keccak, ABI codec), ratelimit, retry, timeutil
  db/                sqlite connection + migrations/0001_initial.sql (append-only snapshots)
  providers/         rpc (JSON-RPC, adaptive log chunking, block↔timestamp), blockscout (quota-aware,
                     cached), dexscreener (chain-filtered), base (status/budget tracking)
  chain/             constants (topics/selectors/privileged sigs), uniswap_v4 (decoders, PoolId,
                     price math), erc20 (metadata/proxy/ownership/simulated transfer), doppler (Airlock)
  ingest/            market (DexScreener→snapshots), pools (Initialize/Swap/ModifyLiquidity),
                     transfers (Transfer replay → holders + point-in-time holder counts),
                     trades (net-delta trade reconstruction), holders (explorer/replay snapshots),
                     security (PASS/WARN/FAIL/UNKNOWN checks)
  metrics/           market, holders, concentration, clustering, whales, trading_quality,
                     liquidity (incl. V4Quoter price impact), launch (first meaningful market),
                     smart_money, narrative, pricing, assemble (point-in-time feature builder)
  scoring/           hard_filters, scores (8 component scores + MOONSHOT), states (state engine)
  alerts/            rules (WHY + ACTION), dedup (cooldown/escalation/cap), telegram, format
  engines/           pipeline (per-token), portfolio_watcher, scanner (stage 1/2/3), scheduler
  backtest/          forward returns, MFE/MAE, survival, per-decile summary, point-in-time replay
```

### Data flow per token
1. **Market** (DexScreener) → `pairs`, `pair_snapshots`, `token_snapshots` (+ quote-asset USD snapshots).
2. **Pools** → `Initialize` located from the pair creation timestamp (block binary search) →
   `pairs.currency0/1, hooks, fee`; `Swap`/`ModifyLiquidity` → `swap_events`, `liquidity_events`.
3. **Transfers** (RPC, idempotent by tx/log index, cursor per token) → `transfers`; balances
   replayed into `holders`; `holder_count_snapshots` emitted every ~6000 blocks (source `rpc_replay`).
4. **Trades** = net token delta per non-system address inside each tx, priced with user-level
   swaps only (hook-internal swaps excluded) → `trades` with quality flags.
5. **Security** (RPC + Blockscout, every 6 h) → `contract_security`.
6. **Metrics** (`metrics/assemble.py`, all reads `ts <= as_of_ts`) → hard filters → scores →
   state → `token_scores` (with `model_version`), `token_states`, `state_transitions`.
7. **Alerts** → `alerts` (sent or suppressed with reason) → Telegram (HTML, plain fallback).

### Source priority and data quality
on-chain (RPC) > explorer (Blockscout) > DexScreener > metadata. Missing values stay `NULL`
and surface in `quality_flags` (e.g. `mc_from_total_supply`, `quote_price_approx`,
`price_impact_approx`, `topn_only`, `security_unknown`). UNKNOWN is never PASS.

## 4. Scores and states
* `SURVIVAL`, `TRACTION`, `ASYMMETRY`, `DISTRIBUTION`, `NARRATIVE` (0-100) → `MOONSHOT` with
  configurable weights (`scoring.weights`, default 30/25/20/15/10).
* `ORGANIC_VOLUME` (heuristic, 0-100 or UNKNOWN), `SMART_MONEY` (UNKNOWN until ≥5 tokens /
  ≥3 closed positions of history), `RUG_RISK` (0-100, higher = worse).
* Hard filters (config `hard_filters`) run first; `unknowns` block a pass without rejecting.
* States: DISCOVER, EARLY_ACCUMULATION, ACCUMULATION, BREAKOUT, BREAKOUT_CONFIRMED, WATCH,
  EXTENDED, DISTRIBUTION, THESIS_BREAK, SECURITY_RISK, REJECTED. Actions: HOLD, WATCH,
  DO_NOT_ADD, REVIEW_EXIT, CANDIDATE, REJECT.

## 5. Backtestability
Every score row stores `as_of_ts`, `model_version`, the full metrics JSON and explanations.
`python -m intel backtest` computes forward returns (1h/6h/24h/3d/7d), MFE/MAE, 7-day
survival/rug rate per moonshot decile and per state, plus rank correlations of each
component with 24 h forward return. `--replay <token>` recomputes historical scores
through the same feature builder with `live=False`, i.e. only snapshots/trades known at
each timestamp.

## 6. Ambiguities and decisions taken
1. **No DB/scheduler existed.** SQLite + asyncio scheduler were added; Postgres can replace
   SQLite later by swapping `db/connection.py` (SQL is plain).
2. **Blockscout quota.** Without an API key the explorer allows ~180 calls per window.
   Explorer calls are therefore quota-aware (`essential` flag, reserve of 25 calls) and the
   heavy lifting (holders, trades, launch history) is reconstructed from RPC. Set
   `INTEL_BLOCKSCOUT_API_KEY` to lift the quota.
3. **Public RPC limits.** 4 rps / 2 concurrent by default; set `INTEL_RPC_URL` to a
   production endpoint and raise `INTEL_RPC_RPS`.
4. **Uniswap v4 liquidity in USD.** Concentrated liquidity has no reserve; USD liquidity comes
   from DexScreener, while on-chain depth uses the V4Quoter (exact) or virtual reserves
   (approximation, flagged).
5. **Quote-asset pricing.** USDG is treated as 1.0; tokenised stocks (MSTR/SPY/TSM/NVDA) and
   WETH are priced from DexScreener snapshots nearest in time (flag `quote_price_approx`
   when only the current price is known).
6. **Circulating supply** is not observable on-chain for Doppler tokens (vesting, hook-held
   inventory); market cap falls back to DexScreener, else price × total supply (flagged).
7. **Portfolio quantity / cost basis / entry time** were not provided → `null` placeholders in
   `config/intel.yaml`; alerts show market context only until filled.
8. **Smart money** starts UNKNOWN by design; it becomes SCORED as wallet histories accumulate.
9. **Trader identity.** Because of settler/ERC-4337 routing, unique traders are counted from
   token-transfer net deltas; wallets funded by the settler share a "funding source", so hub
   addresses are excluded from clustering evidence.
10. **Alert chat.** Alerts use the existing `TELEGRAM_*` chat unless `INTEL_TELEGRAM_*` is set.
11. **Doppler `isPoolLocked()` is not a honeypot signal.** Verified on SAYLORMOON: the view
    returns `true` (its `pool()` is `0xdead…`) while swaps, sell quotes and hundreds of
    reconstructed sells succeed. It is reported as WARN; `honeypot_indicators` combines the
    transfer simulation, the V4Quoter sell quote and observed successful sells (≥5 distinct
    sellers in 24 h) and only FAILs on positive evidence of blocked selling.
12. **Partial transfer history.** A token first seen mid-life has replayed balances only for
    wallets that moved inside the ingested window. Until `launch_history_complete` (mint from
    0x0 seen), holder counts and concentration come from the explorer snapshots, new/lost
    holders and first-meaningful-market are withheld, and every score row carries
    `partial_transfer_history`. `python -m intel backfill` fills creation → first ingested
    block backwards, rebuilds balances and regenerates point-in-time holder counts.
13. **Pass-through routers.** Unlabeled contracts that receive and forward the same amount in
    one transaction (settler → router → user chains) are ignored for trade attribution, never
    counted as round trips, and treated as hubs by the clustering heuristics.
14. **Progressive history on a public RPC.** A token's first pass ingests only the last
    `engine.initial_lookback_blocks` (~1 day) so it is evaluated within minutes; a third
    scheduler loop (`history`, every 45 s, one token, `history_blocks_per_cycle`) then fills
    creation → forward-start backwards, rebuilds balances and regenerates point-in-time holder
    counts. Cursors: `transfers:<t>` (forward), `transfers_fwd_start:<t>`, `transfers_back:<t>`,
    `transfers_rebuilt:<t>`. All heavy ingestion goes through one lock so the portfolio
    watcher, the scanner and the history loop take turns on the rate-limited endpoint, with
    strict priority to portfolio tokens (`TokenPipeline.priority_waiting`): scanner tokens and
    the history loop yield whenever a watched position is waiting to be evaluated.
15. **RPC backoff.** The public endpoint throttles per heavy query, not per second; a long pause
    buys no throughput, so 429 backoff is short and bounded (≤10 s) and log windows shrink
    with observed density instead.
16. **Tokenised stocks are not candidates.** Robinhood mints "… • Robinhood Token" assets
    (MSTR, TSM, F, PFE…) continuously; they appear as base tokens of USDG pools and were being
    scored as moonshots on the first day. They are excluded by `scanner.exclude_name_patterns`
    and treated as quote assets.
17. **History completeness is coverage, not a mint.** A `Transfer` from 0x0 inside the window
    proves nothing for continuously minted tokens; completeness now means the ingested range
    reaches the creation block (or the earliest pool creation when the creation block is unknown).
18. **Transfer simulation needs a real balance.** Replayed balances can be partial; simulating
    from a wallet that is actually empty reverts and looked like a honeypot. The check now reads
    `balanceOf` first, and a revert contradicted by observed sells is a WARN, not a FAIL.

## 6b. Day-one signal review → scoring v0.2 (2026-09-02, n=25 scanner tokens, hours horizon)
Rank correlation of first-score metrics with realised return: liquidity +0.51, volume 24h
+0.38, market cap +0.31, median trade size +0.42, survival +0.32, drawdown-from-ATH +0.33;
buy/sell ratio −0.55, return_1h/24h at signal −0.29/−0.28, traction −0.29, asymmetry −0.29,
price impact −0.32; composite moonshot −0.07 (no edge). Holder growth 24h was unmeasured for
every token at first score. Changes: weights survival 0.30 / asymmetry 0.20 / traction 0.20 /
distribution 0.20 / narrative 0.10; CANDIDATE requires liquidity ≥ $100k, age ≥ 24h,
buy/sell ≤ 2, return_1h ≤ +50% and measured 24h holder growth (`candidate_eligible`);
traction capped at 50 without holder growth; scanner alerts need liquidity ≥ $100k and
"passed hard filters" only from moonshot 70. `MODEL_VERSION` bumped so the backtest can
compare v0.1 and v0.2 rows. Sample is one afternoon: treat as hypotheses to re-test.

## 6c. Decision layer and its first night (2026-09-03)
`intel/engines/decisions.py` turns states into ACHÈTE / VENDS messages on a virtual book
(`positions`, `decisions`). Night one exposed two rules of thumb now enforced: (1) a closed
portfolio position is not re-followed while its state is negative nor within 12 h, and the
same decision kind is never repeated within 24 h for a token (a loop had sent one sell ~150
times); (2) a THESIS_BREAK resting only on the distance to an all-time high that predates the
position is ignored — the sell rule uses the peak reached since entry (−70 %). Retention:
raw events of dead scanner tokens are pruned after 2 days, dense snapshots after 7/14 days;
the scanner demotes scored-but-uninteresting tokens to DORMANT so ingestion stops.

## 7. Validation performed (2026-09-02, public RPC, dry-run Telegram)
* `evaluate --portfolio` on SAYLORMOON over a 150k-block window: 5.6k transfers, 2.2k swaps,
  ~0.8k reconstructed trades; reconstructed median trade price 0.00356 vs DexScreener 0.00354.
* Security: verified Doppler clone, no mint/blacklist/pause/tax functions, sell quote OK,
  transfer simulation OK → overall WARN (owner is the Airlock, `isPoolLocked` view, balance-limit
  functions present). Hard filters pass; state WATCH / action HOLD; moonshot 63.
* Alerts emitted (dry-run): state change, moonshot up; dedup/cooldown persisted in `alerts`.
