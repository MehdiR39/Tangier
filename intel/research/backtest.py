"""The 400 EUR book, with costs that can actually be paid.

Three things this refuses to do, each one a mistake made earlier in this project:

  - fill at the printed price. A print is somebody else's trade; entry is the next trade after the
    decision, and exit is the next trade after the exit condition.
  - count a multiple that cannot be sold. Each level records the quote volume traded in the half
    hour after it is touched; a ticket bigger than MAX_PARTICIPATION of that volume does not get
    out there and the position keeps running to whatever it can be sold at.
  - hide the dead. Pools that never trade after entry return zero, not their last print.

Ticket size is fixed per run and never adapts to how much the book "likes" a token.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable

MAX_PARTICIPATION = 0.20     # a ticket may be at most this share of the volume traded at the exit
DEFAULT_POOL_FEE = 0.01      # v4 launch pools commonly run 1% a leg
GAS_EUR = 0.02               # two transactions on this chain; small but not zero on a 10 EUR line


@dataclass
class Costs:
    pool_fee: float = DEFAULT_POOL_FEE
    gas_eur: float = GAS_EUR
    extra_slippage: float = 0.0        # on top of the modelled participation impact

    def impact(self, ticket_eur: float, depth_eur: float | None) -> float:
        """price paid away for size, as a fraction; unknown depth is treated as thin, not free"""
        if not depth_eur or depth_eur <= 0:
            return 0.05
        return min(0.50, ticket_eur / depth_eur)


@dataclass
class Rule:
    name: str
    t_min: float                                   # when the decision is taken
    predicate: Callable[[dict[str, Any]], bool]


@dataclass
class Exit:
    name: str
    # (multiple, fraction of the remaining position to sell) applied in order
    ladder: list[tuple[float, float]] = field(default_factory=list)
    hold_h: float = 6.0                            # otherwise sold at this horizon


HOLD_6H = Exit("garder 6 h", [])
TP_X2 = Exit("tout a x2", [(2.0, 1.0)])
TP_X5 = Exit("tout a x5", [(5.0, 1.0)])
STAKE_BACK_X5 = Exit("recuperer la mise a x5, laisser courir", [(5.0, 0.2)])
LADDER = Exit("x5 20% · x10 30% · x20 50%", [(5.0, 0.2), (10.0, 0.3), (20.0, 0.5)])
EXITS = [HOLD_6H, TP_X2, TP_X5, STAKE_BACK_X5, LADDER]


def _quote_eur(row: dict[str, Any], quote_usd: dict[str, float],
               quote_dec: dict[str, int], eur_usd: float = 1.08) -> float | None:
    """value of one RAW unit of the pool's quote asset, in euros; None when unknown"""
    q = (row.get("quote_address") or "").lower()
    if q not in quote_usd or q not in quote_dec:
        return None
    return (quote_usd[q] / (10 ** quote_dec[q])) / eur_usd


def simulate(rows: list[dict[str, Any]], rule: Rule, exit_rule: Exit, *,
             bankroll: float = 400.0, ticket: float = 20.0, costs: Costs | None = None,
             quote_usd: dict[str, float] | None = None,
             quote_dec: dict[str, int] | None = None) -> dict[str, Any]:
    """Play the rule over the dataset in chronological order with a finite bankroll.

    Positions are opened in the order the launches actually happened, so the book can run out of
    money exactly as it would live -- a rule that fires on everything is not allowed to buy
    everything.
    """
    costs = costs or Costs()
    quote_usd = quote_usd or {}
    quote_dec = quote_dec or {}
    picks = [r for r in rows if r.get("t_min") == rule.t_min and rule.predicate(r)]
    picks.sort(key=lambda r: (r.get("created_block") or 0, r.get("block") or 0))

    cash = bankroll
    trades: list[dict[str, Any]] = []
    seen: set[str] = set()
    no_depth = 0
    # Money stays IN a position until it is sold. Without this the cash came back the instant a
    # position was opened, 400 EUR ran 377 positions at 40 EUR each, and the final multiple grew
    # with the ticket size purely through unconstrained reinvestment -- an artefact, not an edge.
    # A position is released at the block its exit happened (target hit, or the 6 h horizon).
    open_pos: list[tuple[int, float]] = []          # (release_block, proceeds)
    BPM = 600
    for r in picks:
        now = int(r.get("block") or 0)
        still = []
        for rel, val in open_pos:
            if rel <= now:
                cash += val
            else:
                still.append((rel, val))
        open_pos = still
        if r["pair_id"] in seen or cash < ticket:
            continue
        seen.add(r["pair_id"])
        qe = _quote_eur(r, quote_usd, quote_dec)
        depth_eur = (r.get("liquidity_q") or 0) * qe if qe else None
        if depth_eur is None:
            no_depth += 1
        buy_cost = costs.pool_fee + costs.extra_slippage + costs.impact(ticket, depth_eur)
        units = ticket * (1.0 - buy_cost)          # value terms, normalised to the entry price
        cash -= ticket + costs.gas_eur

        proceeds = 0.0
        remaining = 1.0
        for level, frac in exit_rule.ladder:
            if not r.get(f"hit_x{level:g}"):
                continue
            sellvol = r.get(f"sellable_x{level:g}")
            # a missing volume means UNKNOWN, not zero. Reading it as zero made the participation
            # test reject every exit at that level, and the position fell through to the horizon
            # without anything saying so.
            sell_eur = (sellvol * qe) if (qe and sellvol is not None) else None
            part_ok = (sell_eur is None) or (ticket * frac <= MAX_PARTICIPATION * sell_eur)
            if not part_ok:
                continue                            # the level printed but we could not get out
            take = remaining * frac
            sell_cost = costs.pool_fee + costs.extra_slippage + costs.impact(ticket * take, sell_eur)
            proceeds += units * take * level * (1.0 - sell_cost)
            remaining -= take
            cash -= costs.gas_eur
        if remaining > 0:
            end = r.get("ret_6h") or 0.0
            # closing at the horizon is a trade too: it needs somebody on the other side. Without
            # this the book was selling every held position at the last printed price, which is
            # exactly what made an earlier version look profitable.
            exit_eur = (r.get("exit_vol_6h") or 0) * qe if qe else None
            if exit_eur is not None and ticket * remaining > MAX_PARTICIPATION * exit_eur:
                end = 0.0                              # nobody to sell into: the bag is worthless
            sell_cost = costs.pool_fee + costs.extra_slippage + costs.impact(ticket * remaining, exit_eur or depth_eur)
            proceeds += units * remaining * end * (1.0 - sell_cost)
            if end > 0:
                cash -= costs.gas_eur
        # the money comes back when the position actually closes, not now
        hold_min = 360.0
        if remaining <= 0 and exit_rule.ladder:
            last_level = exit_rule.ladder[-1][0]
            t_hit = r.get(f"t_to_x{last_level:g}")
            if t_hit is not None:
                hold_min = float(t_hit)
        open_pos.append((now + int(hold_min * BPM), proceeds))
        trades.append({"pair_id": r["pair_id"], "in": ticket, "out": proceeds,
                       "mult": proceeds / ticket if ticket else 0.0,
                       "max6h": r.get("max_ret_6h") or 0.0})

    cash += sum(val for _rel, val in open_pos)      # whatever is still open at the end
    if not trades:
        return {"rule": rule.name, "exit": exit_rule.name, "ticket": ticket, "n": 0}
    pnl = [t["out"] - t["in"] for t in trades]
    mult = sorted(t["mult"] for t in trades)
    total = sum(pnl)
    top = sorted(pnl, reverse=True)
    n = len(trades)
    return {
        "rule": rule.name, "exit": exit_rule.name, "ticket": ticket, "n": n,
        "final": bankroll + total, "pnl": total,
        "win_rate": sum(1 for p in pnl if p > 0) / n,
        "median_mult": statistics.median(mult), "mean_mult": statistics.mean(mult),
        "to_zero": sum(1 for m in mult if m <= 0.10) / n,
        "under_80": sum(1 for m in mult if m <= 0.20) / n,
        "n_x2": sum(1 for t in trades if t["max6h"] >= 2),
        "n_x5": sum(1 for t in trades if t["max6h"] >= 5),
        "n_x10": sum(1 for t in trades if t["max6h"] >= 10),
        "n_x20": sum(1 for t in trades if t["max6h"] >= 20),
        "n_x50": sum(1 for t in trades if t["max6h"] >= 50),
        "pnl_sans_top1": total - sum(top[:1]),
        "pnl_sans_top3": total - sum(top[:3]),
        "pnl_sans_top5": total - sum(top[:5]),
        "sans_profondeur": no_depth,
        "trades": trades,
    }


def fmt(res: dict[str, Any]) -> str:
    if not res.get("n"):
        return f"{res['rule']:<28} {res['exit']:<32} aucune position"
    return (f"{res['rule']:<28} {res['exit']:<32} {res['n']:>4} pos · "
            f"final {res['final']:>7.0f}€ · med x{res['median_mult']:.2f} · "
            f"gagn {res['win_rate']:>4.0%} · zero {res['to_zero']:>4.0%} · "
            f"x5:{res['n_x5']:<3} x10:{res['n_x10']:<3} x20:{res['n_x20']:<3} · "
            f"sans top3 {res['pnl_sans_top3']:>+7.0f}€")
