"""Second pass: ERC20 transfers for every launch that traded, on the unbiased sample.

The wide pass took swaps only, because transfers weigh fifty times more and would have capped the
sample at a few hundred launches. Swaps give price, size and depth; they cannot give the two
things the layered test turns on -- who is buying (holders, new wallets, concentration, the
deployer's share) and whether the flow is organic. Those live in transfers.

Scope and cost, chosen deliberately:
  - only pools with at least one swap (a pool nobody ever traded has no holders to count);
  - a 2 h window after the cohort closes: the features are read at T+5..T+60 min, and a longer
    window multiplies the rows for a horizon no feature uses;
  - at most MAX_PER_TOKEN rows per token: the first thousands of transfers are the ones that
    describe adoption; beyond that it is the same wallets churning.
Status is written per pool, failures are retried and counted, and the run resumes by cohort.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any

from intel.context import IntelContext
from intel.research import RESEARCH_DB
from intel.research.collect import COHORT_BLOCKS, TOPIC_TRANSFER, _addr, _int
from intel.research.schema import connect

TRANSFER_FOLLOW = 72_000       # ~2 h
MAX_PER_TOKEN = 5_000
# Measured on the first 8 cohorts: 151 rate-limit refusals in 30 minutes, each costing 10-20 s of
# back-off -- most of the elapsed time. The node objects to the CADENCE of address-array queries,
# not their size, so requests are paced and the address list kept short. Slower per request,
# far faster overall.
BATCH_TOKENS = 25
PACE_S = 1.5


async def run(ctx: IntelContext, db_path: str = RESEARCH_DB) -> dict[str, Any]:
    con = connect(db_path)
    head = await ctx.rpc.block_number()
    pools = [dict(r) for r in con.execute(
        "SELECT pair_id, token_address, cohort, created_block, transfers_status FROM rp_pool "
        "WHERE n_swaps > 0")]
    by_cohort: dict[int, list[dict]] = defaultdict(list)
    for p in pools:
        by_cohort[p["cohort"]].append(p)
    todo = {c: ps for c, ps in by_cohort.items()
            if any(p["transfers_status"] != "ok" for p in ps)}
    print(f"{len(pools)} pools vivants · {len(by_cohort)} cohortes · {len(todo)} a faire", flush=True)

    t0, tot, n_fail = time.time(), 0, 0
    for i, (ci, ps) in enumerate(sorted(todo.items())):
        s0 = min(int(p["created_block"]) for p in ps)
        s1 = s0 + COHORT_BLOCKS
        toks = sorted({str(p["token_address"]).lower() for p in ps})
        count = {t: 0 for t in toks}
        status = "ok"
        # The five densest cohorts (the most recent ones) failed three times with "log query timed
        # out": the node gives up on a 40 000-block chunk over 25 tokens when the period is busy,
        # and iter_logs only shrinks on "too large", not on a timeout. Each retry therefore asks
        # for less per request -- smaller chunks AND fewer tokens -- instead of asking the same
        # thing again and hoping.
        # nb_tokens, not "batch": the inner loop already uses `batch` for the row list, and the
        # collision turned the token-slice arithmetic into int + list on the second slice
        for attempt, (chunk, nb_tokens) in enumerate(((40_000, BATCH_TOKENS), (12_000, 10), (4_000, 5))):
            count = {t: 0 for t in toks}
            con.execute("DELETE FROM rp_transfer WHERE token_address IN (%s)" % ",".join("?" * len(toks)), toks)
            try:
                for j in range(0, len(toks), nb_tokens):
                    sub = toks[j: j + nb_tokens]
                    async for _a, _b, logs in ctx.rpc.iter_logs(
                            address=sub, topics=[TOPIC_TRANSFER],
                            from_block=s0, to_block=min(head, s1 + TRANSFER_FOLLOW), chunk=chunk):
                        batch = []
                        for lg in logs:
                            tp = lg.get("topics") or []
                            if len(tp) < 3:
                                continue
                            tok = str(lg["address"]).lower()
                            if tok not in count or count[tok] >= MAX_PER_TOKEN:
                                continue
                            count[tok] += 1
                            data = lg.get("data")
                            val = _int(data) if data not in (None, "0x", "") else 0
                            batch.append((tok, _int(lg["blockNumber"]), _int(lg.get("logIndex")),
                                          _addr(tp[1]), _addr(tp[2]), str(val)))
                        if batch:
                            con.executemany("INSERT OR IGNORE INTO rp_transfer VALUES(?,?,?,?,?,?)", batch)
                            tot += len(batch)
                        await asyncio.sleep(PACE_S * (attempt + 1))   # breathe more on each retry
                status = "ok"
                break
            except Exception as exc:  # noqa: BLE001
                status = "failed:" + str(exc)[:60]
                if attempt < 2:
                    await asyncio.sleep(20 * (attempt + 1))
        if status != "ok":
            n_fail += 1
        con.executemany(
            "UPDATE rp_pool SET n_transfers=?, transfers_status=? WHERE pair_id=?",
            [(count.get(str(p["token_address"]).lower(), 0), status, p["pair_id"]) for p in ps])
        con.commit()
        capped = sum(1 for v in count.values() if v >= MAX_PER_TOKEN)
        print(f"  cohorte {ci} ({i + 1}/{len(todo)}) · {len(toks)} tokens · "
              f"{sum(count.values()):,} transferts · {capped} plafonnes · {time.time() - t0:.0f}s"
              f"{'' if status == 'ok' else ' ' + status}", flush=True)

    n_ok = con.execute("SELECT COUNT(*) FROM rp_pool WHERE n_swaps>0 AND transfers_status='ok'").fetchone()[0]
    n_rows = con.execute("SELECT COUNT(*) FROM rp_transfer").fetchone()[0]
    con.close()
    return {"pools_ok": n_ok, "pools_vivants": len(pools), "transferts": n_rows,
            "cohortes_en_echec": n_fail, "secondes": round(time.time() - t0, 1)}


if __name__ == "__main__":
    async def main() -> None:
        ctx = IntelContext.build()
        try:
            res = await run(ctx)
            print("\n=== resultat ===")
            for k, v in res.items():
                print(f"  {k:<18} {v}")
        finally:
            await ctx.close()
    asyncio.run(main())
