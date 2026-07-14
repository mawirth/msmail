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
