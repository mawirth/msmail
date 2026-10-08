# Open Items

Remaining findings from the reviews, updated on 2026-10-08, plus decisions
worth not re-litigating. Items are roughly ordered by value within each group.

## Correctness

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

## Interface

**`draft create` has no `--cc` or `--bcc`.** Only `send` has them; for a draft
you need a compose file. Asymmetric and easy to trip over.

**`mark` applies without confirmation**, unlike `move` and `delete`, including
for ranges. Defensible, since read state is reversible, but it is the one range
operation with no preview. Documented in the README.

## Deferred

- CI and lint configuration will be considered separately; this cleanup does
  not introduce workflows or additional tooling dependencies.

## Decided, not open

- **October 2026 cleanup:** local reference resolution no longer acquires a
  token. CLI invocations reuse unexpired credentials and delete/move reuse
  preview metadata. Corrupt account state produces actionable errors; cache
  maintenance failures after successful mutations are warnings. Batch failures
  identify completed messages before stopping.

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
