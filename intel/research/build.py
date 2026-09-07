"""Turn the raw events into observations and outcomes.

Runs entirely off rp_swap / rp_transfer, so it can be re-run with different feature or label
definitions without touching the chain again -- which is the point of keeping the raw events.

Pools that never traded are NOT skipped. They are the majority of launches and the reason every
earlier measurement looked profitable: a dataset containing only pools that traded is a dataset of
survivors. They enter the labels with a zero outcome at every observation they could have been
bought at, which for a pool with no trades means none -- and that absence is itself recorded on
rp_pool as n_swaps = 0 rather than being dropped.
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from intel.research import RESEARCH_DB
from intel.research.features import GRID_MIN, PoolTape, snapshot
from intel.research.labels import label, zero_label
from intel.research.schema import connect

SNAP_COLS = ["pair_id", "t_min", "block", "price", "liquidity_q", "mcap_q", "n_trades", "n_buys",
             "n_sells", "vol_q", "buy_vol_q", "sell_vol_q", "uniq_traders", "uniq_buyers",
             "uniq_sellers", "new_buyers", "holders", "top1", "top5", "top10", "top20",
             "deployer_pct", "feat_json"]
LABEL_COLS = ["pair_id", "t_min", "max_ret_1h", "max_ret_3h", "max_ret_6h", "max_ret_24h",
              "hit_x2", "hit_x3", "hit_x5", "hit_x10", "hit_x20", "hit_x50",
              "t_to_x2", "t_to_x5", "t_to_x10", "t_to_x20", "t_to_x50",
              "dd_before_x5", "dd_before_x10", "dd_before_x20",
              "sellable_x2", "sellable_x3", "sellable_x5", "sellable_x10", "sellable_x20",
              "sellable_x50", "exit_vol_6h", "ret_6h", "dead", "rug"]


def build(*, db_path: str = RESEARCH_DB, pool_manager: str, grid: list[float] | None = None,
          verbose: bool = True) -> dict[str, Any]:
    grid = [float(x) for x in (grid or GRID_MIN)]
    con = connect(db_path)
    # rp_snap and rp_label are derived from the raw events, so they are rebuilt from scratch rather
    # than emptied: a feature or label added since the file was created would otherwise hit a table
    # still carrying the old columns, and CREATE TABLE IF NOT EXISTS would not notice.
    con.execute("DROP TABLE IF EXISTS rp_snap")
    con.execute("DROP TABLE IF EXISTS rp_label")
    con.commit()
    con.close()
    con = connect(db_path)

    pools = [dict(r) for r in con.execute("SELECT * FROM rp_pool")]
    have_tr = {r["token_address"] for r in con.execute(
        "SELECT DISTINCT token_address FROM rp_transfer")}
    if verbose:
        print(f"{len(pools)} pools · {len(have_tr)} tokens avec des transferts", flush=True)

    swaps_by: dict[str, list] = defaultdict(list)
    for r in con.execute("SELECT * FROM rp_swap ORDER BY pair_id, block, log_index"):
        swaps_by[r["pair_id"]].append(r)
    tr_by: dict[str, list] = defaultdict(list)
    for r in con.execute("SELECT * FROM rp_transfer ORDER BY token_address, block, log_index"):
        tr_by[r["token_address"]].append(r)

    t0 = time.time()
    n_snap = n_lab = n_alive = n_zero = 0
    snap_rows: list[tuple] = []
    lab_rows: list[tuple] = []
    for i, p in enumerate(pools):
        sw = swaps_by.get(p["pair_id"], [])
        if not sw:
            continue                       # never traded: stays on rp_pool with n_swaps = 0
        n_alive += 1
        tr = tr_by.get(p["token_address"], [])
        tape = PoolTape(p, sw, tr, pool_manager)
        with_tr = p["token_address"] in have_tr
        for t in grid:
            s = snapshot(tape, t, have_transfers=with_tr)
            if s is None:
                continue
            snap_rows.append(tuple(s.get(c) for c in SNAP_COLS))
            n_snap += 1
            lb = label(tape, t)
            if lb is None:
                lb = zero_label(tape, t)
                n_zero += 1
            # sellability is decided later, in euros, by the backtest; the raw quote volume
            # traded after each level is what gets carried here
            for lv in ("x2", "x3", "x5", "x10", "x20", "x50"):
                lb["sellable_" + lv] = lb.pop("sellvol_" + lv, None)
            lab_rows.append(tuple(lb.get(c) for c in LABEL_COLS))
            n_lab += 1
        if len(snap_rows) >= 5000:
            con.executemany(f"INSERT OR REPLACE INTO rp_snap VALUES({','.join('?' * len(SNAP_COLS))})", snap_rows)
            con.executemany(f"INSERT OR REPLACE INTO rp_label VALUES({','.join('?' * len(LABEL_COLS))})", lab_rows)
            con.commit()
            snap_rows, lab_rows = [], []
        if verbose and (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(pools)} pools · {n_snap:,} observations · {time.time()-t0:.0f}s",
                  flush=True)
    if snap_rows:
        con.executemany(f"INSERT OR REPLACE INTO rp_snap VALUES({','.join('?' * len(SNAP_COLS))})", snap_rows)
        con.executemany(f"INSERT OR REPLACE INTO rp_label VALUES({','.join('?' * len(LABEL_COLS))})", lab_rows)
        con.commit()

    out = {"pools": len(pools), "vivants": n_alive, "morts_a_la_naissance": len(pools) - n_alive,
           "observations": n_snap, "labels": n_lab,
           "positions_invendables": n_zero, "secondes": round(time.time() - t0, 1)}
    con.close()
    return out


if __name__ == "__main__":
    from intel.context import IntelContext
    ctx = IntelContext.build()
    res = build(pool_manager=ctx.pool_manager)
    print("\n=== dataset construit ===")
    for k, v in res.items():
        print(f"  {k:<24} {v}")
