# SPDX-License-Identifier: Apache-2.0
import subprocess

import pytest

from patchtrail import cli, db, store
from patchtrail.config import load_config, paths
from patchtrail.setup import git_version_ok, run_setup, write_default_config


def test_git_version():
    assert git_version_ok("git version 2.43.0") == (True, "2.43.0")
    assert git_version_ok("git version 2.39.1") == (
        False, "patchtrail needs git >= 2.40 (found 2.39.1)")
    assert git_version_ok("git version 2.45.2.windows.1")[0] is True
    assert git_version_ok()[0] is True


def test_old_git_fails_setup(monkeypatch, capsys):
    monkeypatch.setattr("patchtrail.setup.git_version_ok",
                        lambda out=None: (False, "patchtrail needs git >= 2.40 (found 2.1.0)"))
    assert run_setup(seed=None, no_seed=True, do_import=False) == 1
    assert "patchtrail needs git >= 2.40 (found 2.1.0)" in capsys.readouterr().err
    assert not paths().home.exists()


def test_default_config_loads_back():
    p = paths()
    p.home.mkdir(parents=True)
    assert write_default_config(p, ["me@example.org", "me@work.org"]) is True
    cfg = load_config(p)
    assert cfg.addresses == ["me@example.org", "me@work.org"]
    assert cfg.listen == "0.0.0.0:8470" and cfg.interval_hours == 3
    assert cfg.seed is None
    text = p.config.read_text()
    assert "# seed" in text and "# [kernel]" in text
    assert write_default_config(p, ["x@y.org"]) is False


def test_setup_seeds_and_imports(kfix, old_scripts_home, capsys):
    refs = lambda: subprocess.run(["git", "-C", str(kfix.mainline), "for-each-ref"],
                                  capture_output=True, text=True).stdout
    before = refs()
    assert run_setup(seed=kfix.mainline, no_seed=False, do_import=None) == 0
    p = paths()
    assert p.config.exists() and (p.linux / "HEAD").exists()
    out = capsys.readouterr().out
    assert f"seeding from {kfix.mainline} (hardlinks, no copy)" in out
    assert "ptl fetch" in out and "ptl status" in out
    assert store.list_patches(db.connect(p.db))                       # old threads imported
    assert refs() == before
    assert "me@example.org" in p.config.read_text()


def test_setup_default_seed_from_state_dir(kfix, hermetic, capsys):
    seed = hermetic / ".local" / "state" / "stable-watch" / "linux.git"
    seed.parent.mkdir(parents=True)
    subprocess.run(["git", "clone", "-q", "--bare", str(kfix.mainline), str(seed)], check=True)
    assert run_setup(seed=None, no_seed=False, do_import=None) == 0
    assert f"seeding from {seed}" in capsys.readouterr().out
    assert (paths().linux / "HEAD").exists()


def test_setup_no_import_without_old_threads(kfix, capsys):
    assert run_setup(seed=None, no_seed=True, do_import=None) == 0
    assert "seeding" not in capsys.readouterr().out
    assert store.list_patches(db.connect(paths().db)) == []


def test_setup_no_import_flag(old_scripts_home):
    assert run_setup(seed=None, no_seed=True, do_import=False) == 0
    assert store.list_patches(db.connect(paths().db)) == []


def test_setup_twice_keeps_config(kfix):
    run_setup(seed=None, no_seed=True, do_import=False)
    paths().config.write_text('addresses = ["x@y.org"]\n')
    run_setup(seed=None, no_seed=True, do_import=False)
    assert paths().config.read_text() == 'addresses = ["x@y.org"]\n'


def test_setup_does_not_reseed(kfix, capsys):
    run_setup(seed=kfix.mainline, no_seed=False, do_import=False)
    capsys.readouterr()
    assert run_setup(seed=kfix.mainline, no_seed=False, do_import=False) == 0
    assert "seeding" not in capsys.readouterr().out


def test_setup_command(kfix, capsys):
    assert cli.main(["setup", "--no-seed", "--no-import"]) == 0
    assert paths().config.exists()
    with pytest.raises(SystemExit):
        cli.main(["setup", "--seed", str(kfix.mainline), "--no-seed"])


@pytest.mark.parametrize("kind", ["missing", "plain-dir"])
def test_bad_seed_fails_cleanly(tmp_path, capsys, kind):
    seed = tmp_path / "seed"
    if kind == "plain-dir":
        seed.mkdir()
    assert run_setup(seed=seed, no_seed=False, do_import=False) == 1
    cap = capsys.readouterr()
    assert f"ptl: cannot seed from {seed}:" in cap.err
    assert "Traceback" not in cap.err + cap.out
    assert not paths().linux.exists()
    assert not paths().config.exists()


def test_failed_ensure_removes_partial_clone(kfix, monkeypatch, capsys):
    from patchtrail.projects.kernel.repo import GitError, KernelRepo

    def boom(self, seed):
        self.path.mkdir(parents=True)
        raise GitError("clone broke")

    monkeypatch.setattr(KernelRepo, "ensure", boom)
    assert run_setup(seed=kfix.mainline, no_seed=False, do_import=False) == 1
    assert "ptl: cannot seed from" in capsys.readouterr().err
    assert not paths().linux.exists()


def test_setup_twice_with_old_scripts(kfix, old_scripts_home, capsys):
    from patchtrail import snapshot

    def counts():
        c = db.connect(paths().db)
        rows = store.list_patches(c)
        return (len(rows), [len(store.revisions(c, r["id"])) for r in rows],
                [len(store.patch_mails(c, r["id"])) for r in rows],
                c.execute("SELECT count(*) FROM snapshots").fetchone()[0],
                [bool(snapshot.unread(c, r["id"])) for r in rows])

    assert run_setup(seed=None, no_seed=True, do_import=None) == 0
    first = counts()
    assert first[0] == 1
    assert "imported 1 patches" in capsys.readouterr().out
    assert run_setup(seed=None, no_seed=True, do_import=None) == 0
    assert counts() == first
    assert "nothing new to import (1 already tracked)" in capsys.readouterr().out
