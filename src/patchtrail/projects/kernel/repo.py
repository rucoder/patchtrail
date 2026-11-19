# SPDX-License-Identifier: Apache-2.0
"""The kernel git repository: namespaced refs, release tags, first-release lookups."""

import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

from patchtrail.config import KernelUrls
from patchtrail.projects.base import Progress

REFS = "refs/patchtrail"
MAINLINE = f"{REFS}/mainline"
NEXT = f"{REFS}/next"
TAGS = f"{REFS}/tags"


def stable_ref(series: str) -> str:
    return f"{REFS}/linux-{series}.y"


def tree_ref(slug: str, branch: str) -> str:
    return f"{REFS}/trees/{slug}/{branch}"


def slug(url: str) -> str:
    """The URL path with `/` and `.` turned into `-`."""
    return re.sub(r"[/.]", "-", urlparse(url).path)


class GitError(Exception):
    pass


def net_env() -> dict[str, str]:
    """The environment of a git call that reaches a remote: never wait on a
    credential prompt (a missing GitHub repository answers 401 and git asks on
    the terminal), and abort an HTTP transfer stalled for a minute."""
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0",
            "GIT_HTTP_LOW_SPEED_LIMIT": "1000", "GIT_HTTP_LOW_SPEED_TIME": "60"}


class Git:
    def __init__(self, path: Path):
        self.path = Path(path)

    def run(self, *args, env=None, input=None, ok=(0,), cwd=None) -> str:
        """stdout of a git command in the repository; GitError on other exit codes."""
        p = subprocess.run(["git", "-C", str(cwd or self.path), *args],
                           capture_output=True, text=True, env=env, input=input)
        if p.returncode not in ok:
            raise GitError(f"git {' '.join(args)}: {p.stderr.strip()}")
        return p.stdout

    def ok(self, *args, env=None) -> bool:
        return subprocess.run(["git", "-C", str(self.path), *args],
                              capture_output=True, env=env).returncode == 0

    def resolve(self, rev) -> str | None:
        """Full hash of a commit, or None if the repository does not have it."""
        out = subprocess.run(["git", "-C", str(self.path), "rev-parse", "-q", "--verify",
                              f"{rev}^{{commit}}"], capture_output=True, text=True)
        return out.stdout.strip() or None

    def is_ancestor(self, a, b) -> bool:
        return self.ok("merge-base", "--is-ancestor", a, b)

    def no_auto_gc(self) -> None:
        """Keep git from repacking on its own (gc --auto, maintenance --auto after a
        fetch): a repack in the middle of a run takes minutes and un-shares packs
        hardlinked from a seed, gigabytes more on disk. Writes only what differs."""
        for key, value in (("gc.auto", "0"), ("maintenance.auto", "false")):
            if self.run("config", "--local", "--get", key, ok=(0, 1)).strip() != value:
                self.run("config", "--local", key, value)


class KernelRepo(Git):
    def __init__(self, path: Path):
        super().__init__(path)
        self._tags: dict[str | None, list[str]] = {}

    def ensure(self, seed: Path | None) -> None:
        if self.path.is_dir():
            self.no_auto_gc()
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not seed:
            self._plain(["git", "init", "-q", "--bare", str(self.path)])
            self.no_auto_gc()
            return
        # A local clone hardlinks the seed's packs. --mirror takes every ref, not
        # only heads and tags: stable-watch keeps all of its under refs/stable-watch/.
        # Only the objects are wanted, but the refs make the first fetch send just
        # what the seed lacks: they move under seed/ and go once the real remotes
        # are fetched.
        self._plain(["git", "clone", "-q", "--mirror", str(seed), str(self.path)])
        self.run("remote", "remove", "origin")
        moves = []
        for line in self.run("for-each-ref", "--format=%(objectname) %(refname)").splitlines():
            oid, ref = line.split(" ", 1)
            moves += [f"create {REFS}/seed/{ref} {oid}", f"delete {ref}"]
        if moves:
            self.run("update-ref", "--stdin", input="\n".join(moves) + "\n")
        # A .keep file leaves a pack out of every repack: the seed's packs stay shared.
        for pack in (self.path / "objects" / "pack").glob("pack-*.pack"):
            pack.with_suffix(".keep").write_text(f"patchtrail: hardlinked from {seed}\n")
        self.no_auto_gc()

    @staticmethod
    def _plain(cmd: list[str]) -> None:
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode:
            raise GitError(f"{' '.join(cmd[:3])}: {p.stderr.strip()}")

    def fetch(self, urls: KernelUrls, series: list[str],
              trees: list[tuple[str, str]], progress: Progress) -> None:
        self._tags.clear()
        progress.step("mainline")
        self._fetch(urls.mainline, f"+refs/heads/master:{MAINLINE}", f"+refs/tags/v*:{TAGS}/v*")
        progress.step("stable")
        specs = []
        for s in series:
            specs += [f"+refs/heads/linux-{s}.y:{stable_ref(s)}",
                      f"+refs/tags/v{s}.*:{TAGS}/v{s}.*"]
        self._fetch(urls.stable, *specs)
        progress.step("linux-next")
        self._fetch(urls.next, f"+refs/heads/master:{NEXT}")
        for url, branch in trees:
            progress.step(f"tree {url} {branch}")
            self._fetch_tree(url, branch)
        seeds = self.run("for-each-ref", "--format=delete %(refname)", f"{REFS}/seed/")
        if seeds:
            self.run("update-ref", "--stdin", input=seeds)
        self._write_graph()

    def fetch_trees(self, trees: list[tuple[str, str]], progress: Progress) -> None:
        """Fetch maintainer trees only; branch "*" is every head. A tree that
        cannot be fetched is logged and keeps its refs from earlier runs."""
        for url, branch in trees:
            progress.step(f"tree {url} {branch}")
            try:
                self._fetch_tree(url, branch)
            except GitError as e:
                progress.log(f"tree {url} {branch}: {e}")
        self._write_graph()

    def _fetch_tree(self, url: str, branch: str) -> None:
        # --prune drops the refs of branches the tree deleted.
        prune = ["--prune"] if branch == "*" else []
        self._fetch(*prune, url, f"+refs/heads/{branch}:{tree_ref(slug(url), branch)}")

    def _fetch(self, *args) -> None:
        self.run("fetch", "-q", "--no-tags", *args, env=net_env())

    def _write_graph(self) -> None:
        # Generation numbers turn each "is A in B?" from a history walk of
        # seconds into milliseconds; --split only adds the new commits.
        self.run("commit-graph", "write", "--reachable", "--split", "--no-progress")

    def release_tags(self, series: str | None = None) -> list[str]:
        """Mainline release tags (v6.4-rc1, v6.4, ...) or those of one stable
        series (v6.12.1, ...), oldest first: each contains the ones before it,
        so the first one containing a commit is a binary search."""
        if series not in self._tags:
            pattern = (rf"v{re.escape(series)}\.(\d+)$" if series
                       else r"v\d+\.\d+(?:-rc\d+)?$")
            refs = self.run("for-each-ref", "--sort=creatordate",
                            "--format=%(refname:lstrip=3)", f"{TAGS}/").split()
            tags = [t for t in refs if re.fullmatch(pattern, t)]
            if series:
                tags.sort(key=lambda t: int(t.rsplit(".", 1)[1]))
            self._tags[series] = tags
        return self._tags[series]

    def first_tag(self, commit: str, series: str | None = None) -> str | None:
        """The first release containing commit: v6.4-rc1, or v6.12.119 with a
        series. None if no release has it yet."""
        tags = self.release_tags(series)
        lo, hi = 0, len(tags)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.is_ancestor(commit, f"{TAGS}/{tags[mid]}"):
                hi = mid
            else:
                lo = mid + 1
        return tags[lo] if lo < len(tags) else None


def branches(releases_json: bytes) -> list[str]:
    """Series of the maintained stable and longterm releases, in file order."""
    out = []
    for r in json.loads(releases_json)["releases"]:
        if r["moniker"] in ("stable", "longterm") and not r["iseol"]:
            out.append(".".join(r["version"].split(".")[:2]))
    return out


def fetch_releases(urls: KernelUrls, *, urlopen=None) -> bytes:
    url = urls.releases
    if url.startswith("file://"):
        return Path(unquote(urlparse(url).path)).read_bytes()
    opener = urlopen or urllib.request.urlopen
    req = urllib.request.Request(url, headers={"User-Agent": "patchtrail"})
    with opener(req, timeout=60) as r:
        return r.read()
