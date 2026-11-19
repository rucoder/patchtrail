"""Find the user's patches on lore: new series, new versions, stable backports."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from patchtrail import store
from patchtrail.projects.kernel.follow import strip_subject
from patchtrail.sources import lore

_BRACKETS = re.compile(r"^(\s*\[[^]]*\])+")
_VERSION = re.compile(r"\bv(\d+)\b", re.I)
_PATCH_GROUP = re.compile(r"\[\s*[^]]*?PATCH[^]]*\]", re.I)
_SERIES = re.compile(r"(?<![\w.])(\d+\.\d+)(?:\.y)?(?![\w.])")
_SHA = re.compile(r"commit\s+([0-9a-f]{12,40})\s+upstream|\[\s*Upstream commit\s+([0-9a-f]{12,40})\s*\]", re.I)


def slug(subject, taken):
    """A short thread name from a patch subject."""
    words = re.findall(r"[a-z0-9]+",
                       re.sub(r"^(\s*\[[^]]*\])+", "", subject).lower())
    name = ""
    for w in words:
        if len(name) + len(w) + 1 > 32:
            break
        name = f"{name}-{w}" if name else w
    name, n = name or "thread", 2
    base = name
    while name in taken:
        name, n = f"{base}-{n}", n + 1
    return name


def version_of(subject: str) -> int:
    m = _BRACKETS.match(subject)
    v = _VERSION.search(m.group(0)) if m else None
    return int(v.group(1)) if v else 1


def norm(subject: str) -> str:
    return strip_subject(subject).lower()


def backport_of(subject: str, body: str) -> tuple[str | None, str | None]:
    series = None
    for g in _PATCH_GROUP.finditer(subject):
        s = _SERIES.search(g.group(0))
        if s:
            series = s.group(1)
            break
    m = _SHA.search(body or "")
    sha = (m.group(1) or m.group(2)).lower() if m else None
    return series, sha


@dataclass
class DiscoverResult:
    new_patches: list[str] = field(default_factory=list)
    new_revisions: list[str] = field(default_factory=list)
    backports: list[str] = field(default_factory=list)


def _epoch(iso: str) -> int | None:
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00"))
                   .astimezone(timezone.utc).timestamp())
    except ValueError:
        return None


def _match_patch(conn, entry) -> int | None:
    """The patch with a series revision by this author and subject, newest version first."""
    want = norm(entry.subject)
    best = None
    for r in conn.execute("SELECT patch_id, version, subject FROM revisions"
                          " WHERE kind='series' AND author=?", (entry.author.lower(),)):
        if norm(r["subject"]) == want and (best is None or r["version"] > best[0]):
            best = (r["version"], r["patch_id"])
    return best[1] if best else None


def _backport_patch(conn, entry, sha) -> int | None:
    if sha:
        row = conn.execute("SELECT patch_id FROM commits WHERE lower(sha) LIKE ?",
                           (sha[:12].lower() + "%",)).fetchone()
        if row:
            return row["patch_id"]
    want = norm(entry.subject)
    for r in conn.execute("SELECT patch_id, subject FROM revisions WHERE kind='series'"
                          " ORDER BY version DESC"):
        if norm(r["subject"]) == want:
            return r["patch_id"]
    return None


def _known(conn, msgid) -> bool:
    return (store.revision_by_msgid(conn, msgid) is not None
            or conn.execute("SELECT 1 FROM ignored WHERE msgid=?", (msgid,)).fetchone()
            is not None)


def discover(conn, source, addresses: list[str], *, now: int,
             search=lore.search) -> DiscoverResult:
    """Record new patches, versions and backport postings.

    Like store's functions, this commits as it goes; callers need not commit.
    """
    last = store.kv_get(conn, "last_discovery")
    since = int(last) if last is not None else None
    first = since is None
    res = DiscoverResult()
    taken = {r["name"] for r in conn.execute("SELECT name FROM patches")}

    for e in source.discover(addresses, since):
        if e.is_reply or _known(conn, e.msgid):
            continue
        if backport_of(e.subject, e.summary)[0] is not None:
            continue  # a stable backport: handled by the stable-list stage
        fields = dict(version=version_of(e.subject), subject=e.subject,
                      author=e.author.lower(), posted_at=_epoch(e.updated))
        pid = _match_patch(conn, e)
        if pid is not None:
            store.add_revision(conn, pid, e.msgid, **fields)
            res.new_revisions.append(store.patch_by_id(conn, pid)["name"])
            continue
        name = slug(e.subject, taken)
        taken.add(name)
        pid = store.add_patch(conn, name, relation="mine", now=now)
        store.add_revision(conn, pid, e.msgid, **fields)
        if first:
            store.set_field(conn, pid, "read_on_first_snapshot", 1)
        res.new_patches.append(name)

    for addr in addresses:
        for e in search("stable", f"f:{addr}"):
            if _known(conn, e.msgid):
                continue
            series, sha = backport_of(e.subject, e.summary)
            pid = _backport_patch(conn, e, sha)
            if pid is None:
                continue
            store.add_revision(conn, pid, e.msgid, version=version_of(e.subject),
                               subject=e.subject, author=e.author.lower(),
                               posted_at=_epoch(e.updated), kind="backport",
                               branch=series)
            name = store.patch_by_id(conn, pid)["name"]
            if name not in res.backports:
                res.backports.append(name)

    store.kv_set(conn, "last_discovery", now)
    return res


def merge_by_change_id(conn) -> list[str]:
    """Fold a newer patch into the older one that shares a revision change_id."""
    merged = []
    rows = conn.execute(
        "SELECT r.change_id, MIN(r.patch_id) AS keep, GROUP_CONCAT(DISTINCT r.patch_id) AS ids"
        " FROM revisions r WHERE r.change_id IS NOT NULL GROUP BY r.change_id"
        " HAVING COUNT(DISTINCT r.patch_id) > 1").fetchall()
    for row in rows:
        for other in sorted(int(i) for i in row["ids"].split(",")):
            if other == row["keep"]:
                continue
            p = store.patch_by_id(conn, other)
            if p is None:
                continue
            conn.execute("UPDATE revisions SET patch_id=? WHERE patch_id=?",
                         (row["keep"], other))
            conn.execute("UPDATE OR IGNORE commits SET patch_id=? WHERE patch_id=?",
                         (row["keep"], other))
            conn.execute("DELETE FROM patches WHERE id=?", (other,))
            merged.append(p["name"])
    conn.commit()
    return merged
