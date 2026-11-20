# SPDX-License-Identifier: Apache-2.0
import pytest
from conftest import _add_patch, _state, epoch
from mails import make_mail

from patchtrail import snapshot, store, views

NOW = epoch("2026-11-20")
CARD_KEYS = {"name", "project", "relation", "subject", "stage", "stages", "closed", "closed_note",
             "hidden", "standing", "your_turn", "unread", "unread_changes", "links", "note",
             "pills", "finished", "finished_at", "idle", "last_activity", "version", "fetched"}


def _card(conn, name, **kw):
    return views.card(conn, store.get_patch(conn, name), frozenset(), now=NOW, idle_days=180, **kw)


def _new(conn, name, *, date="Wed, 11 Nov 2026 10:00:00 +0000", project="kernel", extra=()):
    raw = make_mail(name + "@x", subject="[PATCH] " + name, date=date)
    pid = _add_patch(conn, name, project, name + "@x", [raw, *extra], subject="[PATCH] " + name,
                     now=NOW)
    return pid


def _branch(state, tag=None):
    return {"state": state, "tag": tag, "detail": [], "prereqs": []}


def test_card_shape(populated):
    c = _card(populated, "iowq-cpuset")
    assert set(c) == CARD_KEYS
    assert c["stages"][0] == "submitted" and c["fetched"] and c["links"] == []
    assert c["last_activity"] == epoch("2026-11-12") + 10 * 3600
    assert len(views.cards(populated, frozenset(), now=NOW, idle_days=180)) == 2


def test_card_without_snapshot(conn):
    _new(conn, "bare")
    c = _card(conn, "bare")
    assert not c["fetched"] and c["standing"]["kind"] == "none" and c["stage"] == "submitted"
    assert c["standing"]["text"] == "not fetched yet" and c["pills"] == []


def test_card_never_parses_mail(populated, monkeypatch):
    from patchtrail import mail

    def boom(*a, **k):
        raise AssertionError("parse_mail called")

    monkeypatch.setattr(mail, "parse_mail", boom)
    assert len(views.cards(populated, frozenset(), now=NOW, idle_days=180)) == 2


def test_pills_worst_tone_per_series(conn):
    pid = _new(conn, "p")
    snapshot.record(conn, pid, _state("accepted", ["p@x"], "t", branches={
        "6.1": {"aaa": _branch("applies"), "bbb": _branch("conflict")},
        "6.12": {"aaa": _branch("released", "v6.12.3")},
        "6.6": {"aaa": _branch("queued")}}, failed={"6.6": {"date": "d", "url": "u"}}), 5)
    assert _card(conn, "p")["pills"] == [
        {"series": "6.12", "state": "released", "tone": "ok"},
        {"series": "6.6", "state": "failed", "tone": "bad"},
        {"series": "6.1", "state": "conflict", "tone": "bad"}]


def test_unread_changes_counts_flagging_only(conn):
    pid = _new(conn, "p")
    a = snapshot.record(conn, pid, _state("submitted", ["p@x"], "waiting"), 5)
    store.set_field(conn, pid, "read_snapshot_id", a)
    st = _state("accepted", ["p@x"], "waiting more")
    st["standing"]["text"] = "other text"           # text-only change: does not flag
    snapshot.record(conn, pid, st, 6)
    assert _card(conn, "p")["unread_changes"] == 1


def test_finished_at_is_start_of_streak(conn):
    pid = _new(conn, "p")
    for t, fin, stage in ((1, True, "released"), (2, False, "accepted"), (3, True, "applied"),
                          (4, True, "released")):
        st = _state(stage, ["p@x"], "t")
        st["finished"] = fin
        snapshot.record(conn, pid, st, t)
    c = _card(conn, "p")
    assert c["finished"] and c["finished_at"] == 3


def test_idle_flag(conn):
    _new(conn, "old", date="Mon, 01 Jan 2024 10:00:00 +0000")
    assert _card(conn, "old")["idle"]
    store.set_commit(conn, store.get_patch(conn, "old")["id"], "a" * 40, "s", "search")
    assert not _card(conn, "old")["idle"]
    _new(conn, "closed", date="Mon, 01 Jan 2024 10:00:00 +0000")
    store.set_field(conn, store.get_patch(conn, "closed")["id"], "closed", "dropped")
    assert not _card(conn, "closed")["idle"]
    _new(conn, "fresh", date="Wed, 11 Nov 2026 10:00:00 +0000")
    assert not _card(conn, "fresh")["idle"]
    _new(conn, "bumped", date="Mon, 01 Jan 2024 10:00:00 +0000", extra=[make_mail(
        "bump@x", in_reply_to="bumped@x", date="Wed, 11 Nov 2026 10:00:00 +0000")])
    assert not _card(conn, "bumped")["idle"]


def test_idle_not_for_patch_without_mail(conn):
    pid = store.add_patch(conn, "nomail", now=1)
    assert pid and not _card(conn, "nomail")["idle"]


def test_steps_done_skipped_todo(conn):
    pid = _new(conn, "p")
    st = _state("accepted", ["p@x"], "t")
    snapshot.record(conn, pid, _state("submitted", ["p@x"], "t"), 5)
    snapshot.record(conn, pid, st, 9)
    store.set_field(conn, pid, "tree_branch", "for-next")
    steps = views.detail(conn, store.get_patch(conn, "p"), frozenset(), now=NOW)["steps"]
    assert [(s["stage"], s["state"]) for s in steps] == [
        ("submitted", "done"), ("reviewed", "skipped"), ("accepted", "done"),
        ("applied", "todo"), ("released", "todo"), ("backports", "todo")]
    assert steps[0]["at"] == NOW and steps[2]["at"] == 9 and steps[1]["at"] is None
    assert steps[2]["note"] == "for-next" and steps[3]["note"] == "mainline: not yet"


def test_detail_kernel(populated_kernel):
    row = store.get_patch(populated_kernel, "iowq-cpuset")
    d = views.detail(populated_kernel, row, frozenset(), now=NOW)
    assert set(d) >= CARD_KEYS | {"lore_url", "revisions", "steps", "since", "commits",
                                  "branches", "failed", "hint", "history", "thread"}
    assert [b["series"] for b in d["branches"]][:2] == ["7.3", "6.12"]
    row61 = next(b for b in d["branches"] if b["series"] == "6.1")["rows"][0]
    assert set(row61) == {"sha", "state", "tag", "tone", "detail", "prereqs"}
    assert row61["tone"] == "bad" and set(row61["prereqs"][0]) == {
        "sha", "subject", "tag", "stable", "text"}
    assert d["steps"][5]["note"] == "3 of 6 branches settled"
    assert d["lore_url"].endswith("/iowq@x/") and d["history"][0]["changes"]
    assert all(set(c) == {"field", "text", "flags"} for h in d["history"] for c in h["changes"])


def test_branch_was_not_exposed(conn):
    pid = _new(conn, "p")
    e = _branch("skipped")
    e["was"] = _branch("conflict")
    snapshot.record(conn, pid, _state("accepted", ["p@x"], "t", branches={"6.1": {"aaa": e}}), 5)
    d = views.detail(conn, store.get_patch(conn, "p"), frozenset(), now=NOW)
    assert "was" not in d["branches"][0]["rows"][0]


@pytest.fixture
def threaded(conn):
    root = make_mail("r@x", subject="[PATCH] t", date="Wed, 11 Nov 2026 10:00:00 +0000")
    c1 = make_mail("c1@x", in_reply_to="r@x", frm="Bob <bob@k.org>", subject="Re: [PATCH] t",
                   date="Wed, 11 Nov 2026 12:00:00 +0000",
                   body="Bob wrote:\n> old\n\nLooks fine.\n<script>alert(1)</script>\n")
    c0 = make_mail("c0@x", in_reply_to="r@x", frm="Al <al@k.org>", subject="Re: [PATCH] t",
                   date="Wed, 11 Nov 2026 11:00:00 +0000", body="hi\n")
    g = make_mail("g@x", in_reply_to="c0@x", subject="Re: [PATCH] t",
                  date="Wed, 11 Nov 2026 13:00:00 +0000", body="thanks\n")
    pid = _add_patch(conn, "t", "kernel", "r@x", [root, c1, c0, g], subject="[PATCH] t", now=NOW)
    bp = store.add_revision(conn, pid, "bp@x", subject="[PATCH 6.1] t", kind="backport",
                            branch="6.1", posted_at=NOW)
    store.upsert_mails(conn, bp, [make_mail("bp@x", subject="[PATCH 6.1] t",
                                            date="Thu, 12 Nov 2026 10:00:00 +0000")], NOW)
    return conn, store.get_patch(conn, "t"), pid


def test_mails_nested_and_grouped(threaded):
    conn, row, _ = threaded
    groups = views.mails(conn, row, frozenset({"me@example.org"}))["groups"]
    assert [g["label"] for g in groups] == [None, "6.1.y backport"]
    assert [(m["msgid"], m["depth"], m["parent"]) for m in groups[0]["mails"]] == [
        ("r@x", 0, None), ("c0@x", 1, "r@x"), ("g@x", 2, "c0@x"), ("c1@x", 1, "r@x")]
    assert groups[0]["mails"][0]["you"] and not groups[0]["mails"][1]["you"]
    assert groups[1]["mails"][0]["msgid"] == "bp@x"
    assert set(groups[0]["mails"][0]) == {"msgid", "parent", "depth", "date", "from_name",
                                          "from_addr", "you", "subject", "new", "body",
                                          "omitted", "lore_url"}


def test_mails_parent_outside_group_is_top_level(threaded):
    conn, row, _ = threaded
    conn.execute("UPDATE mails SET in_reply_to='gone@x' WHERE msgid='bp@x'")
    g = views.mails(conn, row, frozenset())["groups"][1]
    assert g["mails"][0]["depth"] == 0 and g["mails"][0]["parent"] is None


def test_mails_body_is_raw_text(threaded):
    conn, row, _ = threaded
    bob = next(m for m in views.mails(conn, row, frozenset())["groups"][0]["mails"]
               if m["msgid"] == "c1@x")
    assert "<script>alert(1)</script>\n" in bob["body"] and bob["omitted"] == 0


def test_mails_new_flag(threaded):
    conn, row, pid = threaded
    ids = ["r@x", "c0@x"]
    a = snapshot.record(conn, pid, _state("submitted", ids, "t"), 5)
    store.set_field(conn, pid, "read_snapshot_id", a)
    snapshot.record(conn, pid, _state("submitted", ids + ["c1@x"], "t2"), 6)
    ms = views.mails(conn, row, frozenset())["groups"][0]["mails"]
    assert {m["msgid"] for m in ms if m["new"]} == {"c1@x"}
    th = views.detail(conn, row, frozenset(), now=NOW)["thread"]
    assert [t["msgid"] for t in th][:4] == ["r@x", "c0@x", "g@x", "c1@x"]
    assert th[3]["snippet"] == "Looks fine." and th[3]["new"] and set(th[0]) == {
        "msgid", "depth", "date", "who", "you", "snippet", "new"}


def test_snippet():
    assert views.snippet("\n> q\nBob wrote:\n\n  Real line  \nmore") == "Real line"
    assert views.snippet("x" * 200) == "x" * 120 and views.snippet("> a\n") == ""


def _run(conn, trigger, started, status, finished=None, error=None, full=1):
    cur = conn.execute("INSERT INTO runs (pid, trigger, started_at, finished_at, status, error,"
                       " full) VALUES (1,?,?,?,?,?,?)",
                       (trigger, started, finished, status, error, full))
    conn.commit()
    return cur.lastrowid


def _status(conn, **kw):
    return views.status(conn, interval_hours=3, now=NOW, starting=False, version="1", **kw)


def test_status_next_fetch_and_error(conn):
    s = _status(conn)
    assert s["next_fetch_at"] == NOW and s["running"] is None and s["last_run"] is None
    assert s["error"] is None
    ok = _run(conn, "cli", 1000, "ok", 1100)
    assert _status(conn)["next_fetch_at"] == 1000 + 3 * 3600
    bad = _run(conn, "page", 2000, "failed", 2050, "boom")
    s = _status(conn)
    assert s["error"] == {"run_id": bad, "at": 2050, "error": "boom", "status": "failed"}
    assert s["next_fetch_at"] == 2000 + 3 * 3600 and s["last_run"]["id"] == ok
    _run(conn, "schedule", 3000, "ok", 3100)
    assert _status(conn)["error"] is None
    live = _run(conn, "api", 4000, "running")
    s = _status(conn)
    assert s["running"]["id"] == live and s["last_run"]["status"] == "ok"
    assert set(s["running"]) == {"id", "trigger", "started_at", "finished_at", "status", "phase",
                                 "step", "steps", "error"}
    assert views.next_fetch_at(conn, 60, NOW) == 4060


def test_partial_runs_neither_postpone_nor_count_as_fetched(conn):   # final review I1
    sched = _run(conn, "schedule", 1000, "ok", 1100)
    _run(conn, "api", 2000, "ok", 2010, full=0)                 # POST /api/patches, `ptl add`
    _run(conn, "cli", 3000, "failed", 3010, "boom", full=0)     # `ptl fetch NAME`
    _run(conn, "cli", 3500, "running", full=0)
    s = _status(conn)
    assert s["next_fetch_at"] == 1000 + 3 * 3600
    assert s["last_run"]["id"] == sched and s["error"] is None
    assert s["running"]["started_at"] == 3500                    # its progress still shows


def test_status_error_includes_an_interrupted_run_with_a_reason(conn):  # final review I2
    ok = _run(conn, "schedule", 1000, "ok", 1100)
    killed = _run(conn, "schedule", 2000, "interrupted", 2050, "killed after 4 hours")
    s = _status(conn)
    assert s["error"] == {"run_id": killed, "at": 2050, "error": "killed after 4 hours",
                          "status": "interrupted"}
    assert s["last_run"]["id"] == ok                             # "fetched": the last good one
    _run(conn, "cli", 3000, "interrupted", 3010)                 # ^C: no reason, no error
    assert _status(conn)["error"]["run_id"] == killed
    gone = _run(conn, "schedule", 4000, "interrupted", 4010, "fetch process exited with status 1")
    assert _status(conn)["error"]["run_id"] == gone
    _run(conn, "schedule", 5000, "ok", 5100)
    assert _status(conn)["error"] is None


def test_run_log(conn):
    rid = _run(conn, "cli", 1, "ok", 2)
    for i in range(3):
        conn.execute("INSERT INTO run_log (run_id, at, line) VALUES (?,?,?)", (rid, i, f"l{i}"))
    conn.commit()
    lines = views.run_log(conn, rid, 0)["lines"]
    assert [x["line"] for x in lines] == ["l0", "l1", "l2"]
    assert views.run_log(conn, rid, lines[0]["n"])["lines"] == lines[1:]
    assert views.run_log(conn, 999, 0) is None


@pytest.mark.parametrize("where, stage, release, project, note", [
    ("tree:git://git.kernel.org/x/linux.git io_uring-7.4", "accepted", None, "kernel",
     "mainline: only in io_uring-7.4"),
    ("next", "accepted", None, "kernel", "mainline: only in linux-next"),
    ("mainline", "released", "v6.19-rc1", "kernel", "mainline: v6.19-rc1"),
    ("mainline", "applied", None, "kernel", "mainline: yes, after the last tag"),
    ("upstream", "released", "v1.2", "erofs-utils", "applied upstream"),
    ("missing", "accepted", None, "kernel", "mainline: not yet"),
    (None, None, None, "kernel", "mainline: not yet"),
])
def test_applied_step_note(conn, where, stage, release, project, note):
    pid = _new(conn, "p", project=project)
    commits = [{"sha": "a" * 40, "subject": "s", "where": where, "stage": stage,
                "release": release, "stable": False, "cc": None, "fixes": []}] if where else []
    snapshot.record(conn, pid, _state("accepted", ["p@x"], "t", commits=commits), 5)
    steps = views.detail(conn, store.get_patch(conn, "p"), frozenset(), now=NOW)["steps"]
    assert next(s for s in steps if s["stage"] == "applied")["note"] == note
