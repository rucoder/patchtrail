"""A worktree to backport a fix to a stable branch by hand (port of stable-watch backport)."""

import subprocess
from pathlib import Path

from patchtrail.projects.kernel.queue import StableQueue
from patchtrail.projects.kernel.repo import GitError, KernelRepo, stable_ref


def _git(wt: Path, *args, input=None) -> bool:
    return subprocess.run(["git", "-C", str(wt), *args], input=input, text=True,
                          capture_output=True).returncode == 0


def make_backport(repo: KernelRepo, queue: StableQueue, sha: str, name: str, series: str,
                  dest: Path) -> list[str]:
    """A worktree on linux-SERIES.y, branch backport/NAME-SERIES, with stable's queued
    patches to the same files applied and the fix cherry-picked (-x). A conflict is
    left in the worktree to resolve. Returns the lines to print."""
    full = repo.resolve(sha)
    if not full:
        raise GitError(f"unknown commit: {sha}")
    ref = stable_ref(series)
    if not repo.resolve(ref):
        raise GitError(f"no linux-{series}.y fetched: run ptl fetch first")
    wt = Path(dest).absolute()
    branch = f"backport/{name}-{series}"
    repo.run("worktree", "add", "-q", "-b", branch, str(wt), ref)
    files = set(repo.run("show", "--format=", "--name-only", full).split())
    lines = []
    for p in queue.patches(series):
        if p.files & files:
            if _git(wt, "am", "-q", input=p.text):
                lines.append(f"applied queued {p.name}")
            else:
                _git(wt, "am", "--abort")
                lines.append(f"queued {p.name} does not apply; left out")
    clean = _git(wt, "cherry-pick", "-x", full)
    lines.append(f"worktree {wt}, branch {branch} on linux-{series}.y")
    lines.append(f"{full[:12]} applies cleanly" if clean
                 else f"{full[:12]} conflicts: resolve, git cherry-pick --continue")
    lines.append("stable's form: the first body line 'commit <hash> upstream.', your "
                 "Signed-off-by; send to stable@vger.kernel.org in reply to the "
                 "FAILED mail")
    return lines
