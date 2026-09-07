"""Continuous launch collection through Bitquery: every pool born in a window, and its trades.

Why a second collector exists: the chain-log collector samples scattered one-hour cohorts, which
is what an unbiased 45-day history needs but is useless for anything that must be CONTINUOUS --
a trailing regime indicator, or enough recent launches to judge the organic-flow layer, which
ended at 11 test rows. Bitquery's realtime dataset covers the last ~6 days of this chain and
returns decoded rows in well under a second, with the buyer already resolved through the router.

What it stores, and what it cannot:
  - bq_pool: one row per Initialize event (pool id, currencies, fee, hooks, sqrtPrice, block,
    time) -- the sampling frame is EVERY launch in the window, nothing skipped.
  - bq_trade: every DEX trade of the launch's token for TRADE_FOLLOW_H hours after creation,
    with the wallet, side, amounts, quote price per token and Bitquery's USD price.
  - Bitquery's DEXTrades do not carry the v4 pool id, so trades are per (token, quote): a token
    with several pools has them merged, as on day 1. In a launch's first hours there is almost
    always one pool; the risk is recorded on the row, not hidden.
  - USD figures from Bitquery are unreliable for illiquid tokens (hourly sums reached 1e12 $);
    the quote-denominated price is the one to trust, USD only as a rough tag.

The plan on this key is realtime-only (archive queries return 403), so nothing here reaches
back beyond the window Bitquery keeps.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from typing import Any, Iterable

ENDPOINT = "https://streaming.bitquery.io/graphql"
DB_PATH = "/app/data/research_bq.sqlite"
TRADE_FOLLOW_H = 6
PAGE = 5_000
PACE_S = 0.25

DDL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS bq_pool(
    pool_id TEXT PRIMARY KEY, token TEXT, quote TEXT, is_c0 INTEGER,
    currency0 TEXT, currency1 TEXT, fee INTEGER, tick_spacing INTEGER, hooks TEXT,
    sqrt_price TEXT, tick INTEGER, block INTEGER, ts INTEGER,
    n_trades INTEGER, first_trade_ts INTEGER, last_trade_ts INTEGER,
    status TEXT                         -- 'ok' | 'failed:<why>' | NULL = not fetched yet
);
CREATE TABLE IF NOT EXISTS bq_trade(
    token TEXT, ts INTEGER, block INTEGER, tx TEXT, wallet TEXT, side TEXT,
    amount_token REAL, amount_quote REAL, quote TEXT, price_quote REAL, price_usd REAL,
    PRIMARY KEY(token, ts, tx, wallet, side, amount_token)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_bq_trade_tok ON bq_trade(token, ts);
"""


class RateLimited(RuntimeError):
    """the plan said no for now; the pool is left unfetched, not marked failed"""


class QuotaExhausted(RuntimeError):
    """the plan said no until it resets; the whole run stops, nothing is marked failed"""


class Bitquery:
    def __init__(self, token: str | None = None, network: str = "robinhood") -> None:
        self.token = token or os.environ.get("BITQUERY_TOKEN", "")
        if not self.token:
            raise RuntimeError("BITQUERY_TOKEN absent de l'environnement")
        self.network = network

    def query(self, gql: str, retries: int = 3) -> dict[str, Any]:
        req = urllib.request.Request(ENDPOINT, data=json.dumps({"query": gql}).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": "Bearer " + self.token})
        last: Exception | None = None
        for k in range(max(retries, 5)):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    body = json.loads(r.read().decode())
                if "errors" in body:
                    raise RuntimeError(json.dumps(body["errors"])[:300])
                return body["data"]["EVM"]
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code == 402:
                    # the plan's points are spent: no retry will change that today, and every
                    # further call would mark a perfectly good pool as failed (406 of them did)
                    raise QuotaExhausted("bitquery: HTTP 402 Payment Required — quota du plan epuise")
                # 429 is the plan's rate limit, not a fault in the query: 8 of the first 20 pools
                # were marked failed on it with a 2-second pause. Wait properly and try again.
                time.sleep((15.0 if exc.code == 429 else 2.0) * (k + 1))
            except (urllib.error.URLError, RuntimeError, TimeoutError) as exc:
                last = exc
                time.sleep(2.0 * (k + 1))
        raise RateLimited(str(last)) if isinstance(last, urllib.error.HTTPError) and last.code == 429 \
            else RuntimeError(f"bitquery: {last}")

    # --------------------------------------------------------------- launches
    def launches(self, since: str, till: str, pool_manager: str) -> list[dict[str, Any]]:
        """every Initialize on the PoolManager in [since, till), decoded from the event arguments"""
        out: list[dict[str, Any]] = []
        offset = 0
        while True:
            data = self.query(f"""{{ EVM(network: {self.network}, dataset: realtime) {{
              Events(limit:{{count:{PAGE}, offset:{offset}}}, orderBy:{{ascending: Block_Time}},
                     where:{{Block:{{Time:{{since:"{since}", till:"{till}"}}}},
                            Log:{{SmartContract:{{is:"{pool_manager}"}}, Signature:{{Name:{{is:"Initialize"}}}}}}}}) {{
                Block {{ Number Time }}
                Arguments {{ Name Value {{ ... on EVM_ABI_Address_Value_Arg {{ address }}
                                         ... on EVM_ABI_BigInt_Value_Arg {{ bigInteger }}
                                         ... on EVM_ABI_Bytes_Value_Arg {{ hex }}
                                         ... on EVM_ABI_Integer_Value_Arg {{ integer }} }} }}
              }} }} }}""")
            rows = data.get("Events") or []
            for r in rows:
                a = {x["Name"]: next(iter(x["Value"].values())) for x in r["Arguments"]}
                pid = a.get("id") or ""
                pid = pid if pid.startswith("0x") else "0x" + pid
                out.append({
                    "pool_id": pid.lower(), "currency0": str(a.get("currency0", "")).lower(),
                    "currency1": str(a.get("currency1", "")).lower(),
                    "fee": int(a.get("fee") or 0), "tick_spacing": int(a.get("tickSpacing") or 0),
                    "hooks": str(a.get("hooks", "")).lower(), "sqrt_price": str(a.get("sqrtPriceX96") or "0"),
                    "tick": int(a.get("tick") or 0), "block": int(r["Block"]["Number"]),
                    "ts": _ts(r["Block"]["Time"]),
                })
            if len(rows) < PAGE:
                break
            offset += PAGE
            time.sleep(PACE_S)
        return out

    # ----------------------------------------------------------------- trades
    def trades(self, token: str, since: str, till: str) -> list[dict[str, Any]]:
        """every DEX trade where the token is bought or sold, oldest first"""
        out: list[dict[str, Any]] = []
        for side, leg, other in (("BUY", "Buy", "Sell"), ("SELL", "Sell", "Buy")):
            offset = 0
            while True:
                data = self.query(f"""{{ EVM(network: {self.network}, dataset: realtime) {{
                  DEXTrades(limit:{{count:{PAGE}, offset:{offset}}}, orderBy:{{ascending: Block_Time}},
                            where:{{Block:{{Time:{{since:"{since}", till:"{till}"}}}},
                                   Trade:{{{leg}:{{Currency:{{SmartContract:{{is:"{token}"}}}}}}}}}}) {{
                    Block {{ Number Time }} Transaction {{ Hash From }}
                    Trade {{ {leg} {{ Amount Price PriceInUSD }}
                             {other} {{ Amount Currency {{ SmartContract }} }} }}
                  }} }} }}""")
                rows = data.get("DEXTrades") or []
                for r in rows:
                    t = r["Trade"]
                    mine, oth = t[leg], t[other]
                    # The person is the transaction sender. Bitquery's Buyer/Seller on this chain
                    # is the launchpad hook (0x8366a39c... on 7 979 of the first 7 979 trades),
                    # the same router-hop trap as the raw transfers -- 52 "wallets" for 8 000
                    # trades. Transaction.From is the wallet that paid for the block space.
                    wallet = (r.get("Transaction") or {}).get("From")
                    out.append({
                        "token": token, "ts": _ts(r["Block"]["Time"]), "block": int(r["Block"]["Number"]),
                        "tx": r["Transaction"]["Hash"], "wallet": (wallet or "").lower(), "side": side,
                        "amount_token": float(mine.get("Amount") or 0), "amount_quote": float(oth.get("Amount") or 0),
                        "quote": str(oth["Currency"]["SmartContract"]).lower(),
                        "price_quote": float(mine.get("Price") or 0), "price_usd": float(mine.get("PriceInUSD") or 0),
                    })
                if len(rows) < PAGE:
                    break
                offset += PAGE
                time.sleep(PACE_S)
        out.sort(key=lambda r: (r["ts"], r["block"]))
        return out


def _ts(iso: str) -> int:
    return int(time.mktime(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ"))) - time.timezone


def _iso(ts: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=60000")
    con.executescript(DDL)
    return con


def collect(*, pool_manager: str, quote_assets: Iterable[str], since_ts: int, till_ts: int,
            db_path: str = DB_PATH, max_pools: int | None = None, verbose: bool = True) -> dict[str, Any]:
    """Launches in [since, till), then TRADE_FOLLOW_H hours of trades for each. Resumable."""
    bq = Bitquery()
    quotes = {q.lower() for q in quote_assets}
    con = connect(db_path)
    t0 = time.time()
    launches = bq.launches(_iso(since_ts), _iso(till_ts), pool_manager)
    kept = 0
    for L in launches:
        c0, c1 = L["currency0"], L["currency1"]
        if c1 in quotes and c0 not in quotes:
            tok, q, is_c0 = c0, c1, 1
        elif c0 in quotes and c1 not in quotes:
            tok, q, is_c0 = c1, c0, 0
        else:
            continue                                   # quote/quote or unknown/unknown: not a launch we trade
        con.execute("INSERT OR IGNORE INTO bq_pool(pool_id, token, quote, is_c0, currency0, currency1, fee, tick_spacing, hooks, "
                    "sqrt_price, tick, block, ts, status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
                    (L["pool_id"], tok, q, is_c0, c0, c1, L["fee"], L["tick_spacing"], L["hooks"],
                     L["sqrt_price"], L["tick"], L["block"], L["ts"]))
        kept += 1
    con.commit()
    if verbose:
        print(f"{len(launches)} Initialize dans la fenetre · {kept} avec une cotation connue · {time.time()-t0:.0f}s", flush=True)

    todo = [dict(r) for r in con.execute("SELECT * FROM bq_pool WHERE status IS NULL ORDER BY ts")]
    if max_pools:
        todo = todo[:max_pools]
    n_ok = n_fail = n_tr = 0
    for i, p in enumerate(todo):
        since, till = _iso(p["ts"]), _iso(p["ts"] + TRADE_FOLLOW_H * 3600)
        try:
            rows = bq.trades(p["token"], since, till)
            con.executemany("INSERT OR IGNORE INTO bq_trade VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            [(r["token"], r["ts"], r["block"], r["tx"], r["wallet"], r["side"], r["amount_token"],
                              r["amount_quote"], r["quote"], r["price_quote"], r["price_usd"]) for r in rows])
            con.execute("UPDATE bq_pool SET n_trades=?, first_trade_ts=?, last_trade_ts=?, status='ok' WHERE pool_id=?",
                        (len(rows), rows[0]["ts"] if rows else None, rows[-1]["ts"] if rows else None, p["pool_id"]))
            n_ok += 1
            n_tr += len(rows)
        except QuotaExhausted as exc:
            # nothing more will be served today: stop here, every unfetched pool keeps NULL
            print(f"  ARRET : {exc} — {i} pools traites dans cette passe, le reste attend la prochaine", flush=True)
            break
        except RateLimited:
            # not a failure of this pool: leave it unfetched so the next run picks it up, and
            # give the plan's limiter a real pause before asking again
            n_fail += 1
            time.sleep(30.0)
        except Exception as exc:  # noqa: BLE001
            con.execute("UPDATE bq_pool SET status=? WHERE pool_id=?", ("failed:" + str(exc)[:80], p["pool_id"]))
            n_fail += 1
        con.commit()
        time.sleep(PACE_S)
        if verbose and (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(todo)} pools · {n_tr:,} trades · {n_fail} echecs · {time.time()-t0:.0f}s", flush=True)
    alive = con.execute("SELECT COUNT(*) FROM bq_pool WHERE status='ok' AND n_trades>0").fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM bq_pool").fetchone()[0]
    con.close()
    return {"launches_window": len(launches), "pools_total": total, "fetched_ok": n_ok, "fetched_failed": n_fail,
            "trades": n_tr, "alive_total": alive, "seconds": round(time.time() - t0, 1)}


if __name__ == "__main__":
    import sys
    # No IntelContext here on purpose: building one opens the engine's 8 GB database (~1 min, and
    # it blocked outright while the engine was doing its startup backup). This needs two config
    # values and the network, nothing else.
    from intel.settings import IntelConfig, Settings
    settings = Settings.load()
    config = IntelConfig.load(settings.config_path)
    hours = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
    cap = int(sys.argv[2]) if len(sys.argv) > 2 else None
    now = int(time.time())
    till = now - TRADE_FOLLOW_H * 3600 - 600          # only launches whose 6 h window has fully closed
    res = collect(pool_manager=str(config.get("contracts.pool_manager")).lower(),
                  quote_assets=list(config.quote_assets or {}),
                  since_ts=till - int(hours * 3600), till_ts=till, max_pools=cap)
    print("\n=== resultat ===")
    for k, v in res.items():
        print(f"  {k:<18} {v}")
