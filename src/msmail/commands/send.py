from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Confirm

from msmail.core import compose, drafts, graph


console = Console()


def _with_smime(
    draft: compose.ComposeDraft,
    *,
    sign: bool,
    encrypt: bool,
) -> compose.ComposeDraft:
    if not sign and not encrypt:
        return draft
    return compose.ComposeDraft(
        to=draft.to,
        cc=draft.cc,
        bcc=draft.bcc,
        subject=draft.subject,
        body=draft.body,
        body_content_type=draft.body_content_type,
        attachments=draft.attachments,
        sign=sign or draft.sign,
        encrypt=encrypt or draft.encrypt,
    )


def send_message(
    file: Optional[str] = typer.Option(None, "--file", help="Send from a compose file."),
    to: Optional[str] = typer.Option(None, "--to", help="To recipient address list."),
    cc: Optional[str] = typer.Option(None, "--cc", help="Cc recipient address list."),
    bcc: Optional[str] = typer.Option(None, "--bcc", help="Bcc recipient address list."),
    subject: Optional[str] = typer.Option(None, "--subject", help="Message subject."),
    body: Optional[str] = typer.Option(None, "--body", help="Plain text body."),
    body_file: Optional[str] = typer.Option(None, "--body-file", help="Read the message body from a file."),
    attach: Optional[list[str]] = typer.Option(
        None,
        "--attach",
        "-a",
        help="Attach a local file. Can be used more than once.",
    ),
    html: bool = typer.Option(False, "--html", help="Treat the body input as HTML."),
    sign: bool = typer.Option(False, "--sign", help="S/MIME sign the message."),
    encrypt: bool = typer.Option(False, "--encrypt", help="S/MIME encrypt the message."),
    no_signature: bool = typer.Option(False, "--no-signature", help="Do not append the account signature."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Send without interactive confirmation."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
) -> None:
    if json_output and not yes:
        raise typer.BadParameter("--json requires --yes for direct sending.")

    try:
        direct_values = [to, cc, bcc, subject, body, body_file]
        if file:
            if any(value is not None for value in direct_values) or attach:
                raise ValueError(
                    "--file cannot be combined with recipient, subject, body, or attachment options."
                )
            draft = compose.read_compose_file(file, html=html)
        else:
            if body is not None and body_file is not None:
                raise ValueError("Use only one of --body or --body-file.")
            if not any(value is not None for value in direct_values) and not attach:
                raise ValueError("Provide --file or direct message options; direct send never opens an editor.")
            body_text = body or ""
            if body_file:
                body_text = Path(body_file).read_text(encoding="utf-8")
            template = compose.compose_template(
                to=to or "",
                cc=cc or "",
                bcc=bcc or "",
                subject=subject or "",
                attachments=attach or [],
                body=body_text,
            )
            draft = compose.parse_compose_text(template, html=html)

        draft = _with_smime(draft, sign=sign, encrypt=encrypt)

        if not json_output:
            console.print("[bold]Message ready to send[/bold]")
            console.print(f"To: {', '.join(draft.to)}", markup=False)
            if draft.cc:
                console.print(f"Cc: {', '.join(draft.cc)}", markup=False)
            if draft.bcc:
                console.print(f"Bcc: {', '.join(draft.bcc)}", markup=False)
            console.print(f"Subject: {draft.subject}", markup=False)
            if draft.attachments:
                console.print(f"Attachments: {', '.join(draft.attachments)}", markup=False)

        if not yes and not Confirm.ask("Send this message?", default=False):
            console.print("[yellow]Send cancelled.[/yellow]")
            raise typer.Exit()

        result = drafts.create_and_send(
            draft,
            account_email=account,
            include_signature=not no_signature,
        )
    except (OSError, RuntimeError, ValueError, graph.GraphError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if json_output:
        console.print_json(json.dumps(asdict(result)))
        return

    console.print(f"[green]Message sent[/green]: {result.id}")
