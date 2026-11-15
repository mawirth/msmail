# Reading Local EML Files

The `read` command accepts exactly one source: a last-list index, `--id`, or
`--file`. The local source shares the mailbox reader's terminal and JSON output
path. There is no printing function or application-specific integration.

```sh
msmail read --file /path/message.eml
msmail read --file /path/message.eml --json
msmail read --file /path/message.eml --html --attachment-details
msmail read --file /path/message.eml --verify-smime
msmail read --file /path/message.eml --decrypt --verify-smime --account you@example.com
```

## Offline Operation and Source Preservation

Local reading does not request Graph credentials, contact the mailbox, or read
or write the last-list cache. No active account is needed. The input is read as
bytes and never rewritten, normalized or replaced. MIME parsing and S/MIME
operations work on those bytes in memory or in managed private temporary
directories, which are removed on success and failure.

`--account` selects local S/MIME configuration only. Local signature verification
without this option uses the system CA store, even if an account is active.
With the option, the configured account CA bundle and optional `trusted-ca.pem`
are included as for mailbox verification. No private key is needed to verify.
Decryption requires an explicit account and the existing S/MIME configuration.

## JSON and Dates

Most fields match `read --id`: sender, recipients, subject, MIME body,
attachment information, `rendered_body` and `smime`. Local metadata differs
where the source cannot establish mailbox facts:

| Field | Local meaning |
| --- | --- |
| `id` | `null`; a local file has no Graph message ID. |
| `account` | `null`; From/To and key configuration do not establish mailbox ownership. |
| `internet_message_id` | The Message-ID header, or an empty string if absent. |
| `received_date_time` | `null`; the actual receipt time is unknown. |
| `date_header` | The Date header as text, or an empty string. |
| `sent_date_time` | Parsed Date in ISO format, or `null` if missing/invalid. |
| `date_source` | `Date header`; explicitly identifies the provenance. |
| `source` | `file`. |
| `source_path` | Absolute input path. |
| `smime_account` | Explicitly supplied configuration account, otherwise `null`. |

An unknown Date timezone stays unknown; msmail does not assume UTC or the host's
timezone. Terminal output labels the date as an EML header and says that receipt
time is unknown.

MIME charset decoding, plain/HTML alternatives and SafeLinks use the existing
helpers. Local `rendered_body` is always prepared plain text with ANSI and other
terminal control characters removed. `--html` selects the HTML alternative and
shows its markup in the terminal; with local JSON, the markup is available in
`body_content`, while `rendered_body` is still printable plain text. Existing
mailbox `--html --json` behavior is retained.

Attachment metadata is available immediately for local files, so
`--attachment-details` needs no additional fetch. Local attachment IDs are
`null` and `can_save` is false: the mailbox `save-attachments` command does not
accept these local IDs. Inline flags and empty-file sizes are retained. S/MIME
containers are excluded from the user-attachment list. Decryption updates body
and attachment details while retaining the source headers and provenance.

## S/MIME States

The extra `signature_valid` and `certificate_trusted` fields distinguish content
integrity from certificate trust. They supplement the existing mailbox contract:

| Field | Meaning |
| --- | --- |
| `signed` | `true`/`false` once known; `null` when hidden by encryption. |
| `encrypted` | Whether the source envelope was encrypted, even after decryption. |
| `signature_valid` | `null` when unchecked; otherwise whether cryptographic verification succeeded. |
| `certificate_trusted` | Whether verification with the configured trust store succeeded; `null` if not established. |
| `verified` | Existing combined result: signature and certificate verification succeeded. `null` when unchecked. |
| `sender_matches` | Whether the signer certificate matches the outer From address; `null` when unchecked. |
| `trusted` | `verified` and a matching sender; `null` when unchecked. |
| `decrypted` | `null` when not attempted, `true` on success, `false` on failure. |
| `error`, `decrypt_error` | Verification or decryption diagnostics, when applicable. |

A valid signature can still have an untrusted or expired certificate. A valid,
trusted certificate can still fail the sender check. Neither case is labeled
as a trusted message. [OpenSSL's `-noverify` option](https://docs.openssl.org/3.1/man1/openssl-smime/)
is used only to distinguish signature validity after the combined verification
fails; it never promotes that result to trusted.

Detached and opaque signed messages can be displayed without verification.
Opaque extraction does not claim that the signature was checked. An encrypted
message's inner signing state is unknown until decryption succeeds. Verification
of encrypted content therefore needs `--decrypt` as well. Ordinary unsigned
files need neither certificates nor keys, even when the flags are supplied.

As with mailbox reading, a readable message can return status 0 with a failed
S/MIME result; consumers must inspect these fields before treating content as
trusted. Missing keys and failed decryption are reported through
`smime.decrypted=false` and `decrypt_error`. An unreadable file, broken MIME
structure/transfer encoding, or inability to run verification produces an
operational error on stderr and status 1. Conflicting source options use status 2.
Invalid Date text is preserved instead of being treated as a receipt date.
