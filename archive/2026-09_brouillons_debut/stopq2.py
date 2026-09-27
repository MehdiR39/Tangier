"""The same stop test, without the free lunch.

The previous version exited a -9% stop AT -9%. That price is not available: the engine sees a
quote every ~12 min, so the fill is the first observed price BELOW the level, which on these
tokens can be far below it. Here each line keeps its whole observed path and a stop exits at the
first price actually printed under the trigger -- the gap between the two is the honest cost of a
tight stop, and it is exactly the kind of optimism that produced today's retracted numbers.
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
    """the sequence of multiples the engine would actually have SEEN, in order"""
    cur = at(s, t0)
    if cur is None or cur[0] <= 0 or cur[1] < ENTRY_MIN_VOL:
        return None
    entry, end, t, seq = cur[0], s[-1][0], t0, []
    last = None
    while t <= end:
        c = at(s, t)
        if c and c[1] >= EXIT_MIN_VOL and c[0] != last:
            seq.append(c[0] / entry)
            last = c[0]
            if c[0] / entry >= TAKE or t - t0 >= TIMEOUT_H * 3600:
                return seq, True
        t += 600
    c = at(s, end)
    seq.append((c[0] / entry) if c and c[1] >= EXIT_MIN_VOL else 0.0)
    return seq, False


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
        if p and p[0]:
            P.append((ts, p[0]))
P.sort()
cut = P[len(P) // 2][0]
print(f"{len(P)} lignes · ecart median entre deux prix vus : 12 min\n")


def result(seq, lv):
    """walk the observed prices in order; the stop fills at the first one printed under it"""
    for r in seq:
        if lv is not None and r <= lv:
            return r                      # the price we actually see, not the trigger
        if r >= TAKE:
            return TAKE
    return seq[-1]


print(f"{'stop vise':>11} {'sortie reelle moy.':>19} {'par ligne':>11} {'1re moitie':>12} {'2e moitie':>12}")
for lv in (None, 0.90, 0.85, 0.80, 0.70, 0.60, 0.50, 0.25):
    rs = [result(sq, lv) for _t, sq in P]
    a = [result(sq, lv) for t, sq in P if t < cut]
    b = [result(sq, lv) for t, sq in P if t >= cut]
    fired = [r for r in rs if lv is not None and r <= lv]
    fill = statistics.mean(fired) if fired else float("nan")
    lab = f"-{(1-lv)*100:.0f}%" if lv else "aucun"
    fillst = f"x{fill:.2f} ({len(fired)} fois)" if fired else "-"
    print(f"{lab:>11} {fillst:>19} {statistics.mean(r*RT-1 for r in rs):>+10.1%} "
          f"{statistics.mean(r*RT-1 for r in a):>+11.1%} {statistics.mean(r*RT-1 for r in b):>+11.1%}")
