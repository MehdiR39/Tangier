"""Technical signals on tokens that already HAVE a market -- the population the user trades.

Everything measured so far was on launches minutes old. This is the other universe: tokens the
scanner discovered because they had liquidity and volume, observed every ~12 minutes by the live
engine (token_snapshots). Entering AT OR AFTER discovery is legitimate -- the scanner's criteria
are all observable at the time -- and it is entering BEFORE discovery, at the first trade, that
produced the +73% survivorship illusion earlier.

Signals, each one a standing result in the literature rather than a guess:
  - short-horizon MOMENTUM (Liu, Tsyvinski & Wu 2022: the strongest cross-sectional factor in
    crypto), here as the trailing 1 h / 6 h / 24 h return;
  - ATTENTION / volume-to-cap (high attention predicts a few days of continuation, then reversal);
  - BREAKOUT, price against its own trailing high;
  - MEAN REVERSION, drawdown from the trailing high;
  - liquidity-to-cap, the same depth idea as on launches.

Discipline unchanged: entry fills at the NEXT observation (12 min later -- what the engine could
actually do), 2% round trip, thresholds from the older half, numbers from the newer half.
"""
from __future__ import annotations

import random
import statistics
from collections import defaultdict
from typing import Any

FEE = 0.02
STEP_S = 720                # the engine's observation cadence
CLEANING: dict = {}         # tally of what clean_series removed on the last observations() call


def trimmed(xs: list[float], cut: float = 0.05) -> float:
    """mean after dropping the top and bottom ``cut`` share: what a mean is worth on this data"""
    if not xs:
        return 0.0
    s = sorted(xs)
    k = int(len(s) * cut)
    core = s[k: len(s) - k] or s
    return statistics.mean(core)
FEATURES = ["ret_1h", "ret_6h", "ret_24h", "vol_to_mc", "liq_to_mc", "breakout_24h",
            "drawdown_24h", "age_h", "log_mc"]


def _at(series: list[tuple[int, float, float, float, float]], t: int, max_stale: int = 3600):
    lo, hi, best = 0, len(series) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if series[m][0] <= t:
            best = series[m]
            lo = m + 1
        else:
            hi = m - 1
    return best if best and t - best[0] <= max_stale else None


def observations(ctx, *, min_history_h: float = 6.0, fwd_h: float = 6.0) -> list[dict[str, Any]]:
    """one row per (token, observation) with trailing features and forward outcomes"""
    rows = ctx.db.query(
        "SELECT token_address, ts, price_usd, market_cap, liquidity_usd, volume_24h "
        "FROM token_snapshots WHERE chain_id=? AND price_usd>0 ORDER BY token_address, ts",
        (ctx.chain_id,))
    created = {r["address"]: int(r["creation_ts"]) for r in ctx.db.query(
        "SELECT address, creation_ts FROM tokens WHERE chain_id=? AND creation_ts IS NOT NULL",
        (ctx.chain_id,))}
    ser: dict[str, list] = defaultdict(list)
    for r in rows:
        ser[r["token_address"]].append((int(r["ts"]), float(r["price_usd"]),
                                        float(r["market_cap"] or 0), float(r["liquidity_usd"] or 0),
                                        float(r["volume_24h"] or 0)))
    # clean every series BEFORE any feature is computed, and keep the tally: a corrupted print
    # (1e-20 followed by a normal price) turned the mean return into +6e17 % on the first pass
    from intel.research.clean import clean_series, summarize
    tallies = []
    cleaned: dict[str, list] = {}
    for tok, s in ser.items():
        kept, st = clean_series(s)
        tallies.append(st)
        if kept:
            cleaned[tok] = kept
    global CLEANING
    CLEANING = summarize(tallies)
    out = []
    for tok, s in cleaned.items():
        if len(s) < 8:
            continue
        t0 = s[0][0]
        for i in range(len(s) - 1):
            t, px, mc, liq, v24 = s[i]
            if t - t0 < min_history_h * 3600:
                continue
            nxt = s[i + 1]
            if nxt[0] - t > 2 * STEP_S:
                continue                              # no fill within the engine's cadence
            entry = nxt[1]
            horizon = nxt[0] + fwd_h * 3600
            fwd = [x for x in s[i + 1:] if x[0] <= horizon]
            if len(fwd) < 2 or s[-1][0] < horizon:
                continue                              # the window is not fully observed yet
            hist24 = [x for x in s[:i + 1] if x[0] >= t - 86400]
            p1 = _at(s, t - 3600)
            p6 = _at(s, t - 6 * 3600)
            p24 = _at(s, t - 24 * 3600)
            hi24 = max(x[1] for x in hist24) if hist24 else px
            row = {
                "token": tok, "ts": t,
                "ret_1h": (px / p1[1] - 1) if p1 and p1[1] > 0 else None,
                "ret_6h": (px / p6[1] - 1) if p6 and p6[1] > 0 else None,
                "ret_24h": (px / p24[1] - 1) if p24 and p24[1] > 0 else None,
                "vol_to_mc": (v24 / mc) if mc > 0 else None,
                "liq_to_mc": (liq / mc) if mc > 0 else None,
                "breakout_24h": (px / hi24) if hi24 > 0 else None,
                "drawdown_24h": (px / hi24 - 1) if hi24 > 0 else None,
                "age_h": ((t - created[tok]) / 3600) if tok in created else None,
                "log_mc": (__import__("math").log10(mc)) if mc > 0 else None,
                "fwd_max": max(x[1] for x in fwd) / entry,
                "fwd_end": fwd[-1][1] / entry,
                "fwd_liq_end": fwd[-1][3],
            }
            out.append(row)
    return out


def quantiles(rows: list[dict], feature: str, bins: int = 5) -> list[dict[str, Any]] | None:
    vals = sorted(((r[feature], r) for r in rows if r.get(feature) is not None), key=lambda x: x[0])
    if len(vals) < bins * 30:
        return None
    per = len(vals) // bins
    out = []
    for i in range(bins):
        lo, hi = i * per, (len(vals) if i == bins - 1 else (i + 1) * per)
        grp = [r for _v, r in vals[lo:hi]]
        net = [r["fwd_end"] * (1 - FEE) - 1 for r in grp]
        # trimmed, never raw: one surviving bad print would otherwise own the whole bin
        out.append({"bin": i + 1, "n": len(grp), "from": vals[lo][0], "to": vals[hi - 1][0],
                    "ev": trimmed(net), "med": statistics.median(net),
                    "win": sum(1 for x in net if x > 0) / len(net),
                    "x1_5": sum(1 for r in grp if r["fwd_max"] >= 1.5) / len(grp)})
    return out


def split_time(rows: list[dict], frac: float = 0.6):
    ts = sorted({r["ts"] for r in rows})
    cut = ts[int(len(ts) * frac)]
    return [r for r in rows if r["ts"] < cut], [r for r in rows if r["ts"] >= cut]


def book(rows: list[dict], pred, *, bankroll: float = 400.0, ticket: float = 20.0,
         max_open: int = 20) -> dict[str, Any]:
    """one position per token, chronological, finite cash; positions close at the horizon"""
    picks = sorted((r for r in rows if pred(r)), key=lambda r: r["ts"])
    cash, seen, closed, trades = bankroll, set(), [], []
    open_until: list[tuple[int, float]] = []
    for r in picks:
        # release positions whose horizon has passed
        still = []
        for t_end, val in open_until:
            if t_end <= r["ts"]:
                cash += val
            else:
                still.append((t_end, val))
        open_until = still
        if r["token"] in seen or cash < ticket or len(open_until) >= max_open:
            continue
        seen.add(r["token"])
        cash -= ticket
        val = ticket * r["fwd_end"] * (1 - FEE) if r["fwd_liq_end"] > 500 else 0.0
        open_until.append((r["ts"] + 6 * 3600, val))
        trades.append(val - ticket)
    cash += sum(v for _t, v in open_until)
    if not trades:
        return {"n": 0}
    top = sorted(trades, reverse=True)
    return {"n": len(trades), "final": cash,
            "final_sans_top3": bankroll + sum(trades) - sum(top[:3]),
            "win": sum(1 for x in trades if x > 0) / len(trades),
            "zero": sum(1 for x in trades if x <= -0.9 * ticket) / len(trades)}


def placebo(rows: list[dict], n_pick: int, draws: int = 30) -> list[float]:
    toks = sorted({r["token"] for r in rows})
    out = []
    for d in range(draws):
        keep = set(random.Random(d).sample(toks, min(n_pick, len(toks))))
        res = book(rows, lambda r, k=keep: r["token"] in k)
        if res.get("n"):
            out.append(res["final"])
    return sorted(out)
