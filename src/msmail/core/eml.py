"""Read-only adapter from a local RFC 5322/MIME message to the mail view."""
from __future__ import annotations

from dataclasses import dataclass, replace
from email.message import Message
from email.errors import MessageError
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Optional

from msmail.core import attachments, mail, mime, render


@dataclass(frozen=True)
class LocalMessageDetail(mail.MessageDetail):
    smime_signed: Optional[bool]
    source: str = "file"
    source_path: str = ""
    date_header: str = ""
    sent_date_time: Optional[str] = None
    date_source: str = "Date header"
    smime_account: Optional[str] = None


def parse(data: bytes) -> Message:
    try:
        parsed = mime.parse_message(data)
        if not parsed.keys():
            raise ValueError("No message headers found.")
        for part in parsed.walk():
            if not part.is_multipart():
                part.get_payload(decode=True)  # Also detect broken transfer encoding.
            if part.defects:
                raise ValueError(", ".join(type(defect).__name__ for defect in part.defects))
        return parsed
    except (ValueError, RecursionError, MessageError) as exc:
        raise ValueError(f"Invalid MIME in EML content: {exc}") from exc


def with_content(message: LocalMessageDetail, data: bytes, *, raw_html: bool) -> LocalMessageDetail:
    return _with_parsed_content(message, parse(data), raw_html=raw_html)


def _with_parsed_content(message: LocalMessageDetail, parsed: Message, *, raw_html: bool) -> LocalMessageDetail:
    content, content_type = mime.body_content(parsed, prefer_html=raw_html)
    infos = []
    for attachment in mime.attachments(parsed):
        infos.append(mail.AttachmentInfo(
            id=None,
            name=render.display_text(attachments.safe_name(attachment.name, "attachment")),
            content_type=attachment.content_type,
            size=len(attachment.data or b""),
            is_inline=attachment.is_inline,
            attachment_type="fileAttachment",
            can_save=False,  # No Graph attachment ID; local saving is not a read operation.
            is_smime_signature=False,
            is_smime_encrypted=False,
        ))
    signed, encrypted = mime.smime_flags(parsed)
    plain = render.html_to_text(content) if content_type == "html" else render.unwrap_safelinks_in_text(content)
    return replace(
        message, body_content=content, body_content_type=content_type,
        body_preview=render.display_text(plain)[:255],
        attachments=infos, attachment_count=len(infos), has_attachments=bool(infos),
        smime_signed=signed, smime_encrypted=encrypted,
    )


def read_file(filename: str, *, raw_html: bool = False, account: Optional[str] = None) -> tuple[LocalMessageDetail, bytes]:
    path = Path(filename).expanduser().absolute()
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"Cannot read EML file {path}: {exc.strerror or exc}") from exc
    parsed = parse(data)
    def header(name: str) -> str:
        try:
            return render.display_text(str(parsed.get(name, "")))
        except (ValueError, TypeError, MessageError) as exc:
            raise ValueError(f"Invalid EML header: {name}.") from exc

    sender = getaddresses([header("From")])
    # Preserve an invalid Date as text too; older Python header registries can
    # raise while constructing their structured DateHeader object.
    date_header = render.display_text(next((value for name, value in parsed.raw_items() if name.lower() == "date"), ""))
    try:
        sent_date = parsedate_to_datetime(date_header).isoformat() if date_header else None
    except (ValueError, TypeError, OverflowError):
        sent_date = None
    message = LocalMessageDetail(
        account=None, id=None, received_date_time=None,
        subject=header("Subject"),
        from_name=sender[0][0] if sender else "",
        from_address=sender[0][1] if sender else "",
        to_addresses=[render.display_text(address) for _, address in getaddresses([str(v) for v in parsed.get_all("To", [])])],
        cc_addresses=[render.display_text(address) for _, address in getaddresses([str(v) for v in parsed.get_all("Cc", [])])],
        internet_message_id=header("Message-ID"),
        body_content_type="text", body_content="", body_preview="",
        has_attachments=False, attachment_count=0, attachments=[],
        smime_signed=False, smime_encrypted=False, attachment_details_loaded=True,
        source_path=str(path), date_header=date_header, sent_date_time=sent_date,
        smime_account=account,
    )
    return _with_parsed_content(message, parsed, raw_html=raw_html), data
