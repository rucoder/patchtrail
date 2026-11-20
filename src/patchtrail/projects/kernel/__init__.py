# SPDX-License-Identifier: Apache-2.0
"""The kernel trail: a patch's commits in the maintainer's tree, linux-next,
mainline and every maintained stable branch."""

from pathlib import Path

from patchtrail.config import Config, Paths, my_addresses
from patchtrail.projects.base import PatchView, Progress, Trail, TrailResult
from patchtrail.projects.kernel.failed import failed_mails
from patchtrail.projects.kernel.follow import commits_from_mail, maintainer_trees, search_commit
from patchtrail.projects.kernel.queue import StableQueue
from patchtrail.projects.kernel.repo import (MAINLINE, NEXT, KernelRepo, branches,
                                             fetch_releases, slug, stable_ref, tree_ref)
from patchtrail.projects.kernel.stable import branch_status, in_branch, stable_tags
from patchtrail.sources import lore

HINT = "not tagged for stable: ask stable@vger.kernel.org"


class KernelTrail(Trail):
    def __init__(self, paths: Paths, cfg: Config, *, search=lore.search, urlopen=None):
        self.cfg = cfg
        self.search = search
        self.urlopen = urlopen
        self.repo = KernelRepo(paths.linux)
        self.queue = StableQueue(paths.queue)
        self.mine = my_addresses(cfg)
        self.series: list[str] = []
        # patch id -> the (url, branch) trees fetched for it this run; "*" is every branch
        self._trees: dict[str, list[tuple[str, str]]] = {}
        # patch id -> its commit found in linux-next or mainline by subject this run
        self._upstream_found: dict[str, str] = {}

    # --- prepare ------------------------------------------------------------

    def prepare(self, patches: list[PatchView], progress: Progress) -> None:
        k = self.cfg.kernel
        self.series = branches(fetch_releases(k, urlopen=self.urlopen))
        self.repo.ensure(Path(self.cfg.seed).expanduser() if self.cfg.seed else None)
        self.repo.fetch(k, self.series, [], progress)
        # Trees second: which ones a patch needs depends on what mainline and next hold.
        upstream = {slug(u) for u in (k.mainline, k.next, k.stable)}
        self._upstream_found = {}
        self._trees = {p.id: self._trees_for(p, upstream) for p in patches}
        wanted = list(dict.fromkeys(t for ts in self._trees.values() for t in ts))
        every = {u for u, b in wanted if b == "*"}
        wanted = [(u, b) for u, b in wanted if b == "*" or u not in every]
        if wanted:
            self.repo.fetch_trees(wanted, progress)
        self.queue.update(k.queue, progress)

    def _trees_for(self, p: PatchView, upstream: set[str]) -> list[tuple[str, str]]:
        if p.tree and p.tree_source == "manual":
            return [p.tree]
        known = [k[0] for k in self._known(p)]
        if known and all(self._upstream(sha) for sha in known):
            return []
        if not known:
            # Nobody said "Applied": linux-next or mainline may have it under its subject,
            # and then no tree is needed.
            sha = search_commit(self.repo, p.subject, p.author, p.posted_at, [NEXT, MAINLINE])
            if sha:
                self._upstream_found[p.id] = sha
                return []
        if p.tree:
            return [p.tree]
        # Nothing found yet: every tree MAINTAINERS names for the files, but not
        # the "THE REST" entry's mainline again.
        return [(u, "*") for u in maintainer_trees(self.repo, list(p.files))
                if slug(u) not in upstream]

    def _upstream(self, sha: str) -> bool:
        full = self.repo.resolve(sha)
        return bool(full) and (self.repo.is_ancestor(full, MAINLINE)
                               or self.repo.is_ancestor(full, NEXT))

    def _known(self, p: PatchView) -> list[tuple[str, str, str, bool]]:
        """(sha, subject, source, stored) of the patch's stored commits, then of
        those its "Applied" replies name that are not stored yet: a series can
        be applied over several replies."""
        out = [(c["sha"], c.get("subject") or "", c.get("source") or "manual", True)
               for c in p.commits]
        seen = {k[0][:12].lower() for k in out}
        for subject, sha in commits_from_mail(p.mails, self.mine):
            if sha[:12].lower() not in seen:
                seen.add(sha[:12].lower())
                out.append((sha, subject, "applied-mail", False))
        return out

    def _tree_refs(self, p: PatchView) -> list[tuple[str, str, str]]:
        """(ref, url, branch) of the patch's fetched trees."""
        trees = self._trees.get(p.id, [p.tree] if p.tree else [])
        out = []
        for url, branch in trees:
            if branch == "*":
                prefix = tree_ref(slug(url), "")
                out += [(ref, url, ref[len(prefix):]) for ref in
                        self.repo.run("for-each-ref", "--format=%(refname)", prefix).split()]
            elif self.repo.resolve(tree_ref(slug(url), branch)):
                out.append((tree_ref(slug(url), branch), url, branch))
        return out

    # --- evaluate -----------------------------------------------------------

    def evaluate(self, patch: PatchView, progress: Progress) -> TrailResult:
        trees = self._tree_refs(patch)
        refs = [NEXT, MAINLINE] + [ref for ref, _, _ in trees]
        known = self._known(patch)
        if not known:
            sha = (self._upstream_found.get(patch.id)
                   or search_commit(self.repo, patch.subject, patch.author, patch.posted_at, refs))
            known = [(sha, "", "search", False)] if sha else []
        result = TrailResult()
        commits, stable = [], []
        for sha, subject, source, stored in known:
            c, full, tree = self._commit(sha, subject, patch, trees)
            if source != "manual" and c["where"] == "missing":
                # A rebase gives the commit a new hash; a commit that stays
                # missing was dropped from its tree.
                new = search_commit(self.repo, c["subject"], patch.author, patch.posted_at, refs)
                if new and new != full:
                    if stored:
                        result.replaced[full or sha] = new
                    else:
                        source = "search"       # named by this run's mail: nothing stored to replace
                    c, full, tree = self._commit(new, "", patch, trees)
            if any(c["sha"] == seen["sha"] for seen in commits):
                continue                        # one commit named twice (short and full hash)
            commits.append(c)
            if tree and not result.tree:
                result.tree = tree
            if c["stable"] and full:
                stable.append(c)
            if not stored:
                result.commits_found.append((c["sha"], c["subject"], source))
        branches: dict[str, dict] = {}
        for c in stable:
            self._branches(patch, c, branches)
        hint = None
        if (commits and all(c["where"] == "mainline" for c in commits)
                and not any(c["stable"] for c in commits)):
            hint = HINT
        result.fragment = {"commits": commits, "branches": branches,
                           "failed": self._failed(patch, stable, progress), "hint": hint}
        return result

    def _commit(self, sha: str, subject: str, patch: PatchView,
                trees: list[tuple[str, str, str]]) -> tuple[dict, str | None, tuple | None]:
        """The commit's entry, its full hash (None if unknown) and the tree it was found in."""
        full = self.repo.resolve(sha)
        if not full:
            return ({"sha": sha, "subject": subject, "where": "missing", "stage": "accepted",
                     "release": None, "stable": patch.force_stable, "cc": None, "fixes": []},
                    None, None)
        tree = None
        if self.repo.is_ancestor(full, MAINLINE):
            where = "mainline"
        elif self.repo.is_ancestor(full, NEXT):
            where = "next"
        else:
            tree = next(((url, branch) for ref, url, branch in trees
                         if self.repo.is_ancestor(full, ref)), None)
            where = f"tree:{tree[0]} {tree[1]}" if tree else "missing"
        release = self.repo.first_tag(full) if where == "mainline" else None
        stage = "released" if release else "applied" if where == "mainline" else "accepted"
        cc, fixes = stable_tags(self.repo.run("log", "-1", "--format=%B", full))
        fx = []
        for f in fixes:
            target = self.repo.resolve(f)
            fx.append({"sha": target or f, "release": self.repo.first_tag(target) if target else None,
                       "known": bool(target)})
        return ({"sha": full, "subject": self.repo.run("log", "-1", "--format=%s", full).strip(),
                 "where": where, "stage": stage, "release": release,
                 "stable": cc is not None or bool(fixes) or patch.force_stable,
                 "cc": cc, "fixes": fx}, full, tree)

    def _branches(self, patch: PatchView, c: dict, out: dict[str, dict]) -> None:
        full = c["sha"]
        files = self.repo.run("show", "--format=", "--name-only", full).split()
        # An unknown Fixes: commit, or none, means every branch may have the bug.
        known = [f["sha"] for f in c["fixes"] if f["known"]]
        targets = known if c["fixes"] and len(known) == len(c["fixes"]) else []
        for series in self.series:
            if series in patch.skips:
                entry = {"state": "skipped", "tag": None, "detail": [], "prereqs": []}
                was = ((patch.prev_state or {}).get("branches", {}).get(series, {})
                       .get(full[:12]))
                if was is not None and was["state"] != "skipped":
                    entry["was"] = was
                elif was is not None and "was" in was:
                    entry["was"] = was["was"]
            elif series in patch.backports and self._lacks(full, files, series):
                entry = {"state": "backport_sent", "tag": None, "detail": [], "prereqs": []}
            else:
                r = branch_status(self.repo, self.queue, full, files, targets, series)
                entry = {"state": r.state, "tag": r.tag, "detail": r.detail,
                         "prereqs": [{"sha": p.sha, "subject": p.subject, "tag": p.tag,
                                      "cc": p.cc, "fixes": list(p.fixes)} for p in r.prereqs]}
            out.setdefault(series, {})[full[:12]] = entry

    def _lacks(self, full: str, files: list[str], series: str) -> bool:
        """The branch neither has the fix nor has it queued."""
        ref = stable_ref(series)
        if not self.repo.resolve(ref):
            return False
        base = self.repo.run("merge-base", ref, MAINLINE).strip()
        return (not in_branch(self.repo, full, ref, base, files)
                and not self.queue.queued(series, full))

    def _failed(self, patch: PatchView, stable: list[dict], progress: Progress) -> dict:
        failed: dict[str, dict] = {}
        try:
            for c in stable:
                for series, mail in failed_mails(c["subject"], search=self.search).items():
                    failed.setdefault(series, mail)
        except lore.LoreError as e:
            progress.log(f"{patch.name}: FAILED mails: {e}")
            return dict((patch.prev_state or {}).get("failed", {}))
        return failed

    # --- ptl check ----------------------------------------------------------

    def check_commits(self, shas: list[str], progress: Progress) -> list[TrailResult]:
        """Each commit evaluated on its own, every branch shown whatever its tags
        say (stable-watch check). Call prepare([]) first."""
        return [self.evaluate(PatchView(
            id=sha, name=sha, relation="following", project="kernel", mails=[], posted_at=0,
            subject="", author="", commits=[{"sha": sha, "subject": "", "source": "manual"}],
            force_stable=True, skips=frozenset(), manual_applied=False, backports={}), progress)
            for sha in shas]
