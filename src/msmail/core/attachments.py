"""Shared attachment filtering and filesystem output for Graph and MIME."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class FileAttachment:
    name: str
    content_type: str
    # MIME provides bytes; Graph provides base64 text. None means unsupported.
    data: bytes | str | None
    is_inline: bool = False


@dataclass(frozen=True)
class SavedAttachment:
    name: str
    path: str
    size: int


def is_smime_signature(name: str, content_type: str) -> bool:
    normalized_name = name.lower()
    normalized_type = content_type.lower()
    if (
        "pkcs7-signature" in normalized_type
        or normalized_type == "multipart/signed"
        # An opaque signature: application/pkcs7-mime; smime-type=signed-data.
        or "signed-data" in normalized_type
    ):
        return True
    # smime.p7m is deliberately not matched by name. It carries either
    # encrypted data or an opaque signature, and only the content type tells
    # the two apart; matching it here marked every encrypted message as signed.
    return normalized_name == "smime.p7s"


def is_smime_encrypted(name: str, content_type: str) -> bool:
    normalized_name = name.lower()
    normalized_type = content_type.lower()
    if "signed" in normalized_type:
        # multipart/signed and smime-type=signed-data are not encrypted.
        return False
    if "pkcs7-mime" in normalized_type:
        return True
    return normalized_name in {"smime.p7m", "smime.p7c"}


def safe_name(name: str, fallback: str) -> str:
    cleaned = Path(name or fallback).name.strip()
    if not cleaned or cleaned in {".", ".."}:
        cleaned = fallback
    return cleaned.replace("\x00", "_")


def unique_path(directory: Path, filename: str, overwrite: bool) -> Path:
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


def save(
    attachments: Iterable[FileAttachment], *, destination: Path,
    include_inline: bool = False, overwrite: bool = False,
) -> tuple[list[SavedAttachment], int]:
    saved = []
    skipped = 0
    for index, attachment in enumerate(attachments, start=1):
        filename = safe_name(attachment.name, fallback=f"attachment-{index}")
        if (
            attachment.data is None
            or (attachment.is_inline and not include_inline)
            or is_smime_signature(filename, attachment.content_type)
            or is_smime_encrypted(filename, attachment.content_type)
        ):
            skipped += 1
            continue
        data = attachment.data
        if isinstance(data, str):
            try:
                data = base64.b64decode(data, validate=True)
            except ValueError as exc:
                raise ValueError(f"Attachment content is not valid base64: {filename}") from exc
        target = unique_path(destination, filename, overwrite)
        target.write_bytes(data)
        saved.append(SavedAttachment(filename, str(target), len(data)))
    return saved, skipped
