"""Data retention: drop raw event history of dead scanner tokens and old dense snapshots.

Portfolio tokens and ACTIVE scanner tokens keep everything (their history is what the
metrics are built from). REJECTED / DORMANT scanner tokens are cheap to re-ingest if they
ever come back, so their transfers/swaps/trades/holders are removed after ``dead_token_days``.
Scores, alerts, decisions and token-level snapshots are never pruned (backtests need them).
"""
from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable
from typing import Any

from intel.context import IntelContext
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)

RAW_TABLES = ("transfers", "swap_events", "liquidity_events", "trades", "holders", "holder_snapshots", "holder_count_snapshots", "wallet_flows", "wallet_token_positions")


def prune(ctx: IntelContext, cede: Callable[[], None] | None = None) -> dict[str, Any]:
    """``cede`` est appele entre deux jetons : il rend la main au travail prioritaire."""
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
    # Le regroupement coute 23 s sur l index (chain_id, token_address) -- sans commune mesure avec ce
    # qu il libere, et paye sur une connexion a part (voir plus bas) donc il ne gene personne. Les
    # gardes ne bougent pas : rien n est supprime tant qu une ligne de portefeuille, une position
    # ouverte, un candidat vivant ou un echange recent pointe vers le jeton.
    #
    # La selection passe par une connexion en lecture seule a elle, jamais par ctx.db : le verrou
    # interne de la connexion partagee est pris pour la duree de CHAQUE requete, donc un
    # regroupement de 23 s bloquerait tout ce qui touche la base pendant 23 s -- carnets et Telegram
    # compris. En WAL un lecteur separe ne gene personne. Les suppressions, elles, restent sur la
    # connexion partagee : chaque tranche se valide en une fraction de seconde.
    candidates: list[str] = []
    if ctx.db.path != ":memory:":
        ro = sqlite3.connect(f"file:{ctx.db.path}?mode=ro", uri=True, timeout=30)
        ro.row_factory = sqlite3.Row
        try:
            vivants = {r[0] for r in ro.execute(
                "SELECT token_address FROM portfolio_positions WHERE chain_id=? AND active=1 "
                "UNION SELECT token_address FROM positions WHERE chain_id=? AND status IN ('OPEN','HALF') "
                "UNION SELECT token_address FROM scanner_candidates WHERE chain_id=? "
                "  AND status NOT IN ('REJECTED','DORMANT')",
                (ctx.chain_id, ctx.chain_id, ctx.chain_id))}
            plafond = int(cfg.get("max_tokens_per_prune", 60)) * 3
            t0 = time.monotonic()
            lourds = ro.execute(
                "SELECT token_address, COUNT(*) n FROM transfers WHERE chain_id=? AND token_address IS NOT NULL "
                "GROUP BY token_address ORDER BY n DESC LIMIT ?",
                (ctx.chain_id, int(cfg.get("scan_tokens_per_prune", 4000))),
            ).fetchall()
            log.info("purge : %d jetons pesants listes en %.0f s", len(lourds), time.monotonic() - t0)
            # "Mort" se lit sur `transfers`, pas sur une jointure swap_events/pairs : l index
            # (chain_id, token_address, ts) rend le MAX immediat, la jointure non. Un jeton sans
            # aucun transfert depuis `dead_token_days` n a evidemment aucun echange non plus.
            # La selection est bornee dans le temps comme la suppression : le 08/09/2026 elle a
            # tourne plus d un quart d heure sans rien supprimer NI rien dire, ce qui est le meme
            # defaut que celui qui a coute vingt minutes de service la veille.
            t0 = time.monotonic()
            for row in lourds:
                token = row[0]
                if token in vivants:
                    continue
                recent = ro.execute("SELECT MAX(ts) FROM transfers WHERE chain_id=? AND token_address=?",
                                    (ctx.chain_id, token)).fetchone()[0] or 0
                if int(recent) < dead_before:
                    candidates.append(token)
                if len(candidates) >= plafond or time.monotonic() - t0 > 60:
                    break
            stats["candidats_lourds"] = len(candidates)
            log.info("purge : %d candidats retenus en %.0f s", len(candidates), time.monotonic() - t0)
            if not candidates:
                # Quand plus aucun jeton lourd n est mort, on retombe sur l ancienne selection :
                # elle part de `pairs` (113 k lignes) et jamais de `transfers` (16 M), un DISTINCT
                # sur la grande table avec un NOT EXISTS correle ayant tourne plus d une demi-heure
                # sans finir le 07/09/2026.
                candidates = [r[0] for r in ro.execute(
                    "SELECT p.token_address FROM pairs p "
                    "WHERE p.chain_id=? AND p.token_address IS NOT NULL "
                    "  AND p.token_address NOT IN (SELECT token_address FROM portfolio_positions WHERE chain_id=? AND active=1) "
                    "  AND p.token_address NOT IN (SELECT token_address FROM positions WHERE chain_id=? AND status IN ('OPEN','HALF')) "
                    "  AND p.token_address NOT IN (SELECT token_address FROM scanner_candidates WHERE chain_id=? AND status NOT IN ('REJECTED','DORMANT')) "
                    "GROUP BY p.token_address "
                    "HAVING COALESCE(MAX((SELECT MAX(s.ts) FROM swap_events s WHERE s.chain_id=p.chain_id AND s.pair_id=p.pair_id)), 0) < ? "
                    "LIMIT ?",
                    (ctx.chain_id, ctx.chain_id, ctx.chain_id, ctx.chain_id, dead_before,
                     int(cfg.get("scan_tokens_per_prune", 4000))))]
        finally:
            ro.close()
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
    # Et borne dans le temps, pas en nombre de jetons : ce qui compte est la duree pendant laquelle
    # la purge sollicite la base, pas le nombre de jetons tires. Un budget rend la passe previsible
    # quel que soit leur poids -- ce qui n est pas fini ce tour-ci le sera au suivant, les plus
    # lourds restant en tete de liste.
    TRANCHE = 20_000
    budget = float(cfg.get("prune_budget_seconds", 180))
    debut = time.monotonic()
    log.info("purge : suppression de %d jeton(s)", len(dead))
    for token in dead:
        if cede is not None:
            cede()
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
                # Le budget se verifie aussi ENTRE DEUX TRANCHES, pas seulement entre deux jetons :
                # le 08/09/2026 le premier jeton pesait 2,67 millions de lignes et sa suppression a
                # tenu neuf minutes pour un budget de trois. Une histoire a moitie effacee sur un
                # jeton mort ne gene rien, et la passe suivante la reprend en tete de liste.
                if n < TRANCHE or time.monotonic() - debut > budget:
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
