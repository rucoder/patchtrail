---
name: patchtrail-register
description: Use right after sending a patch or patch series upstream with `git send-email` or `b4 send`, to register it with patchtrail (`ptl add`) so it is tracked on lore, with optional PR or Jira links and a note.
---

# Register a sent patch with patchtrail

After you send a patch with `git send-email` or `b4 send`, register it:

    ptl add <short-name> <Message-ID> [--link URL]... [--note TEXT] --json

- `<short-name>`: letters, digits, `.`, `_`, `-`. Pick something short that names the change,
  for example `iowq-cpuset`.
- `<Message-ID>`: of the cover letter (or of the single patch), with or without `<>`. A lore URL
  works too.
- `--link URL` (repeatable) attaches a PR or Jira URL. `--note TEXT` sets a one-line note. Both
  are optional.
- `--json` prints exactly one JSON object on stdout. Errors go to stderr as `ptl: ...` with exit
  status 1 (it only fails if the name already belongs to a different patch; pick another name).

## Finding the Message-ID

- `b4 send` prints it (the cover letter's or single patch's Message-ID) when it sends.
- `git send-email` prints `Message-Id:` lines for each mail it sends; use the cover letter's
  (the first one, for a series with a cover letter).
- Otherwise read the `Message-ID:` header of the first mail in the sent mbox or
  `git send-email --format-patch` output.

## Notes

- It is safe to repeat. If the Message-ID is already registered, nothing is created: new links are
  added, `--note` replaces the note, and the existing patch is reported under its first name.
  Run it again when a PR or Jira ticket appears, with the new `--link`.
- lore may need a few minutes to archive the mail. Until then the JSON has `stage` and `standing`
  as null and `ptl ls` shows "not fetched yet"; that is fine, a later `ptl fetch` picks it up.
- Report the `name` from the JSON to the user, so they know what to type in `ptl show <name>`.
