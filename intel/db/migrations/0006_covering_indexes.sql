-- Covering indexes for the two queries that dominated a token evaluation.
--
-- Measured 2026-09-05 on a token with 3 952 trades, database holding 2 M trades and 7.3 M
-- transfers: one evaluation issued 1 168 queries taking 5.4 s, of which
--   MAX(price_usd) FROM trades ...   436 calls, 4.17 s   (9.6 ms each)
--   MIN(ts) FROM transfers ...         4 calls, 0.69 s   (172 ms each)
-- Both were resolved through an index that does not carry the column being aggregated, so every
-- matching row had to be fetched from the table. Adding the column to the index lets the
-- aggregate be answered from the index alone.

CREATE INDEX IF NOT EXISTS ix_trades_tok_ts_px ON trades(chain_id, token_address, ts, price_usd);
CREATE INDEX IF NOT EXISTS ix_transfers_tok_ts ON transfers(chain_id, token_address, ts);
