# SPDX-License-Identifier: Apache-2.0
import pytest

from patchtrail.projects.kernel.stable import branch_status, stable_tags


@pytest.mark.parametrize("series,state,tag", [
    ("6.0", "not_affected", None), ("6.1", "conflict", None), ("6.2", "released", "v6.2.1"),
    ("6.3", "applies_after_queue", None), ("6.4", "queued", None)])
def test_branch_states(fetched, queue, kfix, series, state, tag):
    F, B = kfix.sha["F"], kfix.sha["B"]
    r = branch_status(fetched, queue, F, ["io.c"], [B], series)
    assert (r.state, r.tag) == (state, tag)


def test_conflict_prereqs(fetched, queue, kfix):
    r = branch_status(fetched, queue, kfix.sha["F"], ["io.c"], [kfix.sha["B"]], "6.1")
    assert r.detail[0] == "CONFLICT in io.c: needs a backport by hand"
    assert [(p.sha, p.subject, p.tag, p.cc, p.fixes) for p in r.prereqs] == \
           [(kfix.sha["R"], "refactor io", "v6.2-rc1", None, ())]


def test_detail_wording(fetched, queue, kfix):
    r = branch_status(fetched, queue, kfix.sha["F"], ["io.c"], [kfix.sha["B"]], "6.3")
    assert r.detail == ["applies cleanly, after 1 queued patch to the same files"]
    r = branch_status(fetched, queue, kfix.sha["F"], ["io.c"], [kfix.sha["B"]], "6.4")
    assert r.detail == ["queued for the next 6.4 release: fix-io.patch"]


def test_stable_tags():
    assert stable_tags("x\nCc: stable@vger.kernel.org # 6.1+\nFixes: abcdef123456 (\"y\")\n") == ("6.1+", ["abcdef123456"])
    assert stable_tags("no tags\n") == (None, [])
