# SPDX-License-Identifier: Apache-2.0
import urllib.request

import pytest


@pytest.fixture(autouse=True)
def hermetic(tmp_path, monkeypatch):
    """Isolate every test from the real home, git config and network."""
    home = tmp_path / "home"
    home.mkdir()
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("[user]\n\tname = Test User\n\temail = me@example.org\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATCHTRAIL_HOME", str(tmp_path / "ptl"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.delenv("PATCHTRAIL_FROM", raising=False)
    b4 = tmp_path / "no-b4"
    b4.write_text("#!/bin/sh\necho 'b4 called in tests' >&2\nexit 99\n")
    b4.chmod(0o755)
    monkeypatch.setenv("PATCHTRAIL_B4", str(b4))

    def no_network(*args, **kwargs):
        raise AssertionError("network in tests")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    return home


@pytest.fixture
def conn():
    from patchtrail import db
    from patchtrail.config import paths

    c = db.connect(paths().db)
    yield c
    c.close()


class NullProgress:
    def phase(self, name, steps=None):
        pass

    def step(self, label):
        pass

    def log(self, line):
        pass


@pytest.fixture(scope="session")
def kfix(tmp_path_factory):
    from gitfix import make_kernel_fixture

    return make_kernel_fixture(tmp_path_factory.mktemp("kfix"))


@pytest.fixture
def fetched(tmp_path, kfix):
    from patchtrail.projects.kernel.repo import KernelRepo

    r = KernelRepo(tmp_path / "linux.git")
    r.ensure(None)
    r.fetch(kfix.urls, ["6.0", "6.1", "6.2", "6.3", "6.4"], [(kfix.tree_url, "*")], NullProgress())
    return r


@pytest.fixture
def queue(tmp_path, kfix):
    from patchtrail.projects.kernel.queue import StableQueue

    q = StableQueue(tmp_path / "stable-queue")
    q.update(kfix.urls.queue, NullProgress())
    return q


# Task 9: patch views, mails and fakes for the trails.

def epoch(day: str) -> int:
    """Seconds since the epoch at 00:00 UTC of YYYY-MM-DD."""
    from datetime import datetime, timezone

    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


@pytest.fixture
def view():
    from patchtrail.projects.base import PatchView

    def make(**kw):
        fields = dict(id=1, name="p", relation="mine", project="kernel", mails=[],
                      posted_at=epoch("2026-01-01"), subject="[PATCH] fix io",
                      author="me@example.org", commits=[], tree=None, tree_source=None,
                      force_stable=False, skips=frozenset(), manual_applied=False,
                      backports={}, prev_state=None)
        fields.update(kw)
        return PatchView(**fields)

    return make


def root(subj):
    from mails import make_mail
    from patchtrail.mail import parse_mail

    return parse_mail(make_mail("r@x", subject=f"[PATCH] {subj}", body="---\n+++ b/io.c\n"))


def ty(blocks):
    from mails import make_mail
    from patchtrail.mail import parse_mail

    return parse_mail(make_mail("t@x", frm="Maint <m@k.org>", in_reply_to="r@x",
                                subject="Re: [PATCH] x", body="Applied, thanks!\n\n" + blocks))


def raising(exc):
    def call(*args, **kwargs):
        raise exc

    return call


class _FileResponse:
    def __init__(self, data: bytes):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_search_from(path):
    """lore.search answering every request with the file at path (relative to the repo)."""
    from pathlib import Path

    from patchtrail.sources import lore

    data = (Path(__file__).parent.parent / path).read_bytes()

    def search(inbox, query, **kwargs):
        return lore.search(inbox, query, urlopen=lambda req, timeout=None: _FileResponse(data))

    return search


@pytest.fixture
def upfix(tmp_path):
    from gitfix import make_upstream_fixture

    return make_upstream_fixture(tmp_path)


# Task 14: a populated database for the reading commands.

def _state(stage, mails, standing_text, *, commits=(), branches=None, failed=None):
    return {"stage": stage, "closed": None, "closed_note": None,
            "standing": {"kind": "new_reply", "who": "Jens Axboe", "since": 0,
                         "text": standing_text},
            "trailers": [], "mails": sorted(mails), "commits": list(commits),
            "branches": branches or {}, "failed": failed or {}, "hint": None,
            "finished": False}


def _add_patch(conn, name, project, root_id, mails, *, subject, now):
    from patchtrail import store

    pid = store.add_patch(conn, name, project=project, now=now)
    rev = store.add_revision(conn, pid, root_id, subject=subject, author="me@example.org",
                             posted_at=now)
    store.upsert_mails(conn, rev, mails, now)
    return pid


@pytest.fixture
def populated(conn):
    from mails import make_mail
    from patchtrail import snapshot, store

    now = epoch("2026-11-12")
    root_mail = make_mail("iowq@x", subject="[PATCH] io_uring/io-wq: apply the current cpuset"
                          " to new workers", to="linux-kernel@vger.kernel.org",
                          date="Wed, 11 Nov 2026 10:00:00 +0000")
    reply = make_mail("iowq-r1@x", frm="Jens Axboe <axboe@kernel.dk>", in_reply_to="iowq@x",
                      subject="Re: [PATCH] io_uring/io-wq: apply the current cpuset to new workers",
                      date="Thu, 12 Nov 2026 10:00:00 +0000", body="Applied, thanks!\n")
    pid = _add_patch(conn, "iowq-cpuset", "kernel", "iowq@x", [root_mail, reply],
                     subject="[PATCH] io_uring/io-wq: apply the current cpuset to new workers",
                     now=now)
    first = snapshot.record(conn, pid, _state("submitted", ["iowq@x"], "waiting for a reply"),
                            epoch("2026-11-11"))
    store.set_field(conn, pid, "read_snapshot_id", first)
    snapshot.record(conn, pid, _state("accepted", ["iowq@x", "iowq-r1@x"],
                                      "APPLIED by Jens Axboe, 2026-11-12"), now)
    erofs = make_mail("erofs@x", subject="[PATCH] erofs-utils: fix a thing",
                      to="linux-erofs@lists.ozlabs.org", date="Tue, 10 Nov 2026 10:00:00 +0000")
    eid = _add_patch(conn, "erofs", "erofs-utils", "erofs@x", [erofs],
                     subject="[PATCH] erofs-utils: fix a thing", now=now)
    snap = snapshot.record(conn, eid, _state("submitted", ["erofs@x"], "waiting for a reply"), now)
    store.set_field(conn, eid, "read_snapshot_id", snap)
    conn.commit()
    return conn


@pytest.fixture
def populated_kernel(populated):
    from patchtrail import snapshot, store

    pid = store.get_patch(populated, "iowq-cpuset")["id"]
    sha = "0659e44ce739" + "0" * 28
    st = snapshot.latest(populated, pid)[2]
    na = {"state": "not_affected", "tag": None, "detail": ["no 84eacf177faa"], "prereqs": []}
    cases = {"7.3": {"state": "released", "tag": "v7.3.2", "detail": [], "prereqs": []},
             "6.12": {"state": "in_branch", "tag": None, "detail": [], "prereqs": []},
             "6.6": {"state": "queued", "tag": None, "prereqs": [],
                     "detail": ["queued for the next 6.6 release: queue-6.6/x.patch"]},
             "6.1": {"state": "conflict", "tag": None, "prereqs": [
                 {"sha": "a" * 40, "subject": "io_uring: earlier change", "tag": "v6.2",
                  "cc": None, "fixes": []}],
                     "detail": ["CONFLICT in io_uring/io-wq.c, after 2 queued patches to the "
                                "same files: needs a backport by hand"]},
             "5.15": na, "5.10": na}
    st["commits"] = [{"sha": sha, "subject": "io_uring/io-wq: apply the current cpuset",
                      "where": "mainline", "stage": "released", "release": "v7.4-rc1",
                      "stable": True, "cc": "", "fixes": [
                          {"sha": "84eacf177faa" + "0" * 28, "release": "v5.18", "known": True}]}]
    st["branches"] = {s: {"0659e44ce739": e} for s, e in cases.items()}
    snapshot.record(populated, pid, st, epoch("2026-11-13"))
    populated.commit()
    return populated


# Task 16: the old scripts' files, as lkml-watch left them.

@pytest.fixture
def old_scripts_home(hermetic):
    from mails import make_mail, mbox

    cfg = hermetic / ".config" / "lkml-watch"
    state = hermetic / ".local" / "state" / "lkml-watch"
    cfg.mkdir(parents=True)
    state.mkdir(parents=True)
    (cfg / "threads").write_text("old-thread old1@x # from lkml-watch\n")
    raw = make_mail("old1@x", subject="[PATCH] kvm: fix bar",
                    to="linux-kernel@vger.kernel.org")
    (state / "old-thread.mbox").write_bytes(mbox(raw))
    (state / "old-thread.seen").write_text("old1@x\n")
    return hermetic


# Final review C2: a seed shaped like the real ~/.local/state/stable-watch/linux.git.

@pytest.fixture
def swclone(tmp_path, kfix):
    from gitfix import make_stable_watch_clone

    return make_stable_watch_clone(kfix, tmp_path / "stable-watch-linux.git")


def tree_state(root):
    """Every file under root with its mtime and contents, and every ref."""
    import subprocess

    files = {str(p.relative_to(root)): (p.stat().st_mtime_ns, p.read_bytes())
             for p in sorted(root.rglob("*")) if p.is_file()}
    refs = subprocess.run(["git", "-C", str(root), "for-each-ref"], capture_output=True,
                          text=True, check=True).stdout
    return refs, files
