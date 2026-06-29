from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from msmail.core import graph
from msmail.core import mail
from msmail.core import mime
from msmail.core import render
from msmail.core import smime


console = Console()


def _smime_metadata(message: mail.MessageDetail) -> dict[str, object]:
    return {
        "signed": message.smime_signed,
        "encrypted": message.smime_encrypted,
        "known": message.attachment_details_loaded,
        "decrypted": None,
        "verified": None,
        "trusted": None,
        "error": None,
    }


def _print_smime_status(
    message: mail.MessageDetail,
    smime_result: smime.VerifyResult | None,
    decrypt_result: smime.DecryptResult | None,
) -> None:
    metadata = _smime_metadata(message)
    decrypt_note = ""
    if decrypt_result is not None:
        if decrypt_result.decrypted:
            decrypt_note = ", decrypted"
        else:
            console.print("[bold]S/MIME:[/bold] encrypted, decrypt failed")
            if decrypt_result.error:
                console.print(f"[yellow]{decrypt_result.error}[/yellow]")
            return

    if smime_result is not None:
        if smime_result.verified:
            console.print(f"[bold]S/MIME:[/bold] signed, trusted{decrypt_note}")
            if smime_result.signer_certificate:
                console.print(f"[bold]Signer:[/bold] {smime_result.signer_certificate.subject}")
                console.print(f"[bold]Issuer:[/bold] {smime_result.signer_certificate.issuer}")
        elif smime_result.signed:
            console.print(f"[bold]S/MIME:[/bold] signed, invalid or untrusted{decrypt_note}")
            if smime_result.error:
                console.print(f"[yellow]{smime_result.error}[/yellow]")
        else:
            console.print(f"[bold]S/MIME:[/bold] not signed{decrypt_note}")
        return

    if metadata["signed"] and metadata["encrypted"]:
        suffix = decrypt_note or " (use --decrypt --verify-smime)"
        console.print(f"[bold]S/MIME:[/bold] signed, encrypted{suffix}")
    elif metadata["signed"]:
        console.print("[bold]S/MIME:[/bold] signed (use --verify-smime)")
    elif metadata["encrypted"]:
        console.print("[bold]S/MIME:[/bold] encrypted")
    elif not metadata["known"]:
        console.print("[bold]S/MIME:[/bold] unknown (use --attachment-details)")
    else:
        console.print("[bold]S/MIME:[/bold] none")


def _render_body(message: mail.MessageDetail, raw_html: bool) -> str:
    if raw_html:
        return message.body_content
    if message.body_content_type.lower() == "html":
        return render.html_to_text(message.body_content)
    return render.unwrap_safelinks_in_text(message.body_content)


def _print_message(message: mail.MessageDetail, raw_html: bool) -> None:
    console.print(f"[bold]From:[/bold] {message.from_name} <{message.from_address}>")
    console.print(f"[bold]To:[/bold] {', '.join(message.to_addresses)}")
    if message.cc_addresses:
        console.print(f"[bold]Cc:[/bold] {', '.join(message.cc_addresses)}")
    console.print(f"[bold]Date:[/bold] {message.received_date_time}")
    console.print(f"[bold]Subject:[/bold] {message.subject}")
    if message.attachment_details_loaded:
        console.print(f"[bold]Attachments:[/bold] {message.attachment_count}")
    else:
        console.print("[bold]Attachments:[/bold] yes")
    for attachment in message.attachments:
        inline = " inline" if attachment.is_inline else ""
        size = f", {attachment.size} bytes" if attachment.size else ""
        console.print(f"  - {attachment.name} ({attachment.attachment_type}{inline}{size})")
    console.print("")
    console.print(_render_body(message, raw_html))


def read_message(
    reference: Optional[str] = typer.Argument(
        None,
        metavar="INDEX_OR_ID",
        help="Message number from last list or Graph message ID.",
    ),
    message_id: Optional[str] = typer.Option(None, "--id", help="Graph message ID."),
    raw_html: bool = typer.Option(False, "--html", help="Show raw HTML body."),
    verify_smime: bool = typer.Option(False, "--verify-smime", help="Verify S/MIME signature from raw MIME."),
    decrypt_smime: bool = typer.Option(False, "--decrypt", help="Decrypt S/MIME encrypted MIME before rendering."),
    attachment_details: bool = typer.Option(
        False,
        "--attachment-details",
        help="Fetch and print attachment names and S/MIME metadata.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
) -> None:
    if bool(reference) == bool(message_id):
        raise typer.BadParameter("Use either INDEX_OR_ID or --id.")

    try:
        resolved_id, resolved_account = mail.resolve_message_reference(
            message_id or reference or "",
            account_email=account,
        )
        message = mail.get_message(
            resolved_id,
            account_email=resolved_account,
            include_attachment_details=attachment_details or verify_smime or decrypt_smime,
        )
        smime_result = None
        decrypt_result = None
        decrypted_body = None
        decrypted_body_type = None
        decrypted_attachments = None
        mime_body = None
        mime_body_type = None
        mime_attachments = None
        should_read_signed_mime = message.smime_signed and not message.smime_encrypted
        if verify_smime or decrypt_smime or should_read_signed_mime:
            mime_bytes, mime_account = mail.get_message_mime(
                resolved_id,
                account_email=resolved_account,
            )
        if decrypt_smime:
            decrypt_result = smime.decrypt_mime_bytes(
                mime_bytes,
                account_email=mime_account,
            )
            if decrypt_result.decrypted:
                decrypted_bytes = Path(decrypt_result.decrypted_path).read_bytes()
                body_source = decrypted_bytes
                if verify_smime:
                    smime_result = smime.verify_signed_mime_bytes(
                        decrypted_bytes,
                        account_email=mime_account,
                    )
                    if smime_result.verified:
                        body_source = Path(smime_result.verified_path).read_bytes()
                decrypted_body, decrypted_body_type, decrypted_attachments = mime.body_from_mime(
                    body_source,
                    raw_html,
                )
        elif verify_smime:
            smime_result = smime.verify_signed_mime_bytes(
                mime_bytes,
                account_email=mime_account,
            )
            body_source = Path(smime_result.verified_path).read_bytes() if smime_result.verified else mime_bytes
            mime_body, mime_body_type, mime_attachments = mime.body_from_mime(
                body_source,
                raw_html,
            )
        elif should_read_signed_mime:
            mime_body, mime_body_type, mime_attachments = mime.body_from_mime(
                mime_bytes,
                raw_html,
            )
    except (RuntimeError, ValueError, graph.GraphError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if json_output:
        data = asdict(message)
        data["rendered_body"] = (
            decrypted_body
            if decrypted_body is not None
            else mime_body
            if mime_body is not None
            else _render_body(message, raw_html)
        )
        data["smime"] = _smime_metadata(message)
        if decrypt_result is not None:
            data["smime"].update(
                {
                    "decrypted": decrypt_result.decrypted,
                    "decrypt_error": decrypt_result.error,
                    "decrypted_path": decrypt_result.decrypted_path if decrypt_result.decrypted else None,
                }
            )
        if smime_result is not None:
            data["smime"].update(
                {
                    "signed": smime_result.signed,
                    "verified": smime_result.verified,
                    "trusted": smime_result.verified,
                    "error": smime_result.error,
                    "verified_path": smime_result.verified_path,
                    "signer_path": smime_result.signer_path,
                    "signer_certificate": asdict(smime_result.signer_certificate)
                    if smime_result.signer_certificate
                    else None,
                }
            )
        if decrypted_body is not None:
            data["decrypted_body_content_type"] = decrypted_body_type
            data["decrypted_attachment_names"] = decrypted_attachments or []
        if mime_body is not None:
            data["mime_body_content_type"] = mime_body_type
            data["mime_attachment_names"] = mime_attachments or []
        console.print_json(json.dumps(data))
        return

    _print_smime_status(message, smime_result, decrypt_result)
    if decrypted_body is not None:
        console.print(f"[bold]From:[/bold] {message.from_name} <{message.from_address}>")
        console.print(f"[bold]To:[/bold] {', '.join(message.to_addresses)}")
        if message.cc_addresses:
            console.print(f"[bold]Cc:[/bold] {', '.join(message.cc_addresses)}")
        console.print(f"[bold]Date:[/bold] {message.received_date_time}")
        console.print(f"[bold]Subject:[/bold] {message.subject}")
        console.print(f"[bold]Encrypted attachments:[/bold] {len(decrypted_attachments or [])}")
        for attachment in decrypted_attachments or []:
            console.print(f"  - {attachment}")
        console.print("")
        console.print(decrypted_body)
        return
    if mime_body is not None:
        console.print(f"[bold]From:[/bold] {message.from_name} <{message.from_address}>")
        console.print(f"[bold]To:[/bold] {', '.join(message.to_addresses)}")
        if message.cc_addresses:
            console.print(f"[bold]Cc:[/bold] {', '.join(message.cc_addresses)}")
        console.print(f"[bold]Date:[/bold] {message.received_date_time}")
        console.print(f"[bold]Subject:[/bold] {message.subject}")
        console.print(f"[bold]MIME attachments:[/bold] {len(mime_attachments or [])}")
        for attachment in mime_attachments or []:
            console.print(f"  - {attachment}")
        console.print("")
        console.print(mime_body)
        return
    _print_message(message, raw_html)
