"""Backtest on what the engine OBSERVED, not on what I reconstructed.

token_snapshots is written forward by the running engine: the price and the 24 h volume as
DexScreener reported them at the moment the engine looked. Nothing is rebuilt from chain logs,
so none of the reconstruction bugs (pool mixing, missing decimals, swallowed batches) can reach
it. Depth is volume_24h/24 — a lagging proxy for the hour's flow, not the hour itself.

Every run prints how many positions ended STUCK (series ran out while still held, so they are
marked at zero). If that number is large the result measures data gaps, not the strategy.
"""
import random, statistics, sys
sys.path.insert(0, "/app")
from intel.context import IntelContext

CAPITAL, BASE_LINE, FEE = 400.0, 20.0, 0.01
TAKE, STOP, TIMEOUT_H = 1.5, 0.75, 3.0
ENTRY_MIN_VOL, EXIT_MIN_VOL = 2_000.0, 300.0
STALE_S = 3600
MAX_PART, IMPACT_CAP = 0.50, 0.60


def at(s, t):
    lo, hi, best = 0, len(s) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if s[m][0] <= t:
            best = s[m]; lo = m + 1
        else:
            hi = m - 1
    if best is None or t - best[0] > STALE_S:
        return None
    return best[1], best[2]


def cost(notional, depth, k):
    if depth <= 0:
        return None
    p = notional / depth
    return None if p > MAX_PART else min(k * p, IMPACT_CAP)


def replay(series, *, k, alpha, rng, step=600):
    entry_t = {}
    for a, s in series.items():
        for ts, _px, d in s:
            if d >= ENTRY_MIN_VOL:
                entry_t[a] = ts; break
    if not entry_t:
        return None
    t0, end = min(entry_t.values()), max(s[-1][0] for s in series.values())
    arr = sorted(entry_t, key=lambda a: entry_t[a])
    cash, open_pos, played, ai, pool = CAPITAL, {}, 0, 0, []
    why = {"cible": 0, "stop": 0, "delai": 0}
    t = t0
    while t <= end:
        while ai < len(arr) and entry_t[arr[ai]] <= t:
            pool.append(arr[ai]); ai += 1
        for a in list(open_pos):
            pos, cur = open_pos[a], at(series[a], t)
            if cur is None:
                continue
            px, d = cur
            r = px / pos["entry"]
            if d < EXIT_MIN_VOL:
                continue
            ex = "cible" if r >= TAKE else "stop" if r <= 1 - STOP else "delai" if t - pos["t0"] >= TIMEOUT_H * 3600 else None
            if not ex:
                continue
            c = cost(pos["units"] * px, d, k)
            if c is None:
                continue
            cash += pos["units"] * px * (1 - FEE - c)
            why[ex] += 1; del open_pos[a]
        eq = cash + sum(p["units"] * ((at(series[a], t) or (0, 0))[0]) for a, p in open_pos.items())
        line = max(BASE_LINE, BASE_LINE * (eq / CAPITAL) ** alpha)
        slots = max(1, int(eq // line))
        defer = []
        while len(open_pos) < slots and pool and cash >= line:
            a = pool.pop(rng.randrange(len(pool)))
            cur = at(series[a], t)
            if cur is None or cur[0] <= 0 or cur[1] < ENTRY_MIN_VOL:
                defer.append(a); continue
            c = cost(line, cur[1], k)
            if c is None:
                defer.append(a); continue
            cash -= line
            open_pos[a] = {"entry": cur[0], "units": line * (1 - FEE - c) / cur[0], "t0": t}
            played += 1
        pool.extend(defer)
        t += step
    stuck = 0
    for a, pos in open_pos.items():
        cur = at(series[a], end)
        ok = cur and cur[1] >= EXIT_MIN_VOL
        if not ok:
            stuck += 1
        px = cur[0] if ok else 0.0
        cash += pos["units"] * px * (1 - FEE)
    return cash, played, why, stuck, line


def mc(series, *, k, alpha, draws=100, seed=7, frac=0.7):
    toks = sorted(series)
    n = max(2, int(len(toks) * frac))
    fin, pl, st, ln, w = [], [], [], [], {"cible": 0, "stop": 0, "delai": 0}
    for d in range(draws):
        sub = {a: series[a] for a in random.Random(seed * 100_003 + d).sample(toks, min(n, len(toks)))}
        out = replay(sub, k=k, alpha=alpha, rng=random.Random(seed + d))
        if not out:
            continue
        f, p, why, stuck, line = out
        fin.append(f); pl.append(p); st.append(stuck); ln.append(line)
        for kk in w: w[kk] += why[kk]
    fin.sort()
    tot = sum(w.values()) or 1
    return {"median": fin[len(fin) // 2], "worst": fin[0], "best": fin[-1],
            "win": sum(1 for f in fin if f > CAPITAL) / len(fin), "lines": statistics.mean(pl),
            "stuck": statistics.mean(st), "line": statistics.median(ln),
            "cible": w["cible"] / tot, "stop": w["stop"] / tot, "delai": w["delai"] / tot}


ctx = IntelContext.build()
rows = ctx.db.query(
    "SELECT token_address, ts, price_usd, volume_24h FROM token_snapshots "
    "WHERE chain_id=? AND price_usd>0 ORDER BY token_address, ts", (ctx.chain_id,))
series = {}
for r in rows:
    series.setdefault(r["token_address"], []).append((int(r["ts"]), float(r["price_usd"]), float(r["volume_24h"] or 0.0) / 24.0))
series = {a: s for a, s in series.items() if len(s) >= 3}
span = (min(s[0][0] for s in series.values()), max(s[-1][0] for s in series.values()))
gaps = sorted(s[i + 1][0] - s[i][0] for s in series.values() for i in range(len(s) - 1))
print(f"donnees observees en direct : {len(series)} tokens · {(span[1]-span[0])/86400:.1f} jours")
print(f"intervalle median entre deux observations : {gaps[len(gaps)//2]/60:.0f} min\n")

for k in (0.0, 1.0, 2.0):
    lab = "sans effet de taille" if k == 0 else f"effet de taille k={k:g}"
    print(f"===== {lab} =====")
    print(f"{'regle':<24} {'ligne':>7} {'pire':>7} {'mediane':>8} {'meilleur':>9} {'gagnant':>8} {'lignes':>7} {'coinces':>8}")
    for a, nm in ((0.0, "fixe 20 €"), (0.25, "monte tres doucement"), (0.5, "monte a la racine"), (1.0, "plein proportionnel")):
        r = mc(series, k=k, alpha=a)
        print(f"{nm:<24} {r['line']:>6.0f}€ {r['worst']:>6.0f}€ {r['median']:>7.0f}€ {r['best']:>8.0f}€ "
              f"{r['win']:>7.0%} {r['lines']:>7.0f} {r['stuck']:>8.1f}")
    r = mc(series, k=k, alpha=0.0)
    print(f"  sorties : cible x1,5 {r['cible']:.0%} · stop {r['stop']:.0%} · delai 3h {r['delai']:.0%}\n")
