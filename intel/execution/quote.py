"""Price a swap from the pool's own state, using exact Uniswap v4 tick math.

Why not a Quoter contract: none is deployed on this chain that we could verify, and an unverified
address is not something to route orders through. The pool publishes everything needed on every
trade — ``sqrtPriceX96`` and the in-range liquidity ride along with each Swap event — so the
quote is computed from the last observed state of the pool itself.

The one assumption, stated plainly: the swap is assumed not to cross a tick boundary. For an
order worth a few tens of euros against a pool holding tens of thousands of dollars, the price
moves far less than one tick, and ``max_order_fraction_of_liquidity`` refuses anything larger.
The on-chain minimum output remains the real protection either way.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from intel.context import IntelContext
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)

Q96 = 2 ** 96


@dataclass(frozen=True)
class Quote:
    amount_out: int
    price_impact_pct: float
    state_age_s: int
    liquidity: int
    sqrt_price_x96: int
    reasons: list[str]

    @property
    def usable(self) -> bool:
        return self.amount_out > 0 and not self.reasons


def _next_sqrt_price_from_amount0(sqrt_p: int, liquidity: int, amount: int) -> int:
    """Price after spending ``amount`` of currency0 (price falls)."""
    if amount == 0:
        return sqrt_p
    numerator = liquidity * Q96
    denominator = numerator + amount * sqrt_p
    return (numerator * sqrt_p + denominator - 1) // denominator  # round up, as the pool does


def _next_sqrt_price_from_amount1(sqrt_p: int, liquidity: int, amount: int) -> int:
    """Price after spending ``amount`` of currency1 (price rises)."""
    return sqrt_p + (amount * Q96) // liquidity


def _amount0_delta(sqrt_a: int, sqrt_b: int, liquidity: int) -> int:
    if sqrt_a > sqrt_b:
        sqrt_a, sqrt_b = sqrt_b, sqrt_a
    return (liquidity * Q96 * (sqrt_b - sqrt_a)) // (sqrt_b * sqrt_a)


def _amount1_delta(sqrt_a: int, sqrt_b: int, liquidity: int) -> int:
    if sqrt_a > sqrt_b:
        sqrt_a, sqrt_b = sqrt_b, sqrt_a
    return (liquidity * (sqrt_b - sqrt_a)) // Q96


def quote_exact_in(*, sqrt_price_x96: int, liquidity: int, zero_for_one: bool, amount_in: int, fee_pips: int) -> int:
    """Output of an exact-input swap that stays inside the current tick, fee deducted first."""
    if amount_in <= 0 or liquidity <= 0 or sqrt_price_x96 <= 0:
        return 0
    after_fee = amount_in - (amount_in * fee_pips) // 1_000_000
    if after_fee <= 0:
        return 0
    if zero_for_one:
        nxt = _next_sqrt_price_from_amount0(sqrt_price_x96, liquidity, after_fee)
        return max(0, _amount1_delta(nxt, sqrt_price_x96, liquidity))
    nxt = _next_sqrt_price_from_amount1(sqrt_price_x96, liquidity, after_fee)
    return max(0, _amount0_delta(sqrt_price_x96, nxt, liquidity))


def price_impact_pct(*, sqrt_price_x96: int, liquidity: int, zero_for_one: bool, amount_in: int, fee_pips: int) -> float:
    """How far this order moves the pool price, in percent."""
    out = quote_exact_in(sqrt_price_x96=sqrt_price_x96, liquidity=liquidity, zero_for_one=zero_for_one,
                         amount_in=amount_in, fee_pips=fee_pips)
    if out <= 0:
        return 100.0
    after_fee = amount_in - (amount_in * fee_pips) // 1_000_000
    nxt = (_next_sqrt_price_from_amount0(sqrt_price_x96, liquidity, after_fee) if zero_for_one
           else _next_sqrt_price_from_amount1(sqrt_price_x96, liquidity, after_fee))
    p0, p1 = (sqrt_price_x96 / Q96) ** 2, (nxt / Q96) ** 2
    return abs(p1 / p0 - 1.0) * 100.0 if p0 else 100.0


def latest_pool_state(ctx: IntelContext, pool_id: str) -> dict[str, Any] | None:
    """The pool state carried by its most recent Swap event."""
    return ctx.db.query_one(
        "SELECT sqrt_price_x96, liquidity, ts, block_number FROM swap_events "
        "WHERE chain_id=? AND pair_id=? AND sqrt_price_x96 IS NOT NULL ORDER BY block_number DESC LIMIT 1",
        (ctx.chain_id, pool_id),
    )


def quote_from_pool(ctx: IntelContext, *, pool_id: str, zero_for_one: bool, amount_in: int, fee_pips: int,
                    max_state_age_s: int = 900, max_impact_pct: float = 3.0,
                    max_order_fraction: float = 0.02) -> Quote:
    """Quote an order against the last observed state of one pool, refusing when that is unsafe."""
    row = latest_pool_state(ctx, pool_id)
    if row is None:
        return Quote(0, 100.0, 10 ** 9, 0, 0, ["état du pool inconnu"])
    sqrt_p = int(row["sqrt_price_x96"] or 0)
    liq = int(row["liquidity"] or 0)
    age = now_ts() - int(row["ts"] or 0)
    reasons: list[str] = []
    if liq <= 0 or sqrt_p <= 0:
        reasons.append("pool sans liquidité en portée")
    if age > max_state_age_s:
        reasons.append(f"dernier échange il y a {age // 60} min (> {max_state_age_s // 60} min)")
    out = quote_exact_in(sqrt_price_x96=sqrt_p, liquidity=liq, zero_for_one=zero_for_one, amount_in=amount_in, fee_pips=fee_pips)
    impact = price_impact_pct(sqrt_price_x96=sqrt_p, liquidity=liq, zero_for_one=zero_for_one, amount_in=amount_in, fee_pips=fee_pips)
    if out <= 0:
        reasons.append("sortie estimée nulle")
    if impact > max_impact_pct:
        reasons.append(f"impact sur le prix {impact:.1f} % > {max_impact_pct:.1f} %")
    # Beyond a small fraction of the book the single-tick assumption stops holding, so the quote
    # would be optimistic exactly when it matters most. The book is measured on the side we pay
    # with: L/sqrtP of currency0, L*sqrtP of currency1. Comparing the raw amount to L itself
    # (2026-09-07) refused every sale of a low-priced token -- 1e25 raw units against an L of
    # 1e21 -- at 0.1 % of impact, while the entry had been quoted through the same pool.
    if liq > 0 and sqrt_p > 0:
        ratio = sqrt_p / (2 ** 96)
        side_reserve = (liq / ratio) if zero_for_one else (liq * ratio)
        if amount_in > side_reserve * max_order_fraction:
            reasons.append("ordre trop gros pour une cotation fiable sur un seul palier")
    return Quote(out, impact, age, liq, sqrt_p, reasons)
