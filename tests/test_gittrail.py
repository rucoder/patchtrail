from conftest import NullProgress, epoch

from patchtrail.config import load_config, paths
from patchtrail.projects.gittrail import GitTrail

SUBJECT = "lib: follow symlinks on intermediate tar path components"


def trail(url, **kw):
    return GitTrail(paths(), load_config(paths()), "erofs-utils", repo=url, branch="master", **kw)


def run(t, v):
    t.prepare([v], NullProgress())
    return t.evaluate(v, NullProgress())


def test_found_and_released(upfix, view):
    v = view(project="erofs-utils", subject=f"[PATCH v2] erofs-utils: {SUBJECT}",
             author="me@example.org", posted_at=epoch("2026-09-20"))
    r = run(trail(upfix.url), v)
    assert r.fragment["commits"] == [{
        "sha": upfix.sha, "subject": SUBJECT, "where": "upstream", "stage": "released",
        "release": "v1.1", "stable": False, "cc": None, "fixes": []}]
    assert r.fragment["branches"] == {} and r.fragment["failed"] == {}
    assert r.commits_found == [(upfix.sha, SUBJECT, "search")]


def test_other_author_not_matched(upfix, view):
    v = view(project="erofs-utils", subject=f"[PATCH] {SUBJECT}",
             author="someone@else.org", posted_at=epoch("2026-09-20"))
    assert run(trail(upfix.url), v).fragment["commits"] == []


def test_stored_commit_and_applied_stage(upfix, view):
    # No tag contains the commit: tags pattern matches nothing.
    v = view(project="erofs-utils", subject="x", commits=[{"sha": upfix.sha, "subject": "", "source": "manual"}])
    c = run(trail(upfix.url, tags="none-*"), v).fragment["commits"][0]
    assert (c["stage"], c["release"], c["where"]) == ("applied", None, "upstream")


def test_dead_url_does_not_raise(tmp_path, view):
    logs = []

    class P(NullProgress):
        def log(self, line):
            logs.append(line)

    v = view(project="erofs-utils", subject=SUBJECT)
    t = trail((tmp_path / "nope").as_uri())
    t.prepare([v], P())
    assert logs
    assert t.evaluate(v, P()).fragment["commits"] == []


def test_config_override(upfix, view):
    cfg = load_config(paths())
    cfg.projects["erofs-utils"] = {"repo": upfix.url, "branch": "master"}
    t = GitTrail(paths(), cfg, "erofs-utils", repo="file:///nonexistent", branch="dev")
    v = view(project="erofs-utils", subject=SUBJECT, posted_at=epoch("2026-09-20"))
    assert run(t, v).fragment["commits"][0]["release"] == "v1.1"


def test_commit_subject_keeps_project_prefix(tmp_path, view):
    from gitfix import ME, _Builder

    b = _Builder(tmp_path)
    repo = b.init(tmp_path / "up")
    b.commit(repo, {"a": "1\n"}, "init", tag="v1.0")
    (repo / "b").write_text("x\n")
    b.git(repo, "add", "b")
    stamp = {f"GIT_{w}_{k}": v for w in ("AUTHOR", "COMMITTER")
             for k, v in (("NAME", ME[0]), ("EMAIL", ME[1]), ("DATE", "2026-09-21T12:00:00Z"))}
    b.git(repo, "commit", "-q", "-m", f"erofs-utils: {SUBJECT}", env=stamp)
    v = view(project="erofs-utils", subject=f"[PATCH] erofs-utils: {SUBJECT}",
             posted_at=epoch("2026-09-20"))
    c = run(trail(repo.as_uri()), v).fragment["commits"]
    assert [(x["where"], x["stage"]) for x in c] == [("upstream", "applied")]
