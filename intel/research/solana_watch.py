"""Watch Solana launches and record what becomes of them. Observation only: it never trades.

Why look at Solana at all. The Robinhood book lost money on 2026-09-07 to one specific move: the
deployer waits for a buyer from outside his own bundle, takes the money and pulls the pool's
liquidity, all within a minute. Most Solana launches begin on a bonding curve whose liquidity the
creator cannot withdraw, so that exact move should be impossible there. Should be: this module
exists to find out, not to assume.

It runs beside the engine and shares nothing with it -- its own database file, its own process, its
own rate limit -- so it cannot slow a live order or lock the trading database.

What it records, per launch, every minute for six hours: price, liquidity, and the buy/sell counts
of the last five minutes. That is enough to ask the two questions that matter: does an entry signal
exist in the first minutes, and does the pool still let anyone sell later on.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import time
from typing import Any

import httpx

DISCOVERY = (
    "https://api.dexscreener.com/token-profiles/latest/v1",
    "https://api.dexscreener.com/token-boosts/latest/v1",
)
PAIRS_URL = "https://api.dexscreener.com/latest/dex/tokens/"
SCHEMA = """
CREATE TABLE IF NOT EXISTS sol_pair(
    pair_id TEXT PRIMARY KEY, token_address TEXT, symbol TEXT, dex TEXT,
    created_ms INTEGER, first_seen_ts INTEGER, age_at_discovery_min REAL
);
CREATE TABLE IF NOT EXISTS sol_obs(
    pair_id TEXT, ts INTEGER, age_min REAL,
    price_usd REAL, liquidity_usd REAL, volume_m5 REAL, fdv REAL,
    buys_m5 INTEGER, sells_m5 INTEGER,
    PRIMARY KEY(pair_id, ts)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_sol_obs_pair ON sol_obs(pair_id, age_min);
"""


def connect(path: str) -> sqlite3.Connection:
    c = sqlite3.connect(path, timeout=30)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    c.execute("PRAGMA journal_mode=WAL")
    return c


async def discover(client: httpx.AsyncClient) -> list[str]:
    """Token addresses of Solana launches DexScreener has just surfaced."""
    out: list[str] = []
    for url in DISCOVERY:
        try:
            r = await client.get(url, timeout=30)
            data = r.json()
        except Exception:  # noqa: BLE001
            continue
        for x in data if isinstance(data, list) else []:
            if x.get("chainId") == "solana" and x.get("tokenAddress"):
                out.append(x["tokenAddress"])
    return list(dict.fromkeys(out))


async def pairs_of(client: httpx.AsyncClient, tokens: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(0, len(tokens), 25):                    # the endpoint takes a comma-separated batch
        try:
            r = await client.get(PAIRS_URL + ",".join(tokens[i:i + 25]), timeout=30)
            out.extend((r.json() or {}).get("pairs") or [])
        except Exception:  # noqa: BLE001
            continue
        await asyncio.sleep(1.0)
    return [p for p in out if p.get("chainId") == "solana"]


def record(db: sqlite3.Connection, pairs: list[dict[str, Any]], max_age_min: float) -> tuple[int, int]:
    now = int(time.time())
    known = {r["pair_id"] for r in db.execute("SELECT pair_id FROM sol_pair")}
    new = obs = 0
    for p in pairs:
        pid = p.get("pairAddress")
        created = p.get("pairCreatedAt")
        if not pid or not created:
            continue
        age = (now * 1000 - created) / 60000.0
        if pid not in known:
            if age > max_age_min:
                continue                                    # too old to teach us anything about launches
            db.execute("INSERT OR IGNORE INTO sol_pair VALUES(?,?,?,?,?,?,?)",
                       (pid, (p.get("baseToken") or {}).get("address"), (p.get("baseToken") or {}).get("symbol"),
                        p.get("dexId"), created, now, round(age, 2)))
            new += 1
        txns = (p.get("txns") or {}).get("m5") or {}
        db.execute("INSERT OR IGNORE INTO sol_obs VALUES(?,?,?,?,?,?,?,?,?)",
                   (pid, now, round(age, 2),
                    float(p["priceUsd"]) if p.get("priceUsd") else None,
                    float((p.get("liquidity") or {}).get("usd") or 0) or None,
                    float((p.get("volume") or {}).get("m5") or 0) or None,
                    float(p.get("fdv") or 0) or None,
                    txns.get("buys"), txns.get("sells")))
        obs += 1
    db.commit()
    return new, obs


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/data/solana.sqlite")
    ap.add_argument("--minutes", type=int, default=0, help="0 = sans fin")
    ap.add_argument("--follow-hours", type=float, default=6.0)
    ap.add_argument("--max-age-min", type=float, default=30.0)
    args = ap.parse_args()
    db = connect(args.db)
    deadline = time.time() + args.minutes * 60 if args.minutes else None
    async with httpx.AsyncClient(headers={"User-Agent": "tangier-intel/solana-study"}) as client:
        while deadline is None or time.time() < deadline:
            t0 = time.time()
            tokens = await discover(client)
            # anything still inside its follow window is asked about again, so we see what became of it
            cutoff = int(time.time() - args.follow_hours * 3600)
            tracked = [r["token_address"] for r in db.execute(
                "SELECT token_address FROM sol_pair WHERE first_seen_ts > ? AND token_address IS NOT NULL", (cutoff,))]
            new, obs = record(db, await pairs_of(client, list(dict.fromkeys(tokens + tracked))), args.max_age_min)
            n_pairs = db.execute("SELECT COUNT(*) FROM sol_pair").fetchone()[0]
            print(f"{time.strftime('%H:%M:%S')} · {new} nouveaux lancements · {obs} observations · "
                  f"{n_pairs} paires suivies · cycle {time.time() - t0:.0f}s", flush=True)
            await asyncio.sleep(max(20.0, 60.0 - (time.time() - t0)))


if __name__ == "__main__":
    asyncio.run(main())
