# Security Notes

`msmail` handles mail, OAuth tokens, certificates and private keys. Treat a
checkout and any test machine with care.

## Never Commit

Do not commit:

- MSAL token caches.
- `~/.local/share/msmail` account state.
- Private keys.
- S/MIME certificates for private correspondents unless intentionally public.
- PKCS#12/PFX archives.
- Decrypted mail.
- `.eml` files from live mailboxes.
- Real compose files containing private content.

The `.gitignore` blocks common key and certificate extensions, but it is not a
substitute for reviewing the tree before publishing.

## Runtime State

Runtime state is outside the repository:

```text
~/.local/share/msmail/
```

On POSIX systems, `msmail` creates and repairs state directories with mode
`0700` and regular state files with mode `0600`. This includes the MSAL token
cache, profiles and list indexes. On Windows, the files rely on the current
user's inherited Windows ACLs.

Authenticate separately as the operating-system account that runs `msmail`.
Do not copy or share the MSAL token cache between hosts or service users.

Account S/MIME material is account-scoped:

```text
~/.local/share/msmail/accounts/<email>/smime/
```

Private-key files are created with restrictive permissions where `msmail`
copies them during `smime setup`.

## S/MIME Cleartext

Encrypted outgoing mail is encrypted locally before the Graph draft is created.
The cleartext should not be uploaded as a normal JSON draft.

Incoming encrypted mail is decrypted locally when using:

```sh
msmail read 1 --decrypt
msmail save-attachments 1 --decrypt
```

OpenSSL helper files are written to a private working directory below `/tmp`
(mode `0700`) and removed again once the result has been read, so decrypted
mail and outgoing cleartext are not left behind. The content still passes
through `/tmp`; on shared systems, or where `/tmp` is not adequately protected,
prefer a `TMPDIR` on local, user-owned storage.

`msmail smime test-sign --output-dir` and the other `--output-dir` options are
the exception: a directory you name yourself belongs to you and is kept for
inspection, including whatever cleartext it holds.

## Reporting Vulnerabilities

Until a public vulnerability-reporting address is chosen, do not file public
issues containing secrets, tokens, private keys or full private message
content. Use a private channel to the maintainer.

Before public release, add a concrete contact address here.
