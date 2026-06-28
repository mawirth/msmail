# Release Checklist

This project is close to a public `0.1.0` pre-release, but a few publication
steps should be explicit.

## Before Publishing on GitHub

- Confirm the MIT license in `LICENSE` is intended for the public release.
- Review the full tree for private data:

  ```sh
  find . -maxdepth 5 -type f \( \
    -name '*.pem' -o -name '*.key' -o -name '*.p12' -o -name '*.pfx' -o \
    -name '*.cer' -o -name '*.crt' -o -name '*token*' -o -name '*.eml' \
  \)
  ```

- Run tests:

  ```sh
  .venv/bin/python -m pytest
  .venv/bin/python -m compileall -q src
  ```

- Run the manual smoke tests from `docs/DEVELOPMENT.md`.
- Remove or keep intentionally any live smoke-test drafts in the mailbox.
- Confirm `pyproject.toml` and `src/msmail/__init__.py` use the same version.
- Confirm historical/private reference material is not present in this
  repository.

## Versioning

Recommended scheme:

- `0.1.x`: early CLI releases; command names may still change.
- `0.2.x`: stabilized S/MIME and folder/search behavior.
- `1.0.0`: command-line and JSON output compatibility are treated as stable.

Current version:

```text
0.1.0
```

## Suggested Git Tags

```sh
git tag -a v0.1.0 -m "msmail 0.1.0"
git push origin v0.1.0
```

## Known Limitations for 0.1.0

- S/MIME reply/forward does not quote or attach the original message.
- `draft edit` preserves existing normal attachments but cannot edit existing
  S/MIME drafts.
- S/MIME drafts created with `--sign` or `--encrypt` are readable but not
  editable; review long messages before creating the S/MIME MIME draft.
- OpenSSL temporary files are written under `/tmp`.
- Graph `$search` behavior depends on Microsoft Graph mailbox search semantics.

## Changelog Template

```markdown
## 0.1.0 - YYYY-MM-DD

- Initial public release.
- Microsoft Graph auth, list, read, search, folders.
- Draft-first create/edit/send/delete.
- Attachments and S/MIME sign/encrypt/decrypt/verify.
```
