# SPDX-License-Identifier: Apache-2.0
"""`ptl setup`: check git, write a default config, seed the Linux clone, import."""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

from patchtrail import db
from patchtrail.config import Paths, load_config, my_addresses, paths
from patchtrail.importer import import_old
from patchtrail.projects.kernel.repo import KernelRepo

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


def run_setup(*, seed: Path | None, no_seed: bool, do_import: bool | None) -> int:
    ok, msg = git_version_ok()
    if not ok:
        print(msg, file=sys.stderr)
        return 1
    p = paths()
    p.home.mkdir(parents=True, exist_ok=True)
    if write_default_config(p, sorted(my_addresses(load_config(p)))):
        print(f"wrote {p.config}")
    cfg = load_config(p)
    conn = db.connect(p.db)
    try:
        if not no_seed and seed is None:
            default = _xdg("XDG_STATE_HOME", ".local/state") / "stable-watch" / "linux.git"
            if cfg.seed:
                seed = Path(cfg.seed).expanduser()
            elif default.is_dir():
                seed = default
        if no_seed:
            seed = None
        if not p.linux.exists():
            if seed is not None:
                print(f"seeding from {seed} (hardlinks, no copy)")
            KernelRepo(p.linux).ensure(seed)
        threads = _xdg("XDG_CONFIG_HOME", ".config") / "lkml-watch" / "threads"
        if do_import or (do_import is None and threads.exists()):
            r = import_old(conn, my_addresses(cfg), now=int(time.time()))
            print(f"imported {len(r.patches)} patches")
    finally:
        conn.close()
    print("next: `ptl fetch` (the first run fetches mainline and stable; with a seed this takes "
          "minutes, without one several GB), then `ptl status`")
    return 0
