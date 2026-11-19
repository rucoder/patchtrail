# SPDX-License-Identifier: Apache-2.0
"""Project registry and detection from a patch's recipients."""

from functools import partial

from patchtrail.config import Config, Paths
from patchtrail.projects.base import (GIT, MAIL_ONLY, STAGES, PatchView, Progress,
                                      Project, Trail, TrailResult)
from patchtrail.projects.generic import mail_only

__all__ = ["GIT", "MAIL_ONLY", "STAGES", "PatchView", "Progress", "Project", "Trail",
           "TrailResult", "DEFAULT_GIT", "get_project", "detect_project"]

DEFAULT_GIT = {
    "erofs-utils": {
        "repo": "https://git.kernel.org/pub/scm/linux/kernel/git/xiang/erofs-utils.git",
        "branch": "dev"},
    "liburing": {"repo": "https://github.com/axboe/liburing.git", "branch": "master",
                 "tags": "liburing-*"},
}


def _kernel_trail(paths: Paths, cfg: Config) -> Trail:
    from patchtrail.projects.kernel import KernelTrail
    return KernelTrail(paths, cfg)


def _git_trail(name: str, paths: Paths, cfg: Config) -> Trail:
    from patchtrail.projects.gittrail import GitTrail
    return GitTrail(paths, cfg, name, **DEFAULT_GIT[name])


_REGISTRY = {
    "kernel": Project("kernel", STAGES, _kernel_trail),
    "qemu": mail_only("qemu"),
    "grub": mail_only("grub"),
    "erofs-utils": Project("erofs-utils", GIT, partial(_git_trail, "erofs-utils")),
    "liburing": Project("liburing", GIT, partial(_git_trail, "liburing")),
}

_EROFS = "linux-erofs@lists.ozlabs.org"
_KERNEL_DOMAINS = ("@vger.kernel.org", "@lists.infradead.org", "@lists.linux.dev")


def get_project(name: str) -> Project:
    return _REGISTRY.get(name) or mail_only(name)


def detect_project(to_cc: tuple[str, ...], subject: str) -> str:
    addrs = [a.lower() for a in to_cc]
    if "qemu-devel@nongnu.org" in addrs:
        return "qemu"
    if "grub-devel@gnu.org" in addrs:
        return "grub"
    if _EROFS in addrs and "erofs-utils" in subject:
        return "erofs-utils"
    if "io-uring@vger.kernel.org" in addrs and "[patch liburing" in subject.lower():
        return "liburing"
    if any(a.endswith(_KERNEL_DOMAINS) for a in addrs) or _EROFS in addrs:
        return "kernel"
    for a in addrs:
        if "-devel@" in a or "@lists." in a or "@vger." in a:
            return a.split("@", 1)[0]
    return "unknown"
