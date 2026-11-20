---
name: patchtrail-register
description: Use right after sending a patch or patch series upstream with `git send-email` or `b4 send`, to register it with patchtrail (`ptl add`) so it is tracked on lore, with optional PR or Jira links and a note.
---

# Register a sent patch with patchtrail

## Why

patchtrail (`ptl`) tracks the user's upstream patches. It follows:
- replies and reviews;
- whose turn it is;
- when a maintainer applies the patch;
- for kernel fixes, mainline and every stable branch.

Registering a patch right after sending it:
- gives it a short name the user will recognize, instead of one made from the subject;
- attaches the PR or Jira links it belongs to, so the user sees them next to its status;
- tracks it at once, even when it was sent from an address patchtrail doesn't search for.

## How

    ptl add <short-name> <Message-ID> [--link URL]... [--note TEXT] --json

- `<short-name>`: letters, digits, `.`, `_`, `-`. Pick something short that names the change,
  for example `iowq-cpuset`.
- `<Message-ID>`: of the cover letter (or of the single patch), with or without `<>`. A lore URL
  works too.
- `--link URL` (repeatable) attaches a PR or Jira URL. `--note TEXT` sets a one-line note. Both
  are optional. Leave them out when there is no PR or ticket.
- `--json` prints exactly one JSON object on stdout. Errors go to stderr as `ptl: ...` with exit
  status 1. It fails only on a malformed argument or a name that belongs to a different patch;
  for the latter, pick another name.

If `ptl` is not installed, tell the user and stop. Don't install it yourself.

## Finding the Message-ID

- `b4 send` prints it (the cover letter's or single patch's Message-ID) when it sends.
- `git send-email` prints `Message-Id:` lines for each mail it sends. Use the cover letter's,
  the first one, for a series that has a cover letter.
- Otherwise read the `Message-ID:` header of the first mail in the sent mbox or
  `git format-patch` output.

## Notes

- It is safe to repeat. If the Message-ID is already registered, nothing is created: new links are
  added, `--note` replaces the note, and the existing patch is reported under its first name.
  Run it again with the new `--link` when a PR or Jira ticket appears.
- lore may need a few minutes to archive the mail. Until then the JSON has `stage` and `standing`
  as null and `ptl ls` shows "not fetched yet". That is fine: the next `ptl fetch` picks it up.
- Tell the user the `name` from the JSON, so they know what to type in `ptl show <name>`.
