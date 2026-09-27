"""One line per token, which is both the honest sample size and how the book would really trade.

3 231 signals over 134 tokens are not 3 231 observations: several hundred smart wallets piling into
the same token produce hundreds of nearly identical returns, and the whole tail came from ONE token.
Counting per token collapses that. The control is the same measurement over every token bought by
anybody in the same window, so both sides carry the identical survivorship in this 280-token
universe and only the DIFFERENCE between them is being read.
"""
import statistics, sys
from collections import defaultdict
sys.path.insert(0, "/app")
from intel.context import IntelContext

MIN_TOKENS_P1, FEE = 3, 0.02

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
order = sorted(elig, key=lambda w: -elig[w])

tape = defaultdict(list)
for r in rows:
    tape[r["token_address"]].append((int(r["ts"]), float(r["px"])))
B = [r for r in rows if r["ts"] >= cut and r["side"] == "BUY"]


def ret(tok, ts, hold_h):
    after = [x for x in tape[tok] if x[0] > ts]
    if not after or after[0][1] <= 0:
        return None
    ent = after[0][1]
    w = [x for x in after if x[0] <= after[0][0] + hold_h * 3600]
    return (w[-1][1] / ent) if w else None


def first_buys(pred):
    """first moment each token is bought by a qualifying wallet -> one line per token"""
    out = {}
    for r in B:
        if r["token_address"] in out or not pred(r["trader"]):
            continue
        out[r["token_address"]] = int(r["ts"])
    return out


def line(label, sigs, hold_h=6):
    rs = [ret(t, ts, hold_h) for t, ts in sigs.items()]
    rs = sorted(x for x in rs if x is not None)
    if len(rs) < 15:
        print(f"{label:<26} {len(rs):>4} tokens — trop peu")
        return
    n = len(rs)
    cap3 = statistics.mean(min(x, 3.0) * (1 - FEE) - 1 for x in rs)
    cap10 = statistics.mean(min(x, 10.0) * (1 - FEE) - 1 for x in rs)
    raw = statistics.mean(x * (1 - FEE) - 1 for x in rs)
    print(f"{label:<26} {n:>4} {statistics.median(rs)*(1-FEE)-1:>+9.1%} {cap3:>+11.1%} {cap10:>+11.1%} "
          f"{raw:>+11.1%} {sum(1 for x in rs if x>1.5)/n:>9.0%} {rs[-1]:>9.1f}")


print(f"{len(elig):,} portefeuilles jugeables sur la 1re moitie\n")
print(f"{'qui on suit':<26} {'n':>4} {'mediane':>9} {'moy. x3 max':>11} {'moy. x10 max':>11} "
      f"{'moy. brute':>11} {'>x1,5':>9} {'max':>9}")
for lab, frac in (("top 1 %", 0.01), ("top 5 %", 0.05), ("top 25 %", 0.25), ("moitie haute", 0.50)):
    sel = set(order[:max(20, int(len(order) * frac))])
    line(lab, first_buys(lambda w: w in sel))
line("dernier quart", first_buys(lambda w: w in set(order[3 * len(order) // 4:])))
line("n'importe qui (temoin)", first_buys(lambda w: True))

print("\n=== duree de detention, en suivant le top 5 % ===")
sel = set(order[:max(20, int(len(order) * 0.05))])
fb = first_buys(lambda w: w in sel)
print(f"{'detention':<26} {'n':>4} {'mediane':>9} {'moy. x3 max':>11} {'moy. x10 max':>11} "
      f"{'moy. brute':>11} {'>x1,5':>9} {'max':>9}")
for h in (0.25, 1, 3, 6, 24, 72):
    line(f"{h} h", fb, hold_h=h)
