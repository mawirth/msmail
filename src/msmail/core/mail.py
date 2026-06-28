from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timezone
import json
from pathlib import Path
from typing import Any, Literal, Optional

from msmail.core import auth, graph, mime, smime


Folder = Literal["inbox", "drafts", "sentitems", "deleteditems", "junkemail"]
InboxClass = Literal["focused", "other", "all"]

FOLDERS: dict[str, Folder] = {
    "inbox": "inbox",
    "drafts": "drafts",
    "sent": "sentitems",
    "sentitems": "sentitems",
    "deleted": "deleteditems",
    "deleteditems": "deleteditems",
    "junk": "junkemail",
    "junkemail": "junkemail",
}


@dataclass(frozen=True)
class MessageSummary:
    account: str
    index: int
    id: str
    subject: str
    from_name: str
    from_address: str
    received_date_time: str
    is_read: bool
    has_attachments: bool
    has_user_attachments: bool
    smime_signed: bool
    smime_encrypted: bool
    inference_classification: Optional[str]
    body_preview: str


@dataclass(frozen=True)
class AttachmentInfo:
    id: str
    name: str
    content_type: str
    size: int
    is_inline: bool
    attachment_type: str
    can_save: bool
    is_smime_signature: bool
    is_smime_encrypted: bool


@dataclass(frozen=True)
class MessageDetail:
    account: str
    id: str
    subject: str
    from_name: str
    from_address: str
    to_addresses: list[str]
    cc_addresses: list[str]
    received_date_time: str
    internet_message_id: str
    body_content_type: str
    body_content: str
    body_preview: str
    has_attachments: bool
    attachment_count: int
    attachments: list[AttachmentInfo]
    smime_signed: bool
    smime_encrypted: bool


@dataclass(frozen=True)
class MessageOperationResult:
    account: str
    id: str
    subject: str
    from_address: str
    destination_folder: Optional[str] = None


@dataclass(frozen=True)
class FolderInfo:
    account: str
    id: str
    display_name: str
    parent_folder_id: str
    depth: int
    child_folder_count: int
    total_item_count: int
    unread_item_count: int


@dataclass(frozen=True)
class SavedAttachment:
    name: str
    path: str
    size: int


@dataclass(frozen=True)
class SaveAttachmentsResult:
    account: str
    id: str
    subject: str
    saved: list[SavedAttachment]
    skipped: int


def normalize_folder(folder: str) -> Folder:
    normalized = folder.strip().lower()
    try:
        return FOLDERS[normalized]
    except KeyError as exc:
        allowed = ", ".join(sorted(FOLDERS))
        raise ValueError(f"Unknown folder '{folder}'. Allowed: {allowed}") from exc


def _is_smime_signature_attachment(name: str, content_type: str) -> bool:
    normalized_name = name.lower()
    normalized_type = content_type.lower()
    return (
        normalized_name in {"smime.p7s", "smime.p7m"}
        or "pkcs7-signature" in normalized_type
        or normalized_type == "multipart/signed"
    )


def _is_smime_encrypted_attachment(name: str, content_type: str) -> bool:
    normalized_name = name.lower()
    normalized_type = content_type.lower()
    return (
        normalized_name in {"smime.p7m", "smime.p7c"}
        and "multipart/signed" not in normalized_type
    ) or ("pkcs7-mime" in normalized_type and "signed" not in normalized_type)


def _attachment_flags(attachments: list[AttachmentInfo]) -> tuple[bool, bool, bool]:
    smime_signed = any(attachment.is_smime_signature for attachment in attachments)
    smime_encrypted = any(attachment.is_smime_encrypted for attachment in attachments)
    has_user_attachments = any(
        not attachment.is_inline
        and not attachment.is_smime_signature
        and not attachment.is_smime_encrypted
        and attachment.attachment_type == "fileAttachment"
        for attachment in attachments
    )
    return has_user_attachments, smime_signed, smime_encrypted


def _message_to_summary(
    account_email: str,
    index: int,
    message: dict[str, Any],
    attachments: Optional[list[AttachmentInfo]] = None,
) -> MessageSummary:
    sender = ((message.get("from") or {}).get("emailAddress") or {})
    has_attachments = bool(message.get("hasAttachments"))
    if attachments is None:
        attachments = []
    has_user_attachments, smime_signed, smime_encrypted = _attachment_flags(attachments)
    if has_attachments and not attachments:
        has_user_attachments = True
    return MessageSummary(
        account=account_email,
        index=index,
        id=message.get("id") or "",
        subject=message.get("subject") or "",
        from_name=sender.get("name") or "",
        from_address=sender.get("address") or "",
        received_date_time=message.get("receivedDateTime") or "",
        is_read=bool(message.get("isRead")),
        has_attachments=has_attachments,
        has_user_attachments=has_user_attachments,
        smime_signed=smime_signed,
        smime_encrypted=smime_encrypted,
        inference_classification=message.get("inferenceClassification"),
        body_preview=message.get("bodyPreview") or "",
    )


def _last_list_path(account_email: str) -> Path:
    return auth.account_dir(account_email) / "last-list.json"


def save_last_list(account_email: str, messages: list[MessageSummary]) -> None:
    path = _last_list_path(account_email)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(message) for message in messages], indent=2) + "\n",
        encoding="utf-8",
    )


def load_last_list(account_email: str) -> list[MessageSummary]:
    path = _last_list_path(account_email)
    if not path.exists():
        raise ValueError("No last list found. Run: msmail list")
    data = json.loads(path.read_text(encoding="utf-8"))
    return [MessageSummary(**item) for item in data]


def remove_from_last_list(account_email: str, message_id: str) -> None:
    path = _last_list_path(account_email)
    if not path.exists():
        return
    messages = load_last_list(account_email)
    remaining = [message for message in messages if message.id != message_id]
    if len(remaining) == len(messages):
        return
    save_last_list(account_email, remaining)


def update_last_list_read_state(account_email: str, message_id: str, is_read: bool) -> None:
    path = _last_list_path(account_email)
    if not path.exists():
        return
    messages = load_last_list(account_email)
    updated = [
        MessageSummary(
            account=message.account,
            index=message.index,
            id=message.id,
            subject=message.subject,
            from_name=message.from_name,
            from_address=message.from_address,
            received_date_time=message.received_date_time,
            is_read=is_read if message.id == message_id else message.is_read,
            has_attachments=message.has_attachments,
            has_user_attachments=message.has_user_attachments,
            smime_signed=message.smime_signed,
            smime_encrypted=message.smime_encrypted,
            inference_classification=message.inference_classification,
            body_preview=message.body_preview,
        )
        for message in messages
    ]
    save_last_list(account_email, updated)


def resolve_message_reference(reference: str, account_email: Optional[str] = None) -> tuple[str, str]:
    access_token, account = auth.get_access_token(account_email)
    del access_token

    if reference.isdigit():
        index = int(reference)
        messages = load_last_list(account.email)
        for message in messages:
            if message.index == index:
                return message.id, account.email
        raise ValueError(f"No message #{index} in last list.")

    return reference, account.email


def resolve_message_references(reference: str, account_email: Optional[str] = None) -> tuple[list[str], str]:
    items, resolved_account = resolve_message_reference_items(reference, account_email=account_email)
    return [item.id for item in items], resolved_account


def resolve_message_reference_items(reference: str, account_email: Optional[str] = None) -> tuple[list[MessageSummary], str]:
    access_token, account = auth.get_access_token(account_email)
    del access_token

    if not reference.strip():
        raise ValueError("Message reference is empty.")

    if not any(character in reference for character in ",-"):
        if reference.isdigit():
            index = int(reference)
            for message in load_last_list(account.email):
                if message.index == index:
                    return [message], account.email
            raise ValueError(f"No message #{index} in last list.")
        return [
            MessageSummary(
                account=account.email,
                index=0,
                id=reference,
                subject="",
                from_name="",
                from_address="",
                received_date_time="",
                is_read=False,
                has_attachments=False,
                has_user_attachments=False,
                smime_signed=False,
                smime_encrypted=False,
                inference_classification=None,
                body_preview="",
            )
        ], account.email

    messages = load_last_list(account.email)
    by_index = {message.index: message for message in messages}
    resolved = []
    seen = set()
    for raw_part in reference.split(","):
        part = raw_part.strip()
        if not part:
            raise ValueError(f"Invalid message range: {reference}")
        if "-" in part:
            start_text, end_text = [value.strip() for value in part.split("-", 1)]
            if not start_text.isdigit() or not end_text.isdigit():
                raise ValueError(f"Invalid message range part: {part}")
            start = int(start_text)
            end = int(end_text)
            if start > end:
                raise ValueError(f"Invalid descending message range: {part}")
            indexes = range(start, end + 1)
        else:
            if not part.isdigit():
                raise ValueError(f"Invalid message range part: {part}")
            indexes = [int(part)]

        for index in indexes:
            try:
                message = by_index[index]
            except KeyError as exc:
                raise ValueError(f"No message #{index} in last list.") from exc
            if message.id not in seen:
                resolved.append(message)
                seen.add(message.id)

    return resolved, account.email


def _quote_odata_string(value: str) -> str:
    return value.replace("'", "''")


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid date '{value}'. Use YYYY-MM-DD.") from exc


def _start_of_day_utc(value: str) -> str:
    parsed = _parse_date(value)
    return datetime.combine(parsed, time.min, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _build_filter(
    *,
    folder_id: Folder,
    inbox_class: InboxClass,
    from_address: Optional[str],
    after: Optional[str],
    before: Optional[str],
) -> str | None:
    filters = []

    if folder_id == "inbox" and inbox_class != "all":
        filters.append(f"inferenceClassification eq '{inbox_class}'")

    if from_address:
        sender = _quote_odata_string(from_address.strip().lower())
        filters.append(f"from/emailAddress/address eq '{sender}'")

    if after:
        filters.append(f"receivedDateTime ge {_start_of_day_utc(after)}")

    if before:
        filters.append(f"receivedDateTime lt {_start_of_day_utc(before)}")

    return " and ".join(filters) if filters else None


def _order_by(
    *,
    folder_id: Folder,
    inbox_class: InboxClass,
    from_address: Optional[str],
) -> str:
    fields = []
    if folder_id == "inbox" and inbox_class != "all":
        fields.append("inferenceClassification")
    if from_address:
        fields.append("from/emailAddress/address")
    fields.append("receivedDateTime DESC")
    return ",".join(fields)


def list_messages(
    *,
    folder: str = "inbox",
    inbox_class: InboxClass = "focused",
    limit: int = 25,
    account_email: Optional[str] = None,
    from_address: Optional[str] = None,
    after: Optional[str] = None,
    before: Optional[str] = None,
) -> list[MessageSummary]:
    folder_id = normalize_folder(folder)
    if folder_id != "inbox" and inbox_class != "all":
        raise ValueError("--focused/--other apply only to the inbox folder.")

    access_token, account = auth.get_access_token(account_email)
    account_email = account.email

    select = ",".join(
        [
            "id",
            "subject",
            "from",
            "receivedDateTime",
            "isRead",
            "hasAttachments",
            "inferenceClassification",
            "bodyPreview",
        ]
    )
    params = {
        "$top": str(limit),
        "$select": select,
        "$orderby": _order_by(
            folder_id=folder_id,
            inbox_class=inbox_class,
            from_address=from_address,
        ),
    }

    filter_expression = _build_filter(
        folder_id=folder_id,
        inbox_class=inbox_class,
        from_address=from_address,
        after=after,
        before=before,
    )
    if filter_expression:
        params["$filter"] = filter_expression

    response = graph.get_json(
        f"/me/mailFolders/{folder_id}/messages",
        access_token,
        params=params,
    )
    values = response.get("value") or []
    messages = []
    for index, message in enumerate(values, start=1):
        attachments = None
        message_id = message.get("id") or ""
        if message.get("hasAttachments") and message_id:
            attachments = list_attachments(message_id, account_email=account_email)
        messages.append(_message_to_summary(account_email, index, message, attachments))
    save_last_list(account_email, messages)
    return messages


def search_messages(
    query: str,
    *,
    limit: int = 25,
    account_email: Optional[str] = None,
) -> list[MessageSummary]:
    if not query.strip():
        raise ValueError("Search query is empty.")

    access_token, account = auth.get_access_token(account_email)
    account_email = account.email
    limit = max(1, min(limit, 100))
    response = graph.get_json(
        "/me/messages",
        access_token,
        params={
            "$top": str(limit),
            "$search": f'"{query}"',
            "$select": ",".join(
                [
                    "id",
                    "subject",
                    "from",
                    "receivedDateTime",
                    "isRead",
                    "hasAttachments",
                    "inferenceClassification",
                    "bodyPreview",
                ]
            ),
        },
    )
    messages = []
    for index, message in enumerate(response.get("value") or [], start=1):
        attachments = None
        message_id = message.get("id") or ""
        if message.get("hasAttachments") and message_id:
            attachments = list_attachments(message_id, account_email=account_email)
        messages.append(_message_to_summary(account_email, index, message, attachments))
    save_last_list(account_email, messages)
    return messages


def list_folders(
    *,
    account_email: Optional[str] = None,
) -> list[FolderInfo]:
    access_token, account = auth.get_access_token(account_email)
    select = "id,displayName,parentFolderId,childFolderCount,totalItemCount,unreadItemCount"

    def fetch(path: str, depth: int) -> list[FolderInfo]:
        response = graph.get_json(
            path,
            access_token,
            params={
                "$top": "100",
                "$select": select,
            },
        )
        folders = []
        for folder in response.get("value") or []:
            child_count = int(folder.get("childFolderCount") or 0)
            info = FolderInfo(
                account=account.email,
                id=folder.get("id") or "",
                display_name=folder.get("displayName") or "",
                parent_folder_id=folder.get("parentFolderId") or "",
                depth=depth,
                child_folder_count=child_count,
                total_item_count=int(folder.get("totalItemCount") or 0),
                unread_item_count=int(folder.get("unreadItemCount") or 0),
            )
            folders.append(info)
            if child_count and info.id:
                folder_id = graph.quote_path_segment(info.id)
                folders.extend(fetch(f"/me/mailFolders/{folder_id}/childFolders", depth + 1))
        return folders

    return fetch("/me/mailFolders", 0)


def _addresses(recipients: list[dict[str, Any]]) -> list[str]:
    addresses = []
    for recipient in recipients or []:
        email = (recipient.get("emailAddress") or {}).get("address")
        if email:
            addresses.append(email)
    return addresses


def _attachment_type(value: str) -> str:
    prefix = "#microsoft.graph."
    if value.startswith(prefix):
        return value[len(prefix) :]
    return value or "attachment"


def _attachment_to_info(attachment: dict[str, Any]) -> AttachmentInfo:
    attachment_type = _attachment_type(attachment.get("@odata.type") or "")
    name = _safe_attachment_name(
        attachment.get("name") or "",
        fallback=attachment.get("id") or "attachment",
    )
    content_type = attachment.get("contentType") or ""
    is_smime_signature = _is_smime_signature_attachment(name, content_type)
    is_smime_encrypted = _is_smime_encrypted_attachment(name, content_type)
    return AttachmentInfo(
        id=attachment.get("id") or "",
        name=name,
        content_type=content_type,
        size=int(attachment.get("size") or 0),
        is_inline=bool(attachment.get("isInline")),
        attachment_type=attachment_type,
        can_save=(
            attachment_type == "fileAttachment"
            and isinstance(attachment.get("contentBytes"), str)
            and not is_smime_signature
            and not is_smime_encrypted
        ),
        is_smime_signature=is_smime_signature,
        is_smime_encrypted=is_smime_encrypted,
    )


def list_attachments(message_id: str, account_email: Optional[str] = None) -> list[AttachmentInfo]:
    access_token, _account = auth.get_access_token(account_email)
    message_path_id = graph.quote_path_segment(message_id)
    response = graph.get_json(
        f"/me/messages/{message_path_id}/attachments",
        access_token,
    )
    return [_attachment_to_info(attachment) for attachment in response.get("value") or []]


def get_message(message_id: str, account_email: Optional[str] = None) -> MessageDetail:
    access_token, account = auth.get_access_token(account_email)
    message_path_id = graph.quote_path_segment(message_id)
    select = ",".join(
        [
            "id",
            "subject",
            "from",
            "toRecipients",
            "ccRecipients",
            "receivedDateTime",
            "internetMessageId",
            "body",
            "bodyPreview",
            "hasAttachments",
        ]
    )
    message = graph.get_json(
        f"/me/messages/{message_path_id}",
        access_token,
        params={"$select": select},
    )
    sender = ((message.get("from") or {}).get("emailAddress") or {})
    body = message.get("body") or {}
    attachments = list_attachments(message.get("id") or message_id, account_email=account.email) if message.get("hasAttachments") else []
    _has_user_attachments, smime_signed, smime_encrypted = _attachment_flags(attachments)
    user_attachments = [
        attachment
        for attachment in attachments
        if not attachment.is_smime_signature and not attachment.is_smime_encrypted
    ]
    return MessageDetail(
        account=account.email,
        id=message.get("id") or message_id,
        subject=message.get("subject") or "",
        from_name=sender.get("name") or "",
        from_address=sender.get("address") or "",
        to_addresses=_addresses(message.get("toRecipients") or []),
        cc_addresses=_addresses(message.get("ccRecipients") or []),
        received_date_time=message.get("receivedDateTime") or "",
        internet_message_id=message.get("internetMessageId") or "",
        body_content_type=body.get("contentType") or "",
        body_content=body.get("content") or "",
        body_preview=message.get("bodyPreview") or "",
        has_attachments=bool(message.get("hasAttachments")),
        attachment_count=len(user_attachments),
        attachments=user_attachments,
        smime_signed=smime_signed,
        smime_encrypted=smime_encrypted,
    )


def get_message_mime(message_id: str, account_email: Optional[str] = None) -> tuple[bytes, str]:
    access_token, account = auth.get_access_token(account_email)
    message_path_id = graph.quote_path_segment(message_id)
    return (
        graph.get_bytes(
            f"/me/messages/{message_path_id}/$value",
            access_token,
            accept="message/rfc822",
        ),
        account.email,
    )


def _operation_summary(message: MessageDetail, destination_folder: Optional[str] = None) -> MessageOperationResult:
    return MessageOperationResult(
        account=message.account,
        id=message.id,
        subject=message.subject,
        from_address=message.from_address,
        destination_folder=destination_folder,
    )


def delete_message(reference: str, account_email: Optional[str] = None) -> MessageOperationResult:
    message_id, resolved_account = resolve_message_reference(reference, account_email)
    message = get_message(message_id, account_email=resolved_account)
    access_token, account = auth.get_access_token(resolved_account)
    message_path_id = graph.quote_path_segment(message.id)
    graph.delete_empty(f"/me/messages/{message_path_id}", access_token)
    remove_from_last_list(account.email, message.id)
    return _operation_summary(message)


def move_message(
    reference: str,
    destination_folder: str,
    destination_folder_id: Optional[str] = None,
    account_email: Optional[str] = None,
) -> MessageOperationResult:
    folder_id = destination_folder_id or normalize_folder(destination_folder)
    message_id, resolved_account = resolve_message_reference(reference, account_email)
    message = get_message(message_id, account_email=resolved_account)
    access_token, account = auth.get_access_token(resolved_account)
    message_path_id = graph.quote_path_segment(message.id)
    response = graph.post_json(
        f"/me/messages/{message_path_id}/move",
        access_token,
        body={"destinationId": folder_id},
    )
    moved_id = response.get("id") or message.id
    remove_from_last_list(account.email, message.id)
    return MessageOperationResult(
        account=message.account,
        id=moved_id,
        subject=response.get("subject") or message.subject,
        from_address=message.from_address,
        destination_folder=folder_id,
    )


def mark_message(
    reference: str,
    *,
    is_read: bool,
    account_email: Optional[str] = None,
) -> MessageOperationResult:
    message_id, resolved_account = resolve_message_reference(reference, account_email)
    message = get_message(message_id, account_email=resolved_account)
    access_token, account = auth.get_access_token(resolved_account)
    message_path_id = graph.quote_path_segment(message.id)
    graph.patch_json(
        f"/me/messages/{message_path_id}",
        access_token,
        body={"isRead": is_read},
    )
    update_last_list_read_state(account.email, message.id, is_read)
    return _operation_summary(message)


def _safe_attachment_name(name: str, fallback: str) -> str:
    cleaned = Path(name or fallback).name.strip()
    if not cleaned or cleaned in {".", ".."}:
        cleaned = fallback
    return cleaned.replace("\x00", "_")


def _unique_path(directory: Path, filename: str, overwrite: bool) -> Path:
    target = directory / filename
    if overwrite or not target.exists():
        return target

    stem = target.stem
    suffix = target.suffix
    for counter in range(1, 1000):
        candidate = directory / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
    raise ValueError(f"Could not choose a unique filename for {filename}")


def save_attachments(
    reference: str,
    *,
    destination: str,
    overwrite: bool = False,
    include_inline: bool = False,
    decrypt: bool = False,
    verify_smime: bool = False,
    account_email: Optional[str] = None,
) -> SaveAttachmentsResult:
    message_id, resolved_account = resolve_message_reference(reference, account_email)
    message = get_message(message_id, account_email=resolved_account)
    access_token, account = auth.get_access_token(resolved_account)

    destination_path = Path(destination).expanduser()
    destination_path.mkdir(parents=True, exist_ok=True)
    if not destination_path.is_dir():
        raise ValueError(f"Attachment destination is not a directory: {destination}")

    if decrypt:
        mime_bytes, _mime_account = get_message_mime(message.id, account_email=account.email)
        decrypt_result = smime.decrypt_mime_bytes(mime_bytes, account_email=account.email)
        if not decrypt_result.decrypted:
            raise ValueError(decrypt_result.error or "S/MIME decryption failed.")
        clear_bytes = Path(decrypt_result.decrypted_path).read_bytes()
        if verify_smime:
            verify_result = smime.verify_signed_mime_bytes(clear_bytes, account_email=account.email)
            if not verify_result.verified:
                raise ValueError(verify_result.error or "S/MIME signature verification failed.")
            clear_bytes = Path(verify_result.verified_path).read_bytes()
        saved = [
            SavedAttachment(name=name, path=str(path), size=size)
            for name, path, size in mime.save_attachments(
                clear_bytes,
                destination=destination_path,
                unique_path=_unique_path,
                safe_name=_safe_attachment_name,
                overwrite=overwrite,
            )
        ]
        return SaveAttachmentsResult(
            account=account.email,
            id=message.id,
            subject=message.subject,
            saved=saved,
            skipped=0,
        )

    message_path_id = graph.quote_path_segment(message.id)
    response = graph.get_json(
        f"/me/messages/{message_path_id}/attachments",
        access_token,
    )

    saved = []
    skipped = 0
    for index, attachment in enumerate(response.get("value") or [], start=1):
        filename = _safe_attachment_name(
            attachment.get("name") or "",
            fallback=f"attachment-{index}",
        )
        content_type = attachment.get("contentType") or ""
        if _is_smime_signature_attachment(filename, content_type) or _is_smime_encrypted_attachment(filename, content_type):
            skipped += 1
            continue
        if attachment.get("@odata.type") != "#microsoft.graph.fileAttachment":
            skipped += 1
            continue
        if attachment.get("isInline") and not include_inline:
            skipped += 1
            continue
        content = attachment.get("contentBytes")
        if not isinstance(content, str) or not content:
            skipped += 1
            continue

        target = _unique_path(destination_path, filename, overwrite=overwrite)
        try:
            data = base64.b64decode(content, validate=True)
        except ValueError as exc:
            raise ValueError(f"Attachment content is not valid base64: {filename}") from exc
        target.write_bytes(data)
        saved.append(
            SavedAttachment(
                name=filename,
                path=str(target),
                size=len(data),
            )
        )

    return SaveAttachmentsResult(
        account=account.email,
        id=message.id,
        subject=message.subject,
        saved=saved,
        skipped=skipped,
    )
