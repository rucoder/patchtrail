# SPDX-License-Identifier: Apache-2.0
"""SQLite connection and schema migrations."""

import re
import sqlite3
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


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, sql in _migrations():
        if version > current:
            # One transaction per migration, with its version: a failure leaves
            # the database at the previous version. executescript commits on its
            # own, so the transaction is in the script.
            try:
                conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version={int(version)};\nCOMMIT;")
            except sqlite3.Error:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                conn.close()
                raise
            current = version
    conn.commit()
    return conn
