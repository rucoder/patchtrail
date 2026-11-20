# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HASH = "# SPDX-License-Identifier: Apache-2.0"
FORMS = {
    ".py": HASH, ".toml": HASH, ".yml": HASH,
    ".sql": "-- SPDX-License-Identifier: Apache-2.0",
    ".ts": "// SPDX-License-Identifier: Apache-2.0",
    ".tsx": "// SPDX-License-Identifier: Apache-2.0",
    ".css": "/* SPDX-License-Identifier: Apache-2.0 */",
    ".html": "<!-- SPDX-License-Identifier: Apache-2.0 -->",
}
SKIP = {"__pycache__", "node_modules"}


def _sources() -> list[Path]:
    files = [p for p in (ROOT / "src").rglob("*") if p.suffix in (".py", ".sql")]
    files += (ROOT / "tests").rglob("*.py")
    files += [p for p in (ROOT / "web" / "src").rglob("*") if p.suffix in (".ts", ".tsx", ".css")]
    files += (ROOT / "web").glob("*.ts")
    files += [ROOT / "web" / "index.html"]
    files += (ROOT / ".github").rglob("*.yml")
    dist = ROOT / "src" / "patchtrail" / "web" / "dist"
    return [p for p in files
            if p.is_file() and not SKIP & set(p.parts) and dist not in p.parents]


def test_every_source_file_has_spdx_header():
    missing = []
    for p in _sources():
        head = [l.strip() for l in p.read_text().splitlines()[:2]]
        if FORMS[p.suffix] not in head:
            missing.append(str(p.relative_to(ROOT)))
    assert missing == []


def test_spdx_covers_the_web_sources():
    names = {p.name for p in _sources()}
    assert {"App.tsx", "vite.config.ts", "index.html", "styles.css", "api.ts"} <= names


def test_no_raw_html_in_web():
    bad = []
    for p in (ROOT / "web" / "src").rglob("*"):
        if p.suffix not in (".ts", ".tsx") or not p.is_file():
            continue
        text = p.read_text()
        for needle in ("dangerouslySetInnerHTML", ".innerHTML", "eval("):
            if needle in text:
                bad.append(f"{p.relative_to(ROOT)}: {needle}")
    assert bad == []
