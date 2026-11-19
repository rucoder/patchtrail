# SPDX-License-Identifier: Apache-2.0
"""Synthetic kernel repositories for tests, served over file://.

Mainline history (one commit per day from 2026-01-02, oldest first):
  A  init io              v6.0    MAINTAINERS (F: io.c, T: git <tree>), io.c
  B  add bug              v6.1-rc1  io.c line 10
  b  readme               v6.1
  R  refactor io          v6.2-rc1  author Other; rewrites io.c lines 5-15
  r2 readme               v6.2
  r3 readme               v6.3
  r4 readme               v6.4
  F  fix io               v6.5-rc1  Fixes: B, Cc: stable; io.c line 10
  U  untagged io cleanup            new file cleanup.c
  V  fix with unknown fixes         Fixes: 000000000000; new file other.c
Tree repo: mainline plus G (fix more io) on branch for-next only.
Next repo: mainline.
Stable: linux-6.N.y from v6.N plus v6.N.1; 6.2 carries a cherry-pick of F.
Queue: queue-6.3 (io-other-hunk.patch, io.c line 50), queue-6.4 (fix-io.patch).
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from patchtrail.config import KernelUrls

DATA = Path(__file__).parent / "data"
ME = ("Me", "me@example.org")
OTHER = ("Other", "o@x.org")


def _io(rewrite: bool = False, fixed: bool = False, bug: bool = True, other: bool = False) -> str:
    lines = [f"int line_{i:02d};" for i in range(1, 61)]
    if bug:
        lines[9] = "int line_10_bug;"
    if rewrite:
        for i in range(4, 16):
            lines[i] = f"int rewritten_{i + 1:02d};"
        if bug:
            lines[9] = "int rewritten_10_bug;"
    if fixed:
        lines[9] = "int rewritten_10_fixed;"
    if other:
        lines[49] = "int line_50_other;"
    return "\n".join(lines) + "\n"


class _Builder:
    def __init__(self, base: Path):
        self.base = base
        self.day = 0
        cfg = base / "gitconfig"
        cfg.write_text("")
        self.env = {**os.environ, "GIT_CONFIG_GLOBAL": str(cfg), "GIT_CONFIG_NOSYSTEM": "1"}

    def git(self, repo: Path, *args, env=None, input=None) -> str:
        p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                           env={**self.env, **(env or {})}, input=input)
        if p.returncode:
            raise RuntimeError(f"git {' '.join(args)}: {p.stderr}")
        return p.stdout.strip()

    def init(self, path: Path) -> Path:
        path.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "master", str(path)], check=True, env=self.env)
        return path

    def clone(self, src: Path, dst: Path) -> Path:
        subprocess.run(["git", "clone", "-q", str(src), str(dst)], check=True, env=self.env,
                       capture_output=True)
        return dst

    def _stamp(self, who) -> dict:
        self.day += 1
        date = f"2026-01-{self.day + 1:02d}T12:00:00Z" if self.day < 30 else \
            f"2026-02-{self.day - 29:02d}T12:00:00Z"
        return {"GIT_AUTHOR_NAME": who[0], "GIT_AUTHOR_EMAIL": who[1], "GIT_AUTHOR_DATE": date,
                "GIT_COMMITTER_NAME": who[0], "GIT_COMMITTER_EMAIL": who[1], "GIT_COMMITTER_DATE": date}

    def commit(self, repo: Path, files: dict[str, str], msg: str, who=ME, tag=None) -> str:
        for name, text in files.items():
            (repo / name).write_text(text)
            self.git(repo, "add", name)
        self.git(repo, "commit", "-q", "-m", msg, env=self._stamp(who))
        sha = self.git(repo, "rev-parse", "HEAD")
        if tag:
            self.git(repo, "tag", tag)
        return sha


@dataclass
class KernelFixture:
    mainline: Path
    stable: Path
    queue: Path
    next: Path
    tree: Path
    urls: KernelUrls
    sha: dict[str, str]
    tree_url: str


def make_kernel_fixture(tmp: Path) -> KernelFixture:
    b = _Builder(tmp)
    tree_path = tmp / "tree"
    tree_url = tree_path.as_uri()
    ml = b.init(tmp / "mainline")
    sha: dict[str, str] = {}
    maint = f"MAINTAINERS\n\nIO\nF:\tio.c\nT:\tgit {tree_url}\n"
    sha["A"] = b.commit(ml, {"io.c": _io(bug=False), "MAINTAINERS": maint, "README": "0\n"},
                        "init io", tag="v6.0")
    sha["B"] = b.commit(ml, {"io.c": _io()}, "add bug", tag="v6.1-rc1")
    b.commit(ml, {"README": "1\n"}, "readme 6.1", tag="v6.1")
    sha["R"] = b.commit(ml, {"io.c": _io(rewrite=True)}, "refactor io", who=OTHER, tag="v6.2-rc1")
    for n in (2, 3, 4):
        b.commit(ml, {"README": f"{n}\n"}, f"readme 6.{n}", tag=f"v6.{n}")
    sha["F"] = b.commit(
        ml, {"io.c": _io(rewrite=True, fixed=True)},
        f'fix io\n\nFixes: {sha["B"][:12]} ("add bug")\nCc: stable@vger.kernel.org\n', tag="v6.5-rc1")
    sha["U"] = b.commit(ml, {"cleanup.c": "int cleanup;\n"}, "untagged io cleanup")
    sha["V"] = b.commit(ml, {"other.c": "int other;\n"},
                        'fix with unknown fixes\n\nFixes: 000000000000 ("nothing")\n')

    nxt = b.clone(ml, tmp / "next")
    tree = b.clone(ml, tree_path)
    b.git(tree, "checkout", "-q", "-b", "for-next")
    sha["G"] = b.commit(tree, {"io.c": _io(rewrite=True, fixed=True, other=True).replace(
        "int rewritten_12;", "int rewritten_12_more;")}, "fix more io")

    st = b.clone(ml, tmp / "stable")
    for n in range(5):
        b.git(st, "checkout", "-q", "-B", f"linux-6.{n}.y", f"v6.{n}")
        if n == 2:
            b.git(st, "cherry-pick", sha["F"], env=b._stamp(ME))
            subject = b.git(st, "log", "-1", "--format=%s")
            rest = b.git(st, "log", "-1", "--format=%b")
            b.git(st, "commit", "-q", "--amend", "-m",
                  f'{subject}\n\ncommit {sha["F"]} upstream.\n\n{rest}\n', env=b._stamp(ME))
            sha["F62"] = b.git(st, "rev-parse", "HEAD")
            b.git(st, "tag", "v6.2.1")
        else:
            b.commit(st, {"README": f"stable {n}\n"}, f"stable 6.{n}.1", tag=f"v6.{n}.1")

    # queue: patches generated from real commits
    scratch = b.clone(ml, tmp / "scratch")
    b.git(scratch, "checkout", "-q", "v6.3")
    b.commit(scratch, {"io.c": _io(rewrite=True, other=True)}, "other hunk")
    other_patch = b.git(scratch, "format-patch", "-1", "--stdout") + "\n"
    fix_patch = b.git(st, "format-patch", "-1", sha["F62"], "--stdout") + "\n"
    q = b.init(tmp / "queue")
    (q / "queue-6.3").mkdir()
    (q / "queue-6.4").mkdir()
    b.commit(q, {"queue-6.3/series": "io-other-hunk.patch\n",
                 "queue-6.3/io-other-hunk.patch": other_patch,
                 "queue-6.4/series": "fix-io.patch\n",
                 "queue-6.4/fix-io.patch": fix_patch}, "queue")

    urls = KernelUrls(mainline=ml.as_uri(), stable=st.as_uri(), queue=q.as_uri(),
                      next=nxt.as_uri(), releases=(DATA / "releases.json").as_uri())
    return KernelFixture(ml, st, q, nxt, tree, urls, sha, tree_url)


@dataclass
class UpstreamFixture:
    url: str
    sha: str


def make_upstream_fixture(tmp: Path) -> UpstreamFixture:
    """A small project: init (v1.0), then Me's `lib: follow symlinks ...` dated
    2026-09-21, then a later commit (v1.1)."""
    b = _Builder(tmp)
    repo = b.init(tmp / "upstream")
    b.commit(repo, {"README": "0\n"}, "init", tag="v1.0")
    (repo / "lib.c").write_text("int lib;\n")
    b.git(repo, "add", "lib.c")
    date = "2026-09-21T12:00:00Z"
    stamp = {"GIT_AUTHOR_NAME": ME[0], "GIT_AUTHOR_EMAIL": ME[1], "GIT_AUTHOR_DATE": date,
             "GIT_COMMITTER_NAME": ME[0], "GIT_COMMITTER_EMAIL": ME[1], "GIT_COMMITTER_DATE": date}
    b.git(repo, "commit", "-q", "-m", "lib: follow symlinks on intermediate tar path components",
          env=stamp)
    sha = b.git(repo, "rev-parse", "HEAD")
    (repo / "README").write_text("1\n")
    b.git(repo, "add", "README")
    b.git(repo, "commit", "-q", "-m", "release 1.1",
          env={k: v.replace("09-21", "10-01") for k, v in stamp.items()})
    b.git(repo, "tag", "v1.1")
    return UpstreamFixture(url=repo.as_uri(), sha=sha)


def make_stable_watch_clone(kfix: KernelFixture, dest: Path) -> Path:
    """A bare clone shaped like stable-watch's linux.git: fully packed, every ref
    under refs/stable-watch/ (mainline, linux-X.Y.y, tags/), none under heads or tags."""
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1"}

    def git(*args):
        subprocess.run(["git", "-C", str(dest), *args], check=True, env=env, capture_output=True)

    subprocess.run(["git", "init", "-q", "--bare", str(dest)], check=True, env=env)
    git("fetch", "-q", "--no-tags", str(kfix.mainline),
        "+refs/heads/master:refs/stable-watch/mainline", "+refs/tags/*:refs/stable-watch/tags/*")
    git("fetch", "-q", "--no-tags", str(kfix.stable),
        "+refs/heads/linux-*:refs/stable-watch/linux-*", "+refs/tags/*:refs/stable-watch/tags/*")
    git("repack", "-q", "-a", "-d")
    git("pack-refs", "--all")
    git("commit-graph", "write", "--reachable")
    return dest
