"""Does a bigger line still get out?

replay() in intel/backtest/history.py gates entries and exits on ABSOLUTE hourly volume
(2 000 $ / 300 $), never on the size of the order relative to the book. A 20 EUR line and a
65 EUR line therefore face an identical world there, and "bigger lines" is pure arithmetic.

This adds the missing term: an order of N USD hitting a token that trades V USD an hour pays
a cost proportional to its participation N/V, and is refused outright above MAX_PART. K is
unknown, so it is swept rather than assumed. K=0 reproduces the current (size-blind) model.
"""
import asyncio, random, statistics, sys
sys.path.insert(0, "/app")

from intel.backtest.history import load_series, _at
from intel.context import IntelContext
from intel.providers.dexscreener import normalize_pair

CAPITAL, BASE_LINE = 400.0, 20.0
FEE = 0.01
TAKE, STOP, TIMEOUT_H = 1.5, 0.75, 3.0        # vendre TOUT a x1.5, stop -75 %, sortie 3 h
ENTRY_MIN_VOL, EXIT_MIN_VOL = 2_000.0, 300.0
MAX_PART = 0.50                                # au-dela, l'ordre ne passe pas du tout
IMPACT_CAP = 0.60


def cost(notional, depth, k):
    """Fraction of the notional lost to moving the price. None = the order cannot be executed."""
    if depth <= 0:
        return None
    part = notional / depth
    if part > MAX_PART:
        return None
    return min(k * part, IMPACT_CAP)


def replay(series, *, k, alpha, rng, step=600, warmup_h=2.0):
    entry_t = {}
    for t, s in series.items():
        for ts, _px, liq in s:
            if liq >= ENTRY_MIN_VOL:
                entry_t[t] = ts
                break
    if not entry_t:
        return CAPITAL, 0, [], 0, BASE_LINE
    t0, end = min(entry_t.values()), max(s[-1][0] for s in series.values())
    by_arrival = sorted(entry_t, key=lambda a: entry_t[a])
    cash, open_pos, closed, played, ai, pool = CAPITAL, {}, [], 0, 0, []
    blocked, last_line, t = 0, BASE_LINE, t0
    while t <= end:
        while ai < len(by_arrival) and entry_t[by_arrival[ai]] <= t:
            pool.append(by_arrival[ai]); ai += 1
        for a in list(open_pos):
            pos, cur = open_pos[a], _at(series[a], t)
            if cur is None:
                continue
            px, depth = cur
            r = px / pos["entry"]
            if depth < EXIT_MIN_VOL:
                continue
            ex = "cible" if r >= TAKE else "stop" if r <= 1 - STOP else "delai" if t - pos["t0"] >= TIMEOUT_H * 3600 else None
            if not ex:
                continue
            c = cost(pos["units"] * px, depth, k)
            if c is None:
                blocked += 1
                continue                      # trop gros pour ce carnet : on reste coince
            cash += pos["units"] * px * (1 - FEE - c)
            closed.append(r); del open_pos[a]
        equity = cash + sum(p["units"] * (_at(series[a], t) or (0, 0))[0] for a, p in open_pos.items())
        line = max(BASE_LINE, BASE_LINE * (equity / CAPITAL) ** alpha)
        last_line = line
        slots = max(1, int(equity // line))
        deferred = []
        while t >= t0 + warmup_h * 3600 and len(open_pos) < slots and pool and cash >= line:
            a = pool.pop(rng.randrange(len(pool)))
            cur = _at(series[a], t)
            if cur is None or cur[0] <= 0 or cur[1] < ENTRY_MIN_VOL:
                deferred.append(a); continue
            c = cost(line, cur[1], k)
            if c is None:
                deferred.append(a); continue  # la ligne est trop grosse pour ce token
            cash -= line
            open_pos[a] = {"entry": cur[0], "peak": cur[0], "units": line * (1 - FEE - c) / cur[0], "t0": t}
            played += 1
        pool.extend(deferred)
        t += step
    for a, pos in open_pos.items():
        cur = _at(series[a], end)
        ok = cur and cur[1] >= EXIT_MIN_VOL and cost(pos["units"] * cur[0], cur[1], k) is not None
        px = cur[0] if ok else 0.0
        c = cost(pos["units"] * px, cur[1], k) if ok else 0.0
        cash += pos["units"] * px * (1 - FEE - c)
        closed.append(px / pos["entry"])
    return cash, played, closed, blocked, last_line


def mc(series, *, k, alpha, draws=100, seed=7, frac=0.7):
    toks = sorted(series)
    n = max(2, int(len(toks) * frac))
    fin, pl, bl, ln = [], [], [], []
    for d in range(draws):
        sub_rng = random.Random(seed * 100_003 + d)
        sub = {a: series[a] for a in sub_rng.sample(toks, min(n, len(toks)))}
        f, p, _c, b, l = replay(sub, k=k, alpha=alpha, rng=random.Random(seed + d))
        fin.append(f); pl.append(p); bl.append(b); ln.append(l)
    fin.sort()
    return {"median": fin[len(fin) // 2], "worst": fin[0], "best": fin[-1],
            "win": sum(1 for f in fin if f > CAPITAL) / len(fin),
            "lines": statistics.mean(pl), "blocked": statistics.mean(bl),
            "final_line": statistics.median(ln)}


async def quote_prices(ctx):
    quotes = {r["quote_address"] for r in ctx.db.query(
        "SELECT DISTINCT quote_address FROM history_meta WHERE chain_id=?", (ctx.chain_id,)) if r["quote_address"]}
    qusd, wrapped = {}, next((a for a, m in ctx.config.quote_assets.items() if m.get("kind") == "native_wrapped"), None)
    for q in quotes:
        m = ctx.config.quote_assets.get(q) or {}
        if m.get("kind") == "stable":
            qusd[q] = float(m.get("usd", 1.0))
    for pr in await ctx.dex.tokens([wrapped]):
        np = normalize_pair(pr)
        if np.get("price_usd"):
            qusd[np["base_address"]] = float(np["price_usd"])
    for q in quotes:
        if (ctx.config.quote_assets.get(q) or {}).get("kind") == "native":
            qusd[q] = qusd.get(wrapped, 0.0)
    return qusd


async def main():
    ctx = IntelContext.build()
    qusd = await quote_prices(ctx)
    toks = [r["token_address"] for r in ctx.db.query(
        "SELECT DISTINCT token_address FROM history_meta WHERE chain_id=?", (ctx.chain_id,))]
    series = load_series(ctx, toks, qusd)
    print(f"{len(series)} tokens · 400 € · vendre tout a x1,5 · 100 tirages\n")

    ALPHAS = [(0.0, "fixe 20 €"), (0.25, "monte tres doucement"), (0.5, "monte a la racine"),
              (0.75, "monte presque en plein"), (1.0, "plein proportionnel")]
    for k in (0.0, 0.5, 1.0, 2.0):
        lab = "AUCUN impact de taille (modele actuel)" if k == 0 else f"impact k={k:g}"
        print(f"===== {lab} =====")
        print(f"{'regle':<26} {'ligne fin':>10} {'pire':>8} {'mediane':>9} {'meilleur':>9} {'gagnant':>8} {'lignes':>7} {'bloque':>7}")
        for a, name in ALPHAS:
            r = mc(series, k=k, alpha=a)
            print(f"{name:<26} {r['final_line']:>9.0f}€ {r['worst']:>7.0f}€ {r['median']:>8.0f}€ "
                  f"{r['best']:>8.0f}€ {r['win']:>7.0%} {r['lines']:>7.0f} {r['blocked']:>7.1f}")
        print()
    await ctx.close()


asyncio.run(main())
