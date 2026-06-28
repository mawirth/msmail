# msmail

`msmail` is a small, scriptable command-line mail client for Outlook.com and
Microsoft 365 accounts. It talks to Microsoft Graph directly and keeps a
draft-first workflow: composing a message creates a draft, and sending that
draft is a separate explicit command.

The project started as a portable Python successor to a PowerShell prototype
(`psmail`). It is currently focused on practical terminal use, predictable JSON
output, attachments, and S/MIME.

## Status

Current version: `0.1.0` pre-release.

Implemented:

- Microsoft Graph device-code authentication.
- Account-scoped local state under `~/.local/share/msmail`.
- Inbox, drafts, sent, deleted and junk listing.
- Focused/Other inbox listing.
- Read mail as text, raw HTML, or JSON.
- Draft create, edit, send and delete.
- Reply and forward draft creation.
- Attachments, including upload sessions for larger normal attachments.
- Save normal attachments and encrypted S/MIME-container attachments.
- Move, delete, mark read/unread.
- Folder listing and move by Graph folder ID.
- Graph mail search.
- Text and HTML signatures.
- S/MIME setup, recipient certificates, sign, encrypt, sign+encrypt, decrypt
  and verify.

Notable limitations:

- `draft edit` refuses existing attachments and S/MIME drafts.
- S/MIME reply/forward creates a new MIME draft and does not yet quote the
  original message or include original attachments automatically.
- Encrypted outgoing messages are uploaded as one complete MIME message. Large
  encrypted MIME payloads depend on Graph accepting the resulting draft size.

## Installation

From a checkout:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

Run:

```sh
msmail --help
python -m msmail --help
```

Requirements:

- Python 3.9 or newer.
- OpenSSL in `PATH` for S/MIME.
- A Microsoft account or Microsoft 365 account with Graph mail access.

## Authentication

`msmail` uses MSAL device-code login:

```sh
msmail auth --login user@example.com
msmail auth --whoami
msmail auth --logout
```

The default public client ID is the Microsoft Graph command-line client used by
the prototype. You can override it with your own app registration:

```sh
MSMAIL_CLIENT_ID=<client-id> msmail auth --login user@example.com
```

Requested Graph scopes are:

- `Mail.ReadWrite`
- `Mail.Send`
- `User.Read`
- `People.Read`
- `Contacts.Read`

Local state is stored below:

```text
~/.local/share/msmail/
  auth-state.json
  accounts/<email>/
    msal-token-cache.json
    profile.json
    last-list.json
    signature.txt
    signature.html
    smime/
```

Do not commit files from this state directory.

## Basic Use

List mail:

```sh
msmail list
msmail list --other
msmail list --all
msmail list --folder sent
msmail list --from alice@example.com
msmail list --after 2026-06-01 --before 2026-07-01
msmail list --json
```

Read mail:

```sh
msmail read 1
msmail read --id AAMkAG...
msmail read 1 --html
msmail read 1 --json
```

Search:

```sh
msmail search "invoice"
msmail search "from:alice@example.com" --limit 10 --json
```

Manage stateful indices:

- Numeric references such as `1` refer to the most recent `list` or `search`
  result for the active account.
- `draft send`, `mark`, `move` and `delete` also accept ranges such as `1-4` or
  `15-20,1-5,7,10-12`.
- Scripts should prefer `--id AAMk...`.

## Range References

Range references are intended for manual mailbox cleanup after a fresh
`list`/`search`. They work for:

```sh
msmail draft send 1-3
msmail mark 1-5,8 --read
msmail move 15-20,1-5,7,10-12 --folder deleted
msmail delete 1-4 --yes
```

Before a range operation asks for confirmation, `msmail` prints every affected
message or draft with its original list index and subject. `--id` stays a
single-item option for scripts.

## Typical Workflows

Check new mail, read a message, save attachments and move it out of the inbox:

```sh
msmail list
msmail read 1
msmail save-attachments 1 --to ~/Downloads
msmail move 1 --folder deleted
```

Create a reviewed S/MIME draft and send it explicitly:

```sh
msmail draft create \
  --to alice@example.com \
  --subject "Status" \
  --body-file status.txt \
  --attach report.pdf \
  --sign \
  --encrypt

msmail list --folder drafts
msmail read 1 --decrypt --verify-smime
msmail draft send 1
```

For scripts, capture Graph IDs from JSON and operate on `--id`:

```sh
id=$(msmail search "invoice" --json | jq -r '.[0].id')
msmail read --id "$id" --json
msmail move --id "$id" --folder deleted --yes
```

## Draft-First Sending

Create a draft:

```sh
msmail draft create --to bob@example.com --subject "Status" --body "Done."
msmail draft create --to bob@example.com --subject "Status" --body-file body.txt
msmail draft create --to bob@example.com --subject "Status" --attach report.pdf
msmail draft create --file mail.txt
msmail draft create --edit
```

Compose file format:

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

Send or delete an existing draft:

```sh
msmail list --folder drafts
msmail draft send 1
msmail draft send 1-3
msmail draft send --id AAMkAG... --yes
msmail draft delete 1
```

`draft send` and `draft delete` ask for confirmation by default.

Reply and forward create drafts only:

```sh
msmail reply 1 --body "Thanks."
msmail reply 1 --all --body-file reply.txt
msmail forward 1 --to bob@example.com --body "FYI"
```

## Attachments

Save normal file attachments:

```sh
msmail save-attachments 1 --to ~/Downloads
msmail save-attachments --id AAMkAG... --to ~/Downloads --inline
```

Save attachments inside an encrypted S/MIME message:

```sh
msmail save-attachments 1 --decrypt --verify-smime --to ~/Downloads
```

For normal outgoing drafts, files larger than the simple Graph attachment limit
are uploaded through Graph upload sessions. For encrypted outgoing drafts,
attachments are embedded locally in the encrypted MIME message.

## Message Operations

```sh
msmail mark 1 --read
msmail mark 1-5,8 --unread
msmail delete 1
msmail delete 1-4 --yes
msmail delete --id AAMkAG... --yes
msmail move 1 --folder junk
msmail move 15-20,1-5,7,10-12 --folder deleted
msmail move 1 --folder deleted
msmail folders
msmail move --id AAMkAG... --folder-id AQMk...
```

Supported folder aliases include `inbox`, `drafts`, `sent`, `deleted` and
`junk`. `msmail folders` lists mail folders recursively and indents child
folders.

## S/MIME

Configure your own certificate, private key and CA bundle:

```sh
msmail smime setup \
  --cert own-cert.pem \
  --key own-key.pem \
  --ca-bundle ca-bundle.pem \
  --account user@example.com

msmail smime status
msmail smime test-sign
```

Import a recipient certificate for encryption:

```sh
msmail smime import-recipient --cert alice.pem --email alice@example.com
```

Create signed/encrypted drafts:

```sh
msmail draft create --to alice@example.com --subject "Signed" --body "Hi" --sign
msmail draft create --to alice@example.com --subject "Encrypted" --body "Hi" --encrypt
msmail draft create --to alice@example.com --subject "Both" --body "Hi" --sign --encrypt
msmail reply 1 --body "Thanks." --sign --encrypt
msmail forward 1 --to alice@example.com --body "FYI" --sign --encrypt
```

Read and verify:

```sh
msmail read 1 --verify-smime
msmail read 1 --decrypt --verify-smime
msmail read 1 --decrypt --verify-smime --json
```

The JSON output includes signer certificate details when verification succeeds.

More details: [docs/SMIME.md](docs/SMIME.md).

## Signatures

Per-account signatures are read from:

```text
~/.local/share/msmail/accounts/<email>/signature.txt
~/.local/share/msmail/accounts/<email>/signature.html
```

Text drafts use `signature.txt`. HTML drafts use `signature.html`, falling back
to a converted text signature. Disable per message:

```sh
msmail draft create ... --no-signature
msmail reply 1 --body "..." --no-signature
```

## JSON and Scripts

Most commands have `--json`. JSON output includes the active account and Graph
message IDs where relevant:

```sh
id=$(msmail search "invoice" --json | jq -r '.[0].id')
msmail read --id "$id" --json
```

Use Graph IDs in scripts. Numeric indices are convenient for interactive use but
depend on the latest list/search cache.

## Development

Run tests:

```sh
.venv/bin/python -m pytest
.venv/bin/python -m compileall -q src
```

Project layout:

```text
src/msmail/
  cli.py
  commands/   # Typer-facing CLI commands
  core/       # Graph, auth, mail, drafts, MIME and S/MIME logic
tests/
docs/
```

Development and release notes: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) and
[docs/RELEASE.md](docs/RELEASE.md).

## License

MIT. See [LICENSE](LICENSE).

## Public Repository Safety

Private keys, certificates, token caches, decrypted mail, `.eml` files and
account state must stay outside the repository. The default runtime location is
`~/.local/share/msmail`, not the checkout.

Before publishing, review [docs/SECURITY.md](docs/SECURITY.md).
