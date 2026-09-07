"""SQLite storage layer (WAL mode) with tiny typed helpers.

A single process owns the database. Writes are serialised with a re-entrant lock so the
async engines and the synchronous sqlite3 driver coexist without ``database is locked``.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Sequence

from intel.db.migrations import apply_migrations


class Database:
    def __init__(self, path: str, *, readonly: bool = False, backup_dir: str | None = None) -> None:
        self.path = path
        self.backup_dir = backup_dir
        self.health: dict[str, str] = {"status": "memory"}
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            if not readonly:
                from intel.db.maintenance import ensure_healthy  # local import: keeps this module light

                self.health = ensure_healthy(path, backup_dir)
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=30, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._tx_depth = 0
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA temp_store=MEMORY")
            self._conn.execute("PRAGMA cache_size=-65536")
        if not readonly:
            self.migrate()

    # ------------------------------------------------------------------ #
    def migrate(self) -> list[str]:
        with self._lock:
            return apply_migrations(self._conn)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def backup_to(self, dest_path: str) -> str:
        """Consistent online copy (safe to read from another OS / process)."""
        from intel.db.maintenance import backup_connection

        with self._lock:
            return backup_connection(self._conn, dest_path)

    def quick_check(self) -> tuple[bool, str]:
        with self._lock:
            rows = self._conn.execute("PRAGMA quick_check").fetchall()
        return (len(rows) == 1 and rows[0][0] == "ok"), "; ".join(str(r[0]) for r in rows[:3])

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._tx_depth == 0:
                self._conn.execute("BEGIN IMMEDIATE")
            self._tx_depth += 1
            try:
                yield self._conn
            except BaseException:
                self._tx_depth -= 1
                if self._tx_depth == 0:
                    self._conn.execute("ROLLBACK")
                raise
            else:
                self._tx_depth -= 1
                if self._tx_depth == 0:
                    self._conn.execute("COMMIT")

    # ------------------------------------------------------------------ #
    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> int:
        with self._lock:
            cur = self._conn.executemany(sql, rows)
            return cur.rowcount if cur.rowcount is not None else 0

    def query(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Sequence[Any] | dict[str, Any] = (), default: Any = None) -> Any:
        row = self.query_one(sql, params)
        if row is None:
            return default
        v = row[0]
        return default if v is None else v

    # ------------------------------------------------------------------ #
    def insert(self, table: str, row: dict[str, Any], *, ignore: bool = False, replace: bool = False) -> int | None:
        cols = list(row.keys())
        verb = "INSERT OR IGNORE" if ignore else "INSERT OR REPLACE" if replace else "INSERT"
        sql = f"{verb} INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        with self._lock:
            cur = self._conn.execute(sql, [_adapt(row[c]) for c in cols])
            return cur.lastrowid if cur.rowcount else None

    def insert_many(self, table: str, rows: list[dict[str, Any]], *, ignore: bool = True) -> int:
        if not rows:
            return 0
        cols = list(rows[0].keys())
        verb = "INSERT OR IGNORE" if ignore else "INSERT"
        sql = f"{verb} INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        with self._lock:
            before = self._conn.total_changes
            self._conn.executemany(sql, [[_adapt(r.get(c)) for c in cols] for r in rows])
            return self._conn.total_changes - before

    def upsert(self, table: str, row: dict[str, Any], conflict_cols: Sequence[str], *, update_cols: Sequence[str] | None = None) -> None:
        cols = list(row.keys())
        upd = [c for c in (update_cols or cols) if c not in conflict_cols]
        sql = (
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
            f"ON CONFLICT({', '.join(conflict_cols)}) DO UPDATE SET " + ", ".join(f"{c}=excluded.{c}" for c in upd)
        ) if upd else (
            f"INSERT OR IGNORE INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        )
        with self._lock:
            self._conn.execute(sql, [_adapt(row[c]) for c in cols])

    # ------------------------------------------------------------------ #
    # key/value cache for immutable provider results
    def cache_get(self, key: str, now_ts: int) -> Any:
        row = self.query_one("SELECT value, expires_ts FROM api_cache WHERE key=?", (key,))
        if row is None:
            return None
        if row["expires_ts"] is not None and row["expires_ts"] < now_ts:
            return None
        try:
            return json.loads(row["value"])
        except Exception:
            return None

    def cache_set(self, key: str, value: Any, now_ts: int, ttl_seconds: int | None) -> None:
        expires = None if ttl_seconds is None else now_ts + int(ttl_seconds)
        self.execute(
            "INSERT OR REPLACE INTO api_cache(key, value, created_ts, expires_ts) VALUES (?,?,?,?)",
            (key, json.dumps(value, default=str), now_ts, expires),
        )

    def cursor_get(self, name: str) -> int | None:
        return self.scalar("SELECT block_number FROM sync_cursors WHERE name=?", (name,))

    def cursor_set(self, name: str, block_number: int, ts: int) -> None:
        self.execute(
            "INSERT INTO sync_cursors(name, block_number, ts, updated_ts) VALUES (?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET block_number=excluded.block_number, ts=excluded.ts, updated_ts=excluded.updated_ts",
            (name, int(block_number), int(ts), int(ts)),
        )


def _adapt(v: Any) -> Any:
    if isinstance(v, (dict, list, tuple)):
        return json.dumps(v, default=str)
    if isinstance(v, bool):
        return int(v)
    return v


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]
