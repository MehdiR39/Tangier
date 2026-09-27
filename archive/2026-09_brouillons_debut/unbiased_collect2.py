"""Collect 24 h of price history for launches drawn WITHOUT looking at what became of them.

Everything measured so far came from `trades`, which only ever held tokens the scanner had already
selected for having liquidity and volume -- i.e. tokens that had already worked. Buying any of them
at random returned +73% median, which is the bias speaking, not a strategy. Every number computed
on that table is therefore meaningless in absolute terms.

Sampling here is by COHORT: random one-hour windows across the chain's history, and every pool
born in that window, dead ones included. That keeps the queries bounded (one log request covers a
whole cohort through the topic filter) while leaving the sample unconditioned on any outcome.

Two lessons from today are built in:
  - decimals are never fetched. A return is a ratio of two prices of the same pool, so decimals
    cancel; the previous collection silently dropped every pool whose decimals the node refused,
    which selected on what the node felt like answering.
  - failures are counted and printed, never swallowed. The run that reported "1800/1800" had in
    fact rebuilt one trade per token.
"""
import asyncio, random, sqlite3, sys, time
sys.path.insert(0, "/app")
from intel.context import IntelContext
from intel.backtest.history import TOPIC_V4_SWAP, decode_swap, is_price_at_bound

COHORTS = 90
COHORT_BLOCKS = 36_000        # ~1 h of launches
FOLLOW_BLOCKS = 864_000       # ~24 h of trading after the cohort closes
MAX_PER_COHORT = 40
CHUNK = 150_000
DB = "/app/data/unbiased2.sqlite"


async def main():
    ctx = IntelContext.build()
    head = await ctx.rpc.block_number()
    rng = random.Random(23)
    rows = ctx.db.query(
        "SELECT pair_id, token_address, created_block, token_is_currency0, quote_address "
        "FROM pairs WHERE chain_id=? AND created_block IS NOT NULL AND token_is_currency0 IS NOT NULL "
        "ORDER BY created_block", (ctx.chain_id,))
    pools = [dict(r) for r in rows]
    lo, hi = pools[0]["created_block"], head - FOLLOW_BLOCKS - COHORT_BLOCKS
    print(f"{len(pools):,} pools · blocs {lo:,} a {head:,} · fenetres tirables jusqu'a {hi:,}", flush=True)

    # cohorts drawn where launches ACTUALLY are: uniform sampling of block space hit 21 empty
    # hours out of 30, because pool creation is concentrated in recent history. Anchoring each
    # cohort on a randomly drawn pool weights the draw by launch density without conditioning
    # on any outcome -- every pool of the chosen hour is then taken, dead ones included.
    anchors = [p["created_block"] for p in pools if p["created_block"] <= hi]
    starts = sorted(rng.sample(anchors, min(COHORTS, len(anchors))))
    con = sqlite3.connect(DB)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS pool(pair_id TEXT PRIMARY KEY, token TEXT, b0 INTEGER,
                                        is_c0 INTEGER, quote TEXT, cohort INTEGER, swaps INTEGER);
        CREATE TABLE IF NOT EXISTS swap(pair_id TEXT, block INTEGER, sqrt TEXT, a0 TEXT, a1 TEXT);
        CREATE INDEX IF NOT EXISTS ix_swap ON swap(pair_id, block);
    """)
    t_start, total_pools, total_swaps, failed = time.time(), 0, 0, 0
    for ci, s0 in enumerate(starts):
        s1 = s0 + COHORT_BLOCKS
        grp = [p for p in pools if s0 <= p["created_block"] < s1]
        if len(grp) > MAX_PER_COHORT:
            grp = rng.sample(grp, MAX_PER_COHORT)
        if not grp:
            print(f"  cohorte {ci+1}/{COHORTS}: aucun lancement dans cette heure", flush=True)
            continue
        ids = [str(p["pair_id"]).lower() for p in grp]
        idset = set(ids)
        stop = min(head, s1 + FOLLOW_BLOCKS)
        got = {i: 0 for i in ids}
        try:
            async for _a, _b, logs in ctx.rpc.iter_logs(address=ctx.pool_manager,
                                                        topics=[TOPIC_V4_SWAP, ids],
                                                        from_block=s0, to_block=stop, chunk=CHUNK):
                batch = []
                for lg in logs:
                    pid = str(lg["topics"][1]).lower()
                    if pid not in idset:
                        continue
                    try:
                        ev = decode_swap(lg)
                    except Exception:
                        continue
                    if is_price_at_bound(ev.sqrt_price_x96):
                        continue
                    if got[pid] >= 5000:
                        continue
                    got[pid] += 1
                    batch.append((pid, ev.block_number, str(ev.sqrt_price_x96),
                                  str(ev.amount0), str(ev.amount1)))
                if batch:
                    con.executemany("INSERT INTO swap VALUES(?,?,?,?,?)", batch)
                    total_swaps += len(batch)
            con.executemany("INSERT OR REPLACE INTO pool VALUES(?,?,?,?,?,?,?)",
                            [(str(p["pair_id"]).lower(), p["token_address"], int(p["created_block"]),
                              1 if p["token_is_currency0"] else 0, p["quote_address"], ci,
                              got[str(p["pair_id"]).lower()]) for p in grp])
            con.commit()
            total_pools += len(grp)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  cohorte {ci+1}/{COHORTS} ECHOUEE ({str(exc)[:90]})", flush=True)
            continue
        alive = sum(1 for v in got.values() if v > 0)
        print(f"  cohorte {ci+1}/{COHORTS} · bloc {s0:,} · {len(grp)} pools · {alive} vivants · "
              f"{sum(got.values()):,} swaps · {time.time()-t_start:.0f}s", flush=True)

    n_alive = con.execute("SELECT COUNT(*) FROM pool WHERE swaps>0").fetchone()[0]
    print(f"\n=== {total_pools} pools collectes dans {COHORTS-failed} cohortes ({failed} echecs) ===")
    print(f"{total_swaps:,} swaps · {n_alive} pools ayant echange au moins une fois "
          f"({n_alive/total_pools:.0%}) · {total_pools-n_alive} morts a la naissance")
    con.close()
    await ctx.close()

asyncio.run(main())
