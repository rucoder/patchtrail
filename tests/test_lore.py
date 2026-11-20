# SPDX-License-Identifier: Apache-2.0
import subprocess
import urllib.error
from pathlib import Path

import pytest
from conftest import raising

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
    assert (tmp_path / "args").read_text().split() == ["-q", "mbox", "-C", "-o", "-", "--", "a@b"]


def test_fetch_thread_error(tmp_path, monkeypatch):
    fake = tmp_path / "b4"
    fake.write_text("#!/bin/sh\necho 'boom: no such thread' >&2\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATCHTRAIL_B4", str(fake))
    with pytest.raises(LoreError, match="boom: no such thread"):
        fetch_thread("a@b")


# --- lore as it really answers (final review C1, I4) ---------------------------

FAILED_PAGE = (DATA / "lore-failed.atom").read_bytes()     # a real page, trimmed to 2 entries
END_PAGE = (DATA / "lore-end.atom").read_bytes()           # lore's answer past the last result


class PagedUrlopen:
    """lore: the first page for a query, then `later` for every offset after it."""

    def __init__(self, first, later):
        self.first, self.later, self.urls = first, later, []

    def __call__(self, req, timeout=None):
        self.urls.append(req.full_url)
        body = self.first if "&o=" not in req.full_url else self.later
        if isinstance(body, int):
            raise urllib.error.HTTPError(req.full_url, body, "err", {}, None)
        return FakeResp(body)


def test_lore_end_page_is_not_xml():
    assert END_PAGE == b"</feed>"


@pytest.mark.parametrize("later", [END_PAGE, 404, b"<html>oops", b'<?xml version="1.0"?>'
                                   b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'],
                         ids=["end-page", "404", "not-xml", "no-entries"])
def test_search_ends_after_the_last_page(later):
    op = PagedUrlopen(FAILED_PAGE, later)
    got = search("stable", 's:"failed to apply to 5.4-stable tree"', urlopen=op)
    assert [e.msgid for e in got] == ["2025012032-alpha-beta-0001@stable-bot",
                                      "2025011317-gamma-delta-0002@stable-bot"]
    assert len(op.urls) == 2 and op.urls[1].endswith("&o=2")


@pytest.mark.parametrize("first", [END_PAGE, b"<html>oops", 500], ids=["end-page", "not-xml", "500"])
def test_search_first_page_errors_raise(first):
    with pytest.raises(LoreError):
        search("stable", "s:x", urlopen=PagedUrlopen(first, END_PAGE))


def test_search_later_page_server_error_raises():
    with pytest.raises(LoreError, match="HTTP 503"):
        search("stable", "s:x", urlopen=PagedUrlopen(FAILED_PAGE, 503))


def test_search_entry_fields_real_format():
    [e, _] = search("stable", "s:x", urlopen=PagedUrlopen(FAILED_PAGE, END_PAGE))
    assert e.subject == ('FAILED: patch "[PATCH] foo: support reconnect with alternate password'
                         ' for SMB1" failed to apply to 5.4-stable tree')
    assert (e.author, e.updated, e.is_reply) == ("stable-bot@example.org",
                                                 "2025-01-20T13:57:58Z", False)
    assert e.href == "https://lore.kernel.org/stable/2025012032-alpha-beta-0001@stable-bot/"


def test_summary_is_the_text_of_lores_xhtml_content():
    from patchtrail.discover import backport_of

    page = (DATA / "lore-stable-review.atom").read_bytes()
    [e] = search("stable", "s:x", urlopen=PagedUrlopen(page, END_PAGE))
    assert e.is_reply and e.subject.startswith("[PATCH 5.10 1840/1848] drm/msm/dp:")
    assert "\ncommit 1111111111111111111111111111111111111111 upstream.\n" in e.summary
    assert "Link: https://lore.kernel.org/r/1642531648-8448-5-git-send-email" in e.summary
    assert "+++ b/drivers/gpu/drm/msm/dp/dp_ctrl.c" in e.summary and "<" not in e.summary[:40]
    assert backport_of(e.subject, e.summary) == ("5.10", "1111111111111111111111111111111111111111")
    [f, _] = search("stable", "s:x", urlopen=PagedUrlopen(FAILED_PAGE, END_PAGE))
    assert "git cherry-pick -x aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" in f.summary


def test_fake_lore_pages_read_like_real_ones():
    from lorefix import FakeLore, entry

    lore = FakeLore(per_page=2)
    lore.add("stable", r"^f:me@example\.org$", [
        entry(f"m{i}@x", f"[PATCH 6.1.y] fix é {i}", inbox="stable", updated="2026-11-20T09:00:00Z",
              in_reply_to="f@gregkh" if i == 0 else None,
              body=f"commit {'a' * 40} upstream.\n\n+++ b/io.c\nsee https://x.org/{i}\n")
        for i in range(3)])
    got = search("stable", "f:me@example.org", urlopen=lore)
    assert [e.msgid for e in got] == ["m0@x", "m1@x", "m2@x"]
    assert [u.rsplit("&", 1)[-1] for u in lore.urls] == ["x=A", "o=2", "o=3"]
    assert got[0].is_reply and not got[1].is_reply and got[0].subject == "[PATCH 6.1.y] fix é 0"
    assert got[0].summary == f"commit {'a' * 40} upstream.\n\n+++ b/io.c\nsee https://x.org/0\n"
    assert search("stable", "f:other@x", urlopen=lore) == []


def test_fetch_thread_never_passes_an_option_to_b4(tmp_path, monkeypatch):   # final review M3
    fake = tmp_path / "b4"
    fake.write_text("#!/bin/sh\necho ran > %s/ran\nprintf 'From x\\n'\n" % tmp_path)
    fake.chmod(0o755)
    monkeypatch.setenv("PATCHTRAIL_B4", str(fake))
    for bad in ["-oProxyCommand=x@y", "no-at-sign", ""]:
        with pytest.raises(LoreError, match="not a Message-ID"):
            fetch_thread(bad)
    assert not (tmp_path / "ran").exists()


def test_b4_timeout_is_lore_error(monkeypatch):
    def run(*a, **k):
        assert k["timeout"] == 600
        raise subprocess.TimeoutExpired("b4", 600)

    monkeypatch.setattr("patchtrail.sources.lore.subprocess.run", run)
    with pytest.raises(LoreError, match="timed out"):
        fetch_thread("a@b")


def test_b4_missing_is_lore_error(monkeypatch):
    monkeypatch.setattr("patchtrail.sources.lore.subprocess.run", raising(FileNotFoundError("b4")))
    with pytest.raises(LoreError, match="b4"):
        fetch_thread("a@b")
