-- Journal of every order the executor considered, whether or not it was submitted.
-- This is the audit trail: a refusal is as important to record as a submission, and the daily
-- spending limits are computed from it rather than from the engine's own view of the world.

CREATE TABLE IF NOT EXISTS executions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  chain_id INTEGER NOT NULL,
  decision_id INTEGER,                 -- decisions.id that asked for this order
  token_address TEXT NOT NULL,
  label TEXT,
  kind TEXT NOT NULL,                  -- BUY | SELL_HALF | SELL_ALL
  size_eur REAL,
  quote_address TEXT,
  amount_in TEXT,                      -- raw units, as a decimal string
  min_amount_out TEXT,                 -- raw units after the slippage limit
  quoted_amount_out TEXT,
  slippage_pct REAL,
  mode TEXT NOT NULL,                  -- dry_run | live
  status TEXT NOT NULL,                -- REFUSED | BUILT | SUBMITTED | CONFIRMED | FAILED
  refused_reason TEXT,
  tx_hash TEXT,
  gas_used INTEGER,
  error TEXT,
  calldata TEXT,
  model_version TEXT
);
CREATE INDEX IF NOT EXISTS ix_executions_ts ON executions(chain_id, ts);
CREATE INDEX IF NOT EXISTS ix_executions_token ON executions(chain_id, token_address, ts);
CREATE UNIQUE INDEX IF NOT EXISTS ux_executions_decision ON executions(chain_id, decision_id) WHERE decision_id IS NOT NULL;
