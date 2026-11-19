# SPDX-License-Identifier: Apache-2.0
from pathlib import Path


def test_every_source_file_has_spdx_header():
    root = Path(__file__).resolve().parents[1]
    files = [p for p in (root / "src").rglob("*") if p.suffix in (".py", ".sql")]
    files += [p for p in (root / "tests").rglob("*.py")]
    files = [p for p in files if "__pycache__" not in p.parts]
    missing = []
    for p in files:
        head = p.read_text().splitlines()[:2]
        if not any(l.strip() in ("# SPDX-License-Identifier: Apache-2.0",
                                 "-- SPDX-License-Identifier: Apache-2.0") for l in head):
            missing.append(str(p.relative_to(root)))
    assert missing == []
