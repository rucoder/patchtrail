# SPDX-License-Identifier: Apache-2.0
"""Find a patch's commits past the list: the maintainer's "Applied" reply, a
search by subject and author, and the trees MAINTAINERS names for its files."""

import re
from fnmatch import fnmatchcase

from patchtrail.mail import MailInfo
from patchtrail.projects.kernel.repo import MAINLINE, Git

_PREFIX = re.compile(r"(?:\[[^\]]*\]|re:)\s*", re.I)
_GLOB = re.compile(r"[*?\[]")
_TAG = re.compile(r"([A-Z]):\s*(.*)")


def commits_from_mail(mails: list[MailInfo], mine: frozenset[str]) -> list[tuple[str, str]]:
    """(subject, sha) of the "Applied" replies not sent by the user, first one first."""
    out, seen = [], set()
    for m in mails:
        if m.from_addr in mine:
            continue
        for subject, sha in m.applied_commits:
            if sha not in seen:
                seen.add(sha)
                out.append((subject, sha))
    return out


def strip_subject(s: str) -> str:
    """The subject without leading [PATCH ...] groups and Re:, whitespace collapsed."""
    s = " ".join(s.split())
    while (m := _PREFIX.match(s)):
        s = s[m.end():]
    return s


def search_commit(repo: Git, subject: str, author: str, since: int, refs: list[str]) -> str | None:
    """The newest commit on refs by author, dated at most a day before since, whose
    subject is the patch's. Refs the repository does not have are left out."""
    want = strip_subject(subject)
    refs = [r for r in refs if repo.resolve(r)]
    if not want or not author or not refs:
        return None
    out = repo.run("log", "-F", "-i", f"--since=@{max(since - 86400, 0)}", f"--author={author}",
                   "--format=%H%x00%s", *refs, "--")
    for line in out.splitlines():
        sha, _, s = line.partition("\0")
        if " ".join(s.split()) == want:
            return sha
    return None


def matches(pattern: str, path: str) -> bool:
    """Whether a MAINTAINERS F: pattern covers path."""
    if _GLOB.search(pattern):
        return fnmatchcase(path, pattern + "*" if pattern.endswith("/") else pattern)
    if pattern.endswith("/"):
        return path.startswith(pattern)
    return path == pattern or path.startswith(pattern + "/")


def maintainer_trees(repo: Git, files: list[str]) -> list[str]:
    """The `T: git` URLs of mainline's MAINTAINERS entries covering any of files."""
    text = repo.run("show", f"{MAINLINE}:MAINTAINERS", ok=(0, 128))
    urls: list[str] = []
    patterns: list[str] = []
    trees: list[str] = []
    for line in text.splitlines() + [""]:
        m = _TAG.match(line)
        if m:
            tag, value = m.groups()
            words = value.split()
            if tag == "F" and words:
                patterns.append(words[0])
            elif tag == "T" and len(words) > 1 and words[0] == "git":
                trees.append(words[1])          # a branch word after the URL is ignored
            continue
        # A blank line or the next entry's title ends the entry.
        if trees and any(matches(p, f) for p in patterns for f in files):
            urls += [u for u in trees if u not in urls]
        patterns, trees = [], []
    return urls
