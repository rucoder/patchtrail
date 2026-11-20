# SPDX-License-Identifier: Apache-2.0
"""Sharing the database between the service, its fetch child and the CLI."""

import shutil
import sqlite3
import threading
import time
from importlib import resources

from patchtrail import db, fetch
from patchtrail.config import paths


def test_busy_timeout_waits(conn):
    p = paths()
    a = sqlite3.connect(p.db, isolation_level=None, check_same_thread=False)
    a.execute("BEGIN IMMEDIATE")
    t = threading.Timer(0.5, lambda: a.execute("COMMIT"))
    t.start()
    b = db.connect(p.db)
    try:
        started = time.monotonic()
        b.execute("UPDATE kv SET value='x' WHERE key='nothing'")
        b.commit()
        assert time.monotonic() - started >= 0.3
    finally:
        t.join()
        b.close()
        a.close()


def test_concurrent_connect_migrates_once(tmp_path, monkeypatch):
    mig = tmp_path / "mig"
    mig.mkdir()
    schema = resources.files("patchtrail").joinpath("schema")
    shutil.copy(str(schema.joinpath("001_init.sql")), mig / "001_init.sql")
    (mig / "002_x.sql").write_text("CREATE TABLE once_only(x);\n")
    monkeypatch.setattr(db, "MIGRATIONS", mig)
    target = tmp_path / "shared" / "new.db"
    barrier = threading.Barrier(2)
    results, errors = [], []

    def go():
        try:
            barrier.wait()
            db.connect(target).close()
            results.append(True)
        except Exception as e:      # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and len(results) == 2
    c = db.connect(target)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 2
    assert c.execute("SELECT count(*) FROM sqlite_master WHERE name='once_only'").fetchone()[0] == 1
    c.close()


def _running(conn, error=None):
    conn.execute("INSERT INTO runs(id,pid,trigger,started_at,status,error)"
                 " VALUES (1,1,'cli',1,'running',?)", (error,))
    conn.commit()


def _row(conn):
    return tuple(conn.execute("SELECT status, finished_at, error FROM runs WHERE id=1").fetchone())


def test_reap_stale_marks_running_rows(conn):
    _running(conn)
    assert fetch.reap_stale(paths(), conn, 100, "killed") == 1
    assert _row(conn) == ("interrupted", 100, "killed")


def test_reap_stale_keeps_old_error_without_one(conn):
    _running(conn, "old")
    assert fetch.reap_stale(paths(), conn, 100) == 1
    assert _row(conn) == ("interrupted", 100, "old")


def test_reap_stale_leaves_live_run(conn):
    _running(conn)
    with fetch.locked(paths(), conn):
        assert fetch.reap_stale(paths(), conn, 100, "killed") == 0
    assert _row(conn) == ("running", None, None)
