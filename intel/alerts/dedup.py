"""Alert deduplication with per-severity cooldowns, escalation and per-cycle caps.

Every candidate is persisted in ``alerts`` (sent or suppressed with a reason) so the
decision trail survives restarts; cooldown state is read back from the table.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from intel import MODEL_VERSION
from intel.alerts.rules import SEV_RANK, AlertCandidate
from intel.db.connection import Database
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)


class AlertDeduper:
    def __init__(self, db: Database, cfg: dict[str, Any], chain_id: int) -> None:
        self.db = db
        self.cfg = cfg
        self.chain_id = chain_id
        self.cooldowns = {k: int(v) for k, v in (cfg.get("cooldown_seconds") or {}).items()}
        self.min_sev = str(cfg.get("min_severity", "WATCH"))
        self.max_per_cycle = int(cfg.get("max_per_cycle", 12))

    def last_sent(self, dedup_key: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT ts, severity, payload_json FROM alerts WHERE dedup_key=? AND sent=1 ORDER BY ts DESC LIMIT 1", (dedup_key,))
        return dict(row) if row else None

    def decide(self, c: AlertCandidate, ts: int | None = None) -> tuple[bool, str | None]:
        ts = ts or now_ts()
        if SEV_RANK.get(c.severity, 0) < SEV_RANK.get(self.min_sev, 1):
            return False, f"below min severity {self.min_sev}"
        last = self.last_sent(c.dedup_key)
        if last is None:
            return True, None
        cooldown = self.cooldowns.get(c.severity, 3600)
        age = ts - int(last["ts"])
        if age >= cooldown:
            return True, None
        if SEV_RANK.get(c.severity, 0) > SEV_RANK.get(last["severity"], 0):
            return True, None  # escalation always goes through
        return False, f"cooldown {cooldown}s (sent {age}s ago)"

    def record(self, c: AlertCandidate, *, sent: bool, suppressed_reason: str | None, ts: int | None = None, body: str = "", message_id: str | None = None, error: str | None = None) -> int | None:
        ts = ts or now_ts()
        return self.db.insert("alerts", {
            "ts": ts, "chain_id": self.chain_id, "token_address": c.token, "severity": c.severity, "kind": c.kind, "dedup_key": c.dedup_key,
            "title": c.title, "body": body, "why": c.why, "action": c.action, "sent": int(sent), "sent_ts": ts if sent else None, "telegram_message_id": message_id, "send_error": error,
            "suppressed": int(not sent and suppressed_reason is not None), "suppress_reason": suppressed_reason, "payload_json": json.dumps(c.payload, default=str), "model_version": MODEL_VERSION,
        })

    def select(self, candidates: list[AlertCandidate], ts: int | None = None) -> tuple[list[AlertCandidate], list[tuple[AlertCandidate, str]]]:
        """Return (to_send, suppressed) honouring dedup, cooldown and the per-cycle cap."""
        ts = ts or now_ts()
        ordered = sorted(candidates, key=lambda c: -SEV_RANK.get(c.severity, 0))
        to_send: list[AlertCandidate] = []
        suppressed: list[tuple[AlertCandidate, str]] = []
        seen_keys: set[str] = set()
        for c in ordered:
            if c.dedup_key in seen_keys:
                suppressed.append((c, "duplicate key in cycle"))
                continue
            seen_keys.add(c.dedup_key)
            ok, reason = self.decide(c, ts)
            if not ok:
                suppressed.append((c, reason or "suppressed"))
                continue
            if len(to_send) >= self.max_per_cycle and c.severity != "CRITICAL":
                suppressed.append((c, "per-cycle cap"))
                continue
            to_send.append(c)
        return to_send, suppressed
