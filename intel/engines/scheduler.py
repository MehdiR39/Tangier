"""Asyncio scheduler running the two engines on independent cadences with health reporting."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import signal
import time
from typing import Any

from intel.alerts.dedup import AlertDeduper
from intel.alerts.telegram import TelegramSender
from intel.context import IntelContext
from intel.engines.pipeline import TokenPipeline
from intel.engines.portfolio_watcher import run_portfolio_cycle
from intel.engines.scanner import Scanner
from intel.health import HealthServer, HealthState
from intel.metrics.pricing import QuotePricer
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)


class Runtime:
    def __init__(self, ctx: IntelContext) -> None:
        self.ctx = ctx
        self.pricer = QuotePricer(ctx)
        self.deduper = AlertDeduper(ctx.db, ctx.config.section("alerts"), ctx.chain_id)
        self.sender = TelegramSender(ctx.settings)
        self.pipeline = TokenPipeline(ctx, self.pricer, self.deduper, self.sender)
        self.scanner = Scanner(self.pipeline)
        self.health = HealthState(ctx)
        self._stop = asyncio.Event()
        self._boot = now_ts()          # the backup loop must not fire on a fresh start

    async def close(self) -> None:
        await self.sender.close()
        await self.ctx.close()

    async def _run_engine(self, name: str, fn: Any) -> dict[str, Any]:
        # Journaliser l ENTREE, pas seulement la sortie. Le 10/09 le moteur est reste muet vingt
        # minutes apres le demarrage : chaque cycle ne se signale qu une fois FINI, donc un cycle
        # qui ne finit jamais ne laisse aucune trace et on ne sait meme pas lequel c est. Une ligne
        # a l entree transforme « le moteur est bloque » en « ce cycle-la est bloque ».
        log.info("cycle %s demarre", name)
        started = now_ts()
        run_id = None
        if name == "t1":
            # A restart request (Telegram /restart, or the flag written by the operator's tooling)
            # ends the process cleanly; the container's restart policy brings it back on the
            # code and config now on disk. The operator is not always at the machine.
            try:
                if self.ctx.db.cursor_get("engine_restart_request"):
                    self.ctx.db.cursor_set("engine_restart_request", 0, now_ts())
                    log.warning("redemarrage demande : arret du processus, Docker le relance")
                    self._stop.set()
                    import os
                    await asyncio.sleep(1.0)
                    os._exit(0)
            except Exception as exc:  # noqa: BLE001
                log.info("drapeau de redemarrage illisible (%s)", str(exc)[:80])
        if name not in ("history", "digest", "backup", "retention", "t1", "telegram", "solana", "solana_carnet", "solana_prix_chaine", "solana_suivi_long", "telegram_rapide", "paliers"):  # keep engine_runs meaningful: real cycles only (t1 and telegram poll every few seconds)
            try:
                run_id = self.ctx.db.insert("engine_runs", {"engine": name, "started_ts": started, "finished_ts": None, "ok": None, "tokens_processed": None, "alerts_sent": None, "error": None, "stats_json": None})
            except Exception as exc:  # noqa: BLE001
                # Bookkeeping must never be able to stop the engine. On 2026-09-07 a long prune held
                # the database, this insert raised "database is locked" OUTSIDE the try below, the
                # exception left the loop, and the whole scheduler went down while the process
                # stayed alive with its HTTP clients closed: two hours of a dead engine that Docker
                # never restarted because it had not exited.
                log.warning("journal du cycle %s non écrit (%s) — le cycle continue", name, str(exc)[:80])
        t0 = time.monotonic()
        try:
            stats = await fn()
            ok = True
            err = None
        except Exception as exc:  # noqa: BLE001
            log.exception("%s cycle failed: %s", name, exc)
            stats = {}
            ok = False
            err = str(exc)[:500]
        tokens = stats.get("tokens") if isinstance(stats, dict) else None
        alerts = stats.get("alerts_sent") if isinstance(stats, dict) else None
        if name in ("scanner", "scanner_deep") and isinstance(stats, dict):
            tokens = (stats.get("stage3") or {}).get("evaluated")
            alerts = (stats.get("stage3") or {}).get("alerts_sent")
        slim = {k: v for k, v in (stats or {}).items() if k != "results"}
        if run_id is not None:
            self.ctx.db.execute("UPDATE engine_runs SET finished_ts=?, ok=?, tokens_processed=?, alerts_sent=?, error=?, stats_json=? WHERE id=?", (now_ts(), int(ok), tokens, alerts, err, json.dumps(slim, default=str)[:20000], run_id))
        self.health.record_run(name, ok, time.monotonic() - t0, err)
        quiet = (
            (name in ("history", "digest", "backup", "retention") and (stats or {}).get("status") in ("idle", "not_due", "disabled"))
            or (name == "execution" and not (stats or {}).get("seen"))   # an idle execution loop says nothing
            or (name == "t1" and not (stats or {}).get("decisions"))     # a 5-second poll only speaks when it buys
            or (name == "telegram" and not (stats or {}).get("answered"))  # and the command loop only when it answers
            or (name == "solana" and not (stats or {}).get("judged"))      # and the solana loop only when it judges
            or name == "solana_carnet"   # la tenue du carnet passe toutes les 5 s : elle ne parle
                                         # que par ses propres lignes (achat, vente, reconciliation)
        )
        if not quiet:
            log.info("%s cycle done ok=%s %.1fs stats=%s", name, ok, time.monotonic() - t0, json.dumps(slim, default=str)[:600])
        return stats or {}

    async def _loop(self, name: str, fn: Any, interval: int) -> None:
        while not self._stop.is_set():
            await self._run_engine(name, fn)
            delay = max(5.0, interval + random.uniform(-0.05, 0.05) * interval)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    async def digest_cycle(self) -> dict[str, Any]:
        """Once a day at ``alerts.daily_digest_hour_utc``: send the summary message."""
        from intel.engines.digest import digest_due, send_digest

        if not self.ctx.config.get("alerts.daily_digest_enabled", True):
            return {"status": "disabled"}
        hour = int(self.ctx.config.get("alerts.daily_digest_hour_utc", 7))
        if not digest_due(self.ctx, hour):
            return {"status": "not_due"}
        ok, err = await send_digest(self.ctx, self.sender)
        return {"status": "sent" if ok else "failed", "error": err, "alerts_sent": int(ok)}

    async def backup_cycle(self) -> dict[str, Any]:
        """Periodic online backup (static file, safe for host-side analysis) + rotation."""
        from intel.db.maintenance import rotate_backups

        from intel.db.maintenance import backup_path

        bdir = self.ctx.settings.backup_dir
        if not bdir or self.ctx.settings.db_path == ":memory:":
            return {"status": "disabled"}
        # Not at startup. Every loop runs its engine once immediately, so the backup used to begin
        # the moment the process came up -- and, being synchronous on the main thread, froze every
        # other loop for the 20-30 minutes an 8 GB copy takes (seen with py-spy, 2026-09-06).
        interval = int(self.ctx.config.get("engine.backup_interval_seconds", 6 * 3600))
        if now_ts() - self._boot < interval:
            return {"status": "not_due"}
        stamp = time.strftime("%Y%m%d-%H%M")
        dest = os.path.join(bdir, f"intel-{stamp}.sqlite")
        try:
            # a connection of its own, in a worker thread: the event loop keeps serving
            await asyncio.to_thread(backup_path, self.ctx.settings.db_path, dest)
            removed = rotate_backups(bdir, keep=int(self.ctx.config.get("engine.backup_keep", 4)))
            ok, msg = self.ctx.db.quick_check()
            return {"status": "ok" if ok else "integrity_warning", "file": dest, "removed": len(removed), "check": msg}
        except Exception as exc:  # noqa: BLE001
            log.exception("backup failed: %s", exc)
            return {"status": "failed", "error": str(exc)[:200]}

    async def regime_cycle(self) -> dict[str, Any]:
        """Refresh the market weather (BTC regime) that gates new buys."""
        from intel.metrics.regime import btc_regime

        r = await btc_regime(self.ctx, force=True)
        return {"regime": r.get("regime"), "return_90d": (r.get("evidence") or {}).get("return_90d")}

    async def retention_cycle(self) -> dict[str, Any]:
        from intel.db.retention import prune

        # La purge ATTEND le verrou au lieu d abandonner. Elle abandonnait des que le scanner le
        # tenait, or les cycles du scanner durent de 440 a 594 secondes et s enchainent : elle ne
        # l obtenait donc quasiment jamais et rendait la main en 0,0 seconde. Resultat mesure le
        # 08/09/2026 : la base a atteint 22,2 Go, et la verification d integrite qu elle declenche
        # au demarrage a laisse le moteur muet vingt minutes, positions ouvertes et Telegram
        # silencieux. Elle ne tourne que quatre fois par jour : la faire patienter ne retarde rien.
        # La purge ne prend PAS le verrou d ingestion. Ce verrou fait alterner les ingestions qui
        # tapent le RPC ; la purge ne fait aucun appel reseau, elle n a rien a y faire. Deux essais
        # ont echoue avant d en arriver la, le 08/09/2026 : abandonner quand le verrou etait pris la
        # renvoyait a 0,0 s (les cycles du scanner durent 145 a 594 s et s enchainent), puis attendre
        # que `priority_waiting` retombe a zero ne marchait pas davantage -- ce compteur suit les
        # evaluations de portefeuille et reste positif presque en permanence. Pendant ce temps la
        # base montait a 22,2 Go et son controle d integrite au demarrage a laisse le moteur muet
        # vingt minutes.
        #
        # A la place elle cede le pas entre deux jetons : une evaluation prioritaire attend au pire
        # la suppression d un jeton, pas une passe entiere. Le travail tourne dans un fil pour ne pas
        # bloquer la boucle, ce que la connexion partagee autorise (check_same_thread=False).
        def cede() -> None:
            for _ in range(60):
                if self.pipeline.priority_waiting == 0:
                    return
                time.sleep(0.5)

        return await asyncio.to_thread(prune, self.ctx, cede)

    async def execution_cycle(self) -> dict[str, Any]:
        """Turn decisions into orders. Dry run by default: builds and checks, sends nothing."""
        from intel.execution.executor import run_once

        if not self.ctx.config.get("execution.enabled", True):
            return {"status": "disabled"}
        return await run_once(self.ctx)

    async def history_cycle(self) -> dict[str, Any]:
        """Low-priority loop: complete launch-to-date history for one token per cycle."""
        blocks = int(self.ctx.config.get("engine.history_blocks_per_cycle", 40_000))
        if self.pipeline.priority_waiting > 0 or self.pipeline.ingest_lock.locked():
            return {"tokens": 0, "status": "idle", "reason": "engine cycle active"}  # never delay live evaluation
        todo = self.pipeline.tokens_needing_history(limit=1)
        if not todo:
            return {"tokens": 0, "status": "idle"}
        token = todo[0]
        res = await self.pipeline.backfill_history(token, max_blocks=blocks)
        return {"tokens": 1, "token": token, **{k: v for k, v in res.items() if k != "wallets"}}

    async def run(self, *, portfolio: bool = True, scanner: bool = True, once: bool = False) -> None:
        if once:
            if portfolio:
                await self._run_engine("portfolio", lambda: run_portfolio_cycle(self.pipeline))
            if scanner:
                await self._run_engine("scanner", self.scanner.run_cycle)
            return
        server = HealthServer(self.health, self.ctx.settings.health_port)
        server.start()
        loop = asyncio.get_running_loop()
        for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
            if sig is None:
                continue
            try:
                loop.add_signal_handler(sig, self._stop.set)
            except (NotImplementedError, RuntimeError):  # Windows: handled via KeyboardInterrupt
                pass
        tasks = []
        if portfolio:
            tasks.append(asyncio.create_task(self._loop("portfolio", lambda: run_portfolio_cycle(self.pipeline), int(self.ctx.config.get("engine.portfolio_cycle_seconds", 60)))))
        if scanner:
            # Two loops on purpose: the cheap triage must never queue behind a stage-3 token that
            # is backfilling half a million blocks.
            tasks.append(asyncio.create_task(self._loop("scanner", self.scanner.triage_cycle, int(self.ctx.config.get("engine.scanner_cycle_seconds", 120)))))
            tasks.append(asyncio.create_task(self._loop("scanner_deep", self.scanner.deep_cycle, int(self.ctx.config.get("engine.scanner_deep_cycle_seconds", 300)))))
        tasks.append(asyncio.create_task(self._loop("execution", self.execution_cycle, int(self.ctx.config.get("execution.cycle_seconds", 30)))))
        tasks.append(asyncio.create_task(self._loop("history", self.history_cycle, int(self.ctx.config.get("engine.history_cycle_seconds", 45)))))
        tasks.append(asyncio.create_task(self._loop("digest", self.digest_cycle, 120)))
        tasks.append(asyncio.create_task(self._loop("backup", self.backup_cycle, int(self.ctx.config.get("engine.backup_interval_seconds", 6 * 3600)))))
        tasks.append(asyncio.create_task(self._loop("retention", self.retention_cycle, int(self.ctx.config.get("retention.prune_interval_seconds", 6 * 3600)))))
        tasks.append(asyncio.create_task(self._loop("regime", self.regime_cycle, 3600)))
        if self.ctx.config.get("t1.enabled", False):
            # The only entry rule that survived out-of-sample testing lives at T+60 s after a
            # pool's first swap. It cannot ride the scanner's minutes-long path, so it gets its own
            # two-second loop. Opt-in, small tickets, writes decisions only -- never signs.
            from intel.engines.t1_watcher import T1Watcher
            self.t1 = T1Watcher(self.ctx)
            tasks.append(asyncio.create_task(self._loop("t1", self.t1.run_cycle, int(self.ctx.config.get("t1.poll_seconds", 2)))))
        if self.ctx.config.get("solana.enabled", False):
            # The same book on another chain: discover, judge the first minute, buy, sell on the
            # clock. Its thresholds are deliberately uncalibrated until the measurement gives them,
            # and it signs nothing without a key AND solana.mode set to live.
            from intel.engines.solana_watcher import SolanaWatcher
            self.solana = SolanaWatcher(self.ctx)
            tasks.append(asyncio.create_task(self._loop("solana", self.solana.run_cycle,
                                                        int(self.ctx.config.get("solana.poll_seconds", 30)))))
            # La tenue du carnet a sa propre boucle, bien plus rapide que la decouverte. Elle etait
            # la queue de `run_cycle` et ne passait donc qu apres le jugement des lancements, soit
            # toutes les 35 a 95 s -- une eternite pour un stop de perte. Voir SolanaWatcher.run_carnet.
            tasks.append(asyncio.create_task(self._loop("solana_carnet", self.solana.run_carnet,
                                                        int(self.ctx.config.get("solana.book_poll_seconds", 5)))))
            # Le prix lu dans les reserves du pool, des la creation. DexScreener n indexe pas ces
            # pools avant ~T+1,5 min -- 6 sur 74 en une heure -- et se rafraichit toutes les 30 a
            # 60 s, ce qui rend toute rejouee de sortie deux fois trop pessimiste (§3.61) et laisse
            # la zone T+0 a T+1,5 min totalement inobservee. Ce collecteur n achete rien : il ecrit
            # une serie de prix a la cadence qu on veut, sans agregateur.
            if self.ctx.config.get("solana.prix_chaine.enabled", True):
                from intel.engines.prix_chaine import PrixChaine
                self.prix_chaine = PrixChaine(self.ctx, self.solana.client)
                tasks.append(asyncio.create_task(self._loop(
                    "solana_prix_chaine", self.prix_chaine.cycle,
                    int(self.ctx.config.get("solana.prix_chaine.pas_secondes", 10)))))
            # Le suivi de LONGUE duree : 24 h par lancement, pas 30 min. L operateur a tenu un jeton
            # quatre heures pour x3,13 la ou le moteur vendait a 30 min ; l ecran montre des jetons a
            # +400 % dix-sept heures apres leur naissance. Toute la recherche s arretait avant.
            # Ce collecteur n achete rien. Voir intel/engines/suivi_long.py.
            if self.ctx.config.get("solana.suivi_long.enabled", True):
                from intel.engines.suivi_long import SuiviLong
                self.suivi_long = SuiviLong(self.ctx, self.solana.client)
                tasks.append(asyncio.create_task(self._loop(
                    "solana_suivi_long", self.suivi_long.cycle,
                    int(self.ctx.config.get("solana.suivi_long.pas_secondes", 30)))))
            if self.ctx.config.get("solana.stream.enabled", False):
                # Ecoute des creations de pool en direct, a cote de DexScreener et non a sa place :
                # la source promotionnelle ne montre que 4,3 des ~20 graduations horaires. Elle
                # n achete rien, elle depose des jetons dans une table que la decouverte lit.
                from intel.engines.solana_stream import SolanaStream
                self.solana_stream = SolanaStream(self.ctx)
                tasks.append(asyncio.create_task(self._loop(
                    "solana_stream", self.solana_stream.run_cycle,
                    int(self.ctx.config.get("solana.stream.pause_seconds", 5)))))
        # Vendre chaque jeton detenu des qu il touche un nouveau sommet historique -- regle posee
        # par l operateur le 11/09, apres la nuit ou une vente demandee n est pas partie (S5.24).
        # Il tourne a part et en continu justement pour ne plus dependre d une passe lente.
        # Vendre une ligne nommee par tranches, a des multiples du prix d entree. Boucle a part et
        # tres rapide : l operateur a demande cinq secondes pour ne pas rater un pic nocturne.
        if self.ctx.config.get("paliers_vente.enabled", False):
            from intel.engines.paliers import Paliers
            import httpx as _hx
            self.paliers = Paliers(self.ctx, getattr(getattr(self, "solana", None), "client", None)
                                   or _hx.AsyncClient(headers={"User-Agent": "tangier-intel/paliers"}))
            tasks.append(asyncio.create_task(self._loop(
                "paliers", self.paliers.cycle,
                int(self.ctx.config.get("paliers_vente.pas_secondes", 5)))))
        # Acheter un lancement qui a un Telegram, le revendre quatre minutes plus tard. Boucle a
        # part et rapide : la fenetre d entree ne dure que cent secondes et la sortie est a la
        # minute pres. Voir intel/engines/telegram_rapide.py pour la mesure qui la justifie.
        if self.ctx.config.get("telegram_rapide.enabled", False):
            from intel.engines.telegram_rapide import TelegramRapide
            import httpx as _hxt
            self.tg_rapide = TelegramRapide(
                self.ctx, getattr(getattr(self, "solana", None), "client", None)
                or _hxt.AsyncClient(headers={"User-Agent": "tangier-intel/tg"}))
            tasks.append(asyncio.create_task(self._loop(
                "telegram_rapide", self.tg_rapide.cycle,
                int(self.ctx.config.get("telegram_rapide.pas_secondes", 10)))))
        if self.ctx.config.get("ath.enabled", False):
            from intel.engines.ath import Ath
            self.ath = Ath(self.ctx, self.solana.client if hasattr(self, "solana") else None)
            if self.ath.client is None:
                import httpx as _httpx
                self.ath.client = _httpx.AsyncClient(headers={"User-Agent": "tangier-intel/ath"})
            tasks.append(asyncio.create_task(self._loop(
                "ath", self.ath.cycle, int(self.ctx.config.get("ath.pas_secondes", 30)))))
        if self.ctx.config.get("alerts.telegram_commands", True):
            # /positions, /closed, /pnl, /orders, /solde, /pause, /resume from the phone. Reads a
            # second bot (INTEL_TELEGRAM_COMMANDS_TOKEN): Telegram allows one reader per bot and
            # the alerts bot is already read by the older watcher container. Idle without a token.
            from intel.alerts.commands import TelegramCommands
            self.commands = TelegramCommands(self.ctx, self.sender, t1=getattr(self, "t1", None))
            tasks.append(asyncio.create_task(self._loop("telegram", self.commands.run_cycle, 5)))
        try:
            # return_exceptions: one loop dying must not tear the others down mid-flight. Each is
            # reported, and the engine keeps the rest of its work running.
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for task, res in zip(tasks, results):
                if isinstance(res, BaseException) and not isinstance(res, asyncio.CancelledError):
                    log.error("une boucle s'est arrêtée: %s", res)
        except (KeyboardInterrupt, asyncio.CancelledError):
            self._stop.set()
        finally:
            # Whatever brought us here, nothing must keep spinning against closed clients: cancel
            # what is left before the context is torn down, then leave for good.
            self._stop.set()
            for t in tasks:
                if not t.done():
                    t.cancel()
            server.stop()
