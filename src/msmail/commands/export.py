from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

import typer

from msmail.console import console
from msmail.core import mail


def export_message(
    reference: Optional[str] = typer.Argument(
        None,
        metavar="INDEX_OR_ID",
        help="Message number from last list or Graph message ID.",
    ),
    message_id: Optional[str] = typer.Option(None, "--id", help="Graph message ID."),
    destination: str = typer.Option(..., "--to", help="Destination .eml file (including filename)."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite an existing file."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
) -> None:
    """Export one complete message as an .eml file, including attachments."""
    if bool(reference) == bool(message_id):
        raise typer.BadParameter("Use either INDEX_OR_ID or --id.")

    result = mail.export_message(
        mail.MessageId(message_id) if message_id is not None else reference or "",
        destination=destination,
        overwrite=overwrite,
        account_email=account,
    )
    if json_output:
        console.print_json(json.dumps(asdict(result)))
    else:
        console.print(f"Saved message: {result.path} ({result.size} bytes)", markup=False)
