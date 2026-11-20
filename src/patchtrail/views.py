# SPDX-License-Identifier: Apache-2.0
"""The API's JSON: pure functions of the database, shaped as the API contract says.
Nothing here writes. Cards never parse mail; detail and mails may."""
import time

from patchtrail import render, snapshot, store
from patchtrail.config import Config
from patchtrail.mail import text_body
from patchtrail.projects import get_project

_TONE = {"released": "ok", "in_branch": "ok", "queued": "ok", "applies": "ok",
         "applies_after_queue": "warn", "backport_sent": "warn", "conflict": "bad",
         "not_affected": "na", "skipped": "na", "not_fetched": "na"}
_RANK = {"na": 0, "ok": 1, "warn": 2, "bad": 3}
_SETTLED = {"released", "not_affected", "skipped"}
_NO_STANDING = {"kind": "none", "who": "", "since": 0, "text": "not fetched yet"}


def tone(state: str) -> str:
    return _TONE.get(state, "na")


# --- status and runs ----------------------------------------------------------

def run_dict(row) -> dict:
    return {k: row[k] for k in ("id", "trigger", "started_at", "finished_at", "status",
                                "phase", "step", "steps", "error")}


def next_fetch_at(conn, interval_s: float, now: int) -> int:
    """The newest full run's start plus the interval, whatever its trigger or status.
    A partial run (`ptl add`, POST /api/patches, `ptl fetch NAME`) does not postpone it."""
    run = conn.execute("SELECT started_at FROM runs WHERE full=1 ORDER BY id DESC LIMIT 1"
                       ).fetchone()
    return int(run["started_at"] + interval_s) if run else now


def status(conn, *, interval_hours: float, now: int, starting: bool, version: str) -> dict:
    """last_run is the newest ok full run (the page's "fetched"). error is the newest full
    run that failed, or was interrupted for a reason (killed, crashed, stopped with the
    service), when no ok full run came after it; a ^C leaves no reason and no error."""
    one = lambda sql: conn.execute(sql).fetchone()          # noqa: E731
    running = one("SELECT * FROM runs WHERE status='running' ORDER BY id DESC LIMIT 1")
    done = one("SELECT * FROM runs WHERE full=1 AND status='ok' ORDER BY id DESC LIMIT 1")
    bad = one("SELECT * FROM runs WHERE full=1 AND (status='failed' OR "
              "(status='interrupted' AND error IS NOT NULL)) AND id > "
              "COALESCE((SELECT MAX(id) FROM runs WHERE full=1 AND status='ok'), 0) "
              "ORDER BY id DESC LIMIT 1")
    return {
        "version": version, "now": now, "interval_hours": interval_hours,
        "next_fetch_at": next_fetch_at(conn, interval_hours * 3600, now),
        "running": run_dict(running) if running else None,
        "starting": starting,
        "last_run": run_dict(done) if done else None,
        "error": ({"run_id": bad["id"], "at": bad["finished_at"] or bad["started_at"],
                   "error": bad["error"] or "", "status": bad["status"]} if bad else None),
    }


def run_log(conn, run_id: int, after: int) -> dict | None:
    if conn.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone() is None:
        return None
    rows = conn.execute("SELECT rowid, at, line FROM run_log WHERE run_id=? AND rowid>? "
                        "ORDER BY rowid", (run_id, after)).fetchall()
    return {"lines": [{"n": r[0], "at": r[1], "line": r[2]} for r in rows]}


# --- cards --------------------------------------------------------------------

def _series_key(series: str):
    return tuple(int(x) if x.isdigit() else 0 for x in series.split("."))


def _pills(state: dict) -> list[dict]:
    worst: dict[str, tuple[str, str]] = {}
    for series, per in state["branches"].items():
        for e in per.values():
            t = tone(e["state"])
            if series not in worst or _RANK[t] > _RANK[worst[series][1]]:
                worst[series] = (e["state"], t)
    for series in state["failed"]:
        if worst.get(series, ("", ""))[1] != "bad":
            worst[series] = ("failed", "bad")
    return [{"series": s, "state": worst[s][0], "tone": worst[s][1]}
            for s in sorted(worst, key=_series_key, reverse=True)]


def _finished_at(conn, patch_id: int) -> int | None:
    """When the newest unbroken run of finished snapshots began."""
    start = None
    for taken, fin in conn.execute("SELECT taken_at, json_extract(state, '$.finished') "
                                   "FROM snapshots WHERE patch_id=? ORDER BY id DESC",
                                   (patch_id,)):
        if not fin:
            break
        start = taken
    return start


def card(conn, row, mine, *, now: int, idle_days: int) -> dict:
    pid = row["id"]
    stages = list(get_project(row["project"]).stages)
    last = snapshot.latest(conn, pid)
    state = last[2] if last else None
    revs = store.revisions(conn, pid)
    newest = store.newest_series(revs)
    standing = state["standing"] if state else dict(_NO_STANDING)
    dates = [m["date"] for m in store.patch_mails(conn, pid)]
    newest_mail = max(dates, default=0)
    finished = bool(state and state["finished"])
    has_commit = bool(store.commits(conn, pid) or (state and state["commits"]))
    _, changes = snapshot.since_read(conn, pid)
    return {
        "name": row["name"], "project": row["project"], "relation": row["relation"],
        "subject": store.display_subject(conn, pid),
        "stage": state["stage"] if state else stages[0], "stages": stages,
        "closed": row["closed"], "closed_note": row["closed_note"],
        "hidden": bool(row["hidden"]),
        "standing": standing, "your_turn": standing["kind"] == "your_turn",
        "unread": snapshot.unread(conn, pid),
        "unread_changes": sum(1 for c in changes if c.flags),
        "links": [{"url": u, "label": render.link_label(u)} for u in store.links(conn, pid)],
        "note": row["note"],
        "pills": _pills(state) if state else [],
        "finished": finished, "finished_at": _finished_at(conn, pid) if finished else None,
        "idle": (row["closed"] is None and not finished and not has_commit
                 and bool(dates) and newest_mail < now - idle_days * 86400),
        "last_activity": newest_mail,
        "version": newest["version"] if newest else 1,
        "fetched": last is not None,
    }


def cards(conn, mine, *, now: int, idle_days: int) -> list[dict]:
    return [card(conn, r, mine, now=now, idle_days=idle_days)
            for r in store.list_patches(conn, hidden=True, closed=True)]


# --- detail -------------------------------------------------------------------

def _changes_t(conn, changes, state) -> list[dict]:
    multi = len(state["commits"]) > 1 if state else False
    return [{"field": c.field, "text": render.change_line(conn, c, multi=multi, state=state),
             "flags": c.flags} for c in changes]


def _applied_note(commits: list[dict]) -> str:
    live = [c for c in commits if c["where"] != "missing"]
    if live and live[-1]["where"] == "upstream":
        return "applied upstream" if live[-1]["stage"] in ("applied", "released") \
            else "mainline: not yet"
    return "mainline: " + render.mainline_phrase(live[-1], branch_only=True) if live \
        else "mainline: not yet"


def _steps(conn, row, state, stages, revs) -> list[dict]:
    pid = row["id"]
    seen = {r[0] for r in conn.execute(
        "SELECT json_extract(state, '$.stage') FROM snapshots WHERE patch_id=?", (pid,))}
    seen.add(state["stage"] if state else stages[0])
    cur = stages.index(state["stage"]) if state and state["stage"] in stages else 0
    taken = [(stages.index(s), t) for s, t in conn.execute(
        "SELECT json_extract(state, '$.stage'), taken_at FROM snapshots WHERE patch_id=? "
        "ORDER BY id", (pid,)) if s in stages]
    series = [r for r in revs if r["kind"] == "series"]
    commits = state["commits"] if state else []
    settled = [e["state"] in _SETTLED for per in (state["branches"] if state else {}).values()
               for e in per.values()]
    notes = {
        "accepted": row["tree_branch"],
        "applied": _applied_note(commits),
        "released": commits[-1].get("release") if commits else None,
        "backports": f"{sum(settled)} of {len(settled)} branches settled" if settled else None,
    }
    out = []
    for i, s in enumerate(stages):
        done = s in seen
        at = None
        if done:
            at = (series[0]["posted_at"] if series else None) if s == "submitted" else next(
                (t for n, t in taken if n >= i), None)
        out.append({"stage": s, "state": "done" if done else "skipped" if cur > i else "todo",
                    "at": at, "note": notes.get(s)})
    return out


def _branches(conn, row, state) -> list[dict]:
    per_series = state["branches"] if state else {}
    skips = store.skips(conn, row["id"])
    out = []
    for series in sorted(set(per_series) | skips, key=_series_key, reverse=True):
        rows = [{"sha": sha, "state": e["state"], "tag": e.get("tag"), "tone": tone(e["state"]),
                 "detail": list(e.get("detail") or []),
                 "prereqs": [{"sha": p["sha"], "subject": p["subject"], "tag": p.get("tag"),
                              "stable": p.get("cc") is not None or bool(p.get("fixes")),
                              "text": render.describe_prereq(p)}
                             for p in e.get("prereqs") or []]}
                for sha, e in per_series.get(series, {}).items()]
        out.append({"series": series, "skipped": series in skips, "rows": rows})
    return out


def detail(conn, row, mine, *, now: int | None = None,
           idle_days: int = Config.idle_days) -> dict:
    """The card plus everything the patch page shows. now defaults to the clock."""
    pid = row["id"]
    last = snapshot.latest(conn, pid)
    state = last[2] if last else None
    revs = store.revisions(conn, pid)
    newest = store.newest_series(revs)
    ref_at, changes = snapshot.since_read(conn, pid)
    taken = dict(conn.execute("SELECT id, taken_at FROM snapshots WHERE patch_id=?", (pid,)))
    out = card(conn, row, mine, now=int(time.time()) if now is None else now,
               idle_days=idle_days)
    out.update({
        "lore_url": f"{render.LORE}/{newest['root_msgid']}/" if newest else None,
        "revisions": [{"version": r["version"], "msgid": r["root_msgid"], "subject": r["subject"],
                       "posted_at": r["posted_at"], "kind": r["kind"], "branch": r["branch"]}
                      for r in revs],
        "steps": _steps(conn, row, state, out["stages"], revs),
        "since": {"at": ref_at, "changes": _changes_t(conn, changes, state)},
        "commits": [{"sha": c["sha"], "subject": c["subject"], "where": c.get("where"),
                     "stage": c["stage"], "release": c.get("release"), "cc": c.get("cc"),
                     "fixes": [{"sha": f["sha"], "release": f.get("release"),
                                "known": f["known"]} for f in c["fixes"]]}
                    for c in (state["commits"] if state else [])],
        "branches": _branches(conn, row, state),
        "failed": [{"series": s, "date": d["date"], "url": d["url"]}
                   for s, d in sorted((state["failed"] if state else {}).items(),
                                      key=lambda kv: _series_key(kv[0]), reverse=True)],
        "hint": state["hint"] if state else None,
        "history": [{"at": taken[sid], "changes": _changes_t(conn, ch, state)}
                    for sid, ch in snapshot.history(conn, pid)],
        "thread": _thread(conn, row, mine),
    })
    return out


# --- mails --------------------------------------------------------------------

def snippet(body: str) -> str:
    for line in body.splitlines():
        line = line.strip()
        if line and not line.startswith(">") and not line.endswith("wrote:"):
            return line[:120]
    return ""


def _tree(rows) -> list[tuple[object, int]]:
    """(row, depth) in tree order: a mail nests under its stored parent when that is in
    the group, else it is top level. Rows come by date, so children do too."""
    ids = {r["msgid"] for r in rows}
    kids: dict[str | None, list] = {}
    for r in rows:
        p = r["in_reply_to"] if r["in_reply_to"] in ids and r["in_reply_to"] != r["msgid"] else None
        kids.setdefault(p, []).append(r)
    out, seen = [], set()

    def walk(r, depth):
        if r["msgid"] in seen:
            return
        seen.add(r["msgid"])
        out.append((r, depth))
        for k in kids.get(r["msgid"], []):
            walk(k, depth + 1)

    for r in kids.get(None, []):
        walk(r, 0)
    for r in rows:                      # a parent cycle has no top-level mail: cut it here
        walk(r, 0)
    return out


def _new_msgids(conn, row) -> set[str]:
    ref, last = snapshot.reference_state(conn, row["id"]), snapshot.latest(conn, row["id"])
    return set(last[2]["mails"]) - set(ref["mails"]) if ref and last else set()


def _groups(conn, row) -> list[tuple[str | None, list]]:
    revs = store.revisions(conn, row["id"])
    series = [r for r in revs if r["kind"] == "series"]
    groups = [(None, [r["root_msgid"] for r in series])]
    groups += [(f"{r['branch']}.y backport", [r["root_msgid"]])
               for r in revs if r["kind"] == "backport"]
    out, seen = [], set()
    for label, roots in groups:
        rows = []
        for root in roots:
            for m in store.thread_mails(conn, root):
                if m["msgid"] not in seen:
                    seen.add(m["msgid"])
                    rows.append(m)
        if rows or label is None:
            out.append((label, sorted(rows, key=lambda m: m["date"])))
    return out


def _mail(m, depth, parent, mine, new) -> dict:
    body, omitted = text_body(bytes(m["raw"]))
    return {"msgid": m["msgid"], "parent": parent, "depth": depth, "date": m["date"],
            "from_name": m["from_name"], "from_addr": m["from_addr"],
            "you": m["from_addr"] in mine, "subject": m["subject"],
            "new": m["msgid"] in new, "body": body, "omitted": omitted,
            "lore_url": f"{render.LORE}/{m['msgid']}/"}


def mails(conn, row, mine) -> dict:
    new = _new_msgids(conn, row)
    groups = []
    for label, rows in _groups(conn, row):
        ids = {m["msgid"] for m in rows}
        groups.append({"label": label, "mails": [
            _mail(m, d, m["in_reply_to"] if m["in_reply_to"] in ids else None, mine, new)
            for m, d in _tree(rows)]})
    return {"groups": groups}


def _thread(conn, row, mine) -> list[dict]:
    return [{"msgid": m["msgid"], "depth": m["depth"], "date": m["date"],
             "who": m["from_name"], "you": m["you"], "snippet": snippet(m["body"]),
             "new": m["new"]}
            for g in mails(conn, row, mine)["groups"] for m in g["mails"]]
