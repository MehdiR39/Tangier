"""Is there ANY exit rule with a positive expectation, on both halves of the period?

Expectation per line, not final capital: it does not depend on slots, cash or draw order, so it
isolates the bet itself. Rules are ranked on the first half and read off the second; a rule that
only works on the half it was chosen from is noise, and the whole point today is to stop shipping
those. A trailing stop is included because 34% of lines currently die on the clock, not on a level.
"""
import statistics, sys
sys.path.insert(0, "/app")
from intel.context import IntelContext

FEE = 0.01
ENTRY_MIN_VOL, EXIT_MIN_VOL, STALE_S = 2_000.0, 300.0, 3600
RT = (1 - FEE) ** 2


def at(s, t):
    lo, hi, best = 0, len(s) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if s[m][0] <= t:
            best = s[m]; lo = m + 1
        else:
            hi = m - 1
    return None if best is None or t - best[0] > STALE_S else (best[1], best[2])


def outcome(s, t0, take, stop, trail, timeout_h):
    cur = at(s, t0)
    if cur is None or cur[0] <= 0 or cur[1] < ENTRY_MIN_VOL:
        return None
    entry, peak, end, t = cur[0], cur[0], s[-1][0], t0
    while t <= end:
        c = at(s, t)
        if c and c[1] >= EXIT_MIN_VOL:
            px = c[0]
            peak = max(peak, px)
            r = px / entry
            if take and r >= take:
                return take
            if stop and r <= 1 - stop:
                return r
            if trail and px / peak - 1 <= -trail:
                return r
            if timeout_h and t - t0 >= timeout_h * 3600:
                return r
        t += 600
    c = at(s, end)
    return (c[0] / entry) if c and c[1] >= EXIT_MIN_VOL else 0.0


ctx = IntelContext.build()
rows = ctx.db.query("SELECT token_address, ts, price_usd, volume_24h FROM token_snapshots "
                    "WHERE chain_id=? AND price_usd>0 ORDER BY token_address, ts", (ctx.chain_id,))
ser = {}
for r in rows:
    ser.setdefault(r["token_address"], []).append((int(r["ts"]), float(r["price_usd"]), float(r["volume_24h"] or 0.0) / 24.0))
ser = {a: s for a, s in ser.items() if len(s) >= 3}
sc = ctx.db.query("SELECT token_address, ts, moonshot, hard_filter_pass FROM token_scores WHERE chain_id=? ORDER BY ts", (ctx.chain_id,))
firsts = {}
for r in sc:
    if r["moonshot"] is None or not r["hard_filter_pass"]:
        continue
    firsts.setdefault(r["token_address"], int(r["ts"]))
lines = [(a, ts) for a, ts in firsts.items() if a in ser]
lines.sort(key=lambda x: x[1])
cut = lines[len(lines) // 2][1]
A = [x for x in lines if x[1] < cut]
B = [x for x in lines if x[1] >= cut]
print(f"{len(lines)} lignes · 1re moitie {len(A)} · 2e moitie {len(B)}\n")


def ev(sub, **kw):
    rs = [outcome(ser[a], ts, **kw) for a, ts in sub]
    rs = [r for r in rs if r is not None]
    if len(rs) < 15:
        return None, 0
    return statistics.mean(r * RT - 1 for r in rs), len(rs)


grid = []
for take in (1.2, 1.3, 1.5, 2.0, None):
    for stop in (0.20, 0.30, 0.50, None):
        for trail in (0.20, 0.35, None):
            for th in (3, 6, 12, 24):
                a, na = ev(A, take=take, stop=stop, trail=trail, timeout_h=th)
                b, nb = ev(B, take=take, stop=stop, trail=trail, timeout_h=th)
                if a is None or b is None:
                    continue
                grid.append((a, b, take, stop, trail, th, na, nb))

grid.sort(key=lambda x: -x[0])          # ranked on the FIRST half only
print("=== les 10 meilleures sur la 1re moitie, et ce qu'elles donnent sur la 2e ===")
print(f"{'cible':>7} {'stop':>7} {'suiveur':>8} {'delai':>7} {'1re moitie':>12} {'2e moitie':>12}")
for a, b, take, stop, trail, th, na, nb in grid[:10]:
    print(f"{('x%g'%take if take else '-'):>7} {('-%d%%'%(stop*100) if stop else '-'):>7} "
          f"{('-%d%%'%(trail*100) if trail else '-'):>8} {str(th)+'h':>7} {a:>+11.1%} {b:>+11.1%}")

both = [g for g in grid if g[0] > 0 and g[1] > 0]
print(f"\nreglages a esperance POSITIVE sur les deux moities : {len(both)} / {len(grid)}")
for a, b, take, stop, trail, th, na, nb in sorted(both, key=lambda x: -min(x[0], x[1]))[:10]:
    print(f"  cible {('x%g'%take if take else '-'):>5} · stop {('-%d%%'%(stop*100) if stop else '-'):>5} · "
          f"suiveur {('-%d%%'%(trail*100) if trail else '-'):>5} · delai {str(th)+'h':>4} : "
          f"1re {a:>+6.1%} · 2e {b:>+6.1%}")
