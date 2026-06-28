from __future__ import annotations

from dataclasses import dataclass
from email import policy
from email.message import Message
from email.parser import BytesParser
from pathlib import Path

from msmail.core import render


@dataclass(frozen=True)
class MimeAttachment:
    name: str
    content_type: str
    data: bytes


def _decode_part(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw_payload = part.get_payload()
        return raw_payload if isinstance(raw_payload, str) else ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _find_body_part(message: Message, preferred_type: str) -> Message | None:
    if message.get_content_type().lower() == "multipart/signed":
        payload = message.get_payload()
        if isinstance(payload, list) and payload:
            return _find_body_part(payload[0], preferred_type)

    if message.is_multipart():
        if message.get_content_type().lower() == "multipart/alternative":
            for part in reversed(message.get_payload()):
                found = _find_body_part(part, preferred_type)
                if found:
                    return found
        for part in message.get_payload():
            found = _find_body_part(part, preferred_type)
            if found:
                return found
        return None

    disposition = (message.get_content_disposition() or "").lower()
    if disposition == "attachment":
        return None
    content_type = message.get_content_type().lower()
    if content_type == preferred_type:
        return message
    if preferred_type == "text/plain" and content_type == "text/html":
        return message
    if preferred_type == "text/html" and content_type == "text/plain":
        return message
    return None


def parse_message(mime_bytes: bytes) -> Message:
    return BytesParser(policy=policy.default).parsebytes(mime_bytes)


def body_from_mime(mime_bytes: bytes, raw_html: bool) -> tuple[str, str, list[str]]:
    parsed = parse_message(mime_bytes)
    body_part = _find_body_part(parsed, "text/html" if raw_html else "text/plain")
    if body_part is None:
        return "", "text", attachment_names(parsed)

    content_type = body_part.get_content_type().lower()
    content = _decode_part(body_part)
    if raw_html:
        rendered = content
    elif content_type == "text/html":
        rendered = render.html_to_text(content)
    else:
        rendered = render.unwrap_safelinks_in_text(content)
    return rendered, content_type.removeprefix("text/") or "text", attachment_names(parsed)


def attachment_names(message: Message) -> list[str]:
    return [attachment.name for attachment in attachments(message, include_smime=True)]


def attachments(message: Message, *, include_smime: bool = False) -> list[MimeAttachment]:
    result = []
    for part in message.walk():
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or "").lower()
        filename = part.get_filename()
        if disposition != "attachment" and not filename:
            continue
        filename = filename or "attachment"
        content_type = part.get_content_type().lower()
        if not include_smime and (
            filename.lower() in {"smime.p7s", "smime.p7m"}
            or "pkcs7-signature" in content_type
            or "pkcs7-mime" in content_type
        ):
            continue
        payload = part.get_payload(decode=True) or b""
        result.append(
            MimeAttachment(
                name=filename,
                content_type=content_type,
                data=payload,
            )
        )
    return result


def save_attachments(
    mime_bytes: bytes,
    *,
    destination: Path,
    unique_path,
    safe_name,
    overwrite: bool,
) -> list[tuple[str, Path, int]]:
    parsed = parse_message(mime_bytes)
    saved = []
    for index, attachment in enumerate(attachments(parsed), start=1):
        filename = safe_name(attachment.name, fallback=f"attachment-{index}")
        target = unique_path(destination, filename, overwrite)
        target.write_bytes(attachment.data)
        saved.append((filename, target, len(attachment.data)))
    return saved
