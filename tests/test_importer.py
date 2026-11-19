# SPDX-License-Identifier: Apache-2.0
from types import SimpleNamespace

import pytest
from mails import make_mail, mbox

from patchtrail import snapshot, store
from patchtrail.importer import import_old

ME = "Me <me@example.org>"
CC = "linux-kernel@vger.kernel.org"
DAY = "Wed, 11 Nov 2026 {}:00:00 +0000"


def _m(msgid, hour="10", **kw):
    kw.setdefault("to", CC)
    return make_mail(msgid, date=DAY.format(hour), **kw)


def _tree(root):
    return {str(p): (p.stat().st_mtime_ns, p.read_bytes()) for p in sorted(root.rglob("*"))
            if p.is_file()}


@pytest.fixture
def old(tmp_path):
    root = tmp_path / "old"
    cfg, state = root / "config", root / "state"
    (cfg / "lkml-watch").mkdir(parents=True)
    (cfg / "stable-watch").mkdir(parents=True)
    (state / "lkml-watch").mkdir(parents=True)
    (cfg / "lkml-watch" / "threads").write_text(
        "# lkml-watch: NAME MESSAGE-ID\nkvm-bar-efault-v2 b@x\nkvm-bar-efault-v1 a@x # old\n"
        "iowq-cpuset c@x\n")
    threads = {
        "kvm-bar-efault-v1": [_m("a@x", subject="[PATCH] kvm: fix bar"),
                              _m("a1@x", "11", frm="Rev <rev@k.org>", in_reply_to="a@x",
                                 subject="Re: [PATCH] kvm: fix bar")],
        "kvm-bar-efault-v2": [_m("b@x", "12", subject="[PATCH v2] kvm: fix bar")],
        "iowq-cpuset": [_m("c@x", subject="[PATCH] io_uring: cpuset"),
                        _m("c1@x", "11", frm="Rev <rev@k.org>", in_reply_to="c@x",
                           subject="Re: [PATCH] io_uring: cpuset"),
                        _m("c2@x", "12", frm=ME, in_reply_to="c1@x",
                           subject="Re: [PATCH] io_uring: cpuset"),
                        _m("c3@x", "13", frm=ME, in_reply_to="c2@x",
                           subject="Re: [PATCH] io_uring: cpuset")],
    }
    for name, raws in threads.items():
        (state / "lkml-watch" / f"{name}.mbox").write_bytes(mbox(*raws))
    seen = {"kvm-bar-efault-v1": ["a@x", "a1@x"], "kvm-bar-efault-v2": ["b@x"],
            "iowq-cpuset": ["c@x", "c1@x", "c2@x"]}
    for name, ids in seen.items():
        (state / "lkml-watch" / f"{name}.seen").write_text(
            "".join(f"<{i}>\n" for i in ids))
    (cfg / "stable-watch" / "fixes").write_text(
        "# NAME COMMIT [TREE-URL BRANCH]\n"
        "iowq-cpuset 0659e44ce739ecd856164c75a5325b7959a2921d "
        "https://git.kernel.org/pub/scm/linux/kernel/git/axboe/linux.git io_uring-7.4\n"
        "lonely 1111111111111111111111111111111111111111\n")
    return SimpleNamespace(root=root, config=cfg, state=state)


MINE = frozenset({"me@example.org"})


def test_import(conn, old):
    before = _tree(old.root)
    r = import_old(conn, MINE, now=1000, old_config=old.config, old_state=old.state)
    assert sorted(r.patches) == ["iowq-cpuset", "kvm-bar-efault"]
    assert r.merged == ["kvm-bar-efault"]
    assert r.fixes == ["iowq-cpuset", "lonely"]
    kvm = store.get_patch(conn, "kvm-bar-efault")
    revs = store.revisions(conn, kvm["id"])
    assert [x["version"] for x in revs] == [1, 2]
    assert [x["root_msgid"] for x in revs] == ["a@x", "b@x"]
    assert revs[0]["subject"] == "[PATCH] kvm: fix bar" and revs[0]["author"] == "me@example.org"
    assert kvm["project"] == "kernel" and kvm["relation"] == "mine"
    assert not snapshot.unread(conn, kvm["id"])
    assert snapshot.latest(conn, kvm["id"]) is None and kvm["read_on_first_snapshot"] == 1
    io = store.get_patch(conn, "iowq-cpuset")
    assert snapshot.unread(conn, io["id"])
    assert [c.field for c in snapshot.since_read(conn, io["id"])[1]] == ["mail"]
    assert (io["tree_url"], io["tree_branch"], io["tree_source"]) == (
        "https://git.kernel.org/pub/scm/linux/kernel/git/axboe/linux.git", "io_uring-7.4",
        "manual")
    assert [(c["sha"], c["source"]) for c in store.commits(conn, io["id"])] == [
        ("0659e44ce739ecd856164c75a5325b7959a2921d", "manual")]
    lonely = store.get_patch(conn, "lonely")
    assert lonely["relation"] == "following" and lonely["project"] == "kernel"
    assert store.revisions(conn, lonely["id"]) == []
    assert _tree(old.root) == before


def test_import_twice_is_idempotent(conn, old):
    import_old(conn, MINE, now=1000, old_config=old.config, old_state=old.state)
    r = import_old(conn, MINE, now=2000, old_config=old.config, old_state=old.state)
    assert r.patches == [] and len(r.skipped) == 3
    assert len(store.list_patches(conn)) == 3


def test_following_when_author_is_not_mine(conn, old):
    import_old(conn, frozenset({"other@example.org"}), now=1000,
               old_config=old.config, old_state=old.state)
    assert store.get_patch(conn, "iowq-cpuset")["relation"] == "following"


def test_fixes_name_with_version_suffix_lands_on_merged_patch(conn, old):
    fixes = old.config / "stable-watch" / "fixes"
    fixes.write_text(f"kvm-bar-efault-v2 {'2' * 40} https://t.example/linux.git br-1\n")
    import_old(conn, MINE, now=1000, old_config=old.config, old_state=old.state)
    assert sorted(p["name"] for p in store.list_patches(conn)) == ["iowq-cpuset", "kvm-bar-efault"]
    kvm = store.get_patch(conn, "kvm-bar-efault")
    assert [c["sha"] for c in store.commits(conn, kvm["id"])] == ["2" * 40]
    assert (kvm["tree_url"], kvm["tree_branch"]) == ("https://t.example/linux.git", "br-1")


def test_reimport_keeps_later_edits(conn, old):
    import_old(conn, MINE, now=1000, old_config=old.config, old_state=old.state)
    io = store.get_patch(conn, "iowq-cpuset")
    sha = store.commits(conn, io["id"])[0]["sha"]
    store.set_commit(conn, io["id"], sha, "io_uring: cpuset", "search")
    store.set_field(conn, io["id"], "tree_url", "https://other.example/linux.git")
    store.set_field(conn, io["id"], "tree_branch", "other")
    store.set_field(conn, io["id"], "tree_source", "auto")
    r = import_old(conn, MINE, now=2000, old_config=old.config, old_state=old.state)
    assert r.fixes == []
    io = store.get_patch(conn, "iowq-cpuset")
    c = store.commits(conn, io["id"])
    assert [(x["subject"], x["source"]) for x in c] == [("io_uring: cpuset", "search")]
    assert (io["tree_url"], io["tree_branch"], io["tree_source"]) == (
        "https://other.example/linux.git", "other", "auto")


def test_version_from_the_root_subject_when_the_name_has_none(conn, old):   # final review I1
    (old.config / "lkml-watch" / "threads").write_text("erofs e2@x\n")
    (old.state / "lkml-watch" / "erofs.mbox").write_bytes(mbox(
        _m("e1@x", "08", subject="[PATCH] erofs-utils: lib: fix"),
        _m("e2@x", "12", subject="[PATCH v2] erofs-utils: lib: fix", in_reply_to="e1@x")))
    import_old(conn, MINE, now=1000, old_config=old.config, old_state=old.state)
    [rev] = store.revisions(conn, store.get_patch(conn, "erofs")["id"])
    assert (rev["root_msgid"], rev["version"]) == ("e2@x", 2)
