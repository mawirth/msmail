from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Confirm

from msmail.core import graph
from msmail.core import mail


console = Console()


def move_message(
    reference: Optional[str] = typer.Argument(
        None,
        metavar="INDEX_OR_ID",
        help="Message number from last list or Graph message ID.",
    ),
    folder: Optional[str] = typer.Option(None, "--folder", "-f", help="Destination folder alias."),
    folder_id: Optional[str] = typer.Option(None, "--folder-id", help="Destination Graph mailFolder ID."),
    message_id: Optional[str] = typer.Option(None, "--id", help="Graph message ID."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Move without interactive confirmation."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
) -> None:
    if bool(reference) == bool(message_id):
        raise typer.BadParameter("Use either INDEX_OR_ID or --id.")
    if bool(folder) == bool(folder_id):
        raise typer.BadParameter("Use either --folder or --folder-id.")
    if json_output and not yes:
        raise typer.BadParameter("--json requires --yes for move.")

    try:
        normalized_folder = folder_id or mail.normalize_folder(folder or "")
        selected = message_id or reference or ""
        resolved_id, resolved_account = mail.resolve_message_reference(
            selected,
            account_email=account,
        )
        preview = mail.get_message(resolved_id, account_email=resolved_account)
    except (ValueError, graph.GraphError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if not json_output:
        console.print("[bold]Message ready to move[/bold]")
        console.print(f"From: {preview.from_address}")
        console.print(f"Subject: {preview.subject}")
        console.print(f"Destination: {normalized_folder}")

    if not yes and not Confirm.ask("Move this message?", default=False):
        console.print("[yellow]Move cancelled.[/yellow]")
        raise typer.Exit()

    try:
        result = mail.move_message(
            resolved_id,
            destination_folder=folder or "",
            destination_folder_id=folder_id,
            account_email=resolved_account,
        )
    except (ValueError, graph.GraphError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if json_output:
        console.print_json(json.dumps(asdict(result)))
        return

    console.print(f"[green]Message moved[/green]: {result.destination_folder}")
