"""Where should the buy-tax ceiling sit? Replay the buys it refused and see what they were worth.

The engine asks the chain what a pool will really give for the ticket, and refuses the buy when
that is more than ``execution.max_hook_tax_pct`` below the arithmetic quote. The ceiling was set at
10 % by judgement on the first live day, and judgement is not a measurement: a token taxed 26 % that
then doubles still pays, while one taxed 5 % that dies does not.

So this takes every buy the ceiling refused, replays it on the prices the chain printed afterwards
-- entry reduced by the tax, exit at the take-profit if it came inside the window, otherwise at the
last print, nothing when nobody could sell in that window -- and reports the result per tax band.
Sold-out-of-nothing is not assumed: a window with no sale in it pays zero, the same rule the paper
book replay uses, validated on the day's four real cases.
"""
from __future__ import annotations

import argparse
import json
import re
from typing import Any

from intel.context import IntelContext
from intel.utils.timeutil import now_ts

FEE = 0.01
GAS = 0.02
TAX_RE = re.compile(r"rend ([0-9.]+) % de moins")


def outcome(ctx: IntelContext, pool_id: str, decided_block: int, tax: float, size: float,
            tp: float, window_s: int) -> tuple[float | None, str]:
    """What this refused buy would have returned, net, in euros. None when it could not be sold."""
    from intel.chain.uniswap_v4 import token_price_in_quote
    from intel.execution.executor import quote_price_usd

    pair = ctx.db.query_one("SELECT token_is_currency0, quote_address, token_address FROM pairs WHERE chain_id=? AND pair_id=?",
                            (ctx.chain_id, pool_id))
    if pair is None:
        return None, "paire inconnue"
    c0 = bool(pair["token_is_currency0"])
    quote = (pair["quote_address"] or "").lower()
    qusd = quote_price_usd(ctx, quote) or 0.0
    dec_t = ctx.db.scalar("SELECT decimals FROM tokens WHERE chain_id=? AND address=?", (ctx.chain_id, pair["token_address"])) or 18
    dec_q = int((ctx.config.quote_assets.get(quote) or {}).get("decimals", 18))
    if qusd <= 0:
        return None, "cotation non convertible"
    rows = ctx.db.query(
        "SELECT block_number, ts, sqrt_price_x96, amount0, amount1 FROM swap_events WHERE chain_id=? AND pair_id=? "
        "AND block_number>=? ORDER BY block_number, log_index", (ctx.chain_id, pool_id, decided_block))
    if len(rows) < 2:
        return None, "aucun échange après la décision"
    entry = None
    last = None
    sells = 0
    end_block = decided_block + int(window_s / 0.1)          # ~0.1 s per block on this chain
    for r in rows:
        if int(r["block_number"]) > end_block:
            break
        try:
            px = float(token_price_in_quote(int(r["sqrt_price_x96"]), c0, int(dec_t), dec_q)) * qusd
            tok = int(r["amount0"]) if c0 else int(r["amount1"])
        except (TypeError, ValueError):
            continue
        if px <= 0:
            continue
        if tok < 0:
            sells += 1
        if entry is None:
            entry = px
            continue
        last = px
        if px / entry >= tp:
            last = entry * tp
            break
    if entry is None or last is None:
        return None, "pas de prix exploitable dans la fenêtre"
    if sells == 0:
        return None, "personne n'a pu vendre dans la fenêtre"
    # the tax means we receive that much less token for the same euros, so it scales the outcome
    gross = size * (last / entry) * (1.0 - tax)
    return gross * (1 - FEE) - size - GAS, "rejoué"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hours", type=int, default=24)
    args = ap.parse_args()
    ctx = IntelContext.build()
    tp = float(ctx.config.get("t1.take_profit_multiple", 2.0))
    window = int(ctx.config.get("t1.max_hold_seconds", 300))
    rows = ctx.db.query(
        "SELECT e.refused_reason, d.metrics_json, d.size_eur FROM executions e JOIN decisions d ON d.id=e.decision_id "
        "WHERE e.chain_id=? AND e.kind='BUY' AND e.status='REFUSED' AND e.refused_reason LIKE '%taxe du hook%' AND e.ts>?",
        (ctx.chain_id, now_ts() - args.hours * 3600))
    bands: dict[str, list[float]] = {}
    unsellable: dict[str, int] = {}
    for r in rows:
        m = TAX_RE.search(r["refused_reason"] or "")
        mj = json.loads(r["metrics_json"] or "{}")
        pool, blk = mj.get("pool_id"), mj.get("decided_block")
        if not m or not pool or not blk:
            continue
        tax = float(m.group(1)) / 100.0
        band = "10-20 %" if tax < 0.20 else ("20-30 %" if tax < 0.30 else "30 % et plus")
        res, why = outcome(ctx, pool, int(blk), tax, float(r["size_eur"] or 5.0), tp, window)
        if res is None:
            unsellable[band] = unsellable.get(band, 0) + 1
            bands.setdefault(band, []).append(-float(r["size_eur"] or 5.0))
        else:
            bands.setdefault(band, []).append(res)
    if not bands:
        print("aucun achat refusé pour taxe dans la fenêtre demandée")
        return
    print(f"Achats refusés par le plafond de taxe, rejoués sur {args.hours} h "
          f"(sortie ×{tp:g} ou T+{window // 60} min) :")
    print(f"  {'taxe':<14}{'n':>4}{'gagnants':>10}{'invendables':>13}{'résultat':>12}{'par ticket':>12}")
    order = ["10-20 %", "20-30 %", "30 % et plus"]
    total: list[float] = []
    for band in order:
        vals = bands.get(band)
        if not vals:
            continue
        total += vals
        wins = sum(1 for v in vals if v > 0)
        print(f"  {band:<14}{len(vals):>4}{wins:>10}{unsellable.get(band, 0):>13}"
              f"{sum(vals):>+11.2f} €{sum(vals) / len(vals):>+11.2f} €")
    wins = sum(1 for v in total if v > 0)
    print(f"  {'ensemble':<14}{len(total):>4}{wins:>10}{sum(unsellable.values()):>13}"
          f"{sum(total):>+11.2f} €{sum(total) / len(total):>+11.2f} €")
    print()
    ceiling = float(ctx.config.get("execution.max_hook_tax_pct", 10.0))
    verdict = ("le plafond fait gagner de l'argent : ces achats auraient coûté"
               if sum(total) < 0 else "le plafond coûte de l'argent : ces achats auraient rapporté")
    print(f"Plafond actuel {ceiling:.0f} % · {verdict} {abs(sum(total)):.2f} € sur {len(total)} tickets.")


if __name__ == "__main__":
    main()
