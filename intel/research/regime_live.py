"""Can the market's temperature be read from the chain's own launch activity, ahead of time?

The same lagged test that was run on the scattered cohorts (rho +0.38..+0.53 on 16-26 usable
hours) and on four hours of paper book (nothing on 13 quarter-hours) -- now on the CONTINUOUS
series the engine records itself, with no collection of any kind:

  activity  : t1_observations -- every launch the watcher judged, bought or not, with its swap
              count in minute one. Per bucket: launches judged, share clearing the bar, median
              busyness. All of it is known at the end of the bucket.
  outcomes  : the paper book's entries decided in each bucket, marked from the chain (peak
              multiple reached within 6 h). Only knowable hours later, which is the point.

The question is whether activity in bucket q predicts outcomes in bucket q+1. The threshold is
the median of the older half and is read on the newer half. Run after at least 24 h of book;
before that the numbers are noise and the script says so.
"""
from __future__ import annotations

import asyncio
import re
import statistics
import sys
import time
from collections import defaultdict

ENGINE_DB = "/app/db/intel.sqlite"


def spearman(a: list[float], b: list[float]) -> float:
    ra = {v: i for i, v in enumerate(sorted(a))}
    rb = {v: i for i, v in enumerate(sorted(b))}
    xa, xb = [ra[v] for v in a], [rb[v] for v in b]
    n = len(a)
    ma, mb = sum(xa) / n, sum(xb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(xa, xb))
    den = (sum((x - ma) ** 2 for x in xa) * sum((y - mb) ** 2 for y in xb)) ** 0.5
    return num / den if den else 0.0


def main(bucket_min: int = 30) -> None:
    import sqlite3
    from intel.context import IntelContext
    from intel.research.paperbook import mark_from_path, paths_rpc, positions
    from intel.settings import IntelConfig, Settings

    s = Settings.load()
    cfg = IntelConfig.load(s.config_path)
    qdec = {a.lower(): int(m.get("decimals", 18)) for a, m in (cfg.quote_assets or {}).items()}
    con = sqlite3.connect(f"file:{ENGINE_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    obs = [dict(r) for r in con.execute(
        "SELECT ts, swaps_first_minute swaps, passed FROM t1_observations ORDER BY ts")]
    con.close()
    if not obs:
        print("aucune observation encore : le moteur vient de commencer a enregistrer")
        return
    span_h = (obs[-1]["ts"] - obs[0]["ts"]) / 3600
    print(f"{len(obs)} lancements juges sur {span_h:.1f} h · seau de {bucket_min} min")
    if span_h < 24:
        print("moins de 24 h de serie : ce qui suit est indicatif, pas un verdict")

    B = bucket_min * 60
    t0 = obs[0]["ts"]
    act: dict[int, dict] = defaultdict(lambda: {"n": 0, "passed": 0, "busy": []})
    for o in obs:
        q = (o["ts"] - t0) // B
        act[q]["n"] += 1
        act[q]["passed"] += int(o["passed"])
        act[q]["busy"].append(int(o["swaps"]))

    ctx = IntelContext.build()
    try:
        pos = positions()
        paths = asyncio.run(paths_rpc(ctx, pos))
    finally:
        asyncio.run(ctx.close())
    outc: dict[int, dict] = defaultdict(lambda: {"n": 0, "x15": 0, "x2": 0})
    for p in pos:
        m = mark_from_path(p, paths.get(p["exec_id"], []), qdec.get((p["quote"] or "").lower(), 18))
        pk = m.get("peak") or 0.0
        q = (int(p["ts"]) - t0) // B
        outc[q]["n"] += 1
        outc[q]["x15"] += pk >= 1.5
        outc[q]["x2"] += pk >= 2.0

    pairs = []
    for q in sorted(act):
        a, o = act[q], outc.get(q + 1)
        if not o or o["n"] < 3:
            continue
        pairs.append({"q": q, "n": a["n"], "share": a["passed"] / a["n"],
                      "busy": statistics.median(a["busy"]), "x15": o["x15"] / o["n"], "x2": o["x2"] / o["n"]})
    print(f"{len(pairs)} paires (seau q -> issues du seau q+1, >= 3 entrees)")
    if len(pairs) < 8:
        print("trop peu de paires pour une correlation qui veuille dire quelque chose")
        return
    for lab, key in (("lancements juges", "n"), ("part >= 27 swaps", "share"), ("busyness mediane", "busy")):
        print(f"  {lab:<20} -> x1.5 suivant {spearman([p[key] for p in pairs], [p['x15'] for p in pairs]):+.2f}"
              f" · -> x2 suivant {spearman([p[key] for p in pairs], [p['x2'] for p in pairs]):+.2f}")
    h = len(pairs) // 2
    train, test = pairs[:h], pairs[h:]
    for lab, key in (("part >= 27 swaps", "share"), ("busyness mediane", "busy")):
        thr = statistics.median([p[key] for p in train])
        hot = [p["x2"] for p in test if p[key] >= thr]
        cold = [p["x2"] for p in test if p[key] < thr]
        if hot and cold:
            print(f"  seuil {lab} = {thr:.3g} (train) · TEST chaud {statistics.mean(hot):.1%} ({len(hot)}) "
                  f"/ froid {statistics.mean(cold):.1%} ({len(cold)})")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
