"""Do the wallets that made money keep making money? The only question that matters here.

Following a wallet is only a strategy if skill PERSISTS. So wallets are ranked on the first half
of the period and judged on the second, which was not looked at while ranking. A wallet that is
merely lucky ranks high on the first half and lands at the population average on the second --
that is exactly what the test is built to expose.

PnL is realised + open, marked at the token's last observed price: a wallet still holding a bag
that never traded again has not made money, so the bag is worth nothing rather than its last print.
"""
import statistics, sys
from collections import defaultdict
sys.path.insert(0, "/app")
from intel.context import IntelContext

MIN_TOKENS_P1 = 3          # a verdict on one or two tokens is a coin toss, not a track record

ctx = IntelContext.build()
rows = ctx.db.query(
    "SELECT token_address, trader, ts, side, token_amount_float amt, usd_value usd, price_usd px "
    "FROM trades WHERE chain_id=? AND price_usd>0 AND trader IS NOT NULL ORDER BY ts", (ctx.chain_id,))
print(f"{len(rows):,} trades · {len({r['trader'] for r in rows}):,} portefeuilles · "
      f"{len({r['token_address'] for r in rows}):,} tokens")
cut = rows[len(rows) // 2]["ts"]
print(f"coupure : 1re moitie avant {cut}, 2e apres\n")

last_px = {}
for r in rows:
    last_px[r["token_address"]] = float(r["px"])


def pnl_by_wallet(sub):
    """-> {wallet: (pnl_usd, invested_usd, n_tokens)} marking leftover bags at zero"""
    pos = defaultdict(lambda: [0.0, 0.0, 0.0])   # units, cash_out, invested
    for r in sub:
        k = (r["trader"], r["token_address"])
        u = float(r["amt"] or 0.0)
        v = float(r["usd"] or 0.0)
        if r["side"] == "BUY":
            pos[k][0] += u; pos[k][2] += v; pos[k][1] -= v
        else:
            pos[k][0] -= u; pos[k][1] += v
    agg = defaultdict(lambda: [0.0, 0.0, set()])
    for (w, tok), (units, cash, inv) in pos.items():
        if inv <= 0:
            continue
        # a bag still held is worth the token's last price ONLY if it still traded; else zero
        val = max(0.0, units) * last_px.get(tok, 0.0)
        agg[w][0] += cash + val
        agg[w][1] += inv
        agg[w][2].add(tok)
    return {w: (p, i, len(t)) for w, (p, i, t) in agg.items() if i > 0}


A = [r for r in rows if r["ts"] < cut]
B = [r for r in rows if r["ts"] >= cut]
p1, p2 = pnl_by_wallet(A), pnl_by_wallet(B)
print(f"1re moitie : {len(p1):,} portefeuilles actifs · 2e moitie : {len(p2):,}")

elig = {w: v for w, v in p1.items() if v[2] >= MIN_TOKENS_P1}
print(f"portefeuilles jugeables (>= {MIN_TOKENS_P1} tokens en 1re moitie) : {len(elig):,}")
both = [w for w in elig if w in p2 and p2[w][1] > 0]
print(f"dont actifs aussi en 2e moitie : {len(both):,}\n")

if len(both) < 30:
    raise SystemExit("trop peu de portefeuilles presents sur les deux periodes pour conclure")

ranked = sorted(both, key=lambda w: -(p1[w][0] / p1[w][1]))
n = len(ranked)
print("=== rendement en 2e moitie, selon le classement etabli sur la 1re ===")
print(f"{'groupe (1re moitie)':<28} {'n':>5} {'rendement 1re':>15} {'rendement 2e':>15} {'% gagnants 2e':>15}")
qs = [("meilleur quart", ranked[:n // 4]), ("2e quart", ranked[n // 4:n // 2]),
      ("3e quart", ranked[n // 2:3 * n // 4]), ("dernier quart", ranked[3 * n // 4:])]
for lab, grp in qs:
    if not grp:
        continue
    r1 = statistics.median(p1[w][0] / p1[w][1] for w in grp)
    r2 = statistics.median(p2[w][0] / p2[w][1] for w in grp)
    win = sum(1 for w in grp if p2[w][0] > 0) / len(grp)
    print(f"{lab:<28} {len(grp):>5} {r1:>14.1%} {r2:>14.1%} {win:>14.0%}")

allr2 = statistics.median(p2[w][0] / p2[w][1] for w in both)
print(f"\n{'ensemble':<28} {len(both):>5} {'':>15} {allr2:>14.1%}")
top = ranked[:max(10, n // 20)]
print(f"\ntop 5 % (n={len(top)}) : rendement median en 2e moitie {statistics.median(p2[w][0]/p2[w][1] for w in top):+.1%} · "
      f"{sum(1 for w in top if p2[w][0] > 0)/len(top):.0%} gagnants")
