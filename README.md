# patchtrail

patchtrail follows the patches you send to mailing lists. It reads the
[lore](https://lore.kernel.org) archive to see where each patch stands:
- waiting for a reply
- reviewed
- applied
- your turn to answer

For a kernel fix it follows the commit on into linux-next and mainline, then into every
maintained stable and longterm branch. In each branch it reports whether the fix is released,
queued, applies cleanly, or conflicts.

It keeps history, so after a few days away you see exactly what changed since you last read
each patch.

The commands are `patchtrail` and its short form `ptl`. This version is the command line. A
background service with a web page is coming next.

## Requirements

- Linux with git 2.40 or newer.
- [uv](https://docs.astral.sh/uv/). It installs Python 3.12 itself if the system has none.
- A few GB of disk for the Linux clone that kernel tracking uses.
- neomutt, optional, for `ptl open`.

## Install

    curl -LsSf https://astral.sh/uv/install.sh | sh        # if you have no uv yet
    uv tool install git+https://github.com/rucoder/patchtrail

`patchtrail` and `ptl` land in `~/.local/bin`. If your shell does not find them, run
`uv tool update-shell` and open a new shell. To upgrade later:

    uv tool upgrade patchtrail

From a checkout, `make install` does the same (`uv tool install --force .`).

## First run

    ptl setup --seed ~/src/linux     # or: ptl setup --no-seed
    ptl fetch
    ptl status

`ptl setup`:
1. Checks git.
2. Creates `~/.patchtrail/` with a starter `config.toml`.
3. Prepares the Linux clone. Run it again any time: it keeps your config.

`--seed PATH` points at any local Linux clone, bare or not. patchtrail clones from it with
hardlinks, so on the same filesystem it costs no extra disk. The first fetch then takes minutes
instead of downloading several GB. The seed itself is never changed.

Before the first fetch, check that `addresses` in `~/.patchtrail/config.toml` lists the
addresses you send patches from (see [Configuration](#configuration)).

The first `ptl fetch` finds every patch you ever sent from those addresses. It counts them as
read, so `ptl status` starts empty and from then on shows only what changes.

## How it works

Each fetch does four things:
1. Searches lore for mail from your addresses.
2. Downloads the threads of your patches.
3. Updates the git trees it follows.
4. Records a new snapshot for every patch whose state changed.

**Patches.** A patch is one change across all its versions. v2 and v3 of a series join the patch
of v1. A patch gets a short name made from its subject, like `foo-fix-a-leak-in-foo-open`; use
`ptl rename` to pick your own. You refer to patches by this name in every command.

**Projects.** The lists a patch went to decide its project:

| Project | Recognized by | Followed in git |
|---|---|---|
| kernel | kernel lists, such as `@vger.kernel.org` and `@lists.infradead.org` | the maintainer's tree, linux-next, mainline, stable |
| qemu | `qemu-devel@nongnu.org` | no |
| grub | `grub-devel@gnu.org` | no |
| erofs-utils | its list, and `erofs-utils` in the subject | yes |
| liburing | `io-uring@vger.kernel.org`, and `[PATCH liburing` in the subject | yes |
| anything else | named after its list | no |

**Stages.** Every patch moves through the same stages, and a project skips the ones it cannot
see:

    submitted → reviewed → accepted → applied → released → backports

- Mail-only projects stop at `accepted`. When such a project takes your patch, run
  `ptl mark-applied`.
- Projects followed in git reach `released`.
- The kernel goes on to `backports`.

**Standing.** Alongside the stage, a patch shows whose move it is, for example:
- `waiting for a reply since 2026-11-11`
- `Reviewed-by Jane Doe; waiting for the maintainer`
- `John Roe replied 2026-11-14: your turn`
- `APPLIED by A. Maintainer, 2026-11-18`

**Kernel fixes.** For each commit, patchtrail shows:
- its `Fixes:` and `Cc: stable` tags;
- where it is: the maintainer's tree, linux-next, or the mainline release;
- for each stable branch, one of:
  - `has it: v6.12.58`
  - `has it, not released yet`
  - queued in stable-queue
  - `applies cleanly`, possibly after queued patches to the same files
  - `CONFLICT`, with the commits the conflicting lines come from
  - `not affected`: the branch doesn't have the bug's commit
  - `won't backport`, after `ptl skip`

**Read and unread.** `ptl status` lists every patch that changed since you last marked it read,
with the change. Nothing is marked read until you say so:
- `ptl read` marks a patch read.
- `ptl unread` flags it again for later.
- `ptl history` shows every recorded change.

## Everyday use

    ptl status --fetch        # fetch, then show what changed (plain `ptl` shows status)
    ptl show NAME             # read the thread
    ptl open NAME             # or read it in neomutt
    ptl read NAME             # done with it; ptl read --all for everything

Example:

    $ ptl status
    foo-fix-a-leak-in-foo-open  [PATCH v2] foo: fix a leak in foo_open()
                                kernel · applied · APPLIED by A. Maintainer, 2026-11-18 (6 messages)
                                https://lore.kernel.org/all/20261110120000.1234-1-you@example.org/
        since you read it on 2026-11-12:
          commit 0123456789ab: – → released v6.19-rc1

    $ ptl ls foo-fix-a-leak-in-foo-open
    ...
        Fixes: 89abcdef0123 (v6.12-rc1)   Cc: stable
        mainline: v6.19-rc1
        6.18.y  has it, not released yet
        6.12.y  applies cleanly
        6.6.y   CONFLICT in drivers/foo/foo.c: needs a backport by hand
        6.1.y   not affected: no 89abcdef0123

## Commands

Run `ptl COMMAND -h` for the exact options of any command. `NAME` is a patch's short name.

**Looking**

| Command | What it does |
|---|---|
| `ptl status [NAME...] [--fetch]` | Patches that changed since you read them, with the changes. `--fetch` fetches first. Plain `ptl` runs this. |
| `ptl ls [NAME...] [--hidden] [--closed] [-v]` | Every patch and where it stands, without fetching. Includes each kernel branch. `-v` lists every prerequisite of a conflict, not only the first eight. |
| `ptl show NAME...` | Every mail of a patch. |
| `ptl open [NAME]` | The patch's mails in neomutt, read-only. Without NAME, it opens the newest patch. |
| `ptl trailers [NAME...]` | Review tags received: Reviewed-by, Acked-by, Tested-by. |
| `ptl history NAME` | What changed at each fetch. |
| `ptl mine [ADDR...]` | Your patch threads on lore, including ones not tracked or hidden. |

**Read state**

| Command | What it does |
|---|---|
| `ptl read NAME...` / `ptl read --all` | Mark read. `--all` skips hidden patches. |
| `ptl unread NAME...` | Flag again, so it shows in `status`. |

**Fetching**

| Command | What it does |
|---|---|
| `ptl fetch [NAME...]` | Fetch lore and the git trees. With names, it fetches only those patches and skips the search for new ones. |
| `ptl poll [NAME...]` | Fetch, then print what this fetch changed. |
| `ptl watch` | Print new changes every 30 seconds, as other fetches record them. It doesn't fetch itself. |

Only one fetch runs at a time. A second one says so and exits.

**Tracking and organizing**

| Command | What it does |
|---|---|
| `ptl add NAME MSGID\|URL [--follow] [--link URL]... [--note TEXT] [--json]` | Track a thread by its Message-ID or lore URL. Use it for a thread discovery cannot find, such as one sent from another address. `--follow` marks someone else's thread you want to watch. |
| `ptl follow NAME COMMIT [--stable]` | Follow someone else's kernel commit through mainline and stable. |
| `ptl follow NAME [COMMIT] [TREE-URL BRANCH] [--stable]` | On a tracked patch: set its commit, its maintainer tree, or both by hand. `--stable` tracks stable even without `Cc: stable`. |
| `ptl link NAME URL...` / `ptl unlink NAME URL...` | Attach or remove PR and ticket links. |
| `ptl note NAME TEXT` | Set a one-line note; `""` clears it. |
| `ptl rename OLD NEW` | Rename a patch. |
| `ptl merge NAME OTHER` | Move OTHER's versions into NAME, when one change was tracked as two patches. |
| `ptl split NAME VERSION` | Move one version out into its own patch, `NAME-vN`. |
| `ptl close NAME rejected\|dropped\|moved [--note TEXT]` | Close a patch that won't be merged. For example, `moved --note "now a GitLab MR"`. |
| `ptl mark-applied NAME [COMMIT]` | The project took it, for projects patchtrail does not follow in git. |
| `ptl hide NAME...` / `ptl unhide NAME...` | Keep a patch out of `ls` and `status`. `ls --hidden` shows hidden patches. |
| `ptl rm NAME...` | Delete a patch and its history. Discovery won't add it again. |

**Kernel stable**

| Command | What it does |
|---|---|
| `ptl check [-v] COMMIT...` | Where any commit stands in each stable branch. Nothing is stored. |
| `ptl skip NAME SERIES` / `ptl unskip NAME SERIES` | Don't backport to a stable series, for example `6.1`. |
| `ptl backport NAME\|COMMIT SERIES [DIR]` | A worktree to backport a fix by hand. See below. |

`ptl backport` makes a worktree on `linux-SERIES.y` with the branch `backport/NAME-SERIES`. It
applies stable's queued patches that touch the same files, then cherry-picks the fix. A conflict
is left in the worktree for you to resolve.

## Configuration

`~/.patchtrail/config.toml`, written by `ptl setup`:

```toml
# Your own mail addresses: patches from them are "mine".
addresses = ["you@example.org", "you@work.example.com"]

# A local Linux clone to seed ~/.patchtrail/git/linux.git from (hardlinks).
# seed = "~/src/linux"

# For the background service (coming): where its web page listens, and hours between fetches.
listen = "0.0.0.0:8470"
interval_hours = 3

# Other kernel remotes, if you don't want kernel.org's. Each key is optional.
# [kernel]
# mainline = "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git"
# stable   = "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git"
# queue    = "https://git.kernel.org/pub/scm/linux/kernel/git/stable/stable-queue.git"
# next     = "https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git"
# releases = "https://www.kernel.org/releases.json"

# Another repository or branch for a project followed in git (erofs-utils, liburing).
# [projects.liburing]
# repo   = "https://github.com/axboe/liburing.git"
# branch = "master"
# tags   = "liburing-*"
```

patchtrail takes your addresses from the first of these that is set:
1. `$PATCHTRAIL_FROM` (space-separated)
2. `addresses` in `config.toml`
3. git's `sendemail.from` and `user.email`

Set `$PATCHTRAIL_HOME` to keep everything somewhere other than `~/.patchtrail`, for example on a
bigger disk.

## Fetching on a schedule

Until the service arrives, cron fetches every three hours, and keeps doing so after you log
out:

    crontab -e
    0 */3 * * * $HOME/.local/bin/ptl fetch >> $HOME/.patchtrail/fetch.log 2>&1

`ptl status` then shows what those fetches found, and `ptl watch` prints it live.

## Registering patches from scripts and AI agents

After `git send-email` or `b4 send`, register the patch right away. This attaches PR or ticket
links, and you don't wait for the next fetch to find it:

    ptl add <short-name> <Message-ID> [--link URL]... [--note TEXT] --json

It is safe to repeat. The contract is in [docs/agents.md](docs/agents.md).

A Claude Code skill that does this after every send is in
`contrib/claude-skill/patchtrail-register/`. To enable it:

    cp -r contrib/claude-skill/patchtrail-register ~/.claude/skills/

## Where files live

Under `~/.patchtrail/` (or `$PATCHTRAIL_HOME`):

- `config.toml`: your settings.
- `patchtrail.db`: SQLite, with patches, mails, snapshots, read state and fetch runs.
- `git/linux.git`: a bare clone; everything patchtrail fetches is under `refs/patchtrail/`.
- `git/stable-queue/`, plus `git/<project>.git` for other projects followed in git.

git never repacks these repositories by itself (`gc.auto=0`). Packs hardlinked from a seed carry
`.keep` files, so they stay shared with the seed. Fetches add packs over time. To merge them,
run this while no fetch is running:

    git -C ~/.patchtrail/git/linux.git repack -a -d -l

It leaves the seed's packs alone.

To move patchtrail to another machine, copy `~/.patchtrail/` with `rsync -aH` while no fetch is
running.

## Development

    make test        # uv run pytest -q

The tests never touch the network or your `~/.patchtrail`.

## License

Apache-2.0, see [LICENSE](LICENSE).
