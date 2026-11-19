# SPDX-License-Identifier: Apache-2.0
"""Import the state of the old lkml-watch and stable-watch scripts, offline. Their
files are only ever opened for reading."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from patchtrail import snapshot, store
from patchtrail.fetch import compose_for
from patchtrail.mail import parse_mail, split_mbox
from patchtrail.projects import detect_project

_VERSION = re.compile(r"^(.+)-v(\d+)$")
_EMPTY = {"commits": [], "branches": {}, "failed": {}, "hint": None}


@dataclass
class ImportReport:
    patches: list[str] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _dir(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / fallback)


def _read_threads(path: Path) -> list[tuple[str, str]]:
    """(name, msgid) in file order, as lkml-watch's load_threads reads them."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return []
    out = []
    for line in text.splitlines():
        fields = line.split("#", 1)[0].split()
        if len(fields) >= 2:
            out.append((fields[0], fields[1].strip("<>")))
    return out


def _read_seen(path: Path) -> set[str]:
    try:
        return {line.strip().strip("<>") for line in path.read_text().splitlines()
                if line.strip()}
    except FileNotFoundError:
        return set()


def _groups(threads: list[tuple[str, str]]) -> dict[str, list[tuple[str, int, str]]]:
    """Base name -> [(name, version, msgid)]; a name without -v<N> is version 1."""
    groups: dict[str, list[tuple[str, int, str]]] = {}
    for name, msgid in threads:
        m = _VERSION.match(name)
        base, version = (m.group(1), int(m.group(2))) if m else (name, 1)
        groups.setdefault(base, []).append((name, version, msgid))
    return groups


def import_old(conn, mine: frozenset[str], *, now: int, old_config: Path | None = None,
               old_state: Path | None = None) -> ImportReport:
    config = old_config or _dir("XDG_CONFIG_HOME", ".config")
    state = old_state or _dir("XDG_STATE_HOME", ".local/state")
    lkml, stable = config / "lkml-watch", config / "stable-watch"
    report = ImportReport()
    for base, members in _groups(_read_threads(lkml / "threads")).items():
        if len(members) > 1:
            report.merged.append(base)
        _import_patch(conn, mine, now, base, members, state / "lkml-watch", report)
    _import_fixes(conn, stable / "fixes", now, report)
    return report


def _import_patch(conn, mine, now, base, members, state: Path, report: ImportReport) -> None:
    pid, seen, newest = None, set(), None
    for name, version, msgid in sorted(members, key=lambda t: t[1]):
        mbox = state / f"{name}.mbox"
        if store.revision_by_msgid(conn, msgid) or not mbox.exists():
            report.skipped.append(name)
            continue
        raws = split_mbox(mbox.read_bytes())
        root = next((parse_mail(r) for r in raws if parse_mail(r).msgid == msgid), None)
        if root is None:
            report.skipped.append(name)
            continue
        if pid is None:
            existing = store.get_patch(conn, base)
            pid = existing["id"] if existing else store.add_patch(conn, base, now=now)
            created = existing is None
        rev = store.add_revision(conn, pid, msgid, version=version, subject=root.subject,
                                 author=root.from_addr, posted_at=root.date)
        store.upsert_mails(conn, rev, raws, now)
        seen |= _read_seen(state / f"{name}.seen")
        newest = root
    if pid is None:
        return
    store.set_field(conn, pid, "project", detect_project(newest.to_cc, newest.subject))
    store.set_field(conn, pid, "relation",
                    "mine" if newest.from_addr in mine else "following")
    if created:
        report.patches.append(base)
        _read_state(conn, mine, now, pid, seen)


def _read_state(conn, mine, now, pid: int, seen: set[str]) -> None:
    row = store.patch_by_id(conn, pid)
    ids = {m["msgid"] for m in store.patch_mails(conn, pid)}
    if ids <= seen:
        # The first fetch's full snapshot, with its trail data, becomes the read
        # reference; recording one here would make that fetch flag the patch.
        store.set_field(conn, pid, "read_on_first_snapshot", 1)
        return
    snapshot.record(conn, pid, compose_for(conn, row, mine, dict(_EMPTY), only=seen), now - 1)
    snapshot.mark_read(conn, pid)
    snapshot.record(conn, pid, compose_for(conn, row, mine, dict(_EMPTY)), now)
    conn.commit()


def _import_fixes(conn, path: Path, now: int, report: ImportReport) -> None:
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        words = line.split("#", 1)[0].split()
        if len(words) < 2:
            continue
        name, sha = words[0], words[1]
        row = store.get_patch(conn, name)
        if row is None:
            pid = store.add_patch(conn, name, relation="following", project="kernel", now=now)
        else:
            pid = row["id"]
        store.set_commit(conn, pid, sha, "", "manual")
        if len(words) >= 4:
            store.set_field(conn, pid, "tree_url", words[2])
            store.set_field(conn, pid, "tree_branch", words[3])
            store.set_field(conn, pid, "tree_source", "manual")
        report.fixes.append(name)
