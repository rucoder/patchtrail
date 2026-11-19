"""State snapshots, diffs between them, and the read/unread reference."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from patchtrail.mail import MailInfo, Standing
from patchtrail.projects import STAGES, Project

_DONE_BRANCH = {"released", "not_affected", "skipped"}


def stage_of(project: Project, standing: Standing, trailers: list[str], commits: list[dict],
             manual_applied: bool) -> str:
    n = 0                                            # index into STAGES
    if trailers:
        n = 1
    if standing.kind == "applied" or commits or manual_applied:
        n = 2
    if manual_applied or (commits and all(c["stage"] in ("applied", "released") for c in commits)):
        n = 3
    if commits and all(c["stage"] == "released" for c in commits):
        n = 4
        if any(c.get("stable") for c in commits):
            n = 5
    allowed = [s for s in project.stages if STAGES.index(s) <= n]
    return allowed[-1] if allowed else project.stages[0]


def compose_state(*, project: Project, standing: Standing, mails: list[MailInfo],
                  fragment: dict, manual_applied: bool, closed: str | None,
                  closed_note: str | None) -> dict:
    trailers = sorted(set(standing.tags))
    commits = list(fragment.get("commits", []))
    branches = fragment.get("branches", {})
    stage = stage_of(project, standing, trailers, commits, manual_applied)
    all_branches_done = all(e["state"] in _DONE_BRANCH
                            for per in branches.values() for e in per.values())
    finished = ((stage == project.stages[-1] and all_branches_done)
                or (stage == "released" and not any(c.get("stable") for c in commits)))
    return {
        "stage": stage,
        "closed": closed,
        "closed_note": closed_note,
        "standing": {"kind": standing.kind, "who": standing.who, "since": standing.since,
                     "text": standing.text()},
        "trailers": trailers,
        "mails": sorted(m.msgid for m in mails),
        "commits": commits,
        "branches": branches,
        "failed": fragment.get("failed", {}),
        "hint": fragment.get("hint"),
        "finished": finished,
    }


def flag_view(state: dict) -> dict:
    return {
        "stage": state["stage"],
        "closed": state["closed"],
        "standing": [state["standing"]["kind"], state["standing"]["who"]],
        "trailers": state["trailers"],
        "mails": state["mails"],
        "commits": {c["sha"][:12]: [c["stage"], c.get("release"), c.get("where") == "missing"]
                    for c in state["commits"]},
        "branches": {s: {sha: [e["state"], e.get("tag")] for sha, e in per.items()}
                     for s, per in state["branches"].items()},
        "failed": sorted(state["failed"]),
    }


def _dump(state: dict) -> str:
    return json.dumps(state, sort_keys=True)


def record(conn, patch_id: int, state: dict, now: int) -> int | None:
    last = latest(conn, patch_id)
    if last is not None and _dump(last[2]) == _dump(state):
        return None
    cur = conn.execute("INSERT INTO snapshots(patch_id, taken_at, state) VALUES (?,?,?)",
                       (patch_id, now, _dump(state)))
    new_id = cur.lastrowid
    if last is None:
        conn.execute("UPDATE patches SET read_snapshot_id=?, read_on_first_snapshot=0 "
                     "WHERE id=? AND read_on_first_snapshot=1", (new_id, patch_id))
    return new_id


def latest(conn, patch_id: int) -> tuple[int, int, dict] | None:
    row = conn.execute("SELECT id, taken_at, state FROM snapshots WHERE patch_id=? "
                       "ORDER BY id DESC LIMIT 1", (patch_id,)).fetchone()
    return (row[0], row[1], json.loads(row[2])) if row else None


@dataclass(frozen=True)
class Change:
    field: str
    old: Any
    new: Any
    flags: bool


def _commit_text(c: dict) -> str:
    text = f"{c['stage']} {c.get('release') or ''}"
    return text + " missing" if c.get("where") == "missing" else text


def _branch_text(e: dict) -> str:
    return f"{e['state']} {e.get('tag') or ''}".strip()


def changes(old: dict | None, new: dict) -> list[Change]:
    if old is None:
        return []
    out: list[Change] = []
    fo, fn = flag_view(old), flag_view(new)
    if old["stage"] != new["stage"]:
        out.append(Change("stage", old["stage"], new["stage"], True))
    if old["closed"] != new["closed"]:
        out.append(Change("closed", old["closed"], new["closed"], True))
    so, sn = old["standing"], new["standing"]
    if fo["standing"] != fn["standing"] or so["text"] != sn["text"]:
        out.append(Change("standing", so["text"], sn["text"], fo["standing"] != fn["standing"]))
    for key, field in (("trailers", "trailers"), ("mails", "mail")):
        added = sorted(set(new[key]) - set(old[key]))
        removed = sorted(set(old[key]) - set(new[key]))
        if added:
            out.append(Change(field, None, added, True))
        elif removed:
            out.append(Change(field, removed, None, True))
    co = {c["sha"][:12]: c for c in old["commits"]}
    cn = {c["sha"][:12]: c for c in new["commits"]}
    for sha in sorted(set(co) | set(cn)):
        if fo["commits"].get(sha) != fn["commits"].get(sha):
            out.append(Change(f"commit:{sha}", _commit_text(co[sha]) if sha in co else None,
                              _commit_text(cn[sha]) if sha in cn else None, True))
    for series in sorted(set(old["branches"]) | set(new["branches"])):
        bo, bn = old["branches"].get(series, {}), new["branches"].get(series, {})
        for sha in sorted(set(bo) | set(bn)):
            eo, en = bo.get(sha), bn.get(sha)
            if eo == en:
                continue
            flags = (eo and [eo["state"], eo.get("tag")]) != (en and [en["state"], en.get("tag")])
            if flags:
                o = _branch_text(eo) if eo else None
                n = _branch_text(en) if en else None
            else:
                o, n = "; ".join(eo.get("detail") or []), "; ".join(en.get("detail") or [])
            out.append(Change(f"branch:{series}:{sha}", o, n, flags))
    for series in sorted(set(old["failed"]) | set(new["failed"])):
        eo, en = old["failed"].get(series), new["failed"].get(series)
        if eo != en:
            out.append(Change(f"failed:{series}", eo and eo.get("date"), en and en.get("date"),
                              (eo is None) != (en is None)))
    return out


def _state_by_id(conn, snap_id) -> tuple[int, dict] | None:
    if snap_id is None:
        return None
    row = conn.execute("SELECT taken_at, state FROM snapshots WHERE id=?", (snap_id,)).fetchone()
    return (row[0], json.loads(row[1])) if row else None


def _reference(conn, patch_id):
    row = conn.execute("SELECT read_snapshot_id FROM patches WHERE id=?", (patch_id,)).fetchone()
    return _state_by_id(conn, row[0]) if row else None


def unread(conn, patch_id: int) -> bool:
    if conn.execute("SELECT flagged FROM patches WHERE id=?", (patch_id,)).fetchone()[0]:
        return True
    last = latest(conn, patch_id)
    if last is None:
        return False
    ref = _reference(conn, patch_id)
    return ref is None or flag_view(last[2]) != flag_view(ref[1])


def since_read(conn, patch_id: int) -> tuple[int | None, list[Change]]:
    ref = _reference(conn, patch_id)
    last = latest(conn, patch_id)
    if ref is None or last is None:
        return (ref[0] if ref else None), []
    return ref[0], changes(ref[1], last[2])


def mark_read(conn, patch_id: int) -> None:
    last = latest(conn, patch_id)
    conn.execute("UPDATE patches SET prev_read_snapshot_id=read_snapshot_id, "
                 "read_snapshot_id=COALESCE(?, read_snapshot_id), flagged=0 WHERE id=?",
                 (last[0] if last else None, patch_id))


def mark_unread(conn, patch_id: int) -> None:
    conn.execute("UPDATE patches SET read_snapshot_id=COALESCE(prev_read_snapshot_id, "
                 "read_snapshot_id), flagged=1 WHERE id=?", (patch_id,))


def history(conn, patch_id: int) -> list[tuple[int, list[Change]]]:
    rows = conn.execute("SELECT id, state FROM snapshots WHERE patch_id=? ORDER BY id",
                        (patch_id,)).fetchall()
    out, prev = [], None
    for sid, raw in rows:
        state = json.loads(raw)
        out.append((sid, changes(prev, state)))
        prev = state
    return out[::-1]
