# SPDX-License-Identifier: Apache-2.0
"""SQLite connection and schema migrations."""

import re
import sqlite3
import time
from importlib import resources
from pathlib import Path

SCHEMA_VERSION = 2

# Where the migrations are read from; None means the package's schema directory.
# Tests point it at a directory of their own.
MIGRATIONS: Path | None = None


def _migrations() -> list[tuple[int, str]]:
    found = []
    base = Path(MIGRATIONS) if MIGRATIONS is not None else resources.files(
        "patchtrail").joinpath("schema")
    for entry in base.iterdir():
        m = re.fullmatch(r"(\d+)_.*\.sql", entry.name)
        if m:
            found.append((int(m.group(1)), entry.read_text(encoding="utf-8")))
    return sorted(found)


def _statements(script: str):
    """The statements of a script. executescript cannot be used: it commits a
    pending transaction first, and the migration's transaction is already open."""
    buf = ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            yield buf
            buf = ""
    if buf.strip():
        yield buf


def _version(conn) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _wal(conn) -> None:
    # Switching a new database to WAL while another connection does the same can
    # fail at once with "locked": the busy handler is not used for it. Retry.
    deadline = time.monotonic() + 5
    while True:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.01)


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    _wal(conn)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.isolation_level = None             # transactions are explicit below
        for version, sql in _migrations():
            if _version(conn) >= version:
                continue
            # One transaction per migration, with its version: a failure leaves
            # the database at the previous version. BEGIN IMMEDIATE takes the
            # write lock first, so a process migrating at the same time waits
            # (busy_timeout) and then finds the migration done.
            conn.execute("BEGIN IMMEDIATE")
            try:
                if _version(conn) < version:
                    for stmt in _statements(sql):
                        conn.execute(stmt)
                    conn.execute(f"PRAGMA user_version={int(version)}")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
    except sqlite3.Error:
        conn.close()
        raise
    conn.isolation_level = ""                   # the default: implicit transactions
    return conn
