-- Reconstructed price history from on-chain Swap events, for real backtests.
-- Built once per token, replayed many times. Downsampled to one point per bucket.

CREATE TABLE IF NOT EXISTS history_series (
  chain_id INTEGER NOT NULL, token_address TEXT NOT NULL, ts INTEGER NOT NULL,
  price_quote REAL NOT NULL,          -- price of 1 token in quote units (exact, from sqrtPriceX96)
  liquidity_quote REAL,               -- quote-side virtual reserve (depth proxy)
  block_number INTEGER,
  PRIMARY KEY (chain_id, token_address, ts)
);
CREATE INDEX IF NOT EXISTS ix_history_series_tok ON history_series(chain_id, token_address, ts);

CREATE TABLE IF NOT EXISTS history_meta (
  chain_id INTEGER NOT NULL, token_address TEXT NOT NULL, pool_id TEXT NOT NULL,
  quote_address TEXT, quote_symbol TEXT, token_decimals INTEGER, quote_decimals INTEGER,
  from_block INTEGER, to_block INTEGER, first_ts INTEGER, last_ts INTEGER,
  n_swaps INTEGER, n_points INTEGER, built_ts INTEGER NOT NULL, error TEXT,
  PRIMARY KEY (chain_id, token_address, pool_id)
);
