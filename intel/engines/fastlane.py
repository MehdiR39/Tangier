"""Buy on the signal that was measured, without waiting for the analysis that was not.

Why this exists: the deep pass evaluates about 96 tokens an hour against a queue of 14 000, so a
token that becomes tradeable waits hours for a score while its window — a median of six minutes —
closes. Measured 2026-09-04: the scanner now spots 100 % of the tokens that become tradeable, and
scores 0 % of them in time.

What the measurements actually support:
- the edge comes from the entry threshold (real traded volume) and the exit rule, not from the
  composite score, which was only ever shown to rank *among* eligible tokens;
- the security checks are the one filter shown to avoid total losses.

So this lane requires exactly those two things and nothing else. The score keeps running behind it
and still governs everything else; this only decides whether a token is worth 20 EUR now.

Every guard from the ordinary decision path is repeated here, deliberately: a faster path must not
be a laxer one.
"""
from __future__ import annotations

import logging
from typing import Any

from intel import MODEL_VERSION
from intel.context import IntelContext
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)


class Skip(Exception):
    """Raised with the reason a token is not taken. Recorded, never silent."""


def _guard(ctx: IntelContext, token: str, cfg: dict[str, Any], volume_usd: float) -> None:
    if not cfg.get("fastlane_enabled", True):
        raise Skip("voie rapide désactivée")
    floor = float(cfg.get("fastlane_min_volume_usd", 2000.0))
    if volume_usd < floor:
        raise Skip(f"volume {volume_usd:,.0f} $/h < {floor:,.0f} $/h")
    if ctx.is_system(token) or token in ctx.config.quote_assets:
        raise Skip("adresse système ou actif de cotation")
    if ctx.db.query_one("SELECT 1 FROM positions WHERE chain_id=? AND token_address=? AND status IN ('OPEN','HALF')", (ctx.chain_id, token)):
        raise Skip("position déjà ouverte")
    cooldown = int(cfg.get("rebuy_cooldown_seconds", 3 * 86400))
    if ctx.db.query_one("SELECT 1 FROM positions WHERE chain_id=? AND token_address=? AND closed_ts>?", (ctx.chain_id, token, now_ts() - cooldown)):
        raise Skip("déjà joué récemment")
    n_open = ctx.db.scalar("SELECT COUNT(*) FROM positions WHERE chain_id=? AND status IN ('OPEN','HALF')", (ctx.chain_id,), 0)
    if n_open >= int(cfg.get("max_open", 15)):
        raise Skip(f"{n_open} positions déjà ouvertes")
    last = ctx.db.query_one("SELECT kind, ts FROM decisions WHERE chain_id=? AND token_address=? ORDER BY id DESC LIMIT 1", (ctx.chain_id, token))
    if last and last["kind"] == "BUY" and now_ts() - int(last["ts"]) < int(cfg.get("repeat_guard_seconds", 86400)):
        raise Skip("achat déjà conseillé récemment")


def _age_ok(ctx: IntelContext, token: str, cfg: dict[str, Any]) -> float | None:
    """Hours since the token's first pool was created, or None when unknown (which is a refusal)."""
    created = ctx.db.scalar("SELECT MIN(created_ts) FROM pairs WHERE chain_id=? AND token_address=? AND created_ts IS NOT NULL", (ctx.chain_id, token))
    if created is None:
        raise Skip("âge inconnu")
    age_h = (now_ts() - int(created)) / 3600.0
    if age_h > float(cfg.get("fastlane_max_age_hours", 48)):
        raise Skip(f"âge {age_h:.0f} h > {float(cfg.get('fastlane_max_age_hours', 48)):.0f} h")
    if age_h * 60 < float(cfg.get("fastlane_min_age_minutes", 10)):
        raise Skip("trop récent pour juger")
    return age_h


async def consider(ctx: IntelContext, token: str, volume_usd: float, price_usd: float | None) -> dict[str, Any] | None:
    """Decide whether to buy this token right now. Returns the decision, or None with a reason logged."""
    from intel.ingest.pools import load_pools
    from intel.ingest.security import run_security_checks  # local import: heavy module

    token = token.lower()
    cfg = ctx.config.section("decisions")
    try:
        _guard(ctx, token, cfg, volume_usd)
        age_h = _age_ok(ctx, token, cfg)
        if not price_usd or price_usd <= 0:
            raise Skip("prix inconnu")
        pools = load_pools(ctx, token)
        if not pools:
            raise Skip("aucun pool résolu")
        report = await run_security_checks(ctx, token, pools)
        if report.fails:
            raise Skip("sécurité: " + ", ".join(c.name for c in report.fails))
        # Unknown is never treated as safe: a token we could not check is not bought.
        if not report.checks:
            raise Skip("sécurité non vérifiable")
        max_unknown = int(cfg.get("fastlane_max_unknown_checks", 2))
        if len(report.unknowns) > max_unknown:
            raise Skip(f"{len(report.unknowns)} contrôles de sécurité sans réponse")
    except Skip as s:
        log.info("voie rapide, %s écarté : %s", token[:10], s)
        return None

    size = float(cfg.get("size_eur", 20.0))
    label = ctx.db.scalar("SELECT symbol FROM tokens WHERE chain_id=? AND address=?", (ctx.chain_id, token)) or token[:10]
    pid = ctx.db.insert("positions", {
        "chain_id": ctx.chain_id, "token_address": token, "label": label, "kind": "VIRTUAL", "opened_ts": now_ts(),
        "entry_price": price_usd, "size_eur": size, "status": "OPEN", "peak_price": price_usd,
        "model_version": MODEL_VERSION, "notes": "voie rapide",
    })
    reason = (f"{volume_usd:,.0f} $ échangés dans l'heure, contrat sain, {age_h:.0f} h d'existence — "
              f"acheté sans attendre l'analyse complète")
    from intel.engines.decisions import _record

    rec = _record(ctx, token, label, "BUY", reason, price_usd, size, pid, {"liquidity_usd": volume_usd}, None)
    rec["plan"] = {"take_profit": float(cfg.get("take_profit_multiple", 1.5)),
                   "timeout_h": float(cfg.get("timeout_hours", 3)),
                   "sells_all": bool(cfg.get("take_profit_sells_all", True))}
    log.info("voie rapide, ACHAT %s (%s) : %s", label, token[:10], reason)
    return rec


async def run(ctx: IntelContext, hot: dict[str, float], prices: dict[str, float], *, limit: int = 5) -> dict[str, Any]:
    """Consider the most heavily traded tokens of the last sweep, busiest first."""
    out: list[dict[str, Any]] = []
    for token, vol in sorted(hot.items(), key=lambda kv: -kv[1])[:limit]:
        rec = await consider(ctx, token, vol, prices.get(token))
        if rec:
            out.append(rec)
    return {"considered": min(limit, len(hot)), "bought": len(out), "decisions": out}
