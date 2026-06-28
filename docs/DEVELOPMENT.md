# Development

## Setup

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

Run the CLI from the checkout:

```sh
python -m msmail --help
msmail --help
```

## Test Commands

```sh
.venv/bin/python -m pytest
.venv/bin/python -m compileall -q src
```

Live Microsoft Graph tests are manual for now. Use a test account or a small
set of clearly named smoke-test messages. Do not send or delete real mail while
testing unless that is the explicit purpose of the test.

## Architecture

```text
src/msmail/
  cli.py
  commands/
    auth.py
    draft.py
    list.py
    read.py
    respond.py
    save_attachments.py
    search.py
  core/
    auth.py
    compose.py
    drafts.py
    graph.py
    mail.py
    mime.py
    render.py
    signature.py
    smime.py
```

`commands/` contains Typer-facing command handlers and presentation logic.
`core/` contains code that should be testable without Typer.

## State Model

Runtime state is intentionally outside the repository:

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

`last-list.json` is the cache used for numeric references such as `msmail read
1`. `draft send`, `mark`, `move` and `delete` also support range references
such as `1-4` or `15-20,1-5,7,10-12`; commands with confirmation print every
affected item before continuing. Scripts should use Graph IDs from `--json`
instead.

## Coding Notes

- Keep Graph HTTP details in `core/graph.py`.
- Keep message and folder operations in `core/mail.py`.
- Keep draft creation and outgoing MIME handling in `core/drafts.py`.
- Keep S/MIME OpenSSL calls in `core/smime.py`.
- Keep MIME parsing helpers in `core/mime.py`.
- Do not add repository-local key or token fixtures.

## Manual Smoke Tests

After authenticating:

```sh
msmail auth --whoami
msmail list --limit 5
msmail read 1
msmail search "msmail" --limit 3
msmail folders
```

Draft workflow:

```sh
msmail draft create \
  --to you@example.com \
  --subject "msmail smoke" \
  --body "Draft smoke." \
  --json

msmail list --folder drafts
msmail read 1
```

S/MIME workflow:

```sh
msmail smime status
msmail smime test-sign
msmail draft create \
  --to you@example.com \
  --subject "msmail signed encrypted smoke" \
  --body "S/MIME smoke." \
  --sign \
  --encrypt \
  --json
```

Send only from a reviewed draft:

```sh
msmail draft send --id AAMk... --yes
```
