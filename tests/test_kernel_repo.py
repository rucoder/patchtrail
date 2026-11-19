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


def test_seed_leaves_source_untouched(tmp_path, kfix):          # Review Focus 3
    src = Git(kfix.mainline)
    before = src.run("for-each-ref"), sorted(p.name for p in (kfix.mainline / ".git").iterdir())
    r = KernelRepo(tmp_path / "linux.git"); r.ensure(kfix.mainline)
    assert r.run("for-each-ref", "--format=%(refname)").split()[0].startswith("refs/patchtrail/seed/")
    r.fetch(kfix.urls, ["6.1"], [], NullProgress())
    assert r.run("for-each-ref", "refs/patchtrail/seed/").strip() == ""
    assert (src.run("for-each-ref"), sorted(p.name for p in (kfix.mainline / ".git").iterdir())) == before


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
    assert fetched.resolve(f"{MAINLINE}") == s["U"]
    assert fetched.resolve(NEXT) == s["U"]
    assert fetched.resolve("refs/patchtrail/trees/-" + kfix.tree_url.split("file:///")[1].replace("/", "-")
                           + "/for-next") == s["G"]
    assert not fetched.is_ancestor(s["G"], MAINLINE)
