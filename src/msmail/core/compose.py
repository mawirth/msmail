from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
import tempfile


SEPARATOR = "---"


class ComposeCancelled(Exception):
    pass


@dataclass(frozen=True)
class ComposeDraft:
    to: list[str]
    cc: list[str]
    bcc: list[str]
    subject: str
    body: str
    body_content_type: str
    attachments: list[str]
    sign: bool
    encrypt: bool


@dataclass(frozen=True)
class ResponseDraft:
    to: list[str]
    cc: list[str]
    bcc: list[str]
    body: str
    body_content_type: str


def parse_addresses(value: str) -> list[str]:
    parts = value.replace(";", ",").split(",")
    return [part.strip() for part in parts if part.strip()]


def parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_compose_text(content: str, *, html: bool = False) -> ComposeDraft:
    header_part, body = _split_compose_parts(content, require_separator=True)
    headers = _parse_headers(header_part)

    attachments = []
    for value in headers.get("attach", []) + headers.get("attachments", []):
        attachments.extend(parse_addresses(value))

    draft = ComposeDraft(
        to=parse_addresses(",".join(headers.get("to", []))),
        cc=parse_addresses(",".join(headers.get("cc", []))),
        bcc=parse_addresses(",".join(headers.get("bcc", []))),
        subject=" ".join(headers.get("subject", [])).strip(),
        body=body,
        body_content_type="HTML" if html else "Text",
        attachments=attachments,
        sign=parse_bool((headers.get("sign", ["no"])[-1])),
        encrypt=parse_bool((headers.get("encrypt", ["no"])[-1])),
    )

    if not draft.to:
        raise ValueError("Compose draft needs at least one To recipient.")
    if not draft.subject:
        raise ValueError("Compose draft needs a Subject.")
    if not draft.body.strip():
        raise ValueError("Compose draft body is empty.")

    return draft


def read_compose_file(path: str, *, html: bool = False) -> ComposeDraft:
    return parse_compose_text(Path(path).read_text(encoding="utf-8"), html=html)


def _split_compose_parts(content: str, *, require_separator: bool = False) -> tuple[str, str]:
    """Split a compose text into its header block and its body.

    A compose file must announce the body with a '---' separator; a reply or
    forward may be body-only, in which case everything is body.
    """
    if not content.strip():
        raise ValueError("Compose content is empty.")

    if f"\n{SEPARATOR}" in content:
        header_part, body_part = content.split(f"\n{SEPARATOR}", 1)
    elif content.startswith(f"{SEPARATOR}\n"):
        header_part, body_part = "", content[len(SEPARATOR) + 1 :]
    elif require_separator:
        raise ValueError("Compose file must contain a '---' separator before the body.")
    else:
        return "", content

    return header_part, body_part.lstrip("\r\n")


def _parse_headers(header_part: str) -> dict[str, list[str]]:
    headers: dict[str, list[str]] = {}
    for raw_line in header_part.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ":" not in line:
            raise ValueError(f"Invalid compose header: {raw_line}")
        key, value = line.split(":", 1)
        headers.setdefault(key.strip().lower(), []).append(value.strip())
    return headers


def parse_response_text(
    content: str,
    *,
    require_to: bool = False,
    html: bool = False,
) -> ResponseDraft:
    header_part, body = _split_compose_parts(content)
    headers = _parse_headers(header_part)
    draft = ResponseDraft(
        to=parse_addresses(",".join(headers.get("to", []))),
        cc=parse_addresses(",".join(headers.get("cc", []))),
        bcc=parse_addresses(",".join(headers.get("bcc", []))),
        body=body,
        body_content_type="HTML" if html else "Text",
    )
    if require_to and not draft.to:
        raise ValueError("Forward draft needs at least one To recipient.")
    if not draft.body.strip():
        raise ValueError("Response body is empty.")
    return draft


def read_response_file(
    path: str,
    *,
    require_to: bool = False,
    html: bool = False,
) -> ResponseDraft:
    return parse_response_text(
        Path(path).read_text(encoding="utf-8"),
        require_to=require_to,
        html=html,
    )


def compose_template(
    *,
    to: str = "",
    cc: str = "",
    bcc: str = "",
    subject: str = "",
    attach: str = "",
    body: str = "",
) -> str:
    return "\n".join(
        [
            f"To: {to}",
            f"Cc: {cc}",
            f"Bcc: {bcc}",
            f"Subject: {subject}",
            f"Attach: {attach}",
            "Sign: no",
            "Encrypt: no",
            "",
            SEPARATOR,
            body,
        ]
    )


def response_template(
    *,
    to: str = "",
    cc: str = "",
    bcc: str = "",
    body: str = "",
    include_recipients: bool = False,
) -> str:
    lines = []
    if include_recipients:
        lines.extend(
            [
                f"To: {to}",
                f"Cc: {cc}",
                f"Bcc: {bcc}",
                "",
                SEPARATOR,
            ]
        )
    return "\n".join(lines + [body])


def editor_command() -> list[str]:
    editor = os.environ.get("EDITOR") or "nvim"
    return editor.split()


def _edit_in_editor(template: str, *, prefix: str, parse):
    """Open the template in the configured editor and parse the result.

    Returns None when the file came back unchanged; the callers decide whether
    that counts as a cancelled compose or as "nothing to update". The temporary
    file is kept on a parse error so the typed text is not lost.
    """
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".md",
        prefix=prefix,
        encoding="utf-8",
        delete=False,
    ) as handle:
        handle.write(template)
        path = handle.name

    try:
        result = subprocess.run(editor_command() + [path], check=False)
        if result.returncode != 0:
            raise ValueError(f"Editor exited with status {result.returncode}. Compose file kept at {path}")
        content = Path(path).read_text(encoding="utf-8")
        if content == template:
            Path(path).unlink(missing_ok=True)
            return None
        try:
            draft = parse(content)
        except ValueError as exc:
            raise ValueError(f"{exc} Compose file kept at {path}") from exc
        Path(path).unlink(missing_ok=True)
        return draft
    except FileNotFoundError as exc:
        raise ValueError(f"Editor not found: {editor_command()[0]}") from exc


def response_interactively(
    template: str,
    *,
    require_to: bool = False,
    html: bool = False,
) -> ResponseDraft:
    draft = _edit_in_editor(
        template,
        prefix="msmail-response-",
        parse=lambda content: parse_response_text(content, require_to=require_to, html=html),
    )
    if draft is None:
        raise ComposeCancelled("Compose cancelled; no draft created.")
    return draft


def compose_interactively(template: str, *, html: bool = False) -> ComposeDraft:
    draft = _edit_in_editor(
        template,
        prefix="msmail-",
        parse=lambda content: parse_compose_text(content, html=html),
    )
    if draft is None:
        raise ComposeCancelled("Compose cancelled; no draft created.")
    return draft


def edit_compose_interactively(template: str, *, html: bool = False) -> ComposeDraft | None:
    # An unchanged file means "leave the draft alone", not "cancel".
    return _edit_in_editor(
        template,
        prefix="msmail-draft-",
        parse=lambda content: parse_compose_text(content, html=html),
    )
