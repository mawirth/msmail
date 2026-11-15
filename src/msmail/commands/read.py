from __future__ import annotations

import json
from dataclasses import asdict, replace
from typing import Optional

import typer
from rich.text import Text

from msmail.console import console
from msmail.core import mail
from msmail.core import eml
from msmail.core import mime
from msmail.core import render
from msmail.core import smime
from msmail.core.errors import MsmailError


def _smime_metadata(message: mail.MessageDetail) -> dict[str, object]:
    return {
        "signed": message.smime_signed,
        "encrypted": message.smime_encrypted,
        "known": message.attachment_details_loaded,
        "decrypted": None,
        "verified": None,
        "trusted": None,
        "sender_matches": None,
        "signature_valid": None,
        "certificate_trusted": None,
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
                console.print(decrypt_result.error, markup=False)
            return

    if smime_result is not None:
        if smime_result.verified:
            if smime_result.trusted:
                status = "signed, trusted, sender matches"
            elif smime_result.sender_matches is False:
                status = "signed, sender mismatch (not trusted)"
            else:
                status = "signature valid, sender not checked"
            console.print(f"[bold]S/MIME:[/bold] {status}{decrypt_note}")
            if smime_result.signer_certificate:
                _print_field("Signer", smime_result.signer_certificate.subject)
                _print_field("Issuer", smime_result.signer_certificate.issuer)
            if smime_result.error:
                console.print(smime_result.error, markup=False)
        elif smime_result.signed:
            status = "signature valid, certificate not trusted" if smime_result.signature_valid else (
                "signature invalid" if smime_result.signature_valid is False else "signature not checked"
            )
            console.print(f"[bold]S/MIME:[/bold] signed, {status}{decrypt_note}")
            if smime_result.error:
                console.print(smime_result.error, markup=False)
        else:
            console.print(f"[bold]S/MIME:[/bold] not signed{decrypt_note}")
        return

    if metadata["signed"] and metadata["encrypted"]:
        suffix = decrypt_note or " (use --decrypt --verify-smime)"
        console.print(f"[bold]S/MIME:[/bold] signed, encrypted{suffix}")
    elif metadata["signed"]:
        console.print("[bold]S/MIME:[/bold] signed (use --verify-smime)")
    elif metadata["encrypted"]:
        console.print(f"[bold]S/MIME:[/bold] encrypted{decrypt_note}")
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


def _print_field(label: str, value: str) -> None:
    console.print(Text.assemble((f"{label}: ", "bold"), render.display_text(value)))


def _print_headers(message: mail.MessageDetail) -> None:
    _print_field("From", f"{message.from_name} <{message.from_address}>")
    _print_field("To", ', '.join(message.to_addresses))
    if message.cc_addresses:
        _print_field("Cc", ', '.join(message.cc_addresses))
    if isinstance(message, eml.LocalMessageDetail):
        _print_field("Date (EML header; receipt time unknown)", message.date_header or "unknown")
    else:
        _print_field("Date", message.received_date_time or "")
    _print_field("Subject", message.subject)


def _print_message(message: mail.MessageDetail, raw_html: bool) -> None:
    _print_headers(message)
    if message.attachment_details_loaded:
        console.print(f"[bold]Attachments:[/bold] {message.attachment_count}")
    else:
        console.print("[bold]Attachments:[/bold] yes")
    for attachment in message.attachments:
        inline = " inline" if attachment.is_inline else ""
        size = f", {attachment.size} bytes" if attachment.size else ""
        console.print(render.display_text(f"  - {attachment.name} ({attachment.attachment_type}{inline}{size})"), markup=False)
    console.print("")
    console.print(render.display_text(_render_body(message, raw_html)), markup=False)


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
    file: Optional[str] = typer.Option(None, "--file", help="Read a local EML file without accessing the mailbox."),
) -> None:
    if sum(value is not None for value in (reference, message_id, file)) != 1:
        raise typer.BadParameter("Use exactly one of INDEX_OR_ID, --id or --file.")
    if file is not None and account is not None and not account.strip():
        raise typer.BadParameter("--account must not be empty.")

    mime_bytes = None
    if file is not None:
        message, mime_bytes = eml.read_file(file, raw_html=raw_html, account=account)
        mime_account = account
    else:
        resolved_id, resolved_account = mail.resolve_message_reference(
            mail.MessageId(message_id) if message_id is not None else reference or "",
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
    if mime_bytes is None and (verify_smime or decrypt_smime or should_read_signed_mime):
        mime_bytes, mime_account = mail.get_message_mime(
            resolved_id,
            account_email=resolved_account,
        )
    # Local files do not implicitly use the currently logged-in mailbox.
    verification_options = {"system_trust_only": True} if file is not None and account is None else {}
    body_source = None
    if decrypt_smime and (file is None or message.smime_encrypted):
        try:
            if file is not None and not account:
                raise ValueError("Decrypting a local EML requires --account for its certificate and private key.")
            decrypt_result = smime.decrypt_mime_bytes(
                mime_bytes,
                account_email=mime_account,
            )
        except (ValueError, MsmailError) as exc:
            if file is None:
                raise
            decrypt_result = smime.DecryptResult(False, "", "", error=str(exc))
        if decrypt_result.decrypted:
            decrypted_bytes = decrypt_result.data or b""
            body_source = decrypted_bytes
            if file is not None:
                signed, _encrypted = mime.smime_flags(eml.parse(decrypted_bytes))
                message = replace(message, smime_signed=signed)
            if verify_smime and (file is None or message.smime_signed):
                smime_result = smime.verify_signed_mime_bytes(
                    decrypted_bytes,
                    account_email=mime_account,
                    expected_sender=message.from_address,
                    **verification_options,
                )
                if smime_result.verified or smime_result.signature_valid:
                    body_source = smime_result.data or body_source
            elif file is not None and message.smime_signed and "pkcs7-mime" in mime.parse_message(decrypted_bytes).get_content_type():
                body_source = smime.extract_signed_content(decrypted_bytes)
            decrypted_body, decrypted_body_type, decrypted_attachments = mime.body_from_mime(
                body_source,
                raw_html,
            )
    elif verify_smime and (file is None or message.smime_signed):
        smime_result = smime.verify_signed_mime_bytes(
            mime_bytes,
            account_email=mime_account,
            expected_sender=message.from_address,
            **verification_options,
        )
        body_source = (smime_result.data or mime_bytes) if smime_result.verified or smime_result.signature_valid else mime_bytes
        mime_body, mime_body_type, mime_attachments = mime.body_from_mime(
            body_source,
            raw_html,
        )
    elif should_read_signed_mime:
        body_source = mime_bytes
        if "pkcs7-mime" in mime.parse_message(mime_bytes).get_content_type():
            body_source = smime.extract_signed_content(mime_bytes)
        mime_body, mime_body_type, mime_attachments = mime.body_from_mime(
            body_source,
            raw_html,
        )

    if file is not None and body_source is not None:
        encrypted = message.smime_encrypted
        signed = message.smime_signed
        message = eml.with_content(message, body_source, raw_html=raw_html)
        message = replace(message, smime_encrypted=encrypted,
                          smime_signed=smime_result.signed if smime_result else (signed or message.smime_signed))

    verification_note = None
    if file is not None and verify_smime and message.smime_encrypted and not (decrypt_result and decrypt_result.decrypted):
        verification_note = "Signature not checked: decrypt the EML first with --decrypt --account."

    if json_output:
        data = asdict(message)
        data["rendered_body"] = (
            decrypted_body
            if decrypted_body is not None
            else mime_body
            if mime_body is not None
            else _render_body(message, raw_html)
        )
        if file is not None:
            # --html selects the display/body_content representation; printable
            # local JSON always supplies plain text in rendered_body.
            data["rendered_body"] = _render_body(message, False)
        data["rendered_body"] = render.display_text(data["rendered_body"])
        data["smime"] = _smime_metadata(message)
        if verification_note:
            data["smime"]["error"] = verification_note
        if decrypt_result is not None:
            data["smime"].update(
                {
                    "decrypted": decrypt_result.decrypted,
                    "decrypt_error": decrypt_result.error,
                    # Empty unless --output-dir kept the working files around.
                    "decrypted_path": (decrypt_result.decrypted_path or None) if decrypt_result.decrypted else None,
                }
            )
        if smime_result is not None:
            data["smime"].update(
                {
                    "signed": smime_result.signed,
                    "verified": smime_result.verified,
                    "trusted": smime_result.trusted,
                    "sender_matches": smime_result.sender_matches,
                    "signature_valid": smime_result.signature_valid,
                    "certificate_trusted": smime_result.certificate_trusted,
                    "error": smime_result.error,
                    "verified_path": smime_result.verified_path or None,
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
    if verification_note:
        console.print(verification_note)
    if file is not None:
        _print_message(message, raw_html)
        return
    if decrypted_body is not None:
        _print_headers(message)
        console.print(f"[bold]Encrypted attachments:[/bold] {len(decrypted_attachments or [])}")
        for attachment in decrypted_attachments or []:
            console.print(f"  - {attachment}", markup=False)
        console.print("")
        console.print(render.display_text(decrypted_body), markup=False)
        return
    if mime_body is not None:
        _print_headers(message)
        console.print(f"[bold]MIME attachments:[/bold] {len(mime_attachments or [])}")
        for attachment in mime_attachments or []:
            console.print(f"  - {attachment}", markup=False)
        console.print("")
        console.print(render.display_text(mime_body), markup=False)
        return
    _print_message(message, raw_html)
