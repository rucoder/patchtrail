"""Stages, the data a trail reads and returns, and the Project descriptor."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from patchtrail.config import Config, Paths
from patchtrail.mail import MailInfo

STAGES = ("submitted", "reviewed", "accepted", "applied", "released", "backports")
MAIL_ONLY = STAGES[:3]
GIT = STAGES[:5]


@dataclass
class PatchView:
    id: str
    name: str
    relation: str
    project: str
    mails: list[MailInfo]
    posted_at: int
    subject: str
    author: str
    commits: list[dict]
    force_stable: bool
    skips: frozenset[str]
    manual_applied: bool
    backports: dict[str, list[str]]
    tree: tuple[str, str] | None = None
    tree_source: str | None = None
    prev_state: dict | None = None
    files: tuple[str, ...] = ()       # paths of the `+++ b/` lines of the patch mails


@dataclass
class TrailResult:
    commits_found: list[tuple[str, str, str]] = field(default_factory=list)
    tree: tuple[str, str] | None = None
    fragment: dict = field(default_factory=dict)


class Progress(Protocol):
    def phase(self, name: str, steps: int | None = None) -> None: ...
    def step(self, label: str) -> None: ...
    def log(self, line: str) -> None: ...


class Trail(ABC):
    @abstractmethod
    def prepare(self, patches: list[PatchView], progress: Progress) -> None:
        """Fetch repos once per run."""

    @abstractmethod
    def evaluate(self, patch: PatchView, progress: Progress) -> TrailResult:
        """Follow one patch past the mailing list."""


@dataclass(frozen=True)
class Project:
    name: str
    stages: tuple[str, ...]
    trail: Callable[[Paths, Config], Trail] | None
