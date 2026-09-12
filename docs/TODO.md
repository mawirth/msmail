# Open Items

Findings from the review on 2026-07-30 that were not addressed, plus decisions
worth not re-litigating. Nothing here is urgent; the items are roughly ordered
by value within each group.

## Correctness

**Corrupt state files raise a traceback.** `core/auth.py` reads
`auth-state.json` in `_active_email` and `profile.json` in `_load_profile` with
a bare `json.loads`. A truncated or hand-edited file produces a raw
`JSONDecodeError` instead of "run auth --login again". `last-list.json` was
given tolerant loading during the paging work; these two were not.

**`list_folders` recurses without a depth limit.** `core/mail.py` walks
`childFolders` for every folder reporting children. A deeply nested or
self-referential structure would recurse until Python's stack limit. A depth cap
with a warning would be enough.

## Security

**`--encrypt` together with `Bcc` discloses that further recipients exist.**
`_post_smime_draft` encrypts one message against To + Cc + Bcc, so the CMS
structure carries a `RecipientInfo` per recipient, each with the issuer and
serial number of that recipient's certificate. A To recipient can read them with
`openssl cms -cmsout -print`. No mail server can strip this: the entries are
required for decryption.

This is inherent to S/MIME, not specific to msmail. The fix mail clients use is
one separately encrypted message per Bcc recipient, which means splitting
`_post_smime_draft` into per-recipient sends. Documented as a limitation in the
README for now.

## Efficiency

**A token is acquired and thrown away.** `mail.resolve_message_reference` calls
`auth.get_access_token` and immediately does `del access_token`; it only wants
the account address. Every reference resolution pays for a silent MSAL
acquisition.

**Batch operations still fetch each message twice.** `delete` and `move` load a
preview per message and then load it again inside `mail.delete_message` /
`mail.move_message` for the result summary. The expensive part -- attachment
bodies -- is gone since both now pass `include_attachment_details=False`, but
the second round trip remains. Passing the already-loaded `MessageDetail` down
would remove it.

## Interface

**`draft create` has no `--cc` or `--bcc`.** Only `send` has them; for a draft
you need a compose file. Asymmetric and easy to trip over.

**`mark` applies without confirmation**, unlike `move` and `delete`, including
for ranges. Defensible, since read state is reversible, but it is the one range
operation with no preview. Documented in the README.

## Decided, not open

- **Missing draft IDs are errors.** Fixed in the September 2026 review: creation
  no longer reports success without an ID. Attachment upload failures include
  the retained draft ID for inspection.

- **`--limit` was removed, not aliased.** `--fetch` replaced it outright at
  0.1.0 while the cost of breaking scripts is near zero. Do not reintroduce an
  alias without a reason.
- **Paging only goes forward.** `--back` would need a stack of cursors. Left out
  until it is actually missed.
- **`search` keeps no paging cursor.** Graph orders `$search` by relevance and
  may shift results between pages, so `list --more` refuses to continue a
  search. Use a larger `--fetch`.
- **The `Bcc:` header in signed MIME drafts is not a leak.** Verified against
  Graph on 2026-07-30: an uploaded MIME draft has its `Bcc:` header parsed into
  the structured `bccRecipients` field, exactly as with a normal JSON draft. A
  control draft created through the JSON path stores the same header. The
  encryption issue above is separate and real.
