"""SQLite connection and schema migrations."""

import re
import sqlite3
from importlib import resources
from pathlib import Path

SCHEMA_VERSION = 1


def _migrations() -> list[tuple[int, str]]:
    found = []
    for entry in resources.files("patchtrail").joinpath("schema").iterdir():
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
            conn.executescript(sql)
            conn.execute(f"PRAGMA user_version={int(version)}")
            current = version
    conn.commit()
    return conn
