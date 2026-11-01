# Independent JSON Pagination

`list --page-json` and `search --page-json` are intended for applications such
as Orbit. msmail owns authentication, mailbox queries and pagination. The
application owns presentation, selection and registration of exported `.eml`
files.

## Starting and Continuing

```sh
msmail list --all --fetch 25 --account you@example.com --page-json
msmail list --cursor "<next_cursor>" --page-json

msmail search "invoice" --fetch 25 --account you@example.com --page-json
msmail search --cursor "<next_cursor>" --page-json
```

Pass the returned `next_cursor` unchanged to the same command. Search
continuation does not take a search string. A cursor pins the account even if
the active account changes. An explicit `--account` is accepted only when it
resolves to the same account.

The first request accepts the usual list filters or a search query. In this
mode `--fetch` specifies the requested Graph page size, from 1 to 100; omitted
or `auto` means 25 regardless of terminal height. `all` is rejected. Each
invocation returns one complete Graph page, which can contain fewer or more
messages than requested. msmail never trims a page and skips its remaining
messages. Even an empty page can have a continuation cursor.

## Response

| Field | Meaning |
| --- | --- |
| `messages` | Array with the same message objects as existing `--json` output. |
| `next_cursor` | Opaque string for continuation, or `null` when finished. |
| `account` | Resolved mailbox account, including on an empty page. |
| `source` | `list` or `search`. |
| `offset` | Number of messages returned before this page. |

Message fields remain `id`, `account`, `index`, `subject`, `from_name`,
`from_address`, `received_date_time`, `is_read`, `has_attachments`,
`has_user_attachments`, `smime_signed`, `smime_encrypted`,
`inference_classification` and `body_preview`. `index` restarts at 1 within each
page and is for display only: it does not establish interactive message numbers.
Use `id` and `account` for subsequent operations, for example:

```sh
msmail export --id "<message.id>" --account "<message.account>" --to selected.eml
```

An empty final page looks like:

```json
{
  "messages": [],
  "next_cursor": null,
  "account": "you@example.com",
  "source": "search",
  "offset": 25
}
```

## Isolation and Validation

Page mode neither reads nor writes `last-list.json`. Multiple independent
lists and searches can be interleaved. Normal `list`, `search`, `--json` and
`list --more` retain their existing cache behavior and do not affect these
cursors. Reusing a cursor requests that page again; it does not consume local
state.

`--cursor` requires `--page-json`. It rejects new filters, a search string,
`--fetch` and `--attachment-details`; the initial attachment-detail setting
is carried forward. `--page-json` cannot be combined with `--json` or `--more`.
List and search cursors are not interchangeable.

Cursors are versioned and validated before authentication or any mail request.
They contain account and query state, but no access or refresh tokens, message
bodies or attachments. They are encoded, not encrypted or signed; applications
must not interpret or construct them. Only HTTPS URLs on `graph.microsoft.com`
for the supported `/v1.0/me/…/messages` collections are accepted. Redirects are
not followed. Invalid cursors and conflicting accounts fail with status 1;
conflicting CLI options fail with status 2. Diagnostics go to stderr.

msmail follows the complete [Graph nextLink](https://learn.microsoft.com/en-us/graph/paging)
without rewriting its query or skip token. Cursors are subject to Graph's query
limits and lifetime; they do not create a stable snapshot of the mailbox. If a
continuation becomes invalid, start a new query. No further cursor means Graph
returned no continuation, including when a service-side search limit is reached.
