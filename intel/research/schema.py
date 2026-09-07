"""Tables for the research dataset. Own file, so the live pipeline cannot be affected."""
import sqlite3

DDL = """
PRAGMA journal_mode=WAL;

-- one row per sampled pool, written BEFORE anything is known about its outcome
CREATE TABLE IF NOT EXISTS rp_pool(
    pair_id TEXT PRIMARY KEY,
    token_address TEXT, quote_address TEXT, is_c0 INTEGER,
    created_block INTEGER, created_ts INTEGER,
    deployer TEXT, launchpad TEXT, total_supply TEXT,
    cohort INTEGER, sampled_ts INTEGER,
    n_swaps INTEGER DEFAULT 0, n_transfers INTEGER DEFAULT 0,
    first_trade_block INTEGER, last_trade_block INTEGER,
    swaps_status TEXT, transfers_status TEXT      -- 'ok' | 'failed:<why>' ; never silently empty
);

-- raw events, kept so every analysis can be redone without refetching
CREATE TABLE IF NOT EXISTS rp_swap(
    pair_id TEXT, block INTEGER, log_index INTEGER,
    sqrt_price TEXT, liquidity TEXT, amount0 TEXT, amount1 TEXT, tick INTEGER,
    PRIMARY KEY(pair_id, block, log_index)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS rp_transfer(
    token_address TEXT, block INTEGER, log_index INTEGER,
    from_address TEXT, to_address TEXT, value TEXT,
    PRIMARY KEY(token_address, block, log_index)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS ix_rp_swap_pair ON rp_swap(pair_id, block);
CREATE INDEX IF NOT EXISTS ix_rp_tr_tok ON rp_transfer(token_address, block);

-- event-time observations: one row per (pool, minutes since first trade)
CREATE TABLE IF NOT EXISTS rp_snap(
    pair_id TEXT, t_min REAL, block INTEGER,
    price REAL, liquidity_q REAL, mcap_q REAL,
    n_trades INTEGER, n_buys INTEGER, n_sells INTEGER,
    vol_q REAL, buy_vol_q REAL, sell_vol_q REAL,
    uniq_traders INTEGER, uniq_buyers INTEGER, uniq_sellers INTEGER, new_buyers INTEGER,
    holders INTEGER, top1 REAL, top5 REAL, top10 REAL, top20 REAL, deployer_pct REAL,
    feat_json TEXT,
    PRIMARY KEY(pair_id, t_min)
) WITHOUT ROWID;

-- forward outcomes measured from each observation, strictly after it
CREATE TABLE IF NOT EXISTS rp_label(
    pair_id TEXT, t_min REAL,
    max_ret_1h REAL, max_ret_3h REAL, max_ret_6h REAL, max_ret_24h REAL,
    hit_x2 INTEGER, hit_x3 INTEGER, hit_x5 INTEGER, hit_x10 INTEGER, hit_x20 INTEGER, hit_x50 INTEGER,
    t_to_x2 REAL, t_to_x5 REAL, t_to_x10 REAL, t_to_x20 REAL, t_to_x50 REAL,
    dd_before_x5 REAL, dd_before_x10 REAL, dd_before_x20 REAL,
    sellable_x2 REAL, sellable_x3 REAL, sellable_x5 REAL, sellable_x10 REAL, sellable_x20 REAL,
    sellable_x50 REAL, exit_vol_6h REAL,
    ret_6h REAL, dead INTEGER, rug INTEGER,
    PRIMARY KEY(pair_id, t_min)
) WITHOUT ROWID;
"""


def connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=60)
    con.row_factory = sqlite3.Row
    # a collector and an analysis may touch the same file: wait for the lock, never fail on it
    con.execute("PRAGMA busy_timeout=60000")
    con.executescript(DDL)
    return con
