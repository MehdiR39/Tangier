"""Alert triggers. Each candidate explains WHY and carries an analytical ACTION label."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from intel.scoring.scores import Scores
from intel.scoring.states import StateDecision

SEVERITIES = ["INFO", "WATCH", "IMPORTANT", "CRITICAL"]
SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}

STATE_SEVERITY = {
    "THESIS_BREAK": "CRITICAL", "SECURITY_RISK": "CRITICAL", "DISTRIBUTION": "IMPORTANT", "EXTENDED": "WATCH", "BREAKOUT": "IMPORTANT",
    "BREAKOUT_CONFIRMED": "IMPORTANT", "ACCUMULATION": "WATCH", "EARLY_ACCUMULATION": "WATCH", "WATCH": "INFO", "REJECTED": "INFO", "DISCOVER": "INFO",
}


@dataclass
class AlertCandidate:
    kind: str
    severity: str
    title: str
    why: str
    action: str
    dedup_key: str
    token: str
    label: str
    payload: dict[str, Any] = field(default_factory=dict)


def _g(m: dict[str, Any], *path: str, default: Any = None) -> Any:
    cur: Any = m
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return default if cur is None else cur


def evaluate_alerts(
    *,
    token: str,
    label: str,
    m: dict[str, Any],
    scores: Scores,
    decision: StateDecision,
    prev_state: str | None,
    prev_moonshot: float | None,
    prev_hard_pass: bool | None,
    hard_pass: bool,
    is_portfolio: bool,
    cfg: dict[str, Any],
    moonshot_threshold: float,
) -> list[AlertCandidate]:
    out: list[AlertCandidate] = []
    state = decision.state
    liq = m.get("liquidity", {})
    wh = m.get("whales", {})
    h = m.get("holders", {})

    # state transitions
    watch_min = float(cfg.get("scanner_alert_min_moonshot", 50))
    liq_floor_state = float(cfg.get("scanner_min_liquidity_usd", 100_000.0))
    thin_state = (m.get("liquidity_usd") is None) or (m.get("liquidity_usd") < liq_floor_state)
    if prev_state != state and not (prev_state is None and state in ("DISCOVER", "WATCH")):
        sev = STATE_SEVERITY.get(state, "INFO")
        if is_portfolio and state in ("DISTRIBUTION", "EXTENDED"):
            sev = "IMPORTANT"
        if not is_portfolio:
            # scanner noise control: only tokens that pass hard filters with a meaningful score
            # are worth a Telegram message; everything else stays INFO (persisted, not sent)
            if state == "REJECTED" and prev_state in (None, "DISCOVER"):
                sev = "INFO"
            elif (thin_state or not (hard_pass and scores.moonshot >= watch_min)) and state not in ("SECURITY_RISK", "THESIS_BREAK"):
                sev = "INFO"
            elif state in ("SECURITY_RISK", "THESIS_BREAK") and prev_state in (None, "DISCOVER"):
                sev = "INFO"  # a brand-new scanner token failing is not actionable news
        out.append(AlertCandidate("state_change", sev, f"{label} — {state}", decision.reason, decision.action, f"state:{token}:{state}", token, label, {"from": prev_state, "to": state}))

    # LP drop
    lc1 = liq.get("liquidity_change_1h")
    thr = float(cfg.get("lp_drop_pct", 0.15))
    if (lc1 is not None and lc1 <= -thr) or liq.get("large_lp_removal"):
        sev = "CRITICAL" if (lc1 is not None and lc1 <= -2 * thr) else "IMPORTANT"
        pct = liq.get("lp_removed_1h_pct")
        why = f"la liquidité a baissé de {abs(lc1):.0%} en 1 h" if lc1 is not None else "gros retrait de liquidité détecté"
        if pct:
            why += f" ({pct:.0%} de la liquidité active retirée)"
        out.append(AlertCandidate("lp_drop", sev, f"{label} — LP DROP", why, "REVIEW_EXIT" if is_portfolio else "DO_NOT_ADD", f"lp_drop:{token}", token, label, {"liquidity_change_1h": lc1}))

    # top wallet distribution
    td = m.get("top_wallet_distribution") or []
    if len(td) >= 2:
        why = f"{len(td)} gros wallets ont réduit leur position d'au moins {float(cfg.get('top_wallet_distribution_pct', 0.2)):.0%} en 6 h ; flux net des gros porteurs sur 6 h : {wh.get('whale_netflow_6h') or 0:,.0f} $"
        out.append(AlertCandidate("top_wallet_distribution", "IMPORTANT", f"{label} — TOP WALLET DISTRIBUTION", why, "DO_NOT_ADD" if not is_portfolio else "REVIEW_EXIT", f"top_dist:{token}", token, label, {"wallets": [w["address"] for w in td[:5]]}))

    # scanner tokens below the bar only get the candidate / security alerts above;
    # v0.2: also nothing below the scanner liquidity floor (fees + impact make it untradeable)
    liq_floor = float(cfg.get("scanner_min_liquidity_usd", 100_000.0))
    thin = (m.get("liquidity_usd") is None) or (m.get("liquidity_usd") < liq_floor)
    scanner_quiet = (not is_portfolio) and (thin or not (hard_pass and scores.moonshot >= watch_min))

    # whale accumulation
    wn1 = wh.get("whale_netflow_1h")
    ch1 = _g(m, "concentration", "top20_pct_change_1h")
    if not scanner_quiet and wn1 is not None and wn1 >= float(cfg.get("whale_accumulation_usd", 25000.0)):
        conc_note = "sans que la concentration augmente" if (ch1 is None or ch1 <= 0.01) else f"la concentration monte ({ch1:+.1%} en 1 h)"
        out.append(AlertCandidate("whale_accumulation", "WATCH", f"{label} — WHALE ACCUMULATION", f"les gros porteurs ont acheté net {wn1:,.0f} $ en 1 h ({wh.get('number_accumulating')} achètent / {wh.get('number_distributing')} vendent), {conc_note}", "WATCH" if not is_portfolio else "HOLD", f"whale_acc:{token}", token, label, {"whale_netflow_1h": wn1}))
    wn6 = wh.get("whale_netflow_6h")
    if not scanner_quiet and wn6 is not None and wn6 <= float(cfg.get("whale_distribution_usd", -25000.0)) and state != "DISTRIBUTION":
        out.append(AlertCandidate("whale_distribution", "IMPORTANT", f"{label} — WHALE SELLING", f"les gros porteurs ont vendu net {abs(wn6):,.0f} $ en 6 h ; {wh.get('number_distributing')} vendent", "DO_NOT_ADD" if not is_portfolio else "REVIEW_EXIT", f"whale_dist:{token}", token, label, {"whale_netflow_6h": wn6}))

    # holder growth acceleration
    acc = h.get("holder_growth_acceleration")
    if not scanner_quiet and acc is not None and acc >= float(cfg.get("holder_acceleration_threshold", 0.5)) and (h.get("holder_count") or 0) >= 100 and (h.get("holder_growth_recent") or 0) >= int(cfg.get("holder_acceleration_min_new", 10)):
        out.append(AlertCandidate("holder_acceleration", "WATCH", f"{label} — HOLDER ACCELERATION", f"+{h.get('holder_growth_recent')} holders dans la dernière heure contre +{h.get('holder_growth_previous')} l'heure d'avant ; prix {(_g(m, 'returns', 'return_1h') or 0):+.0%} sur 1 h", "WATCH", f"holder_acc:{token}", token, label, {"acceleration": acc}))

    # divergences
    divs = [d for d in h.get("divergences", []) if d.endswith("24h")] if not scanner_quiet else []
    for d in divs:
        out.append(AlertCandidate("divergence", "WATCH", f"{label} — DIVERGENCE {d.replace('_24h', '').upper()}", f"prix {(_g(m, 'returns', 'return_24h') or 0):+.0%} sur 24 h alors que les holders font {(h.get('holder_growth_rate_24h') or 0):+.0%}", "WATCH", f"div:{token}:{d}", token, label, {"divergence": d}))

    # material score change
    delta_thr = float(cfg.get("material_score_delta", 10))
    if not scanner_quiet and prev_moonshot is not None and abs(scores.moonshot - prev_moonshot) >= delta_thr:
        direction = "UP" if scores.moonshot > prev_moonshot else "DOWN"
        out.append(AlertCandidate("score_change", "WATCH", f"{label} — MOONSHOT {direction}", f"score passé de {prev_moonshot:.0f} à {scores.moonshot:.0f}", decision.action, f"score:{token}:{direction}:{int(scores.moonshot // delta_thr)}", token, label, {"prev": prev_moonshot, "now": scores.moonshot}))

    # scanner-specific: only tokens the state engine is willing to label CANDIDATE / WATCH
    # (an EXTENDED or DISTRIBUTION token can score high on asymmetry yet is DO_NOT_ADD)
    if not is_portfolio and decision.action in ("CANDIDATE", "WATCH"):
        if hard_pass and not prev_hard_pass:
            hf_min = float(cfg.get("hard_filters_pass_min_moonshot", 70))
            sev = "WATCH" if (scores.moonshot >= hf_min and not thin) else "INFO"
            out.append(AlertCandidate("hard_filters_pass", sev, f"{label} — PASSED HARD FILTERS", f"aucun défaut rédhibitoire ; score {scores.moonshot:.0f} (survie {scores.survival:.0f}, adoption {scores.traction:.0f}, potentiel {scores.asymmetry:.0f}, répartition {scores.distribution:.0f})", decision.action, f"hf_pass:{token}", token, label, {}))
        if decision.action == "CANDIDATE" and not thin and hard_pass and scores.moonshot >= moonshot_threshold and (prev_moonshot is None or prev_moonshot < moonshot_threshold):
            out.append(AlertCandidate("moonshot_candidate", "IMPORTANT", f"{label} — MOONSHOT CANDIDATE", f"score {scores.moonshot:.0f} au-dessus du seuil {moonshot_threshold:.0f} ; {decision.reason}", "CANDIDATE", f"candidate:{token}", token, label, {"moonshot": scores.moonshot}))
    return out
