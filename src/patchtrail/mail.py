# SPDX-License-Identifier: Apache-2.0
"""Parse mail and work out where a thread stands. Port of the mail half of lkml-watch."""

import email
import email.header
import email.utils
import re
import time
from dataclasses import dataclass

REVIEW_TAG = re.compile(
    r"^(Reviewed-by|Acked-by|Tested-by|Nacked-by|Reported-by|Suggested-by):",
    re.IGNORECASE)
_MAINTAINER_TAG = re.compile(r"(Reviewed|Acked|Tested)-by:", re.IGNORECASE)
_THANKS_ITEM = re.compile(r"^\s*\[\d+/\d+\]\s+(.+?)\s*$")
_THANKS_SHA = re.compile(
    r"^\s+(?:commit:\s*|\S*/commit/)([0-9a-f]{12,40})\s*$", re.IGNORECASE)
_PATCH_N_OF_M = re.compile(r"\s[1-9]\d*/\d+\]")


def split_mbox(data: bytes) -> list[bytes]:
    """Raw messages of an mboxrd: split on From_ lines, undo the >From quoting."""
    raws: list[bytes] = []
    cur: list[bytes] | None = None
    for line in data.splitlines(keepends=True):
        if line.startswith(b"From ") and (cur is None or not cur or cur[-1].strip() == b""):
            if cur is not None:
                raws.append(_finish(cur))
            cur = []
            continue
        if cur is not None:
            cur.append(re.sub(rb"^>(>*From )", rb"\1", line))
    if cur is not None:
        raws.append(_finish(cur))
    return raws


def _finish(lines: list[bytes]) -> bytes:
    while lines and lines[-1] in (b"\n", b"\r\n"):
        lines.pop()
    return b"".join(lines)


def _decode_words(value: str) -> str:
    try:
        value = str(email.header.make_header(email.header.decode_header(value)))
    except Exception:
        pass
    return " ".join(value.split())


def _header(msg, field: str) -> str:
    value = msg.get(field)
    if value is None:
        return ""
    try:
        value = str(email.header.make_header(email.header.decode_header(str(value))))
    except Exception:
        value = str(value)
    return " ".join(value.split())


def _decode(payload: bytes, charset: str | None) -> str:
    try:
        return payload.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _leaves(msg):
    return [p for p in msg.walk() if not p.is_multipart()]


def text_body(raw: bytes) -> tuple[str, int]:
    """The text/plain parts, decoded, and how many other parts were left out."""
    msg = email.message_from_bytes(raw)
    texts, omitted = [], 0
    for part in _leaves(msg):
        if part.get_content_type() != "text/plain":
            omitted += 1
            continue
        texts.append(_decode(part.get_payload(decode=True) or b"", part.get_content_charset()))
    return "".join(texts), omitted


@dataclass(frozen=True)
class MailInfo:
    msgid: str
    in_reply_to: str | None
    date: int
    from_name: str
    from_addr: str
    subject: str
    is_reply: bool
    tags: tuple[str, ...]
    applied: bool
    applied_commits: tuple[tuple[str, str], ...]
    change_id: str | None
    to_cc: tuple[str, ...]


def _thanks_commits(lines: list[str]) -> tuple[tuple[str, str], ...]:
    out = []
    for i, line in enumerate(lines):
        m = _THANKS_ITEM.match(line)
        if not m:
            continue
        nxt = next((l for l in lines[i + 1:] if l.strip()), "")
        s = _THANKS_SHA.match(nxt)
        if s:
            out.append((m.group(1), s.group(1)))
    return tuple(out)


def parse_mail(raw: bytes) -> MailInfo:
    msg = email.message_from_bytes(raw)
    try:
        date = int(email.utils.parsedate_to_datetime(msg["Date"]).timestamp())
    except Exception:
        date = 0
    name, addr = email.utils.parseaddr(str(msg.get("From") or ""))
    name = _decode_words(name)
    subject = _header(msg, "Subject")
    is_reply = subject.lower().startswith("re:")
    lines = text_body(raw)[0].splitlines()
    change_id = None
    for l in lines:
        if l.lower().startswith("change-id: "):
            change_id = l[len("change-id: "):].strip() or None
            break
    irt = _header(msg, "In-Reply-To").strip("<>")
    recipients = email.utils.getaddresses(
        [str(v) for v in msg.get_all("To", []) + msg.get_all("Cc", [])])
    return MailInfo(
        msgid=_header(msg, "Message-ID").strip("<>"),
        in_reply_to=irt or None,
        date=date,
        from_name=name or addr,
        from_addr=addr.lower(),
        subject=subject,
        is_reply=is_reply,
        tags=tuple(l.strip() for l in lines if is_reply and REVIEW_TAG.match(l)),
        applied=is_reply and any(l.startswith("Applied") for l in lines),
        applied_commits=_thanks_commits(lines) if is_reply else (),
        change_id=change_id,
        to_cc=tuple(a.lower() for _, a in recipients if a),
    )


def _day(t: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(t)) if t else "?"


@dataclass(frozen=True)
class Standing:
    kind: str
    who: str = ""
    since: int = 0
    tags: tuple[str, ...] = ()

    def text(self) -> str:
        if self.kind == "none":
            return "not fetched yet"
        if self.kind == "applied":
            return f"APPLIED by {self.who}, {_day(self.since)}"
        state = {
            "waiting_reply": f"waiting for a reply since {_day(self.since)}",
            "waiting_maintainer": f"waiting for the maintainer since {_day(self.since)}",
            "your_turn": f"{self.who} replied {_day(self.since)}: your turn",
            "new_reply": f"{self.who} replied {_day(self.since)}",
        }[self.kind]
        return "; ".join([*self.tags, state])


def standing(mails: list[MailInfo], mine: frozenset[str], *, following: bool = False) -> Standing:
    """Where a thread stands, from its mails (sorted by date here; ties keep order)."""
    if not mails:
        return Standing("none")
    mails = sorted(mails, key=lambda m: m.date)
    others = [m for m in mails if m.is_reply and m.from_addr not in mine]
    applied = [m for m in others if m.applied]
    if applied:
        m = applied[-1]
        return Standing("applied", m.from_name, m.date)
    tags: list[str] = []
    for m in others:
        for t in m.tags:
            tag, person = t.split(":", 1)
            person = email.utils.parseaddr(person)[0] or person.strip()
            if f"{tag} {person}" not in tags:
                tags.append(f"{tag} {person}")
    last = mails[-1]
    if last.from_addr in mine:
        kind = "waiting_reply"
    elif following:
        kind = "new_reply"
    elif any(_MAINTAINER_TAG.match(t) for t in last.tags):
        kind = "waiting_maintainer"
    else:
        kind = "your_turn"
    return Standing(kind, last.from_name, last.date, tuple(tags))


def head_subject(mails: list[MailInfo]) -> str:
    """The latest revision's cover letter or lone patch, not patch N/M of it."""
    if not mails:
        return ""
    patches = [m for m in mails if not m.is_reply] or mails
    heads = [m for m in patches if not _PATCH_N_OF_M.search(m.subject)] or patches
    return heads[-1].subject
