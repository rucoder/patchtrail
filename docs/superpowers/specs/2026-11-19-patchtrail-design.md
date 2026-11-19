# patchtrail: design

Date: 2026-11-19. Status: approved by the user on 2026-11-19.

## 1. Intent

The user contributes patches to several open-source projects over mailing lists: the Linux kernel,
QEMU, GRUB, erofs-utils and liburing so far. Two personal scripts follow those patches today:

- `~/bin/lkml-watch` (533 lines of Python) follows each patch's lore thread by Message-ID with b4.
  It works out where the patch stands (applied, reviewed, waiting for a reply, your turn) and
  reports new mail.
- `~/bin/stable-watch` (643 lines) follows an accepted kernel fix into mainline and every maintained
  stable and longterm branch. For each branch it reports whether the branch has the bug, whether the
  fix is released or queued there, whether it applies, and if not, which upstream commits the
  conflicting lines come from. It also reports stable's FAILED mails.

Both scripts live only in `~/bin`, so they can be lost. They run only when called by hand and keep
no history.

The user wants **one product, patchtrail**, in a git repo:

- It installs easily on a new machine.
- A small service fetches every 3 hours on its own.
- A web page on the build server, opened from the user's laptop, shows one dashboard for every
  project the user contributes to.
- After a few days away, the page shows what changed since the user last looked, as a diff
  against the earlier state.

The name follows a patch's trail: list → maintainer tree → mainline → stable. The commands are
`patchtrail` and `ptl`. `pt` was rejected because tcllib's `/usr/bin/pt` and the platinum
searcher already use it.

## 2. Goals

1. One dashboard for every contribution, across all projects. The kernel comes first, then QEMU,
   which has a different process. Other projects get mail tracking only.
2. The service keeps history for good. An update is shown as a diff between the state the user
   last marked read and the state now.
3. Read state is explicit. Nothing becomes read by being viewed. "Mark unread" flags a patch again
   for next time.
4. New patches are discovered automatically: every patch the user sends shows up on its own. An
   accepted kernel fix is followed into mainline and stable automatically. Anything unwanted can be
   hidden with one click.
5. Mail is rendered in the web page. `ptl open` in neomutt stays.
6. The CLI covers everything both scripts do (section 9) before the scripts are retired.
7. Install on a new machine takes a few commands. The service survives logout.

## 3. Non-goals for v1

- Login and TLS. They come later, if the tool ever runs on a VPS.
- The QEMU trail is stage 2. Projects that take merge requests instead of mailed patches come
  later: GitHub pull requests, and GitLab merge requests, which is where GRUB moved (the user's
  GRUB thread stalled because the maintainers asked for an MR). The structure in section 5 must
  make all of these additions, not rewrites.
- Replying to mail or sending patches from the page.
- Notifications (desktop, email, push).
- More than one user.
- Publishing to PyPI. Nothing is pushed anywhere until the user says so.

## 4. Anti-goals: failures even if it works

- Marking anything read without the user doing it.
- Flagging a patch unread for noise, such as "after 2 queued patches" becoming "after 3".
- Breaking `~/bin/lkml-watch` or `~/bin/stable-watch`, or writing into their config or state,
  before the user switches over.
- Writing into anyone's own git refs. Everything fetched lives under `refs/patchtrail/`, tags
  included.
- Letting anyone on the network make the service fetch from a URL of their choosing.
- Hard-coding the user's mail address.

## 5. Concepts

### Project, patch, revision, mail

- **Project** (kernel, QEMU, GRUB, erofs-utils, liburing, …). A patch's project is detected from
  the lists in the root mail's To/Cc. For example: vger lists other than io-uring → kernel;
  qemu-devel → QEMU; grub-devel → GRUB; linux-erofs → erofs-utils; io-uring plus a
  `[PATCH liburing]` subject → liburing. An unknown list gives a generic mail-only project named
  after the list. The user can override the project per patch.
- **Patch**: one change being tracked. It has a unique, renamable name (the slug rule from
  lkml-watch). It can be hidden.
  - It has zero or more revisions. Zero means it is just a commit (see "following" below).
  - It is either **mine** or **following** (agreed with the user), shown on the card:
    - *Mine:* the user's own patches, found by discovery or `ptl add`.
    - *Following:* other people's threads (`ptl add --follow`) or bare commits (`ptl follow NAME
      COMMIT [TREE-URL BRANCH]`, kernel only in v1, like `stable-watch add`).
  - A "following" patch never shows "your turn". A reply from someone else reads "new reply". It
    still flags the patch.
- **Revision**: one posted version of the series (v1, v2, …), with its root Message-ID, version
  number and subject.
  - The newest revision drives the patch's standing. Older ones show as superseded.
  - Today's `kvm-bar-efault-v1` and `-v2` become one patch with two revisions.
  - The user can merge and split revisions from the CLI.
- **Mail**: stored once per Message-ID, with the raw message and the time patchtrail first saw it.

### Stages

The flow is the same for every project. Each project declares which stages it has, so a process
that skips a step just doesn't declare it.

```
submitted → reviewed → accepted → applied → released → backports
 posted     a Reviewed-  maintainer  in mainline  first release  per stable branch
            /Acked-/     tree        / master     tag
            Tested-by
terminal: superseded (newer revision) · rejected · dropped · moved (e.g. to a merge request)
```

`rejected`, `dropped` and `moved` are set by hand in v1.

### Standing: whose turn

Port lkml-watch's `standing()`:

- "APPLIED by X"
- review trailers given
- "waiting for a reply since D" (the user's mail is last)
- "waiting for the maintainer since D" (the last mail carries Reviewed-, Acked- or Tested-by)
- "X replied D: your turn"

"Your turn" is shown in red on the card and has its own filter.

### Code structure

The user asked for abstract classes. The core (storage, history, read state, API, UI) sees only
projects, stages and states.

- `Source`: finds the user's contributions and fetches their mail.
  - `discover(addresses, since)` returns the threads the user started.
  - `fetch(revision)` returns the thread's mails.
  - v1 has `LoreSource`, which uses b4 and lore search. A `GitHubPRSource` comes later.
- `Project`: name, how to recognise its patches, which stages it has, its `Source`, how
  "accepted" shows in mail (default: a reply line starting with "Applied"), and an optional
  `Trail`.
- `Trail`: follows accepted commits past the list and fills in the applied, released and
  backports stages.
  - v1 has `KernelTrail` (section 6).
  - v1 also has `GitTrail` for small mail-based projects (agreed with the user). It is configured
    with the project's upstream repo URL, branch and release-tag pattern.
    - It fetches a bare clone into `git/<project>.git`.
    - **Applied** means a commit on the branch with the patch's subject and author, dated after the
      patch was posted. This is what catches maintainers who commit without replying "Applied".
    - **Released** means the first matching tag that contains that commit, found by binary search.
    - v1 projects: erofs-utils and liburing. The builder finds their current upstream URLs.
    - GRUB has moved to GitLab merge requests. Its mail thread is history, and a GitLab source
      comes with the merge-request work.
  - `QemuTrail` is stage 2 and builds on `GitTrail`: master, then the `stable-X.Y` branches with
    QEMU's rules.
  - Projects without a trail stop at accepted.
- **"Mark applied" by hand** (CLI `ptl mark-applied NAME [COMMIT]` and a page button) is the
  fallback for any project when nothing detects the apply.
- **`ptl close NAME rejected|dropped|moved [--note TEXT]`.** For example, the GRUB thread closes as
  "moved: converted to a GitLab MR".

## 6. The kernel trail (port of stable-watch)

Keep all of stable-watch's behaviour and its lessons:

- **Branches:** the maintained stable and longterm branches, from kernel.org's `releases.json`.
- **Fetching:**
  - Mainline `master` plus the release tags, the stable branches plus their tags, and the
    maintainer trees, all into one bare repo under `refs/patchtrail/`.
  - After every fetch, `git commit-graph write --reachable --split`.
- **stable-queue:** a depth-1 sparse clone. Each `queue-X.Y/series` gives the order the patches
  apply in.
- **Per branch:**
  - Does the branch have the bug? That is, does it have the `Fixes:` commit, or a backport of it
    found through "commit X upstream"? With no `Fixes:` line, every branch counts as affected.
  - Does the branch have the fix, and from which release? Is it queued?
  - Does the fix apply? Test it with `git merge-tree --write-tree` on the branch head plus the
    queued patches that touch the same files, applied to a temporary index.
  - On conflict: blame the fix's hunks at `FIX^`, keep only what the branch lacks, and report
    whether each of those commits is marked for stable.
- **First release containing a commit:** a binary search over the release tags using
  `merge-base --is-ancestor`. Never `name-rev` or `describe --contains`.
- **FAILED mails:** search lore's stable list. HTTP 404 means no results.
- **The hint** "not tagged for stable: ask stable@vger.kernel.org".
- **`backport`:** creates a worktree on `linux-SERIES.y`, `git am`s the queued patches that touch
  the same files, and cherry-picks the fix with `-x`. Conflicts are left for the user to resolve.

What's new over stable-watch:

- **Accepted is detected automatically.** The commit comes from the "Applied … commit:" lines of the
  maintainer's reply: b4's thank-you format, one line per patch of the series. If no reply names a
  commit (some maintainers apply without replying), search linux-next and mainline for a commit with
  the patch's subject and author, dated after it was posted.
- **The maintainer's tree is found automatically:**
  - First, linux-next `master`, fetched each run with no tags; it holds most maintainers' trees.
  - Then the `T:` git trees that mainline's MAINTAINERS lists for the touched files, all branches.
    MAINTAINERS comes from mainline, so it is not user-supplied.
  - A manual tree URL and branch can still be set, from the CLI only. The page can never set one
    (anti-goal).
- **Series** *(builder-check call)*:
  - Each accepted commit of a series has its own stage, listed in the Overview tab.
  - The card's stage is the *least* advanced of them, with a note such as "1 of 2 in mainline".
  - A commit that disappears from the maintainer tree and linux-next before it reaches mainline is
    flagged as "dropped from <tree>?".
  - Cards can move backwards. History records the move.
- **Which fixes get the stable trail** *(builder-check call)*: accepted kernel commits with
  `Cc: stable` or a `Fixes:` line. These are the ones stable picks up on its own.
  - A commit with neither stops at Released, with the hint "not tagged for stable". `ptl follow
    --stable NAME` forces the trail.
  - With a `Cc: stable` but no `Fixes:` line, every branch counts as affected.
- **The stable check starts as soon as a commit is known**, before mainline, as stable-watch does
  today.
- **Per-branch states** that flag a patch: not affected · applies · applies after queued patches ·
  conflict · backport sent · queued · released (tag) · FAILED mail · won't backport. The details
  (which queued patches, the prerequisite list) are shown but don't flag.
- **The backports stage is finished** when every branch is released, not affected, or marked "won't
  backport". A branch that reaches end of life drops out of the table.
  - "Won't backport" is a per-branch action, in the CLI (`ptl skip NAME SERIES`) and on the page.
    It covers a conflict the user decides not to backport by hand.
  - *(builder-check call)*
- **The user's own stable backports** *(builder-check call)* attach to the original patch's branch
  row. They are never new revisions.
  - Discovery also searches the stable list for the user's mail, replies included.
  - A mail counts as a backport when its body has "commit <sha> upstream" or "[ Upstream commit
    <sha> ]" for a tracked commit, or its subject has a `[PATCH X.Y.y]` or `[PATCH X.Y]` prefix
    over a tracked patch's subject.
  - The branch then reads "backport sent", then queued and released as usual.
  - The backport's thread shows in the Thread tab, grouped under its branch. Replies to it flag the
    patch.

## 7. History, diffs and read state

- **Snapshots.** Each run computes a normalised state document per patch: stage, standing,
  trailers, mail IDs, mainline release, per-branch state and details, and FAILED mails. A new
  snapshot is stored only when it differs from the previous one. Snapshots are kept forever; it is
  all small text.
- **History** (the History tab, `ptl history NAME`) is the list of differences between consecutive
  snapshots, newest first, shown as old → new.
- **Read state** is per patch: the snapshot the user last marked read is the reference point.
  - *Unread* means the flagging fields of the newest snapshot differ from the reference, or the
    manual flag is set.
  - The flagging fields are: stage, standing, the set of mails, trailers, mainline release,
    per-branch state and FAILED mails. Changes in detail only are not.
- **"Since you read it on D"** is the diff between the reference snapshot and the newest. If a value
  changed several times in between, the summary shows reference → newest, and the steps in
  between expand.
- **Mark read** sets the reference to the newest snapshot and clears the flag.
- **Mark unread** restores the previous reference, if there is one, and sets the manual flag. So
  the patch is flagged next time even when nothing changed.
- **Mail** that arrived after the reference snapshot is "new" in the Thread tab.
- **The CLI follows the same rule.** `ptl status` never marks anything read. `ptl read NAME…` does.

## 8. Discovery and import

- **The user's addresses** come from `$PATCHTRAIL_FROM`, then `addresses` in config.toml, then
  `git config sendemail.from` and `user.email`.
- **Each run searches lore** (`/all/`, so every list) for `f:<addr> AND s:PATCH`, limited by date
  to the time since the last run.
  - Lore refuses requests without a User-Agent. A search with no results answers 404.
  - First-time import pages through all results.
  - A thread whose root is a reply is skipped.
- **A new series** becomes a new, unread patch.
- **A later version of a known series** becomes a new revision of that patch. Match it the way b4
  does: the same author and the subject with its `[PATCH vN m/n]` prefix stripped, plus the
  `change-id` trailer when there is one. The match details are the builder's call.
- **Hidden patches** stay hidden and are never re-added by discovery. They are listed under the
  Hidden filter and by `ptl ls --hidden`.
- **`ptl import`**, run by `ptl setup` when the old files exist, reads the old files read-only:
  - Each line of `~/.config/lkml-watch/threads` becomes a patch. The names are kept, and revisions
    of the same series are merged.
  - Mail IDs in `~/.local/state/lkml-watch/NAME.seen` count as read. A patch with mail not in
    `.seen` comes in unread.
  - Each line of `~/.config/stable-watch/fixes` sets that patch's commit and maintainer tree.
  - Threads that the lore search finds on the first run and that weren't watched come in as read,
    so the first visit isn't a flood of old patches.

## 9. CLI (`patchtrail`, also installed as `ptl`)

Every command of both scripts has a counterpart. This is the parity checklist for switching over.

| Old | New |
|---|---|
| `lkml-watch [status] [NAME…]` | `ptl status [NAME…]`: unread patches and their diffs. `--fetch` fetches first. Nothing is marked read. |
| `lkml-watch ls` / `stable-watch ls` | `ptl ls [NAME…] [--hidden]`: offline overview of every patch, kernel branch states included. |
| `lkml-watch show NAME…` | `ptl show NAME…`: every mail of the thread. |
| `lkml-watch open [NAME]` | `ptl open [NAME]`: neomutt `-R` on a temporary mbox, using the bundled neomuttrc (the user's current one). |
| `lkml-watch trailers [NAME…]` | `ptl trailers [NAME…]` |
| `lkml-watch poll` / `watch` | `ptl poll` (fetch, print what changed); `ptl watch` (print changes as the service records them, until ^C) |
| `lkml-watch mine [--add] [ADDR…]` | `ptl mine [ADDR…]`: what lore has, including hidden and untracked threads. Discovery itself is automatic. |
| `lkml-watch add NAME MSGID\|URL` | `ptl add NAME MSGID\|URL`: for threads discovery can't find. `--follow` marks someone else's thread as following. |
| `lkml-watch rm` / `stable-watch rm` | `ptl hide NAME…` (and `unhide`); `ptl rm NAME…` deletes a patch and its history. |
| `stable-watch status` | part of `ptl status` and `ptl fetch` |
| `stable-watch check COMMIT…` | `ptl check COMMIT…`: one-off report, nothing stored |
| `stable-watch add NAME [COMMIT] [TREE BRANCH]` | `ptl follow NAME [COMMIT] [TREE-URL BRANCH]`: on an existing patch, a manual override of the automatic follow. With a new NAME and a COMMIT, it creates a "following" patch for that commit. |
| `stable-watch backport NAME\|COMMIT SERIES [DIR]` | `ptl backport NAME\|COMMIT SERIES [DIR]` |
| `-v` | `-v` (every prerequisite, not only the first eight) |

New commands:

- `ptl read NAME…|--all` and `ptl unread NAME…`
- `ptl history NAME`
- `ptl fetch`
- `ptl serve`
- `ptl setup`
- `ptl service install|uninstall|status|logs`
- `ptl import`
- `ptl rename OLD NEW`
- `ptl merge NAME OTHER` and `ptl split NAME REVISION` (revisions)
- `ptl close NAME rejected|dropped|moved [--note TEXT]`
- `ptl mark-applied NAME [COMMIT]`
- `ptl skip NAME SERIES` and `ptl unskip NAME SERIES`: a stable branch's "won't backport"

## 10. Service

- **`ptl serve` is one process**: an HTTP server plus a scheduler thread. Picked over a systemd
  timer plus a separate web unit; the user had no preference.
  - The scheduler starts each fetch as a child process (`ptl fetch`): every `interval` (3 hours),
    at startup when the last run is older than the interval (catch-up after downtime), and on
    "Fetch now".
  - A run is killed by PID after a timeout.
  - One fetch runs at a time, enforced by a lock file that CLI fetches respect too. A "fetch now"
    request while a run is going, from the page, the API or the CLI, starts nothing. The API answers
    409 with the running run's progress, and the CLI says a run is in progress.
  - A run records its phase, a step counter and log lines in the database, for example "fetching
    stable 3/9", "checking iowq-cpuset: 6.1.y" or "lore search". The page shows progress from
    there, which matters for the first run's multi-GB fetch.
- **Listening:** `listen` in config.toml, default `0.0.0.0:<port>`, so the page is reachable from
  the laptop. There is no login.
- **Cross-site protection:** state-changing requests must come from the page itself (Origin
  check). Another site open in the laptop's browser can't press the buttons.
- **`ptl service install`:**
  - Writes `~/.config/systemd/user/patchtrail.service` (`ExecStart=<absolute path> serve`,
    `Restart=on-failure`).
  - Runs `daemon-reload` and `enable --now`.
  - Runs `loginctl enable-linger $USER` so the service survives logout. If that needs privileges,
    it prints the sudo command.
- Logs go to the journal (`ptl service logs`).
- **The user's machine rules apply to the code too:** no `pkill`/`pgrep -f`, no `nohup`/`setsid`.
  Children are tracked by PID.

## 11. Storage

Everything lives under `~/.patchtrail/`, or `$PATCHTRAIL_HOME`, for example to put the clone on
another disk:

- `config.toml`: addresses, listen, interval, an optional seed path and per-patch overrides.
- `patchtrail.db`: SQLite in WAL mode, because the page and the fetch write at the same time. It
  holds patches, revisions, mails (raw), commits, snapshots, read state, runs and a schema version
  for migrations.
- `git/linux.git`: a bare repo with everything under `refs/patchtrail/` and a commit-graph.
- `git/stable-queue/`

## 12. Web page

**Stack:** React and TypeScript, built with Vite. The page talks to a JSON API served by `ptl serve`
(FastAPI and uvicorn are the plan; the builder may change them). The built bundle ships inside the
Python package, so running the service needs no Node.

**Layout.** Approved mockup: `docs/mockups/board-with-detail.html`. The rejected alternatives are in
`docs/mockups/dashboard-layout-v2.html`.

- **Top bar:**
  - Project filters, "Unread only", "Your turn" and "Hidden".
  - When the last fetch ran and when the next one will.
  - **A "Fetch now" button for a manual sync** (asked for by the user). Runs are long, so:
    - While any run is in progress, however it started, the button is disabled and replaced by
      the progress: phase, step N of M, and elapsed time. Every open browser tab sees the same
      state.
    - A second click can't start a second run, and the server refuses one anyway (section 10).
    - Clicking the progress opens the run's log lines.
    - A failed run shows its error in the top bar until the next run succeeds.
- **Board:** six columns (Submitted, Reviewed, Accepted, Applied, Released, Backports).
  - Each card sits in exactly one column: its furthest stage.
  - A card shows the project chip, the name, a badge counting unread changes, a one-line
    standing, "your turn" in red and, for kernel fixes, the stable-branch pills.
  - Unread cards have a blue left edge.
  - Finished cards fold into "+N older" at the bottom of their column 30 days after finishing.
    Finished means the card has reached the last stage its project declares, with every branch
    settled where the project has backports. *(builder-check call)*
  - Closed patches (rejected, dropped, moved) appear only under a filter.
- **Bottom panel**, for the clicked card. It has a draggable divider and closes with Esc or ×.
  - **Header:** chip, name, subject, Mark read/unread, Hide, and a lore link.
  - **Overview tab:**
    - the trail stepper, with dates;
    - the "Since you read it on D" box;
    - for kernel fixes, the stable table (branch, state, detail, conflict prerequisites);
    - a thread summary;
    - recent history.
  - **Thread tab:**
    - Mails nested by In-Reply-To. New mail is open and outlined; the rest is collapsed to one line.
      An "Expand all" button opens everything.
    - Plain text only. An HTML part is replaced by a one-line note.
    - Rendered as text nodes, never as HTML.
    - Colours follow the user's neomuttrc: diff headers, `---`/`+++`, `@@` hunks, `+`/`-` lines,
      three quote levels, review trailers, and Fixes/Cc/Link.
    - Long diffs fold into "… N more lines".
  - **History tab:** the snapshot diffs, newest first.
- **Deep links** (`/p/NAME`, `/p/NAME/thread`), so a patch can be bookmarked.
- **Actions the page can take:**
  - mark read and unread;
  - hide and unhide;
  - fetch now;
  - close;
  - mark applied;
  - mark a stable branch "won't backport";
  - add a thread by Message-ID or lore URL (it only ever fetches from lore).
- **CLI-only actions:** setting a maintainer tree URL, deleting, renaming, merging and splitting.

## 13. Packaging and install

- Python ≥ 3.12 package with `pyproject.toml`. Entry points `patchtrail` and `ptl`.
- b4 is a Python dependency and is called from the same environment, so the system b4 doesn't
  matter.
- **External requirement:** git ≥ 2.40 (for `merge-tree --write-tree --merge-base`). `ptl setup` checks it.
- **From a checkout:** `make install` runs `npm ci && npm run build` (Node 20 or newer; this machine
  has 22) and then `uv tool install --force .`. pipx works too. Commands land in `~/.local/bin`,
  which is on the user's fish PATH.
- **From a release package:** once the repo is hosted, CI builds the package with the bundle
  inside. Installing it needs no Node.
- **`ptl setup`:**
  - creates `~/.patchtrail/`;
  - writes config.toml with the addresses detected from git config;
  - checks the requirements;
  - seeds the Linux clone (section 14);
  - runs `ptl import` when the old files exist;
  - offers `ptl service install`.
- **On a new machine without a local Linux tree,** the first fetch downloads several GB. The page
  shows its progress.

## 14. Coexistence with the old scripts and switch-over

- **The old scripts keep working, unchanged.** patchtrail only ever reads their files.
- **Seeding on this machine:**
  - `git clone --bare ~/.local/state/stable-watch/linux.git ~/.patchtrail/git/linux.git`
    hardlinks the 4.6 GB of packs: under 2 minutes and no extra disk.
  - Then move the refs from `refs/stable-watch/*` to `refs/patchtrail/*` and write the
    commit-graph.
  - Do not `git fetch` from a local path: that copied 4.2 GB and walked for 25 minutes.
  - With `--seed <path>`, any local Linux repo works the same way.
- **Until switch-over,** both tools fetch kernel.org independently.
- **Switch-over:** when the service has run for a day and every row of the table in section 9
  works, the user decides. Deleting `~/bin/{lkml,stable}-watch`, their config, and
  `~/.local/state/stable-watch` (5.1 GB) is the user's call. patchtrail never deletes them.

## 15. Repository

```
pyproject.toml  Makefile  README.md  LICENSE?
src/patchtrail/
  cli.py  config.py  db.py  schema/  fetch.py  service.py  server.py
  snapshot.py          state documents, diffs, read state
  mail.py              mbox parsing, standing, trailers
  sources/lore.py
  projects/base.py  projects/generic.py  projects/kernel/  (projects/qemu/ in stage 2)
  data/neomuttrc
  web/dist/            built bundle (not committed; built by make / CI)
web/                   React app source (package.json, vite.config.ts, src/)
tests/                 pytest; mbox fixtures; small synthetic git repos for the kernel trail
docs/
```

- The scripts have no tests today. The kernel trail gets tests against small synthetic repos
  (mainline, stable branches, tags, a queue directory), so the logic can be checked without
  kernel.org.
- Commits use `git commit -s`. No hand-written Signed-off-by, and no session trailers.
- `.superpowers/` is gitignored.

## 16. Approaches considered

| Decision | Options | Picked, and why |
|---|---|---|
| Language | Python, keeping the scripts' logic · Go rewrite (single binary) | Python: 1,176 lines of working logic and the lessons in it. A rewrite would relearn them. |
| How the service runs | A: one `ptl serve` process (web plus scheduler, fetch as a child) · B: systemd timer for `ptl fetch` plus a separate web unit | A. The user had no preference. One unit, live progress, and it runs the same under tmux or in a container on a VPS. |
| Page | Server-rendered (Flask/Jinja) · React app plus JSON API · stdlib `http.server` | React: the user wants a richer UI. Node is only needed to build. |
| Storage | SQLite · flat files as today | SQLite: diffs against a reference point and concurrent writes from the page and the fetch need it. |
| Dashboard | Inbox · Board · List + detail | Board on top with the detail panel below (the user combined B and C). |
| Scope of trails | Kernel trail now, mail for all · every project's trail now | Kernel now, plus a light `GitTrail` (applied and released) for small mail-based projects; QEMU next; merge-request projects (GRUB on GitLab, GitHub) later. |
| Silent applies | Manual "mark applied" · fetch the project's repo and match subject and author | Both: the user agreed to `GitTrail`, with manual marking as the fallback. |
| Others' work | Only the user's own patches · also "following" threads and commits | Following too, as both old tools allowed (agreed with the user). |
| Mail in the page | Rendered locally · lore links only | Local: read state, standing next to the mail, offline. Lore links stay. |

## 17. Still open: the user's to decide

- Where the repo is hosted (GitHub? public or private?) and its license. Not needed until the first
  push.

## 18. Left to the builder

The database schema and migrations, the API shape, the port number, the React libraries and
styling, how progress reaches the page (polling or SSE), the details of revision matching and lore
paging, the exact list of flagging fields, the timeout values and the test layout.
