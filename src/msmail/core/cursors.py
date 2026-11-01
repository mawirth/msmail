"""Versioned, self-contained mail cursors; no credentials or shared state."""
from __future__ import annotations

import base64
import binascii
from dataclasses import asdict, dataclass
import json
import re
from urllib.parse import parse_qsl, urlsplit


MAX_CURSOR_LENGTH = 65536


@dataclass(frozen=True)
class Cursor:
    account: str
    source: str
    next_link: str
    offset: int
    attachment_details: bool = False


def validate_link(link: str, source: str) -> None:
    """Accept only the mail collection URLs used by our list/search queries."""
    if not isinstance(link, str) or not link or len(link) > MAX_CURSOR_LENGTH:
        raise ValueError("Invalid mail cursor URL.")
    if any(ord(character) <= 32 or ord(character) >= 127 for character in link):
        raise ValueError("Invalid mail cursor URL.")
    url = urlsplit(link)
    path = r"/v1\.0/me/messages"
    if source == "list":
        # Graph can canonicalize folder aliases to IDs or OData key syntax.
        # Only opaque folder keys are allowed, never dot segments or subpaths.
        folder_key = r"(?:[A-Za-z0-9_+=-]|%2[BbFf]|%3[Dd])+"
        path = rf"/v1\.0/me/mailFolders(?:/{folder_key}|\('{folder_key}'\))/messages"
    if (
        source not in {"list", "search"}
        or url.scheme != "https"
        or url.netloc != "graph.microsoft.com"
        or url.fragment
        or not re.fullmatch(path, url.path, flags=re.IGNORECASE)
    ):
        raise ValueError("Invalid mail cursor URL.")
    # Continuation links carry query state, never authentication credentials.
    if any(
        key.lower() in {"access_token", "refresh_token", "authorization", "client_secret"}
        for key, _ in parse_qsl(url.query)
    ):
        raise ValueError("Credentials are not allowed in mail cursors.")


def _validate(cursor: Cursor) -> None:
    if (
        not isinstance(cursor.account, str)
        or not cursor.account
        or len(cursor.account) > 320
        or any(character.isspace() or ord(character) < 32 for character in cursor.account)
        or not isinstance(cursor.source, str)
        or type(cursor.offset) is not int
        or cursor.offset < 0
        or type(cursor.attachment_details) is not bool
    ):
        raise ValueError("Invalid mail cursor state.")
    validate_link(cursor.next_link, cursor.source)


def encode(cursor: Cursor) -> str:
    _validate(cursor)
    data = json.dumps({"version": 1, **asdict(cursor)}, separators=(",", ":")).encode("utf-8")
    result = base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")
    if len(result) > MAX_CURSOR_LENGTH:
        raise ValueError("Mail cursor is too large.")
    return result


def decode(value: str) -> Cursor:
    try:
        if len(value) > MAX_CURSOR_LENGTH or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Invalid encoding")
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict) or type(data.get("version")) is not int or data.pop("version") != 1:
            raise ValueError("Invalid version")
        if set(data) != set(Cursor.__dataclass_fields__):
            raise ValueError("Invalid fields")
        cursor = Cursor(**data)
        _validate(cursor)
        return cursor
    except (ValueError, TypeError, UnicodeError, binascii.Error, RecursionError) as exc:
        raise ValueError("Invalid mail cursor. Start a new --page-json query.") from exc
