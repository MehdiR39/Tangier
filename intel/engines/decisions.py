"""Decision layer: turn states into ACHÈTE / VENDS messages on a virtual position book.

The engine watches; the user only hears about decisions. Rules (config ``decisions``):
- BUY (scanner token): action CANDIDATE, state in ``buy_states``, moonshot ≥ ``min_moonshot_buy``,
  security not FAIL, no open position, fewer than ``max_open`` open positions.
- SELL ALL (held token): THESIS_BREAK, confirmed SECURITY_RISK, liquidity −``liquidity_drop_sell``
  in 24h, or price below entry × (1 − ``stop_loss``).
- TAKE PROFIT (held token): price ≥ entry × ``take_profit_multiple`` sells the WHOLE position.
  Keeping half was measured on 2026-09-04 to turn a mean of +4.2 % into -39.5 %: 91 % of these
  tokens stop trading after the move, so the kept half can no longer be sold at any price.
- SELL HALF: DISTRIBUTION only. After a half exit, a trailing stop of ``trailing_stop`` closes it.
Positions are virtual (no execution). User-held tokens are tracked as PORTFOLIO positions whose
entry is the first observed price (the real cost basis is unknown unless configured).
"""
from __future__ import annotations

import html
import json
import logging
from typing import Any

from intel import MODEL_VERSION
from intel.context import IntelContext
from intel.engines.carnet import SCANNER_SQL
from intel.scoring.scores import Scores
from intel.scoring.states import StateDecision
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)


def _usd(v: float | None) -> str:
    if v is None:
        return "?"
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1_000_000:
        return f"{sign}{a / 1_000_000:.2f} M$".replace(".", ",")
    if a >= 1_000:
        return f"{sign}{a / 1_000:.0f} k$"
    return f"{sign}{a:,.0f} $".replace(",", " ")


def _price(v: float | None) -> str:
    if v is None:
        return "?"
    return (f"{v:,.2f}" if v >= 1 else f"{v:.6f}".rstrip("0").rstrip(".")) + " $"


def open_position(ctx: IntelContext, token: str) -> dict[str, Any] | None:
    # The T+1 book keeps its own positions (model_version t1-...) with its own five-minute exit.
    # The scanner's rules applied to one of them on 2026-09-07 ("-89 % depuis son plus haut") and
    # would emit competing sells; that book is invisible here. Same for the Solana and manual
    # books: on 2026-09-10 03:06 the scanner adopted the operator's manual DOGSHIT line and closed
    # it (§5.24). The scanner sees its own lines only -- see intel/engines/carnet.py.
    r = ctx.db.query_one(
        "SELECT * FROM positions WHERE chain_id=? AND token_address=? AND status IN ('OPEN','HALF') "
        "AND " + SCANNER_SQL + " ORDER BY id DESC LIMIT 1", (ctx.chain_id, token))
    return dict(r) if r else None


def ensure_portfolio_position(ctx: IntelContext, token: str, label: str, price: float | None, cfg_position: dict[str, Any] | None, *, state: str | None = None, cooldown: int = 3 * 86400) -> dict[str, Any] | None:
    pos = open_position(ctx, token)
    if pos or price is None:
        return pos
    # A position the engine already told the user to exit must not be silently re-opened
    # (that re-triggered the same sell every cycle on 2026-09-03). Re-open only after the
    # cooldown AND once the token is back in a non-negative state.
    last_closed = ctx.db.query_one("SELECT closed_ts FROM positions WHERE chain_id=? AND token_address=? AND status='CLOSED' "
                                   "AND " + SCANNER_SQL + " ORDER BY closed_ts DESC LIMIT 1", (ctx.chain_id, token))
    if last_closed and last_closed["closed_ts"]:
        if now_ts() - int(last_closed["closed_ts"]) < cooldown:
            return None
        if state in ("THESIS_BREAK", "SECURITY_RISK", "DISTRIBUTION", "EXTENDED", "REJECTED"):
            return None
    entry = None
    notes = "entrée = premier prix observé (coût réel inconnu)"
    if cfg_position and cfg_position.get("cost_basis_usd") and cfg_position.get("quantity"):
        entry = float(cfg_position["cost_basis_usd"]) / float(cfg_position["quantity"])
        notes = "entrée = coût réel configuré"
    ctx.db.insert("positions", {
        "chain_id": ctx.chain_id, "token_address": token, "label": label, "kind": "PORTFOLIO", "opened_ts": now_ts(), "entry_price": entry or price,
        "size_eur": None, "status": "OPEN", "peak_price": price, "model_version": MODEL_VERSION, "notes": notes,
    })
    return open_position(ctx, token)


def _update_peak(ctx: IntelContext, pos: dict[str, Any], price: float | None) -> None:
    if price is not None and (pos.get("peak_price") is None or price > pos["peak_price"]):
        ctx.db.execute("UPDATE positions SET peak_price=? WHERE id=?", (price, pos["id"]))
        pos["peak_price"] = price


def evaluate_decisions(ctx: IntelContext, *, token: str, label: str, m: dict[str, Any], scores: Scores, decision: StateDecision, is_portfolio: bool, cfg_position: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return the decisions to announce (already persisted); empty when nothing to do."""
    cfg = ctx.config.section("decisions")
    if not cfg.get("enabled", True):
        return []
    price = m.get("price_usd")
    liq = m.get("liquidity", {})
    sec = m.get("security") or {}
    out: list[dict[str, Any]] = []
    ts = now_ts()
    cooldown = int(cfg.get("rebuy_cooldown_seconds", 3 * 86400))
    pos = ensure_portfolio_position(ctx, token, label, price, cfg_position, state=decision.state, cooldown=int(cfg.get("portfolio_reopen_cooldown_seconds", 12 * 3600))) if is_portfolio else open_position(ctx, token)
    # safety net independent of the book: never repeat the same decision kind for a token within 24h
    last_kind = ctx.db.query_one("SELECT kind, ts FROM decisions WHERE chain_id=? AND token_address=? ORDER BY id DESC LIMIT 1", (ctx.chain_id, token))

    def repeated(kind: str) -> bool:
        return bool(last_kind and last_kind["kind"] == kind and ts - int(last_kind["ts"]) < int(cfg.get("repeat_guard_seconds", 86400)))

    if pos:
        _update_peak(ctx, pos, price)
        entry = pos.get("entry_price")
        ret = (price / entry - 1.0) if (price and entry) else None
        peak = pos.get("peak_price")
        from_peak = (price / peak - 1.0) if (price and peak) else None
        sell_all: str | None = None
        sell_half: str | None = None
        # A "thesis break" that rests only on the distance to an all-time high reached BEFORE we
        # started following the position is not a sell signal (TAIWAN, 2026-09-03: the ATH was the
        # launch spike two days before the position existed). Use the peak since entry instead.
        ath_ts = (m.get("ath") or {}).get("ath_ts")
        codes = set(getattr(decision, "codes", []) or [])
        stale_ath_only = codes == {"drawdown_ath"} and (ath_ts is None or int(ath_ts) < int(pos.get("opened_ts") or 0))
        if decision.state == "THESIS_BREAK" and not stale_ath_only:
            sell_all = f"thèse cassée : {decision.reason}"
        elif from_peak is not None and from_peak <= -float(cfg.get("peak_drawdown_sell", 0.7)):
            sell_all = f"le prix a perdu {abs(from_peak) * 100:.0f} % depuis son plus haut sous suivi"
        elif decision.state == "SECURITY_RISK" and sec.get("fails"):
            sell_all = f"risque sur le contrat : {decision.reason}"
        elif liq.get("liquidity_change_24h") is not None and liq["liquidity_change_24h"] <= -float(cfg.get("liquidity_drop_sell", 0.5)):
            sell_all = f"la liquidité a perdu {abs(liq['liquidity_change_24h']) * 100:.0f} % en 24 h"
        elif ret is not None and ret <= -float(cfg.get("stop_loss", 0.5)):
            sell_all = f"stop de protection : {ret * 100:+.0f} % depuis l'entrée"
        elif pos["status"] == "HALF" and from_peak is not None and from_peak <= -float(cfg.get("trailing_stop", 0.70)):
            sell_all = f"le reste de la position rend {abs(from_peak) * 100:.0f} % depuis son plus haut"
        elif pos["kind"] == "VIRTUAL" and cfg.get("timeout_hours") and (ts - int(pos["opened_ts"])) >= float(cfg["timeout_hours"]) * 3600:
            sell_all = f"position ouverte depuis {float(cfg['timeout_hours']):.0f} h sans issue : on libère la ligne"
        elif decision.state == "DISTRIBUTION" and pos["status"] == "OPEN":
            sell_half = f"les gros porteurs vendent : {decision.reason}"
        elif ret is not None and ret >= float(cfg.get("take_profit_multiple", 1.5)) - 1.0 and pos["status"] == "OPEN":
            # Everything, not half. Measured 2026-09-04 on 381 tokens: keeping half turns a mean of
            # +4.2 % into -39.5 %, because 91 % of these tokens stop trading afterwards and the
            # kept half cannot be sold at all. Letting a runner run needs a market to run in.
            tp = float(cfg.get("take_profit_multiple", 1.5))
            if bool(cfg.get("take_profit_sells_all", True)):
                sell_all = f"objectif x{tp:g} atteint ({ret * 100:+.0f} %) : on prend tout pendant qu'il y a des acheteurs"
            else:
                sell_half = f"objectif x{tp:g} atteint ({ret * 100:+.0f} %) : on récupère la mise, le reste court"
        if sell_all and repeated("SELL_ALL"):
            log.warning("decision SELL_ALL for %s suppressed by repeat guard", label)
            ctx.db.execute("UPDATE positions SET status='CLOSED', closed_ts=?, close_price=?, close_reason=? WHERE id=?", (ts, price, sell_all + " (répétition, non envoyée)", pos["id"]))
            return out
        if sell_half and repeated("SELL_HALF"):
            log.warning("decision SELL_HALF for %s suppressed by repeat guard", label)
            return out
        if sell_all:
            realized = None
            if pos.get("size_eur") and entry and price:
                remaining = 1.0 if pos["status"] == "OPEN" else 0.5
                realized = pos["size_eur"] * remaining * (price / entry) + (pos["size_eur"] * 0.5 * (pos["half_price"] / entry) if pos["status"] == "HALF" and pos.get("half_price") else 0.0) - pos["size_eur"]
            ctx.db.execute("UPDATE positions SET status='CLOSED', closed_ts=?, close_price=?, close_reason=?, realized_eur=? WHERE id=?", (ts, price, sell_all, realized, pos["id"]))
            out.append(_record(ctx, token, label, "SELL_ALL", sell_all, price, pos.get("size_eur"), pos["id"], m, ret))
        elif sell_half:
            ctx.db.execute("UPDATE positions SET status='HALF', half_ts=?, half_price=? WHERE id=?", (ts, price, pos["id"]))
            out.append(_record(ctx, token, label, "SELL_HALF", sell_half, price, (pos.get("size_eur") or 0) / 2 or None, pos["id"], m, ret))
        return out

    # no position: buy?
    if is_portfolio:
        return out
    if decision.action != "CANDIDATE" or decision.state not in set(cfg.get("buy_states", ["ACCUMULATION", "EARLY_ACCUMULATION", "BREAKOUT_CONFIRMED"])):
        return out
    if scores.moonshot < float(cfg.get("min_moonshot_buy", 70)) or sec.get("fails") or price is None:
        return out
    from intel.metrics.regime import buying_allowed

    allowed, why_market = buying_allowed(ctx)
    if not allowed:
        log.info("achat de %s bloqué : %s", label, why_market)
        return out
    # kind='PORTFOLIO' : un plafond sur les positions REELLES ne compte pas le papier. Sans ce
    # filtre le compte incluait 14 lignes VIRTUAL et 2 lignes d observation sans mise, soit 16
    # pour un plafond de 15 : le carnet reel etait sature par des simulations et n aurait plus
    # rien achete a sa reactivation, sans qu aucun message ne le dise (§5.18).
    n_open = ctx.db.scalar("SELECT COUNT(*) FROM positions WHERE chain_id=? AND kind='PORTFOLIO' "
                           "AND status IN ('OPEN','HALF')", (ctx.chain_id,), 0)
    if n_open >= int(cfg.get("max_open", 15)):
        return out
    recent = ctx.db.query_one("SELECT 1 FROM positions WHERE chain_id=? AND token_address=? AND closed_ts>? "
                              "AND " + SCANNER_SQL + " LIMIT 1", (ctx.chain_id, token, ts - cooldown))
    if recent or repeated("BUY"):
        return out
    size = float(cfg.get("size_eur", 20.0))
    pid = ctx.db.insert("positions", {"chain_id": ctx.chain_id, "token_address": token, "label": label, "kind": "VIRTUAL", "opened_ts": ts, "entry_price": price, "size_eur": size, "status": "OPEN", "peak_price": price, "model_version": MODEL_VERSION, "notes": decision.reason})
    rec = _record(ctx, token, label, "BUY", decision.reason, price, size, pid, m, None)
    rec["plan"] = {"take_profit": float(cfg.get("take_profit_multiple", 1.5)), "timeout_h": float(cfg.get("timeout_hours", 3)),
                   "sells_all": bool(cfg.get("take_profit_sells_all", True))}
    out.append(rec)
    return out


def _record(ctx: IntelContext, token: str, label: str, kind: str, reason: str, price: float | None, size: float | None, pid: int | None, m: dict[str, Any], ret: float | None) -> dict[str, Any]:
    slim = {"market_cap": m.get("market_cap"), "liquidity_usd": m.get("liquidity_usd"), "holders": (m.get("holders") or {}).get("holder_count"), "ret_since_entry": ret, "returns": m.get("returns"), "security": (m.get("security") or {}).get("overall")}
    did = ctx.db.insert("decisions", {"ts": now_ts(), "chain_id": ctx.chain_id, "token_address": token, "label": label, "kind": kind, "reason": reason, "price": price, "size_eur": size, "position_id": pid, "sent": 0, "metrics_json": json.dumps(slim, default=str), "model_version": MODEL_VERSION})
    pos = ctx.db.query_one("SELECT kind, opened_ts, notes FROM positions WHERE id=?", (pid,)) if pid else None
    ref_note = None
    if pos and pos["kind"] == "PORTFOLIO" and "inconnu" in (pos["notes"] or ""):
        ref_note = "référence : prix du " + __import__("datetime").datetime.fromtimestamp(int(pos["opened_ts"]), __import__("datetime").timezone.utc).strftime("%d/%m") + ", ton prix d'achat réel est inconnu"
    return {"id": did, "token": token, "label": label, "kind": kind, "reason": reason, "price": price, "size_eur": size, "metrics": slim, "ret": ret, "ref_note": ref_note}


def _since_entry(d: dict[str, Any]) -> str:
    """'(+12 % depuis l'achat conseillé)' for virtual lines; nothing when the reference is today's price."""
    ret = d.get("ret")
    if ret is None or d.get("ref_note") or abs(ret) < 0.005:
        return ""
    return f" ({ret * 100:+.0f} % depuis l'achat conseillé)"


def format_decision(d: dict[str, Any], token_url: str | None = None) -> str:
    e = lambda s: html.escape(str(s), quote=False)  # noqa: E731
    met = d.get("metrics") or {}
    r = met.get("returns") or {}
    lines: list[str] = []
    if d["kind"] == "BUY":
        lines.append(f"🟢 <b>ACHÈTE {e(d['label'])} — {d['size_eur']:.0f} €</b>")
        lines.append(f"Prix : {_price(d['price'])} · Capitalisation : {_usd(met.get('market_cap'))} · Liquidité : {_usd(met.get('liquidity_usd'))} · Holders : {met.get('holders') or '?'}")
        lines.append(f"<b>Pourquoi :</b> {e(d['reason'])}")
        # The plan is stated with the numbers that were in force when the advice was given, so a
        # message can never promise an exit the engine does not make.
        plan = d.get("plan") or {}
        tp, to = plan.get("take_profit", 1.5), plan.get("timeout_h", 3.0)
        what = "on vend TOUT" if plan.get("sells_all", True) else "on vend la moitié"
        lines.append(f"<b>Plan de sortie :</b> je te dis quand vendre. À x{tp:g}, {what} — sur ce marché "
                     f"garder le reste coûte plus que ça ne rapporte. Sortie aussi si la liquidité part, si les gros "
                     f"porteurs vendent massivement, si le contrat devient risqué, ou après {to:g} h sans issue.")
    elif d["kind"] == "SELL_HALF":
        lines.append(f"🟠 <b>VENDS LA MOITIÉ de {e(d['label'])}</b>")
        lines.append(f"Prix : {_price(d['price'])}" + _since_entry(d) + f" · Liquidité : {_usd(met.get('liquidity_usd'))}")
        lines.append(f"<b>Pourquoi :</b> {e(d['reason'])}")
        lines.append("Je te dirai quand vendre le reste.")
    else:
        lines.append(f"🔴 <b>VENDS TOUT {e(d['label'])}</b>")
        r24 = r.get("return_24h")
        lines.append(f"Prix : {_price(d['price'])}" + _since_entry(d) + f" · Liquidité : {_usd(met.get('liquidity_usd'))}" + (f" · {r24 * 100:+.0f} % sur 24 h" if r24 is not None else ""))
        lines.append(f"<b>Pourquoi :</b> {e(d['reason'])}")
    if d.get("ref_note"):
        lines.append(f"<i>{e(d['ref_note'])}</i>")
    if token_url:
        lines.append(f'<a href="{e(token_url)}">graphique</a> · <code>{e(d["token"])}</code>')
    return "\n".join(lines)


async def dispatch_decisions(ctx: IntelContext, sender: Any, decisions: list[dict[str, Any]]) -> int:
    sent = 0
    for d in decisions:
        url = f"https://dexscreener.com/{ctx.settings.dexscreener_chain}/{d['token']}"
        body = format_decision(d, url)
        ok, mid, err = (await sender.send(body)) if sender else (False, None, "no sender")
        ctx.db.execute("UPDATE decisions SET sent=?, telegram_message_id=?, send_error=? WHERE id=?", (int(ok), mid, err, d["id"]))
        sent += int(ok)
    return sent


def book_summary(ctx: IntelContext) -> dict[str, Any]:
    """Virtual book P&L for the digest (open positions marked at the latest price)."""
    rows = [dict(r) for r in ctx.db.query("SELECT * FROM positions WHERE chain_id=? ORDER BY opened_ts", (ctx.chain_id,))]
    out: list[dict[str, Any]] = []
    total_realized = 0.0
    total_unrealized = 0.0
    for p in rows:
        last = ctx.db.scalar("SELECT price_usd FROM token_snapshots WHERE chain_id=? AND token_address=? AND price_usd IS NOT NULL ORDER BY ts DESC LIMIT 1", (ctx.chain_id, p["token_address"]))
        ret = (last / p["entry_price"] - 1.0) if (last and p.get("entry_price")) else None
        unreal = None
        if p["status"] != "CLOSED" and p.get("size_eur") and ret is not None:
            frac = 1.0 if p["status"] == "OPEN" else 0.5
            unreal = p["size_eur"] * frac * ret
            total_unrealized += unreal
        if p.get("realized_eur") is not None:
            total_realized += p["realized_eur"]
        out.append({"label": p["label"], "kind": p["kind"], "status": p["status"], "ret": ret, "unrealized_eur": unreal, "realized_eur": p.get("realized_eur"), "opened_ts": p["opened_ts"], "close_reason": p.get("close_reason")})
    return {"positions": out, "realized_eur": total_realized, "unrealized_eur": total_unrealized, "n_open": sum(1 for p in out if p["status"] != "CLOSED")}
