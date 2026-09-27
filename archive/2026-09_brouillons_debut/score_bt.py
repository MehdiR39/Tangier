"""Same replay, but entering only what the model actually flagged, point in time.

A token becomes buyable at the first instant a score of >= threshold was WRITTEN for it
(token_scores.ts), never earlier: the engine could not have known before it computed it.
"""
import random, statistics, sys
sys.path.insert(0, "/app")
sys.path.insert(0, "/app/results")
from intel.context import IntelContext
import live_bt as L

ctx = IntelContext.build()
rows = ctx.db.query("SELECT token_address, ts, price_usd, volume_24h FROM token_snapshots "
                    "WHERE chain_id=? AND price_usd>0 ORDER BY token_address, ts", (ctx.chain_id,))
series = {}
for r in rows:
    series.setdefault(r["token_address"], []).append((int(r["ts"]), float(r["price_usd"]), float(r["volume_24h"] or 0.0) / 24.0))
series = {a: s for a, s in series.items() if len(s) >= 3}

sc = ctx.db.query("SELECT token_address, ts, moonshot, hard_filter_pass FROM token_scores "
                  "WHERE chain_id=? ORDER BY ts", (ctx.chain_id,))
print(f"{len({r['token_address'] for r in sc})} tokens scores · {len(series)} tokens avec des prix\n")


def flagged_at(threshold):
    """first ts at which each token carried a passing score of >= threshold"""
    out = {}
    for r in sc:
        if r["moonshot"] is not None and r["moonshot"] >= threshold and r["hard_filter_pass"] and r["token_address"] not in out:
            out[r["token_address"]] = int(r["ts"])
    return out


def run(gate, label, draws=100):
    """gate: None = anything passing the volume filter; else {token: first_ts_allowed}"""
    if gate is not None:
        sub = {a: s for a, s in series.items() if a in gate}
        sub = {a: [p for p in s if p[0] >= gate[a]] for a, s in sub.items()}
        sub = {a: s for a, s in sub.items() if len(s) >= 3}
    else:
        sub = series
    if len(sub) < 5:
        print(f"{label:<40} pas assez de tokens ({len(sub)})")
        return
    toks = sorted(sub)
    n = max(2, int(len(toks) * 0.7))
    fin, pl, st = [], [], []
    w = {"cible": 0, "stop": 0, "delai": 0}
    for d in range(draws):
        s2 = {a: sub[a] for a in random.Random(7 * 100_003 + d).sample(toks, min(n, len(toks)))}
        out = L.replay(s2, k=1.0, alpha=0.0, rng=random.Random(7 + d))
        if not out:
            continue
        f, p, why, stuck, _ln = out
        fin.append(f); pl.append(p); st.append(stuck)
        for kk in w: w[kk] += why[kk]
    if not fin:
        print(f"{label:<40} aucun achat possible")
        return
    fin.sort()
    tot = sum(w.values()) or 1
    print(f"{label:<40} {len(sub):>5} tokens · mediane {fin[len(fin)//2]:>6.0f}€ · pire {fin[0]:>5.0f}€ · meilleur {fin[-1]:>7.0f}€ · "
          f"gagnant {sum(1 for f in fin if f>400)/len(fin):>4.0%} · {statistics.mean(pl):>4.0f} lignes · coinces {statistics.mean(st):>4.1f} · "
          f"cible {w['cible']/tot:>3.0%}")


print(f"{'selection':<40} {'':>5}")
run(None, "au hasard (filtre de volume seul)")
for th in (50, 60, 70, 80):
    g = flagged_at(th)
    run(g, f"score moonshot >= {th}")
