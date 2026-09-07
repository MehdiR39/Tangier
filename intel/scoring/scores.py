"""Component scores (0-100) with explanations, and the weighted MOONSHOT score.

Weights come from config ``scoring.weights`` (normalised). Narrative can never override a
critical security failure: on any security FAIL it is capped by
``scoring.narrative_cap_on_security_fail``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from intel.scoring.hard_filters import HardFilterResult


def _g(m: dict[str, Any], *path: str, default: Any = None) -> Any:
    cur: Any = m
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return default if cur is None else cur


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


@dataclass
class Scores:
    survival: float
    traction: float
    asymmetry: float
    distribution: float
    organic_volume: float | None
    smart_money: float | None
    rug_risk: float
    narrative: float
    moonshot: float
    explain: dict[str, list[str]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "survival": round(self.survival, 1), "traction": round(self.traction, 1), "asymmetry": round(self.asymmetry, 1), "distribution": round(self.distribution, 1),
            "organic_volume": None if self.organic_volume is None else round(self.organic_volume, 1), "smart_money": None if self.smart_money is None else round(self.smart_money, 1),
            "rug_risk": round(self.rug_risk, 1), "narrative": round(self.narrative, 1), "moonshot": round(self.moonshot, 1), "explain": self.explain,
        }


def survival_score(m: dict[str, Any]) -> tuple[float, list[str]]:
    why: list[str] = []
    s = 50.0
    liq = m.get("liquidity_usd")
    if liq is not None:
        add = min(20.0, liq / 100_000.0 * 20.0)
        s += add
        why.append(f"liquidity ${liq:,.0f} (+{add:.0f})")
    l2m = _g(m, "liquidity", "liquidity_to_mc")
    if l2m is not None:
        if l2m >= 0.15:
            s += 10
            why.append(f"liq/mc {l2m:.2f} (+10)")
        elif l2m >= 0.05:
            s += 5
            why.append(f"liq/mc {l2m:.2f} (+5)")
        elif l2m < 0.03:
            s -= 15
            why.append(f"liq/mc {l2m:.3f} thin (-15)")
    age = m.get("token_age_seconds")
    if age is not None:
        add = min(10.0, age / 86400.0 * 2.0)
        s += add
        why.append(f"age {age / 86400:.1f}d (+{add:.0f})")
    sec = m.get("security") or {}
    checks = sec.get("checks", {})
    if sec.get("fails"):
        s = min(s, 10.0)
        why.append("security FAIL: " + ", ".join(sec["fails"]))
    warns = [w for w in sec.get("warns", []) if w not in ("doppler_pool_lock",)]
    if warns:
        pen = min(25.0, 8.0 * len(warns))
        s -= pen
        why.append(f"security warns {', '.join(warns[:4])} (-{pen:.0f})")
    unknowns = sec.get("unknowns", [])
    if not sec:
        s -= 15
        why.append("security unknown (-15)")
    elif unknowns:
        pen = min(15.0, 4.0 * len(unknowns))
        s -= pen
        why.append(f"{len(unknowns)} security checks unknown (-{pen:.0f})")
    if (checks.get("lp_control") or {}).get("status") == "PASS":
        s += 5
        why.append("LP protocol-managed (+5)")
    if _g(m, "liquidity", "large_lp_removal"):
        s -= 20
        why.append("large LP removal 1h (-20)")
    if _g(m, "liquidity", "single_pool_dependency"):
        s -= 5
        why.append("single-pool dependency (-5)")
    lc24 = _g(m, "liquidity", "liquidity_change_24h")
    if lc24 is not None and lc24 <= -0.3:
        s -= 15
        why.append(f"liquidity -{abs(lc24):.0%} 24h (-15)")
    return clamp(s), why


def traction_score(m: dict[str, Any]) -> tuple[float, list[str]]:
    why: list[str] = []
    s = 30.0
    h = m.get("holders", {})
    organic = m.get("organic_volume_score")
    org_mult = (organic / 100.0) if organic is not None else 0.6
    g24 = h.get("holder_growth_rate_24h")
    if g24 is not None:
        add = clamp(g24 * 100.0, -15.0, 25.0)
        s += add
        why.append(f"holders {g24:+.1%} 24h ({add:+.0f})")
    g6 = h.get("holder_growth_rate_6h")
    if g6 is not None:
        add = clamp(g6 * 150.0, -10.0, 15.0)
        s += add
        why.append(f"holders {g6:+.1%} 6h ({add:+.0f})")
    acc = h.get("holder_growth_acceleration")
    if acc is not None and acc > 0:
        add = min(10.0, acc * 10.0)
        s += add
        why.append(f"holder acceleration {acc:.2f} (+{add:.0f})")
    q24 = _g(m, "trading_quality", "24h", default={})
    ub = q24.get("unique_buyers")
    if ub:
        add = min(15.0, math.log10(ub + 1) * 5.0) * org_mult
        s += add
        why.append(f"{ub} unique buyers 24h (+{add:.0f}, organic x{org_mult:.2f})")
    nb = q24.get("new_buyers")
    if nb is not None and ub:
        share = nb / ub
        add = 10.0 * share * org_mult
        s += add
        why.append(f"new-buyer share {share:.0%} (+{add:.0f})")
    divs = h.get("divergences", [])
    if any(d.startswith("price_down_holders_up") for d in divs):
        s += 5
        why.append("price down / holders up (+5)")
    if any(d.startswith("price_flat_holders_accelerating") for d in divs):
        s += 5
        why.append("price flat / holders accelerating (+5)")
    if any(d.startswith("price_up_holders_down") for d in divs):
        s -= 10
        why.append("price up / holders down (-10)")
    hc = h.get("holder_count")
    if hc is not None:
        add = min(10.0, math.log10(hc + 1) * 2.5)
        s += add
        why.append(f"{hc} holders (+{add:.0f})")
    if organic is not None and organic < 40:
        s -= 10
        why.append(f"organic volume {organic:.0f} (-10)")
    # v0.2: without measured 24h holder growth, traction only sees buying activity, which was
    # the profile of the day-one losers (crowded buying at the top) -> cap it
    if g24 is None:
        s = min(s, 50.0)
        why.append("holder growth 24h not measured yet (cap 50)")
    bs = _g(m, "trading_quality", "24h", "buy_sell_ratio")
    if bs is not None and bs > 2.0:
        s -= 10
        why.append(f"buy/sell ratio {bs:.1f}: crowded buying (-10)")
    return clamp(s), why


def asymmetry_score(m: dict[str, Any], cfg: dict[str, Any]) -> tuple[float, list[str]]:
    why: list[str] = []
    target = float(cfg.get("target_mc_usd", 250_000.0))
    pen_x = float(cfg.get("penalty_x_from_fmm", 50.0))
    mc = m.get("market_cap")
    if mc is None:
        return 30.0, ["market cap unknown -> neutral-low"]
    if mc <= target:
        s = 90.0
    else:
        s = 90.0 - 25.0 * math.log10(mc / target)
    why.append(f"mc ${mc:,.0f} -> base {s:.0f}")
    x = _g(m, "asymmetry", "x_from_first_meaningful_market")
    fmm_reached = _g(m, "launch", "fmm_reached", default=False)
    if not fmm_reached:
        s = min(s, 60.0)
        why.append("first meaningful market not established (cap 60)")
    elif x is not None:
        if x > pen_x:
            s -= 40
            why.append(f"x{x:.1f} from first meaningful market (> {pen_x:.0f}, -40)")
        elif x > 20:
            s -= 20
            why.append(f"x{x:.1f} from first meaningful market (-20)")
        elif x > 10:
            s -= 10
            why.append(f"x{x:.1f} from first meaningful market (-10)")
        else:
            why.append(f"x{x:.2f} from first meaningful market")
    dd = _g(m, "asymmetry", "drawdown_from_ath")
    g24 = _g(m, "holders", "holder_growth_rate_24h")
    if dd is not None and 0.4 <= dd <= 0.85 and (g24 or 0) > 0:
        s += 5
        why.append(f"retrace {dd:.0%} from ATH with holders growing (+5)")
    imp = (m.get("price_impact") or {}).get("buy_1000")
    if imp is not None and imp > 0.10:
        s -= 10
        why.append(f"$1k buy impact {imp:.0%} (-10)")
    return clamp(s), why


def distribution_score(m: dict[str, Any]) -> tuple[float, list[str]]:
    why: list[str] = []
    s = 100.0
    c = m.get("concentration", {})
    cl = m.get("clusters", {})
    top10 = c.get("top10_pct")
    eff10 = cl.get("effective_top10_pct")
    worst = max(v for v in (top10, eff10) if v is not None) if (top10 is not None or eff10 is not None) else None
    if worst is None:
        return 40.0, ["concentration unknown -> 40"]
    if worst > 0.15:
        pen = min(70.0, (worst - 0.15) * 150.0)
        s -= pen
        why.append(f"top10 ex-system {worst:.1%}{' (cluster-adjusted)' if eff10 and eff10 > (top10 or 0) else ''} (-{pen:.0f})")
    else:
        why.append(f"top10 ex-system {worst:.1%}")
    h = c.get("hhi")
    if h is not None and h > 0.10:
        s -= 10
        why.append(f"HHI {h:.3f} (-10)")
    ch24 = c.get("top20_pct_change_24h")
    if ch24 is not None:
        if ch24 >= 0.03:
            s -= 10
            why.append(f"top20 +{ch24:.1%} 24h concentrating (-10)")
        elif ch24 <= -0.02:
            s += 5
            why.append(f"top20 {ch24:+.1%} 24h diffusing (+5)")
    lc = cl.get("largest_cluster_pct")
    if lc is not None and lc > 0.2:
        s -= 20
        why.append(f"insider cluster {lc:.1%} (-20)")
    # holder breadth: use the full economic count when the replay is complete, otherwise the
    # explorer holder count (the top-N page alone says nothing about breadth)
    n = c.get("n_holders_economic") if "topn_only" not in (c.get("quality_flags") or []) else _g(m, "holders", "holder_count")
    if n is not None:
        if n < 100:
            s -= 20
            why.append(f"{n} holders (-20)")
        elif n < 300:
            s -= 10
            why.append(f"{n} holders (-10)")
    dep = ((m.get("security") or {}).get("checks", {}).get("deployer_holdings") or {}).get("status")
    if dep in ("WARN", "FAIL"):
        s -= 10
        why.append("team/deployer holdings notable (-10)")
    return clamp(s), why


def rug_risk_score(m: dict[str, Any]) -> tuple[float, list[str]]:
    why: list[str] = []
    r = 10.0
    sec = m.get("security") or {}
    checks = sec.get("checks", {})
    if sec.get("fails"):
        r = 90.0
        why.append("security FAIL " + ", ".join(sec["fails"]))
    else:
        if not sec:
            r += 25
            why.append("security unknown (+25)")
        r += 6 * len(sec.get("warns", []))
        r += 3 * len(sec.get("unknowns", []))
        if (checks.get("source_verified") or {}).get("status") != "PASS":
            r += 10
            why.append("unverified source (+10)")
        if (checks.get("lp_control") or {}).get("status") == "WARN":
            r += 15
            why.append("LP withdrawable (+15)")
        if (checks.get("deployer_holdings") or {}).get("status") in ("WARN", "FAIL"):
            r += 10
            why.append("deployer holdings (+10)")
    if _g(m, "liquidity", "large_lp_removal"):
        r += 20
        why.append("LP removal (+20)")
    l2m = _g(m, "liquidity", "liquidity_to_mc")
    if l2m is not None and l2m < 0.03:
        r += 15
        why.append("liq/mc < 3% (+15)")
    if _g(m, "liquidity", "single_pool_dependency"):
        r += 5
    age = m.get("token_age_seconds")
    if age is not None and age < 6 * 3600:
        r += 10
        why.append("age < 6h (+10)")
    hc = _g(m, "holders", "holder_count")
    if hc is not None and hc < 50:
        r += 10
        why.append("< 50 holders (+10)")
    top10 = _g(m, "concentration", "top10_pct")
    if top10 is not None and top10 > 0.5:
        r += 20
        why.append(f"top10 {top10:.0%} (+20)")
    lc = _g(m, "clusters", "largest_cluster_pct")
    if lc is not None and lc > 0.3:
        r += 15
        why.append(f"insider cluster {lc:.0%} (+15)")
    return clamp(r), why


def compute_scores(m: dict[str, Any], cfg: dict[str, Any], hf: HardFilterResult) -> Scores:
    weights = dict(cfg.get("weights", {}))
    total = sum(float(v) for v in weights.values()) or 1.0
    w = {k: float(v) / total for k, v in weights.items()}
    surv, e_s = survival_score(m)
    trac, e_t = traction_score(m)
    asym, e_a = asymmetry_score(m, cfg.get("asymmetry", {}))
    dist, e_d = distribution_score(m)
    rug, e_r = rug_risk_score(m)
    narrative = float(_g(m, "narrative", "score", default=0.0))
    e_n = [f"metadata-only score {narrative:.0f}"]
    sec = m.get("security") or {}
    if sec.get("fails") or hf.security_reject:
        cap = float(cfg.get("narrative_cap_on_security_fail", 0))
        narrative = min(narrative, cap)
        e_n.append(f"capped at {cap:.0f} (security FAIL)")
    organic = m.get("organic_volume_score")
    sm = _g(m, "smart_money", "smart_money_score")
    # Weighted mean over the components actually measured, renormalised. A missing component is
    # not a zero: a token must not be marked down for data we failed to collect. Weights and the
    # choice of components come from measurement, not from judgement — see MODEL_VERSION notes.
    available = {"asymmetry": asym, "traction": trac, "survival": surv, "distribution": dist,
                 "narrative": narrative, "organic_volume": organic, "smart_money": sm, "rug_risk": rug}
    num = den = 0.0
    used: list[str] = []
    for key, weight in w.items():
        value = available.get(key)
        if value is None or not weight:
            continue
        num += float(weight) * float(value)
        den += abs(float(weight))
        used.append(f"{key}={float(value):.0f}x{weight:+.2f}")
    moonshot = (num / den) if den > 0 else 0.0
    e_m = used or [f"{k}={v:.2f}" for k, v in w.items()]
    if not hf.passed:
        e_m.append("hard filters not passed: " + "; ".join(hf.reasons + [f"unknown:{u}" for u in hf.unknowns]))
    if hf.warnings:
        e_m.append("warnings: " + "; ".join(hf.warnings))
    return Scores(
        survival=surv, traction=trac, asymmetry=asym, distribution=dist, organic_volume=organic, smart_money=sm, rug_risk=rug, narrative=narrative, moonshot=clamp(moonshot),
        explain={"survival": e_s, "traction": e_t, "asymmetry": e_a, "distribution": e_d, "rug_risk": e_r, "narrative": e_n, "moonshot": e_m,
                 "organic_volume": _g(m, "trading_quality", "24h", "organic_explain", default=[]), "smart_money": [f"status={_g(m, 'smart_money', 'smart_money_status', default='UNKNOWN')}"]},
    )
