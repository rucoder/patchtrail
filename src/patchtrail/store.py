# SPDX-License-Identifier: Apache-2.0
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


_REVISION_FIELDS = frozenset({"subject", "author", "posted_at", "change_id"})


def set_revision(conn, revision_id, **fields):
    bad = set(fields) - _REVISION_FIELDS
    if bad:
        raise ValueError(f"cannot set revision columns {sorted(bad)!r}")
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE revisions SET {sets} WHERE id=?", (*fields.values(), revision_id))
        conn.commit()


def revisions_sharing_change_id(conn):
    """The revisions whose change-id a revision of another patch has too."""
    return conn.execute(
        "SELECT * FROM revisions WHERE change_id IN (SELECT change_id FROM revisions"
        " WHERE change_id IS NOT NULL GROUP BY change_id"
        " HAVING COUNT(DISTINCT patch_id) > 1) ORDER BY id").fetchall()


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


def _same_commit(a: str, b: str) -> bool:
    """One hash is the other or an abbreviation of it."""
    a, b = a.lower(), b.lower()
    return bool(a and b) and (a.startswith(b) or b.startswith(a))


def replace_commit(conn, patch_id, old_sha, new_sha, subject, source="search"):
    """A stored commit was rebased: its row now names new_sha. If the patch already
    has new_sha, the old row goes. Hashes match when one abbreviates the other."""
    rows = commits(conn, patch_id)
    old = [r for r in rows if _same_commit(r["sha"], old_sha)]
    if not old:
        return
    if any(_same_commit(r["sha"], new_sha) for r in rows if r not in old):
        conn.executemany("DELETE FROM commits WHERE id=?", [(r["id"],) for r in old])
    else:
        conn.execute("UPDATE commits SET sha=?, subject=?, source=? WHERE id=?",
                     (new_sha, subject, source, old[0]["id"]))
    conn.commit()


def skips(conn, patch_id) -> frozenset[str]:
    """The stable series the user won't backport this patch to."""
    return frozenset(r[0] for r in conn.execute(
        "SELECT series FROM branch_skips WHERE patch_id=?", (patch_id,)))


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


def _parent(m, known) -> str | None:
    """The mail's parent in its thread, stored as mails.in_reply_to: In-Reply-To if
    that mail is known, else the last known References entry (lore keeps replies
    to mails it never got), else In-Reply-To as given."""
    if m.in_reply_to and known(m.in_reply_to):
        return m.in_reply_to
    for ref in reversed(m.references):
        if ref != m.msgid and known(ref):
            return ref
    return m.in_reply_to


def upsert_mails(conn, revision_id, raws, now) -> list[str]:
    """Store mails of a revision; return the msgids that were not stored before.
    A mail stored before gets a better parent when this batch brings one."""
    from patchtrail.mail import parse_mail

    mails = [(raw, m) for raw in raws if (m := parse_mail(raw)).msgid]
    batch = {m.msgid for _, m in mails}

    def known(msgid):
        return msgid in batch or conn.execute(
            "SELECT 1 FROM mails WHERE msgid=?", (msgid,)).fetchone() is not None

    new = []
    for raw, m in mails:
        parent = _parent(m, known)
        cur = conn.execute(
            "INSERT OR IGNORE INTO mails (msgid, revision_id, in_reply_to, date,"
            " from_name, from_addr, subject, raw, first_seen) VALUES (?,?,?,?,?,?,?,?,?)",
            (m.msgid, revision_id, parent, m.date, m.from_name, m.from_addr,
             m.subject, raw, now),
        )
        if cur.rowcount:
            new.append(m.msgid)
        elif parent is not None and known(parent):
            conn.execute("UPDATE mails SET in_reply_to=? WHERE msgid=? AND in_reply_to IS NOT ?",
                         (parent, m.msgid, parent))
    conn.commit()
    return new


def _below(roots: str, stop: str) -> str:
    """SQL for the stored mails of the given roots and of every mail below them
    through In-Reply-To, by date, not entering the threads of the stop msgids."""
    return ("WITH RECURSIVE below(msgid) AS (" + roots + " UNION"
            " SELECT m.msgid FROM mails m JOIN below b ON m.in_reply_to = b.msgid"
            " WHERE m.msgid NOT IN (" + stop + "))"
            " SELECT m.* FROM mails m JOIN below USING (msgid) ORDER BY m.date, m.rowid")


def thread_mails(conn, root_msgid):
    """The root mail and every mail below it, wherever stored, by date. The threads
    of other revisions' roots below it are not part of it."""
    return conn.execute(
        _below("SELECT ?", "SELECT root_msgid FROM revisions WHERE root_msgid != ?"),
        (root_msgid, root_msgid)).fetchall()


def patch_mails(conn, patch_id):
    """A patch's mails, by date: the root of each of its revisions and every mail
    below it through In-Reply-To, wherever stored, but not the threads of another
    patch's revisions. A mail is stored under the revision whose thread brought it
    first, so that says nothing about whose it is."""
    return conn.execute(
        _below("SELECT root_msgid FROM revisions WHERE patch_id=?",
               "SELECT root_msgid FROM revisions WHERE patch_id != ?"),
        (patch_id, patch_id)).fetchall()


def mail_infos(conn, patch_id):
    from patchtrail.mail import parse_mail

    return [parse_mail(bytes(r["raw"])) for r in patch_mails(conn, patch_id)]
