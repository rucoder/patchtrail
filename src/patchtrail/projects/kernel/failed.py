# SPDX-License-Identifier: Apache-2.0
"""stable's "FAILED: patch ... failed to apply" mails (port of stable-watch)."""

import re

from patchtrail.sources import lore


def failed_mails(subject: str, *, search=lore.search) -> dict[str, dict]:
    """{series: {"date", "url"}} of stable's FAILED mails for a commit subject.
    No results (lore's 404) give {}; a failed search raises LoreError."""
    words = subject.split(": ")[-1]
    out: dict[str, dict] = {}
    for e in search("stable", f's:"FAILED: patch" AND s:"{words}"'):
        m = re.search(r"failed to apply to (\S+)-stable tree", e.subject)
        # Replies to the FAILED mail match too; the date and link are the FAILED mail's.
        if m and subject in e.subject and not e.subject.lower().startswith("re:"):
            out.setdefault(m.group(1), {"date": e.updated[:10], "url": e.href})
    return out
