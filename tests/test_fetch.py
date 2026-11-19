# SPDX-License-Identifier: Apache-2.0
import fcntl
import http.client
import os

import pytest

from patchtrail import snapshot, store
from patchtrail.config import load_config, paths
from patchtrail.fetch import Busy, DbProgress, build_view, last_run, run_fetch
from patchtrail.projects.base import Trail, TrailResult
from patchtrail.sources.base import Source
from patchtrail.sources.lore import Entry, LoreError
from conftest import raising
from mails import make_mail

nosearch = lambda *a, **k: []  # noqa: E731
NOV11 = 1794414425                     # make_mail's default date


def empty():
    return {"commits": [], "branches": {}, "failed": {}, "hint": None}


def E(msgid, subject, author="me@example.org", updated="2026-11-11T16:27:05Z"):
    return Entry(msgid, subject, author, updated, False, f"https://lore.kernel.org/all/{msgid}/")


class FakeSource(Source):
    def __init__(self, threads=None, entries=()):
        self.threads = threads or {}
        self.entries = entries
        self.fetched = []

    def fetch(self, root_msgid):
        self.fetched.append(root_msgid)
        got = self.threads.get(root_msgid, LoreError("not on lore yet?"))
        if isinstance(got, BaseException):
            raise got
        return got

    def discover(self, addresses, since):
        if isinstance(self.entries, BaseException):
            raise self.entries
        return list(self.entries)


class FakeTrail(Trail):
    def __init__(self, result=None, prepare_error=None, evaluate_error=None):
        self.result = result
        self.prepare_error = prepare_error
        self.evaluate_error = evaluate_error
        self.prepared = []
        self.evaluated = []

    def prepare(self, patches, progress):
        self.prepared.append([p.name for p in patches])
        if self.prepare_error:
            raise self.prepare_error

    def evaluate(self, patch, progress):
        self.evaluated.append(patch.name)
        if self.evaluate_error:
            raise self.evaluate_error
        return self.result or TrailResult([], None, empty())


@pytest.fixture
def cfgp():
    p = paths()
    p.home.mkdir(parents=True, exist_ok=True)
    return p, load_config(p)


def log_lines(conn, rid):
    return [r[0] for r in conn.execute("SELECT line FROM run_log WHERE run_id=? ORDER BY rowid",
                                       (rid,))]


def phases_seen(conn, rid):
    return [l.removeprefix("phase: ") for l in log_lines(conn, rid) if l.startswith("phase: ")]


def snapshots(conn, pid):
    return conn.execute("SELECT count(*) FROM snapshots WHERE patch_id=?", (pid,)).fetchone()[0]


def commit(sha, stage="applied", subject="io: fix"):
    return {"sha": sha, "subject": subject, "where": "mainline", "stage": stage, "release": None,
            "stable": False, "cc": None, "fixes": []}


# --- the plan's tests -------------------------------------------------------

def test_run_records_snapshots_and_project(conn, cfgp):
    src = FakeSource(threads={"a@x": [make_mail("a@x", to="io-uring@vger.kernel.org",
                                                subject="[PATCH] io_uring/io-wq: x")]},
                     entries=[E("a@x", "[PATCH] io_uring/io-wq: x")])
    rid = run_fetch(*cfgp, "cli", source=src, trails={"kernel": FakeTrail()}, search=nosearch,
                    now=lambda: 100)
    p = store.list_patches(conn)[0]
    assert p["project"] == "kernel" and snapshot.latest(conn, p["id"]) is not None
    assert conn.execute("SELECT status FROM runs WHERE id=?", (rid,)).fetchone()[0] == "ok"
    assert not snapshot.unread(conn, p["id"])                     # first discovery arrives read


def test_failed_thread_keeps_state(conn, cfgp):                   # Review Focus 1
    good = FakeSource(threads={"a@x": [make_mail("a@x", to="io-uring@vger.kernel.org"),
                                       make_mail("b@x", frm="X <x@y.org>", subject="Re: [PATCH] fix io",
                                                 in_reply_to="a@x")]},
                      entries=[E("a@x", "[PATCH] fix io")])
    run_fetch(*cfgp, "cli", source=good, trails={"kernel": FakeTrail()}, search=nosearch)
    pid = store.list_patches(conn)[0]["id"]
    n = snapshots(conn, pid)
    bad = FakeSource(threads={"a@x": LoreError("lore is down")})
    rid2 = run_fetch(*cfgp, "cli", source=bad, trails={"kernel": FakeTrail()}, search=nosearch)
    assert snapshots(conn, pid) == n and not snapshot.unread(conn, pid)
    assert any("cannot fetch <a@x>: lore is down" in l for l in log_lines(conn, rid2))


def test_busy_when_locked(cfgp):                                  # Review Focus 2
    fd = os.open(cfgp[0].lock, os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    with pytest.raises(Busy):
        run_fetch(*cfgp, "cli", source=FakeSource(), trails={}, search=nosearch)
    os.close(fd)


def test_stale_run_marked_interrupted(conn, cfgp):                # Review Focus 2
    conn.execute("INSERT INTO runs(pid,trigger,started_at,status) VALUES (999999,'cli',1,'running')")
    conn.commit()
    run_fetch(*cfgp, "cli", source=FakeSource(), trails={}, search=nosearch, now=lambda: 50)
    row = conn.execute("SELECT status, finished_at FROM runs WHERE id=1").fetchone()
    assert tuple(row) == ("interrupted", 50)


def test_phases_recorded(conn, cfgp):
    rid = run_fetch(*cfgp, "cli", source=FakeSource(), trails={}, search=nosearch)
    assert phases_seen(conn, rid) == ["discover", "threads", "repos", "evaluate"]


# --- lock, run rows and progress ----------------------------------------------

def test_busy_carries_the_running_run_and_leaves_it_alone(conn, cfgp):
    conn.execute("INSERT INTO runs(pid,trigger,started_at,status,phase,step,steps)"
                 " VALUES (4242,'service',1,'running','threads',3,12)")
    conn.commit()
    fd = os.open(cfgp[0].lock, os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    with pytest.raises(Busy) as e:
        run_fetch(*cfgp, "cli", source=FakeSource(), trails={}, search=nosearch)
    os.close(fd)
    assert (e.value.run["id"], e.value.run["phase"], e.value.run["step"]) == (1, "threads", 3)
    assert [tuple(r) for r in conn.execute("SELECT id, status FROM runs")] == [(1, "running")]


def test_run_row(conn, cfgp):
    assert last_run(conn) is None
    run_fetch(*cfgp, "cli", source=FakeSource(), trails={}, search=nosearch, now=lambda: 7)
    rid = run_fetch(*cfgp, "service", source=FakeSource(), trails={}, search=nosearch, now=lambda: 9)
    r = last_run(conn)
    assert (r["id"], r["pid"], r["trigger"], r["started_at"], r["finished_at"], r["status"]) == (
        rid, os.getpid(), "service", 9, 9, "ok")


def test_unexpected_error_fails_the_run_and_releases_the_lock(conn, cfgp, monkeypatch):
    monkeypatch.setattr("patchtrail.fetch.merge_by_change_id", raising(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        run_fetch(*cfgp, "cli", source=FakeSource(), trails={}, search=nosearch, now=lambda: 3)
    r = last_run(conn)
    assert (r["status"], r["finished_at"]) == ("failed", 3) and "boom" in r["error"]
    monkeypatch.undo()
    rid = run_fetch(*cfgp, "cli", source=FakeSource(), trails={}, search=nosearch)
    assert last_run(conn)["status"] == "ok" and rid == r["id"] + 1


def test_interrupt_marks_the_run_interrupted(conn, cfgp):
    pid = store.add_patch(conn, "p", now=1)
    store.add_revision(conn, pid, "a@x")
    with pytest.raises(KeyboardInterrupt):
        run_fetch(*cfgp, "cli", source=FakeSource({"a@x": KeyboardInterrupt()}), trails={},
                  search=nosearch, now=lambda: 4)
    r = last_run(conn)
    assert (r["status"], r["finished_at"]) == ("interrupted", 4)


def test_db_progress(conn):
    rid = conn.execute("INSERT INTO runs(pid,trigger,started_at,status)"
                       " VALUES (1,'cli',1,'running')").lastrowid
    p = DbProgress(conn, rid, now=lambda: 5)
    p.phase("threads", 2)
    p.step("iowq-cpuset")
    r = conn.execute("SELECT phase, step, steps FROM runs WHERE id=?", (rid,)).fetchone()
    assert tuple(r) == ("threads", 1, 2)
    p.phase("repos")
    p.step("mainline")
    p.log("tree x: gone")
    r = conn.execute("SELECT phase, step, steps FROM runs WHERE id=?", (rid,)).fetchone()
    assert tuple(r) == ("repos", 1, None)
    assert log_lines(conn, rid) == ["phase: threads", "step 1/2: iowq-cpuset", "phase: repos",
                                    "step 1: mainline", "tree x: gone"]
    assert {r[0] for r in conn.execute("SELECT at FROM run_log")} == {5}


# --- threads ----------------------------------------------------------------

def test_first_fetch_fills_revision_project_and_keeps_relation(conn, cfgp):
    theirs = store.add_patch(conn, "theirs", relation="following", now=1)
    store.add_revision(conn, theirs, "t@x")
    other = store.add_patch(conn, "other-address", now=1)       # mine, sent from another address
    store.add_revision(conn, other, "o@x")
    fixed = store.add_patch(conn, "fixed", now=1)
    store.add_revision(conn, fixed, "f@x")
    store.set_field(conn, fixed, "project", "custom")
    store.set_field(conn, fixed, "project_override", 1)
    src = FakeSource({
        "t@x": [make_mail("t@x", frm="Them <them@y.org>", to="qemu-devel@nongnu.org",
                          subject="[PATCH] hw/vfio: x"),
                make_mail("r@x", frm="Rev <rev@z.org>", subject="Re: [PATCH] hw/vfio: x",
                          in_reply_to="t@x", date="Thu, 12 Nov 2026 10:00:00 +0000")],
        "o@x": [make_mail("o@x", frm="Me <me@work.example>", to="grub-devel@gnu.org",
                          subject="[PATCH] grub: y")],
        "f@x": [make_mail("f@x", to="list@vger.kernel.org")]})
    run_fetch(*cfgp, "cli", source=src, trails={}, search=nosearch, discover_new=False)
    rev = store.revision_by_msgid(conn, "t@x")
    assert (rev["subject"], rev["author"], rev["posted_at"]) == ("[PATCH] hw/vfio: x", "them@y.org", NOV11)
    p = store.patch_by_id(conn, theirs)
    assert (p["project"], p["relation"]) == ("qemu", "following")
    assert snapshot.latest(conn, theirs)[2]["standing"]["kind"] == "new_reply"
    p = store.patch_by_id(conn, other)
    assert (p["project"], p["relation"]) == ("grub", "mine")
    assert store.patch_by_id(conn, fixed)["project"] == "custom"


def test_selection_hidden_closed_and_names(conn, cfgp):
    for name in "abcd":
        pid = store.add_patch(conn, name, now=1)
        store.add_revision(conn, pid, f"{name}@x")
    store.set_field(conn, store.get_patch(conn, "c")["id"], "hidden", 1)
    store.set_field(conn, store.get_patch(conn, "d")["id"], "closed", "dropped")
    threads = {f"{n}@x": [make_mail(f"{n}@x")] for n in "abcdn"}
    src = FakeSource(threads, entries=[E("n@x", "[PATCH] new one")])
    rid = run_fetch(*cfgp, "cli", source=src, trails={}, search=nosearch, patch_names=["a", "c"])
    assert src.fetched == ["a@x"] and store.get_patch(conn, "new-one") is None
    assert phases_seen(conn, rid) == ["threads", "repos", "evaluate"]
    src.fetched.clear()
    run_fetch(*cfgp, "cli", source=src, trails={}, search=nosearch)
    assert src.fetched == ["a@x", "b@x", "n@x"]


def test_discovery_failure_is_logged_and_the_run_goes_on(conn, cfgp):
    pid = store.add_patch(conn, "p", now=1)
    store.add_revision(conn, pid, "a@x")
    src = FakeSource({"a@x": [make_mail("a@x")]}, entries=LoreError("lore search failed: HTTP 429"))
    rid = run_fetch(*cfgp, "cli", source=src, trails={}, search=nosearch)
    assert "discover: lore search failed: HTTP 429" in log_lines(conn, rid)
    assert src.fetched == ["a@x"] and last_run(conn)["status"] == "ok"
    assert store.kv_get(conn, "last_discovery") is None


def test_change_id_merges_patches(conn, cfgp):                    # R8
    body = "Why.\n\n---\nchange-id: 20261111-io-abc\n"
    src = FakeSource({"a@x": [make_mail("a@x", subject="[PATCH] io: first try", body=body)],
                      "b@x": [make_mail("b@x", subject="[PATCH v2] io: better name", body=body,
                                        date="Thu, 12 Nov 2026 10:00:00 +0000")]},
                     entries=[E("a@x", "[PATCH] io: first try"), E("b@x", "[PATCH v2] io: better name")])
    rid = run_fetch(*cfgp, "cli", source=src, trails={}, search=nosearch)
    [p] = store.list_patches(conn)
    assert p["name"] == "io-first-try"
    assert [(r["root_msgid"], r["change_id"]) for r in store.revisions(conn, p["id"])] == [
        ("a@x", "20261111-io-abc"), ("b@x", "20261111-io-abc")]
    assert "merged: io-better-name" in log_lines(conn, rid)
    assert snapshot.latest(conn, p["id"])[2]["mails"] == ["a@x", "b@x"]


# --- views and standing -------------------------------------------------------

def test_build_view(conn):                                        # R18
    pid = store.add_patch(conn, "p", now=1)
    v1 = store.add_revision(conn, pid, "a@x", subject="[PATCH] fix io", author="me@example.org",
                            posted_at=100)
    v2 = store.add_revision(conn, pid, "b@x", version=2, subject="[PATCH v2 0/2] fix io",
                            author="me@example.org", posted_at=200)
    store.add_revision(conn, pid, "c@x", subject="[PATCH 6.1] io: a", kind="backport", branch="6.1")
    store.add_revision(conn, pid, "d@x", subject="[PATCH 6.1] io: b", kind="backport", branch="6.1")
    store.upsert_mails(conn, v1, [make_mail("a@x", date="Mon, 09 Nov 2026 10:00:00 +0000")], 1)
    day = "Tue, 10 Nov 2026 10:00:0{} +0000"
    store.upsert_mails(conn, v2, [
        make_mail("b@x", subject="[PATCH v2 0/2] fix io", date=day.format(0)),
        make_mail("b1@x", subject="[PATCH v2 1/2] io: a", in_reply_to="b@x", date=day.format(1),
                  body="---\n+++ b/io.c\n"),
        make_mail("b2@x", subject="[PATCH v2 2/2] fs: b", in_reply_to="b@x", date=day.format(2),
                  body="---\n+++ b/fs/x.c\n@@\n+++ b/io.c\n"),
        make_mail("b3@x", frm="X <x@y.org>", subject="Re: [PATCH v2 1/2] io: a", in_reply_to="b1@x",
                  date=day.format(3), body="> +++ b/quoted.c\n+++ b/reply.c\n"),
        make_mail("b4@x", frm="X <x@y.org>", subject="[PATCH] alt: c", in_reply_to="b@x",
                  date=day.format(4), body="+++ b/other-author.c\n"),
        make_mail("b5@x", subject="Re: [PATCH v2 1/2] io: a", in_reply_to="b3@x",
                  date=day.format(5), body="+++ b/my-reply.c\n")], 1)
    store.set_commit(conn, pid, "a" * 40, "io: a", "applied-mail")
    store.set_field(conn, pid, "tree_url", "https://t/axboe.git")
    store.set_field(conn, pid, "tree_branch", "io_uring-7.4")
    store.set_field(conn, pid, "tree_source", "manual")
    store.set_field(conn, pid, "force_stable", 1)
    conn.execute("INSERT INTO branch_skips VALUES (?, '5.15')", (pid,))
    snapshot.record(conn, pid, {"stage": "accepted"}, 5)
    v = build_view(conn, store.patch_by_id(conn, pid), frozenset({"me@example.org"}))
    assert (v.id, v.name, v.relation, v.project) == (str(pid), "p", "mine", "unknown")
    assert [m.msgid for m in v.mails] == ["a@x", "b@x", "b1@x", "b2@x", "b3@x", "b4@x", "b5@x"]
    assert (v.posted_at, v.subject, v.author) == (200, "[PATCH v2 0/2] fix io", "me@example.org")
    assert v.files == ("io.c", "fs/x.c")
    assert v.commits == [{"sha": "a" * 40, "subject": "io: a", "source": "applied-mail"}]
    assert (v.tree, v.tree_source) == (("https://t/axboe.git", "io_uring-7.4"), "manual")
    assert (v.force_stable, v.manual_applied, v.skips) == (True, False, frozenset({"5.15"}))
    assert v.backports == {"6.1": ["c@x", "d@x"]}
    assert v.prev_state == {"stage": "accepted"}


def test_newest_revision_drives_standing(conn, cfgp):
    pid = store.add_patch(conn, "p", now=1)
    store.add_revision(conn, pid, "a@x", subject="[PATCH] fix io")
    store.add_revision(conn, pid, "b@x", version=2, subject="[PATCH v2] fix io")
    store.add_revision(conn, pid, "c@x", subject="[PATCH 6.1] fix io", kind="backport", branch="6.1")
    src = FakeSource({
        "a@x": [make_mail("a@x", date="Mon, 09 Nov 2026 10:00:00 +0000"),
                make_mail("a1@x", frm="X <x@y.org>", subject="Re: [PATCH] fix io", in_reply_to="a@x",
                          date="Thu, 12 Nov 2026 10:00:00 +0000", body="Reviewed-by: X <x@y.org>\n")],
        "b@x": [make_mail("b@x", subject="[PATCH v2] fix io", date="Tue, 10 Nov 2026 10:00:00 +0000")],
        "c@x": [make_mail("c@x", subject="[PATCH 6.1] fix io", to="stable@vger.kernel.org"),
                make_mail("c1@x", frm="Greg <greg@k.org>", subject="Re: [PATCH 6.1] fix io",
                          in_reply_to="c@x", date="Fri, 13 Nov 2026 10:00:00 +0000")]})
    run_fetch(*cfgp, "cli", source=src, trails={}, search=nosearch, discover_new=False)
    state = snapshot.latest(conn, pid)[2]
    assert (state["standing"]["kind"], state["trailers"]) == ("waiting_reply", [])
    assert state["mails"] == ["a1@x", "a@x", "b@x", "c1@x", "c@x"]


# --- trails -------------------------------------------------------------------

def kernel_patch(conn, name="p", root="a@x"):
    pid = store.add_patch(conn, name, project="kernel", now=1)
    store.add_revision(conn, pid, root)
    return pid


def test_trail_results_are_stored(conn, cfgp):                    # R21
    pid = kernel_patch(conn)
    manual = kernel_patch(conn, "m", "m@x")
    store.set_commit(conn, pid, "a" * 12, "io: fix", "search")
    store.set_field(conn, manual, "tree_url", "https://mine")
    store.set_field(conn, manual, "tree_branch", "fixes")
    store.set_field(conn, manual, "tree_source", "manual")
    found = TrailResult(commits_found=[("b" * 40, "io: more", "applied-mail")],
                        tree=("https://t/axboe.git", "for-next"),
                        fragment={**empty(), "commits": [commit("c" * 40, subject="io: fix again"),
                                                         commit("b" * 40, subject="io: more")]},
                        replaced={"a" * 40: "c" * 40})
    src = FakeSource({"a@x": [make_mail("a@x")], "m@x": [make_mail("m@x")]})
    run_fetch(*cfgp, "cli", source=src, trails={"kernel": FakeTrail(found)}, search=nosearch)
    assert [(c["sha"], c["subject"], c["source"]) for c in store.commits(conn, pid)] == [
        ("c" * 40, "io: fix again", "search"), ("b" * 40, "io: more", "applied-mail")]
    p, m = store.patch_by_id(conn, pid), store.patch_by_id(conn, manual)
    assert (p["tree_url"], p["tree_branch"], p["tree_source"]) == ("https://t/axboe.git", "for-next", "auto")
    assert (m["tree_url"], m["tree_branch"], m["tree_source"]) == ("https://mine", "fixes", "manual")
    assert [c["sha"] for c in snapshot.latest(conn, pid)[2]["commits"]] == ["c" * 40, "b" * 40]


def test_trail_failures_keep_the_previous_fragment(conn, cfgp):  # carried robustness rule
    pid = kernel_patch(conn)
    src = FakeSource({"a@x": [make_mail("a@x")]})
    fragment = {"commits": [commit("c" * 40)], "branches": {"6.1": {"c" * 12: {"state": "queued"}}},
                "failed": {"6.1": {"date": "2026-11-12"}}, "hint": "ask stable"}
    run_fetch(*cfgp, "cli", source=src, trails={"kernel": FakeTrail(TrailResult(fragment=fragment))},
              search=nosearch)
    before = snapshot.latest(conn, pid)

    broken = FakeTrail(prepare_error=RuntimeError("git fetch died"))
    rid = run_fetch(*cfgp, "cli", source=src, trails={"kernel": broken}, search=nosearch)
    assert "kernel: cannot update repos: RuntimeError: git fetch died" in log_lines(conn, rid)
    assert broken.evaluated == [] and snapshot.latest(conn, pid) == before

    broken = FakeTrail(evaluate_error=http.client.IncompleteRead(b""))
    rid = run_fetch(*cfgp, "cli", source=FakeSource({"a@x": OSError("b4 died")}),
                    trails={"kernel": broken}, search=nosearch)
    lines = log_lines(conn, rid)
    assert "p: cannot fetch <a@x>: OSError: b4 died" in lines
    assert any(l.startswith("p: cannot follow the trail: IncompleteRead") for l in lines)
    assert snapshot.latest(conn, pid) == before and last_run(conn)["status"] == "ok"


def test_mail_only_project_without_trail(conn, cfgp):
    pid = store.add_patch(conn, "q", now=1)
    store.add_revision(conn, pid, "q@x")
    src = FakeSource({"q@x": [make_mail("q@x", to="qemu-devel@nongnu.org", subject="[PATCH] hw: q"),
                              make_mail("q1@x", frm="Maint <m@q.org>", subject="Re: [PATCH] hw: q",
                                        in_reply_to="q@x", body="Applied, thanks.\n",
                                        date="Thu, 12 Nov 2026 10:00:00 +0000")]})
    run_fetch(*cfgp, "cli", source=src, search=nosearch, discover_new=False)   # registry trails
    state = snapshot.latest(conn, pid)[2]
    assert state["stage"] == "accepted" and state["standing"]["kind"] == "applied"
    assert {k: state[k] for k in ("commits", "branches", "failed", "hint")} == empty()
