# SPDX-License-Identifier: Apache-2.0
import pytest

from patchtrail.projects import STAGES, detect_project, get_project


@pytest.mark.parametrize("lists,subject,want", [
    (("qemu-devel@nongnu.org",), "[PATCH v2] vfio/igd: x", "qemu"),
    (("grub-devel@gnu.org",), "[PATCH] tpm: x", "grub"),
    (("linux-erofs@lists.ozlabs.org",), "[PATCH v2] erofs-utils: lib: x", "erofs-utils"),
    (("linux-erofs@lists.ozlabs.org",), "[PATCH] erofs: fix y", "kernel"),
    (("io-uring@vger.kernel.org",), "[PATCH liburing] test/iowq-cpuset: x", "liburing"),
    (("io-uring@vger.kernel.org", "linux-kernel@vger.kernel.org"), "[PATCH] io_uring/io-wq: x", "kernel"),
    (("netdev@vger.kernel.org", "linux-arm-kernel@lists.infradead.org"), "[PATCH] net: x", "kernel"),
    (("someone@example.org",), "[PATCH] x", "unknown"),
])
def test_detect(lists, subject, want):
    assert detect_project(lists, subject) == want


def test_detect_fallback_local_part():
    assert detect_project(("foo-devel@example.org",), "[PATCH] x") == "foo-devel"
    assert detect_project(("dev@lists.example.org",), "[PATCH] x") == "dev"


def test_stages():
    assert get_project("kernel").stages == STAGES
    assert get_project("grub").stages == ("submitted", "reviewed", "accepted")
    assert get_project("liburing").stages[-1] == "released"
    assert get_project("whatever").trail is None
    assert get_project("unknown").stages == STAGES[:3]
    assert get_project("kernel").trail is not None
    assert get_project("erofs-utils").trail is not None
