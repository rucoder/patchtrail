"""Per-branch status of a mainline fix in the stable trees (port of stable-watch)."""

import os
import re
import tempfile
from dataclasses import dataclass, field

from patchtrail.projects.kernel.queue import QueuedPatch, StableQueue
from patchtrail.projects.kernel.repo import MAINLINE, KernelRepo, stable_ref


def stable_tags(body: str) -> tuple[str | None, list[str]]:
    """(Cc: stable line's hint or "" if present else None, [Fixes: hashes])."""
    cc = re.search(r"^Cc:.*stable@(?:vger\.)?kernel\.org>?[ \t]*"
                   r"(?:#[ \t]*(.*))?$", body, re.M | re.I)
    fixes = re.findall(r"^Fixes:\s*([0-9a-f]{8,40})", body, re.M | re.I)
    return ((cc.group(1) or "").strip() if cc else None), fixes


def in_branch(repo: KernelRepo, sha, ref, base, files) -> str | None:
    """The commit that brings sha into the branch (itself or a backport)."""
    if repo.is_ancestor(sha, ref):
        return sha
    out = repo.run("log", "-i", "-F", f"--grep={sha[:12]}", "--format=%H",
                   f"{base}..{ref}", "--", *files).split()
    return out[-1] if out else None


def with_queue(repo: KernelRepo, ref, patches: list[QueuedPatch]) -> tuple[str, list[str], list[str]]:
    """A commit of ref plus the given queued patches; (commit, applied, failed)."""
    applied, failed = [], []
    with tempfile.TemporaryDirectory() as d:
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(d, "index"),
                   GIT_AUTHOR_NAME="patchtrail", GIT_AUTHOR_EMAIL="-",
                   GIT_COMMITTER_NAME="patchtrail", GIT_COMMITTER_EMAIL="-")
        repo.run("read-tree", ref, env=env)
        for p in patches:
            path = os.path.join(d, "p")
            with open(path, "w") as f:
                f.write(p.text)
            (applied if repo.ok("apply", "--cached", path, env=env)
             else failed).append(p.name)
        tree = repo.run("write-tree", env=env).strip()
        commit = repo.run("commit-tree", tree, "-p", ref, "-m", "stable-queue",
                          env=env).strip()
    return commit, applied, failed


def conflicts(repo: KernelRepo, sha, onto) -> list[str]:
    """[] if sha applies cleanly onto onto, else the conflicting files."""
    out = repo.run("merge-tree", "--write-tree", "--name-only",
                   f"--merge-base={sha}^", onto, sha, ok=(0, 1))
    # Exit 0 prints only the tree; exit 1 adds the conflicted file names.
    lines = out.splitlines()[1:]
    return lines[:lines.index("")] if "" in lines else lines


@dataclass(frozen=True)
class Prereq:
    sha: str
    subject: str
    tag: str | None
    cc: str | None
    fixes: tuple[str, ...]


def prerequisites(repo: KernelRepo, sha, ref, base, files) -> list[Prereq]:
    """Upstream commits the fix's context lines in files come from that the
    branch lacks, newest first."""
    found = {}
    for f in files:
        diff = repo.run("diff", "-U3", f"{sha}^", sha, "--", f)
        for m in re.finditer(r"^@@ -(\d+)(?:,(\d+))? ", diff, re.M):
            start, n = int(m.group(1)), int(m.group(2) or 1)
            if n == 0:
                start, n = max(start, 1), 1
            blame = repo.run("blame", "--porcelain", "-L", f"{start},+{n}",
                             f"{sha}^", "--", f)
            for c in re.findall(r"^([0-9a-f]{40}) \d+ \d+", blame, re.M):
                found.setdefault(c, f)
    missing = [c for c, f in found.items()
               if not repo.is_ancestor(c, base) and not in_branch(repo, c, ref, base, [f])]
    if not missing:
        return []
    out = []
    for c in repo.run("log", "--no-walk=sorted", "--format=%H", *missing).split():
        cc, fixes = stable_tags(repo.run("log", "-1", "--format=%B", c))
        out.append(Prereq(c, repo.run("log", "-1", "--format=%s", c).strip(),
                          repo.first_tag(c), cc, tuple(fixes)))
    return out


@dataclass
class BranchResult:
    state: str
    tag: str | None = None
    detail: list[str] = field(default_factory=list)
    prereqs: list[Prereq] = field(default_factory=list)


def branch_status(repo: KernelRepo, queue: StableQueue, sha, files, targets, series) -> BranchResult:
    """Where the fix stands on one stable branch."""
    ref = stable_ref(series)
    if not repo.resolve(ref):
        return BranchResult("not_fetched")
    base = repo.run("merge-base", ref, MAINLINE).strip()
    if targets:
        lacks = [t for t in targets
                 if not in_branch(repo, t, ref, base, repo.run(
                     "show", "--format=", "--name-only", t).split())]
        if len(lacks) == len(targets):
            return BranchResult("not_affected", detail=[f"no {', '.join(t[:12] for t in lacks)}"])
    has = in_branch(repo, sha, ref, base, files)
    if has:
        tag = repo.first_tag(has, series)
        return BranchResult("released", tag) if tag else BranchResult("in_branch")
    q = queue.queued(series, sha)
    if q:
        return BranchResult("queued", detail=[f"queued for the next {series} release: {', '.join(q)}"])
    touching = [p for p in queue.patches(series) if p.files & set(files)]
    onto, applied, failed = (with_queue(repo, ref, touching) if touching
                             else (ref, [], []))
    after = (f", after {len(applied)} queued patch"
             f"{'es' if len(applied) != 1 else ''} to the same files"
             if applied else "")
    bad = conflicts(repo, sha, onto)
    extra = [f"queued patches that did not apply: {', '.join(failed)}"] if failed else []
    if not bad:
        return BranchResult("applies_after_queue" if applied else "applies",
                            detail=[f"applies cleanly{after}"] + extra)
    return BranchResult("conflict",
                        detail=[f"CONFLICT in {', '.join(bad)}{after}: needs a backport by hand"] + extra,
                        prereqs=prerequisites(repo, sha, ref, base, bad))
