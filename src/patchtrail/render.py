# SPDX-License-Identifier: Apache-2.0
"""Text rendering of patches, their state and their changes. Pure functions of the
database and the state documents; nothing here writes or touches the network."""
import re
import time

from patchtrail import snapshot, store
from patchtrail.mail import MailInfo, head_subject

LORE = "https://lore.kernel.org/all"
SHOW_PREREQS = 8
_EMPTY_FRAGMENT = {"commits": [], "branches": {}, "failed": {}, "hint": None}
_DASH = "–"


def day(t: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(t)) if t else "?"


def day_time(t: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "?"


def link_label(url: str) -> str:
    if m := re.fullmatch(r"https?://github\.com/[^/]+/[^/]+/pull/(\d+)\S*", url):
        return f"PR #{m.group(1)}"
    if m := re.fullmatch(r"https?://gitlab\.[^/]+/\S*/-/merge_requests/(\d+)\S*", url):
        return f"MR !{m.group(1)}"
    if m := re.search(r"/browse/([A-Z][A-Z0-9]*-\d+)", url):
        return m.group(1)
    m = re.match(r"\w+://([^/]+)", url)
    return m.group(1) if m else url


# --- state of one patch -------------------------------------------------------

def current_state(conn, row, mine: frozenset[str]) -> dict:
    """The patch's latest snapshot, or the state a fetch would compose for it now."""
    last = snapshot.latest(conn, row["id"])
    if last is not None:
        return last[2]
    from patchtrail.fetch import compose_for
    return compose_for(conn, row, mine, dict(_EMPTY_FRAGMENT))


def _new_msgids(conn, row, state: dict) -> set[str]:
    ref = snapshot.reference_state(conn, row["id"])
    return set(state["mails"]) - set(ref["mails"]) if ref else set()


def last_activity(conn, row) -> int:
    """The date of the patch's newest mail; 0 with none."""
    return max((m.date for m in store.mail_infos(conn, row["id"])), default=0)


def by_activity(conn, rows) -> list:
    """Most recent activity first, never-fetched patches last."""
    return sorted(rows, key=lambda r: last_activity(conn, r), reverse=True)


def _has_column(conn, table: str, column: str) -> bool:
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def _links(conn, patch_id: int) -> list[str]:
    if not _has_column(conn, "links", "url"):
        return []
    return [r[0] for r in conn.execute(
        "SELECT url FROM links WHERE patch_id=? ORDER BY rowid", (patch_id,))]


def _note(conn, patch) -> str | None:
    if not _has_column(conn, "patches", "note"):
        return None
    return conn.execute("SELECT note FROM patches WHERE id=?", (patch["id"],)).fetchone()[0]


def summary_lines(conn, patch, *, mine: frozenset[str] = frozenset(), width: int | None = None,
                  state: dict | None = None) -> list[str]:
    w = width or len(patch["name"])
    pad = " " * w
    state = state or current_state(conn, patch, mine)
    mails = store.mail_infos(conn, patch["id"])
    newest = store.newest_series(store.revisions(conn, patch["id"]))
    subject = head_subject(mails) or (newest["subject"] if newest else "")
    if not subject and (commits := store.commits(conn, patch["id"])):
        subject = commits[0]["subject"] or ""
    n = len(state["mails"])
    new = len(_new_msgids(conn, patch, state))
    count = f"{n} message{'s' * (n != 1)}" + (f", {new} new" if new else "")
    if newest:
        link = f"{LORE}/{newest['root_msgid']}/"
    else:
        first = store.commits(conn, patch["id"])
        link = f"{first[0]['sha'][:12]} {first[0]['subject'] or ''}".strip() if first else "(no revision)"
    out = [f"{patch['name']:{w}}  {subject}",
           f"{pad}  {patch['project']} · {state['stage']} · {state['standing']['text']} ({count})",
           f"{pad}  {link}"]
    if links := _links(conn, patch["id"]):
        out.append(f"{pad}  links: " + " · ".join(f"{link_label(u)} {u}" for u in links))
    if note := _note(conn, patch):
        out.append(f"{pad}  note: {note}")
    return out


# --- changes ------------------------------------------------------------------

def _val(v) -> str:
    return str(v) if v not in (None, "") else _DASH


def _branch_commit_suffix(sha: str, multi: bool) -> str:
    return f" ({sha})" if multi else ""


def change_line(conn, c: snapshot.Change, *, multi: bool = False,
                state: dict | None = None) -> str:
    """One change as text. multi: the patch has several commits, so branch lines name
    the commit. state: the patch's state, for what a Change does not carry (the URL of
    a FAILED mail, the note of a closed patch)."""
    f = c.field
    if f == "trailers":
        if c.new:
            return "trailers: " + ", ".join(f"+{t}" for t in c.new)
        return "trailers: " + ", ".join(f"-{t}" for t in c.old or [])
    if f == "mail":
        ids = c.new or c.old or []
        sign = "+" if c.new else "-"
        line = f"mail: {sign}{len(ids)}"
        rows = [conn.execute("SELECT from_name, subject, date FROM mails WHERE msgid=?",
                             (i,)).fetchone() for i in ids]
        rows = [r for r in rows if r]
        if c.new and rows:
            r = max(rows, key=lambda r: r["date"])
            line += f" · {r['from_name']}: {r['subject']}"
        return line
    if f.startswith("commit:"):
        sha = f.split(":", 1)[1]
        if "missing" in (c.new or "").split() and "missing" not in (c.old or "").split():
            return f"commit {sha}: dropped from its tree?"
        return f"commit {sha}: {_val((c.old or '').strip())} → {_val((c.new or '').strip())}"
    if f.startswith("branch:"):
        _, series, sha = f.split(":", 2)
        return (f"{series}.y: {_val(c.old)} → {_val(c.new)}"
                + _branch_commit_suffix(sha, multi))
    if f.startswith("failed:"):
        series = f.split(":", 1)[1]
        if c.new is None:
            return f"FAILED mail for {series}.y: gone"
        entry = ((state or {}).get("failed") or {}).get(series) or {}
        return f"FAILED mail for {series}.y: {entry.get('url') or c.new}"
    new = _val(c.new)
    if f == "closed" and c.new and (note := (state or {}).get("closed_note")):
        new += f" ({note})"
    return f"{f}: {_val(c.old)} → {new}"


def _change_lines(conn, patch_id: int, changes, state) -> list[str]:
    multi = len(store.commits(conn, patch_id)) > 1
    return [change_line(conn, c, multi=multi, state=state) for c in changes]


def status_lines(conn, names: list[str], *, mine: frozenset[str] = frozenset()) -> list[str]:
    if names:
        rows = [store.get_patch(conn, n) for n in names]
    else:
        rows = [r for r in store.list_patches(conn, closed=True)
                if snapshot.unread(conn, r["id"])]
    if not rows:
        return ["nothing unread"]
    rows = by_activity(conn, rows)
    width = max(len(r["name"]) for r in rows)
    out: list[str] = []
    for r in rows:
        state = current_state(conn, r, mine)
        out += summary_lines(conn, r, mine=mine, width=width, state=state)
        ref_at, changes = snapshot.since_read(conn, r["id"])
        out.append(f"    since you read it on {day(ref_at)}:" if ref_at is not None
                   else "    not read yet:")
        out += ["      " + line for line in _change_lines(conn, r["id"], changes, state)]
        out.append("")
    return out[:-1]


def history_lines(conn, patch) -> list[str]:
    state = snapshot.latest(conn, patch["id"])
    state = state[2] if state else None
    out = []
    for taken_at, changes in snapshot.history(conn, patch["id"]):
        out.append(day_time(_taken(conn, taken_at)))
        out += ["  " + line for line in _change_lines(conn, patch["id"], changes, state)]
    return out


def _taken(conn, snapshot_id: int) -> int:
    return conn.execute("SELECT taken_at FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()[0]


# --- mails --------------------------------------------------------------------

def describe_mail(m: MailInfo, mine: frozenset[str], unseen: bool = False) -> str:
    tags = sorted({t.split(":", 1)[0] for t in m.tags})
    if m.applied:
        tags.append("APPLIED")
    tags_text = f"  [{', '.join(tags)}]" if tags else ""
    who = "you" if m.from_addr in mine else m.from_name
    return f"  {'*' if unseen else ' '} {day_time(m.date)}  {who}: {m.subject}{tags_text}"


def show_lines(conn, patch, mine: frozenset[str]) -> list[str]:
    state = current_state(conn, patch, mine)
    out = summary_lines(conn, patch, mine=mine, state=state)
    new = _new_msgids(conn, patch, state)
    out += [describe_mail(m, mine, m.msgid in new) for m in store.mail_infos(conn, patch["id"])]
    return out


def trailers_lines(conn, patch, mine: frozenset[str]) -> list[str]:
    out = [f"{patch['name']}:"]
    found = False
    for m in store.mail_infos(conn, patch["id"]):
        if m.is_reply and m.tags:
            found = True
            out.append(f"  {'you' if m.from_addr in mine else m.from_name}: {m.subject}")
            out += [f"      {t}" for t in m.tags]
    if not found:
        out.append("  no review tags yet")
    return out


# --- kernel -------------------------------------------------------------------

def describe_prereq(p: dict) -> str:
    cc, fixes = p.get("cc"), p.get("fixes") or []
    if cc is not None:
        mark = "Cc: stable" + (f" {cc}" if cc else "") + ": may come on its own"
    elif fixes:
        mark = f"Fixes: {fixes[0][:12]}: may come on its own"
    else:
        mark = "not marked for stable"
    return f"{p['sha'][:12]} {p['subject']} ({p.get('tag') or 'not in a release'}, {mark})"


def _series_key(series: str):
    return tuple(int(x) if x.isdigit() else 0 for x in series.split("."))


def _branch_text(e: dict) -> list[str]:
    st = e["state"]
    if st == "not_affected":
        return ["not affected: " + (e.get("detail") or [""])[0]]
    simple = {"in_branch": "has it, not released yet", "skipped": "won't backport",
              "backport_sent": "backport sent", "not_fetched": "not fetched"}
    if st == "released":
        return [f"has it: {e.get('tag')}"]
    if st in simple:
        return [simple[st]]
    return list(e.get("detail") or []) or [st.replace("_", " ")]


def _mainline(c: dict) -> list[str]:
    where = c["where"]
    if where == "mainline":
        out = [f"    mainline: {c.get('release') or 'yes, after the last tag'}"]
        if c.get("cc") is None and not c["fixes"]:
            out.append("    not tagged for stable: ask stable@vger.kernel.org "
                       "for the branches below")
        return out
    if where == "next":
        return ["    mainline: only in linux-next; stable takes nothing before it "
                "reaches mainline"]
    if where.startswith("tree:"):
        return [f"    mainline: only in {where[5:]}; stable takes nothing before it "
                "reaches mainline"]
    return ["    mainline: not yet; stable takes nothing before it reaches mainline"]


def kernel_lines(state: dict, *, verbose: bool = False) -> list[str]:
    out: list[str] = []
    commits = state["commits"]
    for c in commits:
        if len(commits) > 1:
            out.append(f"    {c['sha'][:12]} {c['subject']}")
        if c["where"] == "missing":
            out.append("    not in the repository")
        tags = [f"Fixes: {f['sha'][:12]} ({f.get('release') or 'not released'})" if f["known"]
                else f"Fixes: {f['sha']} (unknown commit)" for f in c["fixes"]]
        tags.append("no Cc: stable" if c.get("cc") is None
                    else "Cc: stable" + (f" {c['cc']}" if c["cc"] else ""))
        out.append("    " + "   ".join(tags))
        if c["where"] != "missing":
            out += _mainline(c)
        for series in sorted(state["branches"], key=_series_key, reverse=True):
            e = state["branches"][series].get(c["sha"][:12])
            if e is None:
                continue
            text = _branch_text(e)
            out.append(f"    {series + '.y':<8}{text[0]}")
            rest = [f"{'':<8}{t}" for t in text[1:]]
            prereqs = e.get("prereqs") or []
            if prereqs:
                shown = prereqs if verbose else prereqs[:SHOW_PREREQS]
                rest.insert(0, f"{'':<8}the conflicting lines come from:")
                rest[1:1] = [f"{'':<8}  " + describe_prereq(p) for p in shown]
                if len(prereqs) > len(shown):
                    rest.insert(1 + len(shown),
                                f"{'':<8}  ... {len(prereqs) - len(shown)} more (-v)")
            out += ["    " + t for t in rest]
    if state.get("hint"):
        out.append(f"    {state['hint']}")
    failed = state.get("failed") or {}
    if commits and failed:
        out.append("    FAILED mails from stable (send a backport in reply):")
        out += [f"      {s}: {d['date']} {d['url']}" for s, d in sorted(failed.items())]
    return out
