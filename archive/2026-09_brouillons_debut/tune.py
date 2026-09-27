"""Re-tune the exit on data the engine observed, choosing on one half and checking on the other.

Every exit number in the config today was chosen on the reconstructed history, which turned out
to be one trade per token. They are therefore unfounded, not merely imprecise. Here each value is
ranked on the FIRST half of the observed period and then read off the SECOND half, which was not
looked at while choosing; a value that only wins on the first half is fitted to noise.
"""
import random, statistics, sys
sys.path.insert(0, "/app")
from intel.context import IntelContext

CAPITAL, LINE, FEE = 400.0, 20.0, 0.01
ENTRY_MIN_VOL, EXIT_MIN_VOL, STALE_S = 2_000.0, 300.0, 3600
MAX_PART, IMPACT_CAP, K = 0.50, 0.60, 1.0


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


def replay(series, *, take, stop, timeout_h, trail, rng, step=600):
    entry_t = {}
    for a, s in series.items():
        for ts, _p, d in s:
            if d >= ENTRY_MIN_VOL:
                entry_t[a] = ts; break
    if not entry_t:
        return None
    t0, end = min(entry_t.values()), max(s[-1][0] for s in series.values())
    arr = sorted(entry_t, key=lambda a: entry_t[a])
    cash, op, played, ai, pool = CAPITAL, {}, 0, 0, []
    why = {"cible": 0, "stop": 0, "delai": 0, "suiveur": 0}
    slots, t = int(CAPITAL // LINE), t0
    while t <= end:
        while ai < len(arr) and entry_t[arr[ai]] <= t:
            pool.append(arr[ai]); ai += 1
        for a in list(op):
            pos, cur = op[a], at(series[a], t)
            if cur is None:
                continue
            px, d = cur
            pos["peak"] = max(pos["peak"], px)
            r, dp = px / pos["entry"], px / pos["peak"] - 1
            if d < EXIT_MIN_VOL:
                continue
            ex = ("cible" if take and r >= take else "stop" if stop and r <= 1 - stop
                  else "suiveur" if trail and dp <= -trail else
                  "delai" if timeout_h and t - pos["t0"] >= timeout_h * 3600 else None)
            if not ex:
                continue
            c = cost(pos["units"] * px, d)
            if c is None:
                continue
            cash += pos["units"] * px * (1 - FEE - c)
            why[ex] += 1; del op[a]
        defer = []
        while len(op) < slots and pool and cash >= LINE:
            a = pool.pop(rng.randrange(len(pool)))
            cur = at(series[a], t)
            if cur is None or cur[0] <= 0 or cur[1] < ENTRY_MIN_VOL:
                defer.append(a); continue
            c = cost(LINE, cur[1])
            if c is None:
                defer.append(a); continue
            cash -= LINE
            op[a] = {"entry": cur[0], "peak": cur[0], "units": LINE * (1 - FEE - c) / cur[0], "t0": t}
            played += 1
        pool.extend(defer)
        t += step
    stuck = 0
    for a, pos in op.items():
        cur = at(series[a], end)
        ok = cur and cur[1] >= EXIT_MIN_VOL
        stuck += 0 if ok else 1
        cash += pos["units"] * (cur[0] if ok else 0.0) * (1 - FEE)
    return cash, played, why, stuck


def mc(series, *, draws=80, **kw):
    toks = sorted(series)
    if len(toks) < 5:
        return None
    n = max(2, int(len(toks) * 0.7))
    fin, pl, st = [], [], []
    w = {"cible": 0, "stop": 0, "delai": 0, "suiveur": 0}
    for d in range(draws):
        sub = {a: series[a] for a in random.Random(7 * 100_003 + d).sample(toks, min(n, len(toks)))}
        out = replay(sub, rng=random.Random(7 + d), **kw)
        if not out:
            continue
        f, p, why, stuck = out
        fin.append(f); pl.append(p); st.append(stuck)
        for k in w: w[k] += why[k]
    if not fin:
        return None
    fin.sort()
    tot = sum(w.values()) or 1
    return {"median": fin[len(fin) // 2], "worst": fin[0], "win": sum(1 for f in fin if f > CAPITAL) / len(fin),
            "lines": statistics.mean(pl), "stuck": statistics.mean(st),
            "cible": w["cible"] / tot, "delai": w["delai"] / tot}


ctx = IntelContext.build()
rows = ctx.db.query("SELECT token_address, ts, price_usd, volume_24h FROM token_snapshots "
                    "WHERE chain_id=? AND price_usd>0 ORDER BY token_address, ts", (ctx.chain_id,))
series = {}
for r in rows:
    series.setdefault(r["token_address"], []).append((int(r["ts"]), float(r["price_usd"]), float(r["volume_24h"] or 0.0) / 24.0))
series = {a: s for a, s in series.items() if len(s) >= 3}
sc = ctx.db.query("SELECT token_address, ts, moonshot, hard_filter_pass FROM token_scores WHERE chain_id=? ORDER BY ts", (ctx.chain_id,))
first = {}
for r in sc:
    if r["moonshot"] is not None and r["moonshot"] >= 50 and r["hard_filter_pass"] and r["token_address"] not in first:
        first[r["token_address"]] = int(r["ts"])
uni = {a: [p for p in series[a] if p[0] >= first[a]] for a in first if a in series}
uni = {a: s for a, s in uni.items() if len(s) >= 3}

starts = sorted(s[0][0] for s in uni.values())
cut = starts[len(starts) // 2]
A = {a: s for a, s in uni.items() if s[0][0] < cut}
B = {a: s for a, s in uni.items() if s[0][0] >= cut}
print(f"univers score>=50 : {len(uni)} tokens · 1re moitie {len(A)} · 2e moitie {len(B)}\n")

print("=== DELAI : au bout de combien de temps lacher la ligne ? (cible x1,5, stop -75 %) ===")
print(f"{'delai':>10} {'1re moitie':>13} {'2e moitie':>13} {'lignes':>8} {'atteint cible':>15}")
for th in (3, 6, 12, 24, 48, None):
    a = mc(A, take=1.5, stop=0.75, timeout_h=th, trail=None)
    b = mc(B, take=1.5, stop=0.75, timeout_h=th, trail=None)
    if not a or not b:
        continue
    print(f"{(str(th)+' h' if th else 'jamais'):>10} {a['median']:>12.0f}€ {b['median']:>12.0f}€ {b['lines']:>8.0f} {b['cible']:>14.0%}")

print("\n=== CIBLE : a quel multiple vendre ? (delai 24 h) ===")
print(f"{'cible':>10} {'1re moitie':>13} {'2e moitie':>13} {'lignes':>8} {'atteint cible':>15}")
for tk in (1.3, 1.5, 2.0, 3.0, 5.0):
    a = mc(A, take=tk, stop=0.75, timeout_h=24, trail=None)
    b = mc(B, take=tk, stop=0.75, timeout_h=24, trail=None)
    if not a or not b:
        continue
    print(f"{('x%g' % tk):>10} {a['median']:>12.0f}€ {b['median']:>12.0f}€ {b['lines']:>8.0f} {b['cible']:>14.0%}")

print("\n=== STOP : ou couper les pertes ? (cible x1,5, delai 24 h) ===")
print(f"{'stop':>10} {'1re moitie':>13} {'2e moitie':>13}")
for sp in (0.30, 0.50, 0.75, None):
    a = mc(A, take=1.5, stop=sp, timeout_h=24, trail=None)
    b = mc(B, take=1.5, stop=sp, timeout_h=24, trail=None)
    if not a or not b:
        continue
    print(f"{('-%d %%' % (sp*100) if sp else 'aucun'):>10} {a['median']:>12.0f}€ {b['median']:>12.0f}€")
