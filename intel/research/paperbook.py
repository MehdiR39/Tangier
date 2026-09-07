"""Mark the paper book to market: what every dry-run T+1 entry is worth now, honestly.

The executor journals each built order with the amount it would have spent and the token amount
the pool quoted back. Nothing in the engine follows those virtual positions afterwards, so this
script does: for each BUILT t1 execution it pulls the token's trades since the entry (Bitquery,
wallet-resolved, no node scanning) and applies the same rules as every backtest today --

  - the exit is the price of a trade that HAPPENED, never a print we would have had to create;
  - a level only counts when the volume traded around it could absorb the ticket (20 % cap);
  - a token that never traded again after the entry is worth zero, not its last print.

Read-only on the engine database. Prints one line per position and the book's totals.
"""
from __future__ import annotations

import sqlite3
import sys
import time
from typing import Any

from intel.research.bitquery import Bitquery, _iso

ENGINE_DB = "/app/db/intel.sqlite"
TICKET_EUR = 5.0
MAX_PART = 0.20
FEE = 0.01               # per leg, on top of the quoted impact


def positions(db: str = ENGINE_DB) -> list[dict[str, Any]]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT e.id exec_id, e.ts, e.token_address token, e.quote_address quote, e.size_eur, "
        "       e.amount_in, e.quoted_amount_out, e.slippage_pct, d.reason, d.metrics_json "
        "FROM executions e JOIN decisions d ON d.id=e.decision_id "
        "WHERE d.model_version LIKE 't1-%' AND e.status='BUILT' AND e.kind='BUY' ORDER BY e.ts").fetchall()
    c.close()
    return [dict(r) for r in rows]


def mark(p: dict[str, Any], bq: Bitquery, quote_dec: int, horizon_h: float = 6.0) -> dict[str, Any]:
    entry_ts = int(p["ts"])
    till = min(int(time.time()), entry_ts + int(horizon_h * 3600))
    # Only trades against the SAME quote asset the order used. A token's trades come back in
    # whatever it was traded against (native ETH, WETH, USDG), each with a price in that
    # currency's units; mixing them made a launch look like -95 % in six minutes when its
    # ETH-quoted path had simply been followed by a USDG-quoted trade.
    quote = (p["quote"] or "").lower()
    trades = [t for t in bq.trades(p["token"], _iso(entry_ts), _iso(till)) if t["quote"] == quote]
    amount_in_q = int(p["amount_in"]) / (10 ** quote_dec)            # quote units spent
    units = float(p["quoted_amount_out"] or 0)
    if units <= 0 or amount_in_q <= 0:
        return {**p, "status": "sans cotation"}
    # quoted_amount_out is in raw token units; Bitquery prices are per whole token. The entry
    # price in quote-per-token is what the quote implied, and every later trade is compared to it.
    entry_px = None
    for t in trades:
        if t["price_quote"] > 0:
            entry_px = t["price_quote"]
            break
    if entry_px is None:
        return {**p, "status": "jamais retrade", "mult": 0.0, "value_eur": 0.0}
    # the first trade AFTER entry is our fill (behind the print), as in every backtest today.
    # Bitquery's per-trade prices carry the same corrupted prints as everything else on this chain
    # (one position showed a x1200 "peak" six minutes in): the path is cleaned with the same rules
    # as the research dataset before anything is read off it.
    from intel.research.clean import clean_series
    raw = [(t["ts"], t["price_quote"], t) for t in trades if t["price_quote"] > 0]
    kept, _st = clean_series(raw)
    if not kept:
        return {**p, "status": "prix aberrants", "mult": 0.0, "value_eur": 0.0}
    path = [t for _ts, _px, t in kept]
    # The fill is behind the first prints, not equal to one of them: the spike filter cannot judge
    # the very first trade (no earlier neighbour), and a single bad print there made a launch read
    # -95 % for its whole life. The median of the first three cleaned trades is the fill.
    first = sorted(t["price_quote"] for t in path[:3])
    fill = first[len(first) // 2] * (1 + p.get("slippage_pct", 0.5) / 100)
    last = path[-1]
    vol_q = sum(t["amount_quote"] for t in path if t["ts"] >= last["ts"] - 1800)
    position_q = amount_in_q / fill * last["price_quote"]
    sellable = vol_q > 0 and position_q <= MAX_PART * vol_q
    mult = (last["price_quote"] / fill) * (1 - FEE) ** 2 if sellable else 0.0
    peak = max(t["price_quote"] for t in path) / fill
    age_h = (int(time.time()) - entry_ts) / 3600
    return {**p, "status": "ok" if sellable else "invendable", "mult": mult, "peak": peak,
            "n_trades": len(path), "age_h": age_h, "value_eur": TICKET_EUR * mult,
            "fill_px": fill, "last_px": last["price_quote"]}


async def paths_rpc(ctx, pos: list[dict[str, Any]], horizon_h: float = 6.0) -> dict[int, list[tuple[int, float, float]]]:
    """(block, price_quote, quote_volume_raw) per execution, straight from the chain.

    Bitquery's free plan ran out (HTTP 402) with 68 built entries waiting to be read, so the
    book is marked from the pool's own Swap events: one topic-filtered log query per 40 pools
    over the six hours after entry -- the cohort trick again, no quota involved.
    """
    import json as _json
    from intel.chain.constants import TOPIC_V4_SWAP
    from intel.chain.uniswap_v4 import decode_swap, is_price_at_bound, token_price_in_quote
    meta: dict[str, dict[str, Any]] = {}
    for p in pos:
        try:
            pid = _json.loads(p.get("metrics_json") or "{}").get("pool_id")
        except (TypeError, ValueError):
            pid = None
        if not pid:
            continue
        row = ctx.db.query_one("SELECT token_is_currency0, quote_address FROM pairs WHERE chain_id=? AND pair_id=?",
                               (ctx.chain_id, pid))
        if row is None:
            continue
        meta[p["exec_id"]] = {"pid": pid.lower(), "is_c0": bool(row["token_is_currency0"]),
                              "quote": (row["quote_address"] or "").lower(), "ts": int(p["ts"])}
    import asyncio as _aio
    head = await ctx.rpc.block_number()
    out: dict[int, list[tuple[int, float, float]]] = {e: [] for e in meta}
    execs = list(meta.items())
    for j in range(0, len(execs), 20):
        batch = execs[j: j + 20]
        # entry blocks are unknown here; the decision timestamp is mapped through the chain's
        # ~0.1 s block time, with a margin on both sides
        blk = {e: await ctx.rpc.block_by_timestamp(m["ts"], head=head) for e, m in batch}
        lo = min(blk.values()) - 600
        hi = min(head, max(blk.values()) + int(horizon_h * 36_000) + 600)
        by_pid = {m["pid"]: e for e, m in batch}
        # The public node throttles one-off readers while the engine is polling it: the first
        # morning read of 141 entries died on a 429. Each batch is retried with a real pause,
        # and a batch that still fails is reported as missing rather than aborting the book.
        logs_all: list = []
        for attempt in range(4):
            try:
                logs_all = []
                async for _a, _b, logs in ctx.rpc.iter_logs(address=ctx.pool_manager,
                                                            topics=[TOPIC_V4_SWAP, list(by_pid)],
                                                            from_block=lo, to_block=hi, chunk=60_000):
                    logs_all.extend(logs)
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 3:
                    print(f"  lot {j // 20 + 1} : abandonne apres 4 essais ({str(exc)[:60]}) — {len(batch)} entrees non relues")
                    logs_all = []
                else:
                    await _aio.sleep(30.0 * (attempt + 1))
        if True:
            for lg in logs_all:
                e = by_pid.get(str(lg["topics"][1]).lower())
                if e is None:
                    continue
                try:
                    ev = decode_swap(lg)
                except Exception:
                    continue
                if is_price_at_bound(ev.sqrt_price_x96) or ev.block_number < blk[e]:
                    continue
                m = meta[e]
                qdec = int(((ctx.config.quote_assets.get(m["quote"]) or {}).get("decimals", 18)))
                px = token_price_in_quote(ev.sqrt_price_x96, m["is_c0"], 18, qdec)
                if px <= 0:
                    continue
                qvol = abs(ev.amount1 if m["is_c0"] else ev.amount0) / (10 ** qdec)
                out[e].append((ev.block_number, px, qvol))
    for e in out:
        out[e].sort()
    return out


def mark_from_path(p: dict[str, Any], path: list[tuple[int, float, float]], quote_dec: int) -> dict[str, Any]:
    """same rules as mark(), on a (block, price, quote_volume) path from the chain"""
    from intel.research.clean import clean_series
    amount_in_q = int(p["amount_in"]) / (10 ** quote_dec)
    if not path:
        return {**p, "status": "jamais retrade", "mult": 0.0, "value_eur": 0.0, "n_trades": 0}
    kept, _st = clean_series([(b, px, qv) for b, px, qv in path])
    if not kept:
        return {**p, "status": "prix aberrants", "mult": 0.0, "value_eur": 0.0, "n_trades": len(path)}
    first = sorted(px for _b, px, _q in kept[:3])
    fill = first[len(first) // 2] * (1 + (p.get("slippage_pct") or 0.5) / 100)
    last_b, last_px, _ = kept[-1]
    vol_q = sum(qv for b, _px, qv in kept if b >= last_b - 18_000)          # the last 30 min
    position_q = amount_in_q / fill * last_px
    sellable = vol_q > 0 and position_q <= MAX_PART * vol_q
    mult = (last_px / fill) * (1 - FEE) ** 2 if sellable else 0.0
    peak = max(px for _b, px, _q in kept) / fill
    # The research's only cost-beating exit: sell EVERYTHING the first time x1.5 prints, if the
    # half hour after that print traded enough to absorb the ticket. Otherwise the position runs
    # to now, exactly as above. Both figures are reported; neither is chosen after the fact.
    mult_tp = mult
    for i, (b, px, _q) in enumerate(kept):
        if px / fill >= 1.5:
            vol_after = sum(qv for bb, _p, qv in kept[i:] if bb <= b + 18_000)
            if vol_after > 0 and (amount_in_q / fill * px) <= MAX_PART * vol_after:
                mult_tp = 1.5 * (1 - FEE) ** 2
            break
    return {**p, "status": "ok" if sellable else "invendable", "mult": mult, "peak": peak,
            "mult_tp": mult_tp, "n_trades": len(kept), "age_h": (time.time() - int(p["ts"])) / 3600,
            "value_eur": TICKET_EUR * mult, "value_tp_eur": TICKET_EUR * mult_tp,
            "fill_px": fill, "last_px": last_px}


def main() -> None:
    import asyncio
    from intel.settings import IntelConfig, Settings
    s = Settings.load()
    cfg = IntelConfig.load(s.config_path)
    qdec = {a.lower(): int(m.get("decimals", 18)) for a, m in (cfg.quote_assets or {}).items()}
    source = sys.argv[1] if len(sys.argv) > 1 else "bitquery"
    pos = positions()
    print(f"{len(pos)} entrees T+1 construites a blanc · source {source}\n")
    if source == "db":
        # No network at all: the watcher persists the swaps of every pool it bought for six hours
        # (swap_events.source = 't1_follow'), so the book is marked from what the engine already
        # holds. Entries older than the follow feature (before 2026-09-07 ~11:00 local) have only
        # their pre-decision swaps here and read as "jamais retrade" -- use `rpc` for those.
        import json as _json
        c = sqlite3.connect(f"file:{ENGINE_DB}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        from intel.chain.uniswap_v4 import token_price_in_quote
        rows_out = []
        for p in pos:
            try:
                pid = (_json.loads(p.get("metrics_json") or "{}").get("pool_id") or "").lower()
            except (TypeError, ValueError):
                pid = ""
            pr = c.execute("SELECT token_is_currency0, quote_address FROM pairs WHERE pair_id=?", (pid,)).fetchone() if pid else None
            path: list[tuple[int, float, float]] = []
            if pr is not None:
                is_c0 = bool(pr["token_is_currency0"])
                q = (pr["quote_address"] or "").lower()
                qd = qdec.get(q, 18)
                for s_ in c.execute("SELECT block_number b, sqrt_price_x96 s, amount0 a0, amount1 a1 FROM swap_events "
                                    "WHERE pair_id=? AND ts>=? ORDER BY block_number, log_index", (pid, int(p["ts"]))):
                    px = token_price_in_quote(int(s_["s"]), is_c0, 18, qd)
                    if px > 0:
                        path.append((int(s_["b"]), px, abs(int(s_["a1"] if is_c0 else s_["a0"])) / (10 ** qd)))
            rows_out.append((p, mark_from_path(p, path, qdec.get((p["quote"] or "").lower(), 18))))
        c.close()
        _table(rows_out)
        return
    if source == "rpc":
        from intel.context import IntelContext
        ctx = IntelContext.build()
        try:
            paths = asyncio.run(paths_rpc(ctx, pos))
        finally:
            asyncio.run(ctx.close())
        _table([(p, mark_from_path(p, paths.get(p["exec_id"], []), qdec.get((p["quote"] or "").lower(), 18)))
                for p in pos])
        return
    bq = Bitquery()
    _table([(p, mark(p, bq, qdec.get((p["quote"] or "").lower(), 18))) for p in pos])


def _table(rows: list[tuple[dict[str, Any], dict[str, Any]]]) -> None:
    import re
    print(f"{'quand':>8} {'token':<12} {'swaps 1re min':>13} {'toler.':>7} {'trades apres':>12} {'pic':>7} {'maintenant':>11} {'statut':<12}")
    tot = 0.0
    mults, peaks = [], []
    for p, m in rows:
        tot += m.get("value_eur", 0.0)
        if "mult" in m:
            mults.append(m["mult"])
        if m.get("peak"):
            peaks.append(m["peak"])
        found = re.search(r"(\d+)\s+swaps", p["reason"] or "")
        n1 = found.group(1) if found else "?"
        print(f"{m.get('age_h', 0):>6.1f} h {p['token'][:12]:<12} {n1:>13} {(p.get('slippage_pct') or 0):>6.2f}% "
              f"{m.get('n_trades', 0):>12} {('x%.2f' % m['peak']) if m.get('peak') else '-':>7} "
              f"{('x%.2f' % m['mult']) if 'mult' in m else '-':>11} {m['status']:<12}"
              f"  entree {m.get('fill_px', 0):.3e} -> maintenant {m.get('last_px', 0):.3e}")
    n = len(rows)
    tot_tp = sum(m.get("value_tp_eur", m.get("value_eur", 0.0)) for _p, m in rows)
    print(f"\nlivre : {n} x {TICKET_EUR:.0f} EUR = {n*TICKET_EUR:.0f} EUR engages")
    print(f"        garder jusqu'a maintenant : {tot:.2f} EUR ({(tot/(n*TICKET_EUR)-1) if n else 0:+.1%})")
    print(f"        vendre tout a x1,5        : {tot_tp:.2f} EUR ({(tot_tp/(n*TICKET_EUR)-1) if n else 0:+.1%})"
          f"   [{sum(1 for _p, m in rows if m.get('mult_tp', 0) > m.get('mult', 0))} sorties a x1,5 executables]")
    if mults:
        ms = sorted(mults)
        print(f"        mediane x{ms[len(ms)//2]:.2f} · gagnantes {sum(1 for x in ms if x > 1)/len(ms):.0%} · "
              f">=x2 {sum(1 for x in ms if x >= 2)} · <=x0.2 {sum(1 for x in ms if x <= 0.2)} · "
              f"pic>=x1.5 {sum(1 for x in peaks if x >= 1.5)} · pic>=x2 {sum(1 for x in peaks if x >= 2)}")


if __name__ == "__main__":
    main()
