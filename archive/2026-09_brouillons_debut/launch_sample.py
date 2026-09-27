"""Fetch the first 45 minutes of trading for pools drawn AT RANDOM from every launch on the chain.

The trades already in the database belong exclusively to tokens the scanner selected, i.e. tokens
that had already attracted liquidity and volume. Measuring a launch scalp on those answers "what
if I bought things I know succeeded". This draws pools without looking at what became of them.

Decimals are deliberately not needed: a RETURN is a ratio of two prices of the same pool, and the
decimals cancel. Only the orientation matters (whether the token is currency0), which pairs stores.
That removes the failure mode that wrecked the earlier collection, where pools whose decimals the
node refused to serve were silently dropped -- itself a selection on what the node felt like
answering.
"""
import asyncio, json, random, sys, time
sys.path.insert(0, "/app")
from intel.context import IntelContext
from intel.backtest.history import TOPIC_V4_SWAP, decode_swap, is_price_at_bound

WINDOW_BLOCKS = 27_000     # ~45 min at 0.1 s a block
SAMPLE = 400
OUT = "/app/data/launch_sample.json"


async def main():
    ctx = IntelContext.build()
    pools = ctx.db.query(
        "SELECT pair_id, token_address, created_block, token_is_currency0 FROM pairs "
        "WHERE chain_id=? AND created_block IS NOT NULL AND token_is_currency0 IS NOT NULL", (ctx.chain_id,))
    pools = [dict(r) for r in pools]
    print(f"{len(pools)} pools avec un bloc de creation connu", flush=True)
    rng = random.Random(11)
    sample = rng.sample(pools, min(SAMPLE, len(pools)))
    head = await ctx.rpc.block_number()
    sample = [p for p in sample if int(p["created_block"]) + WINDOW_BLOCKS <= head]
    print(f"{len(sample)} tires au hasard (fenetre complete disponible)", flush=True)

    out, t0, fails = {}, time.time(), 0
    for i, p in enumerate(sample):
        pid = str(p["pair_id"]).lower()
        b0 = int(p["created_block"])
        try:
            seq = []
            async for _a, _b, logs in ctx.rpc.iter_logs(
                    address=ctx.pool_manager, topics=[TOPIC_V4_SWAP, [pid]],
                    from_block=b0, to_block=b0 + WINDOW_BLOCKS, chunk=WINDOW_BLOCKS):
                for lg in logs:
                    try:
                        ev = decode_swap(lg)
                    except Exception:
                        continue
                    if is_price_at_bound(ev.sqrt_price_x96):
                        continue
                    seq.append([ev.block_number, str(ev.sqrt_price_x96)])
            out[pid] = {"token": p["token_address"], "b0": b0,
                        "is_c0": bool(p["token_is_currency0"]), "swaps": seq}
        except Exception as exc:  # noqa: BLE001
            fails += 1
            out[pid] = {"token": p["token_address"], "b0": b0,
                        "is_c0": bool(p["token_is_currency0"]), "swaps": None, "error": str(exc)[:80]}
        if (i + 1) % 25 == 0:
            done = sum(1 for v in out.values() if v["swaps"] is not None)
            print(f"  {i+1}/{len(sample)} · {done} lus · {fails} echecs · {time.time()-t0:.0f}s", flush=True)

    with open(OUT, "w") as f:
        json.dump(out, f)
    ok = [v for v in out.values() if v["swaps"] is not None]
    empty = sum(1 for v in ok if not v["swaps"])
    print(f"\necrit dans {OUT}")
    print(f"{len(ok)}/{len(sample)} pools lus · {fails} echecs · {empty} sans AUCUN trade en 45 min "
          f"({empty/len(ok):.0%} des lancements ne demarrent jamais)")
    await ctx.close()

asyncio.run(main())
