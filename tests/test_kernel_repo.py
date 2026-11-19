# SPDX-License-Identifier: Apache-2.0
import os
from pathlib import Path

from patchtrail.config import KernelUrls
from patchtrail.projects.kernel.queue import StableQueue
from patchtrail.projects.kernel.repo import (
    MAINLINE, NEXT, TAGS, Git, KernelRepo, branches, fetch_releases, stable_ref,
)
from conftest import NullProgress

DATA = Path(__file__).parent / "data"


def test_fetch_namespaces_and_graph(tmp_path, kfix):
    r = KernelRepo(tmp_path / "linux.git"); r.ensure(None)
    r.fetch(kfix.urls, ["6.0", "6.1", "6.2", "6.3", "6.4"], [(kfix.tree_url, "*")], NullProgress())
    assert r.run("for-each-ref", "refs/heads", "refs/tags").strip() == ""
    assert r.resolve(MAINLINE) and r.resolve(NEXT) and r.resolve(stable_ref("6.1"))
    assert r.resolve(f"{TAGS}/v6.5-rc1")
    assert (r.path / "objects/info/commit-graphs/commit-graph-chain").exists()


def test_first_tag(fetched, kfix):
    assert fetched.first_tag(kfix.sha["F"]) == "v6.5-rc1"
    assert fetched.first_tag(kfix.sha["B"]) == "v6.1-rc1"
    assert fetched.release_tags("6.2") == ["v6.2.1"]


def test_branches_filter():
    assert branches((DATA / "releases.json").read_bytes()) == ["6.4", "6.3", "6.2", "6.1", "6.0"]


def test_fetch_releases_file_url(kfix):
    assert fetch_releases(kfix.urls) == (DATA / "releases.json").read_bytes()
    seen = []

    class R:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b"{}"

    def opener(req, timeout):
        seen.append(req.full_url)
        return R()

    assert fetch_releases(KernelUrls(releases="https://x.org/r.json"), urlopen=opener) == b"{}"
    assert seen == ["https://x.org/r.json"]


def test_seed_from_a_stable_watch_clone(tmp_path, kfix, swclone):   # final review C2
    from conftest import tree_state

    before = tree_state(swclone)
    assert before[0] and "refs/heads/" not in before[0] and "\trefs/tags/" not in before[0]
    r = KernelRepo(tmp_path / "linux.git"); r.ensure(swclone)
    refs = r.run("for-each-ref", "--format=%(refname)").split()
    assert len(refs) == len(before[0].splitlines())
    assert all(x.startswith("refs/patchtrail/seed/refs/stable-watch/") for x in refs)
    assert r.resolve("refs/patchtrail/seed/refs/stable-watch/mainline") == kfix.sha["V"]
    assert r.run("remote").strip() == ""
    [pack] = (swclone / "objects" / "pack").glob("*.pack")
    assert (r.path / "objects" / "pack" / pack.name).stat().st_ino == pack.stat().st_ino
    r.fetch(kfix.urls, ["6.1"], [], NullProgress())
    assert r.run("for-each-ref", "refs/patchtrail/seed/").strip() == ""
    assert r.resolve(MAINLINE) == kfix.sha["V"]
    assert tree_state(swclone) == before


def test_seed_with_refs_only_under_heads_and_tags(tmp_path, kfix):
    from conftest import tree_state

    before = tree_state(kfix.mainline / ".git")
    r = KernelRepo(tmp_path / "linux.git"); r.ensure(kfix.mainline)
    refs = r.run("for-each-ref", "--format=%(refname)").split()
    assert "refs/patchtrail/seed/refs/heads/master" in refs
    assert all(x.startswith("refs/patchtrail/seed/") for x in refs)
    r.fetch(kfix.urls, ["6.1"], [], NullProgress())
    assert r.run("for-each-ref", "refs/patchtrail/seed/").strip() == ""
    assert tree_state(kfix.mainline / ".git") == before


def test_seed_without_refs(tmp_path):
    empty = tmp_path / "empty.git"
    Git(tmp_path).run("init", "-q", "--bare", str(empty))
    r = KernelRepo(tmp_path / "linux.git"); r.ensure(empty)
    assert r.run("for-each-ref").strip() == ""


def test_queue(tmp_path, kfix):
    q = StableQueue(tmp_path / "stable-queue"); q.update(kfix.urls.queue, NullProgress())
    assert [p.name for p in q.patches("6.3")] == ["io-other-hunk.patch"]
    assert q.queued("6.4", kfix.sha["F"]) == ["fix-io.patch"]
    q.update(kfix.urls.queue, NullProgress())                  # second update: fetch + reset path


def test_scenario(fetched, kfix):
    s = kfix.sha
    f = lambda b, c: fetched.is_ancestor(c, stable_ref(b))
    assert not any(f(b, s["F"]) for b in ("6.0", "6.1", "6.3", "6.4"))
    assert f("6.2", s["F62"]) and fetched.first_tag(s["F62"], "6.2") == "v6.2.1"
    assert not fetched.is_ancestor(s["U"], stable_ref("6.4"))
    assert fetched.resolve(f"{MAINLINE}") == s["V"]
    assert fetched.resolve(NEXT) == s["V"]
    assert fetched.resolve("refs/patchtrail/trees/-" + kfix.tree_url.split("file:///")[1].replace("/", "-")
                           + "/for-next") == s["G"]
    assert not fetched.is_ancestor(s["G"], MAINLINE)


def test_backport_subject_and_body(fetched, kfix, queue):
    f = kfix.sha["F"]
    r = fetched
    assert r.run("log", "-1", "--format=%s", kfix.sha["F62"]).strip() == "fix io"
    assert f"commit {f} upstream." in r.run("log", "-1", "--format=%b", kfix.sha["F62"])
    text = queue.patches("6.4")[0].text
    assert "Subject: [PATCH] fix io" in text
    assert f"commit {f} upstream." in text


NET_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_HTTP_LOW_SPEED_LIMIT": "1000",
           "GIT_HTTP_LOW_SPEED_TIME": "60"}


def test_network_git_calls_never_prompt(tmp_path, kfix, monkeypatch):
    import subprocess

    calls = []
    real = subprocess.run

    def spy(args, *a, **kw):
        calls.append((list(args), kw.get("env")))
        return real(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    r = KernelRepo(tmp_path / "linux.git"); r.ensure(None)
    r.fetch(kfix.urls, ["6.1"], [(kfix.tree_url, "for-next")], NullProgress())
    r.fetch_trees([(kfix.tree_url, "*")], NullProgress())
    q = StableQueue(tmp_path / "stable-queue")
    q.update(kfix.urls.queue, NullProgress()); q.update(kfix.urls.queue, NullProgress())
    net = [(args, env) for args, env in calls if "fetch" in args or "clone" in args]
    assert len(net) == 7      # mainline, stable, next, tree; tree "*"; queue clone, queue fetch
    for args, env in net:
        assert env is not None and {k: env.get(k) for k in NET_ENV} == NET_ENV, args
        assert env["GIT_CONFIG_GLOBAL"] == os.environ["GIT_CONFIG_GLOBAL"]   # merged over the environment


# --- final review I2: git never repacks on its own ------------------------------

def no_auto_gc(path):
    get = lambda key: Git(path).run("config", "--local", "--get", key, ok=(0, 1)).strip()  # noqa: E731
    return get("gc.auto") == "0" and get("maintenance.auto") == "false"


def test_new_repos_never_gc_on_their_own(tmp_path, swclone):
    plain = KernelRepo(tmp_path / "plain.git"); plain.ensure(None)
    seeded = KernelRepo(tmp_path / "seeded.git"); seeded.ensure(swclone)
    assert no_auto_gc(plain.path) and no_auto_gc(seeded.path)
    packs = sorted(p.stem for p in (seeded.path / "objects" / "pack").glob("*.pack"))
    assert packs and sorted(p.stem for p in (seeded.path / "objects" / "pack").glob("*.keep")) == packs
    assert not list((swclone / "objects" / "pack").glob("*.keep"))


def test_existing_repo_gets_the_config_on_open(tmp_path):
    path = tmp_path / "linux.git"
    Git(tmp_path).run("init", "-q", "--bare", str(path))      # made before this config existed
    assert not no_auto_gc(path)
    KernelRepo(path).ensure(None)
    assert no_auto_gc(path)


def test_stable_queue_never_gcs_on_its_own(tmp_path, kfix):
    q = StableQueue(tmp_path / "stable-queue")
    q.update(kfix.urls.queue, NullProgress())
    assert no_auto_gc(q.path)
    Git(q.path).run("config", "--local", "--unset", "gc.auto")
    q.update(kfix.urls.queue, NullProgress())
    assert no_auto_gc(q.path)


def test_git_output_that_is_not_utf8(tmp_path):                  # final review M5
    repo = tmp_path / "r"
    git = Git(repo)
    Git(tmp_path).run("init", "-q", str(repo))
    (repo / "io.c").write_bytes(b"/* (C) 1994 Andr\xe9, latin-1 */\nint io;\n")
    git.run("add", "io.c")
    git.run("commit", "-q", "-m", "io: add")
    (repo / "io.c").write_bytes(b"/* (C) 1994 Andr\xe9, latin-1 */\nint io_fixed;\n")
    git.run("commit", "-q", "-am", "io: fix")
    diff = git.run("diff", "-U3", "HEAD^", "HEAD", "--", "io.c")
    assert " /* (C) 1994 Andr\ufffd, latin-1 */\n-int io;\n+int io_fixed;\n" in diff
    blame = git.run("blame", "--porcelain", "-L", "1,+1", "HEAD", "--", "io.c")
    assert "\t/* (C) 1994 Andr\ufffd, latin-1 */" in blame
