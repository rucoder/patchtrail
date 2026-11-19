import urllib.error
from pathlib import Path

import pytest

from patchtrail.sources.lore import LORE, LoreError, LoreSource, fetch_thread, parse_msgid, search

DATA = Path(__file__).parent / "data"


class FakeResp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeUrlopen:
    def __init__(self):
        self.urls = []
        self.headers = []
        self.p1 = (DATA / "search-page1.atom").read_bytes()
        self.p2 = (DATA / "search-page2.atom").read_bytes()

    def __call__(self, req, timeout=None):
        self.urls.append(req.full_url)
        self.headers.append(req.headers)
        return FakeResp(self.p1 if "&o=" not in req.full_url else self.p2)


@pytest.fixture
def fake_urlopen():
    return FakeUrlopen()


def test_parse_msgid_forms():
    for a in ["<20261111162705.1150983-1-me@x>", "20261111162705.1150983-1-me@x",
              "https://lore.kernel.org/all/20261111162705.1150983-1-me@x/",
              "https://lore.kernel.org/io-uring/20261111162705.1150983-1-me@x/T/#u",
              "https://lore.kernel.org/r/20261111162705.1150983-1-me@x",
              "https://lore.kernel.org/all/20261111162705.1150983-1-me%40x/"]:
        assert parse_msgid(a) == "20261111162705.1150983-1-me@x"


def test_search_pages_and_user_agent(fake_urlopen):
    entries = search("all", "f:me@example.org AND s:PATCH", urlopen=fake_urlopen)
    assert [e.msgid for e in entries] == ["p1@x", "p2@x", "p3@x"]
    assert all(h["User-agent"].startswith("patchtrail/") for h in fake_urlopen.headers)
    assert "x=A" in fake_urlopen.urls[0] and "o=" not in fake_urlopen.urls[0]
    assert "o=2" in fake_urlopen.urls[1]


def test_search_entry_fields(fake_urlopen):
    e = search("all", "x", urlopen=fake_urlopen)
    assert e[0].author == "me@example.org" and e[0].summary == "cover text"
    assert e[0].subject == "[PATCH 0/2] first" and not e[0].is_reply
    assert e[0].updated.startswith("2026-11-11") and e[0].href.startswith("http")
    assert e[1].is_reply and e[1].summary == ""


def test_search_404_is_empty():
    def nf(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
    assert search("stable", "s:x", urlopen=nf) == []


def test_search_other_errors_raise():
    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "slow", {}, None)
    with pytest.raises(LoreError):
        search("all", "s:x", urlopen=boom)


def test_search_defaults_to_module_urlopen_at_call_time():
    with pytest.raises(AssertionError, match="network in tests"):
        search("all", "s:x")


def test_discover_filters_replies_and_dates(fake_urlopen):
    got = LoreSource(urlopen=fake_urlopen).discover(["me@example.org"], 1794900000)
    assert [e.msgid for e in got] == ["p1@x", "p3@x"]
    assert "d%3A20261115.." in fake_urlopen.urls[0]
    assert fake_urlopen.urls[0].startswith(f"{LORE}/all/?q=")


def test_fetch_thread_uses_b4(tmp_path, monkeypatch):
    fake = tmp_path / "b4"
    fake.write_text("#!/bin/sh\necho \"$@\" > %s/args\nprintf 'From x\\n'\n" % tmp_path)
    fake.chmod(0o755)
    monkeypatch.setenv("PATCHTRAIL_B4", str(fake))
    assert fetch_thread("a@b").startswith(b"From ")
    assert (tmp_path / "args").read_text().split() == ["-q", "mbox", "-C", "-o", "-", "a@b"]


def test_fetch_thread_error(tmp_path, monkeypatch):
    fake = tmp_path / "b4"
    fake.write_text("#!/bin/sh\necho 'boom: no such thread' >&2\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATCHTRAIL_B4", str(fake))
    with pytest.raises(LoreError, match="boom: no such thread"):
        fetch_thread("a@b")
