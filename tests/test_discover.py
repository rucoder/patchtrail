# SPDX-License-Identifier: Apache-2.0
import pytest

from patchtrail import store
from patchtrail.discover import backport_of, discover, merge_by_change_id, norm, slug, version_of
from patchtrail.sources.base import Source
from patchtrail.sources.lore import Entry

nosearch = lambda *a, **k: []  # noqa: E731
ME = ["me@example.org"]


def E(msgid, subject, reply=False, author="me@example.org", summary="", updated="2026-11-11T16:27:05Z"):
    return Entry(msgid, subject, author, updated, reply, f"https://lore.kernel.org/all/{msgid}/", summary)


class FakeSource(Source):
    def __init__(self, entries):
        self.entries = entries

    def fetch(self, root_msgid):
        raise NotImplementedError

    def discover(self, addresses, since):
        return [e for e in self.entries if not e.is_reply]


def test_new_series_named_and_read_on_first_run(conn):
    src = FakeSource([E("a@x", "[PATCH] io_uring/io-wq: apply the current cpuset to new workers")])
    r = discover(conn, src, ME, now=100, search=nosearch)
    assert r.new_patches == ["io-uring-io-wq-apply-the-current"]
    p = store.get_patch(conn, r.new_patches[0])
    assert p["read_on_first_snapshot"] == 1
    rev = store.revisions(conn, p["id"])[0]
    assert (rev["author"], rev["posted_at"]) == ("me@example.org", 1794414425)
    assert store.kv_get(conn, "last_discovery") == "100"


def test_second_run_patches_not_read_on_first(conn):
    discover(conn, FakeSource([]), ME, now=1, search=nosearch)
    r = discover(conn, FakeSource([E("a@x", "[PATCH] x one")]), ME, now=2, search=nosearch)
    assert store.get_patch(conn, r.new_patches[0])["read_on_first_snapshot"] == 0


def test_v2_becomes_revision(conn):
    discover(conn, FakeSource([E("a@x", "[PATCH] KVM: x86/mmu: fill memory_fault")]), ME, now=1, search=nosearch)
    r = discover(conn, FakeSource([E("b@x", "[PATCH v2 0/2] KVM: x86/mmu: Fill memory_fault")]), ME, now=2, search=nosearch)
    assert r.new_revisions and not r.new_patches
    p = store.get_patch(conn, "kvm-x86-mmu-fill-memory-fault")
    assert [x["version"] for x in store.revisions(conn, p["id"])] == [1, 2]
    assert p["read_on_first_snapshot"] == 1


def test_v3_attaches_to_newest_of_matching_patches(conn):
    a = store.add_patch(conn, "a", now=1)
    b = store.add_patch(conn, "b", now=1)
    store.add_revision(conn, a, "a1@x", subject="[PATCH] same", author="me@example.org")
    store.add_revision(conn, b, "b1@x", version=2, subject="[PATCH v2] same", author="me@example.org")
    discover(conn, FakeSource([E("n@x", "[PATCH v3] same")]), ME, now=2, search=nosearch)
    assert [r["version"] for r in store.revisions(conn, b)] == [2, 3]


def test_slug_avoids_taken_names_in_db(conn):
    store.add_patch(conn, "x-one", now=1)
    r = discover(conn, FakeSource([E("a@x", "[PATCH] x one", author="other@x.org")]), ME, now=2, search=nosearch)
    assert r.new_patches == ["x-one-2"]


def test_replies_hidden_and_ignored_skipped(conn):
    discover(conn, FakeSource([E("a@x", "[PATCH] x one")]), ME, now=1, search=nosearch)
    conn.execute("UPDATE patches SET hidden=1")
    conn.execute("INSERT INTO ignored VALUES ('c@x')")
    r = discover(conn, FakeSource([E("a@x", "[PATCH] x one"), E("r@x", "Re: [PATCH] x one", reply=True),
                                   E("c@x", "[PATCH] deleted one")]), ME, now=2, search=nosearch)
    assert r.new_patches == [] and r.new_revisions == []
    assert store.get_patch(conn, "x-one")["hidden"] == 1


def test_backport_posting_attaches_to_branch(conn):
    pid = store.add_patch(conn, "fix-io", now=1)
    store.add_revision(conn, pid, "a@x", subject="[PATCH] fix io")
    store.set_commit(conn, pid, "f" * 40, "fix io", "manual")
    stable = [E("bp@x", "[PATCH 6.1.y] fix io", reply=True, summary="commit ffffffffffff upstream.\n")]
    r = discover(conn, FakeSource([]), ME, now=2, search=lambda inbox, q, **k: stable)
    rev = store.revision_by_msgid(conn, "bp@x")
    assert r.backports == ["fix-io"] and (rev["kind"], rev["branch"], rev["patch_id"]) == ("backport", "6.1", pid)


def test_backport_matches_by_subject_and_skips_unknown(conn):
    pid = store.add_patch(conn, "fix-io", now=1)
    store.add_revision(conn, pid, "a@x", subject="[PATCH] fix io")
    stable = [E("bp@x", "[PATCH 6.6] Fix IO", summary="nothing"),
              E("zz@x", "[PATCH 6.6] unrelated", summary="commit 0123456789ab upstream")]
    r = discover(conn, FakeSource([]), ME, now=2, search=lambda *a, **k: stable)
    assert r.backports == ["fix-io"]
    assert store.revision_by_msgid(conn, "zz@x") is None


def test_url_msgids_are_not_discovered(conn):                    # plan 2 final review C1
    pid = store.add_patch(conn, "fix-io", now=1)
    store.add_revision(conn, pid, "a@x", subject="[PATCH] fix io", author="me@example.org")
    store.set_commit(conn, pid, "f" * 40, "fix io", "manual")
    evil = "http://127.0.0.1:8443/l/a@b"
    stable = [E("http://127.0.0.1:8443/l/s@b", "[PATCH 6.1.y] fix io",
                summary="commit ffffffffffff upstream.\n")]
    r = discover(conn, FakeSource([E(evil, "[PATCH] evil one"), E(evil + "2", "[PATCH v2] fix io")]),
                 ME, now=2, search=lambda *a, **k: stable)
    assert (r.new_patches, r.new_revisions, r.backports) == ([], [], [])
    assert [tuple(r) for r in conn.execute("SELECT root_msgid FROM revisions")] == [("a@x",)]

def test_version_and_backport_parsing():
    assert version_of("[RFC PATCH v3 2/5] x") == 3 and version_of("[PATCH] x") == 1
    assert backport_of("[PATCH 6.6] x", "[ Upstream commit 0659e44ce739ecd8 ]") == ("6.6", "0659e44ce739ecd8")
    assert backport_of("[PATCH 5.15.y] x", "commit 0659e44ce739 upstream.") == ("5.15", "0659e44ce739")
    assert backport_of("[PATCH] x", "") == (None, None)
    assert norm("[PATCH v2] Re: Foo  Bar") == "foo bar"
    assert slug("[PATCH] ", set()) == "thread"


def test_merge_by_change_id(conn):
    a = store.add_patch(conn, "old", now=1)
    b = store.add_patch(conn, "new", now=2)
    store.add_revision(conn, a, "a@x", subject="s")
    store.add_revision(conn, b, "b@x", version=2, subject="s")
    conn.execute("UPDATE revisions SET change_id='I1'")
    assert merge_by_change_id(conn) == ["new"]
    assert store.get_patch(conn, "new") is None
    assert [r["version"] for r in store.revisions(conn, a)] == [1, 2]


def test_nonreply_backport_in_both_sources_is_one_backport_revision(conn):
    pid = store.add_patch(conn, "fix-io", now=1)
    store.add_revision(conn, pid, "a@x", subject="[PATCH] fix io", author="me@example.org")
    store.set_commit(conn, pid, "f" * 40, "fix io", "manual")
    bp = E("bp@x", "[PATCH 6.1.y] fix io", summary="commit ffffffffffff upstream.\n")
    r = discover(conn, FakeSource([bp]), ME, now=2, search=lambda *a, **k: [bp])
    assert r.new_patches == [] and r.new_revisions == [] and r.backports == ["fix-io"]
    revs = store.revisions(conn, pid)
    assert [(x["kind"], x["branch"]) for x in revs] == [("series", None), ("backport", "6.1")]


def test_untracked_nonreply_backport_creates_no_patch(conn):
    bp = E("bp@x", "[PATCH 6.1.y] fix io")
    r = discover(conn, FakeSource([bp]), ME, now=2, search=lambda *a, **k: [bp])
    assert r.new_patches == [] and store.list_patches(conn) == []


@pytest.mark.parametrize("subject", ["[PATCH v2 1/2] x", "[PATCH 0/2] x", "[RFC PATCH v3 2/5] x",
                                     "[PATCH liburing] x"])
def test_ordinary_subjects_are_not_backports(subject):
    assert backport_of(subject, "")[0] is None


def test_merge_by_change_id_keeps_links_and_note(conn):
    a = store.add_patch(conn, "old", now=1)
    b = store.add_patch(conn, "new", now=2)
    store.add_revision(conn, a, "a@x", subject="s")
    store.add_revision(conn, b, "b@x", version=2, subject="s")
    conn.execute("UPDATE revisions SET change_id='I1'")
    store.add_links(conn, a, ["https://u/1"], 1)
    store.add_links(conn, b, ["https://u/1", "https://u/2"], 2)
    store.set_field(conn, b, "note", "from new")
    assert merge_by_change_id(conn) == ["new"]
    assert store.links(conn, a) == ["https://u/1", "https://u/2"]
    assert store.patch_by_id(conn, a)["note"] == "from new"


# --- final review C3: my replies on the stable list are not backports ----------

IOWQ = "io_uring/io-wq: apply the current cpuset to new workers"
IOWQ_SHA = "0659e44ce739ecd856164c75a5325b7959a2921d"


def stable_mails():
    """What lore's stable inbox has from me: a reply in the thread of my patch (it
    was Cc'd to stable), my backport sent in reply to stable's FAILED mail, and my
    reply to the backport."""
    from lorefix import entry

    return [
        entry("myreply@x", f"Re: [PATCH] {IOWQ}", inbox="stable", updated="2026-11-12T14:54:49Z",
              in_reply_to="felix@x",
              body=f"On 12/11/2026 Felix wrote:\n> Could this go to stable?\n\n"
                   f"Yes, it fixes 84eacf177faa.\n> commit {IOWQ_SHA[:12]} upstream.\n"),
        entry("bp@x", f"[PATCH 6.1.y] {IOWQ}", inbox="stable", updated="2026-11-20T09:00:00Z",
              in_reply_to="2026112001-failed@gregkh",
              body=f"commit {IOWQ_SHA} upstream.\n\nWorkers ignored the cpuset.\n\n"
                   "---\n+++ b/io_uring/io-wq.c\n"),
        entry("bp-ping@x", f"Re: [PATCH 6.1.y] {IOWQ}", inbox="stable",
              updated="2026-11-25T09:00:00Z", in_reply_to="bp@x", body="Ping?\n"),
    ]


def lore_search(fake):
    from patchtrail.sources import lore

    return lambda inbox, query, **kw: lore.search(inbox, query, urlopen=fake)


def test_my_reply_on_the_stable_list_is_no_backport(conn):
    from lorefix import FakeLore

    pid = store.add_patch(conn, "iowq-cpuset", now=1)
    store.add_revision(conn, pid, "root@x", subject=f"[PATCH] {IOWQ}", author="me@example.org")
    store.set_commit(conn, pid, IOWQ_SHA, IOWQ, "manual")
    fake = FakeLore()
    fake.add("stable", r"^f:me@example\.org$", stable_mails())
    r = discover(conn, FakeSource([]), ME, now=5, search=lore_search(fake))
    assert r.backports == ["iowq-cpuset"]
    assert [(x["root_msgid"], x["kind"], x["branch"]) for x in store.revisions(conn, pid)] == [
        ("root@x", "series", None), ("bp@x", "backport", "6.1")]


def test_my_reply_without_a_tracked_commit_is_no_backport(conn):
    from lorefix import FakeLore

    pid = store.add_patch(conn, "iowq-cpuset", now=1)
    store.add_revision(conn, pid, "root@x", subject=f"[PATCH] {IOWQ}", author="me@example.org")
    fake = FakeLore()
    fake.add("stable", r"^f:me@example\.org$", stable_mails()[:1])
    assert discover(conn, FakeSource([]), ME, now=5, search=lore_search(fake)).backports == []
    assert [x["root_msgid"] for x in store.revisions(conn, pid)] == ["root@x"]
