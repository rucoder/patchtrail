import urllib.request

import pytest


@pytest.fixture(autouse=True)
def hermetic(tmp_path, monkeypatch):
    """Isolate every test from the real home, git config and network."""
    home = tmp_path / "home"
    home.mkdir()
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("[user]\n\tname = Test User\n\temail = me@example.org\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATCHTRAIL_HOME", str(tmp_path / "ptl"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.delenv("PATCHTRAIL_FROM", raising=False)

    def no_network(*args, **kwargs):
        raise AssertionError("network in tests")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    return home
