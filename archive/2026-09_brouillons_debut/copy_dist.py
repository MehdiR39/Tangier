"""Is the tail that carries the copy-trade result real, or is it bad prices?

A mean of +173% on a median of 1.00 is carried entirely by a handful of lines. Either those are
genuine moonshots -- which is exactly what this kind of book lives on -- or they are the same
corrupted prints that produced a +6 739 790% rule earlier today. So: the full distribution, the
mean after capping the tail at several levels, and the actual biggest winners printed out so their
prices can be eyeballed rather than trusted.
"""
import statistics, sys
from collections import defaultdict
sys.path.insert(0, "/app")
from intel.context import IntelContext

MIN_TOKENS_P1, TOP_FRAC, FEE, HOLD_H = 3, 0.05, 0.02, 6

ctx = IntelContext.build()
rows = ctx.db.query(
    "SELECT token_address, trader, ts, side, token_amount_float amt, usd_value usd, price_usd px "
    "FROM trades WHERE chain_id=? AND price_usd>0 AND trader IS NOT NULL ORDER BY ts", (ctx.chain_id,))
cut = rows[len(rows) // 2]["ts"]
last_px = {}
for r in rows:
    last_px[r["token_address"]] = float(r["px"])
pos = defaultdict(lambda: [0.0, 0.0, 0.0])
for r in rows:
    if r["ts"] >= cut:
        continue
    k = (r["trader"], r["token_address"])
    u, v = float(r["amt"] or 0.0), float(r["usd"] or 0.0)
    if r["side"] == "BUY":
        pos[k][0] += u; pos[k][2] += v; pos[k][1] -= v
    else:
        pos[k][0] -= u; pos[k][1] += v
agg = defaultdict(lambda: [0.0, 0.0, set()])
for (w, tok), (units, cash, inv) in pos.items():
    if inv <= 0:
        continue
    agg[w][0] += cash + max(0.0, units) * last_px.get(tok, 0.0)
    agg[w][1] += inv
    agg[w][2].add(tok)
elig = {w: (v[0] / v[1]) for w, v in agg.items() if v[1] > 0 and len(v[2]) >= MIN_TOKENS_P1}
smart = set(sorted(elig, key=lambda w: -elig[w])[:max(20, int(len(elig) * TOP_FRAC))])

tape = defaultdict(list)
for r in rows:
    tape[r["token_address"]].append((int(r["ts"]), float(r["px"])))

sig, seen = [], set()
for r in rows:
    if r["ts"] < cut or r["side"] != "BUY" or r["trader"] not in smart:
        continue
    k = (r["trader"], r["token_address"])
    if k in seen:
        continue
    seen.add(k)
    sig.append((r["token_address"], int(r["ts"])))

res = []
for tok, ts in sig:
    after = [x for x in tape[tok] if x[0] > ts]
    if not after:
        continue
    ent = after[0][1]
    if ent <= 0:
        continue
    w = [x for x in after if x[0] <= after[0][0] + HOLD_H * 3600]
    if not w:
        continue
    res.append((w[-1][1] / ent, tok, ts, ent, w[-1][1]))
res.sort()
mult = [x[0] for x in res]
n = len(mult)
print(f"{n} lignes · detention {HOLD_H} h\n")
print("distribution des multiples")
for q in (1, 5, 10, 25, 50, 75, 90, 95, 99):
    print(f"  {q:>2}e centile : x{mult[int(n*q/100)]:.3f}")
print(f"  maximum     : x{mult[-1]:,.0f}")

print("\nmoyenne selon le plafond applique a la queue")
for cap in (None, 100.0, 10.0, 5.0, 3.0):
    v = [min(x, cap) if cap else x for x in mult]
    print(f"  {('sans plafond' if not cap else 'plafonne a x%g' % cap):<18} {statistics.mean(a*(1-FEE)-1 for a in v):>+9.1%}")
print(f"  {'mediane':<18} {statistics.median(mult)*(1-FEE)-1:>+9.1%}")

print(f"\npart des lignes au-dessus de x10 : {sum(1 for x in mult if x > 10)/n:.2%} "
      f"({sum(1 for x in mult if x > 10)} lignes)")
print("\nles 5 plus gros gains — prix d'entree et de sortie, a verifier a l'oeil")
for m, tok, ts, e, x in res[-5:]:
    print(f"  x{m:>12,.0f}  {tok[:12]}  entree {e:.3e} -> sortie {x:.3e}")
