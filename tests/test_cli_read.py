# SPDX-License-Identifier: Apache-2.0
import os
import sys

import pytest
from conftest import epoch
from mails import make_mail

from patchtrail import render, store
from patchtrail.cli import main
from patchtrail.fetch import Busy
from patchtrail.snapshot import Change


def boom(*a, **kw):
    raise AssertionError("network")


def run_row(**kw):
    return {"id": 7, **kw}


def raise_busy(row):
    def run(*a, **kw):
        raise Busy(row)

    return run


def test_status_shows_only_unread(populated, capsys):
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "iowq-cpuset" in out and "erofs" not in out
    assert "      stage: submitted → accepted" in out
    assert "      mail: +1 · Jens Axboe: Re: [PATCH] io_uring/io-wq: apply the current cpuset to new workers" in out
    assert "    since you read it on " in out
    assert main(["status"]) == 0 and "iowq-cpuset" in capsys.readouterr().out   # status never marks read


def test_no_subcommand_is_status(populated, capsys):
    assert main([]) == 0
    assert "iowq-cpuset" in capsys.readouterr().out


def test_nothing_unread(conn, capsys):
    assert main(["status"]) == 0 and capsys.readouterr().out.strip() == "nothing unread"


def test_ls_offline_lists_all(populated, capsys, monkeypatch):
    monkeypatch.setattr("patchtrail.sources.lore.fetch_thread", boom)
    assert main(["ls"]) == 0
    out = capsys.readouterr().out
    assert "https://lore.kernel.org/all/" in out and "erofs" in out
    assert out.index("iowq-cpuset") < out.index("erofs")          # by last activity
    assert "1 new" in out                                          # iowq: one mail since read


def test_ls_kernel_lines(populated_kernel, capsys):
    main(["ls", "iowq-cpuset"])
    out = capsys.readouterr().out
    assert "    6.1.y   CONFLICT in io_uring/io-wq.c" in out and "    5.15.y  not affected: no 84eacf177faa" in out
    assert "    7.3.y   has it: v7.3.2" in out
    assert "    6.12.y  has it, not released yet" in out
    assert "Fixes: 84eacf177faa (v5.18)   Cc: stable" in out
    assert "    mainline: v7.4-rc1" in out
    assert "io_uring: earlier change (v6.2, not marked for stable)" in out


def test_ls_without_snapshot(conn, capsys):
    pid = store.add_patch(conn, "fresh", project="kernel", now=epoch("2026-11-12"))
    rev = store.add_revision(conn, pid, "fresh@x", subject="[PATCH] fresh")
    store.upsert_mails(conn, rev, [make_mail("fresh@x", subject="[PATCH] fresh")], 1)
    assert main(["ls"]) == 0
    out = capsys.readouterr().out
    assert "fresh  [PATCH] fresh" in out and "1 message)" in out
    assert main(["show", "fresh"]) == 0
    assert main(["status"]) == 0 and "nothing unread" in capsys.readouterr().out.splitlines()[-1]


def test_show_marks_new_mails(populated, capsys):
    assert main(["show", "iowq-cpuset"]) == 0
    out = capsys.readouterr().out
    lines = [l for l in out.splitlines() if " Jens Axboe: Re:" in l]
    assert lines and lines[0].startswith("  * ") and lines[0].endswith("[APPLIED]")
    assert any(l.startswith("    ") and "you: [PATCH]" in l for l in out.splitlines())


def test_trailers_and_history(populated, capsys):
    assert main(["trailers", "iowq-cpuset"]) == 0
    assert "no review tags yet" in capsys.readouterr().out
    assert main(["history", "iowq-cpuset"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0][:2] == "20" and "  stage: submitted → accepted" in out


def test_unknown_name(conn, capsys):
    assert main(["show", "nope"]) == 1 and "ptl: not tracked: nope" in capsys.readouterr().err


def test_status_fetch_busy(populated, capsys, monkeypatch):
    monkeypatch.setattr("patchtrail.cli.run_fetch", raise_busy(run_row(phase="threads", step=3, steps=12)))
    assert main(["status", "--fetch"]) == 1
    assert "ptl: a fetch is already running (run 7, threads 3/12)" in capsys.readouterr().err


def test_status_fetch_passes_names(populated, monkeypatch):
    seen = {}
    monkeypatch.setattr("patchtrail.cli.run_fetch",
                        lambda p, cfg, trigger, **kw: seen.update(trigger=trigger, **kw))
    assert main(["status", "--fetch", "erofs"]) == 0
    assert seen == {"trigger": "cli", "patch_names": ["erofs"]}


def test_mine(populated, capsys, monkeypatch):
    from patchtrail.sources.lore import Entry

    es = [Entry("iowq@x", "[PATCH] a", "me@example.org", "2026-11-11T10:00:00Z", False, ""),
          Entry("new@x", "[PATCH] b", "me@example.org", "2026-11-12T10:00:00Z", False, ""),
          Entry("r@x", "Re: [PATCH] a", "x@y", "2026-11-12T10:00:00Z", True, "")]
    monkeypatch.setattr("patchtrail.sources.lore.search", lambda inbox, q, **kw: es)
    assert main(["mine", "me@example.org"]) == 0
    out = capsys.readouterr().out
    assert "  2026-11-11  iowq-cpuset" in out and "(not tracked)" in out and "Re:" not in out


def test_open_writes_mbox_and_execs(populated, capsys, monkeypatch):
    from patchtrail.config import paths
    from patchtrail.mail import split_mbox

    calls = []
    monkeypatch.setattr(os, "execvp", lambda f, argv: calls.append((f, argv)))
    assert main(["open", "iowq-cpuset"]) == 0
    (f, argv), = calls
    assert f == "neomutt" and argv[:2] == ["neomutt", "-n"]
    assert argv[2] == "-F" and os.path.exists(argv[3]) and argv[3].endswith("neomuttrc")
    assert argv[4:6] == ["-R", "-f"]
    assert argv[6].startswith(str(paths().home / "tmp"))
    raws = split_mbox(open(argv[6], "rb").read())
    assert [r.split(b"\n")[0] for r in raws] == [b"Message-ID: <iowq@x>", b"Message-ID: <iowq-r1@x>"]


def test_open_default_is_newest_patch(populated, monkeypatch):
    calls = []
    monkeypatch.setattr(os, "execvp", lambda f, argv: calls.append(argv))
    main(["open"])
    assert "erofs" in calls[0][-1]   # created after iowq-cpuset? same second: higher id


def test_link_label():
    assert render.link_label("https://github.com/o/r/pull/12") == "PR #12"
    assert render.link_label("https://gitlab.com/g/p/-/merge_requests/5") == "MR !5"
    assert render.link_label("https://jira.example.com/browse/ABC-123") == "ABC-123"
    assert render.link_label("https://example.org/x/y") == "example.org"


def test_change_line_formats(populated_kernel):
    conn = populated_kernel
    cl = lambda f, o, n, **kw: render.change_line(conn, Change(f, o, n, True), **kw)
    assert cl("trailers", None, ["Reviewed-by Tomita Moeko"]) == "trailers: +Reviewed-by Tomita Moeko"
    assert cl("commit:0659e44ce739", "accepted ", "released v7.4-rc1") == \
        "commit 0659e44ce739: accepted → released v7.4-rc1"
    assert cl("commit:0659e44ce739", "accepted ", "accepted  missing") == \
        "commit 0659e44ce739: dropped from its tree?"
    assert cl("branch:6.1:0659e44ce739", "applies", "conflict") == "6.1.y: applies → conflict"
    assert cl("branch:6.1:0659e44ce739", "applies", "conflict", multi=True) == \
        "6.1.y: applies → conflict (0659e44ce739)"
    state = {"failed": {"6.1": {"date": "2026-11-13", "url": "https://lore.kernel.org/x"}},
             "closed_note": "converted to a GitLab MR"}
    assert cl("failed:6.1", None, "2026-11-13", state=state) == \
        "FAILED mail for 6.1.y: https://lore.kernel.org/x"
    assert cl("closed", None, "moved", state=state) == "closed: – → moved (converted to a GitLab MR)"
    assert cl("standing", "a", "b") == "standing: a → b"


def test_prereqs_limited_unless_verbose():
    p = [{"sha": f"{i:040x}", "subject": f"s{i}", "tag": None, "cc": None, "fixes": []}
         for i in range(10)]
    state = {"commits": [{"sha": "c" * 40, "subject": "x", "where": "mainline", "release": None,
                          "stable": False, "cc": None, "fixes": [], "stage": "applied"}],
             "branches": {"6.1": {"c" * 12: {"state": "conflict", "tag": None, "detail": ["CONFLICT"],
                                             "prereqs": p}}},
             "failed": {}, "hint": None}
    short = render.kernel_lines(state)
    assert sum("s" in l and "not in a release" in l for l in short) == 8
    assert any("... 2 more (-v)" in l for l in short)
    assert not any("more (-v)" in l for l in render.kernel_lines(state, verbose=True))


def test_summary_optional_links_and_note(populated, capsys):
    pid = store.get_patch(populated, "erofs")["id"]
    store.add_links(populated, pid, ["https://github.com/o/r/pull/3"], 1)
    store.set_field(populated, pid, "note", "ping in a week")
    assert main(["ls", "erofs"]) == 0
    out = capsys.readouterr().out
    assert "  links: PR #3 https://github.com/o/r/pull/3" in out and "  note: ping in a week" in out


def test_status_includes_closed_not_hidden(populated, capsys):
    from patchtrail import snapshot

    for name, col, val in (("erofs", "closed", "moved"), ("iowq-cpuset", "hidden", 1)):
        store.set_field(populated, store.get_patch(populated, name)["id"], col, val)
    eid = store.get_patch(populated, "erofs")["id"]
    st = snapshot.latest(populated, eid)[2]
    snapshot.record(populated, eid, {**st, "closed": "moved"}, epoch("2026-11-14"))
    populated.commit()
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "erofs" in out and "closed: – → moved" in out and "iowq-cpuset" not in out


def test_status_fetch_validates_names_first(populated, capsys, monkeypatch):
    monkeypatch.setattr("patchtrail.cli.run_fetch", boom)
    assert main(["status", "--fetch", "nope"]) == 1
    assert "ptl: not tracked: nope" in capsys.readouterr().err


def test_summary_links_the_newest_series_revision(conn):           # final review C3
    pid = store.add_patch(conn, "p", project="kernel", now=1)
    store.add_revision(conn, pid, "v1@x", subject="[PATCH] fix io", author="me@example.org")
    store.add_revision(conn, pid, "v2@x", version=2, subject="[PATCH v2] fix io",
                       author="me@example.org")
    store.add_revision(conn, pid, "bp@x", version=3, subject="[PATCH v3 6.1.y] fix io",
                       kind="backport", branch="6.1")
    lines = render.summary_lines(conn, store.patch_by_id(conn, pid))
    assert lines[0].endswith("[PATCH v2] fix io")
    assert lines[2].strip() == "https://lore.kernel.org/all/v2@x/"
