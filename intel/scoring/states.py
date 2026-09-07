"""Token state engine. One state per token; transitions are persisted for Telegram."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from intel.scoring.hard_filters import HardFilterResult
from intel.scoring.scores import Scores

STATES = ["DISCOVER", "EARLY_ACCUMULATION", "ACCUMULATION", "BREAKOUT", "BREAKOUT_CONFIRMED", "WATCH", "EXTENDED", "DISTRIBUTION", "THESIS_BREAK", "SECURITY_RISK", "REJECTED"]
ACTIONS = ["HOLD", "WATCH", "DO_NOT_ADD", "REVIEW_EXIT", "CANDIDATE", "REJECT"]
NEGATIVE_STATES = {"DISTRIBUTION", "THESIS_BREAK", "SECURITY_RISK", "REJECTED", "EXTENDED"}


@dataclass
class StateDecision:
    state: str
    action: str
    reason: str
    codes: list[str] = field(default_factory=list)  # machine-readable triggers (e.g. THESIS_BREAK clauses)


def _g(m: dict[str, Any], *path: str, default: Any = None) -> Any:
    cur: Any = m
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return default if cur is None else cur


def candidate_eligible(m: dict[str, Any], cfg: dict[str, Any]) -> tuple[bool, str]:
    """Tradeable-size and anti-chasing gate for the CANDIDATE action (v0.2)."""
    liq = m.get("liquidity_usd")
    if liq is None or liq < float(cfg.get("candidate_min_liquidity_usd", 100_000.0)):
        return False, f"liquidité {'inconnue' if liq is None else f'{liq:,.0f} $'} sous le plancher"
    age_h = (m.get("token_age_seconds") or 0) / 3600.0
    if age_h < float(cfg.get("candidate_min_age_hours", 24)):
        return False, f"trop jeune ({age_h:.0f} h)"
    bs = _g(m, "trading_quality", "24h", "buy_sell_ratio")
    if bs is not None and bs > float(cfg.get("candidate_max_buy_sell_ratio", 2.0)):
        return False, f"trop d'acheteurs pour peu de vendeurs (ratio {bs:.1f})"
    r1 = _g(m, "returns", "return_1h")
    if r1 is not None and r1 > float(cfg.get("candidate_max_return_1h", 0.5)):
        return False, f"déjà +{r1:.0%} dans l'heure"
    if _g(m, "holders", "holder_growth_rate_24h") is None:
        return False, "croissance des holders sur 24 h pas encore mesurée"
    return True, "ok"


def decide_state(m: dict[str, Any], scores: Scores, hf: HardFilterResult, cfg: dict[str, Any], *, prev_state: str | None, prev_since_ts: int | None, is_portfolio: bool, moonshot_threshold: float) -> StateDecision:
    as_of = int(m.get("as_of_ts") or 0)
    h = m.get("holders", {})
    r = m.get("returns", {})
    liq = m.get("liquidity", {})
    wh = m.get("whales", {})
    c = m.get("concentration", {})
    g24 = h.get("holder_growth_rate_24h")
    g6 = h.get("holder_growth_rate_6h")
    g1 = h.get("holder_growth_rate_1h")
    r1, r6, r24 = r.get("return_1h"), r.get("return_6h"), r.get("return_24h")
    x_fmm = _g(m, "asymmetry", "x_from_first_meaningful_market")
    dd = _g(m, "asymmetry", "drawdown_from_ath")
    age_h = (m.get("token_age_seconds") or 0) / 3600.0
    q1 = _g(m, "trading_quality", "1h", default={})
    organic = m.get("organic_volume_score")
    fmm = _g(m, "launch", "fmm_reached", default=False)
    top_dist = m.get("top_wallet_distribution") or []

    # 1. hard rejects
    if hf.security_reject:
        return StateDecision("SECURITY_RISK", "REVIEW_EXIT" if is_portfolio else "REJECT", "; ".join(hf.reasons) or "défaut de sécurité")
    if hf.reasons:
        return StateDecision("REJECTED", "REVIEW_EXIT" if is_portfolio else "REJECT", "; ".join(hf.reasons))

    # 2. thesis break
    tb_dd = float(cfg.get("thesis_break_drawdown", 0.70))
    tb_lp = float(cfg.get("thesis_break_lp_drop", 0.50))
    tb_h = float(cfg.get("thesis_break_holder_drop_24h", -0.10))
    reasons: list[str] = []
    codes: list[str] = []
    if dd is not None and dd >= tb_dd and (g24 is not None and g24 < 0):
        reasons.append(f"{dd:.0%} sous le sommet et les holders diminuent")
        codes.append("drawdown_ath")
    lc24 = liq.get("liquidity_change_24h")
    lc1 = liq.get("liquidity_change_1h")
    if lc24 is not None and lc24 <= -tb_lp:
        reasons.append(f"liquidité {lc24:+.0%} sur 24 h")
        codes.append("liquidity_24h")
    if liq.get("large_lp_removal") and lc1 is not None and lc1 <= -0.3:
        reasons.append(f"retrait de liquidité, {lc1:+.0%} sur 1 h")
        codes.append("lp_removal")
    if g24 is not None and g24 <= tb_h:
        reasons.append(f"holders {g24:+.1%} sur 24 h")
        codes.append("holders_24h")
    if reasons:
        return StateDecision("THESIS_BREAK", "REVIEW_EXIT" if is_portfolio else "REJECT", "; ".join(reasons), codes)

    # 3. distribution
    wn24 = wh.get("whale_netflow_24h")
    ch24 = c.get("top20_pct_change_24h")
    n_dist = wh.get("number_distributing") or 0
    n_acc = wh.get("number_accumulating") or 0
    dist_reasons: list[str] = []
    if wn24 is not None and wn24 <= float(cfg.get("distribution_whale_netflow_usd", -20000.0)) and (ch24 or 0) >= float(cfg.get("distribution_top20_increase", 0.03)):
        dist_reasons.append(f"les gros porteurs ont vendu net {abs(wn24):,.0f} $ sur 24 h pendant que la concentration montait ({ch24:+.1%})")
    if len(top_dist) >= 3 and (ch24 or 0) > 0:
        dist_reasons.append(f"{len(top_dist)} gros wallets ont vendu au moins 20 % de leur position en 6 h pendant que la concentration montait")
    if n_dist >= 3 and n_dist > 2 * n_acc:
        dist_reasons.append(f"{n_dist} gros porteurs vendent contre {n_acc} qui achètent")
    if any(d.startswith("price_up_holders_down") for d in h.get("divergences", [])) and (wn24 or 0) < 0:
        dist_reasons.append("le prix monte mais les holders diminuent et les gros porteurs vendent")
    if dist_reasons:
        return StateDecision("DISTRIBUTION", "DO_NOT_ADD", "; ".join(dist_reasons))

    # 4. extended
    ext_x = float(cfg.get("extended_x_from_fmm", 20.0))
    ext_r = float(cfg.get("extended_return_24h", 2.0))
    if x_fmm is not None and x_fmm >= ext_x:
        return StateDecision("EXTENDED", "DO_NOT_ADD", f"déjà x{x_fmm:.1f} depuis le premier vrai marché")
    if r24 is not None and r24 >= ext_r and (g24 is None or g24 < r24 / 10):
        return StateDecision("EXTENDED", "DO_NOT_ADD", f"+{r24:.0%} en 24 h sans que les holders suivent")

    # insufficient data: never promote a scanner token to a directional state on unknowns
    if hf.unknowns and not is_portfolio:
        return StateDecision("DISCOVER", "WATCH", "données insuffisantes : " + ", ".join(hf.unknowns))

    # scanner action helper: CANDIDATE only for tradeable, non-chased tokens with measured adoption
    eligible, why_not = candidate_eligible(m, cfg)

    def scanner_action(high: bool) -> str:
        if is_portfolio:
            return "HOLD"
        return "CANDIDATE" if (high and eligible) else "WATCH"

    def note(reason: str, high: bool) -> str:
        return reason if (is_portfolio or not high or eligible) else f"{reason} ; pas candidat : {why_not}"

    # 5/6. breakout
    br = float(cfg.get("breakout_return_1h", 0.15))
    confirm_h = float(cfg.get("breakout_confirm_hours", 6))
    if prev_state in ("BREAKOUT", "BREAKOUT_CONFIRMED") and prev_since_ts is not None:
        if (r6 is not None and r6 >= 0) and (g6 is not None and g6 > 0) and (as_of - prev_since_ts) >= confirm_h * 3600:
            return StateDecision("BREAKOUT_CONFIRMED", scanner_action(True), note(f"la hausse tient depuis {confirm_h:.0f} h et les holders continuent d'arriver", True))
        if prev_state == "BREAKOUT" and (r6 is None or r6 >= -0.10):
            return StateDecision("BREAKOUT", scanner_action(True), note("décollage en cours", True))
    if r1 is not None and r1 >= br and (q1.get("unique_buyers") or 0) >= 10 and (g1 or 0) > 0 and (organic is None or organic >= 40):
        return StateDecision("BREAKOUT", scanner_action(True), note(f"+{r1:.0%} en 1 h avec {q1.get('unique_buyers')} acheteurs distincts et des holders en hausse", True))

    # 7/8. accumulation
    acc_g = float(cfg.get("accumulation_holder_growth_24h", 0.05))
    if g24 is not None and g24 >= acc_g and (r24 is None or abs(r24) < 0.30) and (wn24 is None or wn24 >= 0) and (ch24 is None or ch24 < 0.03):
        high = scores.moonshot >= moonshot_threshold
        return StateDecision("ACCUMULATION", scanner_action(high), note(f"holders {g24:+.1%} sur 24 h, prix {r24:+.0%}, les gros porteurs ne vendent pas" if r24 is not None else f"holders {g24:+.1%} sur 24 h", high))
    if age_h < float(cfg.get("early_accumulation_max_age_hours", 48)) and fmm and (g6 or 0) >= 0.03 and (x_fmm is None or x_fmm < 5):
        high = scores.moonshot >= moonshot_threshold
        return StateDecision("EARLY_ACCUMULATION", scanner_action(high), note(f"token jeune ({age_h:.0f} h), holders {g6:+.1%} en 6 h, x{x_fmm or 0:.1f} depuis le premier vrai marché", high))

    # 9/10
    if scores.moonshot >= float(cfg.get("watch_moonshot_min", 50)) and hf.passed:
        high = scores.moonshot >= moonshot_threshold
        return StateDecision("WATCH", scanner_action(high), note(f"score {scores.moonshot:.0f}, pas de tendance nette", high))
    if not hf.passed and hf.unknowns:
        return StateDecision("DISCOVER", "WATCH" if is_portfolio else "WATCH", "données insuffisantes : " + ", ".join(hf.unknowns))
    return StateDecision("DISCOVER" if (prev_state in (None, "DISCOVER")) else "WATCH", "HOLD" if is_portfolio else "WATCH", f"score {scores.moonshot:.0f}")
