# patchtrail Plan 2: follow-ups

Open items from the task reviews, the final review and the first real run of the service
(2026-11-20). None blocks using `ptl serve` or the page. The final review triaged every item
below as "can wait".

## Found in the first real run on the build server

- **An interrupted run counts for the schedule.** A restart of the service during a fetch
  records that run as `interrupted` ("stopped with the service"). Because `next_fetch_at` takes
  the newest full run whatever its status, the next scheduled fetch comes one interval later, and
  the top bar shows the interruption until then. Consider scheduling from the newest *ok* full
  run, or retrying sooner after an interrupted one.

## Web page

- **Thread tab:**
  - The mail header toggle is a `div` without `role`, `tabIndex` or key handling, so keyboard
    users can't expand a mail (Expand all works).
  - `MailView` is not memoised, which is slow after Expand all on long threads.
  - Fold state is lost when a mail is collapsed and reopened.
  - A transient reload error replaces the whole thread.
  - A multi-file patch folds as one block.
  - The `.ind1`/`.ind2` CSS rules are dead.
  - No tests for the reload tick or the stale-response race.
- **Panel:**
  - Esc closes the panel while the Close… menu or the Add dialog has focus.
  - The divider lacks `aria-value*` and touch support, and its drag listeners leak if the
    panel unmounts mid-drag.
  - Tabs lack `tabpanel`/`aria-controls`.
  - History React keys can collide within one second.
  - The detail loads twice after an action.
  - The panel height is not clamped to the viewport.
  - The "won't backport" button shows once per series, not per row (as intended; document it).
- **Board:**
  - The `useMemo` deps include a per-render `now`, so the memo never hits.
  - A card with an unknown stage is silently dropped.
  - `saveOpen` runs inside the `setOpen` updater.
  - One test uses an impossible idle-and-finished fixture.
- **Top bar and app:**
  - The patches are fetched twice on first load.
  - The connection error is not sequenced and is shared by two requests, so it may flicker.
  - A 202 status takes its sequence number on arrival.
  - A log clicked during "starting…" is adopted by the next run.
  - RunLog's close control is a `span role=button` with no Esc.
  - There is no `color-scheme: light dark`.
  - A non-JSON 2xx answer becomes `null` typed as `T`.
  - `AddResult.links` is typed `unknown`.
  - Test gaps: busy→idle polling, the AddDialog 400 path.
  - `test_no_raw_html_in_web` matches `eval(` inside words and misses `outerHTML`,
    `insertAdjacentHTML` and `new Function`.
- **Since box (spec §7):** the intermediate steps between the reference and the newest
  snapshot don't expand there; only the History tab shows them.

## Server, views and service

- **`cards()` cost:** it loads raw mail BLOBs only to read their dates, and parses the latest
  snapshot three times per card. That took 67 ms at 50 patches and 391 ms at 150 patches with
  20 mails each, per 30 s poll per tab.
- **Steps and notes:**
  - A step counts as done if any snapshot was ever at it, so a stage that moves backwards
    leaves later steps done.
  - The backports note counts series × commit entries, not branches.
- **`mails()`:** computes `parent` separately from the tree walk, so a self-reply or a cycle
  disagrees between the two.
- **Duplication and tests:**
  - `_series_key` and `_new_msgids` are duplicated from `render`.
  - `test_detail_kernel` checks keys with `>=`.
- **Server:**
  - HEAD on `/api/*` answers 404.
  - `App.scheduler` is unused, and `daemon_threads` is set redundantly.
  - A request accepted just before shutdown could still start a child after `terminate()`.
  - The long-path tests accept a 200 as well as a 404.
  - `config.hosts = "name"` (a string, not a list) is read as characters without an error.
  - `fetch.last_run` has no callers left in `src/`.
- **Runner:**
  - The fetch lock is probed every 15 s, so a CLI fetch starting in that window is told one is
    already running.
  - `starting()` is briefly true after the child has written its row.
  - The timeout uses `time.time` (use `time.monotonic`).
  - `terminate()` after a bounded-wait timeout leaves the row `running` until a later poll.
  - Test issues: the grandchild zombie check could flake, and the tests don't close `_conn()`.
- **Service commands:**
  - A missing `loginctl`, `systemctl` or `journalctl` gives a traceback in install, status and
    logs.
  - `uninstall` says "stopped and removed" after a failed disable.
  - There is an `if …: pass else:` construct.
  - The tests duplicate the `getuser` logic.

## Database, fetch and core

- **`db.connect`:**
  - The ROLLBACK is not guarded by `conn.in_transaction`.
  - `_wal` retries every `OperationalError`, not only BUSY/LOCKED.
  - The connection leaks if `_wal` or `_migrations()` fails before the `try`.
  - `_statements` splits per line (two statements on one line in a migration fail).
- **Duplication:** the reap UPDATE is written twice, in `reap_stale` and `run_fetch`.
- **Small items:**
  - The literal 600 appears twice in `lore` (make it a constant).
  - `test_lore`'s `match="b4"` is too loose.
  - The conftest message wording.
  - A local `sqlite3` import in `test_fetch`.
  - `test_busy_timeout_waits` passes on old code too.
- **`render.kernel_lines`:**
  - It reuses `shown` as a bool and then as a list.
  - The " to take it" suffix is added by string concatenation.
- **Missing tests:**
  - `display_subject` with `re:` or an author mismatch.
  - A nested `was` across a fetch.
  - Unskip without `was`.
  - The `populated_kernel` fixture's stage is inconsistent with its commits.
- **Config values:** not type-checked, the same as the existing options.
- **CLI:**
  - `cmd_hide` reevaluates per patch.
  - The `_refused()` wrapper around `hide` does nothing.

## CI and docs

- CI runs twice for each push to a PR branch.
- The release job doesn't check the tag against the package version. Add that before the first
  tag.
- The wheel test can pick up a stale `build/` directory at the repo root.
- README:
  - the `watch` and one-fetch sentences share one long line;
  - the config snippet shows `fetch_timeout_hours` and `idle_days` as active, while `ptl setup`
    writes them commented out.
