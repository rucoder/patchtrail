# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchtrail.sources.lore import Entry


class Source(ABC):
    @abstractmethod
    def fetch(self, root_msgid: str) -> list[bytes]:
        """Return the raw messages of the thread rooted at root_msgid."""

    @abstractmethod
    def discover(self, addresses: list[str], since: int | None) -> list[Entry]:
        """Return the patch threads started by addresses since the epoch time."""
