"""Structured logging for the intel engines.

Reuses the repo convention of writing under ``<project>/logs`` (see config/config.py)
with the same ``asctime - name - level - message`` layout, plus an optional JSON mode
(``INTEL_LOG_JSON=1``) for container log collectors.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import logging.handlers
import os
import sys


class KeyValueFormatter(logging.Formatter):
    """Human-readable line: ``ts level logger message key=value ...``."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extra = getattr(record, "kv", None)
        if extra:
            base += " " + " ".join(f"{k}={v}" for k, v in extra.items())
        return base


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": dt.datetime.fromtimestamp(record.created, dt.timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        kv = getattr(record, "kv", None)
        if kv:
            payload.update(kv)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(logs_dir: str, level: str = "INFO", json_mode: bool | None = None, file_prefix: str = "intel") -> str | None:
    if json_mode is None:
        json_mode = os.getenv("INTEL_LOG_JSON", "0") in ("1", "true", "yes")
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    formatter: logging.Formatter = JsonFormatter() if json_mode else KeyValueFormatter(fmt)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    log_path: str | None = None
    if logs_dir:
        try:
            os.makedirs(logs_dir, exist_ok=True)
            log_path = os.path.join(logs_dir, f"{file_prefix}.log")
            fh = logging.handlers.RotatingFileHandler(log_path, maxBytes=20 * 1024 * 1024, backupCount=5, encoding="utf-8")
            fh.setFormatter(formatter)
            root.addHandler(fh)
        except OSError:
            log_path = None
    # quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return log_path


def kv(**fields: object) -> dict[str, dict[str, object]]:
    """Use as ``log.info("msg", extra=kv(token=addr, n=3))``."""
    return {"kv": fields}
