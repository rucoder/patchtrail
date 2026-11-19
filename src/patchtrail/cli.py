# SPDX-License-Identifier: Apache-2.0
"""Command line entry point."""
import argparse
import json
import os
import re
import sys
import time
from importlib import resources
from pathlib import Path

from patchtrail import __version__, db, render, snapshot, store
from patchtrail.config import load_config, my_addresses, paths
from patchtrail.fetch import Busy, locked, reevaluate, run_fetch
from patchtrail.importer import import_old
from patchtrail.projects.kernel import KernelTrail
from patchtrail.projects.kernel.backport import make_backport
from patchtrail.projects.kernel.queue import StableQueue
from patchtrail.projects.kernel.repo import GitError, KernelRepo
from patchtrail.sources import lore


class CliError(Exception):
    """A failure to report as `ptl: message` with exit status 1."""


def _patches(conn, names: list[str], *, hidden=False, closed=False) -> list:
    """The named patches, or every listed one with no names."""
    if not names:
        return store.list_patches(conn, hidden=hidden, closed=closed)
    rows = [store.get_patch(conn, n) for n in names]
    missing = [n for n, r in zip(names, rows) if r is None]
    if missing:
        raise CliError(f"not tracked: {', '.join(missing)}")
    return rows


def _print(lines: list[str]) -> None:
    for line in lines:
        print(line)


def _busy(e: Busy) -> CliError:
    r = e.run
    detail = f" (run {r['id']}, {r['phase']} {r['step']}/{r['steps']})" if r else ""
    return CliError(f"a fetch is already running{detail}")


def cmd_status(args, conn, cfg, mine) -> int:
    if args.names:
        _patches(conn, args.names)
    if args.fetch:
        try:
            run_fetch(paths(), cfg, "cli", patch_names=args.names or None)
        except Busy as e:
            raise _busy(e) from e
    _print(render.status_lines(conn, args.names, mine=mine))
    return 0


def cmd_ls(args, conn, cfg, mine) -> int:
    rows = render.by_activity(conn, _patches(conn, args.names, hidden=args.hidden,
                                             closed=args.closed))
    width = max((len(r["name"]) for r in rows), default=0)
    for r in rows:
        state = render.current_state(conn, r, mine)
        _print(render.summary_lines(conn, r, mine=mine, width=width, state=state))
        if r["project"] == "kernel":
            _print(render.kernel_lines(state, verbose=args.verbose))
        print()
    return 0


def cmd_show(args, conn, cfg, mine) -> int:
    for r in _patches(conn, args.names):
        _print(render.show_lines(conn, r, mine))
        print()
    return 0


def cmd_trailers(args, conn, cfg, mine) -> int:
    for r in _patches(conn, args.names):
        _print(render.trailers_lines(conn, r, mine))
    return 0


def cmd_history(args, conn, cfg, mine) -> int:
    _print(render.history_lines(conn, _patches(conn, [args.name])[0]))
    return 0


def cmd_mine(args, conn, cfg, mine) -> int:
    addrs = args.addresses or sorted(mine)
    if not addrs:
        raise CliError("no address: pass one, or set git config sendemail.from")
    roots: dict[str, lore.Entry] = {}
    for addr in addrs:
        try:
            entries = lore.search("all", f"f:{addr} AND s:PATCH")
        except lore.LoreError as e:
            raise CliError(f"lore search for {addr} failed: {e}") from e
        for e in entries:
            if not e.is_reply and not e.subject.lower().startswith("re:"):
                roots.setdefault(e.msgid, e)
    owner: dict[str, tuple] = {}  # msgid -> (msgid, patch name, hidden)
    for r in conn.execute("SELECT m.msgid, p.name, p.hidden FROM mails m JOIN revisions v "
                          "ON m.revision_id=v.id JOIN patches p ON v.patch_id=p.id"):
        owner[r[0]] = r
    for r in conn.execute("SELECT v.root_msgid, p.name, p.hidden FROM revisions v "
                          "JOIN patches p ON v.patch_id=p.id"):
        owner[r[0]] = r
    print(f"threads started by {', '.join(addrs)} on lore:")
    for msgid, e in sorted(roots.items(), key=lambda kv: kv[1].updated, reverse=True):
        o = owner.get(msgid)
        name = (f"(hidden) {o[1]}" if o[2] else o[1]) if o else "(not tracked)"
        print(f"  {e.updated[:10]}  {name:32} {e.subject}")
    return 0


def _mboxrd(raws: list[bytes]) -> bytes:
    out = b""
    for raw in raws:
        escaped = re.sub(rb"(?m)^(>*From )", rb">\1", raw)
        if not escaped.endswith(b"\n"):
            escaped += b"\n"
        out += b"From patchtrail@localhost Thu Jan  1 00:00:00 1970\n" + escaped + b"\n"
    return out


def cmd_open(args, conn, cfg, mine) -> int:
    if args.name:
        row = _patches(conn, [args.name])[0]
    else:
        row = conn.execute("SELECT * FROM patches ORDER BY created_at DESC, id DESC").fetchone()
        if row is None:
            raise CliError("no patches tracked")
    raws = [bytes(m["raw"]) for m in store.patch_mails(conn, row["id"])]
    if not raws:
        raise CliError(f"{row['name']}: no mails fetched yet")
    tmp = paths().home / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    mbox = tmp / f"{row['name']}-{int(time.time())}.mbox"
    mbox.write_bytes(_mboxrd(raws))
    rc = resources.files("patchtrail").joinpath("data/neomuttrc")
    with resources.as_file(rc) as rc_path:
        os.execvp("neomutt", ["neomutt", "-n", "-F", str(rc_path), "-R", "-f", str(mbox)])
    return 0


# --- changing commands ---------------------------------------------------------

def _one(conn, name: str):
    return _patches(conn, [name])[0]


def _reeval(conn, cfg, *rows) -> None:
    for row in rows:
        reevaluate(conn, paths(), cfg, row["id"])


def _series(arg: str) -> str:
    m = re.fullmatch(r"(?:linux-)?(\d+\.\d+)(?:\.y)?", arg)
    if not m:
        raise CliError(f"bad series: {arg}")
    return m.group(1)


def cmd_read(args, conn, cfg, mine) -> int:
    if args.all:
        rows = store.list_patches(conn, closed=True)
    elif args.names:
        rows = _patches(conn, args.names)
    else:
        raise CliError("name a patch or pass --all")
    for r in rows:
        snapshot.mark_read(conn, r["id"])
    conn.commit()
    return 0


def cmd_unread(args, conn, cfg, mine) -> int:
    for r in _patches(conn, args.names):
        snapshot.mark_unread(conn, r["id"])
    conn.commit()
    return 0


def _fetch(cfg, names: list[str] | None, **kw) -> int:
    try:
        return run_fetch(paths(), cfg, "cli", patch_names=names, **kw)
    except Busy as e:
        raise _busy(e) from e


def cmd_fetch(args, conn, cfg, mine) -> int:
    _patches(conn, args.names)
    _fetch(cfg, args.names or None, echo=print)
    return 0


def _news(conn, since: int, mine) -> tuple[list[str], int]:
    """The changes of the snapshots after id since, per patch against the snapshot
    before them, and the newest snapshot's id."""
    rows = conn.execute("SELECT id, patch_id FROM snapshots WHERE id>? ORDER BY id",
                        (since,)).fetchall()
    out: list[str] = []
    for pid in dict.fromkeys(r["patch_id"] for r in rows):
        patch = store.patch_by_id(conn, pid)
        if patch is None:
            continue
        old = conn.execute("SELECT state FROM snapshots WHERE patch_id=? AND id<=? "
                           "ORDER BY id DESC LIMIT 1", (pid, since)).fetchone()
        old_state = json.loads(old[0]) if old else None
        new_state = snapshot.latest(conn, pid)[2]
        multi = len(store.commits(conn, pid)) > 1
        out.append(patch["name"])
        out += ["  " + render.change_line(conn, c, multi=multi, state=new_state)
                for c in snapshot.changes(old_state, new_state)]
    return out, rows[-1]["id"] if rows else since


def _newest_snapshot(conn) -> int:
    return conn.execute("SELECT COALESCE(MAX(id), 0) FROM snapshots").fetchone()[0]


def cmd_poll(args, conn, cfg, mine) -> int:
    _patches(conn, args.names)
    before = _newest_snapshot(conn)
    _fetch(cfg, args.names or None, echo=print)
    lines, _ = _news(conn, before, mine)
    _print(lines or ["nothing new"])
    return 0


def cmd_watch(args, conn, cfg, mine) -> int:
    last = _newest_snapshot(conn)
    try:
        while True:
            time.sleep(30)
            lines, last = _news(conn, last, mine)
            _print(lines)
            sys.stdout.flush()
    except KeyboardInterrupt:
        return 0


def _add_report(conn, row, mine, as_json: bool) -> None:
    latest = snapshot.latest(conn, row["id"])
    if as_json:
        revs = store.revisions(conn, row["id"])
        msgid = revs[-1]["root_msgid"] if revs else None
        print(json.dumps({
            "name": row["name"], "msgid": msgid, "project": row["project"],
            "stage": latest[2]["stage"] if latest else None,
            "standing": latest[2]["standing"]["text"] if latest else None,
            "links": store.links(conn, row["id"]), "note": row["note"],
            "url": f"{render.LORE}/{msgid}/" if msgid else None}))
    else:
        _print(render.summary_lines(conn, row, mine=mine,
                                    state=render.current_state(conn, row, mine)))


def cmd_add(args, conn, cfg, mine) -> int:
    if not store.valid_name(args.name):
        raise CliError(f"invalid name: {args.name}")
    msgid = lore.parse_msgid(args.msgid)
    if not msgid:
        raise CliError("no Message-ID")
    now = int(time.time())
    rev = store.revision_by_msgid(conn, msgid)
    if rev is not None:                     # registered before: the first name stays
        row = store.patch_by_id(conn, rev["patch_id"])
    else:
        if store.get_patch(conn, args.name) is not None:
            raise CliError(f"name taken: {args.name}")
        row = store.patch_by_id(conn, store.add_patch(
            conn, args.name, relation="following" if args.follow else "mine", now=now))
        if not args.follow:
            store.set_field(conn, row["id"], "read_on_first_snapshot", 1)
        store.add_revision(conn, row["id"], msgid, subject="")
        conn.execute("DELETE FROM ignored WHERE msgid=?", (msgid,))
        conn.commit()
    store.add_links(conn, row["id"], args.link, now)
    if args.note is not None:
        store.set_field(conn, row["id"], "note", args.note or None)
    try:
        run_fetch(paths(), cfg, "cli", patch_names=[row["name"]], discover_new=False)
    except Busy:
        if not args.json:
            print(f"added {row['name']}; it is fetched on the next run")
            return 0
    except Exception as e:      # lore is reached run by run; the patch is registered
        print(f"ptl: fetch failed: {e}; it is fetched on the next run", file=sys.stderr)
    row = store.patch_by_id(conn, row["id"])
    _add_report(conn, row, mine, args.json)
    return 0


def cmd_link(args, conn, cfg, mine) -> int:
    store.add_links(conn, _one(conn, args.name)["id"], args.urls, int(time.time()))
    return 0


def cmd_unlink(args, conn, cfg, mine) -> int:
    store.remove_links(conn, _one(conn, args.name)["id"], args.urls)
    return 0


def cmd_note(args, conn, cfg, mine) -> int:
    store.set_field(conn, _one(conn, args.name)["id"], "note", args.text or None)
    return 0


def cmd_follow(args, conn, cfg, mine) -> int:
    rest = args.rest
    if len(rest) > 3:
        raise CliError("usage: follow NAME [COMMIT] [TREE-URL BRANCH] [--stable]")
    commit = rest[0] if len(rest) in (1, 3) else None
    tree = tuple(rest[-2:]) if len(rest) >= 2 else None
    row = store.get_patch(conn, args.name)
    if row is None:
        if not store.valid_name(args.name):
            raise CliError(f"invalid name: {args.name}")
        if commit is None:
            raise CliError(f"{args.name} is not tracked: give a COMMIT")
        row = store.patch_by_id(conn, store.add_patch(
            conn, args.name, relation="following", project="kernel", now=int(time.time())))
    elif commit is None and (known := store.commits(conn, row["id"])):
        commit = known[0]["sha"]
    elif commit is None and not tree and not args.stable:
        raise CliError(f"{args.name} has no commit yet: give a COMMIT")
    if commit:
        old = next((c for c in store.commits(conn, row["id"]) if c["sha"] == commit), None)
        store.set_commit(conn, row["id"], commit, old["subject"] if old else "", "manual")
    if tree:
        store.set_field(conn, row["id"], "tree_url", tree[0])
        store.set_field(conn, row["id"], "tree_branch", tree[1])
        store.set_field(conn, row["id"], "tree_source", "manual")
    if args.stable:
        store.set_field(conn, row["id"], "force_stable", 1)
    return 0


def cmd_hide(args, conn, cfg, mine) -> int:
    rows = _patches(conn, args.names)
    for r in rows:
        store.set_field(conn, r["id"], "hidden", 1)
    _reeval(conn, cfg, *rows)
    return 0


def cmd_unhide(args, conn, cfg, mine) -> int:
    for r in _patches(conn, args.names):
        store.set_field(conn, r["id"], "hidden", 0)
    return 0


def _remove(conn, row) -> None:
    """Delete the patch and ignore its roots. The mails below its revisions that
    belong to another patch's thread move to that patch first; deleting a revision
    deletes the mails stored under it."""
    ids = [r["id"] for r in store.revisions(conn, row["id"])]
    mine_ = {m[0] for m in conn.execute(
        f"SELECT msgid FROM mails WHERE revision_id IN ({','.join('?' * len(ids))})", ids)}
    for other in conn.execute("SELECT id FROM patches WHERE id!=?", (row["id"],)).fetchall():
        revs = [r for r in store.revisions(conn, other["id"]) if r["kind"] == "series"] \
            or store.revisions(conn, other["id"])
        if not revs:
            continue
        keep = [(revs[-1]["id"], m["msgid"]) for m in store.patch_mails(conn, other["id"])
                if m["msgid"] in mine_]
        conn.executemany("UPDATE mails SET revision_id=? WHERE msgid=?", keep)
        mine_ -= {m for _, m in keep}
    conn.executemany("INSERT OR IGNORE INTO ignored (msgid) VALUES (?)",
                     [(r["root_msgid"],) for r in store.revisions(conn, row["id"])])
    conn.execute("DELETE FROM patches WHERE id=?", (row["id"],))


def cmd_rm(args, conn, cfg, mine) -> int:
    rows = _patches(conn, args.names)
    for r in rows:
        _remove(conn, r)
    conn.commit()
    return 0


def cmd_rename(args, conn, cfg, mine) -> int:
    row = _one(conn, args.old)
    if not store.valid_name(args.new):
        raise CliError(f"invalid name: {args.new}")
    if store.get_patch(conn, args.new) is not None:
        raise CliError(f"name taken: {args.new}")
    store.set_field(conn, row["id"], "name", args.new)
    return 0


def cmd_merge(args, conn, cfg, mine) -> int:
    a, b = _one(conn, args.name), _one(conn, args.other)
    if a["id"] == b["id"]:
        raise CliError("cannot merge a patch into itself")
    # Mails hang on the revisions, so they move with them.
    conn.execute("UPDATE revisions SET patch_id=? WHERE patch_id=?", (a["id"], b["id"]))
    conn.execute("INSERT OR IGNORE INTO commits (patch_id, sha, subject, source)"
                 " SELECT ?, sha, subject, source FROM commits WHERE patch_id=?",
                 (a["id"], b["id"]))
    conn.execute("INSERT OR IGNORE INTO branch_skips (patch_id, series)"
                 " SELECT ?, series FROM branch_skips WHERE patch_id=?", (a["id"], b["id"]))
    conn.execute("INSERT OR IGNORE INTO links (patch_id, url, added_at)"
                 " SELECT ?, url, added_at FROM links WHERE patch_id=?", (a["id"], b["id"]))
    conn.execute("DELETE FROM patches WHERE id=?", (b["id"],))
    conn.commit()
    _reeval(conn, cfg, a)
    return 0


def cmd_split(args, conn, cfg, mine) -> int:
    row = _one(conn, args.name)
    revs = store.revisions(conn, row["id"])
    hit = [r for r in revs if r["version"] == args.rev and r["kind"] == "series"]
    if not hit:
        raise CliError(f"{args.name} has no v{args.rev}")
    if len(hit) > 1:
        raise CliError(f"{args.name} has several v{args.rev} revisions")
    if len(revs) == 1:
        raise CliError(f"{args.name} has only one revision")
    new = f"{args.name}-v{args.rev}"
    if store.get_patch(conn, new) is not None:
        raise CliError(f"name taken: {new}")
    if not store.valid_name(new):
        raise CliError(f"invalid name: {new}")
    cur = conn.execute("INSERT INTO patches (name, relation, project, project_override,"
                       " created_at) VALUES (?,?,?,?,?)",
                       (new, row["relation"], row["project"], row["project_override"],
                        int(time.time())))
    conn.execute("UPDATE revisions SET patch_id=? WHERE id=?", (cur.lastrowid, hit[0]["id"]))
    conn.commit()
    return 0


def cmd_close(args, conn, cfg, mine) -> int:
    row = _one(conn, args.name)
    store.set_field(conn, row["id"], "closed", args.reason)
    store.set_field(conn, row["id"], "closed_note", args.note)
    _reeval(conn, cfg, row)
    return 0


def cmd_skip(args, conn, cfg, mine) -> int:
    row, series = _one(conn, args.name), _series(args.series)
    conn.execute("INSERT OR IGNORE INTO branch_skips (patch_id, series) VALUES (?,?)",
                 (row["id"], series))
    conn.commit()
    _reeval(conn, cfg, row)
    return 0


def cmd_unskip(args, conn, cfg, mine) -> int:
    row, series = _one(conn, args.name), _series(args.series)
    conn.execute("DELETE FROM branch_skips WHERE patch_id=? AND series=?", (row["id"], series))
    conn.commit()
    _reeval(conn, cfg, row)
    return 0


def cmd_mark_applied(args, conn, cfg, mine) -> int:
    row = _one(conn, args.name)
    store.set_field(conn, row["id"], "manual_applied", 1)
    if args.commit:
        store.set_commit(conn, row["id"], args.commit, "", "manual")
    _reeval(conn, cfg, row)
    return 0


class _StderrProgress:
    def phase(self, name, steps=None):
        print(f"phase: {name}", file=sys.stderr)

    def step(self, label):
        print(f"step: {label}", file=sys.stderr)

    def log(self, line):
        print(line, file=sys.stderr)


def cmd_check(args, conn, cfg, mine) -> int:
    progress = _StderrProgress()
    try:
        with locked(paths(), conn):
            trail = KernelTrail(paths(), cfg)
            trail.prepare([], progress)
            results = trail.check_commits(args.commits, progress)
    except Busy as e:
        raise _busy(e) from e
    except Exception as e:
        raise CliError(f"check failed: {e}") from e
    for i, (sha, res) in enumerate(zip(args.commits, results)):
        frag = res.fragment
        found = frag["commits"][0] if frag["commits"] else {}
        if i:
            print()
        print(f"{(found.get('sha') or sha)[:12]} {found.get('subject') or ''}".rstrip())
        _print(render.kernel_lines({k: frag[k] for k in ("commits", "branches", "failed", "hint")}))
    return 0


def cmd_backport(args, conn, cfg, mine) -> int:
    row = store.get_patch(conn, args.target)
    if row is not None:
        known = store.commits(conn, row["id"])
        if not known:
            raise CliError(f"{row['name']} has no commit yet")
        sha, name = known[0]["sha"], row["name"]
    elif re.fullmatch(r"[0-9a-fA-F]{7,40}", args.target):
        sha, name = args.target, args.target[:12]
    else:
        raise CliError(f"not tracked: {args.target}")
    series = _series(args.series)
    dest = Path(args.dir or f"{name}-{series}")
    try:
        lines = make_backport(KernelRepo(paths().linux), StableQueue(paths().queue),
                              sha, name, series, dest)
    except GitError as e:
        raise CliError(str(e)) from e
    _print(lines)
    return 0


def cmd_import(args, conn, cfg, mine) -> int:
    r = import_old(conn, mine, now=int(time.time()))
    print(f"imported {len(r.patches)} patches")
    for label, items in (("merged", r.merged), ("fixes", r.fixes), ("skipped", r.skipped)):
        if items:
            print(f"{label}: {', '.join(items)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ptl")
    ap.add_argument("--version", action="store_true", help="print version and exit")
    sub = ap.add_subparsers(dest="cmd")

    def add(name, func, help):
        p = sub.add_parser(name, help=help)
        p.set_defaults(func=func)
        return p

    p = add("status", cmd_status, "what changed since you last read each patch")
    p.add_argument("names", nargs="*", metavar="NAME")
    p.add_argument("--fetch", action="store_true", help="fetch first")
    p = add("ls", cmd_ls, "list patches")
    p.add_argument("names", nargs="*", metavar="NAME")
    p.add_argument("--hidden", action="store_true")
    p.add_argument("--closed", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p = add("show", cmd_show, "a patch with all its mails")
    p.add_argument("names", nargs="+", metavar="NAME")
    p = add("trailers", cmd_trailers, "review tags received")
    p.add_argument("names", nargs="*", metavar="NAME")
    p = add("history", cmd_history, "what changed at each fetch")
    p.add_argument("name", metavar="NAME")
    p = add("mine", cmd_mine, "your patch threads on lore")
    p.add_argument("addresses", nargs="*", metavar="ADDR")
    p = add("open", cmd_open, "read a patch's mails in neomutt")
    p.add_argument("name", nargs="?", metavar="NAME")
    p = add("read", cmd_read, "mark patches read")
    p.add_argument("names", nargs="*", metavar="NAME")
    p.add_argument("--all", action="store_true")
    p = add("unread", cmd_unread, "mark patches unread again")
    p.add_argument("names", nargs="+", metavar="NAME")
    p = add("add", cmd_add, "register a posted patch (for you, scripts and AI agents)")
    p.add_argument("name", metavar="NAME")
    p.add_argument("msgid", metavar="MSGID|URL")
    p.add_argument("--follow", action="store_true", help="someone else's thread")
    p.add_argument("--note", help="a note on the patch; replaces the old one")
    p.add_argument("--link", action="append", default=[], metavar="URL",
                   help="a PR or Jira URL; repeatable")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    p = add("link", cmd_link, "attach URLs to a patch")
    p.add_argument("name", metavar="NAME")
    p.add_argument("urls", nargs="+", metavar="URL")
    p = add("unlink", cmd_unlink, "detach URLs from a patch")
    p.add_argument("name", metavar="NAME")
    p.add_argument("urls", nargs="+", metavar="URL")
    p = add("note", cmd_note, "set a patch's note; empty text clears it")
    p.add_argument("name", metavar="NAME")
    p.add_argument("text", metavar="TEXT")
    p = add("follow", cmd_follow, "follow a commit, or set a patch's commit and tree")
    p.add_argument("name", metavar="NAME")
    p.add_argument("rest", nargs="*", metavar="COMMIT | [COMMIT] TREE-URL BRANCH")
    p.add_argument("--stable", action="store_true", help="track stable even without Cc: stable")
    p = add("hide", cmd_hide, "hide patches from ls and status")
    p.add_argument("names", nargs="+", metavar="NAME")
    p = add("unhide", cmd_unhide, "show hidden patches again")
    p.add_argument("names", nargs="+", metavar="NAME")
    p = add("rm", cmd_rm, "delete patches; they are not found again")
    p.add_argument("names", nargs="+", metavar="NAME")
    p = add("rename", cmd_rename, "rename a patch")
    p.add_argument("old", metavar="OLD")
    p.add_argument("new", metavar="NEW")
    p = add("merge", cmd_merge, "move OTHER's revisions into NAME")
    p.add_argument("name", metavar="NAME")
    p.add_argument("other", metavar="OTHER")
    p = add("split", cmd_split, "move a revision into its own patch NAME-vN")
    p.add_argument("name", metavar="NAME")
    p.add_argument("rev", type=int, metavar="VERSION")
    p = add("close", cmd_close, "close a patch that will not be merged")
    p.add_argument("name", metavar="NAME")
    p.add_argument("reason", choices=["rejected", "dropped", "moved"])
    p.add_argument("--note", help="why, e.g. where it went")
    p = add("skip", cmd_skip, "do not backport to a stable series")
    p.add_argument("name", metavar="NAME")
    p.add_argument("series", metavar="SERIES")
    p = add("unskip", cmd_unskip, "backport to a stable series again")
    p.add_argument("name", metavar="NAME")
    p.add_argument("series", metavar="SERIES")
    p = add("mark-applied", cmd_mark_applied, "the patch is applied; optionally as COMMIT")
    p.add_argument("name", metavar="NAME")
    p.add_argument("commit", nargs="?", metavar="COMMIT")
    p = add("fetch", cmd_fetch, "fetch lore and the git trees now")
    p.add_argument("names", nargs="*", metavar="NAME")
    p = add("poll", cmd_poll, "fetch, then print what changed")
    p.add_argument("names", nargs="*", metavar="NAME")
    p = add("watch", cmd_watch, "print new changes every 30 s; does not fetch")
    p = add("check", cmd_check, "where a commit stands in each stable branch")
    p.add_argument("commits", nargs="+", metavar="COMMIT")
    p = add("backport", cmd_backport, "a worktree to backport a fix by hand")
    p.add_argument("target", metavar="NAME|COMMIT")
    p.add_argument("series", metavar="SERIES")
    p.add_argument("dir", nargs="?", metavar="DIR")
    p = add("import", cmd_import, "import lkml-watch and stable-watch state")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.version:
        print(f"patchtrail {__version__}")
        return 0
    if args.cmd is None:
        args = ap.parse_args(["status"])
    cfg = load_config(paths())
    conn = db.connect(paths().db)
    try:
        return args.func(args, conn, cfg, my_addresses(cfg))
    except CliError as e:
        print(f"ptl: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


def run() -> None:
    sys.exit(main())
