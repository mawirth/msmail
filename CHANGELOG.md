# Changelog

## 0.1.0 - Unreleased

- Add Microsoft Graph device-code authentication.
- Add account-scoped local state and active-account handling.
- Add message listing, reading, searching and recursive folder listing.
- Add draft-first create/edit/send/delete workflow.
- Add reply and forward draft creation.
- Add normal and large attachment upload handling.
- Add attachment saving, including decrypted S/MIME-container attachments.
- Add move, delete and mark read/unread commands.
- Add index range support for draft send, move, delete and mark commands.
- Add per-account text and HTML signatures.
- Add S/MIME setup, recipient certificate import, sign, encrypt, decrypt and
  verify support through OpenSSL.
- Add JSON output for scriptable workflows.
- Add an explicit, non-interactive `msmail send --yes --json` workflow for
  unattended scripts and services.
- Restrict POSIX runtime directories to `0700` and runtime files, including the
  MSAL token cache, to `0600`, repairing existing state automatically.
- Fix login leaving no usable token cache when Graph reports a different
  primary address than the one used to log in.
- Remove S/MIME working directories after use, so decrypted incoming mail and
  outgoing cleartext no longer accumulate below `/tmp`.
- Skip attachment detail lookups in `delete` and `move` previews, which
  downloaded every attachment body just to print sender and subject.
- Retry throttled Graph requests (HTTP 429, 503) with `Retry-After`
  backoff, and follow `@odata.nextLink` when listing mail folders.
- Keep HTML drafts in HTML when editing them; `draft edit` converted the body
  to text and saved the draft as a plain text message.
- Classify `smime.p7m` attachments by content type instead of by name, so an
  encrypted message is no longer also reported as signed.
- Verify incoming signatures against the system CA store plus an optional
  `trusted-ca.pem`, and stop requiring an own certificate and private key for
  verification alone.
- Sanitize recipient addresses used as certificate filenames.
- Remove the cached message list, which holds body previews, on `auth
  --logout`; signatures, profile and S/MIME material are kept.
- Harden the runtime state once per process instead of on every token load.
- Add `list --more` to page forward through a listing. Each page numbers its
  messages from 1 and prints which part of the mailbox is on screen.
- Replace `--limit` with `--fetch`, which accepts a number, `auto` or `all`. A
  number is now honoured across as many Graph requests as it takes instead of
  being silently truncated at 100, and the same rule applies to `list` and
  `search`.
- Escape double quotes in `search` terms, which previously ended the search
  expression early.
- Tolerate a `last-list.json` written by an older version instead of failing
  with a traceback.
