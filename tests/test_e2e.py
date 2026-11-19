# SPDX-License-Identifier: Apache-2.0
"""Offline end to end: the old scripts' files, `ptl setup` seeding from a clone
shaped like stable-watch's, the import, and a first `ptl fetch` against lore as
it answers (Atom pages, the bare `</feed>` past the last result, b4 threads) and
git remotes on disk. Only urlopen and b4 are fakes."""

import urllib.request

import pytest
from lorefix import FakeLore, entry
from mails import make_mail, mbox

from patchtrail import db, snapshot, store
from patchtrail.cli import main
from patchtrail.config import paths

ME = "Me <me@example.org>"
XIANG = "Gao Xiang <xiang@kernel.org>"
SEAN = "Sean Christopherson <seanjc@google.com>"
JENS = "Jens Axboe <axboe@kernel.dk>"
GREG = "Greg Kroah-Hartman <gregkh@linuxfoundation.org>"
EROFS = "erofs-utils: lib: follow symlinks on intermediate tar path components"
KVM1 = "KVM: x86/mmu: don't kill the VM on access to a disabled passthrough BAR"
KVM2 = "KVM: x86/mmu: Fill memory_fault for unresolvable guest page faults"


def day(d: str, hm: str = "12:00") -> str:
    """An RFC 5322 date, noon UTC: the same day in every test machine's zone."""
    from datetime import datetime

    return datetime.strptime(f"{d} {hm}", "%Y-%m-%d %H:%M").strftime(
        "%a, %d %b %Y %H:%M:00 +0000")


def threads(sha_f: str) -> dict[str, list[bytes]]:
    """Every thread as lore has it now; b4 returns the whole thread for any of its mails."""
    kvm = "kvm@vger.kernel.org"
    erofs = "linux-erofs@lists.ozlabs.org"
    io = "io-uring@vger.kernel.org"
    return {
        "kvm-v1": [
            make_mail("kv1@x", subject=f"[PATCH 0/1] {KVM1}", to=kvm, date=day("2026-06-21")),
            make_mail("kv1-1@x", subject=f"[PATCH 1/1] {KVM1}", to=kvm, in_reply_to="kv1@x",
                      date=day("2026-06-21", "12:01")),
            make_mail("kv1-r@x", frm=SEAN, subject=f"Re: [PATCH 1/1] {KVM1}", to=kvm,
                      in_reply_to="kv1-1@x", date=day("2026-06-22"), body="Let's do it differently.\n")],
        "kvm-v2": [
            make_mail("kv2@x", subject=f"[PATCH v2 0/2] {KVM2}", to=kvm, date=day("2026-09-20")),
            make_mail("kv2-1@x", subject=f"[PATCH v2 1/2] {KVM2}", to=kvm, in_reply_to="kv2@x",
                      date=day("2026-09-20", "12:01")),
            make_mail("kv2-r@x", frm=SEAN, subject=f"Re: [PATCH v2 0/2] {KVM2}", to=kvm,
                      in_reply_to="kv2@x", date=day("2026-10-02"),
                      body="Reviewed-by: Sean Christopherson <seanjc@google.com>\n")],
        "erofs": [                   # v2 sent in reply to the maintainer's second reply to v1
            make_mail("e1@x", subject=f"[PATCH] {EROFS}", to=erofs, date=day("2026-07-25")),
            make_mail("x1@x", frm=XIANG, subject=f"Re: [PATCH] {EROFS}", to=erofs,
                      in_reply_to="e1@x", date=day("2026-08-02")),
            make_mail("e1-r@x", subject=f"Re: [PATCH] {EROFS}", to=erofs, in_reply_to="x1@x",
                      date=day("2026-08-22")),
            make_mail("x2@x", frm=XIANG, subject=f"Re: [PATCH] {EROFS}", to=erofs,
                      in_reply_to="e1@x", date=day("2026-08-27"), body="Please send a v2.\n"),
            make_mail("e2@x", subject=f"[PATCH v2] {EROFS}", to=erofs, in_reply_to="x2@x",
                      date=day("2026-09-20"))],
        "iowq": [                    # Cc stable; my reply there; the Applied mail is new
            make_mail("io1@x", subject="[PATCH] fix io", to=io, cc="stable@vger.kernel.org",
                      date=day("2026-01-08"), body="---\n+++ b/io.c\n"),
            make_mail("io-f@x", frm="Felix <felix@example.com>", subject="Re: [PATCH] fix io",
                      to=io, cc="stable@vger.kernel.org", in_reply_to="io1@x",
                      date=day("2026-01-09"), body="Should this go to stable?\n"),
            make_mail("myreply@x", subject="Re: [PATCH] fix io", to=io,
                      cc="stable@vger.kernel.org", in_reply_to="io-f@x", date=day("2026-01-09", "14:00"),
                      body="> Should this go to stable?\n\nYes, it carries Cc: stable.\n"),
            make_mail("io-ty@x", frm=JENS, subject="Re: [PATCH] fix io", to=io,
                      in_reply_to="io1@x", date=day("2026-01-10"),
                      body=f"Applied, thanks!\n\n[1/1] fix io\n      commit: {sha_f}\n")],
        "failed-6.1": [              # stable's FAILED mail, my backport in reply to it
            make_mail("2026112001-failed@gregkh", frm=GREG, to="stable@vger.kernel.org",
                      subject='FAILED: patch "[PATCH] fix io" failed to apply to 6.1-stable tree',
                      date=day("2026-11-20", "09:00")),
            make_mail("bp@x", subject="[PATCH 6.1.y] fix io", to="stable@vger.kernel.org",
                      in_reply_to="2026112001-failed@gregkh", date=day("2026-11-20"),
                      body=f"commit {sha_f} upstream.\n\n---\n+++ b/io.c\n")],
    }


def old_files(home, archive):
    """lkml-watch and stable-watch as they were left: a -v1/-v2 pair and erofs (a
    [PATCH v2] root under a name without -vN) fully seen, iowq-cpuset with the
    Applied mail fetched but not seen yet, and its commit in stable-watch's fixes."""
    cfg, state = home / ".config", home / ".local" / "state"
    (cfg / "lkml-watch").mkdir(parents=True)
    (cfg / "stable-watch").mkdir(parents=True)
    (state / "lkml-watch").mkdir(parents=True)
    (cfg / "lkml-watch" / "threads").write_text(
        "# lkml-watch: NAME MESSAGE-ID, one thread per line\n"
        "kvm-bar-efault-v2 kv2@x\nkvm-bar-efault-v1 kv1@x\nerofs e2@x\niowq-cpuset io1@x\n")
    old = {"kvm-bar-efault-v1": archive["kvm-v1"], "kvm-bar-efault-v2": archive["kvm-v2"],
           "erofs": archive["erofs"], "iowq-cpuset": archive["iowq"]}
    for name, raws in old.items():
        (state / "lkml-watch" / f"{name}.mbox").write_bytes(mbox(*raws))
        ids = [r.split(b"Message-ID: <", 1)[1].split(b">", 1)[0].decode() for r in raws]
        if name == "iowq-cpuset":
            ids.remove("io-ty@x")
        (state / "lkml-watch" / f"{name}.seen").write_text("".join(f"<{i}>\n" for i in ids))
    return cfg / "stable-watch" / "fixes"


def fake_b4(tmp_path, archive):
    """b4 mbox: the whole thread of whichever mail is asked for, or b4's error."""
    lore = tmp_path / "lore-threads"
    lore.mkdir()
    for raws in archive.values():
        data = mbox(*raws)
        for raw in raws:
            msgid = raw.split(b"Message-ID: <", 1)[1].split(b">", 1)[0].decode()
            (lore / f"{msgid}.mbox").write_bytes(data)
    b4 = tmp_path / "fake-b4"
    b4.write_text("#!/bin/sh\nfor last; do :; done\n"
                  f'[ -f "{lore}/$last.mbox" ] || {{ echo "No messages found" >&2; exit 1; }}\n'
                  f'exec cat "{lore}/$last.mbox"\n')
    b4.chmod(0o755)
    return b4


def fake_lore(sha_f: str) -> FakeLore:
    """lore's search as it answers: my mails on all lists (discovery), my mails on
    stable (a reply in a thread Cc'd to stable and a backport), stable's FAILED mail;
    every other query 404."""
    lore = FakeLore(per_page=3)
    lore.add("all", r"^f:me@example\.org AND s:PATCH$", [
        entry("bp@x", "[PATCH 6.1.y] fix io", updated="2026-11-20T12:00:00Z",
              in_reply_to="2026112001-failed@gregkh", body=f"commit {sha_f} upstream.\n"),
        entry("kv2@x", f"[PATCH v2 0/2] {KVM2}", updated="2026-09-20T12:00:00Z"),
        entry("kv2-1@x", f"[PATCH v2 1/2] {KVM2}", updated="2026-09-20T12:01:00Z",
              in_reply_to="kv2@x"),
        entry("e2@x", f"[PATCH v2] {EROFS}", updated="2026-09-20T12:00:00Z", in_reply_to="x2@x"),
        entry("e1-r@x", f"Re: [PATCH] {EROFS}", updated="2026-08-22T12:00:00Z", in_reply_to="x1@x"),
        entry("e1@x", f"[PATCH] {EROFS}", updated="2026-07-25T12:00:00Z"),
        entry("kv1@x", f"[PATCH 0/1] {KVM1}", updated="2026-06-21T12:00:00Z"),
        entry("myreply@x", "Re: [PATCH] fix io", updated="2026-01-09T14:00:00Z",
              in_reply_to="io-f@x"),
        entry("io1@x", "[PATCH] fix io", updated="2026-01-08T12:00:00Z",
              body="---\n+++ b/io.c\n")])
    lore.add("stable", r"^f:me@example\.org$", [
        entry("bp@x", "[PATCH 6.1.y] fix io", inbox="stable", updated="2026-11-20T12:00:00Z",
              in_reply_to="2026112001-failed@gregkh", body=f"commit {sha_f} upstream.\n"),
        entry("myreply@x", "Re: [PATCH] fix io", inbox="stable", updated="2026-01-09T14:00:00Z",
              in_reply_to="io-f@x", body="> Should this go to stable?\n\nYes.\n")])
    lore.add("stable", r'^s:"FAILED: patch" AND s:"fix io"$', [
        entry("2026112001-failed@gregkh",
              'FAILED: patch "[PATCH] fix io" failed to apply to 6.1-stable tree',
              inbox="stable", author=("gregkh", "gregkh@linuxfoundation.org"),
              updated="2026-11-20T09:00:00Z",
              body=f"The patch below does not apply to the 6.1-stable tree.\n\n"
                   f"git cherry-pick -x {sha_f}\n")])
    return lore


@pytest.fixture
def world(tmp_path, hermetic, kfix, upfix, monkeypatch):
    from gitfix import make_stable_watch_clone

    sha_f = kfix.sha["F"]
    archive = threads(sha_f)
    fixes = old_files(hermetic, archive)
    fixes.write_text(f"# NAME COMMIT [TREE-URL BRANCH]\niowq-cpuset {sha_f} {kfix.tree_url} for-next\n")
    seed = hermetic / ".local" / "state" / "stable-watch" / "linux.git"
    make_stable_watch_clone(kfix, seed)
    p = paths()
    p.home.mkdir(parents=True)
    u = kfix.urls
    p.config.write_text(f'addresses = ["me@example.org"]\n\n[kernel]\nmainline = "{u.mainline}"\n'
                        f'stable = "{u.stable}"\nqueue = "{u.queue}"\nnext = "{u.next}"\n'
                        f'releases = "{u.releases}"\n\n[projects.erofs-utils]\n'
                        f'repo = "{upfix.url}"\nbranch = "master"\n')
    monkeypatch.setenv("PATCHTRAIL_B4", str(fake_b4(tmp_path, archive)))
    lore = fake_lore(sha_f)
    monkeypatch.setattr(urllib.request, "urlopen", lore)
    return seed, lore


def test_setup_import_and_first_fetch(world, kfix, capsys):
    from conftest import tree_state

    seed, lore = world
    seed_before = tree_state(seed)
    assert main(["setup"]) == 0
    out = capsys.readouterr().out
    assert f"seeding from {seed} (hardlinks, no copy)" in out and "imported 3 patches" in out

    assert main(["fetch"]) == 0
    log = capsys.readouterr().out
    assert "failed" not in log and "cannot" not in log, log
    assert "new revision: erofs" in log and "backport posted: iowq-cpuset" in log
    assert any("&o=" in u for u in lore.urls)              # paged to lore's `</feed>`

    conn = db.connect(paths().db)
    revs = lambda name: [(r["root_msgid"], r["kind"], r["version"], r["branch"])  # noqa: E731
                         for r in store.revisions(conn, store.get_patch(conn, name)["id"])]
    assert revs("iowq-cpuset") == [("io1@x", "series", 1, None), ("bp@x", "backport", 1, "6.1")]
    assert revs("erofs") == [("e1@x", "series", 1, None), ("e2@x", "series", 2, None)]
    assert revs("kvm-bar-efault") == [("kv1@x", "series", 1, None), ("kv2@x", "series", 2, None)]
    assert sorted(p["name"] for p in store.list_patches(conn)) == [
        "erofs", "iowq-cpuset", "kvm-bar-efault"]
    unread = {p["name"] for p in store.list_patches(conn) if snapshot.unread(conn, p["id"])}
    assert unread == {"iowq-cpuset"}                       # its Applied mail was never seen
    linux = paths().linux
    assert not [r for r in tree_state(linux)[0].splitlines() if "refs/patchtrail/seed/" in r]
    assert tree_state(seed) == seed_before

    assert main(["ls"]) == 0
    s = kfix.sha
    assert capsys.readouterr().out.splitlines() == [
        "iowq-cpuset     [PATCH] fix io",
        "                kernel · backports · APPLIED by Jens Axboe, 2026-01-10"
        " (5 messages, 2 new)",
        "                https://lore.kernel.org/all/io1@x/",
        f"    Fixes: {s['B'][:12]} (v6.1-rc1)   Cc: stable",
        "    mainline: v6.5-rc1",
        "    6.4.y   queued for the next 6.4 release: fix-io.patch",
        "    6.3.y   applies cleanly, after 1 queued patch to the same files",
        "    6.2.y   has it: v6.2.1",
        "    6.1.y   backport sent",
        f"    6.0.y   not affected: no {s['B'][:12]}",
        "    FAILED mails from stable (send a backport in reply):",
        "      6.1: 2026-11-20 https://lore.kernel.org/stable/2026112001-failed@gregkh/",
        "",
        f"kvm-bar-efault  [PATCH v2 0/2] {KVM2}",
        "                kernel · reviewed · Reviewed-by Sean Christopherson; waiting for the"
        " maintainer since 2026-10-02 (6 messages)",
        "                https://lore.kernel.org/all/kv2@x/",
        "",
        f"erofs           [PATCH v2] {EROFS}",
        "                erofs-utils · released · waiting for a reply since 2026-09-20 (5 messages)",
        "                https://lore.kernel.org/all/e2@x/",
        "",
    ]
