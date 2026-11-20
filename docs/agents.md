# Registering patches (for scripts and AI agents)

After you send a patch with `git send-email` or `b4 send`, register it with patchtrail:

    ptl add <short-name> <Message-ID> [--link <PR or Jira URL>]... [--note TEXT] --json

- `<short-name>`: letters, digits, `.`, `_`, `-` (not `.` or `..` alone); it is how you refer to the patch later.
- `<Message-ID>`: of the cover letter (or the single patch), with or without `<>`; a lore URL works too.
- `--link` (repeatable) attaches a PR or Jira URL (`http://` or `https://`). `--note` sets a one-line note. Both are optional.
- `--json` prints exactly one JSON object on stdout; errors go to stderr as `ptl: ...`, exit status 1.

It is safe to repeat. If the Message-ID is already registered, nothing is created: new links are
added, `--note` replaces the note, and the existing patch is reported under its first name.
`ptl add` fails (exit 1) only if the name belongs to a different patch or an argument is
malformed: a name with other characters (or `.`, `..`), a Message-ID without `@`, a link that is
not an `http(s)://` URL.

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

## From another machine: `POST /api/patches`

If patchtrail runs as a service (`ptl serve`) on another machine, register the patch over HTTP
instead. The page's address is `http://<server>:8470`, or whatever `listen` says in the
service's config:

    curl -s -X POST http://<server>:8470/api/patches \
      -H 'Content-Type: application/json' \
      -d '{"name": "iowq-cpuset", "msgid": "20261112.abc@example.org",
           "links": ["https://github.com/lf-edge/eve/pull/5123"], "note": "needs a v2"}'

Body (JSON object):
- `name` and `msgid`: required strings, as for `ptl add`. `msgid` may also be a lore URL.
- `links`: optional list of `http(s)://` URLs. `note`: optional string.
- `follow`: optional boolean, for someone else's thread you want to watch.

The answer is the same object as `ptl add --json` prints:

| Status | Meaning |
|---|---|
| 201 | The patch was created. |
| 200 | The Message-ID was already registered: new links were added, `note` replaced the note, and the existing patch is reported under its first name. Safe to repeat. |
| 409 | The name belongs to a different patch. Pick another name. |
| 400 | Bad input: a malformed name, a Message-ID without `@` or one that reads as a URL (`://`), a link that is not `http(s)://`, a body that is not a JSON object, or a field of the wrong type. The answer is `{"error": "..."}`. |

Notes:
- The request must have `Content-Type: application/json`, or the answer is 415.
- It needs no `Origin` header. curl and scripts send none. A request that does carry one must
  match the `Host` it was sent to, or the answer is 403; only browsers on other sites hit that.
- Address the server by its IP address, its host name or full domain name, or `localhost`.
  Another name, such as a DNS alias, gets 403 `unknown Host NAME` until the user adds it to
  `hosts` in `config.toml`.
- The service starts a lore-only fetch for the new patch at once, so lore is usually read within
  seconds. If a fetch is already running, the patch waits for the next run, up to
  `interval_hours` later. Where the patch stands in git comes with the next scheduled fetch.
- The service has no login: use it only on a trusted network.
