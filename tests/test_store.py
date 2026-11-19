import pytest

from patchtrail import db, store
from patchtrail.config import paths


def test_schema_and_pragmas(conn):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_add_patch_rules(conn):
    pid = store.add_patch(conn, "iowq-cpuset", now=1)
    assert store.get_patch(conn, "iowq-cpuset")["id"] == pid
    with pytest.raises(ValueError):
        store.add_patch(conn, "iowq-cpuset", now=1)
    with pytest.raises(ValueError):
        store.add_patch(conn, "bad name", now=1)


def test_delete_cascades(conn):
    pid = store.add_patch(conn, "p", now=1)
    store.add_revision(conn, pid, "a@b", subject="[PATCH] x")
    conn.execute("DELETE FROM patches WHERE id=?", (pid,))
    assert store.revision_by_msgid(conn, "a@b") is None


def test_reconnect_keeps_version(tmp_path):
    p = paths()
    db.connect(p.db).close()
    assert db.connect(p.db).execute("PRAGMA user_version").fetchone()[0] == 1


def test_list_patches_filters(conn):
    a = store.add_patch(conn, "a", now=1)
    b = store.add_patch(conn, "b", now=2)
    c = store.add_patch(conn, "c", now=3)
    store.set_field(conn, b, "hidden", 1)
    store.set_field(conn, c, "closed", "dropped")
    assert [r["name"] for r in store.list_patches(conn)] == ["a"]
    assert {r["name"] for r in store.list_patches(conn, hidden=True)} == {"a", "b"}
    assert {r["name"] for r in store.list_patches(conn, closed=True)} == {"a", "c"}
    assert store.patch_by_id(conn, a)["name"] == "a"


def test_revisions_ordered(conn):
    pid = store.add_patch(conn, "p", now=1)
    store.add_revision(conn, pid, "v2@x", version=2)
    store.add_revision(conn, pid, "v1@x", version=1)
    assert [r["version"] for r in store.revisions(conn, pid)] == [1, 2]


def test_commits_and_set_field(conn):
    pid = store.add_patch(conn, "p", now=1)
    store.set_commit(conn, pid, "abc", "s", "manual")
    store.set_commit(conn, pid, "abc", "s2", "search")
    rows = store.commits(conn, pid)
    assert len(rows) == 1 and rows[0]["subject"] == "s2"
    with pytest.raises(ValueError):
        store.set_field(conn, pid, "id", 5)


def test_kv(conn):
    assert store.kv_get(conn, "k") is None
    store.kv_set(conn, "k", "v")
    store.kv_set(conn, "k", "w")
    assert store.kv_get(conn, "k") == "w"
