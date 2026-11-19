# SPDX-License-Identifier: Apache-2.0
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from patchtrail import __version__
from patchtrail.mail import split_mbox
from patchtrail.sources.base import Source

LORE = "https://lore.kernel.org"
NS = {"a": "http://www.w3.org/2005/Atom",
      "thr": "http://purl.org/syndication/thread/1.0"}


class LoreError(Exception):
    pass


@dataclass(frozen=True)
class Entry:
    msgid: str
    subject: str
    author: str
    updated: str
    is_reply: bool
    href: str
    summary: str = ""


def parse_msgid(arg: str) -> str:
    """A Message-ID with or without <>, or a lore URL holding one."""
    m = re.match(r"https?://[^/]+/[^/]+/([^/]+)", arg)
    if m:
        arg = urllib.parse.unquote(m.group(1))
    return arg.strip().removeprefix("<").removesuffix(">")


def b4_path() -> str:
    env = os.environ.get("PATCHTRAIL_B4")
    if env:
        return env
    beside = Path(sys.executable).parent / "b4"
    if beside.exists():
        return str(beside)
    found = shutil.which("b4")
    if found:
        return found
    raise LoreError("b4 not found")


def fetch_thread(msgid: str) -> bytes:
    r = subprocess.run([b4_path(), "-q", "mbox", "-C", "-o", "-", msgid],
                       capture_output=True)
    if r.returncode != 0 or not r.stdout.startswith(b"From "):
        err = r.stderr.decode(errors="replace").strip().splitlines()
        raise LoreError(err[-1] if err else "not on lore yet?")
    return r.stdout


def _parse_feed(data: bytes) -> list[Entry]:
    entries = []
    for e in ET.fromstring(data).findall("a:entry", NS):
        subject = " ".join(e.findtext("a:title", "", NS).split())
        link = e.find("a:link", NS)
        href = link.get("href", "") if link is not None else ""
        entries.append(Entry(
            msgid=parse_msgid(href),
            subject=subject,
            author=e.findtext("a:author/a:email", "", NS).strip().lower(),
            updated=e.findtext("a:updated", "", NS),
            is_reply=e.find("thr:in-reply-to", NS) is not None
            or subject.lower().startswith("re:"),
            href=href,
            summary=e.findtext("a:content", "", NS),
        ))
    return entries


def search(inbox: str, query: str, *, urlopen=None) -> list[Entry]:
    """All Atom search results for query, following pages until none is new."""
    base = f"{LORE}/{inbox}/?q={urllib.parse.quote(query)}&x=A"
    headers = {"User-Agent": f"patchtrail/{__version__}"}
    entries: list[Entry] = []
    seen: set[str] = set()
    fetched = 0
    while True:
        url = base + (f"&o={fetched}" if fetched else "")
        opener = urlopen or urllib.request.urlopen
        try:
            with opener(urllib.request.Request(url, headers=headers),
                        timeout=60) as r:
                page = _parse_feed(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404 and not fetched:
                return []
            raise LoreError(f"lore search failed: HTTP {e.code}") from e
        except (urllib.error.URLError, OSError, ET.ParseError) as e:
            raise LoreError(f"lore search failed: {e}") from e
        new = [e for e in page if e.msgid not in seen]
        if not new:
            return entries
        seen.update(e.msgid for e in new)
        entries.extend(new)
        fetched += len(page)


class LoreSource(Source):
    def __init__(self, urlopen=None):
        self._urlopen = urlopen

    def fetch(self, root_msgid: str) -> list[bytes]:
        return split_mbox(fetch_thread(root_msgid))

    def discover(self, addresses: list[str], since: int | None) -> list[Entry]:
        date = ""
        if since is not None:
            day = datetime.fromtimestamp(since, timezone.utc) - timedelta(days=2)
            date = f" AND d:{day:%Y%m%d}.."
        found: dict[str, Entry] = {}
        for addr in addresses:
            for e in search("all", f"f:{addr} AND s:PATCH{date}",
                            urlopen=self._urlopen):
                if not e.is_reply:
                    found.setdefault(e.msgid, e)
        return list(found.values())
