# SPDX-License-Identifier: Apache-2.0
from patchtrail import store
from patchtrail.mail import Standing
from patchtrail.projects import get_project
from patchtrail.snapshot import (changes, history, latest, mark_read, mark_unread, record,
                                 since_read, stage_of, unread)


def st(**kw):
    base = dict(
        stage="submitted", closed=None, closed_note=None,
        standing={"kind": "waiting_reply", "who": "", "since": 0,
                  "text": "waiting for a reply since 2026-11-11"},
        trailers=[], mails=["a"], commits=[], branches={}, failed={}, hint=None,
        finished=False)
    base.update(kw)
    return base


def test_record_only_on_change(conn):
    pid = store.add_patch(conn, "p", now=1)
    assert record(conn, pid, st(stage="submitted"), now=10) is not None
    assert record(conn, pid, st(stage="submitted"), now=20) is None
    assert record(conn, pid, st(stage="accepted"), now=30) is not None


def test_detail_change_does_not_flag(conn):
    pid = store.add_patch(conn, "p", now=1)
    a = st(branches={"6.6": {"0659e44ce739": {"state": "applies_after_queue", "tag": None, "detail": ["after 2 queued"]}}})
    b = st(branches={"6.6": {"0659e44ce739": {"state": "applies_after_queue", "tag": None, "detail": ["after 3 queued"]}}})
    record(conn, pid, a, now=1); mark_read(conn, pid)
    record(conn, pid, b, now=2)
    assert not unread(conn, pid)
    assert [c.flags for c in history(conn, pid)[0][1]] == [False]


def test_read_unread_cycle(conn):
    pid = store.add_patch(conn, "p", now=1)
    record(conn, pid, st(stage="submitted"), now=1); mark_read(conn, pid)
    record(conn, pid, st(stage="accepted", mails=["a", "b"]), now=2)
    when, ch = since_read(conn, pid)
    assert unread(conn, pid) and when == 1
    assert [(c.field, c.old, c.new, c.flags) for c in ch] == [("stage", "submitted", "accepted", True),
                                                              ("mail", None, ["b"], True)]
    mark_read(conn, pid); assert not unread(conn, pid)
    mark_unread(conn, pid); assert unread(conn, pid)
    assert since_read(conn, pid)[0] == 1          # the old reference is back


def test_mark_unread_without_change_still_flags(conn):
    pid = store.add_patch(conn, "p", now=1)
    record(conn, pid, st(), now=1); mark_read(conn, pid)
    mark_unread(conn, pid)
    assert unread(conn, pid)


def test_stage_of_caps_and_least_advanced():
    k, g = get_project("kernel"), get_project("grub")
    s = Standing("applied", "Jens Axboe", 0, ())
    two = [{"stage": "released", "stable": False}, {"stage": "accepted", "stable": False}]
    assert stage_of(k, s, [], two, False) == "accepted"
    assert stage_of(k, s, [], [{"stage": "released", "stable": True}], False) == "backports"
    assert stage_of(g, s, [], [], True) == "accepted"          # grub stops at accepted


def test_first_snapshot_read_when_requested(conn):
    pid = store.add_patch(conn, "p", now=1)
    store.set_field(conn, pid, "read_on_first_snapshot", 1)
    record(conn, pid, st(), now=1)
    assert not unread(conn, pid)


def test_changes_first_snapshot_is_empty_and_latest():
    assert changes(None, st()) == []


def test_changes_commit_and_standing_and_failed():
    c = {"sha": "a" * 40, "stage": "accepted", "release": None, "where": "next"}
    a = st(commits=[c])
    b = st(commits=[dict(c, stage="released", release="v7.0", where="missing")],
           standing={"kind": "applied", "who": "J", "since": 5, "text": "APPLIED by J"},
           failed={"6.1": {"date": "d", "url": "u"}})
    got = [(x.field, x.old, x.new, x.flags) for x in changes(a, b)]
    assert got == [("standing", "waiting for a reply since 2026-11-11", "APPLIED by J", True),
                   ("commit:" + "a" * 12, "accepted ", "released v7.0 missing", True),
                   ("failed:6.1", None, "d", True)]


def test_standing_text_only_does_not_flag():
    s2 = {"kind": "waiting_reply", "who": "", "since": 0, "text": "waiting for a reply since 2026-11-12"}
    assert [c.flags for c in changes(st(), st(standing=s2))] == [False]


def test_latest(conn):
    pid = store.add_patch(conn, "p", now=1)
    assert latest(conn, pid) is None
    record(conn, pid, st(), now=7)
    i, at, state = latest(conn, pid)
    assert at == 7 and state == st()
