"""Build the unbiased launch dataset: sample pools, then fetch their raw events.

Sampling is by COHORT anchored on randomly drawn pools. Drawing block ranges uniformly left 21 of
30 windows empty, because launches are concentrated in recent history; anchoring on a real pool
weights by launch density while still conditioning on nothing about the outcome. Every pool born
in the chosen hour is taken, dead ones included -- they are the population the engine never stored.

Cost control, and why the windows differ:
  - SWAPS are followed for 24 h. They give price, size and pool liquidity, and the labels need the
    full horizon.
  - TRANSFERS are followed for 6 h only. They give holders, concentration and the deployer's
    balance, which matter for the entry decision in the first minutes; carrying them to 24 h
    multiplies the log volume for a question nobody asks at that horizon.

Every pool records swaps_status / transfers_status. A cohort whose query is refused is marked
'failed:<reason>', never left looking like a pool that simply did not trade -- the earlier
collection reported "1800/1800" while the error handler had swallowed most of the data.
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import Any

from intel.backtest.history import TOPIC_V4_SWAP, decode_swap, is_price_at_bound
from intel.context import IntelContext
from intel.research import RESEARCH_DB
from intel.research.schema import connect
from intel.utils.timeutil import now_ts

TOPIC_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
COHORT_BLOCKS = 36_000        # ~1 h of launches
SWAP_FOLLOW = 864_000         # ~24 h
TRANSFER_FOLLOW = 216_000     # ~6 h
MAX_SWAPS_PER_POOL = 20_000


def _addr(topic: str) -> str:
    return "0x" + topic[-40:]


async def _nothing():
    """empty async iterator, so the transfer pass can be switched off without a second code path"""
    return
    yield  # pragma: no cover


def _int(v: Any) -> int:
    if isinstance(v, str):
        return int(v, 16) if v.startswith("0x") else int(v)
    return int(v or 0)


async def collect(ctx: IntelContext, *, cohorts: int, per_cohort: int, seed: int = 41,
                  db_path: str = RESEARCH_DB, with_transfers: bool = True,
                  contiguous_hours: int = 0) -> dict[str, Any]:
    """Collect in two passes when the node is the constraint.

    Transfers are an order of magnitude more numerous than swaps (141 841 against 2 792 on the
    first 30 pools), so fetching both at once caps the sample at a few hundred launches. Swaps
    alone already carry price, size, trade counts and pool depth -- everything the entry question
    turns on -- so the wide pass takes swaps only and a second pass adds transfers, and with them
    holders and concentration, on the subset worth the calls.
    """
    con = connect(db_path)
    head = await ctx.rpc.block_number()
    rng = random.Random(seed)

    # only cohorts that came back clean count as done: a cohort marked failed must be retried,
    # otherwise a resume silently inherits whatever the node refused the first time
    done = {r["cohort"] for r in con.execute(
        "SELECT cohort FROM rp_pool GROUP BY cohort HAVING SUM(swaps_status<>'ok')=0")}
    rows = ctx.db.query(
        "SELECT pair_id, token_address, quote_address, created_block, created_ts, token_is_currency0 "
        "FROM pairs WHERE chain_id=? AND created_block IS NOT NULL AND token_is_currency0 IS NOT NULL",
        (ctx.chain_id,))
    pools = [dict(r) for r in rows]
    limit = head - SWAP_FOLLOW - COHORT_BLOCKS
    if contiguous_hours:
        # A regime indicator needs CONSECUTIVE hours: on scattered cohorts "the previous hour"
        # almost never exists, which is the artefact that sank the lagged test. These are the
        # last N complete hours, back to back, each with its full follow window closed.
        starts = [limit - k * COHORT_BLOCKS for k in range(int(contiguous_hours))][::-1]
    else:
        anchors = sorted({int(p["created_block"]) for p in pools if int(p["created_block"]) <= limit})
        if not anchors:
            return {"error": "aucune fenetre complete disponible"}
        starts = sorted(rng.sample(anchors, min(cohorts, len(anchors))))
    print(f"{len(pools):,} pools connus · {len(anchors):,} ancres possibles · "
          f"{len(starts)} cohortes tirees · {len(done)} deja faites", flush=True)

    meta = {r["address"]: r for r in ctx.db.query(
        "SELECT address, total_supply, creator_address, launchpad FROM tokens WHERE chain_id=?",
        (ctx.chain_id,))}

    t0, tot_pools, tot_swaps, tot_tr, n_failed = time.time(), 0, 0, 0, 0
    for ci, s0 in enumerate(starts):
        if ci in done:
            continue
        s1 = s0 + COHORT_BLOCKS
        grp = [p for p in pools if s0 <= int(p["created_block"]) < s1]
        if not grp:
            continue
        if len(grp) > per_cohort:
            grp = rng.sample(grp, per_cohort)
        ids = [str(p["pair_id"]).lower() for p in grp]
        toks = sorted({str(p["token_address"]).lower() for p in grp})
        idset = set(ids)
        got = {i: 0 for i in ids}
        first_b: dict[str, int] = {}
        last_b: dict[str, int] = {}

        # A 429 is the node asking us to slow down, not a verdict on the cohort. Retrying with a
        # widening pause recovers it; giving up would quietly drop a whole hour of launches and
        # bias the sample towards whatever the node happened to feel like answering.
        swap_status = "ok"
        for attempt in range(3):
            got = {i: 0 for i in ids}
            first_b, last_b = {}, {}
            con.execute("DELETE FROM rp_swap WHERE pair_id IN (%s)" % ",".join("?" * len(ids)), ids)
            try:
                async for _a, _b, logs in ctx.rpc.iter_logs(
                        address=ctx.pool_manager, topics=[TOPIC_V4_SWAP, ids],
                        from_block=s0, to_block=min(head, s1 + SWAP_FOLLOW), chunk=800_000):
                    batch = []
                    for lg in logs:
                        pid = str(lg["topics"][1]).lower()
                        if pid not in idset or got[pid] >= MAX_SWAPS_PER_POOL:
                            continue
                        try:
                            ev = decode_swap(lg)
                        except Exception:
                            continue
                        if is_price_at_bound(ev.sqrt_price_x96):
                            continue
                        got[pid] += 1
                        first_b.setdefault(pid, ev.block_number)
                        last_b[pid] = ev.block_number
                        batch.append((pid, ev.block_number, _int(lg.get("logIndex")),
                                      str(ev.sqrt_price_x96), str(ev.liquidity),
                                      str(ev.amount0), str(ev.amount1),
                                      int(getattr(ev, "tick", 0) or 0)))
                    if batch:
                        con.executemany("INSERT OR IGNORE INTO rp_swap VALUES(?,?,?,?,?,?,?,?)", batch)
                        tot_swaps += len(batch)
                swap_status = "ok"
                break
            except Exception as exc:  # noqa: BLE001
                swap_status = "failed:" + str(exc)[:60]
                if attempt < 2:
                    await asyncio.sleep(20 * (attempt + 1))
        if swap_status != "ok":
            n_failed += 1

        tr_count = {t: 0 for t in toks}
        tr_status = "ok" if with_transfers else "skipped"
        try:
            async for _a, _b, logs in (ctx.rpc.iter_logs(
                    address=toks, topics=[TOPIC_TRANSFER],
                    from_block=s0, to_block=min(head, s1 + TRANSFER_FOLLOW), chunk=30_000)
                    if with_transfers else _nothing()):
                batch = []
                for lg in logs:
                    tp = lg.get("topics") or []
                    if len(tp) < 3:
                        continue
                    tok = str(lg["address"]).lower()
                    if tok not in tr_count:
                        continue
                    tr_count[tok] += 1
                    data = lg.get("data")
                    val = _int(data) if data not in (None, "0x", "") else 0
                    batch.append((tok, _int(lg["blockNumber"]), _int(lg.get("logIndex")),
                                  _addr(tp[1]), _addr(tp[2]), str(val)))
                if batch:
                    con.executemany("INSERT OR IGNORE INTO rp_transfer VALUES(?,?,?,?,?,?)", batch)
                    tot_tr += len(batch)
        except Exception as exc:  # noqa: BLE001
            tr_status = "failed:" + str(exc)[:60]

        rowsout = []
        for p in grp:
            pid = str(p["pair_id"]).lower()
            tok = str(p["token_address"]).lower()
            m = meta.get(tok)
            rowsout.append((
                pid, tok, (p["quote_address"] or "").lower(),
                1 if p["token_is_currency0"] else 0,
                int(p["created_block"]), p["created_ts"],
                (m["creator_address"] if m else None), (m["launchpad"] if m else None),
                (str(m["total_supply"]) if m and m["total_supply"] is not None else None),
                ci, now_ts(), got[pid], tr_count.get(tok, 0),
                first_b.get(pid), last_b.get(pid), swap_status, tr_status))
        con.executemany(
            "INSERT OR REPLACE INTO rp_pool VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rowsout)
        con.commit()
        tot_pools += len(grp)
        alive = sum(1 for pid in ids if got[pid] > 0)
        warn = ""
        if swap_status != "ok":
            warn += " SWAPS " + swap_status
        if tr_status != "ok":
            warn += " TRANSFERS " + tr_status
        print(f"  cohorte {ci + 1}/{len(starts)} · bloc {s0:,} · {len(grp)} pools · {alive} vivants · "
              f"{sum(got.values()):,} swaps · {sum(tr_count.values()):,} transferts · "
              f"{time.time() - t0:.0f}s{warn}", flush=True)

    n_pool = con.execute("SELECT COUNT(*) FROM rp_pool").fetchone()[0]
    n_alive = con.execute("SELECT COUNT(*) FROM rp_pool WHERE n_swaps>0").fetchone()[0]
    n_bad = con.execute("SELECT COUNT(*) FROM rp_pool WHERE swaps_status<>'ok'").fetchone()[0]
    out = {"pools_total": n_pool, "vivants": n_alive, "morts_a_la_naissance": n_pool - n_alive,
           "pools_en_echec": n_bad, "swaps": tot_swaps, "transferts": tot_tr,
           "cohortes_en_echec": n_failed, "secondes": round(time.time() - t0, 1)}
    con.close()
    return out


async def main(cohorts: int = 120, per_cohort: int = 40, with_transfers: bool = True) -> None:
    ctx = IntelContext.build()
    try:
        res = await collect(ctx, cohorts=cohorts, per_cohort=per_cohort,
                            with_transfers=with_transfers)
        print("\n=== resultat ===")
        for k, v in res.items():
            print(f"  {k:<22} {v}")
    finally:
        await ctx.close()


if __name__ == "__main__":
    import sys
    c = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    p = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    tr = not (len(sys.argv) > 3 and sys.argv[3] in ("--no-transfers", "0", "no"))
    asyncio.run(main(c, p, tr))
