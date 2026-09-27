"""What are the losses MADE OF? Wipeouts we could have filtered, or ordinary decay?

If the -43% average loser is a handful of tokens going to zero, better security/liquidity checks
recover it. If it is broad decay across most lines, no filter fixes it and the bet itself is wrong.
Also re-checks the tail: one rule scored +6 739 790% on the first half, which is a corrupted price,
not a trade, so the headline numbers get recomputed with absurd multiples excluded.
"""
import statistics, sys
sys.path.insert(0, "/app")
from intel.context import IntelContext

FEE, TAKE, STOP, TIMEOUT_H = 0.01, 1.5, 0.75, 12.0
ENTRY_MIN_VOL, EXIT_MIN_VOL, STALE_S = 2_000.0, 300.0, 3600
RT = (1 - FEE) ** 2
SANE_MAX = 100.0     # a x100 inside 12 h on a token we could actually sell: treat as bad data


def at(s, t):
    lo, hi, best = 0, len(s) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if s[m][0] <= t:
            best = s[m]; lo = m + 1
        else:
            hi = m - 1
    return None if best is None or t - best[0] > STALE_S else (best[1], best[2])


def outcome(s, t0):
    cur = at(s, t0)
    if cur is None or cur[0] <= 0 or cur[1] < ENTRY_MIN_VOL:
        return None
    entry, end, t = cur[0], s[-1][0], t0
    while t <= end:
        c = at(s, t)
        if c and c[1] >= EXIT_MIN_VOL:
            r = c[0] / entry
            if r >= TAKE:
                return TAKE
            if r <= 1 - STOP:
                return r
            if t - t0 >= TIMEOUT_H * 3600:
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

res = []
for a, ts in firsts.items():
    if a not in ser:
        continue
    o = outcome(ser[a], ts)
    if o is not None:
        res.append((a, o))
absurd = [x for x in res if x[1] > SANE_MAX]
res = [x for x in res if x[1] <= SANE_MAX]
mult = sorted(r for _a, r in res)
print(f"{len(mult)} lignes ({len(absurd)} ecartees comme prix aberrant)\n")

buckets = [("perte totale (<= -90%)", lambda r: r <= 0.10),
           ("tres lourde (-90 a -50%)", lambda r: 0.10 < r <= 0.50),
           ("lourde (-50 a -25%)", lambda r: 0.50 < r <= 0.75),
           ("legere (-25 a 0%)", lambda r: 0.75 < r < 1.0),
           ("a l'equilibre", lambda r: r == 1.0),
           ("gagnante (0 a +50%)", lambda r: 1.0 < r < TAKE),
           ("cible atteinte (x1,5)", lambda r: r >= TAKE)]
print(f"{'issue':<26} {'lignes':>7} {'part':>7} {'contribution':>14}")
for nm, fn in buckets:
    sel = [r for r in mult if fn(r)]
    contrib = sum(r * RT - 1 for r in sel) / len(mult) if mult else 0
    print(f"{nm:<26} {len(sel):>7} {len(sel)/len(mult):>6.0%} {contrib:>+13.1%}")

p = sum(1 for r in mult if r >= TAKE) / len(mult)
loss = statistics.mean(r * RT - 1 for r in mult if r < TAKE)
gain = TAKE * RT - 1
print(f"\ntotal par ligne : {statistics.mean(r*RT-1 for r in mult):+.1%}")
print(f"atteint x1,5 : {p:.1%} · il en faudrait {(-loss)/(gain-loss):.1%}")
print(f"mediane : x{statistics.median(mult):.2f} · moyenne : x{statistics.mean(mult):.2f}")
wipe = sum(1 for r in mult if r <= 0.10)
print(f"\nsi on evitait TOUTES les pertes totales ({wipe} lignes, {wipe/len(mult):.0%}) :")
rest = [r for r in mult if r > 0.10]
print(f"   resultat par ligne : {statistics.mean(r*RT-1 for r in rest):+.1%}")
