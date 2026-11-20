# patchtrail Plan 1: follow-ups

Open items found while building and running Plan 1 (2026-11-19). None blocks using `ptl`.
Fix them before or during Plan 2.

## Found in the first real run on the build server

1. ~~**A rebased commit is fixed only on the second run.** The maintainer's "Applied" mail can name a~~ (fixed in Plan 2)
   ~~commit that was later rebased away. The replacement search runs only for commits already stored,~~
   ~~so one named in that run's mail is skipped. kbuild showed "not in the repository" after run 1, and~~
   ~~was corrected (and flagged) after run 2.~~
   - ~~Fix: also run the replacement search for non-manual mail commits that are missing.~~
2. ~~**The "not tagged for stable" hint is wrong.** `render.kernel_lines` prints it twice and says~~ (fixed in Plan 2)
   ~~"for the branches below" when no branches are shown.~~
3. ~~**A line is missing compared with stable-watch.** stable-watch printed "FAILED mails from~~ (fixed in Plan 2)
   ~~stable: none"; ptl prints nothing.~~
4. ~~**The wrong subject shows for a v2 sent inside the v1 thread.** vfio-igd shows the v1 subject,~~ (fixed in Plan 2)
   ~~because v2 was posted in the v1 thread.~~
5. ~~**Maintainer trees are fetched every run for patches never applied.** net, net-next and~~ (fixed in Plan 2)
   ~~linux-vfio (GitHub) are fetched every run for the 2024 net-stmmac and reenable-runtime-pm patches.~~
   - ~~Fix: skip long-idle patches. This is a policy choice; decide it with Plan 2.~~

## Deferred from reviews: before Plan 2's service and HTTP API

- ~~`busy_timeout` on connections, since a service and the CLI will share the database.~~ (fixed in Plan 2)
- ~~Migration race between two processes: `BEGIN IMMEDIATE` and re-read `user_version` inside the~~ (fixed in Plan 2)
  ~~transaction. This must land before migration 003.~~
- ~~Timeout for the b4 subprocess, and wrap its `OSError` in `LoreError`.~~ (fixed in Plan 2)
- ~~Failure-handler ordering in `run_fetch`: finish the run row before logging.~~ (fixed in Plan 2)
- ~~The b4 guard in tests should fail the test, not only log.~~ (fixed in Plan 2)
- A `ptl add` (lore-only) first snapshot uses up `read_on_first_snapshot`. An already-applied thread
  added this way flags once on the next full fetch.
- ~~`skip`/`unskip` show "skipped" only after the next fetch, because `reevaluate` reuses the previous~~ (fixed in Plan 2)
  ~~fragment. The page will want this immediately.~~

## Deferred from reviews: smaller

- **CLI and display:**
  - `mark-applied` blanks a known commit's subject.
  - `merge` drops OTHER's tree and `force_stable`.
  - `read --all` skips hidden patches.
  - `mine` shows lore's UTC date.
  - `open` never cleans up its temporary mboxes.
- **Detection:**
  - MAINTAINERS `F:` globs over-match, and `X:` lines are ignored.
  - The `detect_project` "erofs-utils" match is case-sensitive.
- **Data handling:**
  - `merge_by_change_id` drops the newer patch's `hidden` and `read_on_first_snapshot`.
  - A split revision sharing a change-id merges back on the next fetch.
- **Robustness:**
  - The importer is not atomic.
  - `is_ancestor` treats exit 128 as False.
  - `slug()` doesn't sanitize ref-illegal characters.
- **Performance:**
  - The change-id sync parses every mail below a root on each run.
  - MAINTAINERS is parsed per patch.
  - Per-ref subprocess loops; `for-each-ref --contains` would do.
- **Test coverage:**
  - `first_tag` edge cases.
  - The queue update/reset path.
  - The binary search with more than 2 tags.
  - `compose_state`'s `finished` rule.
  - `flag_view`.
