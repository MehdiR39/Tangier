import sys, statistics
sys.path.insert(0, "/app")
from intel.context import IntelContext
ctx = IntelContext.build()
q = ctx.db.query
n = q("SELECT COUNT(*) c FROM history_series WHERE chain_id=?", (ctx.chain_id,))[0]["c"]
print(f"points de serie : {n:,}")
rows = q("SELECT token_address, COUNT(*) n, MIN(ts) a, MAX(ts) b FROM history_series WHERE chain_id=? GROUP BY token_address", (ctx.chain_id,))
spans = sorted((r["b"] - r["a"]) / 3600 for r in rows)
pts = sorted(r["n"] for r in rows)
print(f"tokens : {len(rows)}")
print(f"duree couverte par token (heures) : p10 {spans[len(spans)//10]:.1f} · mediane {spans[len(spans)//2]:.1f} · p90 {spans[9*len(spans)//10]:.1f} · max {spans[-1]:.1f}")
print(f"points par token : p10 {pts[len(pts)//10]} · mediane {pts[len(pts)//2]} · p90 {pts[9*len(pts)//10]}")
short = sum(1 for s in spans if s < 3.0)
print(f"tokens couverts moins de 3 h (= la duree de detention) : {short} / {len(rows)}  ({short/len(rows):.0%})")
