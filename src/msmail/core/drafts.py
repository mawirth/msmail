from __future__ import annotations

import base64
from dataclasses import dataclass
import mimetypes
from pathlib import Path
from typing import Any, Optional

from msmail.core import auth, compose, graph, render, signature, smime
from msmail.core import mail


MAX_SIMPLE_ATTACHMENT_BYTES = 3 * 1024 * 1024
MAX_UPLOAD_SESSION_ATTACHMENT_BYTES = 150 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class DraftResult:
    account: str
    id: str
    subject: str
    to: list[str]
    attachments: list[str]


@dataclass(frozen=True)
class DraftInfo:
    account: str
    id: str
    subject: str
    from_address: str
    to: list[str]
    cc: list[str]
    bcc: list[str]
    has_attachments: bool
    is_draft: bool


@dataclass(frozen=True)
class DraftEditResult:
    account: str
    id: str
    subject: str
    to: list[str]
    attachments: list[str]


@dataclass(frozen=True)
class ResponseDraftResult:
    account: str
    id: str
    subject: str
    to: list[str]
    source_id: str
    response_type: str


@dataclass(frozen=True)
class AttachmentFile:
    path: Path
    name: str
    size: int
    content_type: str


def _recipient(address: str) -> dict[str, Any]:
    return {"emailAddress": {"address": address}}


def _addresses(recipients: list[dict[str, Any]]) -> list[str]:
    addresses = []
    for recipient in recipients or []:
        address = (recipient.get("emailAddress") or {}).get("address")
        if address:
            addresses.append(address)
    return addresses


def _email_address(value: dict[str, Any] | None) -> str:
    return ((value or {}).get("emailAddress") or {}).get("address") or ""


def _reject_unsupported(draft: compose.ComposeDraft) -> None:
    if draft.sign or draft.encrypt:
        raise ValueError("Editing existing S/MIME drafts is not implemented; create a new signed/encrypted draft instead.")


def _message_body_to_text(body: dict[str, Any]) -> str:
    content = body.get("content") or ""
    content_type = (body.get("contentType") or "").lower()
    if content_type == "html":
        return render.html_to_text(content)
    return render.unwrap_safelinks_in_text(content)


def _draft_payload(draft: compose.ComposeDraft) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "subject": draft.subject,
        "body": {
            "contentType": draft.body_content_type,
            "content": draft.body,
        },
        "toRecipients": [_recipient(address) for address in draft.to],
        "ccRecipients": [_recipient(address) for address in draft.cc],
        "bccRecipients": [_recipient(address) for address in draft.bcc],
    }
    return payload


def _response_payload(response: compose.ResponseDraft) -> dict[str, Any]:
    payload: dict[str, Any] = {"comment": response.body}
    if response.to:
        payload["toRecipients"] = [_recipient(address) for address in response.to]
    if response.cc:
        payload["ccRecipients"] = [_recipient(address) for address in response.cc]
    if response.bcc:
        payload["bccRecipients"] = [_recipient(address) for address in response.bcc]
    return payload


def _prepare_body(
    body: str,
    *,
    account_email: str,
    content_type: str,
    include_signature: bool,
) -> str:
    if content_type.lower() == "html":
        body = signature.format_html_body(body)
    return signature.append_signature(
        body,
        account_email=account_email,
        content_type=content_type,
        enabled=include_signature,
    )


def _attachment_file(path_value: str) -> AttachmentFile:
    path = Path(path_value).expanduser()
    if not path.exists():
        raise ValueError(f"Attachment not found: {path_value}")
    if not path.is_file():
        raise ValueError(f"Attachment is not a file: {path_value}")

    size = path.stat().st_size
    if size > MAX_UPLOAD_SESSION_ATTACHMENT_BYTES:
        limit_mb = MAX_UPLOAD_SESSION_ATTACHMENT_BYTES // (1024 * 1024)
        raise ValueError(
            f"Attachment is too large: {path_value} "
            f"({size} bytes, limit {limit_mb} MB)."
        )

    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return AttachmentFile(
        path=path,
        name=path.name,
        size=size,
        content_type=content_type,
    )


def _attachment_mime_parts(attachments: list[AttachmentFile]) -> list[tuple[str, str, bytes]]:
    return [
        (attachment.name, attachment.content_type, attachment.path.read_bytes())
        for attachment in attachments
    ]


def _simple_attachment_payload(attachment: AttachmentFile) -> dict[str, Any]:
    content = base64.b64encode(attachment.path.read_bytes()).decode("ascii")
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": attachment.name,
        "contentType": attachment.content_type,
        "contentBytes": content,
    }


def _attachment_files(draft: compose.ComposeDraft) -> list[AttachmentFile]:
    return [_attachment_file(attachment) for attachment in draft.attachments]


def _create_upload_session(
    draft_id: str,
    attachment: AttachmentFile,
    access_token: str,
) -> str:
    draft_path_id = graph.quote_path_segment(draft_id)
    response = graph.post_json(
        f"/me/messages/{draft_path_id}/attachments/createUploadSession",
        access_token,
        body={
            "AttachmentItem": {
                "attachmentType": "file",
                "name": attachment.name,
                "size": attachment.size,
                "contentType": attachment.content_type,
            }
        },
    )
    upload_url = response.get("uploadUrl")
    if not isinstance(upload_url, str) or not upload_url:
        raise graph.GraphError("Graph did not return an attachment upload URL.")
    return upload_url


def _upload_large_attachment(
    draft_id: str,
    attachment: AttachmentFile,
    access_token: str,
) -> None:
    upload_url = _create_upload_session(draft_id, attachment, access_token)
    with attachment.path.open("rb") as handle:
        offset = 0
        while True:
            chunk = handle.read(UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            end = offset + len(chunk) - 1
            graph.put_bytes(
                upload_url,
                chunk,
                headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{end}/{attachment.size}",
                },
            )
            offset = end + 1


def _upload_attachments(
    draft_id: str,
    attachments: list[AttachmentFile],
    access_token: str,
) -> list[str]:
    uploaded = []
    draft_path_id = graph.quote_path_segment(draft_id)
    for attachment in attachments:
        if attachment.size <= MAX_SIMPLE_ATTACHMENT_BYTES:
            graph.post_json(
                f"/me/messages/{draft_path_id}/attachments",
                access_token,
                body=_simple_attachment_payload(attachment),
            )
        else:
            _upload_large_attachment(draft_id, attachment, access_token)
        uploaded.append(attachment.name)
    return uploaded


def _post_smime_draft(
    draft: compose.ComposeDraft,
    *,
    account_email: str,
    access_token: str,
    attachments: list[AttachmentFile],
) -> DraftResult:
    mime_entity = smime.build_mime_entity(
        body=draft.body,
        content_type=draft.body_content_type,
        attachments=_attachment_mime_parts(attachments),
    )

    if draft.sign:
        _unsigned_path, signed_path = smime.sign_mime(
            mime_entity,
            account_email=account_email,
        )
        mime_entity = Path(signed_path).read_bytes()

    if draft.encrypt:
        recipients = draft.to + draft.cc + draft.bcc
        _clear_path, encrypted_path = smime.encrypt_mime(
            mime_entity,
            recipients=recipients,
            account_email=account_email,
        )
        mime_entity = Path(encrypted_path).read_bytes()

    mime_message = smime.wrap_mime_entity(
        sender=account_email,
        to=draft.to,
        cc=draft.cc,
        bcc=draft.bcc,
        subject=draft.subject,
        entity=mime_entity,
    )
    response = graph.post_mime_json(
        "/me/messages",
        access_token,
        mime_message,
    )
    return DraftResult(
        account=account_email,
        id=response.get("id") or "",
        subject=response.get("subject") or draft.subject,
        to=draft.to,
        attachments=[attachment.name for attachment in attachments],
    )


def create_draft(
    draft: compose.ComposeDraft,
    account_email: Optional[str] = None,
    include_signature: bool = True,
) -> DraftResult:
    attachments = _attachment_files(draft)
    access_token, account = auth.get_access_token(account_email)
    draft = compose.ComposeDraft(
        to=draft.to,
        cc=draft.cc,
        bcc=draft.bcc,
        subject=draft.subject,
        body=_prepare_body(
            draft.body,
            account_email=account.email,
            content_type=draft.body_content_type,
            include_signature=include_signature,
        ),
        body_content_type=draft.body_content_type,
        attachments=draft.attachments,
        sign=draft.sign,
        encrypt=draft.encrypt,
    )

    if draft.sign or draft.encrypt:
        return _post_smime_draft(
            draft,
            account_email=account.email,
            access_token=access_token,
            attachments=attachments,
        )

    response = graph.post_json("/me/messages", access_token, body=_draft_payload(draft))
    draft_id = response.get("id") or ""
    uploaded = _upload_attachments(draft_id, attachments, access_token) if draft_id else []
    return DraftResult(
        account=account.email,
        id=draft_id,
        subject=response.get("subject") or draft.subject,
        to=draft.to,
        attachments=uploaded,
    )


def get_draft_info(reference: str, account_email: Optional[str] = None) -> DraftInfo:
    message_id, resolved_account = mail.resolve_message_reference(reference, account_email)
    access_token, account = auth.get_access_token(resolved_account)
    message_path_id = graph.quote_path_segment(message_id)
    message = graph.get_json(
        f"/me/messages/{message_path_id}",
        access_token,
        params={
            "$select": "id,subject,from,sender,toRecipients,ccRecipients,bccRecipients,hasAttachments,isDraft"
        },
    )
    info = DraftInfo(
        account=account.email,
        id=message.get("id") or message_id,
        subject=message.get("subject") or "",
        from_address=_email_address(message.get("from")) or _email_address(message.get("sender")) or account.email,
        to=_addresses(message.get("toRecipients") or []),
        cc=_addresses(message.get("ccRecipients") or []),
        bcc=_addresses(message.get("bccRecipients") or []),
        has_attachments=bool(message.get("hasAttachments")),
        is_draft=bool(message.get("isDraft")),
    )
    if not info.is_draft:
        raise ValueError("Refusing to send: selected message is not a draft.")
    return info


def compose_template_for_draft(reference: str, account_email: Optional[str] = None) -> tuple[str, DraftInfo]:
    message_id, resolved_account = mail.resolve_message_reference(reference, account_email)
    access_token, account = auth.get_access_token(resolved_account)
    message_path_id = graph.quote_path_segment(message_id)
    message = graph.get_json(
        f"/me/messages/{message_path_id}",
        access_token,
        params={
            "$select": "id,subject,from,sender,toRecipients,ccRecipients,bccRecipients,body,hasAttachments,isDraft"
        },
    )
    info = DraftInfo(
        account=account.email,
        id=message.get("id") or message_id,
        subject=message.get("subject") or "",
        from_address=_email_address(message.get("from")) or _email_address(message.get("sender")) or account.email,
        to=_addresses(message.get("toRecipients") or []),
        cc=_addresses(message.get("ccRecipients") or []),
        bcc=_addresses(message.get("bccRecipients") or []),
        has_attachments=bool(message.get("hasAttachments")),
        is_draft=bool(message.get("isDraft")),
    )
    if not info.is_draft:
        raise ValueError("Refusing to edit: selected message is not a draft.")
    if info.has_attachments:
        raise ValueError("Editing drafts with existing attachments is not implemented yet.")

    template = compose.compose_template(
        to=", ".join(info.to),
        cc=", ".join(info.cc),
        bcc=", ".join(info.bcc),
        subject=info.subject,
        body=_message_body_to_text(message.get("body") or {}),
    )
    return template, info


def update_draft(
    draft_id: str,
    draft: compose.ComposeDraft,
    account_email: Optional[str] = None,
    include_signature: bool = True,
) -> DraftEditResult:
    _reject_unsupported(draft)
    attachments = _attachment_files(draft)
    access_token, account = auth.get_access_token(account_email)
    draft = compose.ComposeDraft(
        to=draft.to,
        cc=draft.cc,
        bcc=draft.bcc,
        subject=draft.subject,
        body=_prepare_body(
            draft.body,
            account_email=account.email,
            content_type=draft.body_content_type,
            include_signature=include_signature,
        ),
        body_content_type=draft.body_content_type,
        attachments=draft.attachments,
        sign=draft.sign,
        encrypt=draft.encrypt,
    )
    draft_path_id = graph.quote_path_segment(draft_id)
    graph.patch_json(
        f"/me/messages/{draft_path_id}",
        access_token,
        body=_draft_payload(draft),
    )
    uploaded = _upload_attachments(draft_id, attachments, access_token)
    return DraftEditResult(
        account=account.email,
        id=draft_id,
        subject=draft.subject,
        to=draft.to,
        attachments=uploaded,
    )


def delete_draft(reference: str, account_email: Optional[str] = None) -> DraftInfo:
    info = get_draft_info(reference, account_email=account_email)
    access_token, _account = auth.get_access_token(info.account)
    draft_path_id = graph.quote_path_segment(info.id)
    graph.delete_empty(f"/me/messages/{draft_path_id}", access_token)
    return info


def send_draft(draft_id: str, account_email: Optional[str] = None) -> None:
    access_token, _account = auth.get_access_token(account_email)
    draft_path_id = graph.quote_path_segment(draft_id)
    graph.post_empty(f"/me/messages/{draft_path_id}/send", access_token)


def create_reply_draft(
    reference: str,
    response: compose.ResponseDraft,
    *,
    reply_all: bool = False,
    sign: bool = False,
    encrypt: bool = False,
    account_email: Optional[str] = None,
    include_signature: bool = True,
) -> ResponseDraftResult:
    message_id, resolved_account = mail.resolve_message_reference(reference, account_email)
    access_token, account = auth.get_access_token(resolved_account)
    if sign or encrypt:
        source = mail.get_message(message_id, account_email=account.email)
        to = response.to or [source.from_address]
        cc = response.cc
        if reply_all:
            own = account.email.lower()
            existing = {address.lower() for address in to}
            cc = list(response.cc)
            for address in source.to_addresses + source.cc_addresses:
                normalized = address.lower()
                if normalized != own and normalized not in existing:
                    cc.append(address)
                    existing.add(normalized)
        draft_result = create_draft(
            compose.ComposeDraft(
                to=to,
                cc=cc,
                bcc=response.bcc,
                subject=source.subject if source.subject.lower().startswith("re:") else f"Re: {source.subject}",
                body=response.body,
                body_content_type=response.body_content_type,
                attachments=[],
                sign=sign,
                encrypt=encrypt,
            ),
            account_email=account.email,
            include_signature=include_signature,
        )
        return ResponseDraftResult(
            account=account.email,
            id=draft_result.id,
            subject=draft_result.subject,
            to=draft_result.to,
            source_id=message_id,
            response_type="reply-all" if reply_all else "reply",
        )

    response = compose.ResponseDraft(
        to=response.to,
        cc=response.cc,
        bcc=response.bcc,
        body=_prepare_body(
            response.body,
            account_email=account.email,
            content_type=response.body_content_type,
            include_signature=include_signature,
        ),
        body_content_type=response.body_content_type,
    )
    message_path_id = graph.quote_path_segment(message_id)
    action = "createReplyAll" if reply_all else "createReply"
    draft = graph.post_json(
        f"/me/messages/{message_path_id}/{action}",
        access_token,
        body=_response_payload(response),
    )
    return ResponseDraftResult(
        account=account.email,
        id=draft.get("id") or "",
        subject=draft.get("subject") or "",
        to=_addresses(draft.get("toRecipients") or []),
        source_id=message_id,
        response_type="reply-all" if reply_all else "reply",
    )


def create_forward_draft(
    reference: str,
    response: compose.ResponseDraft,
    *,
    sign: bool = False,
    encrypt: bool = False,
    account_email: Optional[str] = None,
    include_signature: bool = True,
) -> ResponseDraftResult:
    if not response.to:
        raise ValueError("Forward draft needs at least one To recipient.")
    message_id, resolved_account = mail.resolve_message_reference(reference, account_email)
    access_token, account = auth.get_access_token(resolved_account)
    if sign or encrypt:
        source = mail.get_message(message_id, account_email=account.email)
        subject = source.subject if source.subject.lower().startswith("fwd:") else f"Fwd: {source.subject}"
        draft_result = create_draft(
            compose.ComposeDraft(
                to=response.to,
                cc=response.cc,
                bcc=response.bcc,
                subject=subject,
                body=response.body,
                body_content_type=response.body_content_type,
                attachments=[],
                sign=sign,
                encrypt=encrypt,
            ),
            account_email=account.email,
            include_signature=include_signature,
        )
        return ResponseDraftResult(
            account=account.email,
            id=draft_result.id,
            subject=draft_result.subject,
            to=draft_result.to,
            source_id=message_id,
            response_type="forward",
        )

    response = compose.ResponseDraft(
        to=response.to,
        cc=response.cc,
        bcc=response.bcc,
        body=_prepare_body(
            response.body,
            account_email=account.email,
            content_type=response.body_content_type,
            include_signature=include_signature,
        ),
        body_content_type=response.body_content_type,
    )
    message_path_id = graph.quote_path_segment(message_id)
    draft = graph.post_json(
        f"/me/messages/{message_path_id}/createForward",
        access_token,
        body=_response_payload(response),
    )
    return ResponseDraftResult(
        account=account.email,
        id=draft.get("id") or "",
        subject=draft.get("subject") or "",
        to=_addresses(draft.get("toRecipients") or []) or response.to,
        source_id=message_id,
        response_type="forward",
    )
