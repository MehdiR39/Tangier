"""Every strategy question, asked once, on launches drawn without knowing what became of them.

Same three honesty rules throughout, each one earned by a mistake made today:
  - LIVENESS: a pool is only bought if it had already traded by the decision instant. Entering at
    "the first trade after +2 min" on a pool whose first trade came at +30 min is hindsight.
  - THE BOOK: entry fills at the NEXT trade's price, never the last print, because a print is
    somebody else's fill and we pay the other side.
  - UNSELLABLE IS ZERO: a bag with no trade after entry is worth nothing, not its last price.
Returns are sqrtPriceX96 ratios, so decimals never enter and no pool is dropped for being
unreadable.
"""
import sqlite3, statistics, sys

BPM = 600          # blocks per minute at ~0.1 s
FEE = 0.02         # round trip
DB = "/app/data/unbiased.sqlite"

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
pools = {r["pair_id"]: dict(r) for r in con.execute("SELECT * FROM pool")}
tape = {}
for r in con.execute("SELECT pair_id, block, sqrt FROM swap ORDER BY pair_id, block"):
    x = int(r["sqrt"]) / (1 << 96)
    p = x * x
    if not pools[r["pair_id"]]["is_c0"]:
        p = 1.0 / p if p else 0.0
    if p > 0:
        tape.setdefault(r["pair_id"], []).append((r["block"], p))

n_all = len(pools)
live = {k: v for k, v in tape.items() if len(v) >= 2}
print(f"{n_all} lancements tires au hasard · {len(live)} ont echange au moins deux fois ({len(live)/n_all:.0%})")
ns = sorted(len(v) for v in live.values())
print(f"trades en 24 h chez les vivants : mediane {ns[len(ns)//2]} · p90 {ns[9*len(ns)//10]} · max {ns[-1]}\n")


def run(pid, delay_min, *, target=None, stop=None, hold_h=None, need=1):
    t = tape.get(pid)
    if not t or len(t) < 2:
        return None
    b0 = pools[pid]["b0"]
    deadline = b0 + delay_min * BPM
    seen = [x for x in t if x[0] <= deadline]
    if len(seen) < need:
        return None                                  # looks dead at the decision instant
    after = [x for x in t if x[0] > deadline]
    if not after:
        return 0.0                                   # bought, then nobody ever traded again
    ent_b, ent_p = after[0]
    rest = [x for x in t if x[0] > ent_b]
    if not rest:
        return 0.0
    horizon = ent_b + (hold_h * 60 * BPM if hold_h else 10 ** 12)
    last = None
    for b, p in rest:
        if b > horizon:
            break
        r = p / ent_p
        last = r
        if target and r >= target:
            return target
        if stop and r <= 1 - stop:
            return r
    return last if last is not None else 0.0


def stat(rs):
    rs = sorted(x for x in rs if x is not None)
    if len(rs) < 15:
        return None
    n = len(rs)
    return {"n": n, "med": statistics.median(rs) * (1 - FEE) - 1,
            "ev3": statistics.mean(min(x, 3.0) * (1 - FEE) - 1 for x in rs),
            "ev": statistics.mean(x * (1 - FEE) - 1 for x in rs),
            "win": sum(1 for x in rs if x * (1 - FEE) > 1) / n,
            "dead": sum(1 for x in rs if x <= 0.10) / n}


def table(title, rowlab, rows_):
    print(f"=== {title} ===")
    print(f"{rowlab:<20} {'n':>5} {'mediane':>9} {'moy. x3 max':>12} {'moy. brute':>12} {'gagnantes':>10} {'a zero':>8}")
    for lab, rs in rows_:
        s = stat(rs)
        if not s:
            print(f"{lab:<20} {'—':>5}")
            continue
        print(f"{lab:<20} {s['n']:>5} {s['med']:>+8.1%} {s['ev3']:>+11.1%} {s['ev']:>+11.1%} "
              f"{s['win']:>9.0%} {s['dead']:>7.0%}")
    print()


ids = list(live)
table("ACHETER TOT, VENDRE VITE (detention fixe, entree a +2 min)", "detention",
      [(f"{h*60:.0f} min" if h < 1 else f"{h:g} h",
        [run(p, 2, hold_h=h) for p in ids]) for h in (0.25, 0.5, 1, 3, 6, 12, 24)])

table("QUAND ENTRER (detention 6 h)", "entree",
      [(f"+{d} min", [run(p, d, hold_h=6) for p in ids]) for d in (1, 2, 5, 15, 30, 60, 180)])

table("VENDRE SUR OBJECTIF (entree +2 min, delai 24 h)", "objectif",
      [(f"x{t:g}", [run(p, 2, target=t, hold_h=24) for p in ids]) for t in (1.2, 1.5, 2, 3, 5, 10)])

table("AJOUTER UN STOP (entree +2 min, objectif x1,5, delai 24 h)", "stop",
      [((f"-{s*100:.0f} %" if s else "aucun"),
        [run(p, 2, target=1.5, stop=s, hold_h=24) for p in ids]) for s in (0.2, 0.3, 0.5, 0.75, None)])

table("EXIGER DE L'ACTIVITE AVANT D'ACHETER (entree +5 min, 6 h)", "trades vus",
      [(f">= {k}", [run(p, 5, hold_h=6, need=k) for p in ids]) for k in (1, 3, 5, 10, 25)])

rs = sorted(x for x in (run(p, 2, hold_h=6) for p in ids) if x is not None)
if rs:
    n = len(rs)
    print("=== distribution de reference (entree +2 min, sortie 6 h) ===")
    for q in (5, 10, 25, 50, 75, 90, 95, 99):
        print(f"  {q:>2}e centile : x{rs[int(n*q/100)]:.3f}")
    print(f"  maximum     : x{rs[-1]:,.1f}")
