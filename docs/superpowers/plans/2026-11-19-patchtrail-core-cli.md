# patchtrail Plan 1: core and CLI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `patchtrail`/`ptl` CLI that does everything `~/bin/lkml-watch` and `~/bin/stable-watch` do, on top of
the storage, history, read state, discovery and trails the design describes, so that Plan 2 (service,
API, React page, systemd) only adds a front end.

**Architecture:** A Python package with SQLite storage under `~/.patchtrail/`.
- Each fetch run discovers the user's patches on lore, fetches their threads with b4, and runs each
  project's trail (kernel: mainline and stable; small projects: one upstream repo).
- Each run then records a JSON state snapshot per patch whenever something changed.
- Read state is a reference snapshot per patch. Unread means the flagging part of the newest snapshot
  differs from the reference.
- The CLI renders the same data the page will.

**Tech Stack:** Python ≥ 3.12 (stdlib: sqlite3, argparse, tomllib, urllib, fcntl), b4 (PyPI, called as
a subprocess), git ≥ 2.40, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-11-19-patchtrail-design.md`. Read it first. The old scripts
`~/bin/lkml-watch` and `~/bin/stable-watch` are the reference implementations being ported; tasks cite
their line ranges. Read them, never modify them.

**Plan 2** (service, API, React page, systemd, `make install` with the web build) is written after this
plan ships.

## Global Constraints

- **Python ≥ 3.12.** The only runtime dependency is `b4>=0.13`. pytest is a dev dependency
  (`[dependency-groups] dev`).
- **Git ≥ 2.40,** needed for `git merge-tree --write-tree --merge-base`. `ptl setup` refuses older
  versions.
- **Storage:** everything lives under `$PATCHTRAIL_HOME`, default `~/.patchtrail/`: `config.toml`,
  `patchtrail.db`, `git/linux.git`, `git/stable-queue/`, `git/<project>.git` and `fetch.lock`.
- **Git refs:** everything fetched goes under `refs/patchtrail/`. Never create `refs/heads/*` or
  `refs/tags/*` in patchtrail's repos, and never write into any other repository.
- **Old files are read-only:** `~/bin/*`, `~/.config/lkml-watch`, `~/.config/stable-watch`,
  `~/.local/state/lkml-watch` and `~/.local/state/stable-watch`.
- **Lore:**
  - Every HTTP request sends `User-Agent: patchtrail/<version>`.
  - A search answering HTTP 404 means "no results".
- **Mail addresses:** never hard-coded. They come from `$PATCHTRAIL_FROM`, then `addresses` in
  config.toml, then `git config sendemail.from` and `user.email`.
- **Kernel git:** first-release lookups are a binary search over release tags with
  `merge-base --is-ancestor`, never `name-rev` or `describe --contains`. Run `git commit-graph write
  --reachable --split` after each kernel fetch.
- **Read state:** nothing marks a patch read except `ptl read` and the import and first-discovery rules
  (Tasks 11 and 13).
- **Times:** stored as integer epoch seconds and shown as local `YYYY-MM-DD`.
- **Processes:** never use `pkill`, `pgrep -f`, `nohup` or `setsid`. Track child processes by PID.
- **Commits:** use `git commit -s`. No hand-written `Signed-off-by` line, and no session or tool
  trailers.
- **Tests are hermetic:**
  - An autouse fixture sets `HOME`, `PATCHTRAIL_HOME`, `XDG_*` and `GIT_CONFIG_GLOBAL` to temp paths.
  - `urllib.request.urlopen` is patched to raise.
  - b4 and lore are faked, and git fixture repos are served over `file://`.
- **Default config values:** `listen = "0.0.0.0:8470"` and `interval_hours = 3`.
- **License:** Apache-2.0 (the user's choice). Every source file starts with an SPDX line: `# SPDX-License-Identifier: Apache-2.0` (Python, Makefile, TOML, shell), `-- SPDX-License-Identifier: Apache-2.0` (SQL), `// SPDX-License-Identifier: Apache-2.0` (TypeScript, Plan 2). After a shebang, it goes on the second line. `tests/test_spdx.py` enforces this for `src/` and `tests/`.

## Review Focus

The five unexercised inputs most likely to bite the user. Each one has its test in the owning task.

1. **A thread fetch or lore search that fails mid-run** (lore down, b4 error, 429). The run goes on with
   the other patches, and the failed patch keeps its previous state: no new snapshot, no false
   "changed" flag. *Test: Task 12 `test_failed_thread_keeps_state`; Task 9
   `test_failed_search_keeps_previous_failed`.*
2. **A second fetch while one is running** (CLI and later the page). It is refused with a message
   naming the running run. A run whose process died is marked `interrupted` the next time. *Test:
   Task 12 `test_busy_when_locked`, `test_stale_run_marked_interrupted`.*
3. **Seeding from the old `linux.git`.** It never changes the source repo's refs or files, so
   `stable-watch` keeps working. *Test: Task 7 `test_seed_leaves_source_untouched`.*
4. **Odd mail:**
   - RFC 2047 headers, a missing or garbage `Date:`, HTML-only multipart and non-UTF-8 charsets.
   - Parsing never raises. An HTML part is counted as omitted, and a bad date becomes 0.
   - *Test: Task 3 `test_odd_mail_does_not_raise`.*
5. **A fix commit that no fetched tree has yet, or an unknown `Fixes:` hash.** The report says so, every
   branch counts as affected, and nothing raises. *Test: Task 9 `test_missing_commit_and_unknown_fixes`.*

---

## File map

```
pyproject.toml                       package, entry points patchtrail + ptl, deps
Makefile                             test, install (Plan 2 adds the web build)
README.md
.gitignore                           (exists: .superpowers/) + .venv/ __pycache__/ *.egg-info/ dist/ build/
src/patchtrail/__init__.py           __version__ = "0.1.0"
src/patchtrail/__main__.py           python -m patchtrail
src/patchtrail/config.py             Paths, Config, KernelUrls, load_config, my_addresses
src/patchtrail/db.py                 connect() + migrations
src/patchtrail/schema/001_init.sql   schema v1
src/patchtrail/store.py              patch / revision / mail / commit rows
src/patchtrail/mail.py               mbox split, MailInfo, standing, applied commits
src/patchtrail/sources/base.py       Source ABC
src/patchtrail/sources/lore.py       parse_msgid, fetch_thread (b4), search (Atom), LoreSource
src/patchtrail/projects/base.py      STAGES, Project, Trail ABC, PatchView, TrailResult
src/patchtrail/projects/__init__.py  registry: detect_project, get_project
src/patchtrail/projects/gittrail.py  GitTrail
src/patchtrail/projects/kernel/__init__.py  KernelTrail
src/patchtrail/projects/kernel/repo.py      Git, KernelRepo, branches()
src/patchtrail/projects/kernel/queue.py     StableQueue
src/patchtrail/projects/kernel/stable.py    branch_status and helpers (port)
src/patchtrail/projects/kernel/follow.py    commits_from_mail, search_commit, maintainer_trees
src/patchtrail/projects/kernel/failed.py    failed_mails
src/patchtrail/projects/kernel/backport.py  make_backport (port)
src/patchtrail/snapshot.py           compose_state, flag_view, record, changes, read state, history
src/patchtrail/discover.py           discovery, revision matching, backport postings
src/patchtrail/fetch.py              run_fetch: lock, runs/progress, orchestration
src/patchtrail/importer.py           import from the old scripts
src/patchtrail/render.py             text output for the CLI
src/patchtrail/cli.py                argparse commands
src/patchtrail/setup.py              ptl setup: checks, config, seed, import
src/patchtrail/data/neomuttrc        copy of ~/.config/lkml-watch/neomuttrc
tests/conftest.py                    hermetic env, db fixture, fake lore/b4
tests/mails.py                       make_mail(...) builder for synthetic mails
tests/gitfix.py                      make_kernel_fixture(), make_upstream_fixture()
tests/test_*.py
```

---

### Task 1: Package skeleton, paths and config

**Files:**
- Create: `pyproject.toml`, `Makefile`, `src/patchtrail/__init__.py`, `src/patchtrail/__main__.py`, `src/patchtrail/config.py`, `src/patchtrail/cli.py` (stub: `--version` only), `tests/conftest.py`, `tests/test_config.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces:
  - `Paths` (frozen dataclass): `home, config, db, git, linux, queue, lock: Path`.
  - `paths() -> Paths`: reads `$PATCHTRAIL_HOME`, default `~/.patchtrail`.
  - `KernelUrls` (frozen dataclass):
    - `mainline = "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git"`
    - `stable = "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git"`
    - `queue = "https://git.kernel.org/pub/scm/linux/kernel/git/stable/stable-queue.git"`
    - `next = "https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git"`
    - `releases = "https://www.kernel.org/releases.json"`
  - `Config` (dataclass): `addresses: list[str]`, `listen: str = "0.0.0.0:8470"`,
    `interval_hours: float = 3`, `seed: str | None = None`, `kernel: KernelUrls`,
    `projects: dict[str, dict]` (raw `[projects.<name>]` tables).
  - `load_config(p: Paths) -> Config`: a missing file gives the defaults. A `[kernel]` table overrides
    `KernelUrls` fields.
  - `my_addresses(cfg: Config) -> frozenset[str]`: lowercased. The order is `$PATCHTRAIL_FROM`
    (whitespace-separated), then `cfg.addresses`, then `git config --get sendemail.from` and
    `user.email`, run with `cwd=$HOME` (port of lkml-watch `my_addrs`, lines 219-231).
  - `cli.main(argv: list[str] | None = None) -> int`.
  - Console scripts `patchtrail` and `ptl` → `patchtrail.cli:run`, which is `sys.exit(main())`.
  - `tests/conftest.py`: an autouse fixture `hermetic(tmp_path, monkeypatch)` that sets `HOME`,
    `PATCHTRAIL_HOME`, `XDG_CONFIG_HOME` and `XDG_STATE_HOME` under `tmp_path`, plus
    `GIT_CONFIG_GLOBAL` pointing to a file with `user.name=Test User` and `user.email=me@example.org`.
    It unsets `PATCHTRAIL_FROM` and patches `urllib.request.urlopen` to raise
    `AssertionError("network in tests")`.

- [ ] **Step 1: Write the failing tests** in `tests/test_config.py`

```python
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
    p = paths(); p.home.mkdir(parents=True, exist_ok=True)
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
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `uv run pytest tests/test_config.py -v`. Expected: collection errors (no package yet).

- [ ] **Step 3: Implement**
  - `pyproject.toml`:
    - setuptools, `src` layout, `requires-python = ">=3.12"` and `dependencies = ["b4>=0.13"]`.
    - `[project.scripts]` with `patchtrail` and `ptl`, and `[dependency-groups] dev = ["pytest>=8"]`.
    - Package data: `schema/*.sql` and `data/*`.
  - `Makefile`: `test: uv run pytest -q` and `install: uv tool install --force .`
  - `.gitignore`: add `.venv/ __pycache__/ *.egg-info/ dist/ build/`.

- [ ] **Step 4: Run the tests and see them pass**

Run: `uv run pytest tests/test_config.py -v`. Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml Makefile .gitignore src tests
git commit -s -m "patchtrail: package skeleton, paths and config"
```

---

### Task 2: Database schema and store

**Files:**
- Create: `src/patchtrail/db.py`, `src/patchtrail/schema/001_init.sql`, `src/patchtrail/store.py`, `tests/test_store.py`
- Modify: `tests/conftest.py` (add `conn` fixture: `db.connect(paths().db)`)

**Interfaces:**
- Produces:
  - `db.connect(path: Path) -> sqlite3.Connection`:
    - creates the parent directories;
    - sets `journal_mode=WAL` and `foreign_keys=ON`, with `row_factory=sqlite3.Row`;
    - applies `schema/NNN_*.sql` files above `PRAGMA user_version` in order, then sets
      `user_version`.
    - `SCHEMA_VERSION = 1`.
  - Schema v1. Columns are exact; the builder may add indexes.

```sql
CREATE TABLE patches (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  project TEXT NOT NULL DEFAULT 'unknown',
  project_override INTEGER NOT NULL DEFAULT 0,
  relation TEXT NOT NULL DEFAULT 'mine' CHECK (relation IN ('mine','following')),
  hidden INTEGER NOT NULL DEFAULT 0,
  closed TEXT CHECK (closed IN ('rejected','dropped','moved')),
  closed_note TEXT,
  manual_applied INTEGER NOT NULL DEFAULT 0,
  force_stable INTEGER NOT NULL DEFAULT 0,
  tree_url TEXT, tree_branch TEXT,
  tree_source TEXT CHECK (tree_source IN ('manual','auto')),
  read_snapshot_id INTEGER REFERENCES snapshots(id) ON DELETE SET NULL,
  prev_read_snapshot_id INTEGER REFERENCES snapshots(id) ON DELETE SET NULL,
  flagged INTEGER NOT NULL DEFAULT 0,
  read_on_first_snapshot INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);
CREATE TABLE revisions (
  id INTEGER PRIMARY KEY,
  patch_id INTEGER NOT NULL REFERENCES patches(id) ON DELETE CASCADE,
  root_msgid TEXT NOT NULL UNIQUE,
  version INTEGER NOT NULL DEFAULT 1,
  subject TEXT NOT NULL,
  author TEXT,                       -- lowercased address
  posted_at INTEGER,
  change_id TEXT,
  kind TEXT NOT NULL DEFAULT 'series' CHECK (kind IN ('series','backport')),
  branch TEXT                        -- '6.1' for kind='backport'
);
CREATE TABLE mails (
  msgid TEXT PRIMARY KEY,            -- without <>
  revision_id INTEGER NOT NULL REFERENCES revisions(id) ON DELETE CASCADE,
  in_reply_to TEXT, date INTEGER NOT NULL DEFAULT 0,
  from_name TEXT, from_addr TEXT, subject TEXT,
  raw BLOB NOT NULL, first_seen INTEGER NOT NULL
);
CREATE TABLE commits (
  id INTEGER PRIMARY KEY,
  patch_id INTEGER NOT NULL REFERENCES patches(id) ON DELETE CASCADE,
  sha TEXT NOT NULL, subject TEXT,
  source TEXT NOT NULL CHECK (source IN ('applied-mail','search','manual')),
  UNIQUE (patch_id, sha)
);
CREATE TABLE branch_skips (
  patch_id INTEGER NOT NULL REFERENCES patches(id) ON DELETE CASCADE,
  series TEXT NOT NULL, PRIMARY KEY (patch_id, series)
);
CREATE TABLE snapshots (
  id INTEGER PRIMARY KEY,
  patch_id INTEGER NOT NULL REFERENCES patches(id) ON DELETE CASCADE,
  taken_at INTEGER NOT NULL, state TEXT NOT NULL      -- JSON, see Task 6
);
CREATE TABLE ignored (msgid TEXT PRIMARY KEY);         -- roots of deleted patches
CREATE TABLE runs (
  id INTEGER PRIMARY KEY, pid INTEGER, trigger TEXT NOT NULL,
  started_at INTEGER NOT NULL, finished_at INTEGER,
  status TEXT NOT NULL CHECK (status IN ('running','ok','failed','interrupted')),
  phase TEXT, step INTEGER, steps INTEGER, error TEXT
);
CREATE TABLE run_log (run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                      at INTEGER NOT NULL, line TEXT NOT NULL);
CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT);
```

  - `store.py`. Every function takes `conn` first; no ORM. Names are fixed:
    - `add_patch(conn, name, *, relation="mine", project="unknown", now) -> int`. Raises `ValueError`
      if the name is not `[A-Za-z0-9._-]+` or is already taken.
    - `get_patch(conn, name) -> sqlite3.Row | None` and `patch_by_id(conn, id) -> sqlite3.Row`.
    - `list_patches(conn, *, hidden=False, closed=False) -> list[sqlite3.Row]`. By default it excludes
      hidden and closed patches.
    - `add_revision(conn, patch_id, root_msgid, *, version=1, subject="", author=None,
      posted_at=None, kind="series", branch=None) -> int`.
    - `revisions(conn, patch_id) -> list[Row]` (by version, then id) and
      `revision_by_msgid(conn, msgid) -> Row | None`.
    - `upsert_mails(conn, revision_id, raws: list[bytes], now) -> list[str]`. Returns the msgids that
      are new; existing mails are not rewritten. Uses `mail.parse_mail` (Task 3), so implement
      `upsert_mails` at the start of Task 3.
    - `patch_mails(conn, patch_id) -> list[Row]`: all revisions, ordered by date.
    - `set_commit(conn, patch_id, sha, subject, source)` and `commits(conn, patch_id) -> list[Row]`.
    - `set_field(conn, patch_id, column, value)`. Allowed columns: `name, project,
      project_override, relation, hidden, closed, closed_note, manual_applied, force_stable,
      tree_url, tree_branch, tree_source, read_snapshot_id, prev_read_snapshot_id, flagged,
      read_on_first_snapshot`. Any other column raises `ValueError`.
    - `kv_get(conn, key) -> str | None` and `kv_set(conn, key, value)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_store.py`

```python
def test_schema_and_pragmas(conn):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

def test_add_patch_rules(conn):
    pid = store.add_patch(conn, "iowq-cpuset", now=1)
    assert store.get_patch(conn, "iowq-cpuset")["id"] == pid
    with pytest.raises(ValueError): store.add_patch(conn, "iowq-cpuset", now=1)
    with pytest.raises(ValueError): store.add_patch(conn, "bad name", now=1)

def test_delete_cascades(conn):
    pid = store.add_patch(conn, "p", now=1)
    rid = store.add_revision(conn, pid, "a@b", subject="[PATCH] x")
    conn.execute("DELETE FROM patches WHERE id=?", (pid,))
    assert store.revision_by_msgid(conn, "a@b") is None

def test_reconnect_keeps_version(tmp_path):
    p = paths(); db.connect(p.db).close()
    assert db.connect(p.db).execute("PRAGMA user_version").fetchone()[0] == 1
```

- [ ] **Step 2: Run the tests and see them fail.** `uv run pytest tests/test_store.py -v` fails on imports.
- [ ] **Step 3: Implement `db.py`, the schema and `store.py`** (except `upsert_mails` and
  `patch_mails`, which come in Task 3).
- [ ] **Step 4: Run the tests and see them pass.** Expected: 4 passed.
- [ ] **Step 5: Commit** with `git commit -s -m "patchtrail: database schema and store"`.

---

### Task 3: Mail parsing and standing

**Files:**
- Create: `src/patchtrail/mail.py`, `tests/mails.py`, `tests/test_mail.py`
- Modify: `src/patchtrail/store.py` (add `upsert_mails`, `patch_mails`)

**Interfaces:**
- Produces, in `mail.py`:
  - `split_mbox(data: bytes) -> list[bytes]`: raw messages of an mboxrd (b4 output). Use
    `mailbox.mbox` on a temp file or an equivalent `^From ` split, and strip the From_ line.
  - `MailInfo`, a frozen dataclass:

    | Field | Type | Notes |
    |---|---|---|
    | `msgid` | `str` | without `<>` |
    | `in_reply_to` | `str \| None` | without `<>` |
    | `date` | `int` | 0 when missing or unparsable |
    | `from_name` | `str` | the name, or the address |
    | `from_addr` | `str` | lowercased |
    | `subject` | `str` | RFC 2047 decoded, whitespace collapsed |
    | `is_reply` | `bool` | the subject starts with "re:", case-insensitive |
    | `tags` | `tuple[str, ...]` | review trailer lines of replies, stripped |
    | `applied` | `bool` | a reply with a line starting `Applied` |
    | `applied_commits` | `tuple[tuple[str, str], ...]` | `(patch subject, full or abbreviated sha)` from b4 thank-you blocks |
    | `change_id` | `str \| None` | from a `change-id: ` line |
    | `to_cc` | `tuple[str, ...]` | lowercased addresses from To and Cc |

    `tags` follows the lkml-watch `REVIEW_TAG` (lines 63-65) and `messages()` (180-200).
  - `parse_mail(raw: bytes) -> MailInfo`.
  - `text_body(raw: bytes) -> tuple[str, int]`: the text/plain parts decoded with their charset,
    `errors="replace"`, and the number of non-text parts left out.
  - `Standing`, a frozen dataclass:
    - `kind`: one of `'applied' 'waiting_reply' 'waiting_maintainer' 'your_turn' 'new_reply' 'none'`;
    - `who: str`, `since: int`, `tags: tuple[str, ...]`;
    - `text() -> str`.
  - `standing(mails: list[MailInfo], mine: frozenset[str], *, following: bool = False) -> Standing`:
    port of lkml-watch `standing()` (lines 253-275), with mails sorted by date. `text()` must
    reproduce the old wording exactly:
    - `"APPLIED by {who}, {YYYY-MM-DD}"`
    - the tags joined with `"; "` before the state;
    - `"waiting for a reply since {D}"`
    - `"waiting for the maintainer since {D}"`
    - `"{who} replied {D}: your turn"`
    - For `following=True`, a last mail from someone else is `kind='new_reply'` with the text
      `"{who} replied {D}"`.
    - With no mails: `kind='none'`, text `"not fetched yet"`.
  - `head_subject(mails) -> str`: port of lkml-watch `summary()`'s choice of the subject (lines
    286-289).
- Produces, in `tests/mails.py`: `make_mail(msgid, *, frm="Me <me@example.org>", subject="[PATCH]
  fix io", date="Wed, 11 Nov 2026 16:27:05 +0000", in_reply_to=None, body="", to="list@vger.kernel.org",
  cc="", extra_headers=None, html_only=False) -> bytes`, plus `mbox(*raws) -> bytes`.
- Produces, in `store.py`:
  - `upsert_mails(conn, revision_id, raws, now) -> list[str]`;
  - `patch_mails(conn, patch_id) -> list[sqlite3.Row]`;
  - `mail_infos(conn, patch_id) -> list[MailInfo]`, parsed from `raw` and sorted by date.

- [ ] **Step 1: Write the failing tests** in `tests/test_mail.py`

```python
JENS = """On Wed, 11 Nov 2026 16:27:05 +0000, Me wrote:
> Since commit ...
> [...]

Applied, thanks!

[1/1] io_uring/io-wq: apply the current cpuset to new workers
      commit: 0659e44ce739ecd856164c75a5325b7959a2921d

Best regards,
--
Jens Axboe
"""

def test_applied_commits_and_standing():
    root = parse_mail(make_mail("r@x", subject="[PATCH] io_uring/io-wq: apply the current cpuset to new workers"))
    ty = parse_mail(make_mail("t@x", frm="Jens Axboe <axboe@kernel.dk>", in_reply_to="r@x",
                              subject="Re: [PATCH] io_uring/io-wq: apply the current cpuset to new workers",
                              date="Wed, 18 Nov 2026 09:07:48 -0700", body=JENS))
    assert ty.applied and ty.applied_commits == (("io_uring/io-wq: apply the current cpuset to new workers",
                                                  "0659e44ce739ecd856164c75a5325b7959a2921d"),)
    s = standing([root, ty], frozenset({"me@example.org"}))
    assert s.kind == "applied" and s.text() == "APPLIED by Jens Axboe, 2026-11-18"

def test_two_patch_series_thank_you():
    body = "Applied to kvm-x86 mmu, thanks!\n\n[1/2] KVM: a\n      https://github.com/kvm-x86/linux/commit/aaaaaaaaaaaa\n[2/2] KVM: b\n      commit: bbbbbbbbbbbb\n"
    m = parse_mail(make_mail("t@x", frm="Sean <s@g.com>", subject="Re: [PATCH v2 0/2] KVM: c", body=body, in_reply_to="r@x"))
    assert m.applied_commits == (("KVM: a", "aaaaaaaaaaaa"), ("KVM: b", "bbbbbbbbbbbb"))

def test_waiting_and_your_turn_wording():
    me = frozenset({"me@example.org"})
    root = parse_mail(make_mail("r@x"))
    rb = parse_mail(make_mail("a@x", frm="Tomita Moeko <t@m.org>", subject="Re: [PATCH] fix io",
                              date="Fri, 24 Jul 2026 10:00:00 +0000", in_reply_to="r@x",
                              body="Reviewed-by: Tomita Moeko <t@m.org>\n"))
    assert standing([root], me).text() == "waiting for a reply since 2026-11-11"
    assert standing([root, rb], me).text() == "Reviewed-by Tomita Moeko; waiting for the maintainer since 2026-07-24"
    q = parse_mail(make_mail("b@x", frm="Jiri Pirko <j@p.org>", subject="Re: [PATCH] fix io",
                             date="Thu, 21 Mar 2024 10:00:00 +0000", in_reply_to="r@x", body="Why?\n"))
    assert standing([root, q], me).text() == "Jiri Pirko replied 2024-03-21: your turn"
    assert standing([root, q], me, following=True).text() == "Jiri Pirko replied 2024-03-21"

def test_odd_mail_does_not_raise():          # Review Focus 4
    raws = [make_mail("h@x", html_only=True),
            make_mail("d@x", date="garbage"),
            make_mail("e@x", subject="=?utf-8?q?R=C3=A9sum=C3=A9?=",
                      extra_headers={"Content-Type": "text/plain; charset=iso-8859-1"}, body="caf\xe9\n")]
    infos = [parse_mail(r) for r in raws]
    assert infos[1].date == 0 and infos[2].subject == "Résumé"
    assert text_body(raws[0]) == ("", 1)

def test_split_mbox_roundtrip():
    raws = split_mbox(mbox(make_mail("a@x"), make_mail("b@x")))
    assert [parse_mail(r).msgid for r in raws] == ["a@x", "b@x"]

def test_upsert_mails_returns_only_new(conn):
    pid = store.add_patch(conn, "p", now=1); rid = store.add_revision(conn, pid, "a@x")
    assert store.upsert_mails(conn, rid, [make_mail("a@x")], now=5) == ["a@x"]
    assert store.upsert_mails(conn, rid, [make_mail("a@x"), make_mail("b@x")], now=6) == ["b@x"]
```

- [ ] **Step 2: Run the tests and see them fail.** `uv run pytest tests/test_mail.py -v` fails on imports.
- [ ] **Step 3: Implement `mail.py` and the store additions.**
  - b4 thank-you blocks: a line `[n/m] <subject>` followed, on the next non-empty indented line, by
    either `commit: <hex 12-40>` or a URL ending `/commit/<hex 12-40>`.
  - The "Applied" test is `line.startswith("Applied")` on body lines, as lkml-watch line 198 does.
- [ ] **Step 4: Run the tests and see them pass.** Expected: 6 passed.
- [ ] **Step 5: Commit** with `git commit -s -m "patchtrail: mail parsing and standing"`.

---

### Task 4: Lore access

**Files:**
- Create: `src/patchtrail/sources/__init__.py`, `src/patchtrail/sources/base.py`, `src/patchtrail/sources/lore.py`, `tests/test_lore.py`, `tests/data/search-page1.atom`, `tests/data/search-page2.atom`

**Interfaces:**
- Produces:
  - `sources/base.py`: `class Source(ABC)` with abstract `fetch(self, root_msgid: str) -> list[bytes]`
    and `discover(self, addresses: list[str], since: int | None) -> list[Entry]`.
  - `sources/lore.py`:
    - `LORE = "https://lore.kernel.org"`, `class LoreError(Exception)`.
    - `parse_msgid(arg: str) -> str`. It accepts `<id>`, `id`, `https://lore.kernel.org/all/<id>/`,
      `…/<list>/<id>/T/#u`, `…/r/<id>` and percent-encoded ids, and returns the id without `<>`. This
      is a port of lkml-watch `parse_msgid` (lines 101-106) extended to `/r/`.
    - `b4_path() -> str`, tried in order: `$PATCHTRAIL_B4`; then `Path(sys.executable).parent / "b4"`
      if it exists; then `shutil.which("b4")`; otherwise raise `LoreError("b4 not found")`.
    - `fetch_thread(msgid: str) -> bytes`. Runs `[b4_path(), "-q", "mbox", "-C", "-o", "-", msgid]`
      (port of lkml-watch `fetch`, lines 135-147). Raises `LoreError(<last stderr line> or "not on lore
      yet?")` unless stdout starts with `b"From "`.
    - `Entry`, a frozen dataclass: `msgid`, `subject`, `author` (lowercased email or ""), `updated`
      (ISO string), `is_reply: bool`, `href`, `summary: str` (the Atom `content` text, "" if absent).
    - `search(inbox: str, query: str, *, urlopen=None) -> list[Entry]`:
      - requests `GET {LORE}/{inbox}/?q={quote(query)}&x=A`, then `&o={n}` with n = the number of
        entries collected so far;
      - stops when a page adds no new msgid;
      - HTTP 404 on the first page means `[]`. Any other error raises `LoreError`;
      - `is_reply` is true when there is a `thr:in-reply-to` element or the title starts with "re:"
        (port of `lore_roots`, lines 438-455).
    - `class LoreSource(Source)`:
      - `fetch` = `split_mbox(fetch_thread(id))`.
      - `discover(addresses, since)` = for each address, `search("all", f"f:{addr} AND s:PATCH" + (f"
        AND d:{YYYYMMDD of since - 2 days}.." if since else ""))`. Non-reply entries only, deduplicated
        by msgid.
- Every request sends the header `User-Agent: patchtrail/<__version__>`.

- [ ] **Step 1: Write the failing tests** in `tests/test_lore.py`.
  - Fake `urlopen(req, timeout)`: record `req.full_url` and `req.headers`, and return page 1 or page 2
    by the `o=` parameter. Page 2 repeats page 1's last entry plus one new one, then a third request
    returns page 2 again.

```python
def test_parse_msgid_forms():
    for a in ["<20261111162705.1150983-1-me@x>", "20261111162705.1150983-1-me@x",
              "https://lore.kernel.org/all/20261111162705.1150983-1-me@x/",
              "https://lore.kernel.org/io-uring/20261111162705.1150983-1-me@x/T/#u",
              "https://lore.kernel.org/r/20261111162705.1150983-1-me@x",
              "https://lore.kernel.org/all/20261111162705.1150983-1-me%40x/"]:
        assert parse_msgid(a) == "20261111162705.1150983-1-me@x"

def test_search_pages_and_user_agent(fake_urlopen):
    entries = search("all", "f:me@example.org AND s:PATCH", urlopen=fake_urlopen)
    assert [e.msgid for e in entries] == ["p1@x", "p2@x", "p3@x"]
    assert all(h["User-agent"].startswith("patchtrail/") for h in fake_urlopen.headers)
    assert "x=A" in fake_urlopen.urls[0] and "o=" not in fake_urlopen.urls[0]

def test_search_404_is_empty():
    def nf(req, timeout=None): raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
    assert search("stable", "s:x", urlopen=nf) == []

def test_search_other_errors_raise():
    def boom(req, timeout=None): raise urllib.error.HTTPError(req.full_url, 429, "slow", {}, None)
    with pytest.raises(LoreError): search("all", "s:x", urlopen=boom)

def test_fetch_thread_uses_b4(tmp_path, monkeypatch):
    fake = tmp_path / "b4"; fake.write_text("#!/bin/sh\necho \"$@\" > %s/args\nprintf 'From x\\n'\n" % tmp_path)
    fake.chmod(0o755); monkeypatch.setenv("PATCHTRAIL_B4", str(fake))
    assert fetch_thread("a@b").startswith(b"From ")
    assert (tmp_path / "args").read_text().split() == ["-q", "mbox", "-C", "-o", "-", "a@b"]

def test_fetch_thread_error(tmp_path, monkeypatch):
    fake = tmp_path / "b4"; fake.write_text("#!/bin/sh\necho 'boom: no such thread' >&2\nexit 1\n")
    fake.chmod(0o755); monkeypatch.setenv("PATCHTRAIL_B4", str(fake))
    with pytest.raises(LoreError, match="boom: no such thread"): fetch_thread("a@b")
```

- [ ] **Step 2: Run the tests and see them fail.**
- [ ] **Step 3: Implement.** The Atom fixtures follow public-inbox's format: `feed/entry` with `title`,
  `updated`, `link href`, `author/email`, and optionally `thr:in-reply-to`. Namespaces are those in
  lkml-watch lines 445-446.
- [ ] **Step 4: Run the tests and see them pass,** then check the installed b4 takes the same
  arguments: `uv run b4 mbox --help | grep -E -- '-C|-o'` shows both options.
- [ ] **Step 5: Commit** with `git commit -s -m "patchtrail: lore access via b4 and Atom search"`.

---

### Task 5: Projects: stages, detection, trail interface

**Files:**
- Create: `src/patchtrail/projects/base.py`, `src/patchtrail/projects/__init__.py`, `src/patchtrail/projects/generic.py`, `tests/test_projects.py`

**Interfaces:**
- Produces:
  - `STAGES = ("submitted", "reviewed", "accepted", "applied", "released", "backports")`.
  - `PatchView`, a dataclass the trails read:
    - `id, name, relation, project: str`;
    - `mails: list[MailInfo]`, `posted_at: int`, `subject: str` (`head_subject`), `author: str`;
    - `commits: list[dict]` (`{"sha", "subject", "source"}`);
    - `tree: tuple[str, str] | None`, `tree_source: str | None`;
    - `force_stable: bool`, `skips: frozenset[str]`, `manual_applied: bool`;
    - `backports: dict[str, list[str]]` (series → backport revision root msgids);
    - `prev_state: dict | None` (the last snapshot).
  - `TrailResult`, a dataclass:
    - `commits_found: list[tuple[str, str, str]]` (`sha, subject, source`);
    - `tree: tuple[str, str] | None` (an auto-found maintainer tree);
    - `fragment: dict` (keys `commits`, `branches`, `failed`, `hint`; see Task 6).
  - `class Progress(Protocol)` with `phase(name: str, steps: int | None = None)`, `step(label: str)`
    and `log(line: str)`.
  - `class Trail(ABC)` with `prepare(self, patches: list[PatchView], progress: Progress) -> None`
    (fetch repos once per run) and `evaluate(self, patch: PatchView, progress: Progress) ->
    TrailResult`.
  - `Project`, a frozen dataclass: `name: str`, `stages: tuple[str, ...]`, `trail: Callable[[Paths,
    Config], Trail] | None`.
  - `MAIL_ONLY = STAGES[:3]` and `GIT = STAGES[:5]`.
  - Registry:
    - `kernel` has all six stages and the trail `KernelTrail` (Task 9; register it lazily by import
      path).
    - `qemu` and `grub` are `MAIL_ONLY`.
    - `erofs-utils` and `liburing` are `GIT`, with `GitTrail` (Task 10).
    - Any other name is mail-only.
  - `get_project(name) -> Project`.
  - `detect_project(to_cc: tuple[str, ...], subject: str) -> str`. The first matching rule wins:
    1. `qemu-devel@nongnu.org` → `"qemu"`
    2. `grub-devel@gnu.org` → `"grub"`
    3. `linux-erofs@lists.ozlabs.org` and `"erofs-utils"` in the subject → `"erofs-utils"`
    4. `io-uring@vger.kernel.org` and `"[PATCH liburing"` (case-insensitive) in the subject →
       `"liburing"`
    5. any `@vger.kernel.org`, `@lists.infradead.org` or `@lists.linux.dev` address, or
       `linux-erofs@lists.ozlabs.org` → `"kernel"`
    6. otherwise, the local part of the first list-looking address (containing `-devel@`, `@lists.`
       or `@vger.`) → that local part; with none, `"unknown"`.

- [ ] **Step 1: Write the failing tests** in `tests/test_projects.py`

```python
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

def test_stages():
    assert get_project("kernel").stages == STAGES
    assert get_project("grub").stages == ("submitted", "reviewed", "accepted")
    assert get_project("liburing").stages[-1] == "released"
    assert get_project("whatever").trail is None
```

- [ ] **Step 2: Run the tests and see them fail.**
- [ ] **Step 3: Implement.** `trail` entries are factories resolved lazily, so Tasks 9 and 10 can land
  later. Until then the kernel and git factories may raise `NotImplementedError`; the `test_stages`
  test doesn't call them.
- [ ] **Step 4: Run the tests and see them pass.** Expected: 9 passed.
- [ ] **Step 5: Commit** with `git commit -s -m "patchtrail: projects, stages and detection"`.

---

### Task 6: Snapshots, diffs and read state

**Files:**
- Create: `src/patchtrail/snapshot.py`, `tests/test_snapshot.py`

**Interfaces:**
- Consumes: `Standing` (Task 3), `get_project` (Task 5), the `snapshots` and `patches` columns
  (Task 2).
- Produces:
  - **The state document.** This is the contract the CLI and Plan 2's API render. Keys are exact:

```python
{
 "stage": "accepted",                       # one of STAGES
 "closed": None,                            # or "rejected"/"dropped"/"moved"
 "closed_note": None,
 "standing": {"kind": "applied", "who": "Jens Axboe", "since": 1795017000, "text": "APPLIED by Jens Axboe, 2026-11-18"},
 "trailers": ["Reviewed-by Tomita Moeko"],  # sorted, unique
 "mails": ["msgid1", "msgid2"],             # sorted
 "commits": [{"sha": "0659e44ce739...", "subject": "...", "where": "tree:https://... io_uring-7.4",
              "stage": "accepted", "release": None, "stable": True, "cc": "", "fixes": [{"sha": "84eacf177faa...", "release": "v6.12-rc1"}]}],
 "branches": {"6.1": {"0659e44ce739": {"state": "conflict", "tag": None, "detail": ["..."]}}},
 "failed": {"6.1": {"date": "2026-11-20", "url": "https://lore..."}},
 "hint": None,                              # e.g. "not tagged for stable"
 "finished": False
}
```

  - `where` is one of `"mainline"`, `"next"`, `"tree:<url> <branch>"`, `"upstream"` (GitTrail) and
    `"missing"`.
  - Branch `state` is one of `not_affected applies applies_after_queue conflict backport_sent queued
    in_branch released skipped not_fetched`.
  - `stage_of(project: Project, standing: Standing, trailers: list[str], commits: list[dict],
    manual_applied: bool) -> str`. Algorithm:
    - Start at `submitted`.
    - `reviewed` if there are trailers.
    - `accepted` if `standing.kind == "applied"`, there are commits, or `manual_applied`.
    - `applied` if `manual_applied`, or all commits have a stage of applied or released.
    - `released` if there are commits and all of them are released.
    - `backports` if the stage is released and any commit has `stable: True`.
    - Then cap: return the furthest stage in `project.stages` that is not beyond the computed one.
  - `compose_state(*, project, standing, mails: list[MailInfo], fragment: dict, manual_applied,
    closed, closed_note) -> dict`. It fills every key above.
    - `trailers` come from `standing.tags`.
    - `finished` is true when:
      - the stage is the project's last stage and every branch entry's state is in `{released,
        not_affected, skipped}`; or
      - the stage is `released` and no commit has `stable: True`.
  - `flag_view(state) -> dict` keeps only what flags a patch:
    - `stage`, `closed`, `[standing.kind, standing.who]`, `trailers`, `mails`;
    - `{sha[:12]: [stage, release, where == "missing"]}` for each commit. Including "missing" is
      what makes a commit that drops out of its tree flag the patch;
    - `{series: {sha12: [state, tag]}}` for branches;
    - `sorted(failed)`.
    - Never `detail`, `text`, `since` or `hint`.
  - `record(conn, patch_id, state, now) -> int | None`. Inserts a row only if `state` differs from
    the last stored state (full JSON equality with sorted keys), and returns the new id or None.
    - If the patch has `read_on_first_snapshot=1` and this is its first snapshot, it sets
      `read_snapshot_id` to the new id and clears the column.
  - `latest(conn, patch_id) -> tuple[int, int, dict] | None`, as `(id, taken_at, state)`.
  - `Change`, a frozen dataclass: `field: str`, `old`, `new`, `flags: bool`. Fields:
    - `stage`, `closed`, `standing`, `trailers` (`new` = the added list), `mail` (`new` = the added
      msgids);
    - `commit:<sha12>`: old and new are strings `"<stage> <release or ''>"`, with `" missing"`
      appended when `where == "missing"`;
    - `branch:<series>:<sha12>` (`"state tag"` strings);
    - `failed:<series>`.
  - `changes(old: dict | None, new: dict) -> list[Change]`. With `old=None`, the result is `[]`: the
    first snapshot is not a change.
  - `unread(conn, patch_id) -> bool`: `flagged`, or `flag_view(latest) != flag_view(reference)`. A
    patch with no reference is unread if it has a snapshot.
  - `since_read(conn, patch_id) -> tuple[int | None, list[Change]]`: the reference's `taken_at` and
    `changes(reference_state, latest_state)`.
  - `mark_read(conn, patch_id)`: `prev_read_snapshot_id = read_snapshot_id`, `read_snapshot_id =
    latest id`, `flagged = 0`.
  - `mark_unread(conn, patch_id)`: if `prev_read_snapshot_id` is set, restore it as the reference;
    then `flagged = 1`.
  - `history(conn, patch_id) -> list[tuple[int, list[Change]]]`: newest first, the changes between
    consecutive snapshots.

- [ ] **Step 1: Write the failing tests** in `tests/test_snapshot.py`.
  - The helper `st(**kw)` builds a full state document with these defaults: `stage="submitted"`,
    `closed=None`, `closed_note=None`, `standing={"kind": "waiting_reply", "who": "", "since": 0,
    "text": "waiting for a reply since 2026-11-11"}`, `trailers=[]`, `mails=["a"]`, `commits=[]`,
    `branches={}`, `failed={}`, `hint=None`, `finished=False`. The keyword arguments override them.

```python
def test_record_only_on_change(conn):
    pid = store.add_patch(conn, "p", now=1)
    assert record(conn, pid, st(stage="submitted"), now=10) is not None
    assert record(conn, pid, st(stage="submitted"), now=20) is None
    assert record(conn, pid, st(stage="accepted"), now=30) is not None

def test_detail_change_does_not_flag(conn):
    pid = store.add_patch(conn, "p", now=1)
    a = st(branches={"6.6": {"0659e44ce739": {"state": "applies_after_queue", "tag": None, "detail": ["after 2 queued"]}}})
    b = st(branches={"6.6": {"0659e44ce739": {"state": "applies_after_queue", "tag": None, "detail": ["after 3 queued"]}}})
    record(conn, pid, a, now=1); mark_read(conn, pid)
    record(conn, pid, b, now=2)
    assert not unread(conn, pid)
    assert [c.flags for c in history(conn, pid)[0][1]] == [False]

def test_read_unread_cycle(conn):
    pid = store.add_patch(conn, "p", now=1)
    record(conn, pid, st(stage="submitted"), now=1); mark_read(conn, pid)
    record(conn, pid, st(stage="accepted", mails=["a", "b"]), now=2)
    when, ch = since_read(conn, pid)
    assert unread(conn, pid) and when == 1
    assert [(c.field, c.old, c.new, c.flags) for c in ch] == [("stage", "submitted", "accepted", True),
                                                              ("mail", None, ["b"], True)]
    mark_read(conn, pid); assert not unread(conn, pid)
    mark_unread(conn, pid); assert unread(conn, pid)
    assert since_read(conn, pid)[0] == 1          # the old reference is back

def test_mark_unread_without_change_still_flags(conn):
    pid = store.add_patch(conn, "p", now=1)
    record(conn, pid, st(), now=1); mark_read(conn, pid)
    mark_unread(conn, pid)
    assert unread(conn, pid)

def test_stage_of_caps_and_least_advanced():
    k, g = get_project("kernel"), get_project("grub")
    s = Standing("applied", "Jens Axboe", 0, ())
    two = [{"stage": "released", "stable": False}, {"stage": "accepted", "stable": False}]
    assert stage_of(k, s, [], two, False) == "accepted"
    assert stage_of(k, s, [], [{"stage": "released", "stable": True}], False) == "backports"
    assert stage_of(g, s, [], [], True) == "accepted"          # grub stops at accepted

def test_first_snapshot_read_when_requested(conn):
    pid = store.add_patch(conn, "p", now=1)
    store.set_field(conn, pid, "read_on_first_snapshot", 1)
    record(conn, pid, st(), now=1)
    assert not unread(conn, pid)
```

  `changes()` orders its result as: stage, closed, standing, trailers, mail, commit:*, branch:*,
  failed:*.

- [ ] **Step 2: Run the tests and see them fail.**
- [ ] **Step 3: Implement `snapshot.py`.**
- [ ] **Step 4: Run the tests and see them pass.** Expected: 6 passed.
- [ ] **Step 5: Commit** with `git commit -s -m "patchtrail: snapshots, diffs and read state"`.

---

### Task 7: Kernel repository and stable-queue

**Files:**
- Create: `src/patchtrail/projects/kernel/repo.py`, `src/patchtrail/projects/kernel/queue.py`, `tests/gitfix.py`, `tests/test_kernel_repo.py`, `tests/data/releases.json`

**Interfaces:**
- Produces, in `repo.py`:
  - `REFS = "refs/patchtrail"`, `MAINLINE = f"{REFS}/mainline"`, `NEXT = f"{REFS}/next"`,
    `TAGS = f"{REFS}/tags"`, `stable_ref(series) -> f"{REFS}/linux-{series}.y"` and
    `tree_ref(slug, branch) -> f"{REFS}/trees/{slug}/{branch}"`.
  - `class GitError(Exception)`.
  - `class Git`, a port of stable-watch `git` and `git_ok` (lines 88-99):
    - `__init__(self, path: Path)`;
    - `run(self, *args, env=None, input=None, ok=(0,), cwd=None) -> str`;
    - `ok(self, *args, env=None) -> bool`;
    - `resolve(self, rev) -> str | None`;
    - `is_ancestor(self, a, b) -> bool`.
  - `class KernelRepo(Git)`:
    - `ensure(self, seed: Path | None) -> None`: port of `ensure_repo` (lines 202-226), with
      `refs/patchtrail/seed/`.
    - `fetch(self, urls: KernelUrls, series: list[str], trees: list[tuple[str, str]], progress) ->
      None`: port of `fetch` (lines 229-251). Additions:
      - linux-next `+refs/heads/master:{NEXT}` with `--no-tags`;
      - `trees` is a list of `(url, branch)`, where branch may be `"*"` for all heads. Each lands in
        `tree_ref(slug(url), branch)`, with `slug` = the URL path with `/` and `.` turned into `-`;
      - afterwards, drop the seed refs and run `commit-graph write --reachable --split
        --no-progress`.
      - Progress: one `progress.step(label)` per remote.
    - `release_tags(self, series: str | None = None) -> list[str]` and `first_tag(self, commit,
      series=None) -> str | None`: port of lines 119-149.
  - `branches(releases_json: bytes) -> list[str]`: port of lines 188-195. Returns the series of the
    maintained stable and longterm releases that are not EOL, in file order.
  - `fetch_releases(urls: KernelUrls, *, urlopen=None) -> bytes`: also reads `file://` URLs.
- Produces, in `queue.py`:
  - `QueuedPatch`, a frozen dataclass: `name, text, files: frozenset[str]`.
  - `class StableQueue`, a port of lines 252-292:
    - `__init__(self, path: Path)`;
    - `update(self, url: str, progress) -> None`;
    - `patches(self, series) -> list[QueuedPatch]`;
    - `queued(self, series, sha) -> list[str]`.
- Produces, in `tests/gitfix.py`: `make_kernel_fixture(tmp: Path) -> KernelFixture`.
  - Fields: `mainline, stable, queue, next, tree: Path`; `urls: KernelUrls` (all `file://`, with
    `releases` pointing at `tests/data/releases.json`); `sha: dict[str, str]`; `tree_url: str`.
  - The scenario. All commits touch `io.c` except the queue patch, which touches another hunk of
    `io.c`. The author is `Me <me@example.org>` unless noted.

    | Step | Commit (subject) | Tag | Notes |
    |---|---|---|---|
    | A | `init io` | `v6.0` | |
    | B | `add bug` | `v6.1-rc1`, then `v6.1` on a later commit | |
    | R | `refactor io` | `v6.2-rc1`; `v6.2`, `v6.3`, `v6.4` on trivial follow-ups | author `Other <o@x.org>`; rewrites the lines the fix touches |
    | F | `fix io` | `v6.5-rc1` | body `Fixes: <B[:12]> ("add bug")` and `Cc: stable@vger.kernel.org` |
    | G | `fix more io` | | only on `tree` branch `for-next`, not in mainline |
    | U | `untagged io cleanup` | | in mainline, no Fixes and no Cc |

  - Stable repo branches:
    - `linux-6.0.y`: from `v6.0`, tag `v6.0.1`.
    - `linux-6.1.y`: from `v6.1`, tag `v6.1.1`.
    - `linux-6.2.y`: from `v6.2`, plus a commit with body `commit <F> upstream.`, tagged `v6.2.1`.
    - `linux-6.3.y`: from `v6.3`, tag `v6.3.1`.
    - `linux-6.4.y`: from `v6.4`, tag `v6.4.1`.
  - Queue repo:
    - `queue-6.3/series` lists `io-other-hunk.patch`, which applies to 6.3 and touches `io.c` away
      from F's hunk.
    - `queue-6.4/series` lists `fix-io.patch`, whose body has `commit <F> upstream.`.
  - `next` repo: mainline plus G.
  - Mainline's `MAINTAINERS` has an entry `F:\tio.c` and `T:\tgit {tree_url}`.
  - `tests/data/releases.json`:
    - 6.4 to 6.0 as `stable` or `longterm` with `"iseol": false`;
    - 5.4 as `longterm` with `"iseol": true`;
    - 6.5-rc1 as `mainline`.

- [ ] **Step 1: Write the failing tests** in `tests/test_kernel_repo.py`

```python
def test_fetch_namespaces_and_graph(tmp_path, kfix):
    r = KernelRepo(tmp_path / "linux.git"); r.ensure(None)
    r.fetch(kfix.urls, ["6.0", "6.1", "6.2", "6.3", "6.4"], [(kfix.tree_url, "*")], NullProgress())
    assert r.run("for-each-ref", "refs/heads", "refs/tags").strip() == ""
    assert r.resolve(MAINLINE) and r.resolve(NEXT) and r.resolve(stable_ref("6.1"))
    assert r.resolve(f"{TAGS}/v6.5-rc1")
    assert (r.path / "objects/info/commit-graphs/commit-graph-chain").exists()

def test_first_tag(fetched, kfix):
    assert fetched.first_tag(kfix.sha["F"]) == "v6.5-rc1"
    assert fetched.first_tag(kfix.sha["B"]) == "v6.1-rc1"
    assert fetched.release_tags("6.2") == ["v6.2.1"]

def test_branches_filter():
    assert branches(Path("tests/data/releases.json").read_bytes()) == ["6.4", "6.3", "6.2", "6.1", "6.0"]

def test_seed_leaves_source_untouched(tmp_path, kfix):          # Review Focus 3
    src = Git(kfix.mainline)
    before = src.run("for-each-ref"), sorted(p.name for p in (kfix.mainline / ".git").iterdir())
    r = KernelRepo(tmp_path / "linux.git"); r.ensure(kfix.mainline)
    assert r.run("for-each-ref", "--format=%(refname)").split()[0].startswith("refs/patchtrail/seed/")
    r.fetch(kfix.urls, ["6.1"], [], NullProgress())
    assert r.run("for-each-ref", "refs/patchtrail/seed/").strip() == ""
    assert (src.run("for-each-ref"), sorted(p.name for p in (kfix.mainline / ".git").iterdir())) == before

def test_queue(tmp_path, kfix):
    q = StableQueue(tmp_path / "stable-queue"); q.update(kfix.urls.queue, NullProgress())
    assert [p.name for p in q.patches("6.3")] == ["io-other-hunk.patch"]
    assert q.queued("6.4", kfix.sha["F"]) == ["fix-io.patch"]
    q.update(kfix.urls.queue, NullProgress())                  # second update: fetch + reset path
```

  Fixtures `kfix` (session-scoped `make_kernel_fixture`) and `fetched` (a fetched `KernelRepo`) live
  in `tests/conftest.py`. So does `NullProgress`, with no-op methods.

- [ ] **Step 2: Run the tests and see them fail.**
- [ ] **Step 3: Implement `gitfix.py`, `repo.py` and `queue.py`.** `--sparse` clone and
  `sparse-checkout set --no-cone /queue-*/` exactly as stable-watch does (lines 252-259).
- [ ] **Step 4: Run the tests and see them pass.** Expected: 5 passed.
- [ ] **Step 5: Commit** with `git commit -s -m "patchtrail: kernel repo, release tags and stable-queue"`.

---

### Task 8: Stable branch status (port)

**Files:**
- Create: `src/patchtrail/projects/kernel/stable.py`, `tests/test_kernel_stable.py`

**Interfaces:**
- Consumes: `KernelRepo`, `StableQueue`, `stable_ref` (Task 7).
- Produces:
  - `stable_tags(body: str) -> tuple[str | None, list[str]]`: port of lines 309-314.
  - `in_branch(repo, sha, ref, base, files) -> str | None`: port of lines 317-323.
  - `with_queue(repo, ref, patches: list[QueuedPatch]) -> tuple[str, list[str], list[str]]`: port of
    lines 326-343. The temp index env uses author and committer name `patchtrail`.
  - `conflicts(repo, sha, onto) -> list[str]`: port of `cherry_pick`, lines 346-356.
  - `Prereq`, a frozen dataclass: `sha, subject, tag: str | None, cc: str | None, fixes:
    tuple[str, ...]`.
  - `prerequisites(repo, sha, ref, base, files) -> list[Prereq]`: port of lines 359-379.
  - `BranchResult`, a dataclass: `state: str`, `tag: str | None`, `detail: list[str]`, `prereqs:
    list[Prereq]`.
  - `branch_status(repo, queue, sha, files, targets, series) -> BranchResult`: port of lines 393-434.
    The old text lines become `detail`, and the outcome becomes `state`:

    | Old wording | `state` | `tag` | `detail` |
    |---|---|---|---|
    | "not fetched" | `not_fetched` | | |
    | "not affected: no X" | `not_affected` | | `["no <X12>"]` |
    | "has it: TAG" | `released` | TAG | |
    | "has it: SHA, not released yet" | `in_branch` | | |
    | "queued for the next …" | `queued` | | `["queued for the next 6.4 release: fix-io.patch"]` |
    | "applies cleanly" | `applies` | | `["applies cleanly"]` |
    | "applies cleanly, after N queued patch(es) …" | `applies_after_queue` | | `["applies cleanly, after 1 queued patch to the same files"]` |
    | "CONFLICT in …" | `conflict` | | the old CONFLICT line, then "queued patches that did not apply: …" when any |

    For a conflict, `prereqs` is filled in and `SHOW_PREREQS = 8` applies only in rendering.

- [ ] **Step 1: Write the failing tests** in `tests/test_kernel_stable.py`. They use the `fetched`
  and `queue` fixtures from Task 7.

```python
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
```

- [ ] **Step 2: Run the tests and see them fail.**
- [ ] **Step 3: Implement the port.** It takes the repo and queue objects instead of globals; the
  logic is unchanged.
- [ ] **Step 4: Run the tests and see them pass.** Expected: 8 passed.
- [ ] **Step 5: Commit** with `git commit -s -m "patchtrail: stable branch status (port of stable-watch)"`.

---

### Task 9: Kernel trail: follow, FAILED mails, evaluation, backport worktree

**Files:**
- Create: `src/patchtrail/projects/kernel/follow.py`, `src/patchtrail/projects/kernel/failed.py`, `src/patchtrail/projects/kernel/__init__.py`, `src/patchtrail/projects/kernel/backport.py`, `tests/test_kernel_trail.py`, `tests/data/failed.atom`
- Modify: `src/patchtrail/projects/__init__.py` (register `KernelTrail`)

**Interfaces:**
- Consumes: Tasks 3, 4, 5, 7 and 8.
- Produces, in `follow.py`:
  - `commits_from_mail(mails: list[MailInfo], mine: frozenset[str]) -> list[tuple[str, str]]`:
    `applied_commits` of mails not sent by the user, deduplicated, in order.
  - `strip_subject(s: str) -> str`: drops leading `[...]` groups and `Re:`, and collapses whitespace.
  - `search_commit(repo, subject: str, author: str, since: int, refs: list[str]) -> str | None`:
    `git log --since=<since-1d> --author=<author> --format=%H%x00%s` over the refs. Returns the first
    commit whose subject equals `strip_subject(subject)`.
  - `maintainer_trees(repo, files: list[str]) -> list[str]`:
    - parses `MAINTAINERS` at `MAINLINE`;
    - an entry matches a file when an `F:` pattern matches: a trailing `/` is a directory prefix;
      `*`, `?` and `[]` go through `fnmatch`; otherwise an exact path or a directory prefix;
    - returns the `T: git <url>` URLs of the matching entries, deduplicated, ignoring any branch word
      after the URL.
- Produces, in `failed.py`: `failed_mails(subject: str, *, search=lore.search) -> dict[str, dict]`.
  - It is a port of lines 439-459. It returns `{series: {"date", "url"}}`.
  - A 404 gives `{}`; other errors raise `LoreError`.
- Produces, in `__init__.py`: `class KernelTrail(Trail)`.
  - `__init__(self, paths, cfg, *, search=lore.search, urlopen=None)`.
  - `prepare(patches, progress)`:
    - reads `branches(fetch_releases())`;
    - ensures the repo, seeded from `cfg.seed` on first creation;
    - fetches mainline, stable, next, and every patch's tree;
    - patches with a manual tree use `(url, branch)`. For patches with no commit found anywhere yet,
      the trees of `maintainer_trees` come from the patch's files (taken from the root mail's diff:
      `+++ b/` paths), fetched with `"*"`;
    - updates the queue.
  - `evaluate(patch, progress) -> TrailResult`:
    1. **Commits.** Use `patch.commits`, else `commits_from_mail`, else `search_commit` over `[NEXT,
       MAINLINE] + tree refs`, with `since=posted_at` and `author=patch.author`.
    2. **Per commit:**
       - resolve it;
       - `where`: `mainline` if it is an ancestor of `MAINLINE`; else `next` if of `NEXT`; else
         `tree:<url> <branch>` (the first tree ref containing it, which also sets `TrailResult.tree`
         with source auto); else `missing`;
       - `stage`: `released` if `first_tag` finds a tag, `applied` if in mainline, `accepted` if
         found anywhere, and `accepted` with `where="missing"` when only the mail names it;
       - `release` is `first_tag`;
       - `cc` and `fixes` come from `stable_tags`;
       - `stable` = `cc is not None or fixes or patch.force_stable`.
    3. **Branches,** for each stable commit and each series:
       - `skipped` if the series is in `patch.skips`;
       - `backport_sent` if `patch.backports` has the series and the branch neither has the fix nor
         has it queued;
       - else `branch_status(...)`, with the targets being the resolvable `Fixes:` commits. When a
         `Fixes:` hash is unknown, or there is no `Fixes:` line, the targets are `[]`, so every branch
         counts as affected.
    4. **Hint:** `"not tagged for stable: ask stable@vger.kernel.org"` when the patch is in mainline
       and no commit has `stable`.
    5. **Failed:** `failed_mails(subject)` for each stable commit. On `LoreError`, copy
       `patch.prev_state["failed"]` (or `{}`) and `progress.log(...)` the error.
  - `check_commits(shas: list[str], progress) -> list[str]`: the text report for `ptl check`. The
    format follows stable-watch `report()` (lines 464-510).
- Produces, in `backport.py`: `make_backport(repo, queue, sha: str, name: str, series: str, dest:
  Path) -> list[str]`, the printed lines. Port of `cmd_backport` (lines 586-622): worktree, branch
  `backport/{name}-{series}`, `git am` of the queued patches to the same files, `cherry-pick -x`, and
  the closing advice text verbatim.

- [ ] **Step 1: Write the failing tests** in `tests/test_kernel_trail.py`.
  - Fixture `trail`: `KernelTrail(paths(), cfg, search=lambda *a, **k: [])`, where `cfg.kernel =
    kfix.urls`.
  - In `tests/conftest.py`:
    - `view(**kw) -> PatchView`, with defaults `id=1`, `name="p"`, `relation="mine"`,
      `project="kernel"`, `mails=[]`, `posted_at=epoch("2026-01-01")`, `subject="[PATCH] fix io"`,
      `author="me@example.org"`, `commits=[]`, `tree=None`, `tree_source=None`,
      `force_stable=False`, `skips=frozenset()`, `manual_applied=False`, `backports={}` and
      `prev_state=None`;
    - `root(subj) = parse_mail(make_mail("r@x", subject=f"[PATCH] {subj}", body="---\n+++ b/io.c\n"))`;
    - `ty(blocks) = parse_mail(make_mail("t@x", frm="Maint <m@k.org>", in_reply_to="r@x",
      subject="Re: [PATCH] x", body="Applied, thanks!\n\n" + blocks))`;
    - `raising(exc)`, a callable that raises `exc`;
    - `fake_search_from(path)`, which returns `lore.search` run with an `urlopen` serving that file;
    - `epoch("YYYY-MM-DD")`.

```python
def test_follow_from_mail_and_tree(trail, view):
    v = view(subject="[PATCH] fix more io", mails=[root("fix more io"),
             ty("[1/1] fix more io\n      commit: " + kfix.sha["G"] + "\n")])
    trail.prepare([v], NullProgress()); res = trail.evaluate(v, NullProgress())
    c = res.fragment["commits"][0]
    assert c["where"] == f"tree:{kfix.tree_url} for-next" and c["stage"] == "accepted"
    assert res.tree == (kfix.tree_url, "for-next")

def test_found_without_reply_by_subject_and_author(trail, view):
    v = view(subject="[PATCH] fix io", mails=[root("fix io")])        # nobody replied "Applied"
    trail.prepare([v], NullProgress()); res = trail.evaluate(v, NullProgress())
    assert res.commits_found == [(kfix.sha["F"], "fix io", "search")]
    c = res.fragment["commits"][0]
    assert (c["where"], c["stage"], c["release"], c["stable"]) == ("mainline", "released", "v6.5-rc1", True)
    assert res.fragment["branches"]["6.1"][kfix.sha["F"][:12]]["state"] == "conflict"

def test_untagged_commit_has_no_branches(trail, view):
    v = view(commits=[{"sha": kfix.sha["U"], "subject": "untagged io cleanup", "source": "manual"}])
    trail.prepare([v], NullProgress()); res = trail.evaluate(v, NullProgress())
    assert res.fragment["branches"] == {} and res.fragment["hint"].startswith("not tagged for stable")

def test_skip_and_backport_sent(trail, view):
    v = view(commits=[{"sha": kfix.sha["F"], "subject": "fix io", "source": "manual"}],
             skips=frozenset({"6.1"}), backports={"6.3": ["bp@x"]})
    trail.prepare([v], NullProgress()); b = trail.evaluate(v, NullProgress()).fragment["branches"]
    k = kfix.sha["F"][:12]
    assert b["6.1"][k]["state"] == "skipped" and b["6.3"][k]["state"] == "backport_sent"

def test_missing_commit_and_unknown_fixes(trail, view):                 # Review Focus 5
    v = view(commits=[{"sha": "deadbeefdead", "subject": "gone", "source": "manual"}])
    trail.prepare([v], NullProgress()); res = trail.evaluate(v, NullProgress())
    assert res.fragment["commits"][0]["where"] == "missing"

def test_failed_mails_parse():
    got = failed_mails("fix io", search=fake_search_from("tests/data/failed.atom"))
    assert got == {"6.1": {"date": "2026-11-20", "url": "https://lore.kernel.org/stable/2026112001-x@gregkh/"}}

def test_failed_search_keeps_previous_failed(trail, view):              # Review Focus 1
    prev = {"failed": {"6.1": {"date": "2026-11-20", "url": "u"}}}
    v = view(commits=[{"sha": kfix.sha["F"], "subject": "fix io", "source": "manual"}], prev_state=prev)
    trail.search = raising(LoreError("429"))
    trail.prepare([v], NullProgress())
    assert trail.evaluate(v, NullProgress()).fragment["failed"] == prev["failed"]

def test_maintainer_trees(fetched):
    assert maintainer_trees(fetched, ["io.c"]) == [kfix.tree_url]

def test_backport_worktree(fetched, queue, tmp_path):
    lines = make_backport(fetched, queue, kfix.sha["F"], "fix-io", "6.3", tmp_path / "wt")
    assert (tmp_path / "wt" / "io.c").exists() and any("applies cleanly" in l for l in lines)
```

  Add a `test_unknown_fixes_hash_means_all_affected` case by adding a fixture commit whose body has
  `Fixes: 000000000000 ("nothing")`. Assert that branch 6.0 is *not* `not_affected`.

- [ ] **Step 2: Run the tests and see them fail.**
- [ ] **Step 3: Implement `follow.py`, `failed.py`, `KernelTrail` and `backport.py`,** and register
  the kernel trail in `projects/__init__.py`.
- [ ] **Step 4: Run the tests and see them pass.** Expected: 10 passed.
- [ ] **Step 5: Commit** with `git commit -s -m "patchtrail: kernel trail: follow, FAILED mails, backport"`.

---

### Task 10: GitTrail for small projects

**Files:**
- Create: `src/patchtrail/projects/gittrail.py`, `tests/test_gittrail.py`
- Modify: `src/patchtrail/projects/__init__.py` (register defaults), `tests/gitfix.py` (add `make_upstream_fixture`)

**Interfaces:**
- Produces:
  - `class GitTrail(Trail)`:
    - `__init__(self, paths, cfg, project: str, *, repo: str, branch: str, tags: str = "v*")`.
    - `cfg.projects[project]` may override `repo`, `branch` and `tags`.
    - `prepare`: a bare repo at `paths.git / f"{project}.git"`; fetch `+refs/heads/{branch}:
      refs/patchtrail/upstream` and `+refs/tags/{tags}:refs/patchtrail/tags/{tags}` with
      `--no-tags`.
    - `evaluate`:
      - commits come from `patch.commits`, else `follow.search_commit(repo, patch.subject,
        patch.author, patch.posted_at, ["refs/patchtrail/upstream"])` with source `search`;
      - each commit dict has `where: "upstream"`, `stage: "released" | "applied"`, `release`
        (binary search over tags sorted with `--sort=v:refname` using `is_ancestor`) and
        `stable: False`;
      - `branches` and `failed` are `{}`.
  - Default registry entries (`DEFAULT_GIT`):
    - `erofs-utils`: `https://git.kernel.org/pub/scm/linux/kernel/git/xiang/erofs-utils.git`, branch
      `dev`.
    - `liburing`: `https://github.com/axboe/liburing.git`, branch `master`.

- [ ] **Step 1: Write the failing tests.**
  - The fixture repo `make_upstream_fixture(tmp)` has commits `init`, then `lib: follow symlinks on
    intermediate tar path components` by `Me <me@example.org>` dated 2026-09-21, then tags `v1.0`
    (before it) and `v1.1` (after it).

```python
def test_found_and_released(tmp_path, upfix, view):
    t = GitTrail(paths(), load_config(paths()), "erofs-utils", repo=upfix.url, branch="master")
    v = view(project="erofs-utils", subject="[PATCH v2] erofs-utils: lib: follow symlinks on intermediate tar path components",
             author="me@example.org", posted_at=epoch("2026-09-20"))
    t.prepare([v], NullProgress()); c = t.evaluate(v, NullProgress()).fragment["commits"]
    assert [(x["where"], x["stage"], x["release"]) for x in c] == [("upstream", "released", "v1.1")]

def test_other_author_not_matched(tmp_path, upfix, view):
    t = GitTrail(paths(), load_config(paths()), "erofs-utils", repo=upfix.url, branch="master")
    v = view(project="erofs-utils", subject="[PATCH] lib: follow symlinks on intermediate tar path components",
             author="someone@else.org", posted_at=epoch("2026-09-20"))
    t.prepare([v], NullProgress())
    assert t.evaluate(v, NullProgress()).fragment["commits"] == []
```

  `strip_subject` drops the `erofs-utils: ` prefix only when it is in brackets. For erofs-utils, the
  commit subject is the patch subject without the `[PATCH v2] erofs-utils: ` part. So GitTrail strips
  a leading `<project>: ` after the brackets; test it with the subject above.

- [ ] **Step 2: Run the tests and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and see them pass,** then check the default upstream URLs:

Run: `git ls-remote https://git.kernel.org/pub/scm/linux/kernel/git/xiang/erofs-utils.git refs/heads/dev refs/heads/master`
and `git ls-remote https://github.com/axboe/liburing.git refs/heads/master`.
Expected: each branch named in `DEFAULT_GIT` is listed. If erofs-utils has no `dev`, use the branch
its maintainer applies patches to (check `git log -3` dates on both) and update the default.

- [ ] **Step 5: Commit** with `git commit -s -m "patchtrail: GitTrail for small upstream projects"`.

---

### Task 11: Discovery, revisions and backport postings

**Files:**
- Create: `src/patchtrail/discover.py`, `tests/test_discover.py`

**Interfaces:**
- Consumes: `LoreSource.discover` and `lore.search` (Task 4), `store` (Task 2), `strip_subject`
  (Task 9).
- Produces:
  - `slug(subject: str, taken: set[str]) -> str`: port of lkml-watch `slug` (lines 458-471).
  - `version_of(subject: str) -> int`: the `vN` inside the leading brackets, default 1.
  - `norm(subject: str) -> str`: `strip_subject(subject).lower()`.
  - `backport_of(subject: str, body: str) -> tuple[str | None, str | None]`, returning `(series,
    upstream sha)`:
    - the series comes from a `[PATCH X.Y.y]` or `[PATCH X.Y]` bracket, with `.y` dropped;
    - the sha comes from a `commit <hex12-40> upstream` or `[ Upstream commit <hex> ]` line.
  - `DiscoverResult`, a dataclass: `new_patches: list[str]`, `new_revisions: list[str]`,
    `backports: list[str]`.
  - `discover(conn, source, addresses: list[str], *, now: int, search=lore.search) -> DiscoverResult`:
    1. `since = kv_get("last_discovery")`, as an int or None. `first = since is None`.
    2. For each non-reply entry of `source.discover(addresses, since)`:
       - skip it if its msgid is already a revision root or is in `ignored`;
       - otherwise, if a revision exists with `author == entry.author` and `norm(subject) ==
         norm(entry.subject)`, add a revision to that patch with `version_of(entry.subject)`;
       - otherwise, `add_patch(slug(...), relation="mine")` plus a revision. When `first` is true, set
         `read_on_first_snapshot=1`.
    3. **Backports:** for each address, `search("stable", f"f:{addr}")` (replies included), and for
       each entry not already a revision:
       - call `backport_of(entry.subject, entry.summary)`;
       - if the sha's first 12 characters match a row in `commits`, or `norm` matches a tracked
         patch's subject, add a revision with `kind="backport"` and `branch=series` to that patch.
    4. `kv_set("last_discovery", now)`.
  - `merge_by_change_id(conn) -> list[str]`: when two patches have revisions with the same non-null
    `change_id`, move the newer patch's revisions into the older patch, delete the newer one, and
    return the merged names. It is called after threads are fetched (Task 12).

- [ ] **Step 1: Write the failing tests** in `tests/test_discover.py`. A `FakeSource` returns a
  configured list of `Entry` objects; a fake `search` returns stable-inbox entries.

```python
def test_new_series_named_and_read_on_first_run(conn):
    src = FakeSource([E("a@x", "[PATCH] io_uring/io-wq: apply the current cpuset to new workers")])
    r = discover(conn, src, ["me@example.org"], now=100, search=lambda *a, **k: [])
    assert r.new_patches == ["io-uring-io-wq-apply-the-current"]
    assert store.get_patch(conn, r.new_patches[0])["read_on_first_snapshot"] == 1

def test_v2_becomes_revision(conn):
    discover(conn, FakeSource([E("a@x", "[PATCH] KVM: x86/mmu: fill memory_fault")]), ["me@example.org"], now=1, search=nosearch)
    r = discover(conn, FakeSource([E("b@x", "[PATCH v2 0/2] KVM: x86/mmu: Fill memory_fault")]), ["me@example.org"], now=2, search=nosearch)
    assert r.new_revisions and not r.new_patches
    p = store.get_patch(conn, "kvm-x86-mmu-fill-memory-fault")
    assert [x["version"] for x in store.revisions(conn, p["id"])] == [1, 2]
    assert p["read_on_first_snapshot"] == 1                 # set on the first run only

def test_replies_hidden_and_ignored_skipped(conn):
    discover(conn, FakeSource([E("a@x", "[PATCH] x one")]), ["me@example.org"], now=1, search=nosearch)
    conn.execute("UPDATE patches SET hidden=1")
    conn.execute("INSERT INTO ignored VALUES ('c@x')")
    r = discover(conn, FakeSource([E("a@x", "[PATCH] x one"), E("r@x", "Re: [PATCH] x one", reply=True),
                                   E("c@x", "[PATCH] deleted one")]), ["me@example.org"], now=2, search=nosearch)
    assert r.new_patches == [] and r.new_revisions == []

def test_backport_posting_attaches_to_branch(conn):
    pid = store.add_patch(conn, "fix-io", now=1); store.add_revision(conn, pid, "a@x", subject="[PATCH] fix io")
    store.set_commit(conn, pid, "f" * 40, "fix io", "manual")
    stable = [E("bp@x", "[PATCH 6.1.y] fix io", reply=True, summary="commit ffffffffffff upstream.\n")]
    r = discover(conn, FakeSource([]), ["me@example.org"], now=2, search=lambda inbox, q, **k: stable)
    rev = store.revision_by_msgid(conn, "bp@x")
    assert r.backports == ["fix-io"] and (rev["kind"], rev["branch"], rev["patch_id"]) == ("backport", "6.1", pid)

def test_version_and_backport_parsing():
    assert version_of("[RFC PATCH v3 2/5] x") == 3 and version_of("[PATCH] x") == 1
    assert backport_of("[PATCH 6.6] x", "[ Upstream commit 0659e44ce739ecd8 ]") == ("6.6", "0659e44ce739ecd8")
```

- [ ] **Step 2: Run the tests and see them fail.**
- [ ] **Step 3: Implement `discover.py`.**
- [ ] **Step 4: Run the tests and see them pass.** Expected: 5 passed.
- [ ] **Step 5: Commit** with `git commit -s -m "patchtrail: discovery, revisions and backport postings"`.

---

### Task 12: Fetch run orchestration

**Files:**
- Create: `src/patchtrail/fetch.py`, `tests/test_fetch.py`

**Interfaces:**
- Consumes: Tasks 2 to 11.
- Produces:
  - `class Busy(Exception)`, carrying `run: sqlite3.Row`, the running run.
  - `class DbProgress(Progress)`: writes `runs.phase`, `step` and `steps`, plus `run_log` rows.
  - `build_view(conn, patch_row, mine) -> PatchView`.
  - `run_fetch(paths, cfg, trigger: str, *, source=None, trails=None, search=None, now=time.time,
    patch_names: list[str] | None = None, discover_new: bool = True) -> int`. Returns the run id.
    - `source` defaults to `LoreSource()` and `search` to `lore.search`.
    - `trails` is `dict[str, Trail]`, keyed by project name. `None` builds each project's trail from
      the registry on first use.
    - A failed thread logs `f"{name}: cannot fetch <{root}>: {err}"`, as lkml-watch line 153 did.
    1. Take a non-blocking `fcntl.flock` on `paths.lock`. If it is held, raise `Busy` with the latest
       `status='running'` row.
    2. Mark every `status='running'` row as `interrupted` with `finished_at=now`. The lock proves
       nobody runs them.
    3. Insert a run with `pid=os.getpid()`, `trigger` and `status='running'`.
    4. Phase `discover`: run `discover` when `discover_new` is true and `patch_names` is None.
    5. Phase `threads`, one step per revision of each selected, non-hidden, non-closed patch:
       - `upsert_mails(source.fetch(root))`;
       - on the first fetch of a revision, set the subject, author and posted_at from its root mail;
       - set `patches.project = detect_project(...)` unless `project_override`;
       - set `relation='following'` when the root mail's author is not in `mine` and the patch was
         added with `--follow`;
       - a `LoreError` is logged and the run continues;
       - finally, call `merge_by_change_id`.
    6. Phase `repos`: group the patches by project and call `trail.prepare(views)` for each project
       with a trail. A failure is logged, and that project's patches keep their previous trail
       fragment.
    7. Phase `evaluate`, one step per patch:
       - `trail.evaluate`; store `commits_found` with `set_commit`; store an auto tree with
         `tree_source='auto'` unless the source is `manual`;
       - `standing(...)`, `compose_state(...)`, `record(...)`;
       - when the trail failed, reuse `prev_state`'s `commits`, `branches`, `failed` and `hint`.
    8. Set `status='ok'`, or `'failed'` with `error` on an unexpected exception, which is re-raised.
       Release the lock.
  - `last_run(conn) -> sqlite3.Row | None`.

- [ ] **Step 1: Write the failing tests** in `tests/test_fetch.py`.
  - `FakeSource(threads: dict[str, list[bytes] | Exception] = {}, entries: list[Entry] = [])`:
    `fetch(root)` returns the list or raises the exception, and `discover(...)` returns `entries`.
  - `FakeTrail`: `prepare` is a no-op, and `evaluate` returns `TrailResult([], None, {"commits": [],
    "branches": {}, "failed": {}, "hint": None})`.
  - `cfgp = (paths(), load_config(paths()))`, `nosearch = lambda *a, **k: []`, and
    `log_lines(conn, rid)` returns the run's `run_log.line` values in order.

```python
def test_run_records_snapshots_and_project(conn, cfgp):
    src = FakeSource(threads={"a@x": [make_mail("a@x", to="io-uring@vger.kernel.org", subject="[PATCH] io_uring/io-wq: x")]},
                     entries=[E("a@x", "[PATCH] io_uring/io-wq: x")])
    rid = run_fetch(*cfgp, "cli", source=src, trails={"kernel": FakeTrail()}, search=nosearch, now=lambda: 100)
    p = store.list_patches(conn)[0]
    assert p["project"] == "kernel" and snapshot.latest(conn, p["id"]) is not None
    assert conn.execute("SELECT status FROM runs WHERE id=?", (rid,)).fetchone()[0] == "ok"
    assert not snapshot.unread(conn, p["id"])                     # first discovery arrives read

def test_failed_thread_keeps_state(conn, cfgp):                   # Review Focus 1
    good = FakeSource(threads={"a@x": [make_mail("a@x", to="io-uring@vger.kernel.org"),
                                       make_mail("b@x", frm="X <x@y.org>", subject="Re: [PATCH] fix io", in_reply_to="a@x")]},
                      entries=[E("a@x", "[PATCH] fix io")])
    run_fetch(*cfgp, "cli", source=good, trails={"kernel": FakeTrail()}, search=nosearch)
    pid = store.list_patches(conn)[0]["id"]
    count = lambda: conn.execute("SELECT count(*) FROM snapshots WHERE patch_id=?", (pid,)).fetchone()[0]
    n = count()
    bad = FakeSource(threads={"a@x": LoreError("lore is down")})
    rid2 = run_fetch(*cfgp, "cli", source=bad, trails={"kernel": FakeTrail()}, search=nosearch)
    assert count() == n and not snapshot.unread(conn, pid)
    assert any("cannot fetch <a@x>: lore is down" in l for l in log_lines(conn, rid2))

def test_busy_when_locked(cfgp):                                  # Review Focus 2
    fd = os.open(cfgp[0].lock, os.O_CREAT | os.O_RDWR); fcntl.flock(fd, fcntl.LOCK_EX)
    with pytest.raises(Busy): run_fetch(*cfgp, "cli", source=FakeSource(), trails={}, search=nosearch)

def test_stale_run_marked_interrupted(conn, cfgp):                # Review Focus 2
    conn.execute("INSERT INTO runs(pid,trigger,started_at,status) VALUES (999999,'cli',1,'running')"); conn.commit()
    run_fetch(*cfgp, "cli", source=FakeSource(), trails={}, search=nosearch)
    assert conn.execute("SELECT status FROM runs WHERE id=1").fetchone()[0] == "interrupted"

def test_phases_recorded(conn, cfgp):
    rid = run_fetch(*cfgp, "cli", source=FakeSource(), trails={}, search=nosearch)
    assert phases_seen(conn, rid) == ["discover", "threads", "repos", "evaluate"]
```

  `phases_seen` reads `run_log` lines of the form `"phase: <name>"`, which `DbProgress.phase`
  writes.

- [ ] **Step 2: Run the tests and see them fail.**
- [ ] **Step 3: Implement `fetch.py`.**
- [ ] **Step 4: Run the tests and see them pass.** Expected: 5 passed.
- [ ] **Step 5: Commit** with `git commit -s -m "patchtrail: fetch runs with lock and progress"`.

---

### Task 13: Import from the old scripts

**Files:**
- Create: `src/patchtrail/importer.py`, `tests/test_importer.py`

**Interfaces:**
- Produces:
  - `ImportReport`, a dataclass: `patches: list[str]`, `merged: list[str]`, `fixes: list[str]`,
    `skipped: list[str]`.
  - `import_old(conn, mine: frozenset[str], *, now: int, old_config: Path | None = None, old_state:
    Path | None = None) -> ImportReport`. The defaults are `$XDG_CONFIG_HOME` (or `~/.config`) and
    `$XDG_STATE_HOME` (or `~/.local/state`). It opens every old file read-only, and steps 3 to 6 are
    per patch:
    1. Read `lkml-watch/threads` as `(name, msgid)` pairs, as lkml-watch `load_threads` does (lines
       78-89).
    2. Group the names that differ only by a trailing `-v<N>`. The base name is the name without the
       suffix, and each `N` becomes a revision version; unsuffixed names get 1. A group of more than
       one name goes in `merged`.
    3. Skip a msgid that is already a revision root (`skipped`), which makes the import idempotent.
       Otherwise create the patch and revisions.
    4. Load `lkml-watch/NAME.mbox` with `split_mbox` and `upsert_mails`, with `first_seen = now`.
       - Set the revision's subject, author and posted_at, and the patch's `project`, from the root
         mail.
       - Set `relation` to `mine` if the root mail's author is in `mine`, else `following`.
    5. Read `lkml-watch/NAME.seen`.
       - If every mail id is in it, record a snapshot (empty fragment) and `mark_read`.
       - Otherwise, first record a snapshot built from the seen mails only, with `taken_at = now - 1`,
         set it as the reference, then record the full snapshot. The patch ends up unread, with the
         unseen mails as the change.
    6. Read each `stable-watch/fixes` line, `NAME COMMIT [TREE-URL BRANCH]`:
       - `set_commit(source="manual")`;
       - with a tree, `tree_url`, `tree_branch` and `tree_source='manual'`;
       - a NAME with no patch becomes a `following` patch with no revisions.

- [ ] **Step 1: Write the failing tests** in `tests/test_importer.py`.
  - Build old files under `tmp_path`: a `threads` file with `kvm-bar-efault-v2 b@x`,
    `kvm-bar-efault-v1 a@x` and `iowq-cpuset c@x`; one mbox per name; `.seen` files where iowq-cpuset
    lacks its last mail; and a `fixes` file with `iowq-cpuset 0659e44ce739ecd856164c75a5325b7959a2921d
    https://git.kernel.org/pub/scm/linux/kernel/git/axboe/linux.git io_uring-7.4`.

```python
def test_import(conn, old):
    before = snapshot_of_tree(old.root)                     # {path: (mtime_ns, bytes)}
    r = import_old(conn, frozenset({"me@example.org"}), now=1000, old_config=old.config, old_state=old.state)
    assert sorted(r.patches) == ["iowq-cpuset", "kvm-bar-efault"] and r.merged == ["kvm-bar-efault"]
    kvm = store.get_patch(conn, "kvm-bar-efault")
    assert [x["version"] for x in store.revisions(conn, kvm["id"])] == [1, 2]
    assert not snapshot.unread(conn, kvm["id"])
    io = store.get_patch(conn, "iowq-cpuset")
    assert snapshot.unread(conn, io["id"])
    assert [c.field for c in snapshot.since_read(conn, io["id"])[1]] == ["mail"]
    assert (io["tree_url"], io["tree_branch"], io["tree_source"]) == (
        "https://git.kernel.org/pub/scm/linux/kernel/git/axboe/linux.git", "io_uring-7.4", "manual")
    assert snapshot_of_tree(old.root) == before             # old files untouched

def test_import_twice_is_idempotent(conn, old):
    import_old(conn, frozenset({"me@example.org"}), now=1000, old_config=old.config, old_state=old.state)
    r = import_old(conn, frozenset({"me@example.org"}), now=2000, old_config=old.config, old_state=old.state)
    assert r.patches == [] and len(r.skipped) == 3
```

- [ ] **Step 2: Run the tests and see them fail.**
- [ ] **Step 3: Implement `importer.py`.**
- [ ] **Step 4: Run the tests and see them pass.** Expected: 2 passed.
- [ ] **Step 5: Commit** with `git commit -s -m "patchtrail: import from lkml-watch and stable-watch"`.

---

### Task 14: CLI: reading commands and rendering

**Files:**
- Create: `src/patchtrail/render.py`, `src/patchtrail/data/neomuttrc` (copy of `~/.config/lkml-watch/neomuttrc`, with the header comment changed to `ptl open`), `tests/test_cli_read.py`
- Modify: `src/patchtrail/cli.py`

**Interfaces:**
- Consumes: store, snapshot, mail, `run_fetch`, `Busy`.
- Produces, in `render.py`, pure functions of `(conn, …) -> list[str]`:
  - `change_line(conn, c: Change) -> str`, with these formats:
    - `stage: submitted → accepted`
    - `standing: <old text> → <new text>`
    - `trailers: +Reviewed-by Tomita Moeko`
    - `mail: +1 · Jens Axboe: Re: [PATCH] …`: the count, then the sender and subject of the newest
      added mail.
    - `commit 0659e44ce739: accepted → released v7.4-rc1`
    - `commit 0659e44ce739: dropped from its tree?`, when `missing` appears in the new value but not
      the old.
    - `6.1.y: applies → conflict`: for multi-commit patches, append ` (0659e44ce739)`.
    - `FAILED mail for 6.1.y: <url>`
    - `closed: – → moved (converted to a GitLab MR)`
    - A missing old or new value prints as `–`.
  - `summary_lines(conn, patch) -> list[str]`, three lines, plus up to two optional ones:
    - `f"{name:{w}}  {subject}"`;
    - an indent, then `f"{project} · {stage} · {standing text} ({n} message(s)[, k new])"`;
    - an indent, then the lore link `https://lore.kernel.org/all/<root msgid>/`. A patch with no
      revisions prints its first commit instead;
    - when the patch has links: an indent, then `"links: " + " · ".join(link_label(u) + " " + u)`;
    - when it has a note: an indent, then `f"note: {note}"`.
    The links and note come from Task 15's schema 002; Task 14 reads them only if the `links` table
    exists, so the two tasks can land in order.
  - `link_label(url: str) -> str`: a short label for known link forms.
    - `https://github.com/<o>/<r>/pull/<n>` → `PR #<n>`
    - `https://gitlab.<…>/<…>/-/merge_requests/<n>` → `MR !<n>`
    - any URL with `/browse/<KEY-123>` → `<KEY-123>`
    - otherwise the host name.
  - `kernel_lines(state) -> list[str]`: the stable-watch report body (lines 478-509) rendered from
    the state document:
    - `Fixes:` and `Cc: stable` line;
    - `mainline:` line;
    - one line per series in the form `f"    {series+'.y':<8}{text}"`;
    - prerequisite lines, limited to 8 unless `-v`;
    - FAILED mails.
  - `status_lines(conn, names) -> list[str]`:
    - for each unread patch, or each named one: `summary_lines`, then
      `"    since you read it on YYYY-MM-DD:"` (`"    not read yet:"` with no reference), then each
      `change_line` indented by 6;
    - prints `["nothing unread"]` when the list is empty.
- Produces, in `cli.py`, these commands. Exit status is 0 on success; unknown names give exit 1 with
  `ptl: not tracked: NAME[, …]` on stderr.
  - `ptl` with no subcommand runs `status`.
  - `status [NAME…] [--fetch]`: `--fetch` runs `run_fetch(trigger="cli", patch_names=NAME or
    None)`. On `Busy`, print `ptl: a fetch is already running (run N, <phase> <step>/<steps>)` and exit
    1.
  - `ls [NAME…] [--hidden] [--closed] [-v]`: `summary_lines`, plus `kernel_lines` for kernel
    patches, ordered by last activity as lkml-watch `by_activity` does (lines 299-304). Never touches
    the network.
  - `show NAME…`: `summary_lines`, then one line per mail in the lkml-watch `describe` format (lines
    244-250). Mails after the reference snapshot are marked `*`.
  - `trailers [NAME…]`: port of lkml-watch `cmd_trailers` (lines 401-413), without fetching.
  - `history NAME`: per snapshot, newest first, `YYYY-MM-DD HH:MM` and then the `change_line`s.
  - `mine [ADDR…]`: `lore.search` per address. Prints `f"  {date}  {name or '(not tracked)':32}
    {subject}"`, marking hidden patches as `(hidden) NAME`.
  - `open [NAME]`: writes the patch's mails to a temp mbox under `paths.home / "tmp"` and runs
    `os.execvp("neomutt", ["neomutt", "-n", "-F", <data/neomuttrc>, "-R", "-f", mbox])`. The default
    NAME is the most recently created patch.

- [ ] **Step 1: Write the failing tests** in `tests/test_cli_read.py`. They use `capsys` and
  `main([...])`, with two fixtures in `tests/conftest.py` that build the DB through store and
  snapshot only:
  - `populated`:
    - `iowq-cpuset` (kernel) has a root mail from `me@example.org` and a reply from `Jens Axboe
      <axboe@kernel.dk>` with subject `Re: [PATCH] io_uring/io-wq: apply the current cpuset to new
      workers`;
    - its read reference is a snapshot at stage submitted with only the root mail, and its latest
      snapshot is at stage accepted with both mails;
    - `erofs` (erofs-utils) has one mail and is read.
  - `populated_kernel`: `populated`, plus a latest snapshot for `iowq-cpuset` whose state has the seven
    branches of the spec's example. The key `0659e44ce739` is set in each; 6.1 is `conflict` with
    detail `["CONFLICT in io_uring/io-wq.c, after 2 queued patches to the same files: needs a backport
    by hand"]`, and 5.15 and 5.10 are `not_affected` with detail `["no 84eacf177faa"]`.

```python
def test_status_shows_only_unread(populated, capsys):
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "iowq-cpuset" in out and "erofs" not in out
    assert "      stage: submitted → accepted" in out
    assert "      mail: +1 · Jens Axboe: Re: [PATCH] io_uring/io-wq: apply the current cpuset to new workers" in out
    assert main(["status"]) == 0 and "iowq-cpuset" in capsys.readouterr().out   # status never marks read

def test_nothing_unread(conn, capsys):
    assert main(["status"]) == 0 and capsys.readouterr().out.strip() == "nothing unread"

def test_ls_offline_lists_all(populated, capsys, monkeypatch):
    monkeypatch.setattr("patchtrail.sources.lore.fetch_thread", boom)
    assert main(["ls"]) == 0
    out = capsys.readouterr().out
    assert "https://lore.kernel.org/all/" in out and "erofs" in out

def test_ls_kernel_lines(populated_kernel, capsys):
    main(["ls", "iowq-cpuset"])
    out = capsys.readouterr().out
    assert "    6.1.y   CONFLICT in io_uring/io-wq.c" in out and "    5.15.y  not affected: no 84eacf177faa" in out

def test_unknown_name(capsys):
    assert main(["show", "nope"]) == 1 and "ptl: not tracked: nope" in capsys.readouterr().err

def test_status_fetch_busy(populated, capsys, monkeypatch):
    monkeypatch.setattr("patchtrail.cli.run_fetch", raise_busy(run_row(phase="threads", step=3, steps=12)))
    assert main(["status", "--fetch"]) == 1
    assert "a fetch is already running" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests and see them fail.**
- [ ] **Step 3: Implement `render.py` and the commands.**
- [ ] **Step 4: Run the tests and see them pass.** Expected: 6 passed.
- [ ] **Step 5: Commit** with `git commit -s -m "patchtrail: CLI reading commands"`.

---

### Task 15: CLI: changing commands

**Files:**
- Modify: `src/patchtrail/cli.py`, `src/patchtrail/fetch.py` (adds `reevaluate`), `src/patchtrail/db.py`
  (atomic migrations), `src/patchtrail/store.py` (links and note)
- Create: `tests/test_cli_write.py`, `src/patchtrail/schema/002_links.sql`, `docs/agents.md`

**Interfaces:**
- Produces these commands. Every change is committed in one transaction.
  - `read NAME…|--all` and `unread NAME…`: `mark_read` and `mark_unread`.
  - `add NAME MSGID|URL [--follow] [--note TEXT] [--link URL]... [--json]`. This is the
    registration interface for scripts and AI agents that post patches (asked for by the user).
    Plan 2 exposes the same semantics as `POST /api/patches`.
    - It validates the name and uses `parse_msgid`.
    - **Idempotent:** if the msgid is already a revision root, it doesn't create anything. It adds
      any new `--link` URLs to the owning patch, replaces the note when `--note` is given, and
      reports that patch. Its name wins even if NAME differs, and the exit status is 0.
    - If NAME is taken by a different patch, it exits 1 with `ptl: name taken: NAME`.
    - Otherwise it creates the patch (relation `following` with `--follow`), a revision, the links
      and the note.
    - Then it runs `run_fetch(trigger="cli", patch_names=[NAME], discover_new=False)`. A thread that
      lore hasn't archived yet is not an error: the run logs it, the patch stays with standing
      "not fetched yet", and later runs fetch it.
    - On `Busy`, the patch stays added. Text mode prints `added NAME; it is fetched on the next run`.
    - **Output:** text mode prints `summary_lines`. `--json` prints exactly one JSON object to stdout:
      `{"name", "msgid", "project", "stage", "standing", "links", "note", "url"}`, where `url` is
      `https://lore.kernel.org/all/<msgid>/`, `stage` and `standing` come from the latest snapshot
      (`null` before the first one), and `links` is a list of URLs.
  - `link NAME URL...` and `unlink NAME URL...`: add or remove links on an existing patch.
  - `note NAME TEXT`: set the note. An empty TEXT clears it.
  - **Schema 002** (`schema/002_links.sql`):
    - `ALTER TABLE patches ADD COLUMN note TEXT;`
    - `CREATE TABLE links (patch_id INTEGER NOT NULL REFERENCES patches(id) ON DELETE CASCADE, url
      TEXT NOT NULL, added_at INTEGER NOT NULL, PRIMARY KEY (patch_id, url));`
    - `db.connect` applies each migration atomically, together with its `PRAGMA user_version`, so a
      failing migration leaves the old version intact. `SCHEMA_VERSION` becomes 2.
    - `store` gains `add_links(conn, patch_id, urls, now) -> list[str]` (the new ones),
      `remove_links(conn, patch_id, urls)`, `links(conn, patch_id) -> list[str]` (by `added_at`),
      and `note` joins the `set_field` allowlist.
    - Links and the note are not part of the snapshot state, so they never flag a patch.
  - **`docs/agents.md`:** the contract for agents, in under 40 lines. After sending a patch with `git
    send-email` or `b4 send`, run `ptl add <short-name> <Message-ID> [--link <PR or Jira URL>]...
    --json`. It is safe to repeat, and lore may need a few minutes. It includes one example of the
    JSON output.
  - `follow NAME [COMMIT] [TREE-URL BRANCH] [--stable]`:
    - on an existing patch: set the commit (`manual`), the tree (`manual`) and `force_stable`;
    - for a new NAME, COMMIT is required: create a `following` patch with project `kernel` and no
      revisions;
    - with no COMMIT on an existing patch, use the patch's first commit, as stable-watch `add` did
      with lkml-watch's thread.
  - `hide NAME…` and `unhide NAME…`.
  - `rm NAME…`: insert every revision root into `ignored`, then delete the patch (cascades).
  - `rename OLD NEW`.
  - `merge NAME OTHER`: move OTHER's revisions, mails, commits and skips into NAME, delete OTHER, and
    record a fresh snapshot for NAME on the next run.
  - `split NAME VERSION`: move that revision into a new patch named `NAME-v{VERSION}`.
  - `close NAME rejected|dropped|moved [--note TEXT]`.
  - `skip NAME SERIES` and `unskip NAME SERIES`. SERIES accepts `6.1`, `6.1.y` and `linux-6.1.y`.
  - `mark-applied NAME [COMMIT]`: `manual_applied=1`, and `set_commit(manual)` when COMMIT is given.
  - The commands that change state (`close`, `skip`, `unskip`, `mark-applied`, `hide` and `merge`)
    recompute the patch's snapshot right away. They call `fetch.reevaluate(conn, paths, cfg,
    patch_id)`, which rebuilds the state from the stored mails and the previous fragment without any
    network, and `record`s it. Add `reevaluate` to `fetch.py` in this task.
  - `fetch [NAME…]`: runs `run_fetch(trigger="cli")` and prints progress lines (`phase: …`, `step
    i/n: label`) as they happen, through a `Progress` that also echoes to stdout. `Busy` behaves as in
    `status`.
  - `poll [NAME…]`: `fetch`, then for each patch that got a new snapshot in this run, its name and
    the `change_line`s since the previous snapshot. Otherwise it prints `nothing new`.
  - `watch`: every 30 s, print the changes of snapshots newer than the last one printed, until ^C. It
    does not fetch.
  - `check COMMIT…`: under the fetch lock, `KernelTrail.prepare([])` and then `check_commits`. It
    prints the report and stores nothing.
  - `backport NAME|COMMIT SERIES [DIR]`: `make_backport` in the current directory, defaulting to
    `NAME-SERIES`.
  - `import`: `import_old`, then print the report.

- [ ] **Step 1: Write the failing tests** in `tests/test_cli_write.py`. Run them on `populated`;
  network-touching commands get monkeypatched `run_fetch`, `KernelTrail` and `make_backport`.

```python
def test_read_unread(populated, capsys):
    assert main(["read", "iowq-cpuset"]) == 0
    main(["status"]); assert capsys.readouterr().out.strip() == "nothing unread"
    main(["unread", "iowq-cpuset"]); main(["status"]); assert "iowq-cpuset" in capsys.readouterr().out

def test_rm_is_not_rediscovered(populated, conn):
    root = store.revisions(conn, store.get_patch(conn, "erofs")["id"])[0]["root_msgid"]
    assert main(["rm", "erofs"]) == 0
    assert conn.execute("SELECT 1 FROM ignored WHERE msgid=?", (root,)).fetchone()

def test_close_moved_flags_change(populated, conn, capsys):
    main(["read", "--all"])
    assert main(["close", "erofs", "moved", "--note", "converted to a GitLab MR"]) == 0
    main(["status"]); assert "closed: – → moved (converted to a GitLab MR)" in capsys.readouterr().out

def test_skip_series_forms(populated, conn):
    for s in ["6.1", "6.1.y", "linux-6.1.y"]:
        assert main(["skip", "iowq-cpuset", s]) == 0
    assert conn.execute("SELECT series FROM branch_skips").fetchall() == [("6.1",)]

def test_follow_bare_commit(populated, conn):
    assert main(["follow", "someones-fix", "0123456789abcdef0123456789abcdef01234567"]) == 0
    p = store.get_patch(conn, "someones-fix")
    assert (p["relation"], p["project"]) == ("following", "kernel") and store.revisions(conn, p["id"]) == []

def test_merge_and_split(populated, conn):
    a = store.add_patch(conn, "kvm-bar-efault", now=1); store.add_revision(conn, a, "v1@x", version=1, subject="[PATCH] KVM: a")
    b = store.add_patch(conn, "kvm-v2", now=1); store.add_revision(conn, b, "v2@x", version=2, subject="[PATCH v2] KVM: b")
    conn.commit()
    assert main(["merge", "kvm-bar-efault", "kvm-v2"]) == 0
    assert store.get_patch(conn, "kvm-v2") is None
    assert [r["version"] for r in store.revisions(conn, a)] == [1, 2]
    assert main(["split", "kvm-bar-efault", "2"]) == 0
    c = store.get_patch(conn, "kvm-bar-efault-v2")
    assert [r["root_msgid"] for r in store.revisions(conn, c["id"])] == ["v2@x"]

def test_add_follow(populated, conn, monkeypatch):
    monkeypatch.setattr("patchtrail.cli.run_fetch", lambda *a, **k: 1)
    assert main(["add", "x-thread", "https://lore.kernel.org/all/abc@d/", "--follow"]) == 0
    assert store.get_patch(conn, "x-thread")["relation"] == "following"

def test_add_for_agents_json_idempotent_links(populated, conn, monkeypatch, capsys):
    monkeypatch.setattr("patchtrail.cli.run_fetch", lambda *a, **k: 1)
    pr, jira = "https://github.com/lf-edge/eve/pull/5123", "https://example.atlassian.net/browse/ZED-42"
    assert main(["add", "iowq-fix", "<new@x>", "--link", pr, "--note", "found by agent", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert (out["name"], out["msgid"], out["links"], out["note"], out["stage"]) == (
        "iowq-fix", "new@x", [pr], "found by agent", None)
    assert out["url"] == "https://lore.kernel.org/all/new@x/"
    # again, under another name and with one more link: same patch, link added, nothing duplicated
    assert main(["add", "other-name", "new@x", "--link", jira, "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["name"] == "iowq-fix" and out["links"] == [pr, jira]
    assert store.get_patch(conn, "other-name") is None

def test_add_name_taken(populated, monkeypatch, capsys):
    monkeypatch.setattr("patchtrail.cli.run_fetch", lambda *a, **k: 1)
    assert main(["add", "erofs", "brand-new@x"]) == 1
    assert "ptl: name taken: erofs" in capsys.readouterr().err

def test_links_do_not_flag(populated, conn):
    main(["read", "--all"])
    assert main(["link", "erofs", "https://github.com/o/r/pull/7"]) == 0
    assert main(["note", "erofs", "x"]) == 0
    assert not snapshot.unread(conn, store.get_patch(conn, "erofs")["id"])

def test_migration_to_v2_is_atomic(tmp_path, monkeypatch):
    # a broken 002 must leave user_version at 1 and no partial table behind
    ...use monkeypatch to make the migration loader return a 002 script that fails midway,
       connect, expect sqlite3.Error, then assert user_version == 1 and no `links` table...
```

  Write `test_migration_to_v2_is_atomic` in full. Point the loader at a temp directory holding
  `001_init.sql` (copied) and a broken `002_x.sql`, through a module-level `MIGRATIONS` hook or
  function parameter in `db.py` that tests can override.

- [ ] **Step 2: Run the tests and see them fail.**
- [ ] **Step 3: Implement the commands and `fetch.reevaluate`.**
- [ ] **Step 4: Run the tests and see them pass.** Expected: 11 passed.
- [ ] **Step 5: Commit** with `git commit -s -m "patchtrail: CLI changing commands, agent registration"`.

---

### Task 16: Setup, seeding, install and the switch-over check

**Files:**
- Create: `src/patchtrail/setup.py`, `tests/test_setup.py`, `README.md`, `contrib/claude-skill/patchtrail-register/SKILL.md`
- Modify: `src/patchtrail/cli.py` (the `setup` command)

**Interfaces:**
- Produces:
  - `git_version_ok(out: str | None = None) -> tuple[bool, str]`. It parses `git --version` and
    requires at least 2.40. The failure message is `"patchtrail needs git >= 2.40 (found X.Y.Z)"`.
  - `write_default_config(p: Paths, addresses: list[str]) -> bool`. Writes `config.toml` only if it
    is missing, with `addresses`, `listen = "0.0.0.0:8470"`, `interval_hours = 3` and commented-out
    `seed` and `[kernel]` examples. Returns whether it wrote.
  - `run_setup(*, seed: Path | None, no_seed: bool, do_import: bool | None) -> int`, behind `ptl setup
    [--seed PATH | --no-seed] [--import | --no-import]`:
    1. check git, failing with exit 1;
    2. create the home directory;
    3. write the config with the addresses from `my_addresses` (git config);
    4. connect to the database;
    5. seed:
       - `seed`, or when neither flag is given and `~/.local/state/stable-watch/linux.git` exists,
         that path. Print `seeding from <path> (hardlinks, no copy)`.
       - Call `KernelRepo(paths.linux).ensure(seed)` only if `paths.linux` doesn't exist yet;
    6. import when `do_import` is true, or when it is None and `~/.config/lkml-watch/threads` exists;
    7. print the next steps: `ptl fetch` (the first run fetches mainline and stable; with a seed this
       takes minutes, without one several GB) and `ptl status`.
  - `README.md`: what it is, install (`make install`), `ptl setup`, the command table (copy spec
    section 9), where files live, the coexistence note, and a short "Registering patches from
    scripts and AI agents" section pointing to `docs/agents.md`.
  - `contrib/claude-skill/patchtrail-register/SKILL.md`: a Claude Code skill wrapping
    `docs/agents.md`. Its description should trigger after an agent sends a patch upstream with
    `git send-email` or `b4 send`. The README says to copy it to `~/.claude/skills/` to enable it.
    `ptl setup` does not install it.

- [ ] **Step 1: Write the failing tests** in `tests/test_setup.py`

```python
def test_git_version():
    assert git_version_ok("git version 2.43.0") == (True, "2.43.0")
    assert git_version_ok("git version 2.39.1") == (False, "patchtrail needs git >= 2.40 (found 2.39.1)")

def test_setup_seeds_and_imports(kfix, old_scripts_home, capsys):
    assert run_setup(seed=kfix.mainline, no_seed=False, do_import=None) == 0
    p = paths()
    assert p.config.exists() and (p.linux / "HEAD").exists()
    assert "seeding from" in capsys.readouterr().out
    assert store.list_patches(db.connect(p.db))                       # old threads imported

def test_setup_twice_keeps_config(kfix):
    run_setup(seed=None, no_seed=True, do_import=False)
    paths().config.write_text('addresses = ["x@y.org"]\n')
    run_setup(seed=None, no_seed=True, do_import=False)
    assert paths().config.read_text() == 'addresses = ["x@y.org"]\n'
```

- [ ] **Step 2: Run the tests and see them fail.**
- [ ] **Step 3: Implement `setup.py`, the `setup` command and the README.**
- [ ] **Step 4: Run the full suite.** Run `make test`. Expected: all tests pass with no network
  access.
- [ ] **Step 5: Commit** with `git commit -s -m "patchtrail: setup, seeding and README"`.
- [ ] **Step 6: Install and run it on this machine.** This is the switch-over check; the old scripts
  stay untouched. Run each step in order and confirm its expected result:
  1. `make install && command -v ptl`: prints `~/.local/bin/ptl`.
  2. `ptl setup`:
     - it seeds from `~/.local/state/stable-watch/linux.git` in under 2 minutes and imports 11
       threads into 10 patches (kvm-bar-efault v1 and v2 merged);
     - `git -C ~/.local/state/stable-watch/linux.git for-each-ref | md5sum` gives the same value
       before and after.
  3. `ptl ls`: every patch from `python3 ~/bin/lkml-watch ls` is present, with the same standing
     text.
  4. `ptl fetch`, run with the Bash tool's `run_in_background`, then wait for the notification:
     - the run ends `ok`;
     - `ptl ls iowq-cpuset` shows the same per-branch outcomes as `python3 ~/bin/stable-watch ls`,
       unless the branches have moved since: 7.3, 6.18 and 6.12 apply, 6.6 after 2 queued, 6.1
       conflicts, 5.15 and 5.10 are not affected.
  5. `ptl status`: lists only patches with changes, and running it twice gives the same output.
  6. Report any difference between old and new output to the user. Do not delete or edit anything
     under `~/bin`, `~/.config/{lkml,stable}-watch` or `~/.local/state/{lkml,stable}-watch`.
