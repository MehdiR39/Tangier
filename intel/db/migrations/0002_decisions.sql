-- Decision layer: a virtual position book and the BUY / SELL messages derived from it.

CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chain_id INTEGER NOT NULL, token_address TEXT NOT NULL, label TEXT,
  kind TEXT NOT NULL,                     -- VIRTUAL (engine buy) / PORTFOLIO (user holds)
  opened_ts INTEGER NOT NULL, entry_price REAL, size_eur REAL,
  status TEXT NOT NULL DEFAULT 'OPEN',    -- OPEN / HALF / CLOSED
  peak_price REAL, half_ts INTEGER, half_price REAL, closed_ts INTEGER, close_price REAL, close_reason TEXT,
  realized_eur REAL, model_version TEXT, notes TEXT
);
CREATE INDEX IF NOT EXISTS ix_positions_token ON positions(chain_id, token_address, status);

CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, chain_id INTEGER NOT NULL, token_address TEXT NOT NULL, label TEXT,
  kind TEXT NOT NULL,                     -- BUY / SELL_ALL / SELL_HALF
  reason TEXT NOT NULL, price REAL, size_eur REAL, position_id INTEGER,
  sent INTEGER NOT NULL DEFAULT 0, telegram_message_id TEXT, send_error TEXT,
  metrics_json TEXT, model_version TEXT
);
CREATE INDEX IF NOT EXISTS ix_decisions_token_ts ON decisions(chain_id, token_address, ts);
