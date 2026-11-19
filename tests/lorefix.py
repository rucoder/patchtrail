# SPDX-License-Identifier: Apache-2.0
"""lore.kernel.org's Atom search pages, written the way lore writes them (compare
tests/data/lore-*.atom, real pages): us-ascii, attributes on their own lines,
the body as xhtml <div><pre> with nested elements, and the bare `</feed>` that
lore answers with past the last result."""

import re
import urllib.error
import urllib.parse
import uuid

LORE = "https://lore.kernel.org"
END = b"</feed>"


def _esc(text: str) -> str:
    text = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&#34;").replace("'", "&#39;"))
    return "".join(c if ord(c) < 128 else f"&#{ord(c)};" for c in text)


def _uuid(seed: str) -> str:
    return f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, seed)}"


def _body(text: str) -> str:
    """lore marks diff lines up with spans and links with <a>."""
    out = []
    for line in _esc(text).splitlines(keepends=True):
        if line.startswith(("diff --git", "--- a/", "+++ b/")):
            line = f'<span\nclass="head">{line}</span>'
        elif line.startswith("+") and not line.startswith("+++"):
            line = f'<span\nclass="add">{line}</span>'
        line = re.sub(r"(https://\S+)", r'<a\nhref="\1">\1</a>', line)
        out.append(line)
    return "".join(out)


def entry(msgid: str, subject: str, *, updated: str, inbox: str = "all",
          author: tuple[str, str] = ("Me", "me@example.org"), in_reply_to: str | None = None,
          body: str = "") -> str:
    title = _esc(subject)
    title_tag = "<title\ntype=\"html\">" if title != subject else "<title>"
    reply = (f'<thr:in-reply-to\nref="{_uuid(in_reply_to)}"\n'
             f'href="{LORE}/{inbox}/{in_reply_to}/"/>' if in_reply_to else "")
    return (f"<entry><author><name>{_esc(author[0])}</name><email>{author[1]}</email></author>"
            f"{title_tag}{title}</title><updated>{updated}</updated><link\n"
            f'href="{LORE}/{inbox}/{msgid}/"/><id>{_uuid(msgid)}</id>{reply}<content\n'
            'type="xhtml"><div\nxmlns="http://www.w3.org/1999/xhtml"><pre\n'
            f'style="white-space:pre-wrap">{_body(body)}</pre></div></content></entry>')


def page(inbox: str, query: str, entries: list[str]) -> bytes:
    q = urllib.parse.quote_plus(query, safe=":")
    head = ('<?xml version="1.0" encoding="us-ascii"?>\n<feed\n'
            'xmlns="http://www.w3.org/2005/Atom"\n'
            'xmlns:thr="http://purl.org/syndication/thread/1.0">'
            f"<title>{_esc(query)} - search results</title><link\nrel=\"alternate\"\n"
            f'type="text/html"\nhref="{LORE}/{inbox}/?q={q}"/><link\nrel="self"\n'
            f'href="{LORE}/{inbox}/?q={q}&amp;x=A"/><id>{_uuid(inbox + query)}</id>'
            "<updated>2026-11-19T17:15:45Z</updated>")
    return (head + "".join(entries) + "</feed>").encode("ascii")


class _Resp:
    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeLore:
    """urlopen for lore's search: the queries it knows answer their entries,
    `per_page` at a time, then `</feed>`; any other query answers 404."""

    def __init__(self, per_page: int = 2):
        self.per_page = per_page
        self.results: list[tuple[str, str, list[str]]] = []   # (inbox, query pattern, entries)
        self.urls: list[str] = []

    def add(self, inbox: str, pattern: str, entries: list[str]) -> None:
        """Answer queries on inbox matching the regex pattern with entries."""
        self.results.append((inbox, pattern, entries))

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.urls.append(url)
        assert req.headers.get("User-agent", "").startswith("patchtrail/"), url
        m = re.match(rf"{re.escape(LORE)}/([^/]+)/\?(.*)$", url)
        inbox, qs = m.group(1), urllib.parse.parse_qs(m.group(2))
        query, offset = qs["q"][0], int(qs.get("o", ["0"])[0])
        for box, pattern, entries in self.results:
            if box == inbox and re.search(pattern, query) and entries:
                if offset >= len(entries):
                    return _Resp(END)
                return _Resp(page(inbox, query, entries[offset:offset + self.per_page]))
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
