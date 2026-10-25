from __future__ import annotations

from email import policy
from email.message import Message
from email.parser import BytesParser

from msmail.core import attachments as attachment_files
from msmail.core import render
from msmail.core.attachments import FileAttachment


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
    if message.get_content_disposition() == "attachment":
        return None
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
    return None


def parse_message(mime_bytes: bytes) -> Message:
    return BytesParser(policy=policy.default).parsebytes(mime_bytes)


def body_from_mime(mime_bytes: bytes, raw_html: bool) -> tuple[str, str, list[str]]:
    parsed = parse_message(mime_bytes)
    preferred, fallback = ("text/html", "text/plain") if raw_html else ("text/plain", "text/html")
    body_part = _find_body_part(parsed, preferred)
    if body_part is None:
        body_part = _find_body_part(parsed, fallback)
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


def attachments(message: Message, *, include_smime: bool = False) -> list[FileAttachment]:
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
            attachment_files.is_smime_signature(filename, content_type)
            or attachment_files.is_smime_encrypted(filename, content_type)
        ):
            continue
        payload = part.get_payload(decode=True) or b""
        result.append(
            FileAttachment(
                name=filename,
                content_type=content_type,
                data=payload,
                is_inline=disposition == "inline",
            )
        )
    return result
