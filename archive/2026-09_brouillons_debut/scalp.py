"""Buy the newest tokens at launch, sell 10-15 minutes later. Does that bet pay?

Different bet from the one measured so far, and it needs per-trade prices: a 10-minute hold is a
single observation in token_snapshots, so that table cannot answer it. This reads `trades`.

Three things decide it and all three are swept rather than assumed:
  - the entry DELAY. The engine cannot buy at the first trade; it needs to see the pool, check the
    contract and sign. Fastest measured path is ~70 s, so 0 min is a physical impossibility shown
    only as the ceiling.
  - the HOLD.
  - the FEE. 1% a leg is the figure used so far; at launch the book is thin and 3-5% is likelier,
    so the table shows what the edge survives.
"""
import statistics, sys
sys.path.insert(0, "/app")
from intel.context import IntelContext

ctx = IntelContext.build()
cols = [r["name"] for r in ctx.db.query("PRAGMA table_info(trades)")]
print("colonnes trades :", ", ".join(cols))
pxcol = next((c for c in ("price_usd", "price_quote", "price") if c in cols), None)
if pxcol is None:
    raise SystemExit("pas de colonne de prix dans trades")
amt = next((c for c in ("usd_value", "amount_usd", "quote_amount", "value_usd") if c in cols), None)
print(f"prix = {pxcol} · montant = {amt or 'aucun'}\n")

rows = ctx.db.query(
    f"SELECT token_address, ts, {pxcol} px{', ' + amt + ' amt' if amt else ''} FROM trades "
    f"WHERE chain_id=? AND {pxcol} > 0 ORDER BY token_address, ts", (ctx.chain_id,))
T = {}
for r in rows:
    T.setdefault(r["token_address"], []).append((int(r["ts"]), float(r["px"]), float(r["amt"] or 0.0) if amt else 0.0))
T = {a: s for a, s in T.items() if len(s) >= 5}
created = {r["address"]: int(r["creation_ts"]) for r in ctx.db.query(
    "SELECT address, creation_ts FROM tokens WHERE chain_id=? AND creation_ts IS NOT NULL", (ctx.chain_id,))}
before = len(T)
T = {a: s for a, s in T.items() if a in created and s[0][0] - created[a] <= 600}
print(f"{before} tokens avec des trades · {len(T)} dont on a vraiment capture le lancement (1er trade < 10 min apres la creation)")
print(f"{len(T)} tokens avec au moins 5 trades\n")


def px_at_or_after(s, t):
    for ts, p, _a in s:
        if ts >= t:
            return ts, p
    return None


def px_at_or_before(s, t, not_before):
    best = None
    for ts, p, _a in s:
        if ts > t:
            break
        if ts >= not_before:
            best = (ts, p)
    return best


def run(delay_min, hold_min, fee):
    rs, dead = [], 0
    for a, s in T.items():
        t0 = s[0][0]
        e = px_at_or_after(s, t0 + delay_min * 60)
        if not e:
            continue
        x = px_at_or_before(s, e[0] + hold_min * 60, e[0])
        if not x or x[0] == e[0]:
            # nobody traded during the whole holding window: we could not have sold
            dead += 1
            continue
        rs.append(x[1] / e[1])
    if len(rs) < 20:
        return None
    net = [r * (1 - fee) ** 2 - 1 for r in rs]
    return {"n": len(rs), "dead": dead, "median": statistics.median(rs),
            "ev": statistics.mean(net), "win": sum(1 for v in net if v > 0) / len(net),
            "p90": sorted(rs)[int(len(rs) * 0.9)]}


for fee in (0.01, 0.03, 0.05):
    print(f"===== frais {fee*100:.0f} % par jambe ({fee*200:.0f} % aller-retour) =====")
    print(f"{'entree':>9} " + " ".join(f"{str(h)+' min':>14}" for h in (5, 10, 15, 30)))
    for d in (0, 1, 2, 5):
        cells = []
        for h in (5, 10, 15, 30):
            r = run(d, h, fee)
            cells.append("      -       " if not r else f"{r['ev']:>+8.1%} {r['win']:>4.0%}")
        lab = "au 1er trade" if d == 0 else f"+{d} min"
        print(f"{lab:>9} " + " ".join(f"{c:>14}" for c in cells))
    print()

r = run(2, 15, 0.03)
if r:
    print(f"reference (+2 min, 15 min, 3 %) : {r['n']} tokens · mediane x{r['median']:.2f} · "
          f"9e decile x{r['p90']:.2f} · {r['dead']} invendables")
