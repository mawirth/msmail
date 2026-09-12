# S/MIME

`msmail` uses OpenSSL for S/MIME operations. The important safety property is
that encrypted outgoing mail is assembled and encrypted locally before a draft
is created in Microsoft Graph.

## Local Material

Account-scoped S/MIME material lives under:

```text
~/.local/share/msmail/accounts/<email>/smime/
  own-cert.pem
  own-key.pem
  ca-bundle.pem
  own-fullchain.p12
  recipients/
    alice@example.com.pem
```

The repository must never contain private keys, token caches, recipient
certificates or decrypted message files.

## Setup

Configure the account certificate and private key:

```sh
msmail smime setup \
  --cert own-cert.pem \
  --key own-key.pem \
  --ca-bundle ca-bundle.pem \
  --account user@example.com
```

Check status:

```sh
msmail smime status --account user@example.com
msmail smime test-sign --account user@example.com
```

Import recipient certificates:

```sh
msmail smime import-recipient --cert alice.pem --email alice@example.com
```

Encryption always includes `own-cert.pem`, so the sender can decrypt the draft
and sent copy. This adds a cryptographic recipient only, not another mail recipient.

## Outgoing Mail

S/MIME drafts created with `--sign` or `--encrypt` are complete MIME drafts.
They can be read, sent or deleted, but they cannot be edited with
`msmail draft edit`. Review long messages as normal drafts before creating the
signed or encrypted final draft.

Signed draft:

```sh
msmail draft create --to alice@example.com --subject "Signed" --body "Hi" --sign
```

Encrypted draft:

```sh
msmail draft create --to alice@example.com --subject "Encrypted" --body "Hi" --encrypt
```

Signed and encrypted draft:

```sh
msmail draft create --to alice@example.com --subject "Both" --body "Hi" --sign --encrypt
```

With attachments:

```sh
msmail draft create \
  --to alice@example.com \
  --subject "Report" \
  --body "Attached." \
  --attach report.pdf \
  --sign \
  --encrypt
```

For `--encrypt`, attachments are embedded into the local MIME entity before
encryption. They are not uploaded separately as Graph attachments.

Reply and forward can also be signed/encrypted:

```sh
msmail reply 1 --body "Thanks." --sign --encrypt
msmail forward 1 --to alice@example.com --body "FYI" --sign --encrypt
```

Current limitation: S/MIME reply/forward creates a new MIME draft with the
given body. It does not yet include quoted original content or original
attachments automatically.

## Incoming Mail

Detect S/MIME markers:

```sh
msmail list --attachment-details
msmail read 1 --attachment-details
msmail read 1 --attachment-details --json
```

Verify a signed message:

```sh
msmail read 1 --verify-smime
```

Decrypt and verify a signed+encrypted message:

```sh
msmail read 1 --decrypt --verify-smime
```

Save attachments from an encrypted S/MIME container:

```sh
msmail save-attachments 1 --decrypt --verify-smime --to ~/Downloads
```

JSON output contains verification state and signer certificate details when
available:

```json
{
  "smime": {
    "signed": true,
    "encrypted": true,
    "decrypted": true,
    "verified": true,
    "trusted": true,
    "sender_matches": true,
    "signer_certificate": {
      "subject": "...",
      "issuer": "...",
      "not_before": "...",
      "not_after": "...",
      "emails": ["user@example.com"],
      "email_protection": true
    }
  }
}
```

`verified` means that the content signature and certificate chain verified.
`sender_matches` compares certificate email addresses with the displayed From
address; `trusted` requires both checks to succeed. A valid signature with a
different sender is displayed as a mismatch. Saving with `--verify-smime` refuses
such a message. The flag also works without `--decrypt` on signed-only messages.

## Temporary Files

OpenSSL operations use private temporary directories below `/tmp` by default.
Normal reading, verification, decryption and draft creation remove their working
directories after use. An explicit `--output-dir` and `smime test-sign` keep their
outputs for inspection. Use a private `TMPDIR` if needed; see [SECURITY.md](SECURITY.md).
