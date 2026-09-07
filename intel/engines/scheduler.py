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
        if name not in ("history", "digest", "backup", "retention", "t1", "telegram"):  # keep engine_runs meaningful: real cycles only (t1 and telegram poll every few seconds)
            run_id = self.ctx.db.insert("engine_runs", {"engine": name, "started_ts": started, "finished_ts": None, "ok": None, "tokens_processed": None, "alerts_sent": None, "error": None, "stats_json": None})
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

        if self.pipeline.priority_waiting > 0 or self.pipeline.ingest_lock.locked():
            return {"status": "idle", "reason": "engine cycle active"}
        async with self.pipeline.ingest_lock:
            return prune(self.ctx)

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
        if self.ctx.config.get("alerts.telegram_commands", True):
            # /positions, /closed, /pnl, /orders, /solde, /pause, /resume from the phone. Reads a
            # second bot (INTEL_TELEGRAM_COMMANDS_TOKEN): Telegram allows one reader per bot and
            # the alerts bot is already read by the older watcher container. Idle without a token.
            from intel.alerts.commands import TelegramCommands
            self.commands = TelegramCommands(self.ctx, self.sender, t1=getattr(self, "t1", None))
            tasks.append(asyncio.create_task(self._loop("telegram", self.commands.run_cycle, 5)))
        try:
            await asyncio.gather(*tasks)
        except (KeyboardInterrupt, asyncio.CancelledError):
            self._stop.set()
        finally:
            server.stop()
