# Registering patches (for scripts and AI agents)

After you send a patch with `git send-email` or `b4 send`, register it with patchtrail:

    ptl add <short-name> <Message-ID> [--link <PR or Jira URL>]... [--note TEXT] --json

- `<short-name>`: letters, digits, `.`, `_`, `-`; it is how you refer to the patch later.
- `<Message-ID>`: of the cover letter (or the single patch), with or without `<>`; a lore URL works too.
- `--link` (repeatable) attaches a PR or Jira URL. `--note` sets a one-line note. Both are optional.
- `--json` prints exactly one JSON object on stdout; errors go to stderr as `ptl: ...`, exit status 1.

It is safe to repeat. If the Message-ID is already registered, nothing is created: new links are
added, `--note` replaces the note, and the existing patch is reported under its first name.
`ptl add` fails (exit 1) only if the name belongs to a different patch.

`ptl add` fetches only the thread from lore, so it returns in seconds; where the patch stands in
git (maintainer tree, mainline, stable branches) is filled in by the next `ptl fetch`.

lore may need a few minutes to archive the mail. Until it has, the patch shows "not fetched yet"
in `ptl ls` (`stage` and `standing` are null in the JSON); a later `ptl fetch` picks it up. Run `ptl add` again
with more `--link` options whenever a PR or ticket appears.

Example:

    $ ptl add iowq-cpuset 20261112.abc@example.org --link https://github.com/lf-edge/eve/pull/5123 --json
    {"name": "iowq-cpuset", "msgid": "20261112.abc@example.org", "project": "unknown", "stage": null, "standing": null, "links": ["https://github.com/lf-edge/eve/pull/5123"], "note": null, "url": "https://lore.kernel.org/all/20261112.abc@example.org/"}

`stage` and `standing` are null until the first fetch has recorded a state; `project` becomes
`kernel` and so on once the mail is fetched.
