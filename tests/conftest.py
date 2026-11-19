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


# Task 9: patch views, mails and fakes for the trails.

def epoch(day: str) -> int:
    """Seconds since the epoch at 00:00 UTC of YYYY-MM-DD."""
    from datetime import datetime, timezone

    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


@pytest.fixture
def view():
    from patchtrail.projects.base import PatchView

    def make(**kw):
        fields = dict(id=1, name="p", relation="mine", project="kernel", mails=[],
                      posted_at=epoch("2026-01-01"), subject="[PATCH] fix io",
                      author="me@example.org", commits=[], tree=None, tree_source=None,
                      force_stable=False, skips=frozenset(), manual_applied=False,
                      backports={}, prev_state=None)
        fields.update(kw)
        return PatchView(**fields)

    return make


def root(subj):
    from mails import make_mail
    from patchtrail.mail import parse_mail

    return parse_mail(make_mail("r@x", subject=f"[PATCH] {subj}", body="---\n+++ b/io.c\n"))


def ty(blocks):
    from mails import make_mail
    from patchtrail.mail import parse_mail

    return parse_mail(make_mail("t@x", frm="Maint <m@k.org>", in_reply_to="r@x",
                                subject="Re: [PATCH] x", body="Applied, thanks!\n\n" + blocks))


def raising(exc):
    def call(*args, **kwargs):
        raise exc

    return call


class _FileResponse:
    def __init__(self, data: bytes):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_search_from(path):
    """lore.search answering every request with the file at path (relative to the repo)."""
    from pathlib import Path

    from patchtrail.sources import lore

    data = (Path(__file__).parent.parent / path).read_bytes()

    def search(inbox, query, **kwargs):
        return lore.search(inbox, query, urlopen=lambda req, timeout=None: _FileResponse(data))

    return search


@pytest.fixture
def upfix(tmp_path):
    from gitfix import make_upstream_fixture

    return make_upstream_fixture(tmp_path)
