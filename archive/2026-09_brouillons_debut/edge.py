"""The arithmetic underneath everything: what hit rate does this bet need to break even?

Selling all at x1.5 wins +50% minus 2% of round-trip fee. So a line is worth
   p x (+0.48)  +  (1-p) x (mean loss on the rest)
and the break-even p follows directly. Comparing it to the p we actually get says whether the
strategy is a tuning problem or a dead end -- and splitting by score says whether a better filter
could close the gap or whether the model has already given what it has.
"""
import statistics, sys
sys.path.insert(0, "/app")
from intel.context import IntelContext

FEE, TAKE, STOP, TIMEOUT_H = 0.01, 1.5, 0.75, 12.0
ENTRY_MIN_VOL, EXIT_MIN_VOL, STALE_S = 2_000.0, 300.0, 3600


def at(s, t):
    lo, hi, best = 0, len(s) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if s[m][0] <= t:
            best = s[m]; lo = m + 1
        else:
            hi = m - 1
    return None if best is None or t - best[0] > STALE_S else (best[1], best[2])


def outcome(s, t_entry):
    """what one line on this token returns, entered at t_entry, under the current exit rule"""
    cur = at(s, t_entry)
    if cur is None or cur[0] <= 0 or cur[1] < ENTRY_MIN_VOL:
        return None
    entry, end = cur[0], s[-1][0]
    t = t_entry
    while t <= end:
        c = at(s, t)
        if c and c[1] >= EXIT_MIN_VOL:
            r = c[0] / entry
            if r >= TAKE:
                return TAKE, "cible"
            if r <= 1 - STOP:
                return r, "stop"
            if t - t_entry >= TIMEOUT_H * 3600:
                return r, "delai"
        t += 600
    c = at(s, end)
    return ((c[0] / entry) if c and c[1] >= EXIT_MIN_VOL else 0.0), "fin"


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
    firsts.setdefault(r["token_address"], (int(r["ts"]), float(r["moonshot"])))

res = []
for a, (ts, m) in firsts.items():
    if a not in ser:
        continue
    o = outcome(ser[a], ts)
    if o:
        res.append((m, o[0], o[1]))

print(f"{len(res)} lignes evaluees (une par token, a l'instant ou le moteur l'a score)\n")


def report(label, rs):
    if len(rs) < 8:
        print(f"{label:<22} {len(rs):>4} lignes — trop peu")
        return
    mult = [x[1] for x in rs]
    hits = [x for x in mult if x >= TAKE]
    rest = [x for x in mult if x < TAKE]
    p = len(hits) / len(mult)
    gain = TAKE * (1 - FEE) ** 2 - 1
    loss = statistics.mean(rest) * (1 - FEE) ** 2 - 1 if rest else 0.0
    ev = p * gain + (1 - p) * loss
    breakeven = (-loss) / (gain - loss) if gain > loss else float("nan")
    print(f"{label:<22} {len(mult):>4} lignes · atteint x1,5 : {p:>5.1%} · perte moyenne des autres : {loss:>6.1%} · "
          f"gain par ligne : {ev:>+6.1%} · il faudrait {breakeven:.1%}")


report("toutes", res)
print()
for lo, hi in ((0, 40), (40, 50), (50, 60), (60, 70), (70, 101)):
    report(f"score {lo}-{hi}", [x for x in res if lo <= x[0] < hi])
print()
w = {}
for _m, _r, why in res:
    w[why] = w.get(why, 0) + 1
print("sorties :", " · ".join(f"{k} {v} ({v/len(res):.0%})" for k, v in sorted(w.items(), key=lambda kv: -kv[1])))
