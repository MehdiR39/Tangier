import asyncio, random, sys
sys.path.insert(0, "/app")
from intel.backtest.history import Rules, load_series, replay, make_picker, monte_carlo
from intel.context import IntelContext
from intel.providers.dexscreener import normalize_pair

async def qp(ctx):
    quotes={r["quote_address"] for r in ctx.db.query("SELECT DISTINCT quote_address FROM history_meta WHERE chain_id=?", (ctx.chain_id,)) if r["quote_address"]}
    qusd={}; wrapped=next((a for a,m in ctx.config.quote_assets.items() if m.get("kind")=="native_wrapped"), None)
    for q in quotes:
        m=ctx.config.quote_assets.get(q) or {}
        if m.get("kind")=="stable": qusd[q]=float(m.get("usd",1.0))
    for pr in await ctx.dex.tokens([wrapped]):
        np=normalize_pair(pr)
        if np.get("price_usd"): qusd[np["base_address"]]=float(np["price_usd"])
    for q in quotes:
        if (ctx.config.quote_assets.get(q) or {}).get("kind")=="native": qusd[q]=qusd.get(wrapped,0.0)
    return qusd

async def main():
    ctx=IntelContext.build()
    qusd=await qp(ctx)
    toks=[r["token_address"] for r in ctx.db.query("SELECT DISTINCT token_address FROM history_meta WHERE chain_id=?", (ctx.chain_id,))]
    series=load_series(ctx, toks, qusd)
    print(f"sauvegarde d'hier : {len(series)} tokens exploitables")
    if series:
        span=(min(s[0][0] for s in series.values()), max(s[-1][0] for s in series.values()))
        print(f"fenetre {(span[1]-span[0])/86400:.1f} jours")
    for nm,r in (("moitie x1.5 · stop .75 · delai 3h", Rules("a",moonbag=1.5,stop=0.75,trail=None,timeout_h=3.0)),
                 ("moitie x3 · trail .70 · delai 18h", Rules("b",moonbag=3.0,stop=0.75,trail=0.70,timeout_h=18.0))):
        m=monte_carlo(series, r, capital=400.0, line=20.0, draws=100)
        print(f"  {nm:<36} mediane {m['median']:>7.0f}€ · pire {m['worst']:>6.0f}€ · meilleur {m['best']:>7.0f}€ · gagnant {m['win_rate']:>4.0%} · lignes {m['lines']:.0f}")
    await ctx.close()
asyncio.run(main())
