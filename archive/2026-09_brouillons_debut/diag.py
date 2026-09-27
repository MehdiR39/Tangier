import asyncio, random, sys
sys.path.insert(0, "/app")
from intel.backtest.history import Rules, load_series, replay, _at, monte_carlo
from intel.context import IntelContext
from intel.providers.dexscreener import normalize_pair
sys.path.insert(0, "/app/results")
from size_test import quote_prices, replay as myreplay, CAPITAL

async def main():
    ctx = IntelContext.build()
    qusd = await quote_prices(ctx)
    toks = [r["token_address"] for r in ctx.db.query("SELECT DISTINCT token_address FROM history_meta WHERE chain_id=?", (ctx.chain_id,))]
    series = load_series(ctx, toks, qusd)
    print(f"univers {len(series)} tokens")
    span = (min(s[0][0] for s in series.values()), max(s[-1][0] for s in series.values()))
    print(f"periode {(span[1]-span[0])/86400:.1f} jours")

    # 1. production replay, production rule
    from intel.backtest.history import make_picker
    r = replay(series, Rules("prod", moonbag=1.5, stop=0.75, trail=None, timeout_h=3.0),
               capital=400.0, line=20.0, picker=make_picker("random"), rng=random.Random(7))
    print(f"\nPROD  replay (vend LA MOITIE a x1.5, stop .75, delai 3h): final {r.final:.0f}€  lignes {r.played}")
    r2 = replay(series, Rules("prod18", moonbag=3.0, stop=0.75, trail=0.70, timeout_h=18.0),
               capital=400.0, line=20.0, picker=make_picker("random"), rng=random.Random(7))
    print(f"PROD  replay (moitie x3, trail .70, delai 18h)            : final {r2.final:.0f}€  lignes {r2.played}")

    # 2. mine, size-blind
    f, p, closed, blocked, ln = myreplay(series, k=0.0, alpha=0.0, rng=random.Random(7))
    print(f"MIENNE (vend TOUT a x1.5, stop .75, delai 3h)             : final {f:.0f}€  lignes {p}")
    await ctx.close()

asyncio.run(main())
