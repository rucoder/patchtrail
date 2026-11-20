# SPDX-License-Identifier: Apache-2.0
import pytest

from patchtrail import actions, snapshot, store
from patchtrail.actions import ActionError
from patchtrail.config import Config, paths

NOW = 1_700_000_000
STATE = {"stage": "submitted", "closed": None, "trailers": [], "mails": ["a"], "commits": [], "branches": {}, "failed": {},
         "standing": {"kind": "waiting_reply", "who": "", "since": 0, "text": "waiting"}}
PR = "https://github.com/lf-edge/eve/pull/1"
JIRA = "https://example.atlassian.net/browse/ZED-1"


def _status(exc_info):
    return exc_info.value.status


def test_register_created_then_existing(conn):
    row, created = actions.register(conn, name="a", msgid="<m1@x>", links=[PR], note="n",
                                    now=NOW)
    assert created and row["name"] == "a" and row["note"] == "n"
    assert store.revision_by_msgid(conn, "m1@x")["patch_id"] == row["id"]
    row2, created2 = actions.register(conn, name="b", msgid="https://lore.kernel.org/all/m1@x/",
                                      links=[JIRA], now=NOW + 1)
    assert not created2 and row2["id"] == row["id"] and row2["name"] == "a"
    assert row2["note"] == "n"
    assert store.links(conn, row["id"]) == [PR, JIRA]
    assert store.get_patch(conn, "b") is None


def test_register_follow_is_not_read_on_first_snapshot(conn):
    mine, _ = actions.register(conn, name="m", msgid="m@x", now=NOW)
    other, _ = actions.register(conn, name="o", msgid="o@x", follow=True, now=NOW)
    assert (mine["relation"], mine["read_on_first_snapshot"]) == ("mine", 1)
    assert (other["relation"], other["read_on_first_snapshot"]) == ("following", 0)


def test_register_name_taken_409(conn):
    actions.register(conn, name="a", msgid="m1@x", now=NOW)
    with pytest.raises(ActionError, match="name taken: a") as e:
        actions.register(conn, name="a", msgid="m2@x", now=NOW)
    assert _status(e) == 409


def test_register_bad_input_400_and_nothing_stored(conn):
    for kw, msg in [({"name": "bad name", "msgid": "m@x"}, "invalid name: bad name"),
                    ({"name": "a", "msgid": "no msgid"}, "not a Message-ID: no msgid"),
                    ({"name": "a", "msgid": "m@x", "links": ["ftp://x"]},
                     r"not an http\(s\) URL: ftp://x")]:
        with pytest.raises(ActionError, match=msg) as e:
            actions.register(conn, now=NOW, **kw)
        assert _status(e) == 400
    assert store.get_patch(conn, "a") is None


def test_register_bad_msgid_400(conn):
    with pytest.raises(ActionError) as e:
        actions.register(conn, name="a", msgid="a b", now=NOW)
    assert _status(e) == 400


def test_patch_unknown_404(conn):
    with pytest.raises(ActionError, match="not tracked: nope") as e:
        actions.patch(conn, "nope")
    assert _status(e) == 404


def test_close_bad_reason_400(conn):
    row, _ = actions.register(conn, name="a", msgid="m@x", now=NOW)
    with pytest.raises(ActionError) as e:
        actions.close(conn, paths(), Config(), row, "bogus", None)
    assert _status(e) == 400
    assert store.get_patch(conn, "a")["closed"] is None


def test_close_sets_reason_and_reevaluates(conn, monkeypatch):
    seen = []
    monkeypatch.setattr(actions, "reevaluate", lambda c, p, cfg, pid: seen.append(pid))
    row, _ = actions.register(conn, name="a", msgid="m@x", now=NOW)
    actions.close(conn, paths(), Config(), row, "moved", "to gitlab")
    cur = store.get_patch(conn, "a")
    assert (cur["closed"], cur["closed_note"]) == ("moved", "to gitlab")
    assert seen == [row["id"]]


def test_skip_reevaluates(conn, monkeypatch):
    seen = []
    monkeypatch.setattr(actions, "reevaluate", lambda c, p, cfg, pid: seen.append(pid))
    row, _ = actions.register(conn, name="a", msgid="m@x", now=NOW)
    actions.skip(conn, paths(), Config(), row, "linux-6.1.y")
    actions.skip(conn, paths(), Config(), row, "6.1")
    assert [tuple(r) for r in conn.execute("SELECT series FROM branch_skips")] == [("6.1",)]
    actions.unskip(conn, paths(), Config(), row, "6.1.y")
    assert conn.execute("SELECT 1 FROM branch_skips").fetchall() == []
    assert seen == [row["id"]] * 3
    with pytest.raises(ActionError, match="bad series: x") as e:
        actions.skip(conn, paths(), Config(), row, "x")
    assert _status(e) == 400 and len(seen) == 3


def test_hide_unhide_and_mark_applied(conn, monkeypatch):
    seen = []
    monkeypatch.setattr(actions, "reevaluate", lambda c, p, cfg, pid: seen.append(pid))
    row, _ = actions.register(conn, name="a", msgid="m@x", now=NOW)
    actions.hide(conn, paths(), Config(), row)
    assert store.get_patch(conn, "a")["hidden"] == 1
    actions.unhide(conn, row)
    assert store.get_patch(conn, "a")["hidden"] == 0
    actions.mark_applied(conn, paths(), Config(), row, "ABCDEF1234")
    assert store.get_patch(conn, "a")["manual_applied"] == 1
    assert store.commits(conn, row["id"])[0]["sha"] == "abcdef1234"
    assert seen == [row["id"]] * 2          # unhide does not reevaluate
    with pytest.raises(ActionError, match="not a commit hash: main") as e:
        actions.mark_applied(conn, paths(), Config(), row, "main")
    assert _status(e) == 400


def test_parse_commit_lowers_and_rejects_refs():
    assert actions.parse_commit("ABCDEF1") == "abcdef1"
    for bad in ("abc", "--help", "HEAD", "g" * 8):
        with pytest.raises(ActionError):
            actions.parse_commit(bad)


def test_mark_read_unread_roundtrip(conn):
    row, _ = actions.register(conn, name="a", msgid="m@x", follow=True, now=NOW)
    snapshot.record(conn, row["id"], STATE, NOW)
    conn.commit()
    assert snapshot.unread(conn, row["id"])
    actions.mark_read(conn, row)
    assert not snapshot.unread(conn, row["id"])
    actions.mark_unread(conn, row)
    assert snapshot.unread(conn, row["id"])


def test_links_and_note(conn):
    row, _ = actions.register(conn, name="a", msgid="m@x", now=NOW)
    actions.add_links(conn, row, [PR, JIRA], NOW)
    actions.remove_links(conn, row, [PR])
    assert store.links(conn, row["id"]) == [JIRA]
    with pytest.raises(ActionError) as e:
        actions.add_links(conn, row, ["javascript:1"], NOW)
    assert _status(e) == 400
    actions.set_note(conn, row, "hello")
    assert store.get_patch(conn, "a")["note"] == "hello"
    actions.set_note(conn, row, "")
    assert store.get_patch(conn, "a")["note"] is None


def test_add_json_shape(conn):
    row, _ = actions.register(conn, name="a", msgid="m@x", links=[PR], note="n", now=NOW)
    assert actions.add_json(conn, row, "m@x") == {
        "name": "a", "msgid": "m@x", "project": row["project"], "stage": None,
        "standing": None, "links": [PR], "note": "n",
        "url": "https://lore.kernel.org/all/m@x/"}
