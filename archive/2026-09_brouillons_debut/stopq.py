"""The one question the stop turns on: do the winners dip before they win?

25% of lines fall 50-90% before we let go, and that bucket alone costs -18.1% per line -- far more
than the outright wipeouts (-2.9%). A tighter stop only recovers that if the tokens which DO reach
x1,5 don't first pass through the same drawdown. So: for every line, the deepest point reached
before its exit, split by whether it ended up hitting the target.
"""
import statistics, sys
sys.path.insert(0, "/app")
from intel.context import IntelContext

FEE, TAKE, TIMEOUT_H = 0.01, 1.5, 12.0
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


def path(s, t0):
    """(hit_target, deepest multiple seen before the exit, exit multiple)"""
    cur = at(s, t0)
    if cur is None or cur[0] <= 0 or cur[1] < ENTRY_MIN_VOL:
        return None
    entry, end, t, low = cur[0], s[-1][0], t0, 1.0
    while t <= end:
        c = at(s, t)
        if c and c[1] >= EXIT_MIN_VOL:
            r = c[0] / entry
            low = min(low, r)
            if r >= TAKE:
                return True, low, TAKE
            if t - t0 >= TIMEOUT_H * 3600:
                return False, low, r
        t += 600
    c = at(s, end)
    r = (c[0] / entry) if c and c[1] >= EXIT_MIN_VOL else 0.0
    return False, min(low, r), r


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
P = []
for a, ts in firsts.items():
    if a in ser:
        p = path(ser[a], ts)
        if p:
            P.append((a, ts, *p))
win = [x for x in P if x[2]]
los = [x for x in P if not x[2]]
print(f"{len(P)} lignes · {len(win)} atteignent x1,5 · {len(los)} non\n")
print("part qui passe SOUS ce niveau avant sa sortie")
print(f"{'niveau':>10} {'gagnantes':>12} {'perdantes':>12}")
for lv in (0.90, 0.80, 0.70, 0.60, 0.50, 0.40, 0.25):
    w = sum(1 for x in win if x[3] <= lv) / len(win)
    l = sum(1 for x in los if x[3] <= lv) / len(los)
    print(f"{'-%d%%' % ((1-lv)*100):>10} {w:>11.0%} {l:>11.0%}")

print("\n=== ce que donnerait chaque stop, sur les memes 199 lignes ===")
print(f"{'stop':>10} {'par ligne':>11} {'gagnantes coupees':>19} {'1re moitie':>12} {'2e moitie':>12}")
P.sort(key=lambda x: x[1])
cut = P[len(P) // 2][1]
for lv in (None, 0.90, 0.80, 0.70, 0.60, 0.50, 0.25):
    def out(x):
        _a, _ts, hit, low, ex = x
        if lv is not None and low <= lv:
            return lv          # the stop fires before anything else can happen
        return TAKE if hit else ex
    rs = [out(x) for x in P]
    a = [out(x) for x in P if x[1] < cut]
    b = [out(x) for x in P if x[1] >= cut]
    cutw = sum(1 for x in win if lv is not None and x[3] <= lv) / len(win)
    print(f"{('-%d%%' % ((1-lv)*100) if lv else 'aucun'):>10} {statistics.mean(r*RT-1 for r in rs):>+10.1%} "
          f"{cutw:>18.0%} {statistics.mean(r*RT-1 for r in a):>+11.1%} {statistics.mean(r*RT-1 for r in b):>+11.1%}")
