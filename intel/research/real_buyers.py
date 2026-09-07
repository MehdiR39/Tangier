"""Does counting the real buyers separate the rugs on Robinhood Chain, as it does on Solana?

Solana answers this in one line: a genuine launch shows two trades per buyer, a bundle shows sixty
eight, and the pools with few distinct buyers are the ones whose liquidity is gone an hour later.
Robinhood Chain could never be asked the question, because the swap `sender` is a router for 98 %
of trades -- every unique-buyer count collapsed to one address.

The research package does resolve that hop: within a block, a PoolManager -> router transfer
followed by router -> someone of the same amount is one purchase by that someone. So the question
IS answerable here, on the 5 491 sampled launches, and it has never been asked.

What it compares, for launches that clear the T+1 bar: the number of distinct buyers and the trades
per buyer in the first minute, against whether the pool was still trading five minutes later and
whether its liquidity was pulled afterwards. If the separation exists, it is the filter the live
book has been missing all day; if it does not, that is worth knowing before another euro is spent.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from typing import Any

from intel.research.features import PoolTape

BPM = 600
POOL_MANAGER = "0x8366a39cc670b4001a1121b8f6a443a643e40951"


def load(db: str, min_trades: int, max_trades: int, limit: int) -> list[dict[str, Any]]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    busy = {}
    for r in c.execute("SELECT pair_id, feat_json FROM rp_snap WHERE t_min=1"):
        n = (json.loads(r["feat_json"] or "{}").get("trades_5m") or 0)
        if min_trades <= n and (not max_trades or n <= max_trades):
            busy[r["pair_id"]] = n
    out: list[dict[str, Any]] = []
    for pid, n_trades in list(busy.items())[:limit]:
        pool = c.execute("SELECT * FROM rp_pool WHERE pair_id=?", (pid,)).fetchone()
        if pool is None or not pool["token_address"]:
            continue
        swaps = [dict(r) for r in c.execute(
            "SELECT block, log_index, sqrt_price, liquidity, amount0, amount1 FROM rp_swap WHERE pair_id=? ORDER BY block, log_index", (pid,))]
        if len(swaps) < 4:
            continue
        transfers = [dict(r) for r in c.execute(
            "SELECT block, log_index, from_address, to_address, value FROM rp_transfer WHERE token_address=? ORDER BY block, log_index",
            (pool["token_address"],))]
        if not transfers:
            continue
        tape = PoolTape(dict(pool), swaps, transfers, POOL_MANAGER)
        t0 = tape.t0
        if t0 is None:
            continue
        # wallet_state() is what carries the resolved buyer set; window() only counts trades.
        ws = tape.wallet_state(t0 + BPM)
        n_buyers = len(ws.get("buyers") or set())
        last = swaps[-1]["block"]
        entry = t0 + BPM
        pull = c.execute("SELECT MIN(block) b FROM rp_transfer WHERE token_address=? AND lower(from_address)=? AND block>?",
                         (pool["token_address"], POOL_MANAGER, last)).fetchone()["b"]
        out.append({"pid": pid, "trades": n_trades, "buyers": n_buyers,
                    "ratio": n_trades / max(n_buyers, 1),
                    "life_min": (last - entry) / BPM, "pulled": pull is not None})
    return out


def band(rows: list[dict[str, Any]], key: str, cuts: tuple[float, ...], title: str) -> None:
    print(f"\n  {title} :")
    print(f"    {'bande':>16}{'n':>6}{'survit 5 min':>15}{'liquidite retiree':>20}")
    edges = [(-1.0, cuts[0])] + [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)] + [(cuts[-1], float("inf"))]
    for lo, hi in edges:
        g = [r for r in rows if lo < (r.get(key) or 0) <= hi]
        if len(g) < 8:
            continue
        alive = sum(1 for r in g if r["life_min"] >= 5) / len(g)
        pulled = sum(1 for r in g if r["pulled"]) / len(g)
        lab = f"<= {hi:g}" if lo < 0 else (f"> {lo:g}" if hi == float("inf") else f"{lo:g} - {hi:g}")
        print(f"    {lab:>16}{len(g):>6}{alive:>14.0%}{pulled:>19.0%}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/data/research.sqlite")
    ap.add_argument("--min-trades", type=int, default=27)
    ap.add_argument("--max-trades", type=int, default=0, help="0 = pas de plafond")
    ap.add_argument("--limit", type=int, default=400)
    args = ap.parse_args()
    rows = load(args.db, args.min_trades, args.max_trades, args.limit)
    if not rows:
        print("aucun lancement exploitable")
        return
    alive = sum(1 for r in rows if r["life_min"] >= 5)
    med_b = sorted(r["buyers"] for r in rows)[len(rows) // 2]
    print(f"{len(rows)} lancements passant la barre · {alive / len(rows):.0%} vivent 5 min apres l'entree")
    print(f"acheteurs distincts, mediane : {med_b} · rapport echanges/acheteur median : "
          f"{sorted(r['ratio'] for r in rows)[len(rows) // 2]:.1f}")
    band(rows, "buyers", (3, 6, 12, 25), "acheteurs reellement distincts (sauts de routeur resolus)")
    band(rows, "ratio", (2, 4, 8, 16), "echanges par acheteur")


if __name__ == "__main__":
    main()
