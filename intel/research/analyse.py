"""Descriptive analysis and threshold discovery. No threshold is chosen by hand anywhere here.

Each feature is cut into deciles of its OWN distribution and the hit rate of x2/x5/x10/x20/x50 is
read off inside each one. A feature that matters shows a monotone gradient across its deciles; a
feature that does not shows the base rate everywhere. That is the whole method, and it is the same
one that exposed the moonshot score as flat (36% / 35% / 31%) earlier.

Everything is split by TIME: the deciles and any rule are read on TRAIN (older cohorts) and the
numbers that get reported come from TEST (newer ones), never seen while choosing. A gradient that
appears on train and vanishes on test is noise, and saying so is the point.
"""
from __future__ import annotations

import json
import math
import statistics
from typing import Any

from intel.research import RESEARCH_DB
from intel.research.schema import connect

LEVELS = ["hit_x2", "hit_x3", "hit_x5", "hit_x10", "hit_x20", "hit_x50"]


def load(db_path: str = RESEARCH_DB, t_min: float | None = None) -> list[dict[str, Any]]:
    con = connect(db_path)
    q = ("SELECT s.*, l.max_ret_6h, l.ret_6h, l.dead, l.rug, "
         "l.hit_x2, l.hit_x3, l.hit_x5, l.hit_x10, l.hit_x20, l.hit_x50, "
         "l.t_to_x5, l.t_to_x10, l.dd_before_x5, l.dd_before_x10, "
         "l.sellable_x2, l.sellable_x3, l.sellable_x5, l.sellable_x10, l.sellable_x20, "
         "l.sellable_x50, l.exit_vol_6h, p.cohort, p.created_block, "
         # the backtest converts depth and exit volume to euros through the quote asset; without
         # this column that conversion silently returns None and the sellability check never fires
         "p.quote_address "
         "FROM rp_snap s JOIN rp_label l ON l.pair_id=s.pair_id AND l.t_min=s.t_min "
         "JOIN rp_pool p ON p.pair_id=s.pair_id")
    if t_min is not None:
        q += f" WHERE s.t_min={float(t_min)}"
    rows = []
    for r in con.execute(q):
        d = dict(r)
        try:
            d.update(json.loads(d.pop("feat_json") or "{}"))
        except (TypeError, ValueError):
            pass
        rows.append(d)
    con.close()
    return rows


def split_by_time(rows: list[dict], frac: float = 0.6) -> tuple[list[dict], list[dict]]:
    """older cohorts train, newer test -- split on the pool's creation block, never at random"""
    ordered = sorted(rows, key=lambda r: (r.get("created_block") or 0))
    blocks = sorted({r.get("created_block") or 0 for r in ordered})
    if len(blocks) < 4:
        return ordered, []
    cut = blocks[int(len(blocks) * frac)]
    return ([r for r in ordered if (r.get("created_block") or 0) < cut],
            [r for r in ordered if (r.get("created_block") or 0) >= cut])


def base_rates(rows: list[dict]) -> dict[str, float]:
    n = len(rows) or 1
    return {lv: sum(1 for r in rows if r.get(lv)) / n for lv in LEVELS}


def deciles(rows: list[dict], feature: str, *, levels: list[str] | None = None,
            bins: int = 5) -> list[dict[str, Any]] | None:
    """hit rate of each level inside each quantile bin of ``feature``"""
    levels = levels or ["hit_x2", "hit_x5", "hit_x10", "hit_x20"]
    vals = [(r[feature], r) for r in rows
            if r.get(feature) is not None and not isinstance(r[feature], str)
            and math.isfinite(float(r[feature]))]
    if len(vals) < bins * 15:
        return None
    vals.sort(key=lambda x: x[0])
    per = len(vals) // bins
    out = []
    for i in range(bins):
        lo = i * per
        hi = len(vals) if i == bins - 1 else (i + 1) * per
        grp = [r for _v, r in vals[lo:hi]]
        if not grp:
            continue
        row = {"bin": i + 1, "n": len(grp),
               "from": vals[lo][0], "to": vals[hi - 1][0],
               "med_ret_6h": statistics.median([r.get("max_ret_6h") or 0.0 for r in grp])}
        for lv in levels:
            row[lv] = sum(1 for r in grp if r.get(lv)) / len(grp)
        out.append(row)
    return out


def monotonicity(bins: list[dict], level: str) -> float:
    """+1 rises cleanly with the feature, -1 falls cleanly, ~0 no relation"""
    v = [b[level] for b in bins]
    if len(v) < 3:
        return 0.0
    ups = sum(1 for a, b in zip(v, v[1:]) if b > a)
    downs = sum(1 for a, b in zip(v, v[1:]) if b < a)
    return (ups - downs) / (len(v) - 1)


def rank_features(rows: list[dict], candidates: list[str], level: str = "hit_x5",
                  bins: int = 5) -> list[dict[str, Any]]:
    """features ordered by how far the top bin beats the bottom, with monotonicity alongside.

    Spread alone is easy to fake with one lucky bin, so both numbers are reported and a feature is
    only worth carrying to the test set when the gradient is monotone as well as wide.
    """
    out = []
    for f in candidates:
        b = deciles(rows, f, levels=[level], bins=bins)
        if not b:
            continue
        lo, hi = b[0][level], b[-1][level]
        out.append({"feature": f, "bottom": lo, "top": hi, "spread": hi - lo,
                    "mono": monotonicity(b, level), "n": sum(x["n"] for x in b)})
    out.sort(key=lambda d: -abs(d["spread"]))
    return out


FEATURES = [
    "trades_5m", "trades_total", "vol_5m", "vol_15m", "vol_accel", "trade_accel",
    "net_buy_pressure", "buy_share_trades", "liq_to_mc", "vol5_to_mc", "vol5_to_liq",
    "holder_velocity_5m", "holder_accel", "new_buyers_5m", "buyer_accel",
    "uniq_buyers", "uniq_sellers", "price_chg_5m", "price_chg_15m", "ret_since_first",
    "log_mcap", "top1", "top5", "top10", "top20", "deployer_pct", "holders",
]
