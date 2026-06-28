from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

import typer
from rich.console import Console

from msmail.core import graph
from msmail.core import mail


console = Console()


def save_attachments(
    reference: Optional[str] = typer.Argument(
        None,
        metavar="INDEX_OR_ID",
        help="Message number from last list or Graph message ID.",
    ),
    message_id: Optional[str] = typer.Option(None, "--id", help="Graph message ID."),
    destination: str = typer.Option(".", "--to", help="Directory to save attachments into."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing files."),
    include_inline: bool = typer.Option(False, "--inline", help="Also save inline file attachments such as embedded images."),
    decrypt: bool = typer.Option(False, "--decrypt", help="Decrypt S/MIME message and save encrypted-container attachments."),
    verify_smime: bool = typer.Option(False, "--verify-smime", help="Verify decrypted S/MIME signature before saving."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
) -> None:
    if bool(reference) == bool(message_id):
        raise typer.BadParameter("Use either INDEX_OR_ID or --id.")

    try:
        result = mail.save_attachments(
            message_id or reference or "",
            destination=destination,
            overwrite=overwrite,
            include_inline=include_inline,
            decrypt=decrypt,
            verify_smime=verify_smime,
            account_email=account,
        )
    except (ValueError, graph.GraphError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if json_output:
        console.print_json(json.dumps(asdict(result)))
        return

    if not result.saved:
        console.print("[yellow]No file attachments saved.[/yellow]")
    for saved in result.saved:
        console.print(f"[green]Saved[/green] {saved.name}: {saved.path}")
    if result.skipped:
        console.print(f"[yellow]Skipped {result.skipped} unsupported or inline attachment(s).[/yellow]")
