# SPDX-License-Identifier: Apache-2.0
"""Storage paths and configuration."""
import dataclasses
import email.utils
import os
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    home: Path
    config: Path
    db: Path
    git: Path
    linux: Path
    queue: Path
    lock: Path


def paths() -> Paths:
    home = Path(os.environ.get("PATCHTRAIL_HOME") or Path.home() / ".patchtrail")
    git = home / "git"
    return Paths(home=home, config=home / "config.toml", db=home / "patchtrail.db",
                 git=git, linux=git / "linux.git", queue=git / "stable-queue",
                 lock=home / "fetch.lock")


@dataclass(frozen=True)
class KernelUrls:
    mainline: str = "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git"
    stable: str = "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git"
    queue: str = "https://git.kernel.org/pub/scm/linux/kernel/git/stable/stable-queue.git"
    next: str = "https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git"
    releases: str = "https://www.kernel.org/releases.json"


@dataclass
class Config:
    addresses: list[str] = field(default_factory=list)
    listen: str = "0.0.0.0:8470"
    interval_hours: float = 3
    seed: str | None = None
    kernel: KernelUrls = field(default_factory=KernelUrls)
    projects: dict[str, dict] = field(default_factory=dict)


def load_config(p: Paths) -> Config:
    try:
        data = tomllib.loads(p.config.read_text())
    except FileNotFoundError:
        return Config()
    known = {f.name for f in dataclasses.fields(KernelUrls)}
    kernel = KernelUrls(**{k: v for k, v in data.get("kernel", {}).items() if k in known})
    return Config(
        addresses=list(data.get("addresses", [])),
        listen=data.get("listen", Config.listen),
        interval_hours=data.get("interval_hours", Config.interval_hours),
        seed=data.get("seed"),
        kernel=kernel,
        projects=dict(data.get("projects", {})),
    )


def my_addresses(cfg: Config) -> frozenset[str]:
    """Own mail addresses, lowercased: first non-empty of $PATCHTRAIL_FROM,
    config addresses, git sendemail.from / user.email."""
    env = os.environ.get("PATCHTRAIL_FROM", "").split()
    if env:
        return frozenset(a.lower() for a in env)
    if cfg.addresses:
        return frozenset(a.lower() for a in cfg.addresses)
    addrs = set()
    for key in ("sendemail.from", "user.email"):
        r = subprocess.run(["git", "config", "--get", key], capture_output=True,
                           text=True, cwd=os.path.expanduser("~"))
        addr = email.utils.parseaddr(r.stdout.strip())[1].lower()
        if addr:
            addrs.add(addr)
    return frozenset(addrs)
