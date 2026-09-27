"""The launch scalp, without the two free lunches left in the first pass.

1. LIVENESS. Entering "at +2 min" only counts if the pool had ALREADY traded by +2 min. The first
   pass entered at the first trade at or after the deadline, so a pool whose first trade came at
   +30 min was still bought -- knowing it would eventually trade. That is hindsight: at +2 min the
   engine sees a pool with zero trades and has no reason to buy it.
2. THE BOOK. A swap price is the price at which SOMEBODY ELSE traded. Buying means paying the ask,
   not the last print. Modelled by entering at the NEXT trade's price rather than the one observed
   at the decision instant, which is the conservative reading of the same tape.

Both corrections remove return, and the point is to see what survives them.
"""
import json, statistics, sys

BPM = 600
d = json.load(open("/app/data/launch_sample.json"))
ok = {k: v for k, v in d.items() if v["swaps"] is not None}
live = {k: v for k, v in ok.items() if v["swaps"]}


def prices(v):
    out = []
    for b, s in v["swaps"]:
        x = int(s) / (1 << 96)
        p = x * x
        p = p if v["is_c0"] else (1.0 / p if p else 0.0)
        if p > 0:
            out.append((b, p))
    return out


def scalp(v, delay_min, hold_min, *, need_trades, pay_next):
    sw = prices(v)
    if len(sw) < 2:
        return None
    deadline = v["b0"] + delay_min * BPM
    seen = [x for x in sw if x[0] <= deadline]
    if len(seen) < need_trades:
        return None                       # at the decision instant this pool looks dead: no buy
    after = [x for x in sw if x[0] > deadline]
    if not after:
        return 0.0                        # we bought and nobody ever traded again
    ent = after[0] if (pay_next or not seen) else seen[-1]
    rest = [x for x in sw if x[0] > ent[0]]
    if not rest:
        return 0.0
    b_out = ent[0] + hold_min * BPM
    within = [x for x in rest if x[0] <= b_out]
    px = within[-1][1] if within else rest[0][1]
    return px / ent[1]


def table(need_trades, pay_next, fee):
    print(f"  {'entree':>10} " + " ".join(f"{str(h)+' min':>17}" for h in (5, 10, 15, 30)))
    for dm in (1, 2, 5, 10):
        cells = []
        for hm in (5, 10, 15, 30):
            rs = [scalp(v, dm, hm, need_trades=need_trades, pay_next=pay_next) for v in live.values()]
            rs = [r for r in rs if r is not None]
            if len(rs) < 20:
                cells.append("         -       ")
                continue
            net = [r * (1 - fee) ** 2 - 1 for r in rs]
            cells.append(f"{statistics.mean(net):>+8.1%} med x{statistics.median(rs):.2f} ({len(rs)})")
        print(f"  {'+'+str(dm)+' min':>10} " + " ".join(f"{c:>17}" for c in cells))


for fee in (0.01, 0.03):
    print(f"########## frais {fee*100:.0f} % par jambe ##########")
    print("\n= tel que teste d'abord (on entre meme si le pool n'a jamais echange) =")
    table(0, False, fee)
    print("\n= correction 1 : il faut au moins 1 trade AVANT d'acheter =")
    table(1, False, fee)
    print("\n= correction 2 : + on paie le prix du trade suivant, pas le dernier vu =")
    table(1, True, fee)
    print("\n= exigence plus realiste : au moins 3 trades avant d'acheter =")
    table(3, True, fee)
    print()

rs = [scalp(v, 2, 15, need_trades=1, pay_next=True) for v in live.values()]
rs = sorted(r for r in rs if r is not None)
if rs:
    print(f"reference corrigee (+2 min, 15 min, >=1 trade, prix suivant) · {len(rs)} lignes")
    print(f"  mediane x{statistics.median(rs):.2f} · moyenne x{statistics.mean(rs):.2f} · 9e decile x{rs[int(len(rs)*0.9)]:.2f}")
    for lab, f in (("perte totale", lambda r: r <= 0.10), ("perdantes", lambda r: r < 1.0),
                   ("au moins x1,5", lambda r: r >= 1.5), ("au moins x3", lambda r: r >= 3.0)):
        n = sum(1 for r in rs if f(r))
        print(f"  {lab:<16} {n:>4} ({n/len(rs):>4.0%})")
