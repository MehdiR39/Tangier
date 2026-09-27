"""Turn the Bitquery collection into the research package's own tables, so nothing downstream changes.

build / analyse / layers / report all read rp_pool, rp_swap and rp_transfer. Bitquery gives a
different shape -- decimal amounts, a quote price per trade, the trader's wallet, no pool
liquidity -- and the honest way to reuse the whole verification chain (fills at the next trade,
sellability, placebos, the pre-written verdict) is to translate once, here, and say exactly what
is synthesized:

  - rp_swap.sqrt_price is rebuilt from the quote price so `price_from_sqrt` returns the same
    number the trade printed. Amounts are scaled to integers (x1e18) with the sign convention the
    tape expects (token leaving the pool on a buy). Ratios are unaffected by the scaling.
  - rp_swap.liquidity is 0: Bitquery does not expose pool depth. Every liquidity-based feature
    (liq_to_mc, vol5_to_liq) comes out None on this data and the impact model falls back to its
    pessimistic default. That is a known blind spot, not a silent one.
  - rp_transfer is synthesized from the trades themselves: a buy is PoolManager -> wallet, a sell
    is wallet -> PoolManager, with the wallet already being the transaction sender. Holder counts
    and concentration therefore reflect TRADERS, not airdrop recipients -- which is the population
    the organic-flow layer is about.
"""
from __future__ import annotations

import math
import sqlite3
import time
from typing import Any

from intel.research.bitquery import DB_PATH as BQ_DB
from intel.research.schema import connect

SCALE = 10 ** 18
Q96 = 1 << 96
ZERO = "0x0000000000000000000000000000000000000000"
BLOCKS_PER_SEC = 10


def _sqrt_from_price(price_quote_per_token: float, is_c0: bool) -> int:
    """the sqrtPriceX96 that price_from_sqrt() maps back onto this quote price"""
    if price_quote_per_token <= 0:
        return 0
    p = price_quote_per_token if is_c0 else 1.0 / price_quote_per_token
    return int(math.sqrt(p) * Q96)


def convert(*, bq_path: str = BQ_DB, out_path: str, pool_manager: str, verbose: bool = True) -> dict[str, Any]:
    src = sqlite3.connect(f"file:{bq_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    con = connect(out_path)
    for t in ("rp_pool", "rp_swap", "rp_transfer", "rp_snap", "rp_label"):
        con.execute(f"DELETE FROM {t}")
    con.commit()
    pm = pool_manager.lower()
    t0 = time.time()

    pools = [dict(r) for r in src.execute("SELECT * FROM bq_pool WHERE status='ok'")]
    # one pool per token: the most traded one, exactly the day-1 rule against mixing pools
    best: dict[str, dict] = {}
    for p in pools:
        cur = best.get(p["token"])
        if cur is None or (p["n_trades"] or 0) > (cur["n_trades"] or 0):
            best[p["token"]] = p
    n_swaps = n_tr = 0
    for i, p in enumerate(best.values()):
        tok, is_c0 = p["token"], bool(p["is_c0"])
        # only trades against THIS pool's quote asset: a token traded against native ETH, WETH and
        # USDG returns prices in three different units, and mixing them fabricates moves
        trades = [dict(r) for r in src.execute(
            "SELECT * FROM bq_trade WHERE token=? AND quote=? ORDER BY ts, block", (tok, p["quote"]))]
        swaps, transfers = [], []
        for k, tr in enumerate(trades):
            sq = _sqrt_from_price(tr["price_quote"], is_c0)
            if sq <= 0:
                continue
            a_tok = int(tr["amount_token"] * SCALE)
            a_q = int(tr["amount_quote"] * SCALE)
            # token leaves the pool on a buy (negative), quote enters (positive)
            tok_leg = -a_tok if tr["side"] == "BUY" else a_tok
            q_leg = a_q if tr["side"] == "BUY" else -a_q
            a0, a1 = (tok_leg, q_leg) if is_c0 else (q_leg, tok_leg)
            swaps.append((p["pool_id"], tr["block"], k, str(sq), "0", str(a0), str(a1), 0))
            w = tr["wallet"] or ""
            if w and w != pm:
                frm, to = (pm, w) if tr["side"] == "BUY" else (w, pm)
                transfers.append((tok, tr["block"], k, frm, to, str(a_tok)))
        con.executemany("INSERT OR IGNORE INTO rp_swap VALUES(?,?,?,?,?,?,?,?)", swaps)
        con.executemany("INSERT OR IGNORE INTO rp_transfer VALUES(?,?,?,?,?,?)", transfers)
        con.execute(
            "INSERT OR REPLACE INTO rp_pool VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (p["pool_id"], tok, p["quote"], int(is_c0), p["block"], p["ts"],
             None, None, None, i // 40, int(time.time()),           # cohort = 40 launches a slice
             len(swaps), len(transfers),
             swaps[0][1] if swaps else None, swaps[-1][1] if swaps else None,
             "ok", "ok" if transfers else "synth:none"))
        n_swaps += len(swaps)
        n_tr += len(transfers)
    con.commit()
    dead = src.execute("SELECT COUNT(*) FROM bq_pool WHERE status='ok' AND n_trades=0").fetchone()[0]
    # dead-at-birth pools stay in the frame with n_swaps = 0, as in the chain-log collection
    for r in src.execute("SELECT * FROM bq_pool WHERE status='ok' AND n_trades=0"):
        con.execute("INSERT OR IGNORE INTO rp_pool VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (r["pool_id"], r["token"], r["quote"], int(r["is_c0"]), r["block"], r["ts"],
                     None, None, None, 0, int(time.time()), 0, 0, None, None, "ok", "synth:none"))
    con.commit()
    con.close()
    src.close()
    out = {"tokens": len(best), "morts_a_la_naissance": dead, "swaps": n_swaps,
           "transferts_synthetises": n_tr, "secondes": round(time.time() - t0, 1)}
    if verbose:
        print(out)
    return out


if __name__ == "__main__":
    import sys
    from intel.context import IntelContext
    ctx = IntelContext.build()
    out_path = sys.argv[1] if len(sys.argv) > 1 else "/app/data/research_bq_rp.sqlite"
    convert(out_path=out_path, pool_manager=ctx.pool_manager)
