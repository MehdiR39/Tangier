"""Data retention: drop raw event history of dead scanner tokens and old dense snapshots.

Portfolio tokens and ACTIVE scanner tokens keep everything (their history is what the
metrics are built from). REJECTED / DORMANT scanner tokens are cheap to re-ingest if they
ever come back, so their transfers/swaps/trades/holders are removed after ``dead_token_days``.
Scores, alerts, decisions and token-level snapshots are never pruned (backtests need them).
"""
from __future__ import annotations

import logging
import time
from typing import Any

from intel.context import IntelContext
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)

RAW_TABLES = ("transfers", "swap_events", "liquidity_events", "trades", "holders", "holder_snapshots", "holder_count_snapshots", "wallet_flows", "wallet_token_positions")


def prune(ctx: IntelContext) -> dict[str, Any]:
    cfg = ctx.config.section("retention")
    now = now_ts()
    dead_before = now - int(cfg.get("dead_token_days", 2)) * 86400
    stats: dict[str, Any] = {"tokens": 0}
    # "Dead" used to mean "a scanner candidate marked REJECTED or DORMANT". The T+1 watcher never
    # files its tokens as candidates, so its pools -- hundreds a day, each followed for six hours --
    # were never pruned and the database reached 15.7 GB by 2026-09-07, past the size at which a
    # backup can finish between two restarts. A token is dead when nothing points at it any more:
    # no active portfolio line, no open position, no live scanner candidate, and no swap in any of
    # its pools for `dead_token_days`. Pruning is all-or-nothing per token because the metrics read
    # whole histories (MIN(ts) for the launch date, every transfer for wallet clusters); half a
    # history would quietly produce wrong numbers rather than missing ones.
    # On part des jetons qui PESENT, pas de ceux qui existent. Mesure du 08/09/2026 : sur 400
    # candidats tires de `pairs`, UN SEUL portait des donnees -- le scanner voit bien plus de pools
    # qu il n en ingere, donc la purge fouillait des coquilles vides et ne liberait rien pendant que
    # la base atteignait 22,2 Go. Les huit jetons les plus lourds totalisent a eux seuls 5,1 des
    # 16,4 millions de transferts, dont un a 1,5 million.
    #
    # Le regroupement coute 23 s sur l index (chain_id, token_address) -- acceptable pour un travail
    # qui tourne toutes les deux heures, et sans commune mesure avec ce qu il libere. Les gardes qui
    # suivent restent les memes : rien n est supprime tant qu une ligne de portefeuille, une
    # position ouverte, un candidat vivant ou un echange recent pointe vers le jeton.
    lourds = [r["token_address"] for r in ctx.db.query(
        "SELECT token_address, COUNT(*) n FROM transfers WHERE chain_id=? AND token_address IS NOT NULL "
        "GROUP BY token_address ORDER BY n DESC LIMIT ?",
        (ctx.chain_id, int(cfg.get("scan_tokens_per_prune", 4000))),
    )]
    vivants = {r["token_address"] for r in ctx.db.query(
        "SELECT token_address FROM portfolio_positions WHERE chain_id=? AND active=1 "
        "UNION SELECT token_address FROM positions WHERE chain_id=? AND status IN ('OPEN','HALF') "
        "UNION SELECT token_address FROM scanner_candidates WHERE chain_id=? "
        "  AND status NOT IN ('REJECTED','DORMANT')",
        (ctx.chain_id, ctx.chain_id, ctx.chain_id))}
    candidates = []
    for token in lourds:
        if token in vivants:
            continue
        recent = ctx.db.scalar(
            "SELECT MAX(s.ts) FROM swap_events s JOIN pairs p ON p.chain_id=s.chain_id AND p.pair_id=s.pair_id "
            "WHERE s.chain_id=? AND p.token_address=?", (ctx.chain_id, token), 0) or 0
        if int(recent) < dead_before:
            candidates.append(token)
        if len(candidates) >= int(cfg.get("max_tokens_per_prune", 60)) * 3:
            break
    stats["candidats_lourds"] = len(candidates)

    if not candidates:
        candidates = [r["token_address"] for r in ctx.db.query(
        # Start from `pairs` (113 k rows), never from `transfers` (13 M): a DISTINCT over the big
        # table with a correlated NOT EXISTS took over half an hour on 2026-09-07 and never
        # finished, where this answers in a tenth of a second.
        "SELECT p.token_address FROM pairs p "
        "WHERE p.chain_id=? AND p.token_address IS NOT NULL "
        "  AND p.token_address NOT IN (SELECT token_address FROM portfolio_positions WHERE chain_id=? AND active=1) "
        "  AND p.token_address NOT IN (SELECT token_address FROM positions WHERE chain_id=? AND status IN ('OPEN','HALF')) "
        "  AND p.token_address NOT IN (SELECT token_address FROM scanner_candidates WHERE chain_id=? AND status NOT IN ('REJECTED','DORMANT')) "
        "GROUP BY p.token_address "
        "HAVING COALESCE(MAX((SELECT MAX(s.ts) FROM swap_events s WHERE s.chain_id=p.chain_id AND s.pair_id=p.pair_id)), 0) < ? "
        "LIMIT ?",
        (ctx.chain_id, ctx.chain_id, ctx.chain_id, ctx.chain_id, dead_before,
         int(cfg.get("scan_tokens_per_prune", 4000))),
    )]
    # Most dead pools carry no rows at all -- the scanner sees far more pools than it ever ingests --
    # so a batch picked blindly frees nothing (60 tokens, 100 rows, 2026-09-07). Keep the ones that
    # actually hold data; the check is one indexed lookup per token.
    dead: list[str] = []
    limit = int(cfg.get("max_tokens_per_prune", 60))
    for token in candidates:
        if ctx.db.scalar("SELECT 1 FROM transfers WHERE chain_id=? AND token_address=? LIMIT 1", (ctx.chain_id, token)):
            dead.append(token)
            if len(dead) >= limit:
                break
    # Par tranches, jamais d un bloc. Le jeton le plus lourd porte 1,5 million de transferts : les
    # effacer en une transaction tiendrait le verrou d ecriture plusieurs minutes, et le carnet a
    # besoin de ce meme verrou pour enregistrer une vente. Une tranche se valide en une fraction de
    # seconde et rend la main entre deux. Si le processus meurt au milieu d un jeton il reste une
    # histoire partielle -- sans consequence, puisque seul un jeton mort arrive ici et que plus rien
    # ne le lit; la purge suivante le retrouvera en tete de liste et finira le travail.
    # Et borne dans le temps, pas en nombre de jetons : la purge tient le verrou d ingestion pendant
    # qu elle travaille, donc ce qui compte est la duree, pas le compte. Un budget rend le cycle
    # previsible quel que soit le poids des jetons tires -- ce qui n est pas fini ce tour-ci le sera
    # au suivant, les plus lourds restant en tete de liste.
    TRANCHE = 20_000
    budget = float(cfg.get("prune_budget_seconds", 180))
    debut = time.monotonic()
    for token in dead:
        if time.monotonic() - debut > budget:
            stats["budget_atteint"] = True
            break
        for t in RAW_TABLES:
            if t in ("swap_events", "liquidity_events"):
                sel = (f"SELECT rowid FROM {t} WHERE chain_id=? AND pair_id IN "
                       f"(SELECT pair_id FROM pairs WHERE chain_id=? AND token_address=?) LIMIT {TRANCHE}")
                args: tuple = (ctx.chain_id, ctx.chain_id, token)
            else:
                sel = f"SELECT rowid FROM {t} WHERE chain_id=? AND token_address=? LIMIT {TRANCHE}"
                args = (ctx.chain_id, token)
            while True:
                with ctx.db.transaction():
                    n = ctx.db.execute(f"DELETE FROM {t} WHERE rowid IN ({sel})", args).rowcount
                stats[t] = stats.get(t, 0) + n
                if n < TRANCHE:
                    break
        with ctx.db.transaction():
            for name in ("transfers", "pools", "trades", "transfers_back", "transfers_fwd_start", "transfers_rebuilt"):
                ctx.db.execute("DELETE FROM sync_cursors WHERE name=?", (f"{name}:{token}",))
        stats["tokens"] += 1
    # dense snapshots: keep a rolling window for everyone (point-in-time metrics use recent data only)
    hs_before = now - int(cfg.get("holder_snapshot_days", 7)) * 86400
    ps_before = now - int(cfg.get("pair_snapshot_days", 14)) * 86400
    with ctx.db.transaction():
        stats["holder_snapshots_old"] = ctx.db.execute("DELETE FROM holder_snapshots WHERE chain_id=? AND ts<?", (ctx.chain_id, hs_before)).rowcount
        stats["pair_snapshots_old"] = ctx.db.execute(
            "DELETE FROM pair_snapshots WHERE chain_id=? AND ts<? AND token_address NOT IN (SELECT token_address FROM portfolio_positions WHERE chain_id=? AND active=1)", (ctx.chain_id, ps_before, ctx.chain_id)
        ).rowcount
    log.info("retention prune done: %s", stats)
    return stats
