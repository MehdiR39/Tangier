"""Is the money in the settings, or in choosing WHEN to play at all?

Re-tuning the exits on the observed data gave contradictory answers between the two halves of the
period (a 3 h hold wins on the first half, 12 h on the second; the same rule returns 153 EUR on one
half and 407 EUR on the other). When identical rules swing by 2.7x between two consecutive days,
the parameter is not what decides the outcome — the market state is.

So this measures a market-wide gate instead: at each instant, what fraction of the tokens the
engine is tracking are ABOVE their price W hours ago. That number uses only information available
at that instant, chain-wide, and never touches the sub-universe of a draw.
"""
import random, statistics, sys
sys.path.insert(0, "/app")
from intel.context import IntelContext

CAPITAL, LINE, FEE = 400.0, 20.0, 0.01
ENTRY_MIN_VOL, EXIT_MIN_VOL, STALE_S = 2_000.0, 300.0, 3600
MAX_PART, IMPACT_CAP, K = 0.50, 0.60, 1.0
STEP = 600


def at(s, t):
    lo, hi, best = 0, len(s) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if s[m][0] <= t:
            best = s[m]; lo = m + 1
        else:
            hi = m - 1
    return None if best is None or t - best[0] > STALE_S else (best[1], best[2])


def cost(n, d):
    if d <= 0:
        return None
    p = n / d
    return None if p > MAX_PART else min(K * p, IMPACT_CAP)


def breadth_curve(all_series, t_lo, t_hi, window_h):
    """fraction of tracked tokens above their own price `window_h` ago, chain-wide, per bucket"""
    out, w = {}, int(window_h * 3600)
    t = t_lo - t_lo % STEP          # meme grille que celle interrogee par le replay
    while t <= t_hi:
        up = tot = 0
        for s in all_series.values():
            now, then = at(s, t), at(s, t - w)
            if now and then and then[0] > 0:
                tot += 1
                up += now[0] > then[0]
        out[t] = (up / tot) if tot >= 20 else None   # too few observations to judge: unknown
        t += STEP
    return out


def replay(series, *, take, stop, timeout_h, gate, thr, rng):
    entry_t = {}
    for a, s in series.items():
        for ts, _p, d in s:
            if d >= ENTRY_MIN_VOL:
                entry_t[a] = ts; break
    if not entry_t:
        return None
    t0, end = min(entry_t.values()), max(s[-1][0] for s in series.values())
    arr = sorted(entry_t, key=lambda a: entry_t[a])
    cash, op, played, ai, pool, blocked = CAPITAL, {}, 0, 0, [], 0
    slots, t = int(CAPITAL // LINE), t0
    while t <= end:
        while ai < len(arr) and entry_t[arr[ai]] <= t:
            pool.append(arr[ai]); ai += 1
        for a in list(op):
            pos, cur = op[a], at(series[a], t)
            if cur is None:
                continue
            px, d = cur
            r = px / pos["entry"]
            if d < EXIT_MIN_VOL:
                continue
            ex = ("cible" if r >= take else "stop" if stop and r <= 1 - stop
                  else "delai" if timeout_h and t - pos["t0"] >= timeout_h * 3600 else None)
            if not ex:
                continue
            c = cost(pos["units"] * px, d)
            if c is None:
                continue
            cash += pos["units"] * px * (1 - FEE - c)
            del op[a]
        # the gate: an unknown market state is NOT a green light
        b = gate.get(t - t % STEP) if gate is not None else 1.0
        open_now = gate is None or (b is not None and b >= thr)
        if not open_now:
            blocked += 1
        defer = []
        while open_now and len(op) < slots and pool and cash >= LINE:
            a = pool.pop(rng.randrange(len(pool)))
            cur = at(series[a], t)
            if cur is None or cur[0] <= 0 or cur[1] < ENTRY_MIN_VOL:
                defer.append(a); continue
            c = cost(LINE, cur[1])
            if c is None:
                defer.append(a); continue
            cash -= LINE
            op[a] = {"entry": cur[0], "units": LINE * (1 - FEE - c) / cur[0], "t0": t}
            played += 1
        pool.extend(defer)
        t += STEP
    for a, pos in op.items():
        cur = at(series[a], end)
        ok = cur and cur[1] >= EXIT_MIN_VOL
        cash += pos["units"] * (cur[0] if ok else 0.0) * (1 - FEE)
    return cash, played, blocked


def mc(series, *, draws=80, **kw):
    toks = sorted(series)
    if len(toks) < 5:
        return None
    n = max(2, int(len(toks) * 0.7))
    fin, pl, bl = [], [], []
    for d in range(draws):
        sub = {a: series[a] for a in random.Random(7 * 100_003 + d).sample(toks, min(n, len(toks)))}
        out = replay(sub, rng=random.Random(7 + d), **kw)
        if not out:
            continue
        f, p, b = out
        fin.append(f); pl.append(p); bl.append(b)
    if not fin:
        return None
    fin.sort()
    return {"median": fin[len(fin) // 2], "worst": fin[0], "best": fin[-1],
            "win": sum(1 for f in fin if f > CAPITAL) / len(fin), "lines": statistics.mean(pl)}


ctx = IntelContext.build()
rows = ctx.db.query("SELECT token_address, ts, price_usd, volume_24h FROM token_snapshots "
                    "WHERE chain_id=? AND price_usd>0 ORDER BY token_address, ts", (ctx.chain_id,))
allser = {}
for r in rows:
    allser.setdefault(r["token_address"], []).append((int(r["ts"]), float(r["price_usd"]), float(r["volume_24h"] or 0.0) / 24.0))
allser = {a: s for a, s in allser.items() if len(s) >= 3}
sc = ctx.db.query("SELECT token_address, ts, moonshot, hard_filter_pass FROM token_scores WHERE chain_id=? ORDER BY ts", (ctx.chain_id,))
first = {}
for r in sc:
    if r["moonshot"] is not None and r["moonshot"] >= 50 and r["hard_filter_pass"] and r["token_address"] not in first:
        first[r["token_address"]] = int(r["ts"])
uni = {a: [p for p in allser[a] if p[0] >= first[a]] for a in first if a in allser}
uni = {a: s for a, s in uni.items() if len(s) >= 3}
t_lo = min(s[0][0] for s in allser.values()); t_hi = max(s[-1][0] for s in allser.values())
starts = sorted(s[0][0] for s in uni.values()); cut = starts[len(starts) // 2]
A = {a: s for a, s in uni.items() if s[0][0] < cut}
B = {a: s for a, s in uni.items() if s[0][0] >= cut}
print(f"univers score>=50 : {len(uni)} tokens · 1re moitie {len(A)} · 2e moitie {len(B)}")

for wh in (2, 6):
    g = breadth_curve(allser, t_lo, t_hi, wh)
    vals = [v for v in g.values() if v is not None]
    vals.sort()
    print(f"\n=== FEU DE MARCHE · part des tokens en hausse sur {wh} h  (mediane observee {vals[len(vals)//2]:.0%}) ===")
    print(f"{'on achete si':>16} {'1re moitie':>13} {'2e moitie':>13} {'lignes':>8} {'pire (2e)':>11}")
    qs = sorted(v for v in g.values() if v is not None)
    for thr in [None] + [qs[int(len(qs) * f)] for f in (0.25, 0.40, 0.50, 0.60, 0.75)]:
        kw = dict(take=1.5, stop=0.75, timeout_h=12, gate=(None if thr is None else g), thr=(thr or 0.0))
        a, b = mc(A, **kw), mc(B, **kw)
        if not a or not b:
            continue
        lbl = "toujours" if thr is None else f">= {thr:.0%} en hausse"
        print(f"{lbl:>16} {a['median']:>12.0f}€ {b['median']:>12.0f}€ {b['lines']:>8.0f} {b['worst']:>10.0f}€")
