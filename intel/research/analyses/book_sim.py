"""A whole 400 EUR book replayed over the 45-day history: which exit rules, per position and for the book?

Every earlier exit study priced a silent pool at zero ("no buyer"). That is wrong for an AMM: a sale
needs liquidity in the pool, not a buyer, and rp_swap carries the pool's liquidity at every print.
So here a position is worth what selling it INTO THE CURVE would return -- constant product, our
own impact included -- and a pool whose depth collapsed to a tenth of its peak (the label's rug
rule) is worth nothing. That is the executable value, alive or silent.

The replay is chronological on the unbiased sample: 80 slots of 5 EUR, real prices and depths,
5-minute ticks, fills behind the first prints. Per-position rules and book rules are crossed on
the same data with the same fills; the ranking is the finding, the euros are the scale.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from intel.research.features import price_from_sqrt, virtual_quote

BPM = 600
TICK = 5 * BPM
FEE = 0.01            # pool fee per leg
GAS = 0.02            # EUR per transaction
TICKET = 5.0
SLOTS = 80
MIN_TRADES = 27
DUST_EUR = 0.10       # a sale that returns less than this costs more than it brings: abandoned
RUG_FRAC = 0.10       # depth under a tenth of its own peak: the label's rug definition


@dataclass
class Pos:
    pid: str
    entry_block: int
    tokens: float               # raw token units held
    ticket_raw: float           # the ticket in raw quote units (what 5 EUR is in this pool)
    path: list                  # (block, price_raw, depth_raw, net_quote_in_raw)
    peak_depth: float
    i: int = 0
    peak: float = 1.0
    armed: bool = False
    half_done: bool = False
    cost: float = TICKET + GAS


def load(db: str, quote_usd: dict[str, float], quote_dec: dict[str, int], eur_usd: float = 1.08) -> list[dict[str, Any]]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    pools = {r["pair_id"]: (bool(r["is_c0"]), (r["quote_address"] or "").lower())
             for r in c.execute("SELECT pair_id, is_c0, quote_address FROM rp_pool WHERE n_swaps>0")}
    busy = {r["pair_id"]: (json.loads(r["feat_json"]).get("trades_5m") or 0)
            for r in c.execute("SELECT pair_id, feat_json FROM rp_snap WHERE t_min=1")}
    launches = []
    for pid, (c0, q_addr) in pools.items():
        if busy.get(pid, 0) < MIN_TRADES or q_addr not in quote_usd or q_addr not in quote_dec:
            continue
        sw = []
        cum = 0.0                                      # quote that really sits in the pool: buys in, sells out
        for r in c.execute("SELECT block, sqrt_price, liquidity, amount0, amount1 FROM rp_swap WHERE pair_id=? ORDER BY block, log_index", (pid,)):
            sq, lq = int(r["sqrt_price"]), int(r["liquidity"] or 0)
            a0, a1 = int(r["amount0"]), int(r["amount1"])
            q = abs(a1 if c0 else a0)
            tok = a0 if c0 else a1
            cum += q if tok > 0 else -q                # v4 deltas are the user side: tokens received means a buy
            px = price_from_sqrt(sq, c0)
            if px > 0:
                sw.append((r["block"], px, virtual_quote(lq, sq, c0), max(cum, 0.0)))
        if len(sw) < 4:
            continue
        b = sw[0][0] + BPM
        after = [s for s in sw if s[0] > b]
        if len(after) < 3:
            continue
        ticket_raw = TICKET * eur_usd / quote_usd[q_addr] * (10 ** quote_dec[q_addr])
        peak_depth = max(s[2] for s in sw if s[0] <= after[0][0])
        launches.append({"pid": pid, "entry_block": after[0][0], "ticket_raw": ticket_raw,
                         "path": after, "peak_depth": peak_depth,
                         "fill": sorted(x[1] for x in after[:3])[1], "depth0": after[0][2]})
    launches.sort(key=lambda L: L["entry_block"])
    return launches


def buy(L: dict[str, Any]) -> Pos:
    """5 EUR into the curve at the fill: the tokens we actually get, our own impact included"""
    q = L["ticket_raw"] * (1 - FEE)
    y = max(L["depth0"], 1.0)
    x = y / L["fill"]
    tokens = x * q / (y + q)
    return Pos(L["pid"], L["entry_block"], tokens, L["ticket_raw"], L["path"], L["peak_depth"])


def mark(pos: Pos, tick: int) -> tuple[float, float, float, float]:
    """(frictionless multiple vs what we put in, price_raw, depth_raw, real quote in pool) at the last print <= tick"""
    while pos.i + 1 < len(pos.path) and pos.path[pos.i + 1][0] <= tick:
        pos.i += 1
        pos.peak_depth = max(pos.peak_depth, pos.path[pos.i][2])
    _blk, px, depth, real_q = pos.path[pos.i]
    m = px * pos.tokens / (pos.ticket_raw * (1 - FEE))
    pos.peak = max(pos.peak, m)
    return m, px, depth, real_q


CAPPED = [0, 0]       # sales capped by the quote really held by the pool / all sales (diagnostic)


def value_eur(pos: Pos, px: float, depth: float, real_q: float, frac: float = 1.0, count: bool = False) -> float:
    """what selling ``frac`` of the position returns, in EUR, before fee and gas

    The curve gives the proceeds; the quote really held by the pool (what buyers put in, net of
    what sellers took out, assuming the launch itself brought none) is the ceiling. That is the
    conservative reading of a one-sided launch: virtual depth can be large while the pool holds
    almost nothing to pay out.
    """
    if depth <= RUG_FRAC * pos.peak_depth or depth <= 0:
        return 0.0
    n = pos.tokens * frac
    x = depth / px
    proceeds = depth * n / (x + n)
    if count:
        CAPPED[1] += 1
        if proceeds > real_q:
            CAPPED[0] += 1
    proceeds = min(proceeds, real_q)
    return proceeds / pos.ticket_raw * TICKET


def simulate(launches: list[dict[str, Any]], *, pos_rule: str, book_rule: str = "none",
             silence_min: int = 30, dust: bool = True, start_cash: float = 400.0) -> dict[str, Any]:
    cash = start_cash
    base = start_cash
    open_: list[Pos] = []
    realised: list[float] = []
    mults: list[float] = []
    unfunded = 0
    resets = 0
    eq_curve: list[float] = []
    start_block = launches[0]["entry_block"] - TICK
    end_block = max(L["path"][-1][0] for L in launches)
    li = 0
    tick = start_block

    def sell(p: Pos, px: float, depth: float, real_q: float, frac: float = 1.0) -> bool:
        """returns True when the position is gone"""
        nonlocal cash
        v = value_eur(p, px, depth, real_q, frac, count=True)
        if frac >= 1.0:
            mults.append(v / max(p.cost, 0.01))
        if dust and v < DUST_EUR:
            if frac >= 1.0:
                realised.append(-p.cost)                 # abandoned: worth less than the fee
                return True
            return False
        cash += v * (1 - FEE) - GAS
        if frac >= 1.0:
            realised.append(v * (1 - FEE) - GAS - p.cost)
            return True
        p.tokens *= (1 - frac)
        p.cost -= v * (1 - FEE) - GAS
        if p.cost < 0:                                    # stake recovered: the rest rides for free
            realised.append(-p.cost)
            p.cost = 0.0
        return False

    while tick <= end_block:
        still = []
        for p in open_:
            m, px, depth, real_q = mark(p, tick)
            age_min = (tick - p.entry_block) / BPM
            silent = (tick - p.path[p.i][0]) / BPM > silence_min
            gone = False
            if m >= 5.0:
                p.armed = True
            if pos_rule == "hold6h":
                if silent or age_min >= 360:
                    gone = sell(p, px, depth, real_q)
            elif pos_rule == "trail5":
                if silent or (p.armed and m <= p.peak * 0.5) or (age_min >= 360 and m < 1.0):
                    gone = sell(p, px, depth, real_q)
            elif pos_rule.startswith("tp"):
                if m >= float(pos_rule[2:]) or silent or age_min >= 360:
                    gone = sell(p, px, depth, real_q)
            elif pos_rule.startswith("half"):
                if not p.half_done and m >= float(pos_rule[4:]):
                    sell(p, px, depth, real_q, 0.5)
                    p.half_done = True
                    p.peak = m
                elif p.half_done and m <= p.peak * 0.5:
                    gone = sell(p, px, depth, real_q)
                elif silent or (age_min >= 360 and m < 1.0):
                    gone = sell(p, px, depth, real_q)
            if not gone:
                still.append(p)
        open_ = still
        # the book rule works on executable equity
        vals = [(p,) + mark(p, tick) for p in open_]
        equity = cash + sum(value_eur(p, px, depth, rq) for p, _m, px, depth, rq in vals)
        eq_curve.append(equity)
        kind, _, pct = book_rule.partition("_")
        if kind in ("reset", "harvest") and equity >= base * (1 + float(pct) / 100):
            keep = []
            for p, m, px, depth, rq in vals:
                if kind == "harvest" and m < 2.0:
                    keep.append(p)
                    continue
                if not sell(p, px, depth, rq):
                    keep.append(p)
            open_ = keep
            resets += 1
            base = cash + sum(value_eur(p, *mark(p, tick)[1:]) for p in open_)
        while li < len(launches) and launches[li]["entry_block"] <= tick:
            L = launches[li]
            li += 1
            if len(open_) >= SLOTS or cash < TICKET + GAS:
                unfunded += 1
                continue
            cash -= TICKET + GAS
            open_.append(buy(L))
        tick += TICK
    equity = cash + sum(value_eur(p, *mark(p, end_block)[1:]) * (1 - FEE) for p in open_)
    full = sorted(mults)
    return {"final": equity, "sells": len(realised), "open": len(open_), "resets": resets, "unfunded": unfunded,
            "exit_med": full[len(full) // 2] if full else 0.0,
            "min_equity": min(eq_curve), "max_equity": max(eq_curve),
            "win_rate": (sum(1 for r in realised if r > 0) / len(realised)) if realised else 0.0}


POS_RULES = (("hold6h", "tenir 6 h (ou silence)"),
             ("tp1.5", "tout vendre a x1.5"),
             ("tp2", "tout vendre a x2"),
             ("tp3", "tout vendre a x3"),
             ("half2", "moitie a x2, reste suiveur -50 %"),
             ("half3", "moitie a x3, reste suiveur -50 %"),
             ("trail5", "suiveur -50 % arme a x5, 6 h si < x1"))
BOOK_RULES = (("none", "aucune"), ("reset_20", "tout vendre a +20 %"), ("reset_50", "tout vendre a +50 %"),
              ("harvest_20", "+20 %: vendre les >= x2"))


def line(lab: str, r: dict[str, Any]) -> str:
    return (f"{lab:<48} {r['final']:>7.0f}€ {r['min_equity']:>8.1f}€ {r['max_equity']:>9.0f}€ "
            f"{r['sells']:>6} {r['win_rate']:>5.0%} {r['exit_med']:>6.2f} {r['unfunded']:>8} {r['resets']:>6}")


if __name__ == "__main__":
    import asyncio
    from intel.context import IntelContext
    from intel.research.report import native_price_usd, quote_maps
    ctx = IntelContext.build()
    native = asyncio.run(native_price_usd(ctx))
    quote_usd, quote_dec = quote_maps(ctx, native)
    launches = load("/app/data/research.sqlite", quote_usd, quote_dec)
    span_d = (launches[-1]["entry_block"] - launches[0]["entry_block"]) / BPM / 60 / 24
    print(f"{len(launches)} lancements jouables par la regle T+1 sur {span_d:.0f} jours · 400 EUR · {SLOTS} places de {TICKET:.0f} EUR · natif {native:.0f} $")
    hdr = f"{'regle':<48} {'final':>8} {'plus bas':>9} {'plus haut':>10} {'ventes':>6} {'gagn.':>6} {'sortie':>6} {'non fin.':>8} {'resets':>6}"
    print("\n== regles par position (livre: aucune regle) ==")
    print(hdr)
    for pr, plab in POS_RULES:
        print(line(plab, simulate(launches, pos_rule=pr)))
    print("\n== silence avant de vendre (regle tp2) ==")
    print(hdr)
    for s in (5, 10, 30, 60):
        print(line(f"tp2, vendre apres {s} min sans trade", simulate(launches, pos_rule="tp2", silence_min=s)))
    print("\n== regles de livre croisees avec les 3 meilleures regles par position ==")
    print(hdr)
    ranked = sorted(POS_RULES, key=lambda pr: -simulate(launches, pos_rule=pr[0])["final"])[:3]
    for pr, plab in ranked:
        for br, blab in BOOK_RULES:
            print(line(f"{plab} · {blab}", simulate(launches, pos_rule=pr, book_rule=br)))
    print("\n== stabilite: premiere moitie / seconde moitie des lancements (400 EUR chacune) ==")
    print(hdr)
    h = len(launches) // 2
    for pr, plab in ranked:
        print(line(f"{plab} · 1re moitie", simulate(launches[:h], pos_rule=pr)))
        print(line(f"{plab} · 2de moitie", simulate(launches[h:], pos_rule=pr)))
    print(f"\nventes plafonnees par la cotation reellement detenue par le pool: {CAPPED[0]} / {CAPPED[1]}")
    print("\n== poussiere: vendre meme sous 0.10 EUR (regle tp2) ==")
    print(line("tp2 · on vend meme la poussiere", simulate(launches, pos_rule="tp2", dust=False)))
