import urllib.request

import pytest


@pytest.fixture(autouse=True)
def hermetic(tmp_path, monkeypatch):
    """Isolate every test from the real home, git config and network."""
    home = tmp_path / "home"
    home.mkdir()
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("[user]\n\tname = Test User\n\temail = me@example.org\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATCHTRAIL_HOME", str(tmp_path / "ptl"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.delenv("PATCHTRAIL_FROM", raising=False)

    def no_network(*args, **kwargs):
        raise AssertionError("network in tests")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    return home


@pytest.fixture
def conn():
    from patchtrail import db
    from patchtrail.config import paths

    c = db.connect(paths().db)
    yield c
    c.close()


class NullProgress:
    def phase(self, name, steps=None):
        pass

    def step(self, label):
        pass

    def log(self, line):
        pass


@pytest.fixture(scope="session")
def kfix(tmp_path_factory):
    from gitfix import make_kernel_fixture

    return make_kernel_fixture(tmp_path_factory.mktemp("kfix"))


@pytest.fixture
def fetched(tmp_path, kfix):
    from patchtrail.projects.kernel.repo import KernelRepo

    r = KernelRepo(tmp_path / "linux.git")
    r.ensure(None)
    r.fetch(kfix.urls, ["6.0", "6.1", "6.2", "6.3", "6.4"], [(kfix.tree_url, "*")], NullProgress())
    return r


@pytest.fixture
def queue(tmp_path, kfix):
    from patchtrail.projects.kernel.queue import StableQueue

    q = StableQueue(tmp_path / "stable-queue")
    q.update(kfix.urls.queue, NullProgress())
    return q
