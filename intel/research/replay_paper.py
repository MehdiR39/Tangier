"""Recompute the paper book from the recorded prices, so it measures the rule and not the engine.

On 2026-09-07 the simulated book showed -109 EUR. Forty-two of its forty-three losing lines carried
the same reason -- "invendable apres 5 essais" -- and the refusals behind them were the engine's own
faults of that morning: unknown token decimals, an entry-sized quote guard applied to an exit, an
impact ceiling meant for buying. Not one of those lines was refused by the market. A number built
from them measures the bugs, not the strategy.

This replays each such line against what the chain actually printed: entry at the recorded price,
exit at the take-profit if it was reached inside the window, otherwise at the last print inside it,
and nothing at all when the pool never printed again. It reports before it writes, and it only ever
rewrites lines whose loss came from a refusal we have since fixed.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from intel.context import IntelContext
from intel.utils.timeutil import now_ts

# Refusals that came from the engine, not from the market. Anything else is left alone.
ENGINE_FAULTS = (
    "décimales du token inconnues",
    "ordre trop gros pour une cotation fiable",
    "impact sur le prix",
    "quantité détenue inconnue",
    "actif de cotation non autorisé",
    "aucun pool utilisable",
    "dernier échange il y a",
)
FEE = 0.01
GAS = 0.02


def _bug_caused(ctx: IntelContext, position_id: int) -> str | None:
    """The engine fault that sank this line, or None when the market refused it."""
    rows = ctx.db.query(
        "SELECT COALESCE(e.refused_reason, e.error, '') w FROM decisions d "
        "JOIN executions e ON e.chain_id=d.chain_id AND e.decision_id=d.id "
        "WHERE d.chain_id=? AND d.position_id=? AND d.kind='SELL_ALL'", (ctx.chain_id, position_id))
    seen = [str(r["w"]) for r in rows if r["w"]]
    if not seen:
        return None
    for fault in ENGINE_FAULTS:
        if all(fault in w for w in seen):
            return fault
    return None


def replay(ctx: IntelContext, p: dict[str, Any], tp: float, window_s: int) -> tuple[float | None, str]:
    """(multiple actually reachable, why). None when the pool never printed again: worth nothing."""
    from intel.chain.uniswap_v4 import token_price_in_quote

    notes = dict(kv.split(":", 1) for kv in (p["notes"] or "").split() if ":" in kv)
    pool_id, quote = notes.get("pool"), notes.get("quote")
    if not pool_id or not p["entry_price"]:
        return None, "pool ou prix d'entrée inconnu"
    pair = ctx.db.query_one("SELECT token_is_currency0 FROM pairs WHERE chain_id=? AND pair_id=?", (ctx.chain_id, pool_id))
    if pair is None:
        return None, "paire inconnue"
    dec_t = ctx.db.scalar("SELECT decimals FROM tokens WHERE chain_id=? AND address=?", (ctx.chain_id, p["token_address"])) or 18
    dec_q = int((ctx.config.quote_assets.get(quote or "") or {}).get("decimals", 18))
    opened = int(p["opened_ts"])
    rows = ctx.db.query(
        "SELECT ts, sqrt_price_x96, amount0, amount1 FROM swap_events WHERE chain_id=? AND pair_id=? AND ts IS NOT NULL "
        "AND ts>=? AND ts<=? ORDER BY ts, log_index", (ctx.chain_id, pool_id, opened, opened + window_s))
    if not rows:
        return None, "aucun échange après l'entrée : rien à vendre"
    # Could anyone actually leave? On a honeypot every print is a purchase: the contract lets money
    # in and never out. Four of eight real buys on 2026-09-07 were exactly that, and a replay that
    # assumes our sale goes through would count them as winners. A window with no sale at all in it
    # is a window in which our own sale would not have gone through either.
    c0 = bool(pair["token_is_currency0"])
    sells = 0
    for r in rows:
        try:
            tok = int(r["amount0"]) if c0 else int(r["amount1"])
        except (TypeError, ValueError):
            continue
        if tok < 0:                       # v4 deltas are the user side: tokens going in is a sale
            sells += 1
    if sells == 0:
        return None, f"aucune vente possible dans la fenêtre ({len(rows)} achats, zéro vente)"
    entry = float(p["entry_price"])
    # entry_price is in dollars; the path is priced the same way through the quote's dollar price
    from intel.execution.executor import quote_price_usd
    qusd = quote_price_usd(ctx, quote or "") or 0.0
    if qusd <= 0:
        return None, "cotation non convertible"
    last = None
    for r in rows:
        try:
            px = float(token_price_in_quote(int(r["sqrt_price_x96"]), bool(pair["token_is_currency0"]), int(dec_t), dec_q)) * qusd
        except Exception:  # noqa: BLE001
            continue
        if px <= 0:
            continue
        last = px
        if px / entry >= tp:
            return tp, f"objectif ×{tp:g} atteint"
    if last is None:
        return None, "aucun prix exploitable"
    return last / entry, "fin de fenêtre"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="corriger les lignes en base (sinon: rapport seul)")
    ap.add_argument("--hours", type=int, default=24)
    args = ap.parse_args()
    ctx = IntelContext.build()
    tp = float(ctx.config.get("t1.take_profit_multiple", 2.0))
    window = int(ctx.config.get("t1.max_hold_seconds", 300))
    rows = ctx.db.query(
        "SELECT * FROM positions WHERE chain_id=? AND kind='VIRTUAL' AND model_version LIKE 't1-%' "
        "AND opened_ts>? AND (close_reason IS NULL OR close_reason NOT LIKE 'vendu%')",
        (ctx.chain_id, now_ts() - args.hours * 3600))
    before = ctx.db.scalar("SELECT COALESCE(SUM(realized_eur),0) FROM positions WHERE chain_id=? AND kind='VIRTUAL' "
                           "AND model_version LIKE 't1-%' AND opened_ts>?", (ctx.chain_id, now_ts() - args.hours * 3600), 0.0)
    fixed = kept = 0
    delta = 0.0
    per_quote: dict[str, list[float]] = {}
    for p in rows:
        fault = _bug_caused(ctx, p["id"])
        if fault is None:
            kept += 1
            continue
        mult, why = replay(ctx, dict(p), tp, window)
        size = float(p["size_eur"] or 5.0)
        old = float(p["realized_eur"] or 0.0)
        new = -size if mult is None else size * mult * (1 - FEE) - size - GAS
        notes = dict(kv.split(":", 1) for kv in (p["notes"] or "").split() if ":" in kv)
        per_quote.setdefault((notes.get("quote") or "?")[:6], []).append(new)
        delta += new - old
        fixed += 1
        if args.write:
            reason = ("rejoué : " + why) if mult is not None else ("rejoué : " + why)
            ctx.db.execute("UPDATE positions SET close_reason=?, realized_eur=?, close_price=? WHERE id=?",
                           (("vendu " if mult is not None else "") + reason, round(new, 2),
                            (float(p["entry_price"]) * mult) if (mult and p["entry_price"]) else None, p["id"]))
    print(f"lignes examinées : {len(rows)} · rejouées (échec dû au moteur) : {fixed} · laissées telles quelles : {kept}")
    print(f"carnet à blanc {args.hours} h : {before:+.2f} € avant · {before + delta:+.2f} € après correction")
    for q, vals in sorted(per_quote.items(), key=lambda kv: -len(kv[1])):
        wins = sum(1 for v in vals if v > 0)
        print(f"  cotation {q}… : {len(vals):3d} lignes · {wins:3d} gagnantes ({wins / len(vals):.0%}) · {sum(vals):+8.2f} €")
    print("écriture effectuée." if args.write else "rapport seul (ajouter --write pour corriger la base).")


if __name__ == "__main__":
    main()
