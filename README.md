# patchtrail

patchtrail follows the patches you send to mailing lists. It reads the lore archive to see
where each patch stands (waiting for a reply, reviewed, applied, your turn), and for kernel
fixes it follows the commit into mainline and every maintained stable and longterm branch:
released, queued, applies, or conflicts. It keeps history, so you see what changed since you
last marked a patch read.

The commands are `patchtrail` and its short form `ptl`. It replaces the personal scripts
`lkml-watch` and `stable-watch`.

Plan 2 (a background service and a web page) is coming next; this version is the command line.

## Install

From a checkout, with [uv](https://docs.astral.sh/uv/) and git >= 2.40:

    make install        # uv tool install --force .

`patchtrail` and `ptl` land in `~/.local/bin`. Then:

    ptl setup           # check git, write the config, seed the Linux clone, import old state
    ptl fetch           # the first run fetches mainline and stable
    ptl status

`ptl setup` options: `--seed PATH` seeds `~/.patchtrail/git/linux.git` from a local linux.git by
hardlinks (no copy, the seed is never modified); `--no-seed` skips seeding; `--import` or
`--no-import` forces or skips the import of the old scripts' state. Without flags it seeds from
`~/.local/state/stable-watch/linux.git` if that exists, and imports if
`~/.config/lkml-watch/threads` exists. Without a seed the first fetch downloads several GB; with
one it takes minutes. Running `ptl setup` again keeps your config.

## Commands

Old script commands and their `ptl` counterparts:

| Old | New |
|---|---|
| `lkml-watch [status] [NAME...]` | `ptl status [NAME...]`: unread patches and their diffs. `--fetch` fetches first. Nothing is marked read. |
| `lkml-watch ls` / `stable-watch ls` | `ptl ls [NAME...] [--hidden] [--closed]`: offline overview of every patch, kernel branch states included. |
| `lkml-watch show NAME...` | `ptl show NAME...`: every mail of the thread. |
| `lkml-watch open [NAME]` | `ptl open [NAME]`: neomutt `-R` on a temporary mbox, using the bundled neomuttrc. |
| `lkml-watch trailers [NAME...]` | `ptl trailers [NAME...]` |
| `lkml-watch poll` / `watch` | `ptl poll` (fetch, print what changed); `ptl watch` (print new changes every 30 s, does not fetch) |
| `lkml-watch mine [--add] [ADDR...]` | `ptl mine [ADDR...]`: what lore has, including hidden and untracked threads. Discovery itself is automatic. |
| `lkml-watch add NAME MSGID\|URL` | `ptl add NAME MSGID\|URL [--note TEXT] [--link URL]... [--json]`: for threads discovery can't find, and for scripts and AI agents. `--follow` marks someone else's thread as following. |
| `lkml-watch rm` / `stable-watch rm` | `ptl hide NAME...` (and `unhide`); `ptl rm NAME...` deletes a patch and its history. |
| `stable-watch status` | part of `ptl status` and `ptl fetch` |
| `stable-watch check COMMIT...` | `ptl check [-v] COMMIT...`: one-off report, nothing stored |
| `stable-watch add NAME [COMMIT] [TREE BRANCH]` | `ptl follow NAME [COMMIT] [TREE-URL BRANCH]`: a manual override of the automatic follow. With a new NAME and a COMMIT, it creates a "following" patch for that commit. `--stable` tracks stable without Cc: stable. |
| `stable-watch backport NAME\|COMMIT SERIES [DIR]` | `ptl backport NAME\|COMMIT SERIES [DIR]` |
| `-v` | `ptl ls -v`, `ptl check -v` (every prerequisite, not only the first eight) |

New commands:

- `ptl read NAME...|--all` and `ptl unread NAME...`
- `ptl history NAME`
- `ptl fetch [NAME...]`
- `ptl setup`
- `ptl import`: import the old scripts' state (also done by `ptl setup`)
- `ptl link NAME URL...`, `ptl unlink NAME URL...` and `ptl note NAME TEXT`
- `ptl rename OLD NEW`
- `ptl merge NAME OTHER` and `ptl split NAME VERSION` (revisions)
- `ptl close NAME rejected|dropped|moved [--note TEXT]`
- `ptl mark-applied NAME [COMMIT]`
- `ptl skip NAME SERIES` and `ptl unskip NAME SERIES`: a stable branch's "won't backport"

## Where files live

Everything is under `~/.patchtrail/`, or `$PATCHTRAIL_HOME` (for example to put the clone on
another disk):

- `config.toml`: your addresses, listen address, fetch interval, an optional seed path.
- `patchtrail.db`: SQLite; patches, mails, snapshots, read state, runs.
- `git/linux.git`: a bare clone with everything under `refs/patchtrail/`.
- `git/stable-queue/`

git never repacks these repositories on its own (`gc.auto=0`, `maintenance.auto=false`), and the
packs hardlinked from a seed carry `.keep` files, so they stay shared with the seed instead of
costing their size again. Fetches add packs over time; while no fetch runs,
`git -C ~/.patchtrail/git/linux.git repack -a -d -l` merges them and leaves the `.keep` packs
alone (the same goes for `git/stable-queue` and project repositories).

Your own mail addresses come from `$PATCHTRAIL_FROM`, then `addresses` in `config.toml`, then
git's `sendemail.from` and `user.email`.

## Coexistence with the old scripts

patchtrail never writes to `~/bin`, `~/.config/{lkml,stable}-watch` or
`~/.local/state/{lkml,stable}-watch`. The import only reads them, and seeding is a local
`git clone --mirror` from the old `linux.git`, which leaves it untouched. Both tools can run
side by side until you retire the scripts.

## Registering patches from scripts and AI agents

After `git send-email` or `b4 send`, an agent or script registers the patch with
`ptl add <short-name> <Message-ID> [--link URL]... [--note TEXT] --json`. It is safe to repeat.
The contract is in [docs/agents.md](docs/agents.md). A Claude Code skill that does this is in
`contrib/claude-skill/patchtrail-register/`; copy it to `~/.claude/skills/` to enable it:

    cp -r contrib/claude-skill/patchtrail-register ~/.claude/skills/

## License

Apache-2.0, see [LICENSE](LICENSE).
