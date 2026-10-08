from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

import typer
from rich.prompt import Confirm

from msmail.console import console
from msmail.core import compose, drafts


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

    draft = compose.draft_from_inputs(
        file=file, to=to, cc=cc, bcc=bcc, subject=subject, body=body,
        body_file=body_file, attachments=attach, html=html, sign=sign, encrypt=encrypt,
    )

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

    if not yes and not Confirm.ask("Send this message?", default=False, console=console):
        console.print("Send cancelled.")
        raise typer.Exit()

    result = drafts.create_and_send(
        draft,
        account_email=account,
        include_signature=not no_signature,
    )

    if json_output:
        console.print_json(json.dumps(asdict(result)))
        return

    console.print(f"Message sent: {result.id}")
