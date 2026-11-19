"""Plain-SQL access to the patchtrail database. Every function takes conn first."""

import re
import sqlite3

_NAME_RE = re.compile(r"[A-Za-z0-9._-]+")

_FIELDS = frozenset(
    "name project project_override relation hidden closed closed_note "
    "manual_applied force_stable tree_url tree_branch tree_source "
    "read_snapshot_id prev_read_snapshot_id flagged read_on_first_snapshot".split()
)


def add_patch(conn, name, *, relation="mine", project="unknown", now) -> int:
    if not _NAME_RE.fullmatch(name):
        raise ValueError(f"invalid patch name: {name!r}")
    try:
        cur = conn.execute(
            "INSERT INTO patches (name, relation, project, created_at) VALUES (?,?,?,?)",
            (name, relation, project, now),
        )
    except sqlite3.IntegrityError as e:
        if "patches.name" in str(e):
            raise ValueError(f"patch name already taken: {name}") from e
        raise
    conn.commit()
    return cur.lastrowid


def get_patch(conn, name):
    return conn.execute("SELECT * FROM patches WHERE name=?", (name,)).fetchone()


def patch_by_id(conn, id):
    return conn.execute("SELECT * FROM patches WHERE id=?", (id,)).fetchone()


def list_patches(conn, *, hidden=False, closed=False):
    sql = "SELECT * FROM patches"
    where = []
    if not hidden:
        where.append("hidden=0")
    if not closed:
        where.append("closed IS NULL")
    if where:
        sql += " WHERE " + " AND ".join(where)
    return conn.execute(sql + " ORDER BY id").fetchall()


def add_revision(conn, patch_id, root_msgid, *, version=1, subject="", author=None,
                 posted_at=None, kind="series", branch=None) -> int:
    cur = conn.execute(
        "INSERT INTO revisions (patch_id, root_msgid, version, subject, author,"
        " posted_at, kind, branch) VALUES (?,?,?,?,?,?,?,?)",
        (patch_id, root_msgid, version, subject, author, posted_at, kind, branch),
    )
    conn.commit()
    return cur.lastrowid


def revisions(conn, patch_id):
    return conn.execute(
        "SELECT * FROM revisions WHERE patch_id=? ORDER BY version, id", (patch_id,)
    ).fetchall()


def revision_by_msgid(conn, msgid):
    return conn.execute(
        "SELECT * FROM revisions WHERE root_msgid=?", (msgid,)
    ).fetchone()


def set_commit(conn, patch_id, sha, subject, source):
    conn.execute(
        "INSERT INTO commits (patch_id, sha, subject, source) VALUES (?,?,?,?)"
        " ON CONFLICT (patch_id, sha) DO UPDATE SET"
        " subject=excluded.subject, source=excluded.source",
        (patch_id, sha, subject, source),
    )
    conn.commit()


def commits(conn, patch_id):
    return conn.execute(
        "SELECT * FROM commits WHERE patch_id=? ORDER BY id", (patch_id,)
    ).fetchall()


def set_field(conn, patch_id, column, value):
    if column not in _FIELDS:
        raise ValueError(f"cannot set column {column!r}")
    conn.execute(f"UPDATE patches SET {column}=? WHERE id=?", (value, patch_id))
    conn.commit()


def kv_get(conn, key):
    row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def kv_set(conn, key, value):
    conn.execute(
        "INSERT INTO kv (key, value) VALUES (?,?)"
        " ON CONFLICT (key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
