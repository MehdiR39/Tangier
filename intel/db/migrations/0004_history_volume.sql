-- Real tradeable depth. The virtual reserve of in-range liquidity massively overstates depth for
-- concentrated (launchpad) positions: tokens with $1 of book were passing a $20k filter. What can
-- actually be traded is measured by what WAS traded, so each bucket now carries its quote volume.

ALTER TABLE history_series ADD COLUMN vol_quote REAL;
ALTER TABLE history_series ADD COLUMN n_trades INTEGER;
