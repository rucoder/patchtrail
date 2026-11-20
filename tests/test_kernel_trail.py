# SPDX-License-Identifier: Apache-2.0
from dataclasses import replace

import pytest

from patchtrail.config import load_config, paths
from patchtrail.projects import get_project
from patchtrail.projects.kernel import KernelTrail
from patchtrail.projects.kernel.backport import make_backport
from patchtrail.projects.kernel.failed import failed_mails
from patchtrail.projects.kernel.repo import slug
from patchtrail.projects.kernel.follow import (commits_from_mail, maintainer_trees, matches,
                                               strip_subject)
from patchtrail.sources.lore import LoreError
from conftest import NullProgress, epoch, fake_search_from, raising, root, ty


@pytest.fixture
def trail(kfix):
    cfg = load_config(paths())
    cfg.kernel = kfix.urls
    return KernelTrail(paths(), cfg, search=lambda *a, **k: [])


def test_follow_from_mail_and_tree(trail, view, kfix):
    v = view(subject="[PATCH] fix more io", files=("io.c",), mails=[root("fix more io"),
             ty("[1/1] fix more io\n      commit: " + kfix.sha["G"] + "\n")])
    trail.prepare([v], NullProgress()); res = trail.evaluate(v, NullProgress())
    c = res.fragment["commits"][0]
    assert c["where"] == f"tree:{kfix.tree_url} for-next" and c["stage"] == "accepted"
    assert res.tree == (kfix.tree_url, "for-next")
    assert res.commits_found == [(kfix.sha["G"], "fix more io", "applied-mail")]


def test_found_without_reply_by_subject_and_author(trail, view, kfix):
    v = view(subject="[PATCH] fix io", mails=[root("fix io")])        # nobody replied "Applied"
    trail.prepare([v], NullProgress()); res = trail.evaluate(v, NullProgress())
    assert res.commits_found == [(kfix.sha["F"], "fix io", "search")]
    c = res.fragment["commits"][0]
    assert (c["where"], c["stage"], c["release"], c["stable"]) == ("mainline", "released", "v6.5-rc1", True)
    assert c["fixes"] == [{"sha": kfix.sha["B"], "release": "v6.1-rc1", "known": True}]
    assert res.fragment["branches"]["6.1"][kfix.sha["F"][:12]]["state"] == "conflict"
    assert res.fragment["branches"]["6.1"][kfix.sha["F"][:12]]["prereqs"][0]["sha"] == kfix.sha["R"]
    assert res.fragment["hint"] is None and res.tree is None


def test_untagged_commit_has_no_branches(trail, view, kfix):
    v = view(commits=[{"sha": kfix.sha["U"], "subject": "untagged io cleanup", "source": "manual"}])
    trail.prepare([v], NullProgress()); res = trail.evaluate(v, NullProgress())
    assert res.fragment["branches"] == {} and res.fragment["hint"].startswith("not tagged for stable")
    assert res.fragment["commits"][0]["stage"] == "applied" and res.commits_found == []


def test_skip_and_backport_sent(trail, view, kfix):
    v = view(commits=[{"sha": kfix.sha["F"], "subject": "fix io", "source": "manual"}],
             skips=frozenset({"6.1"}), backports={"6.3": ["bp@x"], "6.4": ["bp2@x"]})
    trail.prepare([v], NullProgress()); b = trail.evaluate(v, NullProgress()).fragment["branches"]
    k = kfix.sha["F"][:12]
    assert b["6.1"][k]["state"] == "skipped" and b["6.3"][k]["state"] == "backport_sent"
    assert b["6.4"][k]["state"] == "queued"                    # queued wins over a sent backport


def test_missing_commit_and_unknown_fixes(trail, view):                 # Review Focus 5
    v = view(commits=[{"sha": "deadbeefdead", "subject": "gone", "source": "manual"}])
    trail.prepare([v], NullProgress()); res = trail.evaluate(v, NullProgress())
    assert res.fragment["commits"][0]["where"] == "missing"
    assert res.fragment["commits"][0]["stage"] == "accepted" and res.fragment["branches"] == {}


def test_unknown_fixes_hash_means_all_affected(trail, view, kfix):
    v = view(commits=[{"sha": kfix.sha["V"], "subject": "fix with unknown fixes", "source": "manual"}])
    trail.prepare([v], NullProgress()); res = trail.evaluate(v, NullProgress())
    assert res.fragment["commits"][0]["fixes"] == [{"sha": "000000000000", "release": None, "known": False}]
    assert res.fragment["branches"]["6.0"][kfix.sha["V"][:12]]["state"] != "not_affected"


def test_failed_mails_parse():
    got = failed_mails("fix io", search=fake_search_from("tests/data/failed.atom"))
    assert got == {"6.1": {"date": "2026-11-20", "url": "https://lore.kernel.org/stable/2026112001-x@gregkh/"}}


def test_failed_search_keeps_previous_failed(trail, view, kfix):        # Review Focus 1
    prev = {"failed": {"6.1": {"date": "2026-11-20", "url": "u"}}}
    v = view(commits=[{"sha": kfix.sha["F"], "subject": "fix io", "source": "manual"}], prev_state=prev)
    trail.search = raising(LoreError("429"))
    logged = []
    progress = NullProgress()
    progress.log = logged.append
    trail.prepare([v], NullProgress())
    assert trail.evaluate(v, progress).fragment["failed"] == prev["failed"]
    assert any("429" in line for line in logged)


def test_maintainer_trees(fetched, kfix):
    assert maintainer_trees(fetched, ["io.c"]) == [kfix.tree_url]
    assert maintainer_trees(fetched, ["README"]) == []


@pytest.mark.parametrize("pattern,path,want", [
    ("io.c", "io.c", True), ("io.c", "io.cc", False),
    ("drivers/net/", "drivers/net/x/y.c", True), ("drivers/net", "drivers/net/y.c", True),
    ("drivers/net", "drivers/netfoo.c", False), ("drivers/*/phy.c", "drivers/net/phy.c", True),
    ("include/linux/io_uring*", "include/linux/io_uring_types.h", True),
])
def test_maintainers_patterns(pattern, path, want):
    assert matches(pattern, path) is want


def test_subjects_and_applied_commits():
    assert strip_subject("Re: [PATCH v2 1/3] [net]  io:  fix\tx ") == "io: fix x"
    mine = replace(ty("[1/1] fix io\n      commit: 1111111111aa\n"), from_addr="me@example.org")
    mails = [ty("[1/2] a\n      commit: 2222222222aa\n[2/2] b\n      commit: 3333333333aa\n"),
             mine, ty("[1/2] a\n      commit: 2222222222aa\n")]
    assert commits_from_mail(mails, frozenset({"me@example.org"})) == [("a", "2222222222aa"),
                                                                         ("b", "3333333333aa")]


def test_check_commits_forces_the_stable_trail(trail, kfix):
    trail.prepare([], NullProgress())
    [res] = trail.check_commits([kfix.sha["U"][:12]], NullProgress())
    c = res.fragment["commits"][0]
    assert (c["sha"], c["subject"], c["stable"]) == (kfix.sha["U"], "untagged io cleanup", True)
    assert set(res.fragment["branches"]) == {"6.4", "6.3", "6.2", "6.1", "6.0"}
    assert res.fragment["hint"] is None


def test_kernel_project_builds_the_trail(kfix):
    assert isinstance(get_project("kernel").trail(paths(), load_config(paths())), KernelTrail)


def test_backport_worktree(fetched, queue, tmp_path, kfix):
    # `fetched` is function-scoped: the backport branch never reaches another test's repo.
    lines = make_backport(fetched, queue, kfix.sha["F"], "fix-io", "6.3", tmp_path / "wt")
    assert (tmp_path / "wt" / "io.c").exists() and any("applies cleanly" in l for l in lines)
    assert lines[0] == "applied queued io-other-hunk.patch"
    assert lines[-1].startswith("stable's form: the first body line 'commit <hash> upstream.'")
    log = fetched.run("log", "-1", "--format=%B", "refs/heads/backport/fix-io-6.3")
    assert f"(cherry picked from commit {kfix.sha['F']})" in log


def test_backport_conflict_is_left_to_resolve(fetched, queue, tmp_path, kfix):
    lines = make_backport(fetched, queue, kfix.sha["F"], "fix-io", "6.1", tmp_path / "wt")
    assert f"{kfix.sha['F'][:12]} conflicts: resolve, git cherry-pick --continue" in lines
    assert (tmp_path / "wt" / ".git").exists()


def test_trees_fetched_only_while_needed(trail, view, kfix):
    merged = view(id=1, files=("io.c",),
                  commits=[{"sha": kfix.sha["F"], "subject": "fix io", "source": "manual"}])
    trail.prepare([merged], NullProgress())                    # in mainline: no tree needed
    assert trail.repo.run("for-each-ref", "refs/patchtrail/trees/").strip() == ""
    waiting = view(id=2, subject="[PATCH] fix more io", files=("io.c",))
    trail.prepare([merged, waiting], NullProgress())           # not found yet: MAINTAINERS' trees
    assert trail.repo.run("for-each-ref", "refs/heads", "refs/tags").strip() == ""
    res = trail.evaluate(waiting, NullProgress())
    assert res.commits_found == [(kfix.sha["G"], "fix more io", "search")]
    assert res.fragment["commits"][0]["where"] == f"tree:{kfix.tree_url} for-next"


def test_fetch_trees_logs_a_dead_tree(fetched, kfix, tmp_path):
    logged = []
    progress = NullProgress()
    progress.log = logged.append
    fetched.fetch_trees([((tmp_path / "gone").as_uri(), "*"), (kfix.tree_url, "for-next")], progress)
    assert len(logged) == 1 and "gone" in logged[0]
    assert fetched.resolve(f"refs/patchtrail/trees/{slug(kfix.tree_url)}/for-next") == kfix.sha["G"]


def test_later_applied_reply_adds_to_stored_commits(trail, view, kfix):          # R21 (a)
    F, U = kfix.sha["F"], kfix.sha["U"]
    v = view(commits=[{"sha": F, "subject": "fix io", "source": "applied-mail"}],
             mails=[root("fix io"), ty("[1/2] fix io\n      commit: " + F[:12] + "\n"),
                    ty("[2/2] untagged io cleanup\n      commit: " + U[:12] + "\n")])
    trail.prepare([v], NullProgress()); res = trail.evaluate(v, NullProgress())
    assert [c["sha"] for c in res.fragment["commits"]] == [F, U]
    assert res.commits_found == [(U, "untagged io cleanup", "applied-mail")]
    assert res.replaced == {}


@pytest.mark.parametrize("source", ["applied-mail", "search", "manual"])
def test_rebased_commit_is_replaced_unless_manual(trail, view, kfix, source):    # R21 (b)
    gone = "de" * 20                                           # rebased away: in no ref
    v = view(commits=[{"sha": gone, "subject": "fix io", "source": source}])
    trail.prepare([v], NullProgress()); res = trail.evaluate(v, NullProgress())
    c = res.fragment["commits"][0]
    if source == "manual":
        assert res.replaced == {} and (c["sha"], c["where"]) == (gone, "missing")
    else:
        assert res.replaced == {gone: kfix.sha["F"]}
        assert (c["sha"], c["where"], c["release"]) == (kfix.sha["F"], "mainline", "v6.5-rc1")
        assert kfix.sha["F"][:12] in res.fragment["branches"]["6.1"]
    assert res.commits_found == []


def test_dropped_commit_stays_missing(trail, view):
    v = view(commits=[{"sha": "de" * 20, "subject": "never merged", "source": "applied-mail"}])
    trail.prepare([v], NullProgress()); res = trail.evaluate(v, NullProgress())
    assert res.replaced == {} and res.fragment["commits"][0]["where"] == "missing"


def test_found_upstream_by_subject_needs_no_tree(trail, view, kfix):  # final review I5
    v = view(subject="[PATCH] fix io", files=("io.c",), mails=[root("fix io")])
    trail.prepare([v], NullProgress())          # nobody replied "Applied", but mainline has it
    assert trail.repo.run("for-each-ref", "refs/patchtrail/trees/").strip() == ""
    res = trail.evaluate(v, NullProgress())
    assert res.commits_found == [(kfix.sha["F"], "fix io", "search")]
    assert res.fragment["commits"][0]["where"] == "mainline"
    waiting = view(id=2, subject="[PATCH] fix more io", files=("io.c",))
    trail.prepare([v, waiting], NullProgress())                 # only in its tree: fetched
    assert trail.repo.run("for-each-ref", "--format=%(refname)",
                          "refs/patchtrail/trees/").split() != []


def test_rebased_commit_found_on_first_run(trail, view, kfix):
    gone = "de" * 20                                  # the "Applied" mail names a rebased-away hash
    v = view(subject="[PATCH] fix io", mails=[root("fix io"),
             ty("[1/1] fix io\n      commit: " + gone + "\n")])
    trail.prepare([v], NullProgress()); res = trail.evaluate(v, NullProgress())
    assert res.commits_found == [(kfix.sha["F"], "fix io", "search")]
    assert res.replaced == {}
    assert [(c["sha"], c["where"]) for c in res.fragment["commits"]] == [(kfix.sha["F"], "mainline")]


# --- idle patches ---------------------------------------------------------------

NOW = epoch("2026-11-20")


def _idle_trail(kfix, **cfg_kw):
    cfg = load_config(paths())
    cfg.kernel = kfix.urls
    for k, v in cfg_kw.items():
        setattr(cfg, k, v)
    return KernelTrail(paths(), cfg, search=lambda *a, **k: [], now=lambda: NOW)


def _aged(day, subject="fix more io"):
    return replace(root(subject), date=epoch(day))


class LogProgress(NullProgress):
    def __init__(self):
        self.lines = []

    def log(self, line):
        self.lines.append(line)


def _trees_fetched(trail):
    return trail.repo.run("for-each-ref", "refs/patchtrail/trees/").strip() != ""


def test_idle_patch_trees_not_fetched(kfix, view):
    trail, progress = _idle_trail(kfix), LogProgress()
    v = view(name="old", subject="[PATCH] fix more io", files=("io.c",), mails=[_aged("2024-03-01")])
    trail.prepare([v], progress)
    assert not _trees_fetched(trail)
    assert progress.lines == ["old: idle since 2024-03-01, maintainer trees not fetched"]
    res = trail.evaluate(v, NullProgress())              # still evaluated, just without a tree
    assert res.fragment["commits"] == [] and res.tree is None


def test_idle_patch_still_found_upstream(kfix, view):
    trail = _idle_trail(kfix)
    v = view(subject="[PATCH] fix io", files=("io.c",), mails=[_aged("2024-03-01", "fix io")])
    trail.prepare([v], NullProgress())
    assert trail.evaluate(v, NullProgress()).commits_found == [(kfix.sha["F"], "fix io", "search")]


def test_recent_patch_trees_fetched(kfix, view):
    trail = _idle_trail(kfix)
    v = view(subject="[PATCH] fix more io", files=("io.c",), mails=[_aged("2026-10-01")])
    trail.prepare([v], NullProgress())
    assert _trees_fetched(trail)


def test_patch_without_mails_is_never_idle(kfix, view):
    trail = _idle_trail(kfix)
    trail.prepare([view(subject="[PATCH] fix more io", files=("io.c",), mails=[])], NullProgress())
    assert _trees_fetched(trail)


def test_manual_tree_always_fetched(kfix, view):
    trail = _idle_trail(kfix)
    v = view(subject="[PATCH] fix more io", files=("io.c",), mails=[_aged("2024-03-01")],
             tree=(kfix.tree_url, "for-next"), tree_source="manual")
    trail.prepare([v], NullProgress())
    assert _trees_fetched(trail)


def test_idle_days_from_config(kfix, view, tmp_path):
    paths().home.mkdir(parents=True, exist_ok=True)
    paths().config.write_text("idle_days = 30\n")
    assert load_config(paths()).idle_days == 30
    mails = [_aged("2026-09-01")]                        # 80 days old: idle at 30, not at 180
    v = view(subject="[PATCH] fix more io", files=("io.c",), mails=mails)
    short = _idle_trail(kfix, idle_days=30)
    short.prepare([v], NullProgress())
    assert not _trees_fetched(short)
    longer = _idle_trail(kfix, idle_days=180)
    longer.prepare([v], NullProgress())
    assert _trees_fetched(longer)
