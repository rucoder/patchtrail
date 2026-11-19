"""Build realistic RFC 5322 mails and mboxrd files for tests."""

import email.header
import re


def _subject(s: str) -> str:
    if s.isascii():
        return s
    return email.header.Header(s, "utf-8").encode()


def make_mail(msgid, *, frm="Me <me@example.org>", subject="[PATCH] fix io",
              date="Wed, 11 Nov 2026 16:27:05 +0000", in_reply_to=None, body="",
              to="list@vger.kernel.org", cc="", extra_headers=None,
              html_only=False) -> bytes:
    headers = {
        "Message-ID": f"<{msgid}>",
        "From": frm,
        "To": to,
        "Subject": _subject(subject),
        "Date": date,
        "MIME-Version": "1.0",
        "Content-Type": "text/plain; charset=utf-8",
    }
    if in_reply_to:
        headers["In-Reply-To"] = f"<{in_reply_to}>"
    if cc:
        headers["Cc"] = cc
    if html_only:
        headers["Content-Type"] = "text/html; charset=utf-8"
        body = f"<html><body><p>{body or 'hello'}</p></body></html>\n"
    headers.update(extra_headers or {})
    m = re.search(r"charset=\"?([\w-]+)", headers["Content-Type"])
    charset = m.group(1) if m else "utf-8"
    head = "".join(f"{k}: {v}\n" for k, v in headers.items())
    return (head + "Content-Transfer-Encoding: 8bit\n\n").encode("ascii") \
        + body.encode(charset)


def mbox(*raws) -> bytes:
    out = b""
    for raw in raws:
        escaped = re.sub(rb"(?m)^(>*From )", rb">\1", raw)
        if not escaped.endswith(b"\n"):
            escaped += b"\n"
        out += b"From mboxrd@z Thu Jan  1 00:00:00 1970\n" + escaped + b"\n"
    return out
