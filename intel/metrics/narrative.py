"""Narrative / catalyst score from metadata only. Kept separate from on-chain scores and
never allowed to override a critical security failure (enforced in scoring)."""
from __future__ import annotations

from typing import Any


def narrative_score(pairs: list[dict[str, Any]], *, profile: dict[str, Any] | None = None, boosts_active: int | None = None, quote_symbol: str | None = None, age_seconds: int | None = None) -> tuple[float, dict[str, Any]]:
    websites: set[str] = set()
    socials: dict[str, str] = {}
    image = None
    for p in pairs:
        for w in p.get("websites") or []:
            if w:
                websites.add(w)
        for s in p.get("socials") or []:
            if s.get("url"):
                socials[s.get("type") or "link"] = s["url"]
        image = image or p.get("image_url")
        if boosts_active is None and p.get("boosts_active") is not None:
            boosts_active = int(p["boosts_active"])
    score = 20.0
    ev: dict[str, Any] = {"websites": sorted(websites), "socials": socials, "has_profile": bool(profile or image), "boosts_active": boosts_active, "quote_symbol": quote_symbol}
    if websites:
        score += 15
    if "twitter" in socials:
        score += 15
    if "telegram" in socials or "discord" in socials:
        score += 10
    if profile or image:
        score += 10
    if boosts_active:
        score += min(15, 5 + boosts_active)  # paid attention: mild, capped
        ev["note"] = "boosts are paid promotion, not organic interest"
    # quote asset narrative: tokenised-stock pairs (MSTR/SPY/TSM/NVDA) on Robinhood Chain
    if quote_symbol and quote_symbol.upper() not in ("USDG", "USDC", "USDT", "WETH", "ETH"):
        score += 5
        ev["quote_narrative"] = quote_symbol
    if age_seconds is not None and age_seconds < 6 * 3600:
        score -= 5  # too new for narrative to have formed
    return max(0.0, min(100.0, score)), ev
