"""What a launch scalp actually returns, on pools drawn at random rather than pre-selected.

Returns are ratios of two sqrtPriceX96 readings of the same pool, so token decimals cancel and no
pool is dropped for being unreadable. Every sampled pool is counted, including the ones that never
trade at all -- those are the population the earlier +277% quietly excluded.

A position that finds no trade before the horizon is NOT quietly dropped: it is either sold at the
first later trade or, if none exists inside the window, marked at zero, because an unsellable bag
is worth nothing rather than its last printed price.
"""
import json, statistics, sys

BPM = 600           # blocks per minute at ~0.1 s
WINDOW = 27_000
d = json.load(open("/app/data/launch_sample.json"))
ok = {k: v for k, v in d.items() if v["swaps"] is not None}
empty = {k: v for k, v in ok.items() if not v["swaps"]}
live = {k: v for k, v in ok.items() if v["swaps"]}
print(f"{len(ok)} lancements tires au hasard")
print(f"  {len(empty):>4} n'ont AUCUN trade en 45 min   ({len(empty)/len(ok):>4.0%})")
print(f"  {len(live):>4} s'echangent                    ({len(live)/len(ok):>4.0%})")
ns = sorted(len(v["swaps"]) for v in live.values())
print(f"  trades en 45 min sur ceux qui vivent : mediane {ns[len(ns)//2]} · p90 {ns[9*len(ns)//10]} · max {ns[-1]}\n")


def price(v, s):
    x = int(s) / (1 << 96)
    p = x * x
    return p if v["is_c0"] else (1.0 / p if p else 0.0)


def scalp(v, delay_min, hold_min):
    """-> multiple, or None if we never got in"""
    sw = [(b, price(v, s)) for b, s in v["swaps"]]
    sw = [(b, p) for b, p in sw if p > 0]
    if len(sw) < 2:
        return None
    b_in = v["b0"] + delay_min * BPM
    ent = next(((b, p) for b, p in sw if b >= b_in), None)
    if ent is None:
        return None
    b_out = ent[0] + hold_min * BPM
    later = [(b, p) for b, p in sw if b > ent[0]]
    if not later:
        return 0.0                       # nobody ever traded again: the bag is unsellable
    at_or_before = [(b, p) for b, p in later if b <= b_out]
    if at_or_before:
        return at_or_before[-1][1] / ent[1]
    return later[0][1] / ent[1]          # first trade after the horizon: we get out late


for fee in (0.01, 0.03, 0.05):
    print(f"===== frais {fee*100:.0f} % par jambe · esperance par ligne (et % de lignes gagnantes) =====")
    print(f"{'entree':>12} " + " ".join(f"{str(h)+' min':>16}" for h in (5, 10, 15, 30)))
    for dm in (1, 2, 5, 10):
        cells = []
        for hm in (5, 10, 15, 30):
            rs = [scalp(v, dm, hm) for v in live.values()]
            rs = [r for r in rs if r is not None]
            if len(rs) < 20:
                cells.append("        -       ")
                continue
            net = [r * (1 - fee) ** 2 - 1 for r in rs]
            cells.append(f"{statistics.mean(net):>+8.1%} {sum(1 for x in net if x>0)/len(net):>4.0%} ({len(rs)})")
        print(f"{'+'+str(dm)+' min':>12} " + " ".join(f"{c:>16}" for c in cells))
    print()

rs = [scalp(v, 2, 15) for v in live.values()]
rs = [r for r in rs if r is not None]
rs.sort()
if rs:
    print(f"reference (+2 min, sortie 15 min) sur {len(rs)} lignes :")
    print(f"  mediane x{statistics.median(rs):.2f} · moyenne x{statistics.mean(rs):.2f} · "
          f"9e decile x{rs[int(len(rs)*0.9)]:.2f} · pire x{rs[0]:.3f}")
    for lab, f in (("perte totale (<=-90%)", lambda r: r <= 0.10), ("perdantes", lambda r: r < 1.0),
                   ("gagnantes", lambda r: r >= 1.0), ("au moins x1,5", lambda r: r >= 1.5),
                   ("au moins x3", lambda r: r >= 3.0)):
        n = sum(1 for r in rs if f(r))
        print(f"  {lab:<22} {n:>4} ({n/len(rs):>4.0%})")
