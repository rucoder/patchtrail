# SPDX-License-Identifier: Apache-2.0
"""`ptl setup`: check git, write a default config, seed the Linux clone, import."""

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from patchtrail import db, store
from patchtrail.config import Paths, load_config, my_addresses, paths
from patchtrail.importer import import_old
from patchtrail.projects.kernel.repo import GitError, KernelRepo

MIN_GIT = (2, 40)


def git_version_ok(out: str | None = None) -> tuple[bool, str]:
    """(ok, version) from `git --version`; on failure the second item is the message."""
    if out is None:
        out = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", out)
    if not m:
        return False, f"patchtrail needs git >= 2.40 (found {out.strip() or 'none'})"
    found = ".".join(g for g in m.groups() if g is not None)
    if (int(m.group(1)), int(m.group(2))) < MIN_GIT:
        return False, f"patchtrail needs git >= 2.40 (found {found})"
    return True, found


def write_default_config(p: Paths, addresses: list[str]) -> bool:
    """Write config.toml unless it exists; True when written."""
    if p.config.exists():
        return False
    addrs = ", ".join('"' + a.replace("\\", "\\\\").replace('"', '\\"') + '"' for a in addresses)
    p.config.write_text(f"""\
# patchtrail configuration
# Your own mail addresses: patches from them are "mine".
addresses = [{addrs}]

# Where `ptl serve` listens.
listen = "0.0.0.0:8470"

# Hours between scheduled fetches.
interval_hours = 3

# A local clone of linux.git to seed ~/.patchtrail/git/linux.git from (hardlinks).
# seed = "~/linux.git"

# Other kernel remotes, if you do not want kernel.org's:
# [kernel]
# mainline = "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git"
# stable = "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git"
""")
    return True


def _xdg(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / fallback)


def _seed(cfg, seed: Path | None, no_seed: bool) -> Path | None:
    """The repository to seed from: --seed, else the config's seed, else
    stable-watch's clone when there is one."""
    if no_seed:
        return None
    if seed is None and cfg.seed:
        seed = Path(cfg.seed).expanduser()
    if seed is None:
        default = _xdg("XDG_STATE_HOME", ".local/state") / "stable-watch" / "linux.git"
        seed = default if default.is_dir() else None
    return seed


def _not_a_repo(seed: Path) -> str | None:
    """Why seed cannot be cloned from, None if it can."""
    if not seed.is_dir():
        return "no such directory"
    r = subprocess.run(["git", "-C", str(seed), "rev-parse", "--git-dir"],
                       capture_output=True, text=True)
    return (r.stderr.strip() or "not a git repository") if r.returncode else None


def run_setup(*, seed: Path | None, no_seed: bool, do_import: bool | None) -> int:
    ok, msg = git_version_ok()
    if not ok:
        print(msg, file=sys.stderr)
        return 1
    p = paths()
    cfg = load_config(p)
    seed = None if p.linux.exists() else _seed(cfg, seed, no_seed)
    if seed is not None and (why := _not_a_repo(seed)):
        print(f"ptl: cannot seed from {seed}: {why}", file=sys.stderr)
        return 1
    p.home.mkdir(parents=True, exist_ok=True)
    if write_default_config(p, sorted(my_addresses(cfg))):
        print(f"wrote {p.config}")
    cfg = load_config(p)
    conn = db.connect(p.db)
    try:
        if not p.linux.exists():
            if seed is not None:
                print(f"seeding from {seed} (hardlinks, no copy)")
            try:
                KernelRepo(p.linux).ensure(seed)
            except GitError as e:
                shutil.rmtree(p.linux, ignore_errors=True)
                what = f"seed from {seed}" if seed is not None else f"create {p.linux}"
                print(f"ptl: cannot {what}: {e}", file=sys.stderr)
                return 1
        threads = _xdg("XDG_CONFIG_HOME", ".config") / "lkml-watch" / "threads"
        if do_import or (do_import is None and threads.exists()):
            r = import_old(conn, my_addresses(cfg), now=int(time.time()))
            if r.patches or r.fixes:
                print(f"imported {len(r.patches)} patches")
            else:
                print(f"nothing new to import ({len(store.list_patches(conn))} already tracked)")
    finally:
        conn.close()
    print("next: `ptl fetch` (the first run fetches mainline and stable; with a seed this takes "
          "minutes, without one several GB), then `ptl status`")
    return 0
