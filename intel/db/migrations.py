"""Versioned SQL migrations: ``intel/db/migrations/NNNN_name.sql`` applied in order.

Each migration file is split into statements and applied inside one transaction, so a
failing migration leaves the schema untouched.
"""
from __future__ import annotations

import os
import re
import sqlite3
import time

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")
_NAME_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


def list_migrations(directory: str = MIGRATIONS_DIR) -> list[tuple[int, str, str]]:
    out: list[tuple[int, str, str]] = []
    for fn in sorted(os.listdir(directory)):
        m = _NAME_RE.match(fn)
        if m:
            out.append((int(m.group(1)), m.group(2), os.path.join(directory, fn)))
    return out


def split_statements(sql: str) -> list[str]:
    lines = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        # strip trailing line comments (our migrations never put '--' inside string literals)
        if "--" in line:
            line = line.split("--", 1)[0]
        lines.append(line)
    body = "\n".join(lines)
    return [s.strip() for s in body.split(";") if s.strip()]


def apply_migrations(conn: sqlite3.Connection, directory: str = MIGRATIONS_DIR) -> list[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_ts INTEGER NOT NULL)"
    )
    applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    done: list[str] = []
    for version, name, path in list_migrations(directory):
        if version in applied:
            continue
        with open(path, encoding="utf-8") as fh:
            sql = fh.read()
        conn.execute("BEGIN")
        try:
            for stmt in split_statements(sql):
                conn.execute(stmt)
            conn.execute("INSERT INTO schema_migrations(version, name, applied_ts) VALUES (?,?,?)", (version, name, int(time.time())))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        done.append(f"{version:04d}_{name}")
    return done
