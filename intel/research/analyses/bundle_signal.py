"""Can a bundle be told apart from a real launch, one minute in, before any money is spent?

The live book lost money to a pattern the historical replay cannot contain: the deployer waits for
a buyer from outside his own bundle, takes the money and pulls the liquidity. Measured on 2026-09-07
over twelve hours, at identical filters, 73 % of the pools this book bought died within a minute of
the purchase against 35 % of the eligible pools it did not buy -- our own order appears to be the
trigger, and no replay of a past in which we never existed can show that.

What a replay CAN answer is the question just before it: at T+60 s, does anything separate a pool
run by three wallets from one a crowd is buying? The engine cannot see this today because a swap's
`sender` is the router for 98 % of trades; the research package resolves that hop, so the count of
genuinely distinct buyers exists here and only here.

Outcome measured per launch, on the same tape: whether the pool was still trading five minutes after
a T+1 entry -- the window the exit rule needs -- and whether its liquidity was pulled afterwards.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from typing import Any

BPM = 600
POOL_MANAGER = "0x8366a39cc670b4001a1121b8f6a443a643e40951"


def load(db: str, min_trades: int) -> list[dict[str, Any]]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    snaps = {}
    for r in c.execute("SELECT pair_id, n_trades, uniq_buyers, uniq_traders, new_buyers, feat_json FROM rp_snap WHERE t_min=1"):
        f = json.loads(r["feat_json"] or "{}")
        if (f.get("trades_5m") or 0) < min_trades:
            continue
        snaps[r["pair_id"]] = {"trades": f.get("trades_5m") or 0, "uniq_buyers": r["uniq_buyers"] or 0,
                               "uniq_traders": r["uniq_traders"] or 0, "new_buyers": r["new_buyers"] or 0,
                               "buy_share": f.get("buy_share_trades"), "organic": f.get("organic_buy_ratio")}
    out = []
    for pid, feat in snaps.items():
        p = c.execute("SELECT token_address, is_c0 FROM rp_pool WHERE pair_id=?", (pid,)).fetchone()
        if p is None:
            continue
        blocks = c.execute("SELECT MIN(block) a, MAX(block) b FROM rp_swap WHERE pair_id=?", (pid,)).fetchone()
        if not blocks or blocks["a"] is None:
            continue
        entry = blocks["a"] + BPM                    # the T+1 decision point
        last = blocks["b"]
        if last <= entry:
            continue
        pull = c.execute("SELECT MIN(block) b FROM rp_transfer WHERE token_address=? AND lower(from_address)=? AND block>?",
                         (p["token_address"], POOL_MANAGER, last)).fetchone()["b"]
        out.append({**feat, "pid": pid, "life_min": (last - entry) / BPM, "pulled": pull is not None})
    return out


def band(rows: list[dict[str, Any]], key: str, cuts: tuple[float, ...]) -> None:
    print(f"\n  {key} :")
    print(f"    {'bande':>14}{'n':>6}{'survit 5 min':>14}{'vie mediane':>13}{'liquidite retiree':>19}")
    edges = [(-1, cuts[0])] + [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)] + [(cuts[-1], float("inf"))]
    for lo, hi in edges:
        g = [r for r in rows if lo < (r.get(key) or 0) <= hi]
        if len(g) < 15:
            continue
        alive = sum(1 for r in g if r["life_min"] >= 5) / len(g)
        lives = sorted(r["life_min"] for r in g)
        pulled = sum(1 for r in g if r["pulled"]) / len(g)
        label = f"<= {hi:g}" if lo < 0 else (f"> {lo:g}" if hi == float("inf") else f"{lo:g} - {hi:g}")
        print(f"    {label:>14}{len(g):>6}{alive:>13.0%}{lives[len(lives) // 2]:>12.1f}'{pulled:>18.0%}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/data/research.sqlite")
    ap.add_argument("--min-trades", type=int, default=27)
    args = ap.parse_args()
    rows = load(args.db, args.min_trades)
    if not rows:
        print("aucun lancement ne passe la barre dans ce jeu de donnees")
        return
    alive = sum(1 for r in rows if r["life_min"] >= 5)
    print(f"{len(rows)} lancements passent la barre des {args.min_trades} echanges.")
    print(f"  {alive / len(rows):.0%} vivent encore cinq minutes apres l'entree · "
          f"{sum(1 for r in rows if r['pulled']) / len(rows):.0%} finissent liquidite retiree")
    for r in rows:
        r["trades_per_buyer"] = r["trades"] / max(r["uniq_buyers"], 1)
    band(rows, "uniq_buyers", (3, 6, 10, 20))
    band(rows, "trades_per_buyer", (2, 4, 8, 16))
    band(rows, "trades", (40, 60, 100, 200))
    band(rows, "new_buyers", (3, 6, 12, 25))


if __name__ == "__main__":
    main()
