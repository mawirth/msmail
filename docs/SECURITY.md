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

Verifying an incoming signature uses trust anchors only and never reads the
private key. Anchors are the system default CA store, the account's own
`ca-bundle.pem` and an optional `trusted-ca.pem`. Adding a CA to
`trusted-ca.pem` means trusting it for every incoming signature on that
account, so add only anchors you would also add to the system store.

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

Report security problems privately, through GitHub's private vulnerability
reporting: open the repository's **Security** tab and choose **Report a
vulnerability**. That creates a private advisory visible only to you and the
maintainer, so no address has to be published and nothing is disclosed while
the issue is still open.

Please do not open a normal issue for a security problem, and never put
secrets, tokens, private keys, certificates or full private message content
into any issue, pull request or advisory. A description of the problem and the
steps to reproduce it are enough; if a sample is genuinely required, redact it
first.

There is no service to attack here: `msmail` runs on your own machine against
your own mailbox. The interesting reports are therefore about the local
handling of credentials and cleartext -- token cache, private keys, decrypted
mail, temporary files -- or about a command doing something other than what it
says.

This is a pre-release project maintained by one person in their spare time.
Expect an acknowledgement rather than an immediate fix.
