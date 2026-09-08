"""The safety envelope every order must clear before it can be signed.

This module holds no keys and performs no I/O beyond reading the local database. It is the one
place that decides whether an order is allowed, so it stays small enough to read in one sitting
and is covered by tests case by case.

Design rules, in order of importance:
- refuse by default: any unknown, missing or unparsable input is a refusal, never an approval;
- every limit is absolute, expressed in euros or in counts, never as a percentage of something
  that the engine itself computes (a bug in scoring must not be able to raise a spending limit);
- refusals carry a reason, so a blocked order can be explained without re-running anything.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from intel.context import IntelContext
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)

# Order kinds the executor understands. Anything else is refused outright.
BUY, SELL_HALF, SELL_ALL = "BUY", "SELL_HALF", "SELL_ALL"
KINDS = {BUY, SELL_HALF, SELL_ALL}


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reasons: list[str] = field(default_factory=list)

    @property
    def why(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "ok"


@dataclass(frozen=True)
class Limits:
    """Absolute ceilings. Read from config once, never recomputed from live metrics."""
    max_eur_per_order: float = 25.0
    max_open_positions: int = 15
    max_orders_per_day: int = 40
    max_eur_per_day: float = 200.0
    max_slippage_pct: float = 5.0
    max_sell_impact_pct: float = 60.0        # exits are allowed to be expensive; being stuck is worse
    min_quote_liquidity_usd: float = 20_000.0
    allowed_quotes: tuple[str, ...] = ()      # empty means "no quote allowed": refuse by default
    kill_switch: bool = False

    @classmethod
    def from_config(cls, ctx: IntelContext) -> "Limits":
        c = ctx.config.section("execution")
        quotes = tuple(str(a).lower() for a in (c.get("allowed_quotes") or []))
        return cls(
            max_eur_per_order=float(c.get("max_eur_per_order", 25.0)),
            max_open_positions=int(c.get("max_open_positions", 15)),
            max_orders_per_day=int(c.get("max_orders_per_day", 40)),
            max_eur_per_day=float(c.get("max_eur_per_day", 200.0)),
            max_slippage_pct=float(c.get("max_slippage_pct", 5.0)),
            max_sell_impact_pct=float(c.get("max_sell_impact_pct", 60.0)),
            min_quote_liquidity_usd=float(c.get("min_quote_liquidity_usd", 20_000.0)),
            allowed_quotes=quotes,
            kill_switch=bool(c.get("kill_switch", False)),
        )


def spent_today(ctx: IntelContext) -> tuple[int, float]:
    """(buys, euros committed) in the last 24 h, from the execution journal.

    Buys only. The daily ceilings exist to bound what LEAVES the wallet, and every sale used to
    count against them: on 2026-09-08 fourteen buys in a row were refused for "41 orders today >=
    40" when most of those orders were exits, and each retried sale ate a little more of the
    allowance. A book that sells a lot would forbid itself from buying at all.
    """
    # Spending grants are journalled too, but they are not orders: counting them would eat the
    # daily allowance without a single trade being made.
    row = ctx.db.query_one(
        "SELECT COUNT(*) n, COALESCE(SUM(size_eur), 0) eur FROM executions "
        "WHERE chain_id=? AND ts>? AND status IN ('SUBMITTED','CONFIRMED') AND kind='BUY'",
        (ctx.chain_id, now_ts() - 86400),
    )
    return (int(row["n"]), float(row["eur"])) if row else (0, 0.0)


def check(ctx: IntelContext, order: dict[str, Any], limits: Limits) -> Verdict:
    """Every reason an order is refused, collected — not just the first one.

    Collecting them all matters operationally: fixing one limit only to hit the next one on the
    following pass wastes a window that lasts minutes on this asset class.
    """
    reasons: list[str] = []
    kind = order.get("kind")
    token = str(order.get("token") or "").lower()
    quote = str(order.get("quote") or "").lower()
    size = order.get("size_eur")
    slippage = order.get("slippage_pct")
    liq = order.get("quote_liquidity_usd")

    if limits.kill_switch:
        reasons.append("arrêt d'urgence actif")
    if kind not in KINDS:
        reasons.append(f"type d'ordre inconnu: {kind!r}")
    if not token.startswith("0x") or len(token) != 42:
        reasons.append("adresse de token invalide")
    # The whitelist says what we are willing to SPEND, so it gates buys. Applying it to a sell
    # traps the book inside a token whose only living pool is quoted elsewhere: on 2026-09-07 a
    # bag was written off as unsellable while a USDG-quoted pool would have paid for it.
    if kind == BUY and quote not in limits.allowed_quotes:
        reasons.append(f"actif de cotation non autorisé: {quote or 'aucun'}")

    if kind == BUY:
        if size is None:
            reasons.append("taille d'ordre absente")
        else:
            size = float(size)
            if size <= 0:
                reasons.append("taille d'ordre nulle ou négative")
            elif size > limits.max_eur_per_order:
                reasons.append(f"taille {size:.0f} € > plafond {limits.max_eur_per_order:.0f} €")
        # Each book counts its own positions. The scanner's virtual book held 15 positions from
        # two days earlier (opened while the engine was down, never closed) and, on the night of
        # 2026-09-06, 75 of 105 T+1 orders were refused against THAT cap -- a bookkeeping collision,
        # not a market judgement. A T+1 order is capped by T+1 positions; the scanner by its own.
        mv = str(order.get("model_version") or "")
        prefix = mv.split("-")[0] + "-" if mv else ""
        if prefix:
            n_open = ctx.db.scalar("SELECT COUNT(*) FROM positions WHERE chain_id=? AND status IN ('OPEN','HALF') AND model_version LIKE ?",
                                   (ctx.chain_id, prefix + "%"), 0)
        else:
            n_open = ctx.db.scalar("SELECT COUNT(*) FROM positions WHERE chain_id=? AND status IN ('OPEN','HALF')", (ctx.chain_id,), 0)
        if n_open >= limits.max_open_positions:
            reasons.append(f"{n_open} positions ouvertes >= plafond {limits.max_open_positions}")
        n_today, eur_today = spent_today(ctx)
        if n_today >= limits.max_orders_per_day:
            reasons.append(f"{n_today} ordres passés aujourd'hui >= plafond {limits.max_orders_per_day}")
        if size is not None and eur_today + float(size) > limits.max_eur_per_day:
            reasons.append(f"{eur_today:.0f} € déjà engagés aujourd'hui, +{float(size):.0f} € dépasse {limits.max_eur_per_day:.0f} €")
        if liq is None:
            reasons.append("liquidité inconnue")  # unknown is never treated as safe
        elif float(liq) < limits.min_quote_liquidity_usd:
            reasons.append(f"liquidité {float(liq):,.0f} $ < plancher {limits.min_quote_liquidity_usd:,.0f} $")

    if slippage is None:
        reasons.append("slippage non calculé")
    elif kind == BUY and float(slippage) > limits.max_slippage_pct:
        reasons.append(f"slippage {float(slippage):.1f} % > plafond {limits.max_slippage_pct:.1f} %")
    elif kind != BUY and float(slippage) > limits.max_sell_impact_pct:
        # A sale that moves the price is expensive; a sale refused is worth zero. The exit ceiling
        # is deliberately loose and exists only to catch a pool with nothing left in it.
        reasons.append(f"impact de sortie {float(slippage):.1f} % > plafond {limits.max_sell_impact_pct:.1f} %")

    return Verdict(not reasons, reasons)
