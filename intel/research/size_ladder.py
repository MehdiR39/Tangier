"""What does a bigger ticket actually cost? Ask the chain, on the pools the book is buying now.

The book buys 5 EUR at a time and leaves 98 % of the wallet idle, so the obvious question is whether
to buy more. The obvious answer -- "impact was only a few percent" -- could not be checked: the
journal was recording the slippage TOLERANCE (8 %) in the field meant for the measured impact, so
every confirmed buy read "8.0 %" whatever really happened.

This measures it instead of estimating it. For each recently traded pool that the T+1 rule would
buy, it asks the router what several ticket sizes would really return, and reports the price paid
per euro relative to the smallest ticket. That difference IS the cost of size, hook and curve
included, at the moment the question is asked. Read-only: nothing is signed.
"""
from __future__ import annotations

import argparse
import asyncio
import time
from typing import Any

from intel.context import IntelContext
from intel.execution import orders as ord_mod
from intel.execution.executor import _amount_in_raw, chain_actual_out, choose_pool
from intel.utils.timeutil import now_ts

SIZES_EUR = (5.0, 10.0, 25.0, 50.0, 100.0)


async def ladder(ctx: IntelContext, pool: dict[str, Any], sizes: tuple[float, ...]) -> dict[float, float] | None:
    """{size in euros: tokens received per euro}, straight from the chain."""
    quote = str(pool["quote_address"]).lower()
    token = str(pool["token_address"]).lower()
    if pool.get("fee") is None or pool.get("tick_spacing") is None:
        return None
    key = ord_mod.PoolKey(currency0=pool["currency0"], currency1=pool["currency1"], fee=int(pool["fee"]),
                          tick_spacing=int(pool["tick_spacing"]), hooks=pool["hooks"] or "0x" + "00" * 20)
    zero_for_one = str(pool["currency0"]).lower() == quote
    out: dict[float, float] = {}
    for size in sizes:
        amount_in = _amount_in_raw(ctx, quote, size, 1.08)
        if not amount_in:
            return None
        order = ord_mod.build_swap(key=key, token=token, quote=quote, kind="BUY", zero_for_one=zero_for_one,
                                   amount_in=amount_in, quoted_amount_out=2, slippage_pct=50.0,
                                   router=str(ctx.config.get("execution.router")), deadline_s=300,
                                   native_quote=(quote == "0x" + "00" * 20))
        try:
            got = await chain_actual_out(ctx, order, key)
        except Exception:  # noqa: BLE001
            got = None
        if not got:
            return None
        out[size] = got / size
    return out


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pools", type=int, default=6)
    ap.add_argument("--minutes", type=int, default=30)
    args = ap.parse_args()
    ctx = IntelContext.build()
    rows = ctx.db.query(
        "SELECT DISTINCT p.pair_id, p.token_address, p.quote_address, p.currency0, p.currency1, p.fee, p.tick_spacing, p.hooks "
        "FROM pairs p JOIN swap_events s ON s.pair_id=p.pair_id WHERE p.chain_id=? AND lower(p.quote_address)=? "
        "AND (p.hooks IS NULL OR p.hooks='0x' || '00'*20 OR p.hooks='0x0000000000000000000000000000000000000000') "
        "AND s.ts>? GROUP BY p.pair_id ORDER BY MAX(s.ts) DESC LIMIT ?",
        (ctx.chain_id, "0x" + "00" * 20, now_ts() - args.minutes * 60, args.pools))
    print(f"Coût réel d'un ticket plus gros, mesuré maintenant sur {len(rows)} pools que la règle achèterait")
    print(f"(prix payé par euro, en % de moins qu'un ticket de {SIZES_EUR[0]:.0f} €)\n")
    header = "  pool        " + "".join(f"{s:>9.0f} €" for s in SIZES_EUR[1:])
    print(header)
    agg: dict[float, list[float]] = {s: [] for s in SIZES_EUR[1:]}
    for r in rows:
        res = await ladder(ctx, dict(r), SIZES_EUR)
        if not res:
            continue
        base = res[SIZES_EUR[0]]
        cells = []
        for s in SIZES_EUR[1:]:
            loss = (1.0 - res[s] / base) * 100.0
            agg[s].append(loss)
            cells.append(f"{loss:>9.1f} %")
        print(f"  {r['pair_id'][:10]}  " + "".join(cells))
    print()
    if any(agg.values()):
        print("  " + "moyenne".ljust(12) + "".join(f"{sum(v) / len(v):>9.1f} %" if v else f"{'—':>11}" for v in agg.values()))
        print()
        ev5 = float(ctx.config.get("t1.ev_per_ticket_eur", 1.30))
        print(f"Lecture : à {SIZES_EUR[0]:.0f} € l'espérance mesurée est de {ev5:+.2f} € par ticket, soit {ev5 / SIZES_EUR[0] * 100:.0f} % de la mise.")
        for s in SIZES_EUR[1:]:
            v = agg[s]
            if not v:
                continue
            cost = sum(v) / len(v)
            rate = ev5 / SIZES_EUR[0] * 100 - cost
            print(f"  à {s:>5.0f} € : coût de taille {cost:>5.1f} % → rendement attendu {rate:>5.1f} % "
                  f"= {rate / 100 * s:+.2f} € par ticket" + ("  (au-dessus de 5 €)" if rate / 100 * s > ev5 else ""))

if __name__ == "__main__":
    asyncio.run(main())
