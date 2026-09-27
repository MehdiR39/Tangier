"""Following the skilled wallets: does copying them pay, entering AFTER them?

The persistence test says these wallets are good. It does not say we can ride them: we see their
buy only once it is on chain, and we necessarily fill behind them. So entry here is the price of
the NEXT trade after theirs, never their own price, and every delay is swept.

Wallets are selected on the FIRST half only. Everything measured happens in the second half, so
no wallet was chosen using a trade this test then scores.
"""
import statistics, sys
from collections import defaultdict
sys.path.insert(0, "/app")
from intel.context import IntelContext

MIN_TOKENS_P1, TOP_FRAC, FEE = 3, 0.05, 0.02

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
ranked = sorted(elig, key=lambda w: -elig[w])
smart = set(ranked[:max(20, int(len(ranked) * TOP_FRAC))])
print(f"{len(elig):,} portefeuilles jugeables · top {TOP_FRAC:.0%} retenu = {len(smart):,} portefeuilles")

tape = defaultdict(list)
for r in rows:
    tape[r["token_address"]].append((int(r["ts"]), float(r["px"])))

B = [r for r in rows if r["ts"] >= cut]
signals, seen = [], set()
for r in B:
    if r["side"] != "BUY" or r["trader"] not in smart:
        continue
    k = (r["trader"], r["token_address"])
    if k in seen:
        continue
    seen.add(k)
    signals.append((r["token_address"], int(r["ts"])))
print(f"{len(signals):,} signaux d'achat en 2e moitie ({len({s[0] for s in signals})} tokens distincts)")
span_h = (rows[-1]["ts"] - cut) / 3600
print(f"soit {len(signals)/span_h:.1f} signaux par heure sur {span_h:.0f} h\n")


def forward(tok, ts, hold_h):
    t = tape[tok]
    after = [x for x in t if x[0] > ts]
    if not after:
        return None
    ent = after[0][1]                      # we fill on the next trade, behind them
    if ent <= 0:
        return None
    horizon = after[0][0] + hold_h * 3600
    within = [x for x in after if x[0] <= horizon]
    if not within:
        return None
    return within[-1][1] / ent


def show(label, sigs):
    print(f"{label:<34} " + " ".join(f"{('%gh'%h):>16}" for h in (0.25, 1, 3, 6, 24)))
    cells = []
    for h in (0.25, 1, 3, 6, 24):
        rs = [forward(t, ts, h) for t, ts in sigs]
        rs = [x for x in rs if x is not None]
        if len(rs) < 20:
            cells.append("        -       ")
            continue
        net = [x * (1 - FEE) - 1 for x in rs]
        cells.append(f"{statistics.mean(net):>+7.1%} med{statistics.median(rs):>5.2f} ({len(rs)})")
    print(f"{'':<34} " + " ".join(f"{c:>16}" for c in cells))


print(f"=== rendement apres un achat, frais {FEE*100:.0f} % aller-retour ===")
show("suivre le top 5 %", signals)
allbuys, seen2 = [], set()
for r in B:
    if r["side"] != "BUY":
        continue
    k = (r["trader"], r["token_address"])
    if k in seen2:
        continue
    seen2.add(k)
    allbuys.append((r["token_address"], int(r["ts"])))
import random
random.Random(3).shuffle(allbuys)
show("n'importe quel acheteur (temoin)", allbuys[:4000])
