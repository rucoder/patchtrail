# SPDX-License-Identifier: Apache-2.0
"""Command line entry point."""
import argparse
import os
import re
import sys
import time
from importlib import resources

from patchtrail import __version__, db, render, store
from patchtrail.config import load_config, my_addresses, paths
from patchtrail.fetch import Busy, run_fetch
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


def cmd_status(args, conn, cfg, mine) -> int:
    if args.fetch:
        try:
            run_fetch(paths(), cfg, "cli", patch_names=args.names or None)
        except Busy as e:
            r = e.run
            detail = f" (run {r['id']}, {r['phase']} {r['step']}/{r['steps']})" if r else ""
            raise CliError(f"a fetch is already running{detail}") from e
    if args.names:
        _patches(conn, args.names)
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
