# msmail

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)

A small, scriptable command-line mail client for Outlook.com and Microsoft 365.
It talks to Microsoft Graph directly, with no Exchange server, no IMAP bridge
and no background daemon.

```console
$ msmail list
  # UASE Date             From               Subject
  1 **-- 2026-07-29 09:14 Alice Weber        Rechnung 2026-0871 im Anhang
  2 *-** 2026-07-29 08:02 Bob Neumann        Re: Vertragsentwurf
  3 ---- 2026-07-28 22:41 CI Pipeline        Build #2914 passed
  4 -**- 2026-07-28 17:30 Carol Fischer      Protokoll Jour Fixe
```

The four status flags are **U**nread, **A**ttachment, S/MIME **s**igned, S/MIME
**e**ncrypted. Message 2 is unread, signed and encrypted; message 4 has been
read, carries a file and is signed.

```console
$ msmail read 1
From: Alice Weber <alice@example.com>
To: you@example.com
Cc: buchhaltung@example.com
Date: 2026-07-29T09:14:00Z
Subject: Rechnung 2026-0871 im Anhang
Attachments: 1
  - rechnung-2026-0871.pdf (fileAttachment, 84213 bytes)

Hallo,

anbei die Rechnung fuer Juli.

Viele Gruesse
Alice
```

HTML mail is rendered to readable text, and Outlook Safelinks are unwrapped back
to the original URLs.

## Why

- **Draft-first.** Composing creates a draft; sending it is a separate, explicit
  command. Nothing leaves your mailbox because a keystroke went astray.
- **Scriptable.** Almost every command takes `--json` and works on stable Graph
  message IDs, so it composes with `jq` and cron.
- **S/MIME that works.** Sign, encrypt, decrypt and verify through OpenSSL,
  including reading encrypted attachments.
- **Nothing to host.** One `pipx install`, a device-code login, done.

## Install

```sh
pipx install git+https://github.com/mawirth/msmail.git
msmail --help
```

You need Python 3.9 or newer, `git` on your `PATH` (pipx clones the repository)
and, for S/MIME, `openssl`.

Pin a released version, upgrade, or remove it again:

```sh
pipx install git+https://github.com/mawirth/msmail.git@v0.1.0
pipx upgrade msmail
pipx uninstall msmail
```

From a checkout, for development:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m msmail --help
```

## Quickstart

```sh
msmail auth --login you@example.com   # device-code login, opens no browser
msmail doctor                         # verify the installation
msmail list                           # newest inbox messages
msmail read 1                         # read message number 1
```

`auth --login` prints a short code and a URL. Open the URL on any device, enter
the code and approve the sign-in. The token is cached locally afterwards, so
this is a one-time step.

Write a mail, look at it, then send it:

```sh
msmail draft create \
  --to alice@example.com \
  --subject "Hello" \
  --body "Hello from msmail."

msmail list --folder drafts
msmail read 1
msmail draft send 1
```

## How It Works

**Drafts are the unit of work.** `draft create`, `reply` and `forward` all
produce a draft and stop there. `draft send` is what actually sends. For
unattended jobs where that round trip is pointless, `send` creates and sends in
one step, but it requires `--yes` to skip its confirmation.

**Numbers refer to the last listing.** After `msmail list` or `msmail search`,
`1` means the first result. The mapping is cached per account and is replaced by
the next `list`, `search` or `list --more` -- including when you page forward,
where the numbers start again at 1. They describe what is on screen and nothing
else. `draft send`, `mark`, `move` and `delete` also take ranges: `1-4` or
`15-20,1-5,7,10-12`.

Numbers are meant for typing by hand. **Scripts should use `--id`**, which takes
the Graph message ID and never depends on cached state:

```sh
id=$(msmail search "invoice" --json | jq -r '.[0].id')
msmail read --id "$id" --json
```

**Local state** lives outside the checkout, restricted to your user account
(`0700` for directories, `0600` for files, including the token cache):

```text
~/.local/share/msmail/
  auth-state.json
  accounts/<email>/
    msal-token-cache.json
    profile.json
    last-list.json          # the number -> message ID mapping
    signature.txt
    signature.html
    smime/
      own-cert.pem
      own-key.pem
      ca-bundle.pem
      trusted-ca.pem        # optional, extra anchors for incoming signatures
      recipients/           # recipient certificates for encryption
```

Never commit these files, and do not copy the token cache between machines or
operating-system users. On Windows the files rely on your inherited ACLs.

## Reading Mail

```sh
msmail list                                   # focused inbox
msmail list --other                           # other inbox
msmail list --all                             # both
msmail list --folder sent                     # inbox, drafts, sent, deleted, junk
msmail list --from alice@example.com
msmail list --after 2026-06-01 --before 2026-07-01
msmail list --fetch 50                        # a number, 'auto' or 'all'
msmail list --json
```

`--fetch` says how many messages to bring back. Left out, it is `auto`: as many
as fit the terminal, or 25 when the output is piped. A number means that many,
fetched across as many Graph requests as it takes. `all` empties the query.

To page forward, use `--more`:

```console
$ msmail list --fetch 2
  # UASE Date             From               Subject
  1 **-- 2026-07-29 09:14 Alice Weber        Rechnung 2026-0871 im Anhang
  2 *-** 2026-07-29 08:02 Bob Neumann        Re: Vertragsentwurf
more: msmail list --more

$ msmail list --more
  # UASE Date             From               Subject
  1 ---- 2026-07-28 22:41 CI Pipeline        Build #2914 passed
  2 -**- 2026-07-28 17:30 Carol Fischer      Protokoll Jour Fixe
Messages 3-4 · more: msmail list --more
```

**The numbers restart at 1 on every page.** They always describe what is on
screen, never what scrolled past; the line below the table says which part of
the mailbox you are looking at. `--more` continues the previous query, so the
filters do not have to be repeated -- and for the same reason it cannot be
combined with them. A plain `msmail list` starts over.

If you need to work across pages, that is what `--json` and `--id` are for:

```sh
msmail list --fetch all --json | jq -r '.[] | select(.is_read == false) | .id'
```

By default `list` does not inspect attachments, which keeps it fast. `A` then
just means "Graph reports attachments". Use `--attachment-details` when you need
the S/MIME flags or want to tell real files from S/MIME metadata.

```sh
msmail read 1
msmail read --id AAMkAG...
msmail read 1 --html                # raw HTML instead of rendered text
msmail read 1 --attachment-details  # list attachment names
msmail read 1 --json
```

Search the mailbox, and list folders including nested ones:

```sh
msmail search "invoice"
msmail search "from:alice@example.com" --fetch 10 --json
msmail folders
```

## Writing Mail

Create a draft from options, from a file, or in your editor:

```sh
msmail draft create --to bob@example.com --subject "Status" --body "Done."
msmail draft create --to bob@example.com --subject "Status" --body-file body.txt
msmail draft create --to bob@example.com --subject "Status" --attach report.pdf
msmail draft create --file mail.txt
msmail draft create --edit
```

`--edit` and the no-argument form open `$EDITOR` (default `nvim`) with a compose
file. The same format works with `--file`:

```text
To: bob@example.com
Cc:
Bcc:
Subject: Status
Attach: /path/to/report.pdf
Sign: no
Encrypt: no

---
Message body starts here.
```

Edit, send or discard an existing draft:

```sh
msmail draft edit 1
msmail draft send 1
msmail draft send 1-3
msmail draft send --id AAMkAG... --yes
msmail draft delete 1
```

`draft edit` opens an HTML draft as raw HTML and saves it as HTML, so no markup
is lost; text drafts stay text. `draft send` and `draft delete` ask for
confirmation unless you pass `--yes`.

Reply and forward create drafts too:

```sh
msmail reply 1 --body "Thanks."
msmail reply 1 --all --body-file reply.txt
msmail forward 1 --to bob@example.com --body "FYI"
```

Per-account signatures are read from `signature.txt` and `signature.html` in the
account directory; HTML drafts fall back to a converted text signature. Suppress
it per message with `--no-signature`.

## Attachments

```sh
msmail draft create --to bob@example.com --subject "Report" -a a.pdf -a b.xlsx
msmail save-attachments 1 --to ~/Downloads
msmail save-attachments --id AAMkAG... --to ~/Downloads --inline
msmail save-attachments 1 --decrypt --verify-smime --to ~/Downloads
```

Files above the simple Graph limit are uploaded through upload sessions, up to
150 MB. For encrypted mail, attachments are embedded in the encrypted MIME
message instead.

## Managing Messages

```sh
msmail mark 1 --read
msmail mark 1-5,8 --unread
msmail move 1 --folder junk
msmail move 15-20,1-5,7 --folder deleted
msmail move --id AAMkAG... --folder-id AQMk...
msmail delete 1
msmail delete 1-4 --yes
```

Folder aliases are `inbox`, `drafts`, `sent`, `deleted` and `junk`; use
`--folder-id` with an ID from `msmail folders` for anything else. `move` and
`delete` print every affected message with its number and subject and ask for
confirmation; `mark` applies directly.

## S/MIME

Configure your certificate, private key and CA bundle once:

```sh
msmail smime setup \
  --cert own-cert.pem \
  --key own-key.pem \
  --ca-bundle ca-bundle.pem

msmail smime status
msmail smime test-sign          # local signing smoke test, sends nothing
```

To encrypt to somebody, import their certificate first:

```sh
msmail smime import-recipient --cert alice.pem --email alice@example.com
```

Then sign, encrypt, or both:

```sh
msmail draft create --to alice@example.com --subject "Signed" --body "Hi" --sign
msmail draft create --to alice@example.com --subject "Secret" --body "Hi" --encrypt
msmail draft create --to alice@example.com --subject "Both" --body "Hi" --sign --encrypt
msmail reply 1 --body "Thanks." --sign --encrypt
```

Read incoming signed or encrypted mail:

```sh
msmail read 1 --verify-smime
msmail read 1 --decrypt --verify-smime
msmail read 1 --decrypt --verify-smime --json   # includes signer certificate details
```

Verifying a signature needs trust anchors only, never your private key, so
`--verify-smime` works without `smime setup`. Trusted are, combined: the
operating system's CA store, your own `ca-bundle.pem`, and an optional
`trusted-ca.pem` for anchors the system does not know, such as an internal
company CA. Signing, encrypting and decrypting do need your own key.

More detail: [docs/SMIME.md](docs/SMIME.md).

## Automation

`send` never opens an editor and, with `--yes`, never prompts:

```sh
msmail send \
  --to admin@example.com \
  --subject "Backup failed on site-b-01" \
  --body-file /path/to/message.txt \
  --account sender@example.com \
  --no-signature \
  --yes \
  --json
```

If Graph creates the draft but sending fails, the error carries the retained
draft ID so you can inspect it. Compose files, Cc/Bcc, repeated `--attach`, HTML
and S/MIME all work here too.

For a headless machine, run `auth --login` once as the same operating-system
user that will later run the job; the browser step may happen on another
computer. Tokens are then renewed silently from the local cache.

## Troubleshooting

Start with `msmail doctor`, which checks everything the other commands rely on:

```console
$ msmail doctor
Python:         OK, 3.11.9
msmail:         OK, 0.1.0
Account:        OK, you@example.com
Token:          OK, you@example.com
Graph:          OK
OpenSSL:        OK, OpenSSL 3.5.5
S/MIME cert:    OK, ~/.local/share/msmail/accounts/you@example.com/smime/own-cert.pem
S/MIME key:     OK, ~/.local/share/msmail/accounts/you@example.com/smime/own-key.pem
CA bundle:      OK, ~/.local/share/msmail/accounts/you@example.com/smime/ca-bundle.pem
Recipients:     OK, 3 imported
Signature txt:  MISSING, ~/.local/share/msmail/accounts/you@example.com/signature.txt
Signature html: MISSING, ~/.local/share/msmail/accounts/you@example.com/signature.html
Temp dir:       OK, /tmp
```

Missing signatures are informational. `doctor` exits non-zero if anything else
is wrong, so it also works as a health check in scripts.

**The sign-in is refused, or approval never appears.** On Microsoft 365 the
requested permissions may need administrator approval for your tenant. msmail
asks for `Mail.ReadWrite`, `Mail.Send`, `User.Read`, `People.Read` and
`Contacts.Read`. If your organisation blocks the default client, register your
own application and point msmail at it:

```sh
MSMAIL_CLIENT_ID=<client-id> msmail auth --login you@example.com
```

**"No token cache entry"** means the cached token for that account is gone. Run
`msmail auth --login <email>` again.

**"No last list found"** means there is no cached numbering yet. Run `msmail
list` or `msmail search`, then use the numbers from it.

**A signature does not verify** although the mail looks fine. The issuing CA is
probably not in your system store; add it to `trusted-ca.pem` in the account's
`smime/` directory.

**The editor does not open.** Set `EDITOR`; msmail falls back to `nvim`.

Check which account is active, or switch away from it:

```sh
msmail auth --whoami
msmail auth --logout        # drops the token and the cached list
```

## Status

Version `0.1.0`, pre-release. The commands and JSON output described here work;
expect rough edges elsewhere.

Known limitations:

- S/MIME drafts created with `--sign` or `--encrypt` are complete MIME messages.
  They can be read, sent and deleted, but not edited with `draft edit`. Write
  and review the text first, then create the signed draft.
- S/MIME reply and forward do not yet quote the original message or carry its
  attachments over.
- Encrypted mail is uploaded as one MIME message, so very large encrypted
  payloads depend on what Graph accepts as a draft.
- With `--encrypt` and `Bcc`, every recipient key is part of the same encrypted
  message. A To recipient can see that further recipients exist. Send separately
  if that matters.
- `list --more` only pages forward. To get back to an earlier page, list again.
- `search` results cannot be paged: Graph orders them by relevance and may shift
  them between pages, so `--more` refuses to continue a search. Use `--fetch`
  with a larger number instead.

## Development

```sh
.venv/bin/python -m pytest
.venv/bin/python -m compileall -q src
```

```text
src/msmail/
  cli.py        # Typer entry point
  commands/     # one module per CLI command
  core/         # Graph, auth, mail, drafts, MIME and S/MIME logic
tests/
docs/
```

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) and
[docs/RELEASE.md](docs/RELEASE.md).

## Security

Private keys, certificates, token caches, decrypted mail and account state stay
outside the repository, under `~/.local/share/msmail`. Never commit them.
[docs/SECURITY.md](docs/SECURITY.md) has the details, including how S/MIME
cleartext is handled.

## License

MIT. See [LICENSE](LICENSE).

The project began as a portable Python successor to a PowerShell prototype
called `psmail`.
