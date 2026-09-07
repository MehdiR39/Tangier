"""Database maintenance: integrity check at startup, online backups, corruption quarantine.

Lesson from 2026-09-02: a WAL-mode SQLite file on a Docker Desktop bind mount, opened from
both the Linux container and the Windows host, was corrupted within hours. The live database
now lives in a container-private volume; host-side analysis uses static backups/snapshots
produced with the SQLite online-backup API.
"""
from __future__ import annotations

import glob
import logging
import os
import sqlite3
import time

log = logging.getLogger(__name__)


def quick_check(path: str) -> tuple[bool, str]:
    """``PRAGMA quick_check`` on a file (opened read-only). (True, 'ok') when healthy."""
    if path == ":memory:" or not os.path.exists(path):
        return True, "no file"
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
        try:
            rows = con.execute("PRAGMA quick_check").fetchall()
        finally:
            con.close()
    except sqlite3.DatabaseError as exc:
        return False, str(exc)
    msg = "; ".join(str(r[0]) for r in rows[:3])
    return (len(rows) == 1 and rows[0][0] == "ok"), msg


def quarantine(path: str) -> str:
    """Rename a corrupt database (and its -wal/-shm) out of the way; returns the new path."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = f"{path}.corrupt-{stamp}"
    os.replace(path, target)
    for suffix in ("-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.replace(path + suffix, target + suffix)
    log.error("corrupt database quarantined: %s", target)
    return target


def backup_connection(conn: sqlite3.Connection, dest_path: str) -> str:
    """Consistent online backup of an open connection to ``dest_path`` (atomic via temp file)."""
    os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
    tmp = dest_path + ".tmp"
    for p in (tmp, tmp + "-wal", tmp + "-shm"):
        if os.path.exists(p):
            os.remove(p)
    dest = sqlite3.connect(tmp)
    try:
        conn.backup(dest, pages=4096, sleep=0.01)
        dest.execute("PRAGMA journal_mode=DELETE")
    finally:
        dest.close()
    os.replace(tmp, dest_path)
    return dest_path


def backup_path(src_path: str, dest_path: str) -> str:
    """Online backup from a connection of its OWN, so it can run off the event loop.

    Measured 2026-09-06 with py-spy on the live engine: `backup_to()` copies the 8 GB database
    through the main connection, on the main thread, with a blocking sleep between page batches.
    Every coroutine -- scanner, execution, the T+1 watcher -- is frozen for the 20-30 minutes it
    takes, and the backup loop fires at startup, so each restart began with a frozen engine.
    WAL mode lets a second, read-only connection copy safely while the engine keeps writing.
    """
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    try:
        return backup_connection(src, dest_path)
    finally:
        src.close()


def rotate_backups(backup_dir: str, keep: int = 4, prefix: str = "intel-") -> list[str]:
    files = sorted(glob.glob(os.path.join(backup_dir, f"{prefix}*.sqlite")))
    removed = []
    while len(files) > keep:
        victim = files.pop(0)
        try:
            os.remove(victim)
            removed.append(victim)
        except OSError:
            pass
    return removed


def latest_backup(backup_dir: str, prefix: str = "intel-") -> str | None:
    files = sorted(glob.glob(os.path.join(backup_dir, f"{prefix}*.sqlite")))
    return files[-1] if files else None


def restore_from_backup(backup_path: str, dest_path: str) -> bool:
    ok, msg = quick_check(backup_path)
    if not ok:
        log.error("backup %s is itself damaged: %s", backup_path, msg)
        return False
    src = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    try:
        backup_connection(src, dest_path)
    finally:
        src.close()
    log.warning("database restored from backup %s", backup_path)
    return True


def _check_due(path: str) -> tuple[bool, str]:
    """Is a full integrity scan due, or did one pass recently enough?

    `PRAGMA quick_check` reads the whole file. At 10 GB that is 8-15 minutes on this disk, paid
    on EVERY start of the engine and of every one-off script (seen with py-spy, 2026-09-06), while
    the engine sat with no loop running. A scan that passed less than INTEL_DB_CHECK_HOURS ago
    (default 24) is trusted; INTEL_DB_CHECK=always restores the old behaviour, never skips it.
    """
    mode = (os.environ.get("INTEL_DB_CHECK") or "daily").lower()
    if mode == "always":
        return True, "forced"
    if mode == "never":
        return False, "disabled"
    marker = path + ".checked"
    try:
        age_h = (time.time() - os.path.getmtime(marker)) / 3600
    except OSError:
        return True, "no previous check"
    limit = float(os.environ.get("INTEL_DB_CHECK_HOURS") or 24)
    return (age_h >= limit), f"last passed {age_h:.1f} h ago"


def _header_check(path: str) -> tuple[bool, str]:
    """Can the file be opened and its catalogue read? Reads the first pages only."""
    if not os.path.exists(path):
        return True, "absent"
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            con.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        finally:
            con.close()
        return True, "header ok"
    except sqlite3.DatabaseError as exc:
        return False, f"header: {exc}"


def ensure_healthy(path: str, backup_dir: str | None) -> dict[str, str]:
    """Called before opening the live database: quarantine a corrupt file and restore the
    latest good backup when one exists (otherwise a fresh database is created by the caller)."""
    due, why = _check_due(path)
    if not due:
        # The full scan is skipped, not the question. A broken header or catalogue shows up in
        # one read of the first pages, so that much is always paid before trusting the marker.
        ok, msg = _header_check(path)
        if ok:
            log.info("integrity check skipped (%s)", why)
            return {"status": "ok", "detail": "skipped: " + why}
    else:
        ok, msg = quick_check(path)
    if ok:
        try:
            with open(path + ".checked", "w") as fh:
                fh.write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        except OSError:
            pass
        return {"status": "ok", "detail": msg}
    quarantined = quarantine(path)
    restored = None
    if backup_dir:
        latest = latest_backup(backup_dir)
        if latest and restore_from_backup(latest, path):
            restored = latest
    return {"status": "restored" if restored else "recreated", "detail": msg, "quarantined": quarantined, "restored_from": restored or ""}
