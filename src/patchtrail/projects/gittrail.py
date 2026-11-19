# SPDX-License-Identifier: Apache-2.0
"""The trail of a small project: find the patch in the project's own repository
by subject and author, then the first release tag containing it."""

import re
import subprocess

from patchtrail.config import Config, Paths
from patchtrail.projects.base import PatchView, Progress, Trail, TrailResult
from patchtrail.projects.kernel.follow import search_commit, strip_subject
from patchtrail.projects.kernel.repo import REFS, Git, GitError, net_env

UPSTREAM = f"{REFS}/upstream"
TAGS = f"{REFS}/tags"


class GitTrail(Trail):
    def __init__(self, paths: Paths, cfg: Config, project: str, *, repo: str, branch: str,
                 tags: str = "v*"):
        over = cfg.projects.get(project, {})
        self.project = project
        self.url = over.get("repo", repo)
        self.branch = over.get("branch", branch)
        self.tags = over.get("tags", tags)
        self.repo = Git(paths.git / f"{project}.git")
        self._tag_list: list[str] | None = None

    def prepare(self, patches: list[PatchView], progress: Progress) -> None:
        self._tag_list = None
        progress.step(self.project)
        try:
            if not self.repo.path.is_dir():
                self.repo.path.parent.mkdir(parents=True, exist_ok=True)
                p = subprocess.run(["git", "init", "-q", "--bare", str(self.repo.path)],
                                   capture_output=True, text=True)
                if p.returncode:
                    raise GitError(f"git init: {p.stderr.strip()}")
            self.repo.run("fetch", "-q", "--no-tags", self.url,
                          f"+refs/heads/{self.branch}:{UPSTREAM}",
                          f"+refs/tags/{self.tags}:{TAGS}/{self.tags}", env=net_env())
        except (GitError, OSError) as e:
            progress.log(f"{self.project} {self.url}: {e}")

    def _release_tags(self) -> list[str]:
        """Release tags, oldest first: each contains the ones before it."""
        if self._tag_list is None:
            if not self.repo.path.is_dir():
                return []
            out = self.repo.run("-c", "versionsort.suffix=-rc", "for-each-ref",
                                "--sort=v:refname", "--format=%(refname)", f"{TAGS}/")
            self._tag_list = out.split()
        return self._tag_list

    def _first_tag(self, commit: str) -> str | None:
        tags = self._release_tags()
        lo, hi = 0, len(tags)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.repo.is_ancestor(commit, tags[mid]):
                hi = mid
            else:
                lo = mid + 1
        return tags[lo][len(TAGS) + 1:] if lo < len(tags) else None

    def _subjects(self, patch: PatchView) -> list[str]:
        """The subject to look for: without the `<project>: ` prefix, then with
        it (erofs-utils commits keep the prefix, some projects' do not)."""
        s = strip_subject(patch.subject)
        bare = re.sub(rf"^{re.escape(self.project)}:\s*", "", s, flags=re.I)
        return [bare] if bare == s else [bare, s]

    def evaluate(self, patch: PatchView, progress: Progress) -> TrailResult:
        result = TrailResult()
        if not self.repo.path.is_dir():
            result.fragment = {"commits": [], "branches": {}, "failed": {}, "hint": None}
            return result
        known = [(c["sha"], c.get("subject") or "") for c in patch.commits]
        if not known:
            sha = next(filter(None, (search_commit(self.repo, s, patch.author, patch.posted_at,
                                                   [UPSTREAM]) for s in self._subjects(patch))), None)
            if sha:
                known = [(sha, "")]
                result.commits_found.append(
                    (sha, self.repo.run("log", "-1", "--format=%s", sha).strip(), "search"))
        commits = []
        for sha, subject in known:
            full = self.repo.resolve(sha)
            if not full or not self.repo.is_ancestor(full, UPSTREAM):
                commits.append({"sha": sha, "subject": subject, "where": "missing",
                                "stage": "accepted", "release": None, "stable": False,
                                "cc": None, "fixes": []})
                continue
            release = self._first_tag(full)
            commits.append({"sha": full, "subject": self.repo.run("log", "-1", "--format=%s", full).strip(),
                            "where": "upstream", "stage": "released" if release else "applied",
                            "release": release, "stable": False, "cc": None, "fixes": []})
        result.fragment = {"commits": commits, "branches": {}, "failed": {}, "hint": None}
        return result
