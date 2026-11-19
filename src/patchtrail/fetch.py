# SPDX-License-Identifier: Apache-2.0
"""A fetch run: under a lock, discover new patches, fetch their threads, let each
project's trail fetch its repos once and follow each patch, and record a snapshot
of every patch whose state changed. Progress goes to the runs and run_log tables."""

import contextlib
import dataclasses
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

    def __init__(self, conn, run_id: int, now=time.time, echo=None):
        self.echo = echo        # called with every log line, e.g. to print it
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
        if self.echo is not None:
            self.echo(line)


def last_run(conn) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()


# --- views --------------------------------------------------------------------

def _below(mails: list[MailInfo], parents: dict[str, str | None], root: str,
           stop: set[str]) -> list[MailInfo]:
    """The root and every mail below it through the stored parents, in the given
    order, not entering the threads of the stop msgids."""
    children: dict[str | None, list[str]] = {}
    for m in mails:
        children.setdefault(parents[m.msgid], []).append(m.msgid)
    seen, todo = {root}, [root]
    while todo:
        for c in children.get(todo.pop(), ()):
            if c not in seen and c not in stop:
                seen.add(c)
                todo.append(c)
    return [m for m in mails if m.msgid in seen]


def _load(conn, row) -> tuple[PatchView, list[MailInfo]]:
    """The patch as the trails see it, and the mails of its newest series revision
    (its root and the mails below it), which drive its standing."""
    pid = row["id"]
    revs = store.revisions(conn, pid)
    newest = store.newest_series(revs)
    raws, parents, mails = {}, {}, []
    for m in store.patch_mails(conn, pid):
        raws[m["msgid"]], parents[m["msgid"]] = bytes(m["raw"]), m["in_reply_to"]
        mails.append(parse_mail(raws[m["msgid"]]))
    backports: dict[str, list[str]] = {}
    for r in revs:
        if r["kind"] == "backport" and r["branch"]:
            backports.setdefault(r["branch"], []).append(r["root_msgid"])
    newest_mails, subject, author, posted_at, files = mails, "", "", 0, {}
    if newest is not None:
        root = newest["root_msgid"]
        newest_mails = _below(mails, parents, root, {r["root_msgid"] for r in revs} - {root})
        author = newest["author"] or ""
        posted_at = newest["posted_at"] or 0
        own = [m for m in newest_mails if author and m.from_addr == author and not m.is_reply]
        subject = head_subject(own) or head_subject(newest_mails) or newest["subject"]
        for m in own:
            files.update(dict.fromkeys(_DIFF_PATH.findall(text_body(raws[m.msgid])[0])))
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
    return view, newest_mails


def _compose(row, view: PatchView, standing_mails: list[MailInfo], mine: frozenset[str],
             fragment: dict) -> dict:
    return compose_state(
        project=get_project(row["project"]),
        standing=standing(standing_mails, mine, following=row["relation"] == "following"),
        mails=view.mails, fragment=fragment, manual_applied=bool(row["manual_applied"]),
        closed=row["closed"], closed_note=row["closed_note"])


def compose_for(conn, row, mine: frozenset[str], fragment: dict, *,
                only: set[str] | None = None) -> dict:
    """The state a fetch run would record for the patch with this trail fragment.
    only restricts the mails to those msgids."""
    view, newest = _load(conn, row)
    mails = view.mails
    if only is not None:
        mails = [m for m in mails if m.msgid in only]
        newest = [m for m in newest if m.msgid in only]
        view = dataclasses.replace(view, mails=mails)
    return _compose(row, view, newest, mine, fragment)


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
        # Patches with a revision whose fetch failed and whose root mail is not stored.
        self.unfetched: set[int] = set()

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
        not_fetched = set()
        for row in rows:
            for rev in revs[row["id"]]:
                self.progress.step(f"{row['name']} v{rev['version']}" if rev["kind"] == "series"
                                   else f"{row['name']} backport {rev['branch']}")
                if not self._fetch(row, rev):
                    not_fetched.add(rev["id"])
        # Second pass: a root mail may have come with any thread of this run.
        synced = set()
        for row in rows:
            roots = {rev["id"]: self._sync(rev) for rev in revs[row["id"]]}
            synced.update(roots)
            if any(roots[i] is None and i in not_fetched for i in roots):
                self.unfetched.add(row["id"])
            series_roots = [roots[r["id"]] for r in revs[row["id"]]
                            if r["kind"] == "series" and roots[r["id"]] is not None]
            if series_roots and not row["project_override"]:
                newest = series_roots[-1]
                project = detect_project(newest.to_cc, newest.subject)
                if project != row["project"]:
                    store.set_field(self.conn, row["id"], "project", project)
        # A change-id taken from below a root before the revision there was tracked
        # is stale now, also in patches this run did not select.
        for rev in store.revisions_sharing_change_id(self.conn):
            if rev["id"] not in synced:
                self._sync(rev)
        ids = {row["id"] for row in rows}
        merged = merge_by_change_id(self.conn)
        for name in merged:
            self.progress.log(f"merged: {name}")
        if merged:      # a merged patch lives on in the patch that took its revisions
            owners = (store.revision_by_msgid(self.conn, rev["root_msgid"])
                      for rs in revs.values() for rev in rs)
            ids |= {o["patch_id"] for o in owners if o is not None}
        return [p for p in store.list_patches(self.conn) if p["id"] in ids]

    def _fetch(self, row, rev) -> bool:
        """Store the revision's thread; False if lore did not give it."""
        root_id = rev["root_msgid"]
        try:
            raws = self.source.fetch(root_id)
        except Exception as e:      # the patch keeps its stored mails and state
            self.progress.log(f"{row['name']}: cannot fetch <{root_id}>: {_why(e)}")
            return False
        try:
            if self.conn.execute("SELECT 1 FROM revisions WHERE id=?", (rev["id"],)).fetchone() is None:
                self.progress.log(f"{row['name']}: removed during the run")
                return False
            store.upsert_mails(self.conn, rev["id"], raws, int(self.now()))
        except sqlite3.Error as e:  # e.g. the patch was removed while the thread came in
            self.conn.rollback()
            self.progress.log(f"{row['name']}: cannot store <{root_id}>: {_why(e)}")
            return False
        return True

    def _sync(self, rev) -> MailInfo | None:
        """Take the revision's subject, author, posted_at and change-id from its root
        mail, wherever another thread stored it; return the root, None if not stored."""
        root_id = rev["root_msgid"]
        thread = store.thread_mails(self.conn, root_id)
        raw = next((bytes(m["raw"]) for m in thread if m["msgid"] == root_id), None)
        if raw is None:
            return None
        root = parse_mail(raw)
        want = {"subject": root.subject, "author": root.from_addr,
                "posted_at": root.date or rev["posted_at"]}
        # The root's own change-id, else one from the author's mails below it. Never
        # one from the rest of the thread or from another revision's thread below
        # (thread_mails stops there): that one names another series. Worked out
        # afresh each time, as the revisions tracked below the root change.
        below = (parse_mail(bytes(m["raw"])) for m in thread if m["msgid"] != root_id)
        want["change_id"] = root.change_id or next(
            (m.change_id for m in below
             if m.change_id and root.from_addr and m.from_addr == root.from_addr), None)
        store.set_revision(self.conn, rev["id"],
                           **{k: v for k, v in want.items() if v != rev[k]})
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
            try:
                self._evaluate_one(row, loaded, ready)
            except Exception as e:      # e.g. the patch was removed while the run went on
                self.conn.rollback()
                self.progress.log(f"{row['name']}: cannot record its state: {_why(e)}")

    def _evaluate_one(self, row, loaded, ready) -> None:
        view, standing_mails = loaded[row["id"]]
        failed = row["project"] not in ready
        if failed:
            fragment = _previous(view)
        elif ready[row["project"]] is None:
            fragment = _empty()
        else:
            fragment, failed = self._follow(row, view, ready[row["project"]])
        # What the user changed during the run (close, mark-applied, hide, ...) wins:
        # read the row again, and drop a patch that was removed.
        fresh = store.patch_by_id(self.conn, row["id"])
        if fresh is None:
            self.progress.log(f"{row['name']}: removed during the run")
            return
        row = fresh
        if (view.prev_state is None and row["read_on_first_snapshot"]
                and (failed or row["id"] in self.unfetched)):
            # A first snapshot from half a run would use up read_on_first_snapshot,
            # and the patch would flag once the rest arrives. Other patches are
            # unread until read anyway, so they record what there is.
            self.progress.log(f"{row['name']}: first snapshot waits for a complete fetch")
            return
        state = _compose(row, view, standing_mails, self.mine, fragment)
        record(self.conn, row["id"], state, int(self.now()))
        self.conn.commit()

    def _follow(self, row, view: PatchView, trail: Trail) -> tuple[dict, bool]:
        """The trail's fragment for the patch, and whether the trail failed."""
        try:
            result = trail.evaluate(view, self.progress)
        except Exception as e:
            self.progress.log(f"{row['name']}: cannot follow the trail: {_why(e)}")
            return _previous(view), True
        self._store(row, result)
        return result.fragment, False

    def _store(self, row, result: TrailResult) -> None:
        pid = row["id"]
        for old, new in result.replaced.items():
            subject = next((c.get("subject") or "" for c in result.fragment.get("commits", [])
                            if c["sha"][:12] == new[:12]), "")
            store.replace_commit(self.conn, pid, old, new, subject, source="search")
        for sha, subject, source in result.commits_found:
            store.set_commit(self.conn, pid, sha, subject, source)
        if result.tree:
            # One statement, so a tree the user sets by hand meanwhile is never overwritten.
            url, branch = result.tree
            self.conn.execute(
                "UPDATE patches SET tree_url=?, tree_branch=?, tree_source='auto' WHERE id=?"
                " AND tree_source IS NOT 'manual' AND (tree_url IS NOT ? OR tree_branch IS NOT ?"
                " OR tree_source IS NOT 'auto')", (url, branch, pid, url, branch))
            self.conn.commit()


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


@contextlib.contextmanager
def locked(paths: Paths, conn):
    """Hold the fetch lock; raise Busy, with the running run's row, when another
    process holds it. conn only reads that row."""
    fd = os.open(paths.lock, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy(conn.execute("SELECT * FROM runs WHERE status='running'"
                                    " ORDER BY id DESC LIMIT 1").fetchone()) from None
        yield
    finally:
        os.close(fd)                # releases the lock


def reevaluate(conn, paths: Paths, cfg: Config, patch_id: int) -> int | None:
    """Record the patch's state again from its stored mails, the changes made by hand
    and the trail fragment of its last snapshot. No network. Returns the new snapshot's
    id, None if nothing changed or if the patch has no snapshot yet and is waiting for
    its first complete fetch."""
    row = store.patch_by_id(conn, patch_id)
    view, _ = _load(conn, row)
    if view.prev_state is None and row["read_on_first_snapshot"]:
        return None
    state = compose_for(conn, row, my_addresses(cfg), _previous(view))
    snap = record(conn, patch_id, state, int(time.time()))
    store.commit(conn)
    return snap


def run_fetch(paths: Paths, cfg: Config, trigger: str, *, source=None, trails=None, search=None,
              now=time.time, patch_names: list[str] | None = None,
              discover_new: bool = True, echo=None) -> int:
    """One fetch run; returns its id. Raises Busy when another run holds the lock.
    echo is called with each progress line as it is logged."""
    source = LoreSource() if source is None else source
    search = lore.search if search is None else search
    conn = db.connect(paths.db)
    try:
        with locked(paths, conn):
            # The lock proves that no process runs these any more.
            conn.execute("UPDATE runs SET status='interrupted', finished_at=?"
                         " WHERE status='running'", (int(now()),))
            run_id = conn.execute("INSERT INTO runs (pid, trigger, started_at, status)"
                                  " VALUES (?,?,?,'running')",
                                  (os.getpid(), trigger, int(now()))).lastrowid
            conn.commit()
            progress = DbProgress(conn, run_id, now, echo)
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
        conn.close()
