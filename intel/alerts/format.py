"""Telegram message formatting (HTML), written for a non-technical French reader.

Layout: importance + what happens → whose token and what to do → why (one sentence) →
four useful numbers → what it means → details for the curious → link.
"""
from __future__ import annotations

import html
from typing import Any

from intel.alerts.labels import SEVERITY_FR, action_fr, kind_title_fr, meaning_fr, state_fr
from intel.alerts.rules import AlertCandidate
from intel.scoring.scores import Scores
from intel.scoring.states import StateDecision


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


def _pct(v: float | None, signed: bool = True) -> str:
    if v is None:
        return "?"
    s = f"{v:+.0%}" if signed else f"{v:.0%}"
    return s.replace("%", " %")


def _price(v: float | None) -> str:
    if v is None:
        return "?"
    if v >= 1:
        return f"{v:,.2f} $".replace(",", " ")
    return f"{v:.6f} $".rstrip("0").rstrip(".") + ""


def _g(m: dict[str, Any], *path: str, default: Any = None) -> Any:
    cur: Any = m
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return default if cur is None else cur


def esc(s: Any) -> str:
    return html.escape(str(s), quote=False)


def format_alert(c: AlertCandidate, m: dict[str, Any], scores: Scores, decision: StateDecision, *, prev_state: str | None, prev_moonshot: float | None, token_url: str | None = None, is_portfolio: bool | None = None) -> str:
    r = m.get("returns", {})
    liq = m.get("liquidity", {})
    h = m.get("holders", {})
    wh = m.get("whales", {})
    sec = m.get("security") or {}
    if is_portfolio is None:
        is_portfolio = c.action in ("HOLD", "REVIEW_EXIT")
    title = kind_title_fr(c.kind, decision.state)
    lines: list[str] = []
    lines.append(f"{SEVERITY_FR.get(c.severity, c.severity)} · <b>{esc(c.label)} — {esc(title)}</b>")
    lines.append(f"{'Ton token' if is_portfolio else 'Nouveau token (scanner)'} · Action : <b>{esc(action_fr(c.action))}</b>")
    lines.append("")
    lines.append(f"<b>Pourquoi :</b> {esc(c.why)}")
    lines.append("")
    lines.append("<b>En bref</b>")
    lines.append(f"• Prix : {_price(m.get('price_usd'))} ({_pct(r.get('return_1h'))} sur 1 h, {_pct(r.get('return_24h'))} sur 24 h)")
    lc1 = liq.get("liquidity_change_1h")
    liq_note = "stable" if (lc1 is not None and abs(lc1) < 0.03) else (_pct(lc1) + " sur 1 h" if lc1 is not None else "")
    lines.append(f"• Capitalisation : {_usd(m.get('market_cap'))} · Liquidité : {_usd(m.get('liquidity_usd'))}" + (f" ({liq_note})" if liq_note else ""))
    hc = h.get("holder_count")
    g24 = h.get("holder_growth_rate_24h")
    lines.append(f"• Holders : {hc:,} ({_pct(g24)} sur 24 h)".replace(",", " ") if hc is not None and g24 is not None else (f"• Holders : {hc:,}".replace(",", " ") if hc is not None else "• Holders : ?"))
    wn = wh.get("whale_netflow_24h")
    if wn is not None and (wh.get("n_whales") or 0) > 0:
        lines.append(f"• Gros porteurs (24 h) : {_usd(wn)} net, {wh.get('number_accumulating', 0)} achètent / {wh.get('number_distributing', 0)} vendent")
    overall = sec.get("overall")
    sec_txt = {"PASS": "rien à signaler", "WARN": "avertissements", "FAIL": "PROBLÈME", "UNKNOWN": "non vérifiée"}.get(overall or "", "non vérifiée")
    if sec.get("fails"):
        sec_txt += " (" + ", ".join(sec["fails"][:2]) + ")"
    lines.append(f"• Sécurité du contrat : {esc(sec_txt)}")
    lines.append("")
    meaning = meaning_fr(c.kind, decision.state)
    if meaning:
        lines.append(f"<b>Ce que ça veut dire :</b> {esc(meaning)}")
        lines.append("")
    # compact details
    ms = f"{prev_moonshot:.0f} → {scores.moonshot:.0f}" if prev_moonshot is not None and abs(prev_moonshot - scores.moonshot) >= 1 else f"{scores.moonshot:.0f}"
    details = [f"score {ms} (survie {scores.survival:.0f} · adoption {scores.traction:.0f} · potentiel {scores.asymmetry:.0f} · répartition {scores.distribution:.0f})"]
    if prev_state and prev_state != decision.state:
        details.append(f"état : {state_fr(prev_state)} → {state_fr(decision.state)}")
    else:
        details.append(f"état : {state_fr(decision.state)}")
    x = _g(m, "asymmetry", "x_from_first_meaningful_market")
    dd = _g(m, "asymmetry", "drawdown_from_ath")
    if x is not None:
        details.append(f"x{x:.1f} depuis le premier vrai marché")
    if dd is not None:
        details.append(f"{_pct(dd, signed=False)} sous le sommet")
    org = m.get("organic_volume_score")
    if org is not None:
        details.append(f"volume organique {org:.0f}/100")
    flags = [f for f in (m.get("quality_flags") or []) if f in ("partial_transfer_history", "launch_history_incomplete")]
    if flags:
        details.append("historique encore incomplet")
    lines.append(f"<i>Détails : {esc(' · '.join(details))}</i>")
    if token_url:
        lines.append(f'<a href="{esc(token_url)}">graphique</a> · <code>{esc(c.token)}</code>')
    else:
        lines.append(f"<code>{esc(c.token)}</code>")
    return "\n".join(lines)


def strip_tags_for_test(text: str) -> str:
    import re

    return html.unescape(re.sub(r"<[^>\n]+>", "", text))


def format_digest(title: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"<b>{esc(title)}</b>", ""]
    for r in rows:
        lines.append(f"• {esc(r.get('label'))}: {esc(state_fr(r.get('state')))} | score {r.get('moonshot', 0):.0f} | MC {_usd(r.get('market_cap'))} | {esc(action_fr(r.get('action')))}")
    return "\n".join(lines)
