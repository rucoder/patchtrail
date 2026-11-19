# SPDX-License-Identifier: Apache-2.0
"""A fetch run: under a lock, discover new patches, fetch their threads, let each
project's trail fetch its repos once and follow each patch, and record a snapshot
of every patch whose state changed. Progress goes to the runs and run_log tables."""

import fcntl
import os
import re
import sqlite3
import time

from patchtrail import db, store
from patchtrail.config import Config, Paths, my_addresses
from patchtrail.discover import discover, merge_by_change_id
from patchtrail.mail import MailInfo, head_subject, parse_mail, standing, text_body
from patchtrail.projects import (PatchView, Progress, Trail, TrailResult, detect_project,
                                 get_project)
from patchtrail.snapshot import compose_state, latest, record
from patchtrail.sources import lore
from patchtrail.sources.lore import LoreError, LoreSource

_DIFF_PATH = re.compile(r"(?m)^\+\+\+ b/(.+?)\s*$")


class Busy(Exception):
    """Another fetch holds the lock. run is its runs row, None if it left none."""

    def __init__(self, run: sqlite3.Row | None):
        self.run = run
        super().__init__("a fetch is already running"
                         + (f" (run {run['id']})" if run is not None else ""))


class DbProgress(Progress):
    """Progress of one run, kept in runs.phase/step/steps and in run_log lines."""

    def __init__(self, conn, run_id: int, now=time.time):
        self.conn = conn
        self.run_id = run_id
        self.now = now
        self.steps: int | None = None
        self.n = 0

    def phase(self, name: str, steps: int | None = None) -> None:
        self.steps, self.n = steps, 0
        self.conn.execute("UPDATE runs SET phase=?, step=0, steps=? WHERE id=?",
                          (name, steps, self.run_id))
        self.log(f"phase: {name}")

    def step(self, label: str) -> None:
        self.n += 1
        self.conn.execute("UPDATE runs SET step=? WHERE id=?", (self.n, self.run_id))
        of = f"/{self.steps}" if self.steps is not None else ""
        self.log(f"step {self.n}{of}: {label}")

    def log(self, line: str) -> None:
        self.conn.execute("INSERT INTO run_log (run_id, at, line) VALUES (?,?,?)",
                          (self.run_id, int(self.now()), line))
        self.conn.commit()


def last_run(conn) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()


# --- views --------------------------------------------------------------------

def _load(conn, row) -> tuple[PatchView, list[MailInfo]]:
    """The patch as the trails see it, and the mails of its newest series revision,
    which drive its standing."""
    pid = row["id"]
    revs = store.revisions(conn, pid)
    series = [r for r in revs if r["kind"] == "series"]
    newest = series[-1] if series else None
    authors = {r["id"]: r["author"] for r in revs}
    mails, newest_mails, files = [], [], {}
    for m in store.patch_mails(conn, pid):
        raw = bytes(m["raw"])
        info = parse_mail(raw)
        mails.append(info)
        if newest is not None and m["revision_id"] == newest["id"]:
            newest_mails.append(info)
        if not info.is_reply and info.from_addr and info.from_addr == authors[m["revision_id"]]:
            files.update(dict.fromkeys(_DIFF_PATH.findall(text_body(raw)[0])))
    backports: dict[str, list[str]] = {}
    for r in revs:
        if r["kind"] == "backport" and r["branch"]:
            backports.setdefault(r["branch"], []).append(r["root_msgid"])
    subject, author, posted_at = "", "", 0
    if newest is not None:
        author = newest["author"] or ""
        posted_at = newest["posted_at"] or 0
        subject = (head_subject([m for m in newest_mails if m.from_addr == author])
                   or head_subject(newest_mails) or newest["subject"])
    prev = latest(conn, pid)
    tree = (row["tree_url"], row["tree_branch"]) if row["tree_url"] and row["tree_branch"] else None
    view = PatchView(
        id=str(pid), name=row["name"], relation=row["relation"], project=row["project"],
        mails=mails, posted_at=posted_at, subject=subject, author=author,
        commits=[{"sha": c["sha"], "subject": c["subject"], "source": c["source"]}
                 for c in store.commits(conn, pid)],
        tree=tree, tree_source=row["tree_source"], force_stable=bool(row["force_stable"]),
        skips=store.skips(conn, pid), manual_applied=bool(row["manual_applied"]),
        backports=backports, prev_state=prev[2] if prev else None, files=tuple(files))
    return view, newest_mails if newest is not None else mails


def build_view(conn, patch_row, mine: frozenset[str]) -> PatchView:
    """What the trails read about a patch. No field depends on mine yet; it is
    part of the interface the CLI calls."""
    return _load(conn, patch_row)[0]


def _empty() -> dict:
    return {"commits": [], "branches": {}, "failed": {}, "hint": None}


def _previous(view: PatchView) -> dict:
    """The trail fragment of the patch's last snapshot."""
    prev = view.prev_state or {}
    return {"commits": prev.get("commits", []), "branches": prev.get("branches", {}),
            "failed": prev.get("failed", {}), "hint": prev.get("hint")}


def _why(e: BaseException) -> str:
    return str(e) if isinstance(e, LoreError) else f"{type(e).__name__}: {e}"


# --- the run ------------------------------------------------------------------

class _Run:
    def __init__(self, conn, paths: Paths, cfg: Config, progress: DbProgress, *, source,
                 trails: dict[str, Trail] | None, search, now):
        self.conn, self.paths, self.cfg, self.progress = conn, paths, cfg, progress
        self.source, self.trails, self.search, self.now = source, trails, search, now
        self.mine = my_addresses(cfg)
        self._built: dict[str, Trail | None] = {}

    def discover(self) -> None:
        self.progress.phase("discover")
        try:
            r = discover(self.conn, self.source, sorted(self.mine), now=int(self.now()),
                         search=self.search)
        except Exception as e:      # lore down: the known patches are still followed
            self.progress.log(f"discover: {_why(e)}")
            return
        for kind, names in (("new patch", r.new_patches), ("new revision", r.new_revisions),
                            ("backport posted", r.backports)):
            for name in names:
                self.progress.log(f"{kind}: {name}")

    def threads(self, rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
        """Fetch every revision's thread; return the patches as they are afterwards."""
        revs = {row["id"]: store.revisions(self.conn, row["id"]) for row in rows}
        self.progress.phase("threads", sum(len(v) for v in revs.values()))
        for row in rows:
            roots: dict[int, MailInfo] = {}
            for rev in revs[row["id"]]:
                self.progress.step(f"{row['name']} v{rev['version']}" if rev["kind"] == "series"
                                   else f"{row['name']} backport {rev['branch']}")
                root = self._fetch(row, rev)
                if root is not None:
                    roots[rev["id"]] = root
            series_roots = [roots[r["id"]] for r in revs[row["id"]]
                            if r["kind"] == "series" and r["id"] in roots]
            if series_roots and not row["project_override"]:
                newest = series_roots[-1]
                project = detect_project(newest.to_cc, newest.subject)
                if project != row["project"]:
                    store.set_field(self.conn, row["id"], "project", project)
        ids = {row["id"] for row in rows}
        merged = merge_by_change_id(self.conn)
        for name in merged:
            self.progress.log(f"merged: {name}")
        if merged:      # a merged patch lives on in the patch that took its revisions
            owners = (store.revision_by_msgid(self.conn, rev["root_msgid"])
                      for rs in revs.values() for rev in rs)
            ids |= {o["patch_id"] for o in owners if o is not None}
        return [p for p in store.list_patches(self.conn) if p["id"] in ids]

    def _fetch(self, row, rev) -> MailInfo | None:
        """Store the thread's mails; return its root mail, None if it is not there."""
        root_id = rev["root_msgid"]
        try:
            raws = self.source.fetch(root_id)
        except Exception as e:      # the patch keeps its stored mails and state
            self.progress.log(f"{row['name']}: cannot fetch <{root_id}>: {_why(e)}")
            return None
        new = store.upsert_mails(self.conn, rev["id"], raws, int(self.now()))
        infos = sorted((parse_mail(raw) for raw in raws), key=lambda m: m.date)
        root = next((m for m in infos if m.msgid == root_id), None)
        fields = {}
        if root is not None and root_id in new:
            fields.update(subject=root.subject, author=root.from_addr,
                          posted_at=root.date or rev["posted_at"])
        if rev["change_id"] is None:
            change_id = next((m.change_id for m in infos if m.change_id), None)
            if change_id:
                fields["change_id"] = change_id
        store.set_revision(self.conn, rev["id"], **fields)
        return root

    def _trail(self, project: str) -> Trail | None:
        if self.trails is not None:
            return self.trails.get(project)
        if project not in self._built:
            factory = get_project(project).trail
            self._built[project] = factory(self.paths, self.cfg) if factory else None
        return self._built[project]

    def repos(self, views: dict[int, PatchView]) -> dict[str, Trail | None]:
        """Prepare each project's trail; return the usable ones. A project missing
        from the result failed and keeps its previous fragments."""
        self.progress.phase("repos")
        groups: dict[str, list[PatchView]] = {}
        for v in views.values():
            groups.setdefault(v.project, []).append(v)
        ready: dict[str, Trail | None] = {}
        for project, vs in groups.items():
            try:
                trail = self._trail(project)
                if trail is not None:
                    trail.prepare(vs, self.progress)
            except Exception as e:
                self.progress.log(f"{project}: cannot update repos: {_why(e)}")
                continue
            ready[project] = trail
        return ready

    def evaluate(self, rows: list[sqlite3.Row], loaded: dict[int, tuple[PatchView, list]],
                 ready: dict[str, Trail | None]) -> None:
        self.progress.phase("evaluate", len(rows))
        for row in rows:
            self.progress.step(row["name"])
            view, standing_mails = loaded[row["id"]]
            if row["project"] not in ready:
                fragment = _previous(view)
            elif ready[row["project"]] is None:
                fragment = _empty()
            else:
                fragment = self._follow(row, view, ready[row["project"]])
            state = compose_state(
                project=get_project(row["project"]),
                standing=standing(standing_mails, self.mine,
                                  following=row["relation"] == "following"),
                mails=view.mails, fragment=fragment, manual_applied=bool(row["manual_applied"]),
                closed=row["closed"], closed_note=row["closed_note"])
            record(self.conn, row["id"], state, int(self.now()))
            self.conn.commit()

    def _follow(self, row, view: PatchView, trail: Trail) -> dict:
        try:
            result = trail.evaluate(view, self.progress)
        except Exception as e:
            self.progress.log(f"{row['name']}: cannot follow the trail: {_why(e)}")
            return _previous(view)
        self._store(row, result)
        return result.fragment

    def _store(self, row, result: TrailResult) -> None:
        pid = row["id"]
        for old, new in result.replaced.items():
            subject = next((c.get("subject") or "" for c in result.fragment.get("commits", [])
                            if c["sha"][:12] == new[:12]), "")
            store.replace_commit(self.conn, pid, old, new, subject, source="search")
        for sha, subject, source in result.commits_found:
            store.set_commit(self.conn, pid, sha, subject, source)
        if result.tree and row["tree_source"] != "manual":
            url, branch = result.tree
            if (row["tree_url"], row["tree_branch"], row["tree_source"]) != (url, branch, "auto"):
                store.set_field(self.conn, pid, "tree_url", url)
                store.set_field(self.conn, pid, "tree_branch", branch)
                store.set_field(self.conn, pid, "tree_source", "auto")


def _selected(conn, names: list[str] | None) -> list[sqlite3.Row]:
    rows = store.list_patches(conn)
    if names is None:
        return rows
    names = set(names)
    return [r for r in rows if r["name"] in names]


def _finish(conn, run_id: int, status: str, now: int, error: str | None = None) -> None:
    conn.execute("UPDATE runs SET status=?, finished_at=?, error=? WHERE id=?",
                 (status, now, error, run_id))
    conn.commit()


def run_fetch(paths: Paths, cfg: Config, trigger: str, *, source=None, trails=None, search=None,
              now=time.time, patch_names: list[str] | None = None,
              discover_new: bool = True) -> int:
    """One fetch run; returns its id. Raises Busy when another run holds the lock."""
    source = LoreSource() if source is None else source
    search = lore.search if search is None else search
    conn = db.connect(paths.db)
    try:
        fd = os.open(paths.lock, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Busy(conn.execute("SELECT * FROM runs WHERE status='running'"
                                        " ORDER BY id DESC LIMIT 1").fetchone()) from None
            # The lock proves that no process runs these any more.
            conn.execute("UPDATE runs SET status='interrupted', finished_at=?"
                         " WHERE status='running'", (int(now()),))
            run_id = conn.execute("INSERT INTO runs (pid, trigger, started_at, status)"
                                  " VALUES (?,?,?,'running')",
                                  (os.getpid(), trigger, int(now()))).lastrowid
            conn.commit()
            progress = DbProgress(conn, run_id, now)
            try:
                run = _Run(conn, paths, cfg, progress, source=source, trails=trails,
                           search=search, now=now)
                if discover_new and patch_names is None:
                    run.discover()
                rows = run.threads(_selected(conn, patch_names))
                loaded = {row["id"]: _load(conn, row) for row in rows}
                ready = run.repos({pid: v for pid, (v, _) in loaded.items()})
                run.evaluate(rows, loaded, ready)
            except KeyboardInterrupt:
                conn.rollback()
                _finish(conn, run_id, "interrupted", int(now()))
                raise
            except Exception as e:
                conn.rollback()
                progress.log(f"failed: {_why(e)}")
                _finish(conn, run_id, "failed", int(now()), _why(e))
                raise
            _finish(conn, run_id, "ok", int(now()))
            return run_id
        finally:
            os.close(fd)                # releases the lock
    finally:
        conn.close()
