"""The stable-queue: patches queued for the stable branches."""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from patchtrail.projects.base import Progress
from patchtrail.projects.kernel.repo import Git, GitError, net_env


@dataclass(frozen=True)
class QueuedPatch:
    name: str
    text: str
    files: frozenset[str]


class StableQueue(Git):
    def __init__(self, path: Path):
        super().__init__(path)
        self._cache: dict[str, list[QueuedPatch]] = {}

    def update(self, url: str, progress: Progress) -> None:
        progress.step("stable-queue")
        self._cache.clear()
        if (self.path / ".git").is_dir():
            self.run("fetch", "-q", "--depth", "1", "origin", "master", env=net_env())
            self.run("reset", "-q", "--hard", "FETCH_HEAD")
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        p = subprocess.run(["git", "clone", "-q", "--depth", "1", "--sparse", url, str(self.path)],
                           capture_output=True, text=True, env=net_env())
        if p.returncode:
            raise GitError(f"git clone {url}: {p.stderr.strip()}")
        self.run("sparse-checkout", "set", "--no-cone", "/queue-*/")

    def patches(self, series: str) -> list[QueuedPatch]:
        """The patches of queue-SERIES in series order."""
        if series not in self._cache:
            d = self.path / f"queue-{series}"
            out = []
            if d.is_dir():
                if (d / "series").exists():
                    order = [ln.strip() for ln in (d / "series").read_text(errors="replace").splitlines()
                             if ln.strip() and not ln.startswith("#")]
                else:
                    order = sorted(f.name for f in d.iterdir() if f.name.endswith(".patch"))
                for name in order:
                    path = d / name
                    if not path.exists():
                        continue
                    text = path.read_text(errors="replace")
                    files = frozenset(re.findall(r"^\+\+\+ b/(\S+)", text, re.M))
                    out.append(QueuedPatch(name, text, files))
            self._cache[series] = out
        return self._cache[series]

    def queued(self, series: str, sha: str) -> list[str]:
        """Names of the queued patches that are a backport of sha."""
        key = sha[:12]
        return [p.name for p in self.patches(series)
                if re.search(rf"(?i)commit {key}|upstream.{{0,12}}{key}", p.text)]
