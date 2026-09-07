"""A whole 400 EUR book replayed over the history, with the exit priced the way this chain really works.

What the tapes say about the pools the T+1 rule buys (374 launches, research.sqlite):
  - they trade for a few minutes, then stop -- median tape span 0.1 h;
  - 301 of them (80 %) have their tokens leave the PoolManager within a second of the LAST swap:
    the deployer pulls the liquidity as soon as the bots stop. Nothing is sellable after that.
So a position is worth something only while the pool still trades: a sale placed before the last
swap gets the curve price at the last print (our own impact included), capped by the quote the
pool really holds (buys in minus sells out, plus our own ticket); a sale placed at or after the
last swap gets zero when the pool was pulled, and the curve price when it was not.

Rules are then plain: sell at T+k minutes, or at a target if it comes first, or trail. The book
replays the trades chronologically with 80 slots of 5 EUR, and the book-level rules (cash out at
+20 %, harvest winners) sit on top. Same data, same fills, the ranking is the finding.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from intel.research.features import price_from_sqrt, virtual_quote

BPM = 600
TICK = 5 * BPM
FEE = 0.01
GAS = 0.02
TICKET = 5.0
SLOTS = 80
MIN_TRADES = 27
DUST_EUR = 0.10
POOL_MANAGER = "0x8366a39cc670b4001a1121b8f6a443a643e40951"


def load(db: str, quote_usd: dict[str, float], quote_dec: dict[str, int], eur_usd: float = 1.08) -> list[dict[str, Any]]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    pools = {r["pair_id"]: (bool(r["is_c0"]), (r["quote_address"] or "").lower(), (r["token_address"] or "").lower())
             for r in c.execute("SELECT pair_id, is_c0, quote_address, token_address FROM rp_pool WHERE n_swaps>0")}
    busy = {r["pair_id"]: (json.loads(r["feat_json"]).get("trades_5m") or 0)
            for r in c.execute("SELECT pair_id, feat_json FROM rp_snap WHERE t_min=1")}
    launches = []
    for pid, (c0, q_addr, tok_addr) in pools.items():
        if busy.get(pid, 0) < MIN_TRADES or q_addr not in quote_usd or q_addr not in quote_dec:
            continue
        sw = []
        cum = 0.0
        for r in c.execute("SELECT block, sqrt_price, liquidity, amount0, amount1 FROM rp_swap WHERE pair_id=? ORDER BY block, log_index", (pid,)):
            sq, lq = int(r["sqrt_price"]), int(r["liquidity"] or 0)
            a0, a1 = int(r["amount0"]), int(r["amount1"])
            q = abs(a1 if c0 else a0)
            tok = a0 if c0 else a1
            cum += q if tok > 0 else -q                # v4 deltas are the user side: tokens received is a buy
            px = price_from_sqrt(sq, c0)
            if px > 0:
                sw.append((r["block"], px, virtual_quote(lq, sq, c0), max(cum, 0.0)))
        if len(sw) < 4:
            continue
        b = sw[0][0] + BPM
        after = [s for s in sw if s[0] > b]
        if len(after) < 3:
            continue
        last_block = sw[-1][0]
        pull = c.execute("SELECT MIN(block) b FROM rp_transfer WHERE token_address=? AND lower(from_address)=? AND block>?",
                         (tok_addr, POOL_MANAGER, last_block)).fetchone()["b"]
        ticket_raw = TICKET * eur_usd / quote_usd[q_addr] * (10 ** quote_dec[q_addr])
        launches.append({"pid": pid, "entry_block": after[0][0], "ticket_raw": ticket_raw, "path": after,
                         "fill": sorted(x[1] for x in after[:3])[1], "depth0": after[0][2],
                         "last_block": last_block, "pulled": pull is not None})
    launches.sort(key=lambda L: L["entry_block"])
    return launches


def tokens_bought(L: dict[str, Any]) -> float:
    q = L["ticket_raw"] * (1 - FEE)
    y = max(L["depth0"], 1.0)
    x = y / L["fill"]
    return x * q / (y + q)


def proceeds_eur(L: dict[str, Any], tokens: float, px: float, depth: float, real_q: float) -> float:
    """selling ``tokens`` into the curve at this print, capped by the quote the pool really holds"""
    if depth <= 0:
        return 0.0
    x = depth / px
    out = depth * tokens / (x + tokens)
    out = min(out, real_q + L["ticket_raw"] * (1 - FEE))
    return out / L["ticket_raw"] * TICKET


def trade(L: dict[str, Any], rule: str) -> dict[str, Any]:
    """one position under one rule: (exit_block, eur_out, reason). Rules:
       t+k          sell at entry + k minutes
       tpX|t+k      sell when the multiple reaches X, else at entry + k minutes
       trail:P|t+k  once the multiple reached P, sell at half the peak; else at entry + k minutes
    """
    tokens = tokens_bought(L)
    cost = TICKET + GAS
    kind, _, tail = rule.partition("|")
    k = float((tail or kind).split("+")[1]) if "t+" in (tail or kind) else 360.0
    deadline = L["entry_block"] + int(k * BPM)
    target = float(kind[2:]) if kind.startswith("tp") else None
    trail_arm = float(kind.split(":")[1]) if kind.startswith("trail") else None
    peak = 0.0
    armed = False
    sale_block = deadline
    reason = "temps"
    for blk, px, depth, real_q in L["path"]:
        if blk > deadline:
            break
        m = px * tokens / (L["ticket_raw"] * (1 - FEE))
        peak = max(peak, m)
        if target is not None and m >= target:
            sale_block, reason = blk, "cible"
            break
        if trail_arm is not None:
            if m >= trail_arm:
                armed = True
            if armed and m <= 0.5 * peak:
                sale_block, reason = blk, "suiveur"
                break
    # what is executable at that block: the last print at or before it
    last = None
    for s in L["path"]:
        if s[0] <= sale_block:
            last = s
        else:
            break
    if last is None:
        last = L["path"][0]
    if sale_block >= L["last_block"]:
        # the pool has stopped trading: pulled means gone, otherwise the curve still pays
        if L["pulled"]:
            return {"exit_block": sale_block, "out": 0.0, "reason": "rug", "cost": cost}
        reason = "silence"
    out = proceeds_eur(L, tokens, last[1], last[2], last[3])
    if out < DUST_EUR:
        return {"exit_block": sale_block, "out": 0.0, "reason": "poussiere", "cost": cost}
    return {"exit_block": sale_block, "out": out * (1 - FEE) - GAS, "reason": reason, "cost": cost}


def book(launches: list[dict[str, Any]], rule: str, book_rule: str = "none", start_cash: float = 400.0) -> dict[str, Any]:
    trades = [(L["entry_block"], trade(L, rule)) for L in launches]
    cash = start_cash
    base = start_cash
    open_: list[dict[str, Any]] = []
    realised: list[float] = []
    reasons: dict[str, int] = {}
    unfunded = 0
    resets = 0
    lo = hi = start_cash
    ti = 0
    tick = trades[0][0] - TICK
    end = max(t["exit_block"] for _e, t in trades) + TICK
    while tick <= end:
        still = []
        for t in open_:
            if t["exit_block"] <= tick:
                cash += t["out"]
                realised.append(t["out"] - t["cost"])
                reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
            else:
                still.append(t)
        open_ = still
        equity = cash + sum(t["cost"] for t in open_)          # open positions carried at cost: nothing is banked before it is sold
        lo, hi = min(lo, equity), max(hi, equity)
        kind, _, pct = book_rule.partition("_")
        if kind == "reset" and cash >= base * (1 + float(pct) / 100):
            resets += 1
            base = cash                                         # "on repart de zero": the bar moves up with the book
        while ti < len(trades) and trades[ti][0] <= tick:
            entry, t = trades[ti]
            ti += 1
            if len(open_) >= SLOTS or cash < TICKET + GAS:
                unfunded += 1
                continue
            cash -= TICKET + GAS
            open_.append(t)
        tick += TICK
    for t in open_:
        cash += t["out"]
        realised.append(t["out"] - t["cost"])
    mults = sorted((r + TICKET + GAS) / (TICKET + GAS) for r in realised)
    n = len(realised)
    return {"final": cash, "n": n, "win": sum(1 for r in realised if r > 0) / n if n else 0.0,
            "med": mults[n // 2] if n else 0.0, "p25": mults[n // 4] if n else 0.0, "p75": mults[3 * n // 4] if n else 0.0,
            "lo": lo, "hi": hi, "unfunded": unfunded, "resets": resets, "reasons": reasons,
            "sum_pos": sum(r for r in realised if r > 0), "sum_neg": sum(r for r in realised if r < 0)}


def line(lab: str, r: dict[str, Any]) -> str:
    rs = " ".join(f"{k}:{v}" for k, v in sorted(r["reasons"].items(), key=lambda kv: -kv[1]))
    return (f"{lab:<34} {r['final']:>7.0f}€ {r['lo']:>6.0f}€ {r['n']:>5} {r['win']:>5.0%} "
            f"{r['p25']:>5.2f} {r['med']:>5.2f} {r['p75']:>5.2f} {r['sum_pos']:>7.0f}€ {r['sum_neg']:>7.0f}€ {r['unfunded']:>4} {r['resets']:>3}  {rs}")


HDR = (f"{'regle':<34} {'final':>8} {'bas':>7} {'trad':>5} {'gagn':>6} {'p25':>5} {'med':>5} {'p75':>5} "
       f"{'gains':>8} {'pertes':>8} {'nonf':>4} {'rst':>3}  sorties")

if __name__ == "__main__":
    import asyncio
    from intel.context import IntelContext
    from intel.research.report import native_price_usd, quote_maps
    ctx = IntelContext.build()
    native = asyncio.run(native_price_usd(ctx))
    qu, qd = quote_maps(ctx, native)
    launches = load("/app/data/research.sqlite", qu, qd)
    span_d = (launches[-1]["entry_block"] - launches[0]["entry_block"]) / BPM / 60 / 24
    pulled = sum(L["pulled"] for L in launches)
    lifes = sorted((L["last_block"] - L["entry_block"]) / BPM for L in launches)
    print(f"{len(launches)} lancements T+1 sur {span_d:.0f} jours · liquidite retiree apres le dernier swap: {pulled} ({pulled/len(launches):.0%}) "
          f"· vie apres notre entree (min) p25/med/p75: {lifes[len(lifes)//4]:.1f}/{lifes[len(lifes)//2]:.1f}/{lifes[3*len(lifes)//4]:.1f} · natif {native:.0f} $")
    print("\n== vendre a T+k minutes (livre 400 EUR, 80 places de 5 EUR) ==")
    print(HDR)
    rules = [f"t+{k}" for k in (1, 2, 3, 4, 5, 7, 10, 15, 30)]
    for r in rules:
        print(line(f"vendre a T+{r[2:]} min", book(launches, r)))
    print("\n== cible x1.5 / x2 / x3, sinon T+k ==")
    print(HDR)
    for tp in (1.5, 2, 3):
        for k in (3, 5, 10):
            print(line(f"x{tp} sinon T+{k}", book(launches, f"tp{tp}|t+{k}")))
    print("\n== suiveur -50 % arme a x2 / x3, sinon T+k ==")
    print(HDR)
    for arm in (2, 3):
        for k in (5, 10):
            print(line(f"suiveur des x{arm} sinon T+{k}", book(launches, f"trail:{arm}|t+{k}")))
    best = max([f"t+{k}" for k in (2, 3, 4, 5, 7, 10)] + [f"tp{tp}|t+{k}" for tp in (1.5, 2, 3) for k in (3, 5, 10)],
               key=lambda r: book(launches, r)["final"])
    print(f"\n== regles de livre sur la meilleure regle ({best}) ==")
    print(HDR)
    for br, lab in (("none", "aucune"), ("reset_20", "repartir de 0 a +20 %"), ("reset_50", "repartir de 0 a +50 %")):
        print(line(f"{best} · {lab}", book(launches, best, br)))
    print(f"\n== stabilite ({best}): tiers chronologiques, 400 EUR chacun ==")
    print(HDR)
    k = len(launches) // 3
    for i, part in enumerate((launches[:k], launches[k:2 * k], launches[2 * k:])):
        print(line(f"{best} · tiers {i + 1}", book(part, best)))
    print(f"\n== {best}: sans les 1 / 3 / 5 meilleures ventes ==")
    tr = sorted((trade(L, best)["out"] - TICKET - GAS for L in launches), reverse=True)
    tot = sum(tr)
    for n in (1, 3, 5):
        print(f"   sans top {n}: {tot - sum(tr[:n]):+.0f} € (total {tot:+.0f} €)")
