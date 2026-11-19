# SPDX-License-Identifier: Apache-2.0
import os
from pathlib import Path

from patchtrail.cli import main
from patchtrail.config import load_config, my_addresses, paths


def test_paths_follow_env(monkeypatch):
    p = paths()
    assert p.home == Path(os.environ["PATCHTRAIL_HOME"])
    assert p.db == p.home / "patchtrail.db" and p.linux == p.home / "git" / "linux.git"
    monkeypatch.delenv("PATCHTRAIL_HOME")
    assert paths().home == Path(os.environ["HOME"]) / ".patchtrail"


def test_defaults_without_file():
    cfg = load_config(paths())
    assert cfg.listen == "0.0.0.0:8470" and cfg.interval_hours == 3
    assert cfg.kernel.next.endswith("/next/linux-next.git")


def test_kernel_override(tmp_path):
    p = paths()
    p.home.mkdir(parents=True, exist_ok=True)
    p.config.write_text('addresses = ["A@x.org"]\n[kernel]\nmainline = "file:///m"\n')
    cfg = load_config(p)
    assert cfg.kernel.mainline == "file:///m" and cfg.addresses == ["A@x.org"]


def test_my_addresses_order(monkeypatch):
    cfg = load_config(paths())
    assert my_addresses(cfg) == {"me@example.org"}          # from GIT_CONFIG_GLOBAL
    monkeypatch.setenv("PATCHTRAIL_FROM", "X@a.org y@b.org")
    assert my_addresses(cfg) == {"x@a.org", "y@b.org"}


def test_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "patchtrail 0.1.0"
