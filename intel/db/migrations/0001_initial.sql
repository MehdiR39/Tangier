-- Tangier Intel initial schema. Append-only time series: snapshots are never overwritten.
-- Conventions: ts = unix seconds UTC; addresses lower-case hex; big integers stored as TEXT (wei).

CREATE TABLE IF NOT EXISTS tokens (
  chain_id INTEGER NOT NULL,
  address TEXT NOT NULL,
  name TEXT, symbol TEXT, decimals INTEGER,
  total_supply TEXT,
  creator_address TEXT, creation_tx TEXT, creation_block INTEGER, creation_ts INTEGER,
  first_seen_ts INTEGER NOT NULL,
  launchpad TEXT,                -- e.g. doppler
  proxy_type TEXT, implementation TEXT, is_verified INTEGER,
  is_portfolio INTEGER NOT NULL DEFAULT 0,
  raw_json TEXT,
  updated_ts INTEGER NOT NULL,
  PRIMARY KEY (chain_id, address)
);

CREATE TABLE IF NOT EXISTS token_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, chain_id INTEGER NOT NULL, token_address TEXT NOT NULL,
  source TEXT NOT NULL, block_number INTEGER,
  price_usd REAL, price_native REAL, market_cap REAL, fdv REAL,
  circulating_supply REAL, total_supply REAL,
  liquidity_usd REAL, volume_24h REAL, holder_count INTEGER,
  quality_flags TEXT, raw_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_token_snapshots_tok_ts ON token_snapshots(chain_id, token_address, ts);

CREATE TABLE IF NOT EXISTS pairs (
  chain_id INTEGER NOT NULL,
  pair_id TEXT NOT NULL,          -- Uniswap v4 PoolId (bytes32) or pair contract address
  token_address TEXT NOT NULL,
  quote_address TEXT, quote_symbol TEXT,
  dex TEXT, version TEXT, hooks TEXT, fee INTEGER, tick_spacing INTEGER,
  currency0 TEXT, currency1 TEXT, token_is_currency0 INTEGER,
  created_ts INTEGER, created_block INTEGER,
  source TEXT NOT NULL, raw_json TEXT,
  first_seen_ts INTEGER NOT NULL, updated_ts INTEGER NOT NULL,
  PRIMARY KEY (chain_id, pair_id)
);
CREATE INDEX IF NOT EXISTS ix_pairs_token ON pairs(chain_id, token_address);

CREATE TABLE IF NOT EXISTS pair_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, chain_id INTEGER NOT NULL, pair_id TEXT NOT NULL, token_address TEXT NOT NULL,
  source TEXT NOT NULL, block_number INTEGER,
  price_usd REAL, price_native REAL,
  liquidity_usd REAL, liquidity_base REAL, liquidity_quote REAL,
  fdv REAL, market_cap REAL,
  vol_5m REAL, vol_1h REAL, vol_6h REAL, vol_24h REAL,
  buys_5m INTEGER, sells_5m INTEGER, buys_1h INTEGER, sells_1h INTEGER,
  buys_6h INTEGER, sells_6h INTEGER, buys_24h INTEGER, sells_24h INTEGER,
  pc_5m REAL, pc_1h REAL, pc_6h REAL, pc_24h REAL,
  sqrt_price_x96 TEXT, liquidity_raw TEXT, tick INTEGER,
  quality_flags TEXT, raw_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_pair_snapshots_pair_ts ON pair_snapshots(chain_id, pair_id, ts);
CREATE INDEX IF NOT EXISTS ix_pair_snapshots_tok_ts ON pair_snapshots(chain_id, token_address, ts);

CREATE TABLE IF NOT EXISTS holders (
  chain_id INTEGER NOT NULL, token_address TEXT NOT NULL, address TEXT NOT NULL,
  balance TEXT NOT NULL DEFAULT '0',      -- current replayed balance (wei)
  first_seen_block INTEGER, first_seen_ts INTEGER,
  last_change_block INTEGER, last_change_ts INTEGER,
  is_contract INTEGER, is_system INTEGER NOT NULL DEFAULT 0, system_label TEXT,
  PRIMARY KEY (chain_id, token_address, address)
);
CREATE INDEX IF NOT EXISTS ix_holders_balance ON holders(chain_id, token_address, is_system);

CREATE TABLE IF NOT EXISTS holder_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, chain_id INTEGER NOT NULL, token_address TEXT NOT NULL,
  source TEXT NOT NULL, block_number INTEGER,
  address TEXT NOT NULL, balance TEXT NOT NULL, balance_float REAL, rank INTEGER,
  is_system INTEGER NOT NULL DEFAULT 0, system_label TEXT
);
CREATE INDEX IF NOT EXISTS ix_holder_snapshots_tok_ts ON holder_snapshots(chain_id, token_address, ts);

CREATE TABLE IF NOT EXISTS holder_count_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, chain_id INTEGER NOT NULL, token_address TEXT NOT NULL,
  source TEXT NOT NULL, block_number INTEGER,
  holder_count INTEGER, holder_count_ex_system INTEGER, transfers_count INTEGER,
  quality_flags TEXT
);
CREATE INDEX IF NOT EXISTS ix_holder_count_tok_ts ON holder_count_snapshots(chain_id, token_address, ts);

CREATE TABLE IF NOT EXISTS wallets (
  chain_id INTEGER NOT NULL, address TEXT NOT NULL,
  is_contract INTEGER, label TEXT, system_kind TEXT,
  first_seen_ts INTEGER, first_seen_block INTEGER,
  funding_source TEXT, funding_tx TEXT, funding_ts INTEGER,
  raw_json TEXT, updated_ts INTEGER NOT NULL,
  PRIMARY KEY (chain_id, address)
);

CREATE TABLE IF NOT EXISTS wallet_token_positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, chain_id INTEGER NOT NULL, token_address TEXT NOT NULL, address TEXT NOT NULL,
  source TEXT NOT NULL, block_number INTEGER,
  balance TEXT NOT NULL, balance_float REAL, supply_pct REAL, usd_value REAL,
  cost_basis_usd REAL, avg_entry_price_usd REAL, realized_pnl_usd REAL, entry_ts INTEGER,
  quality_flags TEXT
);
CREATE INDEX IF NOT EXISTS ix_wtp_tok_addr_ts ON wallet_token_positions(chain_id, token_address, address, ts);

CREATE TABLE IF NOT EXISTS wallet_flows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, chain_id INTEGER NOT NULL, token_address TEXT NOT NULL, address TEXT NOT NULL,
  window TEXT NOT NULL, source TEXT NOT NULL, block_number INTEGER,
  gross_buy_usd REAL, gross_sell_usd REAL, net_buy_usd REAL,
  buy_count INTEGER, sell_count INTEGER, balance_delta TEXT, balance_delta_float REAL,
  position_change_pct REAL, is_whale INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_wallet_flows_tok_ts ON wallet_flows(chain_id, token_address, ts);

CREATE TABLE IF NOT EXISTS transfers (
  chain_id INTEGER NOT NULL, tx_hash TEXT NOT NULL, log_index INTEGER NOT NULL,
  block_number INTEGER NOT NULL, ts INTEGER,
  token_address TEXT NOT NULL, from_address TEXT NOT NULL, to_address TEXT NOT NULL,
  value TEXT NOT NULL, source TEXT NOT NULL,
  PRIMARY KEY (chain_id, tx_hash, log_index)
);
CREATE INDEX IF NOT EXISTS ix_transfers_tok_block ON transfers(chain_id, token_address, block_number);
CREATE INDEX IF NOT EXISTS ix_transfers_from ON transfers(chain_id, token_address, from_address);
CREATE INDEX IF NOT EXISTS ix_transfers_to ON transfers(chain_id, token_address, to_address);

CREATE TABLE IF NOT EXISTS swap_events (
  chain_id INTEGER NOT NULL, tx_hash TEXT NOT NULL, log_index INTEGER NOT NULL,
  block_number INTEGER NOT NULL, ts INTEGER,
  pair_id TEXT NOT NULL, sender TEXT NOT NULL,
  amount0 TEXT NOT NULL, amount1 TEXT NOT NULL,
  sqrt_price_x96 TEXT NOT NULL, liquidity TEXT NOT NULL, tick INTEGER, fee INTEGER,
  source TEXT NOT NULL,
  PRIMARY KEY (chain_id, tx_hash, log_index)
);
CREATE INDEX IF NOT EXISTS ix_swap_events_pair_block ON swap_events(chain_id, pair_id, block_number);

CREATE TABLE IF NOT EXISTS liquidity_events (
  chain_id INTEGER NOT NULL, tx_hash TEXT NOT NULL, log_index INTEGER NOT NULL,
  block_number INTEGER NOT NULL, ts INTEGER,
  pair_id TEXT NOT NULL, sender TEXT NOT NULL,
  tick_lower INTEGER, tick_upper INTEGER, liquidity_delta TEXT NOT NULL, salt TEXT,
  source TEXT NOT NULL,
  PRIMARY KEY (chain_id, tx_hash, log_index)
);
CREATE INDEX IF NOT EXISTS ix_liquidity_events_pair_block ON liquidity_events(chain_id, pair_id, block_number);

CREATE TABLE IF NOT EXISTS trades (
  chain_id INTEGER NOT NULL, tx_hash TEXT NOT NULL, token_address TEXT NOT NULL, trader TEXT NOT NULL,
  block_number INTEGER NOT NULL, ts INTEGER, log_index INTEGER,
  pair_id TEXT, side TEXT NOT NULL,             -- BUY / SELL
  token_amount TEXT NOT NULL, token_amount_float REAL,
  quote_address TEXT, quote_amount_float REAL,
  price_native REAL, price_usd REAL, usd_value REAL,
  swap_log_count INTEGER, source TEXT NOT NULL, quality_flags TEXT,
  PRIMARY KEY (chain_id, tx_hash, token_address, trader)
);
CREATE INDEX IF NOT EXISTS ix_trades_tok_ts ON trades(chain_id, token_address, ts);
CREATE INDEX IF NOT EXISTS ix_trades_tok_block ON trades(chain_id, token_address, block_number);
CREATE INDEX IF NOT EXISTS ix_trades_trader ON trades(chain_id, trader, ts);

CREATE TABLE IF NOT EXISTS contract_security (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, chain_id INTEGER NOT NULL, token_address TEXT NOT NULL,
  source TEXT NOT NULL, block_number INTEGER,
  check_name TEXT NOT NULL, status TEXT NOT NULL,   -- PASS / WARN / FAIL / UNKNOWN
  detail TEXT, evidence_json TEXT, model_version TEXT
);
CREATE INDEX IF NOT EXISTS ix_contract_security_tok_ts ON contract_security(chain_id, token_address, ts);

CREATE TABLE IF NOT EXISTS launch_profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, chain_id INTEGER NOT NULL, token_address TEXT NOT NULL,
  source TEXT NOT NULL, model_version TEXT NOT NULL,
  raw_first_trade_ts INTEGER, raw_first_trade_block INTEGER, raw_first_trade_price_usd REAL, raw_first_trade_price_native REAL,
  fmm_ts INTEGER, fmm_block INTEGER, fmm_price_usd REAL, fmm_price_native REAL, fmm_market_cap REAL,
  fmm_reached INTEGER NOT NULL DEFAULT 0,
  ath_price_usd REAL, ath_ts INTEGER, ath_market_cap REAL,
  heuristic_params_json TEXT, quality_flags TEXT
);
CREATE INDEX IF NOT EXISTS ix_launch_profiles_tok_ts ON launch_profiles(chain_id, token_address, ts);

CREATE TABLE IF NOT EXISTS token_scores (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, chain_id INTEGER NOT NULL, token_address TEXT NOT NULL,
  model_version TEXT NOT NULL, as_of_ts INTEGER NOT NULL, block_number INTEGER,
  survival REAL, traction REAL, asymmetry REAL, distribution REAL, organic_volume REAL,
  smart_money REAL, rug_risk REAL, narrative REAL, moonshot REAL,
  hard_filter_pass INTEGER, hard_filter_reasons TEXT,
  state TEXT, prev_state TEXT, action TEXT,
  metrics_json TEXT, explain_json TEXT, quality_flags TEXT
);
CREATE INDEX IF NOT EXISTS ix_token_scores_tok_ts ON token_scores(chain_id, token_address, ts);

CREATE TABLE IF NOT EXISTS token_states (
  chain_id INTEGER NOT NULL, token_address TEXT NOT NULL,
  state TEXT NOT NULL, since_ts INTEGER NOT NULL, last_eval_ts INTEGER NOT NULL,
  moonshot REAL, action TEXT, reason TEXT,
  PRIMARY KEY (chain_id, token_address)
);

CREATE TABLE IF NOT EXISTS state_transitions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, chain_id INTEGER NOT NULL, token_address TEXT NOT NULL,
  from_state TEXT, to_state TEXT NOT NULL, reason TEXT, score_id INTEGER, model_version TEXT
);
CREATE INDEX IF NOT EXISTS ix_state_transitions_tok_ts ON state_transitions(chain_id, token_address, ts);

CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, chain_id INTEGER NOT NULL, token_address TEXT,
  severity TEXT NOT NULL, kind TEXT NOT NULL, dedup_key TEXT NOT NULL,
  title TEXT NOT NULL, body TEXT NOT NULL, why TEXT, action TEXT,
  sent INTEGER NOT NULL DEFAULT 0, sent_ts INTEGER, telegram_message_id TEXT, send_error TEXT,
  suppressed INTEGER NOT NULL DEFAULT 0, suppress_reason TEXT,
  payload_json TEXT, model_version TEXT
);
CREATE INDEX IF NOT EXISTS ix_alerts_dedup ON alerts(dedup_key, ts);
CREATE INDEX IF NOT EXISTS ix_alerts_tok_ts ON alerts(chain_id, token_address, ts);

CREATE TABLE IF NOT EXISTS portfolio_positions (
  chain_id INTEGER NOT NULL, token_address TEXT NOT NULL,
  label TEXT, quantity REAL, cost_basis_usd REAL, entry_ts INTEGER,
  active INTEGER NOT NULL DEFAULT 1, notes TEXT, updated_ts INTEGER NOT NULL,
  PRIMARY KEY (chain_id, token_address)
);

CREATE TABLE IF NOT EXISTS discovery_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, chain_id INTEGER NOT NULL, token_address TEXT NOT NULL, pair_id TEXT,
  source TEXT NOT NULL, block_number INTEGER,
  stage INTEGER NOT NULL, passed INTEGER NOT NULL, reason TEXT, metrics_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_discovery_tok_ts ON discovery_events(chain_id, token_address, ts);
CREATE INDEX IF NOT EXISTS ix_discovery_ts ON discovery_events(ts);

CREATE TABLE IF NOT EXISTS scanner_candidates (
  chain_id INTEGER NOT NULL, token_address TEXT NOT NULL,
  first_seen_ts INTEGER NOT NULL, last_seen_ts INTEGER NOT NULL,
  discovery_source TEXT, pair_id TEXT,
  stage_reached INTEGER NOT NULL DEFAULT 0, last_stage_ts INTEGER,
  status TEXT NOT NULL DEFAULT 'NEW',        -- NEW / ACTIVE / REJECTED / DORMANT
  reject_reason TEXT, next_eval_ts INTEGER,
  PRIMARY KEY (chain_id, token_address)
);

CREATE TABLE IF NOT EXISTS wallet_clusters (
  cluster_id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, chain_id INTEGER NOT NULL, token_address TEXT,
  confidence REAL NOT NULL, size INTEGER NOT NULL, evidence_json TEXT, model_version TEXT
);
CREATE TABLE IF NOT EXISTS wallet_cluster_members (
  cluster_id INTEGER NOT NULL, address TEXT NOT NULL, confidence REAL NOT NULL, evidence_json TEXT,
  PRIMARY KEY (cluster_id, address)
);
CREATE INDEX IF NOT EXISTS ix_cluster_members_addr ON wallet_cluster_members(address);

CREATE TABLE IF NOT EXISTS provider_status (
  provider TEXT PRIMARY KEY,
  last_ok_ts INTEGER, last_error_ts INTEGER, last_error TEXT,
  consecutive_errors INTEGER NOT NULL DEFAULT 0,
  calls_total INTEGER NOT NULL DEFAULT 0, calls_failed INTEGER NOT NULL DEFAULT 0,
  rate_limited_count INTEGER NOT NULL DEFAULT 0, avg_latency_ms REAL,
  updated_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS engine_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  engine TEXT NOT NULL, started_ts INTEGER NOT NULL, finished_ts INTEGER,
  ok INTEGER, tokens_processed INTEGER, alerts_sent INTEGER, error TEXT, stats_json TEXT
);

CREATE TABLE IF NOT EXISTS sync_cursors (
  name TEXT PRIMARY KEY, block_number INTEGER NOT NULL, ts INTEGER NOT NULL, updated_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS api_cache (
  key TEXT PRIMARY KEY, value TEXT NOT NULL, created_ts INTEGER NOT NULL, expires_ts INTEGER
);

CREATE TABLE IF NOT EXISTS block_timestamps (
  chain_id INTEGER NOT NULL, block_number INTEGER NOT NULL, ts INTEGER NOT NULL,
  PRIMARY KEY (chain_id, block_number)
);
