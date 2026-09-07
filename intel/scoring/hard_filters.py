"""Hard filters applied before scoring. Unknown critical inputs do not pass silently."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class HardFilterResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)      # reject reasons
    warnings: list[str] = field(default_factory=list)     # severe warnings (not rejects)
    unknowns: list[str] = field(default_factory=list)     # data gaps that block a PASS
    security_reject: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "reasons": self.reasons, "warnings": self.warnings, "unknowns": self.unknowns, "security_reject": self.security_reject}


def _g(m: dict[str, Any], *path: str, default: Any = None) -> Any:
    cur: Any = m
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return default if cur is None else cur


def apply_hard_filters(m: dict[str, Any], cfg: dict[str, Any]) -> HardFilterResult:
    r = HardFilterResult(passed=True)
    min_liq = float(cfg.get("min_liquidity_usd", 20000.0))
    min_l2m = float(cfg.get("min_liquidity_to_mc", 0.03))
    l2m_age_h = float(cfg.get("liquidity_to_mc_reject_min_age_hours", 24))
    max_top10 = float(cfg.get("max_top10_excluded_system_pct", 0.50))
    max_cluster = float(cfg.get("max_insider_cluster_pct", 0.40))
    x_pen = float(cfg.get("asymmetry_penalty_x_from_fmm", 50.0))

    liq = m.get("liquidity_usd")
    if liq is None:
        r.unknowns.append("liquidity_unknown")
    elif liq < min_liq:
        r.reasons.append(f"liquidité {liq:,.0f} $ sous le minimum ({min_liq:,.0f} $)")

    l2m = _g(m, "liquidity", "liquidity_to_mc")
    age_h = (m.get("token_age_seconds") or 0) / 3600.0
    if l2m is None:
        if liq is not None and m.get("market_cap") is None:
            r.unknowns.append("market_cap_unknown")
    elif l2m < min_l2m:
        if age_h >= l2m_age_h:
            r.reasons.append(f"liquidité trop faible par rapport à la capitalisation ({l2m:.1%}, minimum {min_l2m:.0%})")
        else:
            r.warnings.append(f"liquidité faible par rapport à la capitalisation ({l2m:.1%}), token jeune ({age_h:.0f} h)")

    top10 = _g(m, "concentration", "top10_pct")
    eff10 = _g(m, "clusters", "effective_top10_pct")
    worst10 = max(v for v in (top10, eff10) if v is not None) if (top10 is not None or eff10 is not None) else None
    if worst10 is None:
        r.unknowns.append("concentration_unknown")
    elif worst10 > max_top10:
        r.reasons.append(f"les 10 plus gros porteurs détiennent {worst10:.0%} (maximum {max_top10:.0%})" + (" en regroupant les wallets liés" if eff10 is not None and eff10 > (top10 or 0) else ""))

    sec = m.get("security")
    if not sec:
        r.unknowns.append("security_unknown")
    else:
        checks = sec.get("checks", {})

        def st(name: str) -> str:
            return (checks.get(name) or {}).get("status", "UNKNOWN")

        if st("honeypot_indicators") == "FAIL":
            r.reasons.append("indices de piège confirmés (transferts bloqués, contrat en pause)")
            r.security_reject = True
        if st("transfer_simulation") == "FAIL":
            r.reasons.append("vente impossible : la simulation de transfert échoue")
            r.security_reject = True
        if st("mint_capability") == "FAIL":
            r.reasons.append("le propriétaire peut créer des tokens à volonté")
            r.security_reject = True
        if st("blacklist") == "FAIL":
            r.reasons.append("le contrat peut bloquer des adresses (blacklist)")
            r.security_reject = True
        if cfg.get("reject_on_security_fail", True) and sec.get("fails"):
            extra = [f for f in sec["fails"] if f not in ("honeypot_indicators", "transfer_simulation", "mint_capability", "blacklist")]
            if extra:
                r.reasons.append("sécurité en échec : " + ", ".join(extra))
                r.security_reject = True

    largest_cluster = _g(m, "clusters", "largest_cluster_pct")
    if largest_cluster is not None and largest_cluster > max_cluster:
        r.reasons.append(f"un groupe de wallets liés détient {largest_cluster:.0%} (maximum {max_cluster:.0%})")

    x_fmm = _g(m, "asymmetry", "x_from_first_meaningful_market")
    if x_fmm is not None and x_fmm > x_pen:
        r.warnings.append(f"déjà x{x_fmm:.0f} depuis le premier vrai marché : potentiel restant pénalisé")

    r.passed = not r.reasons and not r.unknowns
    return r
