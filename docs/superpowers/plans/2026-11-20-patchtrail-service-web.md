# patchtrail Plan 2: service, API and web page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ptl serve`, a service that fetches every 3 hours and serves the approved dashboard (board on
top, detail panel below) and a JSON API, installable as a systemd user service that survives
logout.

**Architecture:**
- **One process:** `ptl serve` runs the HTTP server and a scheduler thread. Fetches never run inside
  it; each fetch is a child `python -m patchtrail fetch` process, tracked by PID, under the existing
  fetch lock.
- **HTTP:** the server is stdlib `http.server.ThreadingHTTPServer`. A pure `App.handle(Request) ->
  Response` router sits behind it, so tests need no sockets.
- **Shared code:**
  - JSON views live in `views.py`.
  - Every changing operation lives in `actions.py`, which the CLI and the API both call.
- **The page:** React and TypeScript, built by Vite into `src/patchtrail/web/dist/`, which ships
  inside the package. It polls the API; there is no SSE.

**Tech Stack:**
- Python ≥ 3.12, stdlib only (`http.server`, `subprocess`, `threading`), plus b4.
- Web: React 18, TypeScript 5, Vite 5, Vitest 2 with jsdom and Testing Library.
- Node ≥ 20, to build only.

**Spec:** `docs/superpowers/specs/2026-11-19-patchtrail-design.md`. Read it first, especially:
- §10 Service
- §12 Web page
- §8 "Registering patches"
- §13 Packaging

Approved mockup: `docs/mockups/board-with-detail.html`. Open items from Plan 1:
`docs/superpowers/plans/2026-11-19-patchtrail-core-cli-followups.md`.

**Calls this plan makes where the spec leaves it to the builder (§18):**
- **HTTP server:** stdlib `ThreadingHTTPServer`, not FastAPI/uvicorn. The API has about 15
  single-user endpoints, and the only runtime dependency stays b4.
- **Progress:** the page polls `/api/status` every 2 s while a run is going and every 30 s
  otherwise. There is no SSE.
- **Timeout:** a fetch child is killed after 4 hours (`fetch_timeout_hours`).
- **Idle patches:** they stop fetching maintainer trees after 180 days (`idle_days`, Task 3). The
  follow-ups doc left this policy open. The user confirmed it on 2026-11-20, with one addition:
  idle patches stay tracked and listed, in `ptl ls` and on the board. The board folds them under
  an expandable "+N idle" at the bottom of their column (Task 10).
- **Releases:** a GitHub Actions workflow builds a wheel with the page inside when a `v*` tag is
  pushed. Tagging stays the user's call.

## Global Constraints

- **Python and dependencies:**
  - Python ≥ 3.12. The only runtime dependency stays `b4>=0.13`.
  - The server uses only the stdlib.
  - pytest stays a dev dependency.
- **Node:** needed only to build the page (≥ 20). Running `ptl serve` never needs Node.
- **Config defaults:** `listen = "0.0.0.0:8470"`, `interval_hours = 3`, `fetch_timeout_hours = 4`,
  `idle_days = 180`, `hosts = []`.
- **No login.** Every `/api` request, GET included, must name a known `Host` (final review I6,
  against DNS rebinding):
  - Allowed, case-insensitive and with any port: an IP literal (IPv4, or bracketed IPv6),
    `localhost`, `socket.gethostname()`, `socket.getfqdn()`, and each name in the config option
    `hosts` (`Config.hosts: list[str]`, default empty; `ptl setup` writes it commented out).
  - Anything else answers 403 `{"error": "unknown Host <name>; add it to hosts in config.toml"}`.
    A missing or malformed Host header answers 403 `{"error": "missing or malformed Host
    header"}`. Static files stay open.
- Every request that changes state (POST, PUT, DELETE) must also pass two checks:
  - **(a)** If it carries an `Origin` header, the Origin must equal `http://` + its `Host` header.
    Otherwise answer 403.
  - **(b)** It must have `Content-Type: application/json`. Otherwise answer 415.
  - A request with no Origin, such as curl from an agent, passes (a).
- **The page and the API never take a git URL.**
  - The only network fetch they can cause is a lore fetch by Message-ID.
  - No endpoint sets a maintainer tree, renames, deletes, merges or splits. Those stay CLI-only.
- **Mail is rendered as text.**
  - `dangerouslySetInnerHTML`, `innerHTML` and `eval` must never appear in `web/src`.
    `tests/test_spdx.py` gets a check for this (Task 9).
- **Read state:** only the explicit read and unread actions change it. Opening a card, a tab or a
  mail never marks anything read.
- **Processes:**
  - Never use `pkill`, `pgrep -f`, `nohup` or `setsid`.
  - The fetch child is a `subprocess.Popen` started with `process_group=0`, so its process group ID
    is its own PID. A timeout kills that group with `os.killpg(child.pid, …)`.
- **Database:** every connection sets `PRAGMA busy_timeout=5000` (Task 1). The service, its fetch
  child and the CLI all share the database.
- **Times:** the API carries integer epoch seconds; the page formats them in local time.
- **SPDX headers:**
  - `.py`, `.toml`, Makefile and `.yml`: `# SPDX-License-Identifier: Apache-2.0`
  - `.sql`: `-- SPDX-License-Identifier: Apache-2.0`
  - `.ts` and `.tsx`: `// SPDX-License-Identifier: Apache-2.0`
  - `.css`: `/* SPDX-License-Identifier: Apache-2.0 */`
  - `.html`: `<!-- SPDX-License-Identifier: Apache-2.0 -->`
  - The built bundle in `src/patchtrail/web/dist/` is exempt.
- **JS dependencies:** pinned to exact versions, with `web/package-lock.json` committed.
  - `react` and `react-dom` 18.3.1
  - `@types/react` 18.3.12, `@types/react-dom` 18.3.1
  - `typescript` 5.6.3
  - `vite` 5.4.11, `@vitejs/plugin-react` 4.3.4
  - `vitest` 2.1.8, `jsdom` 25.0.1
  - `@testing-library/react` 16.1.0, `@testing-library/dom` 10.4.0,
    `@testing-library/user-event` 14.5.2
  - No other runtime libraries: no router, no state library, no CSS framework.
- **Binding:** dev servers bind `0.0.0.0`. The user opens pages from a laptop, and 127.0.0.1 is
  unreachable from there.
- **Python tests stay hermetic** (Plan 1's `hermetic` fixture):
  - `urllib.request.urlopen` is patched to raise. Socket tests use `http.client.HTTPConnection`
    to 127.0.0.1 on port 0.
  - The b4 guard fails the test (Task 1).
- **Web tests:** never touch the network; `fetch` is a `vi.fn`.
- **Commits:** `git commit -s`. No hand-written Signed-off-by, and no session or tool trailers.
- **Old scripts:** their files stay read-only: `~/bin/*`, `~/.config/{lkml,stable}-watch` and
  `~/.local/state/{lkml,stable}-watch`.

## Review Focus

1. **Two "Fetch now" clicks at once.** The clicks may come from two tabs, or arrive while a CLI or
   cron fetch runs. Exactly one run happens. The other request gets 409 with the running run's
   progress, and both tabs show the progress with the button disabled. *Tests: Task 6
   `test_start_refused_while_child_alive` and `test_start_refused_when_cli_holds_lock`; Task 7
   `test_fetch_now_conflict`; Task 9 `FetchButton.test.tsx`.*
2. **A fetch child that hangs, is killed, or dies with the service.** The run ends up `interrupted`
   with a reason. It never shows as running forever, and the next scheduled fetch still happens.
   *Tests: Task 6 `test_timeout_kills_group_and_marks_interrupted`,
   `test_stale_running_row_reaped`, `test_schedule_after_failed_run`.*
3. **Mail that looks like HTML or script** (`<script>`, `<img onerror=…>`, `&amp;`) is shown
   literally. *Tests: Task 5 `test_mails_body_is_raw_text`; Task 12 `Thread.test.tsx` "renders
   markup as text".*
4. **Requests from another site open in the laptop's browser**, such as a cross-site JSON POST or a
   `text/plain` form POST, are refused and change nothing. An agent's curl POST without Origin
   works. *Tests: Task 7 `test_cross_origin_refused`, `test_form_post_refused`,
   `test_agent_post_without_origin`.*
5. **The CLI and the service write the database at the same time.** For example, `ptl read` runs
   while a fetch child writes, or an upgrade migrates while the service runs. There are no
   "database is locked" errors and no double migration. *Tests: Task 1 `test_busy_timeout_waits`,
   `test_concurrent_connect_migrates_once`.*

---

## File map

```
src/patchtrail/db.py            + busy_timeout, migration under BEGIN IMMEDIATE (Task 1)
src/patchtrail/fetch.py         + reap_stale(); failure ordering (Task 1)
src/patchtrail/sources/lore.py  + b4 timeout, OSError → LoreError (Task 1)
src/patchtrail/store.py         + display_subject() (Task 2)
src/patchtrail/actions.py       NEW: changing operations shared by CLI and API (Task 4)
src/patchtrail/views.py         NEW: JSON views (Task 5)
src/patchtrail/service.py       NEW: Runner, Scheduler, systemd unit (Tasks 6, 8)
src/patchtrail/server.py        NEW: App router, static files, serve() (Task 7)
src/patchtrail/cli.py           uses actions; + serve, service, hidden fetch options
src/patchtrail/config.py        + fetch_timeout_hours, idle_days
src/patchtrail/web/dist/        built bundle, git-ignored, shipped in the wheel
web/                            React app: package.json, package-lock.json, tsconfig.json,
                                vite.config.ts, index.html, src/
.github/workflows/ci.yml        NEW: tests, web build, release wheel on v* tags (Task 13)
tests/test_concurrency.py test_actions.py test_views.py test_service.py test_server.py
```

## API contract

Python Tasks 5 to 7 produce this contract, and web Tasks 9 to 12 consume it.
`web/src/types.ts` mirrors it exactly. Every response is JSON except static files. Every error is
`{"error": "<message>"}`.

**Types**

```ts
type Run = { id: number; trigger: "cli"|"schedule"|"page"|"api"; started_at: number;
  finished_at: number|null; status: "running"|"ok"|"failed"|"interrupted";
  phase: string|null; step: number|null; steps: number|null; error: string|null };

type Status = { version: string; now: number; interval_hours: number;
  next_fetch_at: number|null;        // newest *full* run's started_at + interval; now if none yet
  running: Run|null;                 // the run in progress, from any process, full or not
  starting: boolean;                 // the service started a child whose run row isn't written yet
  last_run: Run|null;                // newest full run that finished ok (the bar's "fetched")
  error: {run_id: number; at: number; error: string; status: "failed"|"interrupted"}|null };
      // newest full run that failed, or was interrupted with an error (killed, crashed,
      // stopped with the service), if no ok full run came after it
  // A full run discovers, takes every patch and follows the trails (runs.full = 1, migration
  // 003). `ptl add`, POST /api/patches, `ptl fetch NAME` and --lore-only runs are not full.

type Link = { url: string; label: string };          // label from render.link_label
type Pill = { series: string; state: string; tone: "ok"|"warn"|"bad"|"na" };
type Standing = { kind: string; who: string; since: number; text: string };

type Card = { name: string; project: string; relation: "mine"|"following"; subject: string;
  stage: string; stages: string[];                   // stages the project declares
  closed: "rejected"|"dropped"|"moved"|null; closed_note: string|null; hidden: boolean;
  standing: Standing; your_turn: boolean;
  unread: boolean; unread_changes: number;           // flagging changes since read
  links: Link[]; note: string|null; pills: Pill[];
  finished: boolean; finished_at: number|null;       // start of the newest unbroken finished streak
  idle: boolean;                                     // not closed, not finished, no commit, newest
                                                     // mail older than idle_days (Task 3's rule)
  last_activity: number;                             // newest mail date, 0 if none
  version: number;                                   // newest series revision's version, 1 if none
  fetched: boolean };                                // has a snapshot

type ChangeT = { field: string; text: string; flags: boolean };   // text from render.change_line
type Step = { stage: string; state: "done"|"todo"|"skipped"; at: number|null; note: string|null };
type Prereq = { sha: string; subject: string; tag: string|null; stable: boolean; text: string };
type BranchRow = { sha: string; state: string; tag: string|null; tone: Pill["tone"];
  detail: string[]; prereqs: Prereq[] };
type Detail = Card & {
  lore_url: string|null;
  revisions: {version: number; msgid: string; subject: string; posted_at: number|null;
              kind: "series"|"backport"; branch: string|null}[];
  steps: Step[];
  since: { at: number|null; changes: ChangeT[] };    // at null: never read
  commits: {sha: string; subject: string; where: string|null; stage: string;
            release: string|null; cc: string|null;
            fixes: {sha: string; release: string|null; known: boolean}[];
            mainline: string|null}[];    // kernel: "mainline: v6.19-rc1", "mainline: only in
                                         // linux-next", "not in the repository"; else null
  branches: {series: string; skipped: boolean; rows: BranchRow[]}[];  // kernel only, newest series first
  failed: {series: string; date: string; url: string}[];
  hint: string|null;
  history: {at: number; changes: ChangeT[]}[];       // newest first
  thread: {msgid: string; depth: number; date: number; who: string; you: boolean;
           snippet: string; new: boolean}[] };       // overview summary, tree order
type Mail = { msgid: string; parent: string|null; depth: number; date: number;
  from_name: string; from_addr: string; you: boolean; subject: string; new: boolean;
  body: string; omitted: number; lore_url: string };
type MailGroup = { label: string|null; mails: Mail[] };   // null: the series; "6.1.y backport"
```

**Endpoints**

| Method and path | Body | Answer |
|---|---|---|
| `GET /api/status` | | 200 `Status` |
| `POST /api/fetch` | `{}` | 202 `Status`; 409 `{error, running: Run\|null}` |
| `GET /api/runs/<id>/log?after=<n>` | | 200 `{lines: [{n, at, line}]}`. `n` is the `run_log` rowid; only rows with rowid > after. 404 for an unknown run |
| `GET /api/patches` | | 200 `{patches: Card[]}`, all of them, hidden and closed included |
| `GET /api/patches/<name>` | | 200 `Detail`; 404 |
| `GET /api/patches/<name>/mails` | | 200 `{groups: MailGroup[]}`; 404 |
| `POST /api/patches` | `{name, msgid, follow?, note?, links?}` | 201 created, 200 already registered: `ptl add --json`'s object. 409 when the name belongs to another patch; 400 for bad input |
| `POST /api/patches/<name>/read` · `/unread` · `/hide` · `/unhide` | `{}` | 200 `Card` |
| `POST /api/patches/<name>/close` | `{reason, note?}` | 200 `Card`; 400 for a bad reason |
| `POST /api/patches/<name>/mark-applied` | `{commit?}` | 200 `Card`; 400 for a bad hash |
| `POST /api/patches/<name>/skip` · `/unskip` | `{series}` | 200 `Card`; 400 for a bad series |
| `POST /api/patches/<name>/links` | `{add?: [url], remove?: [url]}` | 200 `Card`; 400 for a non-http(s) URL |
| `PUT /api/patches/<name>/note` | `{note: string\|null}` | 200 `Card` |
| `GET /` and `GET /p/...` and any other non-`/api` path | | `index.html`, or the file under `dist/` |

**Pill and branch tones.** Each series gets one pill: the worst tone over the patch's commits, in
the order bad > warn > ok > na. A series with a FAILED mail is `bad`.

| state | tone |
|---|---|
| `released`, `in_branch`, `queued`, `applies` | ok |
| `applies_after_queue`, `backport_sent` | warn |
| `conflict` | bad |
| `not_affected`, `skipped`, `not_fetched` | na |
| `failed` (pill only: a series with a FAILED mail and no worse branch state) | bad |

**Steps:** one per stage the project declares.
- `done` if the patch has reached the stage.
- `skipped` if the patch is past the stage but no snapshot ever had it.
- `todo` otherwise.
- `at`:
  - `submitted`: the oldest series revision's `posted_at`.
  - Any other stage: the `taken_at` of the first snapshot at or past it.
  - null for todo and skipped.
- `note`:
  - `accepted`: `tree_branch` when one is known.
  - `applied`: human text, never a raw `where` value or URL.
    - Kernel: the first line of `render._mainline` for the newest commit, without the stable hint:
      `mainline: v6.19-rc1`, `mainline: only in linux-next`, `mainline: only in <branch>`.
    - Other projects: `applied upstream` once the newest commit is applied or released.
    - `mainline: not yet` when there is no such commit.
  - `released`: the newest commit's release.
  - `backports`: `"N of M branches settled"`, counting released, not affected and skipped.
  - Otherwise null.

---

### Task 1: Database and fetch hardening for a shared database

The open items from the follow-ups doc that must land before a service shares the database.

**Files:**
- Modify: `src/patchtrail/db.py`, `src/patchtrail/fetch.py`, `src/patchtrail/sources/lore.py`,
  `src/patchtrail/cli.py` (fetch options), `tests/conftest.py` (b4 guard)
- Create: `tests/test_concurrency.py`
- Test: `tests/test_fetch.py`, `tests/test_lore.py`

**Interfaces:**
- Produces:
  - `db.connect()` sets `PRAGMA busy_timeout=5000` before anything else. It runs each pending
    migration as `BEGIN IMMEDIATE`, re-reads `user_version` inside the transaction, and skips a
    migration another process applied meanwhile.
  - `fetch.reap_stale(paths: Paths, conn, now: int, error: str | None = None) -> int`:
    - It tries the fetch lock without blocking.
    - If it gets the lock, no fetch is running, so it marks every `runs` row with
      `status='running'` as `interrupted`. It sets `finished_at=now` and, if `error` is given,
      `error` (otherwise it keeps the old one). It returns how many rows it changed.
    - If another process holds the lock, it returns 0.
  - `run_fetch`'s failure handler calls `_finish(...)` before `progress.log(...)`, so a failing log
    write cannot leave the run `running`.
  - `lore.fetch_thread` passes `timeout=600` to b4's `subprocess.run`. It raises `LoreError` on
    `subprocess.TimeoutExpired` and on `OSError` (b4 missing or not executable).
  - `ptl fetch` gets two options hidden from `--help` (`help=argparse.SUPPRESS`):
    - `--trigger {cli,schedule,page,api}`, default `cli`, passed to `run_fetch`;
    - `--lore-only`, which passes `lore_only=True, discover_new=False`.
  - The `tests/conftest.py` b4 guard calls `pytest.fail(...)` instead of only logging.

- [ ] **Step 1: Write the failing tests** in `tests/test_concurrency.py`:
  - `test_busy_timeout_waits`:
    - Connection A begins `BEGIN IMMEDIATE` and a thread commits it after 0.5 s.
    - Meanwhile connection B runs `UPDATE kv ...`.
    - B must succeed without `sqlite3.OperationalError`.
  - `test_concurrent_connect_migrates_once`:
    - Point `db.MIGRATIONS` at a temp dir holding `001_init.sql` from the package plus a
      `002_x.sql` that does `CREATE TABLE once_only(x)`.
    - Two threads call `db.connect()` on the same new path at once.
    - Both succeed, `user_version` is 2, and `once_only` exists.
  - `test_reap_stale_marks_running_rows`:
    - Insert a `running` row with no lock held.
    - `reap_stale(paths, conn, 100, "killed")` returns 1, and the row reads
      `interrupted`/`100`/`killed`.
  - `test_reap_stale_leaves_live_run`: while `fetch.locked(paths, conn)` is held, it returns 0
    and the row stays `running`.
- [ ] **Step 2: Write the remaining tests:**
  - In `tests/test_lore.py`: `test_b4_timeout_is_lore_error` and `test_b4_missing_is_lore_error`,
    with `subprocess.run` monkeypatched to raise `TimeoutExpired` and `FileNotFoundError`.
  - In `tests/test_fetch.py`: `test_failed_run_finished_even_if_log_fails`. Make
    `DbProgress.log` raise after the first failure; the run row must still read `failed`.
  - In `tests/test_cli_write.py`: `test_fetch_trigger_option_recorded`. Run `ptl fetch --trigger
    schedule` with fakes; the newest run has `trigger == "schedule"`.
- [ ] **Step 3: Run** `uv run pytest -q tests/test_concurrency.py tests/test_lore.py
  tests/test_fetch.py tests/test_cli_write.py`. **Expected:** the new tests fail.
- [ ] **Step 4: Implement the interfaces above.**
- [ ] **Step 5: Run** `uv run pytest -q`. **Expected:** all pass.
- [ ] **Step 6: Commit:** `git commit -s -m "db, fetch: busy timeout, safe migrations, reap stale runs, b4 timeout"`

### Task 2: Core fixes the page would show

Follow-ups 1 to 4 from the first real run, and the immediate `skip`/`unskip`.

**Files:**
- Modify: `src/patchtrail/store.py`, `src/patchtrail/render.py`,
  `src/patchtrail/projects/kernel/__init__.py`, `src/patchtrail/fetch.py` (`reevaluate`)
- Test: `tests/test_store.py`, `tests/test_cli_read.py`, `tests/test_kernel_trail.py`,
  `tests/test_cli_write.py`

**Interfaces:**
- Produces:
  - `store.display_subject(conn, patch_id) -> str`: the subject of the newest mail that meets all
    of these:
    - it is in the newest series revision's thread (`thread_mails` of its root);
    - it is from that revision's author;
    - its subject doesn't start with `re:` (case-insensitive);
    - its subject is not patch N/M (`mail._PATCH_N_OF_M`).

    It falls back to the newest series revision's subject, then the first commit's subject, then
    `""`. It reads only the `mails` columns and never parses `raw`. `render.summary_lines` uses it.
  - `render.kernel_lines`:
    - prints the "not tagged for stable" hint once, from `state["hint"]` only, and `_mainline`
      no longer adds it;
    - when the patch has no branch rows, the hint reads "not tagged for stable: ask
      stable@vger.kernel.org to take it" instead of "…for the branches below";
    - prints `FAILED mails from stable: none` when a commit has `stable` true and
      `state["failed"]` is empty.
  - In `KernelTrail`, the replacement search (find a rebased commit by subject and author) also
    runs for a commit named in this run's "Applied" mail and missing from every fetched tree.
    That is any commit whose source is not `manual`, not only the stored ones.
  - `fetch.reevaluate` applies the patch's skips to the reused trail fragment, so a change shows at
    once:
    - **Skip:** each branch entry of a skipped series becomes `{"state": "skipped", "tag": None,
      "detail": [], "prereqs": [], "was": <the previous entry>}`.
    - **Unskip:** an entry of an unskipped series that is `skipped` goes back to its `was`. Without
      `was`, it becomes `{"state": "not_fetched", "tag": None, "detail": ["checked on the next
      fetch"], "prereqs": []}`.
    - `was` is detail; `snapshot.flag_view` ignores it.
  - `KernelTrail`'s own skipped entries also carry `was` when the patch's previous state had an
    entry for that branch.

- [ ] **Step 1: Write the failing tests:**
  - `test_display_subject_v2_in_v1_thread`: a `[PATCH v2]` sent as a reply inside the v1 thread
    becomes the subject.
  - `test_display_subject_ignores_backport_posting`: a `[PATCH 6.1.y]` revision rooted below the
    series is not the subject.
  - `test_display_subject_ignores_patch_n_of_m`
  - `test_ls_hint_once_without_branches`: the hint appears once, with "to take it".
  - `test_ls_failed_none_line`
  - `test_rebased_commit_found_on_first_run`:
    - Use the fixture's maintainer tree with the "Applied" mail naming a commit that was rebased
      away.
    - After one run, the commit is the replacement, with `source == "search"`, and no
      "not in the repository" line.
  - `test_skip_shows_at_once`:
    - `ptl skip NAME 6.1`, then `ptl ls` shows `won't backport` for 6.1 with no fetch in between.
    - `ptl unskip NAME 6.1` brings back the previous state text.
- [ ] **Step 2: Run them.** **Expected:** they fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -q`. **Expected:** all pass.
- [ ] **Step 5: Commit:** `git commit -s -m "core: display subject, stable hint and FAILED lines, rebased commits on the first run, immediate skip"`

### Task 3: Idle patches stop fetching maintainer trees

Follow-up 5. **Policy, confirmed by the user on 2026-11-20:** a patch with no known commit whose
newest mail is more than `idle_days` (default 180) old no longer causes its MAINTAINERS `T:` trees
to be fetched. It is still searched in linux-next and mainline, which are fetched anyway, so an
apply still shows. Idle patches stay tracked, fetched from lore, and listed. The user will come
back to them. Only the page folds them away (Task 10).

**Files:**
- Modify: `src/patchtrail/config.py`, `src/patchtrail/projects/kernel/__init__.py`,
  `src/patchtrail/setup.py` (comment in the default config)
- Test: `tests/test_kernel_trail.py`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `Config.idle_days: int = 180`, read from config.toml `idle_days`.
  - `Config.fetch_timeout_hours: float = 4`, read from `fetch_timeout_hours` (Task 6 uses it).
  - `KernelTrail.prepare` computes a patch's trees as today, but leaves out patches that are idle:
    - no commits;
    - no manual tree;
    - `max(m.date for m in view.mails) < now - idle_days*86400`.

    It logs `"<name>: idle since <date>, maintainer trees not fetched"` once per run.

- [ ] **Step 1: Write the failing tests:**
  - `test_idle_patch_trees_not_fetched`: a fixture patch with a 2024 mail date. The `T:` tree URL
    is not fetched; assert on the fake fetch's recorded URLs.
  - `test_recent_patch_trees_fetched`
  - `test_manual_tree_always_fetched`
  - `test_idle_days_from_config`
- [ ] **Step 2: Run them.** **Expected:** they fail.
- [ ] **Step 3: Implement.** Add `idle_days` and `fetch_timeout_hours` to the default
  config text with one comment line each.
- [ ] **Step 4: Run** `uv run pytest -q`. **Expected:** all pass.
- [ ] **Step 5: Commit:** `git commit -s -m "kernel: skip maintainer trees of long-idle patches"`

### Task 4: `actions.py`: changing operations shared by the CLI and the API

**Files:**
- Create: `src/patchtrail/actions.py`, `tests/test_actions.py`
- Modify: `src/patchtrail/cli.py`. Its commands call actions, and the CLI behaves exactly as
  before.

**Interfaces:**
- Produces:
  - `class ActionError(Exception)` with `.status: int` (400, 404 or 409) and the message as
    `str(e)`.
  - `patch(conn, name) -> sqlite3.Row`: raises 404 `not tracked: NAME`.
  - `parse_series(arg) -> str` and `parse_commit(arg) -> str`: these move here from cli
    `_series` and `_commit_arg`, with the same messages, as 400.
  - `check_urls(urls) -> list[str]`: 400 `not an http(s) URL: …`.
  - Each of these runs in one `store.atomic` transaction. Those that affect state call
    `fetch.reevaluate` exactly where the CLI does today: hide, close, mark-applied, skip, unskip.
    - `mark_read(conn, row)` and `mark_unread(conn, row)`
    - `hide(conn, paths, cfg, row)` and `unhide(conn, row)`
    - `close(conn, paths, cfg, row, reason: str, note: str | None)`: reason must be one of
      rejected, dropped or moved, else 400.
    - `mark_applied(conn, paths, cfg, row, commit: str | None)`
    - `skip(conn, paths, cfg, row, series)` and `unskip(conn, paths, cfg, row, series)`
    - `add_links(conn, row, urls, now)` and `remove_links(conn, row, urls)`
    - `set_note(conn, row, text: str | None)`: empty text clears the note.
  - `register(conn, *, name, msgid, follow=False, note=None, links=(), now) -> tuple[sqlite3.Row,
    bool]`. This is `cmd_add`'s database part, moved here; the bool is True when the patch was
    created.
    - Bad name, msgid or URL: 400.
    - Name taken by another patch: 409 `name taken: NAME`.
  - `add_json(conn, row, msgid) -> dict`: the object `ptl add --json` prints, moved from
    `_add_report`.
  - The CLI wraps every action call to turn `ActionError` into `CliError` with the same message.

- [ ] **Step 1: Write the failing tests** in `tests/test_actions.py`. Include one test per error
  status:
  - `test_register_created_then_existing`: the first call returns `(row, True)`. The same msgid
    under another name returns the first row and False, and adds the new links.
  - `test_register_name_taken_409`
  - `test_register_bad_msgid_400`
  - `test_close_bad_reason_400`
  - `test_patch_unknown_404`
  - `test_skip_reevaluates`
  - `test_mark_read_unread_roundtrip`
- [ ] **Step 2: Run** `uv run pytest -q tests/test_actions.py`. **Expected:** it fails on import.
- [ ] **Step 3: Implement `actions.py`** and switch `cli.py` over to it.
- [ ] **Step 4: Run** `uv run pytest -q`. **Expected:** all pass. The existing CLI tests prove the
  output is unchanged.
- [ ] **Step 5: Commit:** `git commit -s -m "actions: one implementation of every change for the CLI and the API"`

### Task 5: `views.py`: the API's JSON

**Files:**
- Create: `src/patchtrail/views.py`, `tests/test_views.py`

**Interfaces:**
- Consumes:
  - `store.display_subject` (Task 2)
  - `snapshot.latest`, `unread`, `since_read`, `history`
  - `render.change_line` and `render.link_label`
  - `fetch.last_run`
  - `projects.get_project`
- Produces (shapes from "API contract"):
  - `status(conn, *, interval_hours: float, now: int, starting: bool, version: str) -> dict`
  - `run_dict(row) -> dict`
  - `run_log(conn, run_id, after: int) -> dict | None`: None for an unknown run.
  - `card(conn, row, mine, *, now: int, idle_days: int) -> dict`:
    - Never calls `mail.parse_mail`.
    - `idle` follows the rule in the contract. A patch with no mail at all is not idle.
    - Uses `snapshot.latest`'s state, `mails.date` for `last_activity`, and
      `store.display_subject`.
    - A patch with no snapshot gets the standing `{"kind": "none", "who": "", "since": 0,
      "text": "not fetched yet"}` and the project's first stage.
  - `cards(conn, mine, *, now: int, idle_days: int) -> list[dict]`: every patch.
  - `detail(conn, row, mine) -> dict`
  - `mails(conn, row, mine) -> dict`:
    - `body` and `omitted` come from `mail.text_body(raw)`.
    - Within a group, mails nest by their stored `in_reply_to`. A parent outside the group makes
      the mail a top-level one.
    - Children are ordered by date. `depth` counts from 0.
    - `new` is true for msgids not in the reference snapshot's `mails`.
    - Each backport revision gets its own group labelled `"<branch>.y backport"`, after the series
      group.
  - `snippet(body: str) -> str`: the first non-empty line that doesn't start with `>` and isn't an
    attribution line (one ending in `wrote:`), cut to 120 characters.

- [ ] **Step 1: Write the failing tests**, building the database with Plan 1's fixtures
  (`tests/mails.py`, the `db` fixture):
  - `test_card_shape`: the keys are exactly the `Card` keys.
  - `test_card_never_parses_mail`: monkeypatch `patchtrail.mail.parse_mail` to raise, then call
    `cards()`.
  - `test_pills_worst_tone_per_series`: two commits, one with 6.1 `applies` and one with 6.1
    `conflict`, give a `bad` pill. A FAILED mail for 6.6 also gives `bad`.
  - `test_unread_changes_counts_flagging_only`
  - `test_finished_at_is_start_of_streak`
  - `test_idle_flag`:
    - A 2024 patch with no commit is idle.
    - It stops being idle with a commit, when closed, or when it has a mail newer than
      `idle_days`.
  - `test_steps_done_skipped_todo`: a kernel patch accepted without trailers has `reviewed`
    skipped, and `applied` onwards todo.
  - `test_mails_nested_and_grouped`
  - `test_mails_body_is_raw_text`: a body containing `<script>alert(1)</script>` comes back
    byte-for-byte as text.
  - `test_mails_new_flag`
  - `test_status_next_fetch_and_error`:
    - With no runs, `next_fetch_at == now`.
    - After an ok run at t, it is `t + interval`.
    - `error` is set by a failed run with no ok run after it, and cleared by a later ok run.
- [ ] **Step 2: Run** `uv run pytest -q tests/test_views.py`. **Expected:** it fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -q`. **Expected:** all pass.
- [ ] **Step 5: Commit:** `git commit -s -m "views: JSON for status, cards, patch detail and threads"`

### Task 6: `service.py`: the fetch runner and the scheduler

**Files:**
- Create: `src/patchtrail/service.py`, `tests/test_service.py`

**Interfaces:**
- Consumes:
  - `fetch.locked`, `fetch.reap_stale` and `fetch.Busy` (Task 1)
  - `Config.interval_hours` and `Config.fetch_timeout_hours`
- Produces:
  - `class Runner`, constructed as `Runner(paths, *, timeout_s: float, spawn=subprocess.Popen,
    now=time.time)`. Thread-safe: one internal lock guards `start` and `poll`.
    - `start(trigger: str, names: list[str] | None = None, lore_only: bool = False) -> None`.
      - It raises `fetch.Busy(run_row_or_None)` when its own child is alive, or when the fetch
        lock is held, tested with `fetch.locked` and released at once.
      - Otherwise it spawns `[sys.executable, "-m", "patchtrail", "fetch", "--trigger",
        trigger, *(["--lore-only"] if lore_only else []), *(names or [])]` with
        `process_group=0`, `stdin=DEVNULL` and `stdout=DEVNULL`. stderr is inherited, so
        tracebacks reach the journal.
    - `poll() -> None`:
      - Reaps a finished child. After any child exit it calls `reap_stale(..., error="fetch
        process exited with status N")` when N ≠ 0.
      - Kills a child running longer than `timeout_s`: `os.killpg(pid, SIGTERM)`, then SIGKILL if
        it is still alive 30 s later. It then calls `reap_stale(..., error="killed after H
        hours")`.
      - With no child alive, it calls `reap_stale(...)` with no error, which clears rows left by
        a dead CLI fetch.
    - `child_pid -> int | None`
    - `starting(conn) -> bool`: True while the child is alive and no `running` row has
      `pid == child_pid`.
  - `class Scheduler`, constructed as `Scheduler(runner, paths, *, interval_s: float,
    now=time.time)`.
    - `next_at(conn) -> int`: the newest *full* run's `started_at + interval_s`, whatever its
      trigger or status; `now()` when there is none. A partial run (`ptl add`, POST
      /api/patches, `ptl fetch NAME`) never postpones it.
    - `tick() -> None`:
      - Calls `runner.poll()`.
      - If `now() >= next_at` and no child is alive, calls `runner.start("schedule")`.
      - Swallows `Busy`; a CLI or cron fetch counts as the run.
    - `run_forever(stop: threading.Event, every_s: float = 15) -> None`
  - Startup catch-up comes from `next_at`: after downtime, the first tick is already due.

- [ ] **Step 1: Write the failing tests.** Use a real child process where the test is about
  processes:
  - `test_start_spawns_child_with_trigger`: a fake `spawn` records argv.
  - `test_start_refused_while_child_alive`
  - `test_start_refused_when_cli_holds_lock`: hold `fetch.locked` in the test, expect `Busy`.
  - `test_timeout_kills_group_and_marks_interrupted`:
    - `spawn` starts `[sys.executable, "-c", "<insert a running row with os.getpid(); start a
      grandchild sleep 600; sleep 600>"]` with `process_group=0`.
    - Use `timeout_s=1`, a fake `now`, and the 30 s grace patched to 1 s.
    - After `poll()`, the child and grandchild are gone (`os.kill(pid, 0)` raises), and the row
      is `interrupted` with "killed after".
  - `test_stale_running_row_reaped`: a `running` row with no process and no lock; `poll()` marks
    it interrupted.
  - `test_scheduler_due_at_startup_with_no_runs`
  - `test_scheduler_waits_interval_after_cli_run`
  - `test_schedule_after_failed_run`: a failed run at t; at `t + interval` a run starts.
  - `test_tick_ignores_busy`
- [ ] **Step 2: Run** `uv run pytest -q tests/test_service.py`. **Expected:** it fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -q`. **Expected:** all pass, with no stray processes left
  (each test reaps what it started).
- [ ] **Step 5: Commit:** `git commit -s -m "service: fetch runner with timeout and the 3-hour scheduler"`

### Task 7: `server.py` and `ptl serve`

**Files:**
- Create: `src/patchtrail/server.py`, `tests/test_server.py`
- Modify: `src/patchtrail/cli.py` (`serve` command), `pyproject.toml` (package data),
  `.gitignore`

**Interfaces:**
- Consumes: `actions` (Task 4), `views` (Task 5), `Runner` and `Scheduler` (Task 6).
- Produces:
  - `@dataclass Request(method: str, path: str, query: dict[str, str], headers: dict[str, str],
    body: bytes)`. Header names are lowercase.
  - `@dataclass Response(status: int, body: bytes, content_type: str = "application/json",
    headers: dict[str, str] = {})`
  - `class App`, constructed as `App(paths, cfg, runner, scheduler, *, static_dir: Path | None)`,
    with `handle(req) -> Response`.
    - It opens one `db.connect(paths.db)` per request and closes it.
    - It routes as in the API contract.
    - It runs the Origin and Content-Type checks from Global Constraints before any changing
      route.
    - `ActionError` becomes its `status`, and a bad JSON body becomes 400.
    - An unknown `/api` path gives 404 JSON.
    - `POST /api/patches`:
      - calls `actions.register`;
      - on success calls `runner.start("api", [name], lore_only=True)`, ignoring `Busy`;
      - answers 201 or 200 with `actions.add_json`.
    - `POST /api/fetch` calls `runner.start("page")`. `Busy` gives 409 with `running`.
  - Static files:
    - `static_dir` defaults to `importlib.resources.files("patchtrail") / "web" / "dist"`.
    - A path naming a file inside it is served with a `mimetypes` type, and `/assets/*` gets
      `Cache-Control: max-age=31536000, immutable`.
    - Every other non-`/api` GET serves `index.html` with `Cache-Control: no-cache`.
    - Paths are resolved and must stay inside `static_dir`, else 404.
    - With no `index.html`, GET `/` answers 200 with a short HTML page:
      "patchtrail's web page was not built. Install from a release, or run `make install` in a
      checkout. The API works: /api/status".
  - `serve(paths, cfg, listen: str | None = None) -> int`:
    - Parses `HOST:PORT` (also `[v6]:PORT`).
    - Starts the scheduler thread, then a `ThreadingHTTPServer` whose handler builds a `Request`
      and writes the `Response`.
    - Prints `patchtrail <version> serving on http://HOST:PORT`.
    - On `OSError` EADDRINUSE it prints `ptl: HOST:PORT is in use; is the service running? (ptl
      service status)` and returns 1.
    - On SIGTERM or ^C it stops the scheduler, terminates a running child's process group (the
      same as a timeout, without the grace wait) and returns 0.
  - `ptl serve [--listen HOST:PORT]`
  - `pyproject.toml`: `patchtrail = ["schema/*.sql", "data/*", "web/dist/*",
    "web/dist/assets/*"]`
  - `.gitignore`: `src/patchtrail/web/dist/` and `web/node_modules/`

- [ ] **Step 1: Write the failing tests** against `App.handle`, with a fake runner and a temp
  `static_dir`:
  - `test_status_ok`
  - `test_cards_and_detail`
  - `test_unknown_patch_404`
  - `test_actions_return_card`: one test per action route.
  - `test_note_put`
  - `test_register_201_200_409_400`
  - `test_register_starts_lore_only_fetch`
  - `test_fetch_now_202`
  - `test_fetch_now_conflict`: the fake runner raises `Busy(row)`; the answer is 409 with
    `running.id`.
  - `test_cross_origin_refused`: `Origin: http://evil.example` with `Host: 10.0.0.1:8470` gives
    403, and the database is unchanged.
  - `test_form_post_refused`: `Content-Type: text/plain` gives 415.
  - `test_agent_post_without_origin`: 201.
  - `test_no_route_sets_tree`: POSTing `{"tree_url": ...}` to every action route leaves
    `tree_url` NULL.
  - `test_spa_fallback_and_assets`: `/p/foo/thread` gives index.html; `/assets/x.js` gives the
    file with the immutable cache header; `/../pyproject.toml` gives 404.
  - `test_no_bundle_page`
  - `test_serve_socket_roundtrip`: `serve` on `127.0.0.1:0` in a thread, then `GET /api/status`
    with `http.client`, then shutdown.
- [ ] **Step 2: Run** `uv run pytest -q tests/test_server.py`. **Expected:** it fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -q`. **Expected:** all pass.
- [ ] **Step 5: Commit:** `git commit -s -m "server: JSON API, static page and ptl serve"`

### Task 8: `ptl service install|uninstall|status|logs`

**Files:**
- Modify: `src/patchtrail/service.py`, `src/patchtrail/cli.py`, `src/patchtrail/setup.py`
- Test: `tests/test_service.py`, `tests/test_setup.py`

**Interfaces:**
- Produces:
  - `unit_path() -> Path`: `$XDG_CONFIG_HOME/systemd/user/patchtrail.service`, where
    XDG_CONFIG_HOME defaults to `~/.config`.
  - `unit_text() -> str`:
    ```
    [Unit]
    Description=patchtrail: follow your patches on the mailing lists
    After=network-online.target

    [Service]
    ExecStart=<sys.executable> -m patchtrail serve
    Restart=on-failure
    RestartSec=10
    Environment=PATCHTRAIL_HOME=<path>     (only when $PATCHTRAIL_HOME is set)

    [Install]
    WantedBy=default.target
    ```
  - `install(run=subprocess.run) -> list[str]`, which writes the unit, then:
    - runs `systemctl --user daemon-reload`, then `systemctl --user enable --now
      patchtrail.service`;
    - checks `loginctl show-user $USER -p Linger`. If it is `no`, it runs `loginctl enable-linger
      $USER`. If that fails, it returns the line `run: sudo loginctl enable-linger <user>  (so
      the service keeps running after you log out)`.
    - It returns the lines to print, ending with the page URL from `cfg.listen`.
  - `uninstall(run)`: `disable --now`, removes the unit, `daemon-reload`.
  - `ptl service status` runs `systemctl --user status patchtrail.service --no-pager`.
  - `ptl service logs [-f]` runs `journalctl --user -u patchtrail.service -e [-f]`.
  - `ptl setup` ends with the line: `To fetch every 3 hours and serve the page: ptl service
    install`.

- [ ] **Step 1: Write the failing tests**, with a fake `run` that records argv and returns the
  configured results:
  - `test_unit_text_exec_and_home`
  - `test_install_commands_in_order`
  - `test_install_linger_already_on`
  - `test_install_linger_needs_sudo_prints_hint`
  - `test_uninstall`
  - `test_setup_mentions_service`
- [ ] **Step 2: Run them.** **Expected:** they fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -q`. **Expected:** all pass.
- [ ] **Step 5: Commit:** `git commit -s -m "service: systemd user unit install, uninstall, status and logs"`

### Task 9: Web app scaffold, API client, top bar and Fetch now

**Files:**
- Create:
  - `web/package.json`, `web/package-lock.json`, `web/tsconfig.json`, `web/vite.config.ts`,
    `web/index.html`
  - `web/src/main.tsx`, `web/src/App.tsx`, `web/src/types.ts`, `web/src/api.ts`,
    `web/src/styles.css`
  - `web/src/lib/time.ts`, `web/src/lib/route.ts`
  - `web/src/components/TopBar.tsx`, `web/src/components/FetchButton.tsx`,
    `web/src/components/RunLog.tsx`, `web/src/components/AddDialog.tsx`
  - Tests next to each file (`*.test.ts(x)`), and `web/src/test-setup.ts`
- Modify: `Makefile`, `tests/test_spdx.py`

**Interfaces:**
- Produces:
  - **Scripts in `package.json`:**
    - `build`: `tsc --noEmit && vite build`
    - `test`: `vitest run`
    - `dev`: `vite --host 0.0.0.0`
  - **`vite.config.ts`:**
    - `build.outDir = "../src/patchtrail/web/dist"` and `emptyOutDir: true`.
    - The dev server proxies `/api` to `http://127.0.0.1:8470`.
    - The test environment is jsdom, with setup `src/test-setup.ts`.
  - **`types.ts`:** the API contract types, verbatim.
  - **`api.ts`:** `getStatus()`, `fetchNow()`, `getRunLog(id, after)`, `getPatches()`,
    `getPatch(name)`, `getMails(name)`, `addPatch(body)`, and `act(name, action, body?)` for the
    POST actions and `setNote`.
    - Every call sends `Content-Type: application/json` on writes.
    - A non-2xx answer throws `ApiError {status, message, body}`.
  - **`lib/route.ts`:**
    - `parseRoute(pathname) -> {name: string|null, tab: "overview"|"thread"|"history"}`, for `/`,
      `/p/NAME`, `/p/NAME/thread` and `/p/NAME/history`.
    - `routePath(r)` is its inverse.
  - **`lib/time.ts`:** `short(t)`, `dayTime(t)`, `clock(t)` and `elapsed(from, now)`, as in
    "Nov 11", "2026-11-11 16:27", "13:12" and "4m 12s".
  - **`App.tsx`:**
    - Holds `status`, `patches`, the route and the filters.
    - Polls `getStatus` every 2 s while `running || starting`, else every 30 s.
    - Re-fetches `getPatches` every 30 s, after every action, and when `status.last_run.id`
      changes.
    - Uses `history.pushState` and `popstate` for routes.
  - **`TopBar`:**
    - "patchtrail", the project filter chips (All plus each project present), "Unread only · N",
      "Your turn · N", and a view select (Open | Hidden | Closed).
    - "fetched HH:MM · next HH:MM", the "Add thread" button, and `FetchButton`.
    - When `status.error` is set, it shows it in red until a later ok run clears it.
  - **`FetchButton`:**
    - Idle: a "Fetch now" button.
    - While `running || starting`, the button is replaced by a non-button element showing
      `phase · step N of M · elapsed` ("starting…" before the row exists).
    - Clicking the progress opens `RunLog`.
    - A click sets local `pending` until the next status, so a double click sends one request. A
      409 answer shows the returned progress.
  - **`RunLog`:** a popover listing the run's lines. It polls `getRunLog(id, after)` every 2 s
    while open and the run is running.
  - **`AddDialog`:**
    - Fields: name, Message-ID or lore URL, links (one per line), note, and a "someone else's
      thread" checkbox.
    - It calls `addPatch` and shows the 400/409 message inline. On success it closes and opens
      the new card.
  - **`styles.css`:** the mockup's classes. It defines the CSS variables the mockup assumes
    (`--text-primary`, `--text-secondary`, `--bg-primary`, `--bg-secondary`, `--bg-tertiary`,
    `--border`, `--accent`, `--success`, `--warning`, `--error`, `--selected-bg`) for light and
    for dark, with `@media (prefers-color-scheme: dark)`.
  - **Makefile:**
    - `web:` runs `cd web && npm ci && npm run build`.
    - `install:` depends on `web`, then runs `uv tool install --force .`.
    - `test-web:` runs `cd web && npm ci && npm test`.
  - **`tests/test_spdx.py`:**
    - Also covers `web/src/**`, `web/*.ts`, `web/index.html` and `.github/**/*.yml`, with each
      file type's comment form.
    - New `test_no_raw_html_in_web`: `dangerouslySetInnerHTML`, `.innerHTML` and `eval(` don't
      appear in `web/src`.

- [ ] **Step 1: Scaffold.** Write the files above. Run `cd web && npm install` once to create
  `package-lock.json` with the pinned versions.
- [ ] **Step 2: Write the failing tests:**
  - `route.test.ts`: round trips; an unknown path gives `{name: null}`.
  - `time.test.ts`
  - `api.test.ts`: writes send JSON content-type; 409 throws an `ApiError` carrying the body.
  - `FetchButton.test.tsx`:
    - Idle renders a button.
    - Running renders "fetching stable · step 3 of 9 · 1m 05s" and no button.
    - A double click calls `fetchNow` once.
    - A 409 shows the progress.
  - `TopBar.test.tsx`: the counts; the error banner.
- [ ] **Step 3: Run** `cd web && npm test`. **Expected:** the new tests fail.
- [ ] **Step 4: Implement.**
- [ ] **Step 5: Run** `cd web && npm test && npm run build`, then `uv run pytest -q
  tests/test_spdx.py`. **Expected:** all pass, and `src/patchtrail/web/dist/index.html` exists.
- [ ] **Step 6: Commit** (without `dist/`): `git commit -s -m "web: scaffold, API client, top bar and Fetch now with progress"`

### Task 10: The board

**Files:**
- Create: `web/src/lib/board.ts`, `web/src/components/Board.tsx`, `web/src/components/Card.tsx`
  (with tests)
- Modify: `web/src/App.tsx`

**Interfaces:**
- Consumes: `Card` and `Status` (Task 9).
- Produces:
  - **`COLUMNS`:** `["submitted","reviewed","accepted","applied","released","backports"]`, titled
    Submitted, Reviewed, Accepted, Applied, Released and Backports.
  - **`filterCards(cards, f: {project: string|null; unreadOnly: boolean; yourTurn: boolean;
    view: "open"|"hidden"|"closed"}) -> Card[]`:**
    - `open`: not hidden and not closed.
    - `hidden`: hidden ones.
    - `closed`: closed ones that are not hidden.
  - **`columns(cards, now) -> {stage, cards: Card[], idle: Card[], older: Card[]}[]`:**
    - Each card goes in the column of its `stage`.
    - Within each list: unread first, then `last_activity` descending.
    - `idle` holds the cards with `idle && !unread`. An unread idle card stays in view until it
      is read.
    - `older` holds the cards with `finished && finished_at < now - 30*86400 && !unread`. An
      unread card never folds.
  - **`Board`:**
    - Six columns titled "Title · N", where N counts every card, folded ones included.
    - Each column shows its cards, then a "+N idle" toggle, then a "+N older" toggle. Each toggle
      expands its cards in place. Idle cards are drawn dimmed.
    - Which columns have a fold open is kept in localStorage, wrapped in try/catch.
    - A column scrolls inside itself.
  - **`Card`:**
    - The project chip, coloured per the mockup: kernel `k`, qemu `q`, grub `g`, erofs-utils `e`,
      liburing `l`, and any other project neutral.
    - A badge with `unread_changes`, or "new" when unread with 0 changes.
    - The name; one line of standing, ellipsised (`your turn` in red when `your_turn`); a
      "following" tag when `relation == "following"`.
    - The link labels, and the pills (`p-ok`, `p-warn`, `p-bad`, `p-na`).
    - Class `u` when unread; class `sel` when selected.
    - A click selects it and routes to `/p/NAME`.

- [ ] **Step 1: Write the failing tests:**
  - `board.test.ts`:
    - filter combinations;
    - column assignment;
    - the order;
    - the 30-day fold (29 days stays, 31 days folds);
    - the idle fold: an idle card folds, an unread idle card stays out, and a card is never in
      both folds.
  - `Board.test.tsx`: "+2 idle" expands to show both cards, and the column count includes them.
  - `Card.test.tsx`:
    - the badge numbers and "new";
    - the your-turn text;
    - the pill classes;
    - the link labels.
- [ ] **Step 2: Run** `npm test`. **Expected:** they fail.
- [ ] **Step 3: Implement**, and wire it into `App`.
- [ ] **Step 4: Run** `npm test && npm run build`. **Expected:** both pass.
- [ ] **Step 5: Commit:** `git commit -s -m "web: the board"`

### Task 11: The panel: header, Overview, History and actions

**Files:**
- Create: `web/src/components/Panel.tsx`, `web/src/components/Overview.tsx`,
  `web/src/components/History.tsx`, `web/src/components/LinksNote.tsx` (with tests)
- Modify: `web/src/App.tsx`

**Interfaces:**
- Consumes: `Detail` and `api.act` (Task 9).
- Produces:
  - **`Panel`:**
    - It sits below the board, with a draggable divider. Its height is kept in localStorage,
      every access wrapped in try/catch.
    - Esc or × closes it and routes to `/`.
    - It loads `getPatch(name)` on open, after each action, and when that card's JSON changes in
      the 30 s refresh.
    - **Header:**
      - the chip, the name, and the subject;
      - "Mark read" or "Mark unread", whichever applies;
      - "Hide" or "Unhide";
      - a "Close…" menu: rejected, dropped or moved, with an optional note;
      - "Mark applied" (shown before the `applied` stage, not on closed patches);
      - "lore ↗" when `lore_url` is set;
      - ×.
    - **Tabs:** Overview, Thread · N (a dot when any mail is new), and History. The tab is part
      of the route.
    - After an action it shows the returned card at once, then reloads the detail.
  - **`Overview`:**
    - The stepper from `steps` (`d` for done, `skip` for skipped), each step with its date and
      note.
    - A "Since you read it on D" box listing `since.changes[].text`. It reads "Not read yet" when
      `since.at` is null, and is hidden when there are no changes.
    - For kernel patches with commits, whether or not there are branch rows: each commit's
      line (sha, subject) with its Fixes, `Cc: stable` (or `no Cc: stable`) and `mainline` text.
    - For kernel patches with branch rows, a stable table:
      - Columns: branch, state, detail (`detail` lines), and prerequisites with
        `prereqs[].text`, the first 8 shown and "show all" for the rest.
      - Each row has a "won't backport" button (`skip`) or "backport again" (`unskip`).
    - Under it, "FAILED mails from stable: none" or the list (when there are branch rows or
      FAILED mails).
    - The hint, whenever it is set: a released patch without `Cc: stable` has no branch rows.
    - For other projects with commits, a commit list.
    - A thread summary from `thread`, indented by depth, with a dot when new.
    - Recent history: the first 5 entries.
  - **`History`:** every entry, newest first, with `dayTime(at)` and its change texts; flagging
    changes in bold.
  - **`LinksNote`:**
    - Link chips with × (`links.remove`) and an add field (`links.add`).
    - The note, editable inline (`PUT note`); an empty note clears it.

- [ ] **Step 1: Write the failing tests:**
  - `Panel.test.tsx`:
    - read/unread toggles call the right action and show the returned card's state;
    - Esc closes;
    - the tab follows the route.
  - `Overview.test.tsx`:
    - stepper classes;
    - the since box ("Not read yet");
    - the skip button calls `skip` with the series;
    - prerequisites folded after 8.
  - `History.test.tsx`
  - `LinksNote.test.tsx`
  - A test that opening the panel sends no POST: no read happens by viewing.
- [ ] **Step 2: Run** `npm test`. **Expected:** they fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test && npm run build`. **Expected:** both pass.
- [ ] **Step 5: Commit:** `git commit -s -m "web: detail panel with overview, history and actions"`

### Task 12: The Thread tab

**Files:**
- Create: `web/src/lib/mailtext.ts`, `web/src/components/Thread.tsx` (with tests)

**Interfaces:**
- Consumes: `MailGroup` and `getMails` (Task 9).
- Produces:
  - **`classify(line) -> string|null`**, the CSS class per neomuttrc (`src/patchtrail/data/neomuttrc`):
    - `^diff --git ` and the `index`, `new file mode`, `deleted file mode`, `old mode`, `new mode`,
      `similarity index`, `rename from`/`rename to` lines: `dg`
    - `^(---|\+\+\+) `: `df`
    - `^@@ .* @@`: `dh`
    - `^\+([^+]|$)`: `da`
    - `^-[^-]`: `dd`
    - quote depth 1, 2 and 3 or more (`^>`, `^> ?>`, `^> ?> ?>`): `q1`, `q2`, `q3`
    - `^(Signed-off-by|Reviewed-by|Acked-by|Tested-by|Reported-by|Co-developed-by|Suggested-by|Reported-and-tested-by):`:
      `tr`
    - `^(Fixes|Cc|Link|Closes|BugLink):`: `tf`
    - otherwise null.
  - **`foldDiffs(lines, max = 60) -> ({line: string; cls: string|null} | {fold: number; at:
    number})[]`:** a diff block runs from `diff --git` to the next line that is neither a diff
    line nor context. Each block longer than `max` lines keeps its first `max` lines, followed by
    one fold marker for the rest.
  - **`Thread`:**
    - Groups: the series first, then each backport group under its label.
    - Each mail is indented by `depth`, at 22 px per level up to 6 levels.
    - New mails start open, with the `new` outline and a dot. The others are one collapsed line
      (who, snippet, date); clicking toggles.
    - The "Expand all" / "Collapse all" button.
    - "Open in neomutt: ptl open NAME" copies the command (`navigator.clipboard`, ignoring
      failures).
    - The body is a `<pre class="mb">` of spans, one per line with its class. Every text is a
      React text child, never HTML.
    - A fold marker is a button "… N more lines" that expands that block.
    - `omitted > 0` adds a muted line "[N non-text parts not shown]".
    - Each mail header has a "lore ↗" link (`lore_url`).

- [ ] **Step 1: Write the failing tests:**
  - `mailtext.test.ts`: a table of lines to classes, covering every rule. Also: `+++` is `df`,
    not `da`; `---` is `df`, not `dd`; and fold boundaries.
  - `Thread.test.tsx`:
    - nesting indent;
    - new mails open and others collapsed;
    - Expand all;
    - "renders markup as text": a body with `<img src=x onerror=alert(1)>` appears as visible
      text, and `container.querySelector("img")` is null;
    - the fold button expands.
- [ ] **Step 2: Run** `npm test`. **Expected:** they fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test && npm run build`. **Expected:** both pass.
- [ ] **Step 5: Commit:** `git commit -s -m "web: thread tab with neomutt colours"`

### Task 13: Packaging, CI, docs and version

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `src/patchtrail/__init__.py` (`__version__ = "0.2.0"`), `pyproject.toml` (version),
  `README.md`, `docs/agents.md`, `contrib/claude-skill/patchtrail-register/SKILL.md`,
  `docs/superpowers/plans/2026-11-19-patchtrail-core-cli-followups.md` (strike what this plan
  fixed)
- Test: `tests/test_server.py` (`test_wheel_contains_bundle`)

**Interfaces:**
- Produces:
  - **`ci.yml`** (`# SPDX…` line first):
    - On push and pull request:
      - a `python` job: checkout, `astral-sh/setup-uv`, `uv run pytest -q`;
      - a `web` job: `actions/setup-node` with node 22, `npm ci`, `npm test`, `npm run build`
        in `web/`.
    - On tags `v*`, a `release` job (`permissions: contents: write`):
      - build the web bundle, then `uv build --wheel`;
      - assert that `unzip -l dist/*.whl` lists `patchtrail/web/dist/index.html`;
      - run `gh release create "$GITHUB_REF_NAME" dist/*.whl --generate-notes` with
        `GH_TOKEN: ${{ github.token }}`.
  - **`test_wheel_contains_bundle`:**
    - Skipped unless `src/patchtrail/web/dist/index.html` exists and `uv` is on PATH.
    - Runs `uv build --wheel -o <tmp>` and asserts that the wheel lists
      `patchtrail/web/dist/index.html`.
  - **README:**
    - Install: from a release wheel, with no Node (`uv tool install
      https://github.com/rucoder/patchtrail/releases/download/vX.Y.Z/patchtrail-X.Y.Z-py3-none-any.whl`);
      or from a checkout with Node ≥ 20 (`make install`).
    - `uv tool install git+…` gives the CLI and the API without the page.
    - New sections:
      - **The web page:** what each part does, with no screenshots.
      - **Running the service:** `ptl serve` and `ptl service install|uninstall|status|logs`,
        linger, and how to open `http://<server>:8470` from another machine.
      - **No login:** the page has none; keep the service on a trusted network.
      - **Configuration:** `fetch_timeout_hours` and `idle_days`.
    - "Fetching on a schedule" becomes "the service does this; cron if you don't run it".
  - **`docs/agents.md`:** a section on `POST /api/patches` for agents on other machines: the curl
    example, the 201/200/409/400 answers, and that it needs no Origin header.
  - **The skill:** mention the HTTP form for a remote machine in one line.

- [ ] **Step 1: Write `test_wheel_contains_bundle`. Run it** after `make web`. **Expected:** pass.
- [ ] **Step 2: Write the workflow, the docs and the version bump.**
- [ ] **Step 3: Run** `uv run pytest -q && (cd web && npm test)`. **Expected:** all pass.
- [ ] **Step 4: Commit:** `git commit -s -m "release: CI, wheel with the page, docs for the service and page; 0.2.0"`

### Step 14: Real run on the build server (controller, after the final review)

Like Plan 1's Step 6. Nothing is pushed and no tag is created; those are the user's call.

1. Run `make install` and `ptl --version`. **Expected:** 0.2.0.
2. Run `ptl service install`, then `systemctl --user is-active patchtrail` and `loginctl
   show-user $USER -p Linger`. **Expected:** active, and `Linger=yes` or the sudo hint shown to
   the user.
3. Run `curl -s http://10.208.13.10:8470/api/status`. **Expected:** JSON with `next_fetch_at`.
4. Run `curl -s -X POST -H 'Content-Type: application/json' -d '{}'
   http://10.208.13.10:8470/api/fetch` twice. **Expected:** 202, then 409 with progress. Then
   poll `/api/status` until the run is `ok`, and note its duration.
5. Run `curl -s -X POST -H 'Origin: http://evil.example' -H 'Content-Type: application/json' -d
   '{}' http://10.208.13.10:8470/api/fetch`. **Expected:** 403.
6. Check `ptl status` against the page's unread cards. **Expected:** the same set.
7. Run `systemctl --user restart patchtrail` while a fetch runs. **Expected:** the run becomes
   `interrupted` and a later tick starts a new one.
8. Ask the user to open `http://10.208.13.10:8470` on the laptop and check:
   - the board, the panel and the thread colours;
   - Fetch now with its progress;
   - mark read and unread;
   - deep links.
9. Check that the old scripts' files are untouched (checksums as in Plan 1 Step 6).
