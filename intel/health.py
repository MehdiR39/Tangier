"""Health check: in-process state + a tiny stdlib HTTP server (``/health``, ``/status``)."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from intel import MODEL_VERSION, __version__
from intel.context import IntelContext
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)


class HealthState:
    def __init__(self, ctx: IntelContext) -> None:
        self.ctx = ctx
        self.started = now_ts()
        self.runs: dict[str, dict[str, Any]] = {}

    def record_run(self, engine: str, ok: bool, seconds: float, error: str | None) -> None:
        self.runs[engine] = {"ts": now_ts(), "ok": ok, "seconds": round(seconds, 1), "error": error}

    def _expected_interval(self, engine: str) -> int:
        """How often this engine is supposed to run, in seconds."""
        cfg = self.ctx.config
        return {
            "portfolio": int(cfg.get("engine.portfolio_cycle_seconds", 60)),
            "scanner": int(cfg.get("engine.scanner_cycle_seconds", 120)),
            "scanner_deep": int(cfg.get("engine.scanner_deep_cycle_seconds", 300)),
            "history": int(cfg.get("engine.history_cycle_seconds", 45)),
            "execution": int(cfg.get("execution.cycle_seconds", 30)),
            "digest": 120,
            "backup": int(cfg.get("engine.backup_interval_seconds", 6 * 3600)),
            "retention": int(cfg.get("retention.prune_interval_seconds", 6 * 3600)),
            "regime": 3600,
            "t1": int(cfg.get("t1.poll_seconds", 5)),
            "telegram": 30,                                     # 5 s between polls, each up to 20 s long
        }.get(engine, 300)

    def snapshot(self) -> dict[str, Any]:
        stale_after = int(self.ctx.config.get("health.stale_after_seconds", 300))
        providers = self.ctx.status.snapshot()
        now = now_ts()
        engines_ok = all(r["ok"] for r in self.runs.values()) if self.runs else True
        # Each engine is judged against its own cadence. A single threshold declared the whole
        # container unhealthy because the 6-hourly backup had not run in the last 15 minutes
        # (2026-09-04), which hides a real failure behind a permanent false alarm.
        stale = [e for e, r in self.runs.items() if now - r["ts"] > max(stale_after * 3, self._expected_interval(e) * 3)]
        providers_ok = all(p.get("healthy", True) for p in providers.values())
        db_size = os.path.getsize(self.ctx.settings.db_path) if os.path.exists(self.ctx.settings.db_path) else None
        return {
            "ok": engines_ok and providers_ok and not stale,
            "version": __version__, "model_version": MODEL_VERSION,
            "uptime_s": now - self.started, "engines": self.runs, "stale_engines": stale, "providers": providers,
            "db_path": self.ctx.settings.db_path, "db_size_bytes": db_size, "ts": now,
        }

    def status_detail(self) -> dict[str, Any]:
        s = self.snapshot()
        try:
            if not s["providers"]:  # fresh process (CLI `status`): use the persisted provider stats
                s["providers"] = {r["provider"]: dict(r) for r in self.ctx.db.query("SELECT * FROM provider_status")}
            s["portfolio"] = [dict(r) for r in self.ctx.db.query("SELECT p.label, p.token_address, s.state, s.moonshot, s.action, s.since_ts FROM portfolio_positions p LEFT JOIN token_states s ON s.chain_id=p.chain_id AND s.token_address=p.token_address WHERE p.chain_id=? AND p.active=1", (self.ctx.chain_id,))]
            s["scanner"] = {r["status"]: r["n"] for r in self.ctx.db.query("SELECT status, COUNT(*) AS n FROM scanner_candidates WHERE chain_id=? GROUP BY status", (self.ctx.chain_id,))}
            s["alerts_24h"] = self.ctx.db.scalar("SELECT COUNT(*) FROM alerts WHERE sent=1 AND ts>?", (now_ts() - 86400,), 0)
            s["last_runs"] = [dict(r) for r in self.ctx.db.query("SELECT engine, started_ts, finished_ts, ok, tokens_processed, alerts_sent, error FROM engine_runs ORDER BY id DESC LIMIT 6")]
        except Exception as exc:  # noqa: BLE001
            s["status_error"] = str(exc)
        return s


class HealthServer:
    def __init__(self, state: HealthState, port: int) -> None:
        self.state = state
        self.port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path.startswith("/health"):
                    payload = state.snapshot()
                    code = 200 if payload["ok"] else 503
                elif self.path.startswith("/status"):
                    payload = state.status_detail()
                    code = 200
                else:
                    payload = {"error": "not found"}
                    code = 404
                body = json.dumps(payload, default=str, indent=1).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: Any) -> None:  # silence default access log
                return

        try:
            self._server = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        except OSError as exc:
            log.warning("health server not started on port %d: %s", self.port, exc)
            return
        self._thread = threading.Thread(target=self._server.serve_forever, name="health", daemon=True)
        self._thread.start()
        log.info("health server listening on :%d (/health, /status)", self.port)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
