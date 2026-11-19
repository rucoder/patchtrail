# SPDX-License-Identifier: Apache-2.0
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from mails import make_mail

from patchtrail import db, snapshot, store
from patchtrail.cli import main
from patchtrail.fetch import Busy
from patchtrail.projects import TrailResult


def test_read_unread(populated, capsys):
    assert main(["read", "iowq-cpuset"]) == 0
    main(["status"]); assert capsys.readouterr().out.strip() == "nothing unread"
    main(["unread", "iowq-cpuset"]); main(["status"]); assert "iowq-cpuset" in capsys.readouterr().out


def test_read_needs_names_or_all(populated, capsys):
    assert main(["read"]) == 1
    assert "ptl: name a patch or pass --all" in capsys.readouterr().err


def test_rm_is_not_rediscovered(populated, conn):
    root = store.revisions(conn, store.get_patch(conn, "erofs")["id"])[0]["root_msgid"]
    assert main(["rm", "erofs"]) == 0
    assert conn.execute("SELECT 1 FROM ignored WHERE msgid=?", (root,)).fetchone()
    assert store.get_patch(conn, "erofs") is None


def test_rm_keeps_mails_of_another_patchs_thread(conn):
    a = store.add_patch(conn, "a-series", now=1)
    ra = store.add_revision(conn, a, "a@x", subject="[PATCH] a")
    b = store.add_patch(conn, "b-series", now=1)
    store.add_revision(conn, b, "b@x", subject="[PATCH] b")
    # b's reply was stored under a's revision (its thread brought it first)
    store.upsert_mails(conn, ra, [make_mail("a@x", subject="[PATCH] a"),
                                  make_mail("b-r@x", in_reply_to="b@x", subject="Re: [PATCH] b"),
                                  make_mail("a-r@x", in_reply_to="a@x", subject="Re: [PATCH] a")], 1)
    assert "b-r@x" in {m["msgid"] for m in store.patch_mails(conn, b)}
    assert main(["rm", "a-series"]) == 0
    assert [m["msgid"] for m in store.patch_mails(conn, b)] == ["b-r@x"]
    assert [r[0] for r in conn.execute("SELECT msgid FROM mails")] == ["b-r@x"]


def test_close_moved_flags_change(populated, conn, capsys):
    main(["read", "--all"])
    assert main(["close", "erofs", "moved", "--note", "converted to a GitLab MR"]) == 0
    main(["status"]); assert "closed: – → moved (converted to a GitLab MR)" in capsys.readouterr().out


def test_skip_series_forms(populated, conn):
    for s in ["6.1", "6.1.y", "linux-6.1.y"]:
        assert main(["skip", "iowq-cpuset", s]) == 0
    assert [tuple(r) for r in conn.execute("SELECT series FROM branch_skips")] == [("6.1",)]
    assert main(["unskip", "iowq-cpuset", "linux-6.1.y"]) == 0
    assert conn.execute("SELECT series FROM branch_skips").fetchall() == []


def test_skip_bad_series(populated, capsys):
    assert main(["skip", "iowq-cpuset", "latest"]) == 1
    assert "ptl: bad series: latest" in capsys.readouterr().err


def test_mark_applied(populated, conn):
    sha = "0123456789abcdef0123456789abcdef01234567"
    assert main(["mark-applied", "erofs", sha]) == 0
    p = store.get_patch(conn, "erofs")
    assert p["manual_applied"] == 1
    assert [(c["sha"], c["source"]) for c in store.commits(conn, p["id"])] == [(sha, "manual")]


def test_follow_bare_commit(populated, conn):
    assert main(["follow", "someones-fix", "0123456789abcdef0123456789abcdef01234567"]) == 0
    p = store.get_patch(conn, "someones-fix")
    assert (p["relation"], p["project"]) == ("following", "kernel") and store.revisions(conn, p["id"]) == []


def test_follow_new_needs_commit(populated, capsys):
    assert main(["follow", "someones-fix"]) == 1
    assert "ptl: someones-fix is not tracked: give a COMMIT" in capsys.readouterr().err


def test_follow_existing_with_tree_and_stable(populated, conn):
    sha = "0123456789abcdef0123456789abcdef01234567"
    store.set_commit(conn, store.get_patch(conn, "erofs")["id"], sha, "s", "search")
    assert main(["follow", "erofs", "git://t.example/linux.git", "next", "--stable"]) == 0
    p = store.get_patch(conn, "erofs")
    assert (p["tree_url"], p["tree_branch"], p["tree_source"], p["force_stable"]) == (
        "git://t.example/linux.git", "next", "manual", 1)
    assert [(c["sha"], c["source"]) for c in store.commits(conn, p["id"])] == [(sha, "manual")]


def test_hide_unhide_rename(populated, conn):
    assert main(["hide", "erofs"]) == 0 and store.get_patch(conn, "erofs")["hidden"] == 1
    assert main(["unhide", "erofs"]) == 0 and store.get_patch(conn, "erofs")["hidden"] == 0
    assert main(["rename", "erofs", "erofs-utils-fix"]) == 0
    assert store.get_patch(conn, "erofs") is None and store.get_patch(conn, "erofs-utils-fix")


def test_rename_taken_or_invalid(populated, capsys):
    assert main(["rename", "erofs", "iowq-cpuset"]) == 1
    assert "ptl: name taken: iowq-cpuset" in capsys.readouterr().err
    assert main(["rename", "erofs", "bad name"]) == 1
    assert "ptl: invalid name: bad name" in capsys.readouterr().err


def test_merge_and_split(populated, conn):
    a = store.add_patch(conn, "kvm-bar-efault", now=1); store.add_revision(conn, a, "v1@x", version=1, subject="[PATCH] KVM: a")
    b = store.add_patch(conn, "kvm-v2", now=1); store.add_revision(conn, b, "v2@x", version=2, subject="[PATCH v2] KVM: b")
    conn.commit()
    assert main(["merge", "kvm-bar-efault", "kvm-v2"]) == 0
    assert store.get_patch(conn, "kvm-v2") is None
    assert [r["version"] for r in store.revisions(conn, a)] == [1, 2]
    assert main(["split", "kvm-bar-efault", "2"]) == 0
    c = store.get_patch(conn, "kvm-bar-efault-v2")
    assert [r["root_msgid"] for r in store.revisions(conn, c["id"])] == ["v2@x"]


def test_merge_moves_commits_skips_links(populated, conn):
    a, b = (store.get_patch(conn, n)["id"] for n in ("iowq-cpuset", "erofs"))
    store.set_commit(conn, b, "ab" * 20, "s", "manual")
    conn.execute("INSERT INTO branch_skips VALUES (?, '6.1')", (b,))
    store.add_links(conn, b, ["https://x.example/1"], 1)
    assert main(["merge", "iowq-cpuset", "erofs"]) == 0
    assert [c["sha"] for c in store.commits(conn, a)] == ["ab" * 20]
    assert store.skips(conn, a) == {"6.1"} and store.links(conn, a) == ["https://x.example/1"]


def test_split_refuses_unknown_version(populated, capsys):
    assert main(["split", "erofs", "9"]) == 1
    assert "ptl: erofs has no v9" in capsys.readouterr().err


def test_reevaluate_without_network(populated, conn, monkeypatch):
    from patchtrail import fetch

    pid = store.get_patch(conn, "erofs")["id"]
    store.set_field(conn, pid, "closed", "dropped")
    n = len(conn.execute("SELECT 1 FROM snapshots WHERE patch_id=?", (pid,)).fetchall())
    from patchtrail.config import load_config, paths
    assert fetch.reevaluate(conn, paths(), load_config(paths()), pid) is not None
    assert snapshot.latest(conn, pid)[2]["closed"] == "dropped"
    assert len(conn.execute("SELECT 1 FROM snapshots WHERE patch_id=?", (pid,)).fetchall()) == n + 1
    assert fetch.reevaluate(conn, paths(), load_config(paths()), pid) is None   # nothing changed


def test_add_follow(populated, conn, monkeypatch):
    monkeypatch.setattr("patchtrail.cli.run_fetch", lambda *a, **k: 1)
    assert main(["add", "x-thread", "https://lore.kernel.org/all/abc@d/", "--follow"]) == 0
    assert store.get_patch(conn, "x-thread")["relation"] == "following"


def test_add_runs_a_targeted_fetch(populated, monkeypatch):
    seen = {}
    monkeypatch.setattr("patchtrail.cli.run_fetch", lambda *a, **k: seen.update(a=a, k=k) or 1)
    assert main(["add", "x-thread", "abc@d"]) == 0
    assert seen["a"][2] == "cli"
    assert seen["k"]["patch_names"] == ["x-thread"] and seen["k"]["discover_new"] is False
    assert seen["k"]["lore_only"] is True


def test_add_busy_text(populated, conn, monkeypatch, capsys):
    def busy(*a, **k):
        raise Busy(None)
    monkeypatch.setattr("patchtrail.cli.run_fetch", busy)
    assert main(["add", "x-thread", "abc@d"]) == 0
    assert capsys.readouterr().out.strip() == "added x-thread; it is fetched on the next run"
    assert store.get_patch(conn, "x-thread")


def test_add_unarchived_shows_not_fetched_yet(populated, monkeypatch, capsys):
    monkeypatch.setattr("patchtrail.cli.run_fetch", lambda *a, **k: 1)
    assert main(["add", "x-thread", "abc@d"]) == 0
    out = capsys.readouterr().out
    assert "x-thread" in out and "https://lore.kernel.org/all/abc@d/" in out


def test_add_for_agents_json_idempotent_links(populated, conn, monkeypatch, capsys):
    monkeypatch.setattr("patchtrail.cli.run_fetch", lambda *a, **k: 1)
    pr, jira = "https://github.com/lf-edge/eve/pull/5123", "https://zededa.atlassian.net/browse/ZED-42"
    assert main(["add", "iowq-fix", "<new@x>", "--link", pr, "--note", "found by agent", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert (out["name"], out["msgid"], out["links"], out["note"], out["stage"]) == (
        "iowq-fix", "new@x", [pr], "found by agent", None)
    assert list(out) == ["name", "msgid", "project", "stage", "standing", "links", "note", "url"]
    assert out["url"] == "https://lore.kernel.org/all/new@x/"
    # again, under another name and with one more link: same patch, link added, nothing duplicated
    assert main(["add", "other-name", "new@x", "--link", jira, "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["name"] == "iowq-fix" and out["links"] == [pr, jira]
    assert out["note"] == "found by agent"          # no --note: kept
    assert store.get_patch(conn, "other-name") is None


def test_add_json_reports_snapshot_state(populated, monkeypatch, capsys):
    monkeypatch.setattr("patchtrail.cli.run_fetch", lambda *a, **k: 1)
    assert main(["add", "x", "iowq@x", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert (out["name"], out["stage"], out["standing"]) == (
        "iowq-cpuset", "accepted", "APPLIED by Jens Axboe, 2026-11-12")


def test_add_name_taken(populated, monkeypatch, capsys):
    monkeypatch.setattr("patchtrail.cli.run_fetch", lambda *a, **k: 1)
    assert main(["add", "erofs", "brand-new@x"]) == 1
    assert "ptl: name taken: erofs" in capsys.readouterr().err


def test_add_invalid_name(populated, capsys):
    assert main(["add", "bad name", "x@y"]) == 1
    assert "ptl: invalid name: bad name" in capsys.readouterr().err


def test_add_clears_ignored(populated, conn, monkeypatch):
    monkeypatch.setattr("patchtrail.cli.run_fetch", lambda *a, **k: 1)
    conn.execute("INSERT INTO ignored VALUES ('back@x')"); conn.commit()
    assert main(["add", "back", "back@x"]) == 0
    assert not conn.execute("SELECT 1 FROM ignored").fetchone()


def test_link_unlink_note(populated, conn, capsys):
    pid = store.get_patch(conn, "erofs")["id"]
    u1, u2 = "https://github.com/o/r/pull/7", "https://j.example/browse/X-1"
    assert main(["link", "erofs", u1, u2, u1]) == 0
    assert store.links(conn, pid) == [u1, u2]
    assert main(["unlink", "erofs", u1]) == 0 and store.links(conn, pid) == [u2]
    assert main(["note", "erofs", "hello"]) == 0 and store.get_patch(conn, "erofs")["note"] == "hello"
    main(["ls", "erofs"]); out = capsys.readouterr().out
    assert "note: hello" in out and u2 in out
    assert main(["note", "erofs", ""]) == 0 and store.get_patch(conn, "erofs")["note"] is None


def test_links_do_not_flag(populated, conn):
    main(["read", "--all"])
    assert main(["link", "erofs", "https://github.com/o/r/pull/7"]) == 0
    assert main(["note", "erofs", "x"]) == 0
    assert not snapshot.unread(conn, store.get_patch(conn, "erofs")["id"])


def test_migration_to_v2_is_atomic(tmp_path, monkeypatch):
    # a broken 002 must leave user_version at 1 and no partial table behind
    src = Path(db.__file__).parent / "schema"
    mig = tmp_path / "migrations"
    mig.mkdir()
    shutil.copy(src / "001_init.sql", mig / "001_init.sql")
    (mig / "002_x.sql").write_text(
        "ALTER TABLE patches ADD COLUMN note TEXT;\n"
        "CREATE TABLE links (patch_id INTEGER NOT NULL);\n"
        "CREATE TABLE links (again INTEGER);\n")      # fails: table links already exists
    monkeypatch.setattr(db, "MIGRATIONS", mig)
    path = tmp_path / "t.db"
    with pytest.raises(sqlite3.Error):
        db.connect(path)
    raw = sqlite3.connect(path)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 1
    assert raw.execute("SELECT 1 FROM sqlite_master WHERE name='links'").fetchone() is None
    assert "note" not in [r[1] for r in raw.execute("PRAGMA table_info(patches)")]
    raw.close()


def test_schema_v2_has_the_index(conn):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 2
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='mails_in_reply_to'").fetchone()


# --- fetch, poll, watch, check, backport, import ----------------------------------

def test_fetch_prints_progress(populated, monkeypatch, capsys):
    def fake(paths, cfg, trigger, *, echo=None, patch_names=None, **k):
        assert trigger == "cli" and patch_names is None
        echo("phase: threads"); echo("step 1/1: erofs v1")
        return 3
    monkeypatch.setattr("patchtrail.cli.run_fetch", fake)
    assert main(["fetch"]) == 0
    assert capsys.readouterr().out.splitlines() == ["phase: threads", "step 1/1: erofs v1"]


def test_fetch_busy(populated, monkeypatch, capsys):
    def busy(*a, **k):
        raise Busy({"id": 7, "phase": "threads", "step": 2, "steps": 5})
    monkeypatch.setattr("patchtrail.cli.run_fetch", busy)
    assert main(["fetch"]) == 1
    assert "ptl: a fetch is already running (run 7, threads 2/5)" in capsys.readouterr().err


def test_fetch_unknown_name(populated, monkeypatch, capsys):
    monkeypatch.setattr("patchtrail.cli.run_fetch", lambda *a, **k: 1)
    assert main(["fetch", "nope"]) == 1
    assert "ptl: not tracked: nope" in capsys.readouterr().err


def test_poll_prints_new_changes(populated, conn, monkeypatch, capsys):
    pid = store.get_patch(conn, "erofs")["id"]

    def fake(*a, **k):
        st = snapshot.latest(conn, pid)[2]
        snapshot.record(conn, pid, {**st, "stage": "accepted"}, 99)
        conn.commit()
        return 4
    monkeypatch.setattr("patchtrail.cli.run_fetch", fake)
    assert main(["poll"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "erofs" and out[1] == "  stage: submitted → accepted"


def test_poll_nothing_new(populated, monkeypatch, capsys):
    monkeypatch.setattr("patchtrail.cli.run_fetch", lambda *a, **k: 1)
    assert main(["poll"]) == 0
    assert capsys.readouterr().out.strip() == "nothing new"


def test_check_renders_each_commit(populated, monkeypatch, capsys):
    sha = "0123456789abcdef0123456789abcdef01234567"
    calls = []

    class FakeTrail:
        def __init__(self, paths, cfg):
            pass
        def prepare(self, patches, progress):
            calls.append(("prepare", patches))
        def check_commits(self, shas, progress):
            calls.append(("check", shas))
            return [TrailResult(fragment={
                "commits": [{"sha": sha, "subject": "io_uring: fix", "where": "mainline",
                             "stage": "released", "release": "v7.4-rc1", "stable": True,
                             "cc": "", "fixes": []}],
                "branches": {}, "failed": {}, "hint": None})]
    monkeypatch.setattr("patchtrail.cli.KernelTrail", FakeTrail)
    assert main(["check", sha]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"{sha[:12]} io_uring: fix\n") and "mainline" in out
    assert calls == [("prepare", []), ("check", [sha])]


def test_check_busy(populated, monkeypatch, capsys):
    import fcntl, os
    from patchtrail.config import paths
    paths().home.mkdir(parents=True, exist_ok=True)
    fd = os.open(paths().lock, os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        monkeypatch.setattr("patchtrail.cli.KernelTrail", lambda *a: pytest.fail("ran"))
        assert main(["check", "abc1234"]) == 1
        assert "ptl: a fetch is already running" in capsys.readouterr().err
    finally:
        os.close(fd)


def test_backport_by_patch_name_and_commit(populated, conn, monkeypatch, capsys, tmp_path):
    sha = "0123456789abcdef0123456789abcdef01234567"
    store.set_commit(conn, store.get_patch(conn, "iowq-cpuset")["id"], sha, "s", "manual")
    got = []

    def fake(repo, queue, sha_, name, series, dest):
        got.append((sha_, name, series, Path(dest).name))
        return ["worktree made"]
    monkeypatch.setattr("patchtrail.cli.make_backport", fake)
    monkeypatch.chdir(tmp_path)
    assert main(["backport", "iowq-cpuset", "linux-6.1.y"]) == 0
    assert main(["backport", sha, "6.6", "mydir"]) == 0
    assert got == [(sha, "iowq-cpuset", "6.1", "iowq-cpuset-6.1"), (sha, sha[:12], "6.6", "mydir")]
    assert "worktree made" in capsys.readouterr().out


def test_import_prints_report(populated, monkeypatch, capsys):
    from patchtrail.importer import ImportReport
    monkeypatch.setattr("patchtrail.cli.import_old", lambda conn, mine, **k: ImportReport(
        patches=["a", "b"], merged=["a"], fixes=["f"], skipped=["s"]))
    assert main(["import"]) == 0
    out = capsys.readouterr().out
    assert "imported 2 patches" in out and "merged: a" in out and "skipped: s" in out


def test_watch_prints_new_changes_until_interrupted(populated, conn, monkeypatch, capsys):
    pid = store.get_patch(conn, "erofs")["id"]
    calls = []

    def sleep(n):
        calls.append(n)
        if len(calls) == 1:
            snapshot.record(conn, pid, {**snapshot.latest(conn, pid)[2], "stage": "accepted"}, 99)
            conn.commit()
        else:
            raise KeyboardInterrupt
    monkeypatch.setattr("patchtrail.cli.time.sleep", sleep)
    assert main(["watch"]) == 0
    assert calls == [30, 30]
    assert capsys.readouterr().out.splitlines() == ["erofs", "  stage: submitted → accepted"]


def test_add_folded_into_older_patch_by_change_id(populated, conn, monkeypatch, capsys):
    """The targeted fetch merges the new patch into the older one: report that one,
    keep the agent's link and note."""
    old = store.get_patch(conn, "erofs")["id"]
    store.add_links(conn, old, ["https://x.example/old"], 1)
    store.set_field(conn, old, "note", "old note")

    def fetch(paths, cfg, trigger, *, patch_names, **k):
        new = store.get_patch(conn, patch_names[0])
        store.merge_into(conn, old, new["id"])
        conn.commit()
        return 1
    monkeypatch.setattr("patchtrail.cli.run_fetch", fetch)
    zed = "https://zededa.atlassian.net/browse/ZED-42"
    assert main(["add", "erofs-v2", "v2@x", "--link", zed, "--note", "agent note", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert (out["name"], out["msgid"], out["links"], out["note"]) == (
        "erofs", "v2@x", ["https://x.example/old", zed], "old note")   # the survivor keeps its note
    assert store.get_patch(conn, "erofs-v2") is None


def test_merge_keeps_links_and_the_survivors_note(populated, conn):
    a, b = (store.get_patch(conn, n)["id"] for n in ("iowq-cpuset", "erofs"))
    store.add_links(conn, b, ["https://x.example/b"], 1)
    store.set_field(conn, b, "note", "b note")
    assert main(["merge", "iowq-cpuset", "erofs"]) == 0
    assert store.links(conn, a) == ["https://x.example/b"]
    assert store.get_patch(conn, "iowq-cpuset")["note"] == "b note"     # survivor had none
    c = store.add_patch(conn, "c", now=1); d = store.add_patch(conn, "d", now=1)
    store.set_field(conn, c, "note", "c note"); store.set_field(conn, d, "note", "d note")
    assert main(["merge", "c", "d"]) == 0
    assert store.get_patch(conn, "c")["note"] == "c note"


def test_add_is_one_transaction(populated, conn, monkeypatch, capsys):
    monkeypatch.setattr("patchtrail.cli.run_fetch", lambda *a, **k: 1)
    real = store.add_revision

    def boom(*a, **k):
        raise sqlite3.OperationalError("disk full")
    monkeypatch.setattr(store, "add_revision", boom)
    with pytest.raises(sqlite3.OperationalError):
        main(["add", "x-thread", "abc@d", "--link", "https://x.example/1"])
    assert store.get_patch(conn, "x-thread") is None
    monkeypatch.setattr(store, "add_revision", real)
    assert main(["add", "x-thread", "abc@d", "--link", "https://x.example/1"]) == 0
    p = store.get_patch(conn, "x-thread")
    assert [r["root_msgid"] for r in store.revisions(conn, p["id"])] == ["abc@d"]


def test_close_is_one_transaction(populated, conn, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr("patchtrail.cli.reevaluate", boom)
    with pytest.raises(RuntimeError):
        main(["close", "erofs", "dropped", "--note", "n"])
    p = store.get_patch(conn, "erofs")
    assert (p["closed"], p["closed_note"]) == (None, None)


def test_add_fetches_the_thread_but_not_the_trail(populated, conn, monkeypatch, tmp_path,
                                                  capsys):                # final review I3
    from mails import mbox

    from patchtrail.projects.kernel import KernelTrail
    built = []

    class Recorder(KernelTrail):
        def __init__(self, *a, **k):
            built.append(a)
            super().__init__(*a, **k)
    monkeypatch.setattr("patchtrail.projects.kernel.KernelTrail", Recorder)
    threads = tmp_path / "lore"
    threads.mkdir()
    (threads / "new@x.mbox").write_bytes(mbox(
        make_mail("new@x", subject="[PATCH v2] io: fix", to="io-uring@vger.kernel.org"),
        make_mail("r@x", frm="X <x@y.org>", in_reply_to="new@x", subject="Re: [PATCH v2] io: fix",
                  date="Thu, 12 Nov 2026 10:00:00 +0000", body="Reviewed-by: X <x@y.org>\n")))
    b4 = tmp_path / "b4"
    b4.write_text(f'#!/bin/sh\nfor last; do :; done\nexec cat "{threads}/$last.mbox"\n')
    b4.chmod(0o755)
    monkeypatch.setenv("PATCHTRAIL_B4", str(b4))
    assert main(["add", "io-fix", "new@x", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert built == []
    assert (out["project"], out["stage"]) == ("kernel", "reviewed")
    assert out["standing"].startswith("Reviewed-by X; waiting for the maintainer since 2026-11-1")
    p = store.get_patch(conn, "io-fix")
    assert store.revisions(conn, p["id"])[0]["version"] == 2
    assert not snapshot.unread(conn, p["id"])
    log = [r[0] for r in conn.execute(
        "SELECT line FROM run_log WHERE run_id=(SELECT MAX(id) FROM runs) ORDER BY rowid")]
    assert [l for l in log if l.startswith("phase: ")] == ["phase: threads", "phase: evaluate"]


# --- final review M3: arguments that reach git, b4 and pages are checked --------

@pytest.mark.parametrize("msgid", ["-oProxyCommand=x@y", "--help@x", "no-at-sign", "a b@x"])
def test_add_rejects_what_is_no_message_id(populated, conn, monkeypatch, capsys, msgid):
    monkeypatch.setattr("patchtrail.cli.run_fetch", lambda *a, **k: pytest.fail("fetched"))
    assert main(["add", "x-thread", "--", msgid]) == 1
    assert "ptl: not a Message-ID:" in capsys.readouterr().err
    assert store.get_patch(conn, "x-thread") is None


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "ftp://x.org/a",
                                 "https://", "github.com/a/b/pull/1"])
def test_links_must_be_http_urls(populated, conn, monkeypatch, capsys, url):
    monkeypatch.setattr("patchtrail.cli.run_fetch", lambda *a, **k: 1)
    assert main(["add", "x-thread", "x@y", "--link", url]) == 1
    assert main(["link", "erofs", url]) == 1
    assert capsys.readouterr().err.count(f"ptl: not an http(s) URL: {url}") == 2
    assert store.get_patch(conn, "x-thread") is None
    assert store.links(conn, store.get_patch(conn, "erofs")["id"]) == []
    with pytest.raises(ValueError):
        store.add_links(conn, store.get_patch(conn, "erofs")["id"], [url], 1)


@pytest.mark.parametrize("name", [".", ".."])
def test_dot_names_are_invalid(populated, monkeypatch, capsys, name):
    monkeypatch.setattr("patchtrail.cli.run_fetch", lambda *a, **k: 1)
    assert not store.valid_name(name)
    assert main(["add", name, "x@y"]) == 1
    assert main(["rename", "erofs", name]) == 1
    assert main(["follow", name, "0123456789ab"]) == 1
    assert capsys.readouterr().err.count(f"ptl: invalid name: {name}") == 3


@pytest.mark.parametrize("cmd", [["follow", "someones-fix", "{}"], ["follow", "erofs", "{}"],
                                 ["follow", "erofs", "{}", "https://t.org/x.git", "main"],
                                 ["mark-applied", "erofs", "{}"], ["check", "{}"],
                                 ["backport", "{}", "6.1"]])
@pytest.mark.parametrize("commit", ["HEAD", "main", "012345", "0123456789abcdefX",
                                    "a" * 41, "HEAD~1"])
def test_commit_arguments_are_hashes(populated, conn, monkeypatch, capsys, cmd, commit):
    monkeypatch.setattr("patchtrail.cli.KernelTrail", lambda *a: pytest.fail("ran"))
    monkeypatch.setattr("patchtrail.cli.make_backport", lambda *a: pytest.fail("ran"))
    assert main([c.format(commit) for c in cmd]) == 1
    err = capsys.readouterr().err
    assert f"ptl: not a commit hash: {commit}" in err or f"ptl: not tracked: {commit}" in err
    assert store.get_patch(conn, "someones-fix") is None
    assert store.commits(conn, store.get_patch(conn, "erofs")["id"]) == []
    assert not store.get_patch(conn, "erofs")["manual_applied"]


def test_check_verbose_shows_every_prerequisite(populated, monkeypatch, capsys):  # final review M4
    sha = "0123456789abcdef0123456789abcdef01234567"
    prereqs = [{"sha": f"{i:040x}", "subject": f"io: change {i}", "tag": "v6.2", "cc": None,
                "fixes": []} for i in range(10)]

    class FakeTrail:
        def __init__(self, paths, cfg):
            pass

        def prepare(self, patches, progress):
            pass

        def check_commits(self, shas, progress):
            return [TrailResult(fragment={
                "commits": [{"sha": sha, "subject": "io: fix", "where": "mainline",
                             "stage": "released", "release": "v7.4-rc1", "stable": True,
                             "cc": "", "fixes": []}],
                "branches": {"6.1": {sha[:12]: {"state": "conflict", "tag": None, "prereqs": prereqs,
                                                "detail": ["CONFLICT in io.c"]}}},
                "failed": {}, "hint": None})]
    monkeypatch.setattr("patchtrail.cli.KernelTrail", FakeTrail)
    assert main(["check", sha]) == 0
    out = capsys.readouterr().out
    assert "io: change 7" in out and "io: change 8" not in out and "... 2 more (-v)" in out
    assert main(["check", "-v", sha]) == 0
    out = capsys.readouterr().out
    assert "io: change 9" in out and "more (-v)" not in out
