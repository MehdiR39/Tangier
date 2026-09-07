"""Historical backtest: rebuild past prices from on-chain Swap events, then replay the rules.

Why this exists: waiting for forward data is too slow for an asset class where a token lives
and dies in hours. Every Uniswap v4 Swap event carries ``sqrtPriceX96``, so the price of a
token is exactly recoverable at every trade since its pool was created. Validated on TUX
(2026-09-03): 13 917 swaps over 7 days rebuilt in 44 RPC calls, last price within 2.4 % of
DexScreener.

Approximations, stated plainly:
- prices are expressed in the QUOTE token (exact); USD conversion uses the quote's current
  price as a constant, which is fine for stable quotes and a few percent off for stock quotes;
- depth is the USD volume traded in the preceding hour, not a reserve figure: concentrated
  launchpad liquidity makes reserve-based depth overstate what can be traded by orders of magnitude;
- execution is assumed at the last traded price plus a configurable fee/slippage per leg.
"""
from __future__ import annotations

import bisect
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from intel.chain.constants import TOPIC_V4_SWAP
from intel.chain.erc20 import fetch_metadata
from intel.chain.uniswap_v4 import decode_swap, is_price_at_bound, token_price_in_quote, virtual_reserves
from intel.context import IntelContext
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# block -> timestamp (piecewise linear from a few anchors: block time is ~0.1 s and regular)
# --------------------------------------------------------------------------- #
async def block_time_model(ctx: IntelContext, b0: int, b1: int, anchors: int = 12) -> Callable[[int], int]:
    anchors = max(2, anchors)
    blocks = sorted({b0 + round(i * (b1 - b0) / (anchors - 1)) for i in range(anchors)})
    ts_map = await ctx.rpc.block_timestamps(blocks, max_gap=10 ** 9)
    known = sorted((b, t) for b, t in ts_map.items() if t)
    if len(known) < 2:
        raise RuntimeError("cannot anchor block timestamps")
    xs = [b for b, _ in known]
    ys = [t for _, t in known]

    def ts_of(block: int) -> int:
        i = bisect.bisect_left(xs, block)
        if i == 0:
            return ys[0] + int((block - xs[0]) * ctx.rpc.block_time_hint)
        if i >= len(xs):
            return ys[-1] + int((block - xs[-1]) * ctx.rpc.block_time_hint)
        x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
        return int(y0 + (block - x0) * (y1 - y0) / max(1, x1 - x0))

    return ts_of


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #
async def build_history(ctx: IntelContext, token: str, pool: dict[str, Any], *, bucket_seconds: int = 60, chunk: int = 150_000) -> dict[str, Any]:
    """Rebuild and store one token's price series from its pool's Swap events."""
    token = token.lower()
    pool_id = pool["pair_id"]
    quote = pool["quote_address"]
    from_block = int(pool["created_block"])
    t_start = time.time()
    meta_row = ctx.db.query_one("SELECT to_block, n_points FROM history_meta WHERE chain_id=? AND token_address=? AND pool_id=?", (ctx.chain_id, token, pool_id))
    dec_t = (await fetch_metadata(ctx.rpc, token)).get("decimals")
    # Native ETH is the zero address: no contract to call, so read decimals from the configured quote table first.
    dec_q = (ctx.config.quote_assets.get((quote or "").lower()) or {}).get("decimals")
    if dec_q is None and quote:
        dec_q = (await fetch_metadata(ctx.rpc, quote)).get("decimals")
    if dec_t is None or dec_q is None:
        return {"token": token, "error": "decimals unknown"}
    head = await ctx.rpc.block_number()
    start = int(meta_row["to_block"]) + 1 if meta_row and meta_row["to_block"] else from_block
    if start > head:
        return {"token": token, "points": meta_row["n_points"] if meta_row else 0, "cached": True}
    ts_of = await block_time_model(ctx, start, head)
    buckets: dict[int, tuple[int, float, float, float, int]] = {}
    n_clamped = 0
    n_swaps = 0
    token_is_c0 = bool(pool["token_is_currency0"])
    async for _a, _b, logs in ctx.rpc.iter_logs(address=ctx.pool_manager, topics=[TOPIC_V4_SWAP, pool_id], from_block=start, to_block=head, chunk=chunk):
        for lg in logs:
            try:
                ev = decode_swap(lg)
            except Exception:
                continue
            n_swaps += 1
            if is_price_at_bound(ev.sqrt_price_x96):
                n_clamped += 1
                continue  # pool pushed out of range: the clamp value is not a tradeable price
            px = token_price_in_quote(ev.sqrt_price_x96, token_is_c0, dec_t, dec_q)
            if px <= 0:
                continue
            r0, r1 = virtual_reserves(ev.liquidity, ev.sqrt_price_x96)
            liq_quote = (r1 if token_is_c0 else r0) / (10 ** dec_q)
            vol_quote = abs(ev.amount1 if token_is_c0 else ev.amount0) / (10 ** dec_q)
            ts = ts_of(ev.block_number)
            k = ts // bucket_seconds
            prev = buckets.get(k)
            buckets[k] = (ev.block_number, px, liq_quote, (prev[3] if prev else 0.0) + vol_quote, (prev[4] if prev else 0) + 1)
    rows = [{"chain_id": ctx.chain_id, "token_address": token, "ts": k * bucket_seconds, "price_quote": v[1], "liquidity_quote": v[2],
             "vol_quote": v[3], "n_trades": v[4], "block_number": v[0]} for k, v in sorted(buckets.items())]
    with ctx.db.transaction():
        if rows:
            ctx.db.insert_many("history_series", rows, ignore=True)
        first_ts = ctx.db.scalar("SELECT MIN(ts) FROM history_series WHERE chain_id=? AND token_address=?", (ctx.chain_id, token))
        last_ts = ctx.db.scalar("SELECT MAX(ts) FROM history_series WHERE chain_id=? AND token_address=?", (ctx.chain_id, token))
        n_points = ctx.db.scalar("SELECT COUNT(*) FROM history_series WHERE chain_id=? AND token_address=?", (ctx.chain_id, token), 0)
        ctx.db.upsert("history_meta", {
            "chain_id": ctx.chain_id, "token_address": token, "pool_id": pool_id, "quote_address": quote, "quote_symbol": pool.get("quote_symbol"),
            "token_decimals": dec_t, "quote_decimals": dec_q, "from_block": from_block, "to_block": head,
            "first_ts": first_ts, "last_ts": last_ts, "n_swaps": (meta_row["n_points"] if meta_row else 0) and None or n_swaps,
            "n_points": n_points, "built_ts": now_ts(), "error": None,
        }, ("chain_id", "token_address", "pool_id"))
    return {"token": token, "swaps": n_swaps, "clamped": n_clamped, "points": len(rows), "seconds": round(time.time() - t_start, 1)}


async def build_history_batch(ctx: IntelContext, pools: list[dict[str, Any]], *, bucket_seconds: int = 60,
                              batch: int = 50, chunk: int = 400_000, window_blocks: int | None = 1_800_000) -> dict[str, Any]:
    """Rebuild many tokens at once by asking for several pools in a single log query.

    ``eth_getLogs`` accepts a list of values in a topic position, meaning "any of these", so one
    request can carry fifty pools instead of one. Measured 2026-09-04 against this node: 2.5 s per
    pool one at a time, 0.004 s per pool grouped — the same work in a six-hundredth of the calls.
    Reading the chain in slices is simply how it is meant to be read.

    Pools are grouped by age so a batch does not drag a young pool across a range it never existed
    in, and each pool keeps its own decimals and orientation when its swaps are decoded.

    ``window_blocks`` stops each group a fixed distance after its oldest pool was created —
    1 800 000 blocks is about two days. These tokens trade for a median of six minutes and the
    strategy holds a position for at most three hours, so scanning forty-five days of silence to
    find a few minutes of activity is what was making the node refuse the queries. Pass None to
    scan to the chain head.
    """
    # Decimals are already known for most tokens: reading them from the database first turns
    # 3 600 RPC calls into one query, and the public node was refusing the calls anyway.
    known: dict[str, int] = {r["address"]: int(r["decimals"]) for r in ctx.db.query(
        "SELECT address, decimals FROM tokens WHERE chain_id=? AND decimals IS NOT NULL", (ctx.chain_id,))}
    for meta_row in ctx.db.query(
            "SELECT token_address, token_decimals, quote_address, quote_decimals FROM history_meta WHERE chain_id=?", (ctx.chain_id,)):
        if meta_row["token_decimals"] is not None:
            known.setdefault(meta_row["token_address"], int(meta_row["token_decimals"]))
        if meta_row["quote_address"] and meta_row["quote_decimals"] is not None:
            known.setdefault(meta_row["quote_address"], int(meta_row["quote_decimals"]))

    async def decimals_of(address: str) -> int | None:
        address = (address or "").lower()
        if not address:
            return None
        cfg = (ctx.config.quote_assets.get(address) or {}).get("decimals")
        if cfg is not None:
            return int(cfg)
        if address in known:
            return known[address]
        try:
            d = (await fetch_metadata(ctx.rpc, address)).get("decimals")
        except Exception as exc:  # noqa: BLE001
            log.debug("décimales illisibles pour %s: %s", address[:10], exc)
            return None
        if d is not None:
            known[address] = int(d)
        return int(d) if d is not None else None

    ctxs: dict[str, dict[str, Any]] = {}
    skipped = 0
    for p in pools:
        token = str(p["token_address"]).lower()
        quote = (p.get("quote_address") or "").lower()
        if p.get("created_block") is None:
            skipped += 1
            continue
        dec_q = await decimals_of(quote)
        dec_t = await decimals_of(token)
        if dec_t is None or dec_q is None:
            skipped += 1
            continue
        ctxs[str(p["pair_id"]).lower()] = {
            "token": token, "quote": quote, "dec_t": int(dec_t), "dec_q": int(dec_q),
            "is_c0": bool(p.get("token_is_currency0")), "from_block": int(p["created_block"]),
            "symbol": p.get("quote_symbol"), "buckets": {}, "swaps": 0,
        }
    if not ctxs:
        return {"pools": 0, "skipped": skipped, "swaps": 0, "seconds": 0.0}

    head = await ctx.rpc.block_number()
    t_start = time.time()
    ordered = sorted(ctxs.items(), key=lambda kv: kv[1]["from_block"])
    groups = [ordered[i: i + batch] for i in range(0, len(ordered), batch)]
    total_swaps = 0
    failed_groups = 0
    for gi, group in enumerate(groups):
        ids = [pid for pid, _ in group]
        start = min(c["from_block"] for _pid, c in group)
        stop = head if window_blocks is None else min(head, max(c["from_block"] for _pid, c in group) + window_blocks)
        try:
            ts_of = await block_time_model(ctx, start, stop)
            stream = ctx.rpc.iter_logs(address=ctx.pool_manager, topics=[TOPIC_V4_SWAP, ids],
                                       from_block=start, to_block=stop, chunk=chunk)
        except Exception as exc:  # noqa: BLE001
            # A public node refusing one heavy query must not discard the whole collection: the
            # pools of this group keep whatever they already had and the rest carries on.
            log.warning("lot %d/%d abandonné (%s) — la collecte continue", gi + 1, len(groups), str(exc)[:120])
            failed_groups += 1
            continue
        try:
            async for _a, _b, logs in stream:
                for lg in logs:
                    pid = str(lg["topics"][1]).lower()
                    c = ctxs.get(pid)
                    if c is None:
                        continue
                    try:
                        ev = decode_swap(lg)
                    except Exception:
                        continue
                    c["swaps"] += 1
                    total_swaps += 1
                    if is_price_at_bound(ev.sqrt_price_x96):
                        continue
                    px = token_price_in_quote(ev.sqrt_price_x96, c["is_c0"], c["dec_t"], c["dec_q"])
                    if px <= 0:
                        continue
                    r0, r1 = virtual_reserves(ev.liquidity, ev.sqrt_price_x96)
                    liq_quote = (r1 if c["is_c0"] else r0) / (10 ** c["dec_q"])
                    vol_quote = abs(ev.amount1 if c["is_c0"] else ev.amount0) / (10 ** c["dec_q"])
                    k = ts_of(ev.block_number) // bucket_seconds
                    prev = c["buckets"].get(k)
                    c["buckets"][k] = (ev.block_number, px, liq_quote,
                                       (prev[3] if prev else 0.0) + vol_quote, (prev[4] if prev else 0) + 1)
        except Exception as exc:  # noqa: BLE001
            log.warning("lot %d/%d interrompu (%s) — ce qui a été lu est conservé", gi + 1, len(groups), str(exc)[:120])
            failed_groups += 1
        for _pid, c in group:
            c["scanned_to"] = stop

    # One series per token, from its most heavily traded pool. history_series is keyed by token
    # and timestamp with no room for a pool, so writing every pool of a token mixed their prices:
    # VIRTUAL read 3.03e-4 from a near-empty pool and 0.75 from the real one on consecutive days,
    # a fabricated x2500 that then dominated every average computed from it.
    best: dict[str, str] = {}
    for pid, c in ctxs.items():
        cur = best.get(c["token"])
        if cur is None or c["swaps"] > ctxs[cur]["swaps"]:
            best[c["token"]] = pid
    dropped = len(ctxs) - len(best)
    ctxs = {pid: c for pid, c in ctxs.items() if best.get(c["token"]) == pid}

    built = 0
    with ctx.db.transaction():
        for c in ctxs.values():
            # remove anything a previous run wrote for this token from another pool
            ctx.db.execute("DELETE FROM history_series WHERE chain_id=? AND token_address=?", (ctx.chain_id, c["token"]))
            ctx.db.execute("DELETE FROM history_meta WHERE chain_id=? AND token_address=?", (ctx.chain_id, c["token"]))
        for pid, c in ctxs.items():
            rows = [{"chain_id": ctx.chain_id, "token_address": c["token"], "ts": k * bucket_seconds,
                     "price_quote": v[1], "liquidity_quote": v[2], "vol_quote": v[3], "n_trades": v[4],
                     "block_number": v[0]} for k, v in sorted(c["buckets"].items())]
            if rows:
                ctx.db.insert_many("history_series", rows, ignore=True)
                built += 1
            first_ts = ctx.db.scalar("SELECT MIN(ts) FROM history_series WHERE chain_id=? AND token_address=?", (ctx.chain_id, c["token"]))
            last_ts = ctx.db.scalar("SELECT MAX(ts) FROM history_series WHERE chain_id=? AND token_address=?", (ctx.chain_id, c["token"]))
            n_points = ctx.db.scalar("SELECT COUNT(*) FROM history_series WHERE chain_id=? AND token_address=?", (ctx.chain_id, c["token"]), 0)
            ctx.db.upsert("history_meta", {
                "chain_id": ctx.chain_id, "token_address": c["token"], "pool_id": pid, "quote_address": c["quote"],
                "quote_symbol": c["symbol"], "token_decimals": c["dec_t"], "quote_decimals": c["dec_q"],
                # to_block records what was actually scanned, not the chain head: a later run must
                # know the window really covered, or it would believe the series complete.
                "from_block": c["from_block"], "to_block": c.get("scanned_to", head),
                "first_ts": first_ts, "last_ts": last_ts,
                "n_swaps": c["swaps"], "n_points": n_points, "built_ts": now_ts(), "error": None,
            }, ("chain_id", "token_address", "pool_id"))
    return {"pools": len(ctxs), "with_data": built, "skipped": skipped, "swaps": total_swaps,
            "requests": len(groups), "failed_groups": failed_groups, "secondary_pools_dropped": dropped,
            "seconds": round(time.time() - t_start, 1)}


async def enumerate_launches(ctx: IntelContext, *, days: int, per_day: int, window_blocks: int = 30_000) -> list[dict[str, Any]]:
    """Sample pool launches straight from the chain, one cohort per past day.

    The engine's ``pairs`` table only holds pools it happened to resolve (mostly recent), so a
    multi-day backtest has to read ``Initialize`` events from the PoolManager itself. One
    window of ``window_blocks`` per day is enough for a cohort and costs a couple of RPC calls.
    """
    from intel.chain.constants import TOPIC_V4_INITIALIZE
    from intel.chain.uniswap_v4 import decode_initialize
    from intel.ingest.pools import store_pool_init

    head = await ctx.rpc.block_number()
    out: list[dict[str, Any]] = []
    seen_tokens: set[str] = set()
    for d in range(1, days + 1):
        target_ts = now_ts() - d * 86400
        try:
            start = await ctx.rpc.block_by_timestamp(target_ts, head=head)
        except Exception as exc:  # noqa: BLE001
            log.warning("cohort J-%d unreachable: %s", d, exc)
            continue
        end = min(head, start + window_blocks)
        cohort: list[dict[str, Any]] = []
        try:
            logs = await ctx.rpc.get_logs(address=ctx.pool_manager, topics=[TOPIC_V4_INITIALIZE], from_block=start, to_block=end)
        except Exception as exc:  # noqa: BLE001
            log.warning("cohort J-%d getLogs failed: %s", d, exc)
            continue
        ts_of = None
        for lg in logs:
            try:
                init = decode_initialize(lg)
            except Exception:
                continue
            q0, q1 = ctx.quote_asset(init.currency0), ctx.quote_asset(init.currency1)
            if bool(q0) == bool(q1):
                continue  # need exactly one side to be a known quote asset
            token = init.currency1 if q0 else init.currency0
            if ctx.is_system(token):
                continue
            if ts_of is None:
                ts_of = await block_time_model(ctx, start, end, anchors=4)
            info = store_pool_init(ctx, token, init, ts_of(init.block_number), "backtest_enumeration")
            cohort.append({"pair_id": info.pair_id, "token_address": token, "quote_address": info.quote_address,
                           "quote_symbol": (q0 or q1 or {}).get("symbol"), "created_block": init.block_number,
                           "created_ts": ts_of(init.block_number), "token_is_currency0": int(info.token_is_currency0), "cohort_day": d})
            if len(cohort) >= per_day * 3:
                break
        random.Random(d).shuffle(cohort)
        kept = []
        for c in cohort:
            if c["token_address"] in seen_tokens:
                continue  # one series per token, even when it launched several pools
            seen_tokens.add(c["token_address"])
            kept.append(c)
            if len(kept) >= per_day:
                break
        out.extend(kept)
        log.info("cohort J-%d: %d pools (blocs %d-%d, %d événements)", d, len(kept), start, end, len(logs))
    return out


def candidate_pools(ctx: IntelContext, *, min_age_hours: float, max_age_hours: float, limit: int, exclude_names: Iterable[str] = ("robinhood token",)) -> list[dict[str, Any]]:
    """Pools created in a past window, deepest first, excluding tokenised stocks."""
    now = now_ts()
    rows = ctx.db.query(
        "SELECT p.pair_id, p.token_address, p.quote_address, p.quote_symbol, p.created_block, p.created_ts, p.token_is_currency0, t.symbol, t.name "
        "FROM pairs p LEFT JOIN tokens t ON t.chain_id=p.chain_id AND t.address=p.token_address "
        "WHERE p.chain_id=? AND p.currency0 IS NOT NULL AND p.created_block IS NOT NULL AND p.created_ts IS NOT NULL "
        "AND p.created_ts<=? AND p.created_ts>=? ORDER BY p.created_ts DESC LIMIT ?",
        (ctx.chain_id, now - int(min_age_hours * 3600), now - int(max_age_hours * 3600), limit * 4),
    )
    out, seen = [], set()
    bad = [b.lower() for b in exclude_names]
    for r in rows:
        d = dict(r)
        if d["token_address"] in seen:
            continue
        if any(b in (d.get("name") or "").lower() for b in bad):
            continue
        seen.add(d["token_address"])
        out.append(d)
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- #
# replay
# --------------------------------------------------------------------------- #
@dataclass
class Rules:
    name: str
    moonbag: float | None = 3.0        # sell half at this multiple
    stop: float | None = None          # hard stop, fraction below entry
    trail: float | None = None         # trailing stop from peak, once armed
    timeout_h: float | None = 18.0     # free the line
    entry_min_vol_usd: float = 2_000.0   # USD actually traded in the preceding hour
    entry_max_age_h: float | None = None   # only buy tokens younger than this at entry
    fee: float = 0.01                  # proportional cost per leg (swap fee + slippage)
    gas_usd: float = 0.0               # flat chain cost per transaction; hurts small lines most
    # Below this depth nobody is on the other side: an exit cannot be executed, and a bag still
    # held at the end of the window is worth nothing rather than its last printed price.
    exit_min_vol_usd: float = 300.0


@dataclass
class Result:
    final: float
    played: int
    closed: list[float] = field(default_factory=list)
    # How many candidates the picker had to choose from at each buy. If this is ~1, every
    # eligible token gets bought and no selection rule can possibly differ from another.
    choices: list[int] = field(default_factory=list)
    min_equity: float = 0.0   # lowest mark-to-market value of the whole account along the way

    @property
    def avg_choices(self) -> float:
        return sum(self.choices) / len(self.choices) if self.choices else 0.0


def load_series(ctx: IntelContext, tokens: list[str], quote_usd: dict[str, float], *, depth_window_s: int = 3600) -> dict[str, list[tuple[int, float, float]]]:
    """(ts, price_usd, depth_usd) per token, using a constant quote price.

    ``depth_usd`` is the USD volume actually traded over the preceding hour, NOT the pool's
    virtual reserve. Launchpad liquidity is concentrated in a narrow band, so the reserve figure
    overstates depth by orders of magnitude: tokens holding $1 of real book were clearing a
    $20k filter. What was traded is the only honest answer to "could I have got in and out?".
    """
    out: dict[str, list[tuple[int, float, float]]] = {}
    meta = {r["token_address"]: dict(r) for r in ctx.db.query("SELECT token_address, quote_address FROM history_meta WHERE chain_id=?", (ctx.chain_id,))}
    for t in tokens:
        q = (meta.get(t) or {}).get("quote_address")
        qusd = quote_usd.get((q or "").lower(), 0.0)
        if not qusd:
            continue
        rows = ctx.db.query("SELECT ts, price_quote, vol_quote FROM history_series WHERE chain_id=? AND token_address=? ORDER BY ts", (ctx.chain_id, t))
        if not rows:
            continue
        pts = [(int(r["ts"]), float(r["price_quote"]) * qusd, float(r["vol_quote"] or 0) * qusd) for r in rows]
        series, lo, running = [], 0, 0.0
        for i, (ts, px, vol) in enumerate(pts):
            running += vol
            while pts[lo][0] <= ts - depth_window_s:
                running -= pts[lo][2]
                lo += 1
            series.append((ts, px, running))
        out[t] = series
    return out


MAX_STALENESS_S = 900


def _at(series: list[tuple[int, float, float]], t: int, max_staleness: int = MAX_STALENESS_S) -> tuple[float, float] | None:
    """Price and depth at ``t``, or None when the last trade is too old to act on.

    A series only holds minutes in which the token actually traded, so "the last known price" can
    be hours stale. Carrying it forward lets the replay buy at a price nobody was offering and
    sell into a jump it never risked: one sparse token (6 379 swaps, 48 observed minutes) alone
    turned 400 EUR into 28 616 EUR that way. No recent trade means no trade.
    """
    lo, hi = 0, len(series) - 1
    if not series or series[0][0] > t:
        return None
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if series[mid][0] <= t:
            lo = mid
        else:
            hi = mid - 1
    if t - series[lo][0] > max_staleness:
        return None
    return series[lo][1], series[lo][2]


Picker = Callable[[list[str], random.Random, int, dict[str, list[tuple[int, float, float]]]], str]


def _feature(series: dict[str, list[tuple[int, float, float]]], token: str, t: int, kind: str) -> float:
    """Point-in-time feature of a candidate at time ``t``. Uses only data published before ``t``."""
    s = series[token]
    cur = _at(s, t)
    if cur is None:
        return float("-inf")
    px, liq = cur
    if kind == "deep":
        return liq
    if kind == "thin":
        return -liq
    if kind == "young":
        return -(t - s[0][0])
    first = s[0][1]
    if kind == "momentum":
        return px / first if first > 0 else 0.0
    if kind == "flat":  # not yet pumped: closest to its launch price
        return -abs((px / first) - 1.0) if first > 0 else float("-inf")
    if kind == "active":  # number of price updates so far, a proxy for trade count
        n = 0
        for ts, _p, _l in s:
            if ts > t:
                break
            n += 1
        return float(n)
    if kind == "liq_growth":
        base = next((l for ts, _p, l in s if ts >= s[0][0] + 1800), s[0][2]) or 0.0
        return liq / base if base > 0 else 0.0
    raise ValueError(kind)


def make_picker(kind: str) -> Picker:
    """Selection rule. ``random`` is the benchmark every other rule has to beat."""
    if kind == "random":
        return lambda pool, rng, t, series: rng.choice(pool)

    def pick(pool: list[str], rng: random.Random, t: int, series: dict[str, list[tuple[int, float, float]]]) -> str:
        best, best_v = pool[0], float("-inf")
        for a in pool:
            v = _feature(series, a, t, kind)
            if v > best_v:
                best, best_v = a, v
        return best

    return pick


def replay(series: dict[str, list[tuple[int, float, float]]], rules: Rules, *, capital: float, line: float, picker: Picker, rng: random.Random, step: int = 600, warmup_h: float = 2.0) -> Result:
    entry_t: dict[str, int] = {}
    for t, s in series.items():
        for ts, _px, liq in s:
            if liq >= rules.entry_min_vol_usd:
                entry_t[t] = ts
                break
    if not entry_t:
        return Result(capital, 0)
    t0 = min(entry_t.values())
    end = max(s[-1][0] for s in series.values())
    by_arrival = sorted(entry_t, key=lambda a: entry_t[a])
    slots = max(1, int(capital // line))
    cash, open_pos, closed, played, ai, pool, choices = capital, {}, [], 0, 0, [], []
    min_equity = capital
    t = t0
    while t <= end:
        while ai < len(by_arrival) and entry_t[by_arrival[ai]] <= t:
            pool.append(by_arrival[ai])
            ai += 1
        for a in list(open_pos):
            pos = open_pos[a]
            cur = _at(series[a], t)
            if cur is None:
                continue
            px = cur[0]
            pos["peak"] = max(pos["peak"], px)
            r = px / pos["entry"]
            dp = px / pos["peak"] - 1
            if cur[1] < rules.exit_min_vol_usd:
                continue  # no depth: the position cannot be sold at this instant, at any price
            ex = None
            if rules.stop and r <= 1 - rules.stop:
                ex = "stop"
            elif rules.trail and pos["armed"] and dp <= -rules.trail:
                ex = "trailing"
            elif rules.timeout_h and t - pos["t0"] >= rules.timeout_h * 3600:
                ex = "timeout"
            if rules.moonbag and not pos["half"] and r >= rules.moonbag:
                cash += pos["units"] * 0.5 * px * (1 - rules.fee) - rules.gas_usd
                pos["units"] *= 0.5
                pos["half"] = pos["armed"] = True
            if ex:
                cash += pos["units"] * px * (1 - rules.fee) - rules.gas_usd
                closed.append(r)
                del open_pos[a]
        deferred: list[str] = []
        while t >= t0 + warmup_h * 3600 and len(open_pos) < slots and pool and cash >= line:
            choices.append(len(pool))
            a = picker(pool, rng, t, series)
            pool.remove(a)
            cur = _at(series[a], t)
            if cur is None or cur[0] <= 0:
                # No fresh price at this instant is a "not now", not a "never": the token trades
                # again in a few minutes. Discarding it here removed almost every candidate on its
                # first draw and left the book with 21 lines instead of 235.
                deferred.append(a)
                continue
            # The book has to be deep enough AT THE MOMENT OF THE BUY, not merely at some past
            # instant: a drained pool shows a collapsed price nobody could actually buy into.
            if cur[1] < rules.entry_min_vol_usd:
                deferred.append(a)
                continue
            if rules.entry_max_age_h is not None and t - series[a][0][0] > rules.entry_max_age_h * 3600:
                continue
            cash -= line + rules.gas_usd
            open_pos[a] = {"entry": cur[0], "peak": cur[0], "units": line * (1 - rules.fee) / cur[0], "t0": t, "half": False, "armed": rules.trail is not None and rules.moonbag is None}
            played += 1
        pool.extend(deferred)  # still candidates, just not buyable at this instant
        # Mark the whole book to market: what the account is actually worth at this instant, so the
        # deepest drawdown along the way is visible and not just the figure at the finish line.
        equity = cash
        for a, pos in open_pos.items():
            cur = _at(series[a], t)
            if cur and cur[1] >= rules.exit_min_vol_usd:
                equity += pos["units"] * cur[0]
        min_equity = min(min_equity, equity)
        t += step
    for a, pos in open_pos.items():
        # A bag that no longer trades cannot be sold, so it is marked at zero rather than at the
        # last price printed by somebody else's trade.
        cur = _at(series[a], end)
        px = cur[0] if cur and cur[1] >= rules.exit_min_vol_usd else 0.0
        cash += pos["units"] * px * (1 - rules.fee) - (rules.gas_usd if px > 0 else 0.0)
        closed.append(px / pos["entry"])
    return Result(cash, played, closed, choices, min_equity)


def monte_carlo(series: dict[str, list[tuple[int, float, float]]], rules: Rules, *, capital: float, line: float, draws: int = 100, seed: int = 7,
                picker: str = "random", universe_frac: float = 0.7) -> dict[str, Any]:
    """Replay ``draws`` times on random sub-universes.

    Each draw hides part of the token universe, so a deterministic selection rule still produces a
    distribution. The seed drives the sub-universes, so every picker is compared on identical draws.
    """
    fn = make_picker(picker)
    tokens = sorted(series)
    k = max(2, int(len(tokens) * universe_frac))
    finals, plays, choices, mins = [], [], [], []
    for d in range(draws):
        sub_rng = random.Random(seed * 100_003 + d)
        sub = {a: series[a] for a in sub_rng.sample(tokens, min(k, len(tokens)))}
        res = replay(sub, rules, capital=capital, line=line, picker=fn, rng=random.Random(seed + d))
        finals.append(res.final)
        plays.append(res.played)
        choices.append(res.avg_choices)
        mins.append(res.min_equity)
    finals.sort()
    n = len(finals)
    return {
        "rule": rules.name, "picker": picker, "mean": sum(finals) / n, "median": finals[n // 2], "p10": finals[n // 10], "p90": finals[9 * n // 10],
        "worst": finals[0], "best": finals[-1], "win_rate": sum(1 for f in finals if f > capital) / n,
        "lines": sum(plays) / len(plays), "choices": sum(choices) / len(choices) if choices else 0.0,
        "min_equity_median": sorted(mins)[len(mins) // 2], "min_equity_worst": min(mins),
        "ruin_rate": sum(1 for m in mins if m < capital * 0.5) / n,
    }
