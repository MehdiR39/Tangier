"""Daily digest: one Telegram message per day, written for a non-technical French reader.

Sections: your tokens (what to do, in words) → decisions of the last 24 h and what the price
did since → virtual book → what the scanner is watching (not buys) → outcome of past alerts →
one engine health line. No developer codes, no addresses.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import logging
from typing import Any

from intel import MODEL_VERSION
from intel.alerts.labels import action_fr, state_fr
from intel.context import IntelContext
from intel.engines.carnet import SCANNER_SQL
from intel.metrics.launch import launch_history_complete
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)
PARIS_OFFSET_HOURS = 2  # CEST; good enough for a morning stamp (the engine runs in UTC)


def _usd(v: float | None) -> str:
    if v is None:
        return "?"
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1_000_000:
        return f"{sign}{a / 1_000_000:.2f} M$".replace(".", ",")
    if a >= 1_000:
        return f"{sign}{a / 1_000:.0f} k$"
    return f"{sign}{a:,.0f} $".replace(",", " ")


def _pct(v: float | None) -> str:
    return "?" if v is None else f"{v * 100:+.0f} %"


def _n(v: int | None) -> str:
    return "?" if v is None else f"{v:,}".replace(",", " ")


def _hm(ts: int) -> str:
    return (dt.datetime.fromtimestamp(int(ts), dt.timezone.utc) + dt.timedelta(hours=PARIS_OFFSET_HOURS)).strftime("%d/%m %Hh%M")


def _latest_metrics(ctx: IntelContext, token: str) -> dict[str, Any]:
    row = ctx.db.query_one("SELECT metrics_json, ts FROM token_scores WHERE chain_id=? AND token_address=? ORDER BY ts DESC LIMIT 1", (ctx.chain_id, token))
    if not row or not row["metrics_json"]:
        return {}
    try:
        m = json.loads(row["metrics_json"])
        m["_score_ts"] = int(row["ts"])
        return m
    except Exception:
        return {}


def _latest_price(ctx: IntelContext, token: str) -> float | None:
    return ctx.db.scalar("SELECT price_usd FROM token_snapshots WHERE chain_id=? AND token_address=? AND price_usd IS NOT NULL ORDER BY ts DESC LIMIT 1", (ctx.chain_id, token))


ADVICE_FR = {
    "HOLD": "GARDER",
    "REVIEW_EXIT": "ENVISAGER LA SORTIE",
    "DO_NOT_ADD": "GARDER, NE PAS RENFORCER",
    "WATCH": "GARDER",
}


def build_digest(ctx: IntelContext) -> str:
    now = now_ts()
    stamp = (dt.datetime.fromtimestamp(now, dt.timezone.utc) + dt.timedelta(hours=PARIS_OFFSET_HOURS)).strftime("%d/%m à %Hh%M")
    e = lambda s: html.escape(str(s), quote=False)  # noqa: E731
    lines = [f"<b>📊 Résumé du matin — {e(stamp)}</b>", ""]
    try:
        from intel.metrics.regime import buying_allowed, cached_regime

        regime = cached_regime(ctx)
        allowed, _why = buying_allowed(ctx)
        if not allowed:  # only shown when it actually changes something (switch is off by default)
            label_fr = {"bear": "marché baissier"}
            lines.append(f"<b>⚠️ Achats suspendus</b> : {e(label_fr.get(regime, regime))}")
            lines.append("")
    except Exception as exc:  # noqa: BLE001
        log.warning("regime line failed: %s", exc)

    # ---- your tokens ------------------------------------------------------ #
    lines.append("<b>Tes tokens</b>")
    rows = ctx.db.query(
        "SELECT p.label, p.token_address, s.state, s.action, s.moonshot, s.reason, s.last_eval_ts FROM portfolio_positions p LEFT JOIN token_states s ON s.chain_id=p.chain_id AND s.token_address=p.token_address WHERE p.chain_id=? AND p.active=1 ORDER BY p.label",
        (ctx.chain_id,),
    )
    if not rows:
        lines.append("• aucune position configurée")
    for r in rows:
        label = r["label"] or r["token_address"][:10]
        if r["state"] is None:
            lines.append(f"• <b>{e(label)}</b> — première analyse en cours")
            continue
        m = _latest_metrics(ctx, r["token_address"])
        ret = m.get("returns", {})
        h = m.get("holders", {})
        pos = ctx.db.query_one("SELECT status, kind FROM positions WHERE chain_id=? AND token_address=? AND " + SCANNER_SQL + " ORDER BY id DESC LIMIT 1", (ctx.chain_id, r["token_address"]))
        advice = ADVICE_FR.get(r["action"] or "", action_fr(r["action"]))
        if pos and pos["status"] == "HALF":
            advice = "GARDER LE RESTE (moitié vendue)"
        elif pos and pos["status"] == "CLOSED" and r["state"] in ("THESIS_BREAK", "SECURITY_RISK"):
            advice = "SORTIE CONSEILLÉE, toujours en danger"
        sec = (m.get("security") or {}).get("overall")
        sec_txt = {"PASS": "contrat sain", "WARN": "contrat avec avertissements", "FAIL": "CONTRAT À RISQUE", "UNKNOWN": "contrat non vérifié"}.get(sec or "", "contrat non vérifié")
        hist = "" if launch_history_complete(ctx, r["token_address"]) else " · historique encore en cours"
        lines.append(f"• <b>{e(label)} — {e(advice)}</b> · {e(state_fr(r['state']))}")
        lines.append(f"   {_pct(ret.get('return_24h'))} sur 24 h · capitalisation {_usd(m.get('market_cap'))} · liquidité {_usd(m.get('liquidity_usd'))} · {_n(h.get('holder_count'))} holders · {e(sec_txt)}{e(hist)}")
    lines.append("")

    # ---- decisions of the last 24 h --------------------------------------- #
    decs = ctx.db.query("SELECT ts, kind, label, reason, price, token_address FROM decisions WHERE chain_id=? AND sent=1 AND ts>? ORDER BY ts", (ctx.chain_id, now - 86400))
    lines.append("<b>Conseils envoyés ces dernières 24 h</b>")
    if not decs:
        lines.append("• aucun : rien n'a justifié d'acheter ou de vendre")
    kind_fr = {"BUY": "ACHÈTE", "SELL_ALL": "VENDS TOUT", "SELL_HALF": "VENDS LA MOITIÉ"}
    for d in decs:
        p_now = _latest_price(ctx, d["token_address"])
        since = (p_now / d["price"] - 1.0) if (p_now and d["price"]) else None
        lines.append(f"• {e(_hm(d['ts']))} — {e(kind_fr.get(d['kind'], d['kind']))} {e(d['label'])} · depuis : {_pct(since)}")
    lines.append("")

    # ---- virtual book ------------------------------------------------------ #
    try:
        from intel.engines.decisions import book_summary

        book = book_summary(ctx)
        virtual_open = [p for p in book["positions"] if p["status"] != "CLOSED" and p["kind"] == "VIRTUAL"]
        virtual_closed = [p for p in book["positions"] if p["status"] == "CLOSED" and p["kind"] == "VIRTUAL"]
        lines.append("<b>Carnet virtuel (20 € par achat conseillé)</b>")
        if not virtual_open and not virtual_closed:
            lines.append("• aucun achat conseillé pour l'instant : aucun nouveau token n'a réuni toutes les conditions")
        for p in virtual_open:
            lines.append(f"• {e(p['label'])} : {_pct(p['ret'])} depuis l'achat conseillé" + (" (moitié vendue)" if p["status"] == "HALF" else ""))
        if virtual_closed:
            lines.append(f"• {len(virtual_closed)} ligne(s) soldée(s) : {sum((p.get('realized_eur') or 0) for p in virtual_closed):+.0f} €")
        if virtual_open:
            lines.append(f"<i>latent {book['unrealized_eur']:+.0f} € sur {len(virtual_open)} ligne(s)</i>")
        lines.append("")
    except Exception as exc:  # noqa: BLE001
        log.warning("book summary failed: %s", exc)

    # ---- scanner watchlist ------------------------------------------------- #
    lines.append("<b>Ce que le scanner regarde de près (pas des achats)</b>")
    cands = ctx.db.query(
        "SELECT c.token_address, t.symbol, s.state, s.action, s.moonshot FROM scanner_candidates c JOIN token_states s ON s.chain_id=c.chain_id AND s.token_address=c.token_address "
        "LEFT JOIN tokens t ON t.chain_id=c.chain_id AND t.address=c.token_address "
        "WHERE c.chain_id=? AND c.status='ACTIVE' AND c.stage_reached>=3 AND c.token_address NOT IN (SELECT token_address FROM portfolio_positions WHERE chain_id=? AND active=1) "
        "AND s.state NOT IN ('REJECTED','SECURITY_RISK','EXTENDED','DISTRIBUTION','THESIS_BREAK') ORDER BY s.moonshot DESC LIMIT 5",
        (ctx.chain_id, ctx.chain_id),
    )
    if not cands:
        lines.append("• rien de convaincant pour l'instant")
    for r in cands:
        m = _latest_metrics(ctx, r["token_address"])
        why = "candidat possible si les holders continuent d'arriver" if r["action"] == "CANDIDATE" else "à surveiller"
        lines.append(f"• {e(r['symbol'] or r['token_address'][:8])} — score {r['moonshot'] or 0:.0f} · capitalisation {_usd(m.get('market_cap'))} · liquidité {_usd(m.get('liquidity_usd'))} · {e(state_fr(r['state']))} · {e(why)}")
    counts = {r["status"]: r["n"] for r in ctx.db.query("SELECT status, COUNT(*) AS n FROM scanner_candidates WHERE chain_id=? GROUP BY status", (ctx.chain_id,))}
    lines.append(f"<i>{_n(sum(counts.values()))} tokens vus, {_n(counts.get('ACTIVE', 0))} suivis, {_n(counts.get('REJECTED', 0))} éliminés</i>")
    lines.append("")

    # ---- outcome of past alerts (24h horizon) ------------------------------ #
    try:
        from intel.backtest.scorecard import alert_outcomes, format_scorecard

        outcomes = alert_outcomes(ctx, since_ts=now - 3 * 86400)
        lines.append("<b>Ce que les prix ont fait après les alertes (à 24 h)</b>")
        for l in format_scorecard(outcomes, "24h", max_rows=6):
            lines.append(e(l))
        lines.append("")
    except Exception as exc:  # noqa: BLE001
        log.warning("scorecard failed: %s", exc)

    # ---- engine ------------------------------------------------------------ #
    real_sent = ctx.db.scalar("SELECT COUNT(*) FROM alerts WHERE sent=1 AND kind!='daily_digest' AND (telegram_message_id IS NULL OR telegram_message_id NOT LIKE 'not-sent%') AND ts>?", (now - 86400,), 0)
    prov = {r["provider"]: r for r in ctx.db.query("SELECT provider, calls_total, calls_failed FROM provider_status")}
    rpc = prov.get("rpc")
    rpc_txt = "réseau OK" if (rpc and rpc["calls_total"] and rpc["calls_failed"] / rpc["calls_total"] < 0.05) else "réseau ralenti"
    ok, _msg = ctx.db.quick_check()
    lines.append(f"<i>Moteur : {e(rpc_txt)} · base {'saine' if ok else 'À VÉRIFIER'} · {real_sent} message(s) hier · modèle {MODEL_VERSION.split('-')[-1]}</i>")
    lines.append("<i>Pas de message dans la journée = rien à faire.</i>")
    return "\n".join(lines)


async def send_digest(ctx: IntelContext, sender: Any, *, force: bool = False) -> tuple[bool, str | None]:
    """Send today's digest once (dedup key digest:<date>). ``force`` re-sends."""
    from intel.utils.timeutil import to_iso

    day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    key = f"digest:{day}"
    if not force and ctx.db.query_one("SELECT 1 FROM alerts WHERE dedup_key=? AND sent=1", (key,)) is not None:
        return False, "already sent today"
    body = build_digest(ctx)
    ok, mid, err = await sender.send(body)
    ctx.db.insert("alerts", {
        "ts": now_ts(), "chain_id": ctx.chain_id, "token_address": None, "severity": "INFO", "kind": "daily_digest", "dedup_key": key,
        "title": f"digest {day}", "body": body, "why": "scheduled daily summary", "action": "INFO", "sent": int(ok), "sent_ts": now_ts() if ok else None,
        "telegram_message_id": mid, "send_error": err, "suppressed": 0, "suppress_reason": None, "payload_json": None, "model_version": MODEL_VERSION,
    })
    log.info("daily digest %s sent=%s err=%s at %s", day, ok, err, to_iso(now_ts()))
    return ok, err


def digest_due(ctx: IntelContext, hour_utc: int) -> bool:
    now = dt.datetime.now(dt.timezone.utc)
    if now.hour != hour_utc:
        return False
    key = f"digest:{now.strftime('%Y-%m-%d')}"
    return ctx.db.query_one("SELECT 1 FROM alerts WHERE dedup_key=? AND sent=1", (key,)) is None
