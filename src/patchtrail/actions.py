# SPDX-License-Identifier: Apache-2.0
"""The changes a user can make to a patch: one implementation for the CLI and the API.

Each action runs in one `store.atomic` transaction, which nests inside a caller's.
Failures raise ActionError with an HTTP-style status."""
import re
import sqlite3

from patchtrail import render, snapshot, store
from patchtrail.config import Config, Paths
from patchtrail.fetch import reevaluate
from patchtrail.sources import lore

CLOSE_REASONS = ("rejected", "dropped", "moved")


class ActionError(Exception):
    """A refused change: status 400 (bad input), 404 (not tracked) or 409 (conflict)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def patch(conn, name: str) -> sqlite3.Row:
    row = store.get_patch(conn, name)
    if row is None:
        raise ActionError(404, f"not tracked: {name}")
    return row


def parse_series(arg: str) -> str:
    m = re.fullmatch(r"(?:linux-)?(\d+\.\d+)(?:\.y)?", arg)
    if not m:
        raise ActionError(400, f"bad series: {arg}")
    return m.group(1)


def parse_commit(arg: str) -> str:
    """A commit hash: 7 to 40 hex digits, never a ref or anything git could read as an
    option."""
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", arg):
        raise ActionError(400, f"not a commit hash: {arg}")
    return arg.lower()


def check_urls(urls) -> list[str]:
    urls = list(urls)
    for url in urls:
        if not store.valid_url(url):
            raise ActionError(400, f"not an http(s) URL: {url}")
    return urls


def _reeval(conn, paths: Paths, cfg: Config, row) -> None:
    reevaluate(conn, paths, cfg, row["id"])


def mark_read(conn, row) -> None:
    with store.atomic(conn):
        snapshot.mark_read(conn, row["id"])
        store.commit(conn)


def mark_unread(conn, row) -> None:
    with store.atomic(conn):
        snapshot.mark_unread(conn, row["id"])
        store.commit(conn)


def hide(conn, paths: Paths, cfg: Config, row) -> None:
    with store.atomic(conn):
        store.set_field(conn, row["id"], "hidden", 1)
        _reeval(conn, paths, cfg, row)


def unhide(conn, row) -> None:
    with store.atomic(conn):
        store.set_field(conn, row["id"], "hidden", 0)


def close(conn, paths: Paths, cfg: Config, row, reason: str, note: str | None) -> None:
    if reason not in CLOSE_REASONS:
        raise ActionError(400, f"bad reason: {reason} (one of {', '.join(CLOSE_REASONS)})")
    with store.atomic(conn):
        store.set_field(conn, row["id"], "closed", reason)
        store.set_field(conn, row["id"], "closed_note", note)
        _reeval(conn, paths, cfg, row)


def mark_applied(conn, paths: Paths, cfg: Config, row, commit: str | None) -> None:
    sha = parse_commit(commit) if commit else None
    with store.atomic(conn):
        store.set_field(conn, row["id"], "manual_applied", 1)
        if sha:
            store.set_commit(conn, row["id"], sha, "", "manual")
        _reeval(conn, paths, cfg, row)


def skip(conn, paths: Paths, cfg: Config, row, series: str) -> None:
    series = parse_series(series)
    with store.atomic(conn):
        conn.execute("INSERT OR IGNORE INTO branch_skips (patch_id, series) VALUES (?,?)",
                     (row["id"], series))
        store.commit(conn)
        _reeval(conn, paths, cfg, row)


def unskip(conn, paths: Paths, cfg: Config, row, series: str) -> None:
    series = parse_series(series)
    with store.atomic(conn):
        conn.execute("DELETE FROM branch_skips WHERE patch_id=? AND series=?",
                     (row["id"], series))
        store.commit(conn)
        _reeval(conn, paths, cfg, row)


def add_links(conn, row, urls, now: int) -> None:
    urls = check_urls(urls)
    with store.atomic(conn):
        store.add_links(conn, row["id"], urls, now)


def remove_links(conn, row, urls) -> None:
    with store.atomic(conn):
        store.remove_links(conn, row["id"], list(urls))


def set_note(conn, row, text: str | None) -> None:
    with store.atomic(conn):
        store.set_field(conn, row["id"], "note", text or None)


def register(conn, *, name: str, msgid: str, follow: bool = False, note: str | None = None,
             links=(), now: int) -> tuple[sqlite3.Row, bool]:
    """Track the thread of a Message-ID (or lore URL) under NAME. A thread registered
    before keeps its first name. Returns the patch and whether it was created."""
    if not store.valid_name(name):
        raise ActionError(400, f"invalid name: {name}")
    mid = lore.parse_msgid(msgid)
    if not lore.valid_msgid(mid):
        raise ActionError(400, f"not a Message-ID: {msgid}")
    links = check_urls(links)
    with store.atomic(conn):
        rev = store.revision_by_msgid(conn, mid)
        created = rev is None
        if not created:                     # registered before: the first name stays
            row = store.patch_by_id(conn, rev["patch_id"])
        else:
            if store.get_patch(conn, name) is not None:
                raise ActionError(409, f"name taken: {name}")
            row = store.patch_by_id(conn, store.add_patch(
                conn, name, relation="following" if follow else "mine", now=now))
            if not follow:
                store.set_field(conn, row["id"], "read_on_first_snapshot", 1)
            store.add_revision(conn, row["id"], mid, subject="")
            conn.execute("DELETE FROM ignored WHERE msgid=?", (mid,))
        store.add_links(conn, row["id"], links, now)
        if note is not None:
            store.set_field(conn, row["id"], "note", note or None)
    return store.patch_by_id(conn, row["id"]), created


def add_json(conn, row, msgid: str) -> dict:
    """The object `ptl add --json` prints."""
    latest = snapshot.latest(conn, row["id"])
    return {
        "name": row["name"], "msgid": msgid, "project": row["project"],
        "stage": latest[2]["stage"] if latest else None,
        "standing": latest[2]["standing"]["text"] if latest else None,
        "links": store.links(conn, row["id"]), "note": row["note"],
        "url": f"{render.LORE}/{msgid}/"}
