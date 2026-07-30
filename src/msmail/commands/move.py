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
        metavar="INDEX_RANGE_OR_ID",
        help="Message number/range from last list or Graph message ID.",
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
        items, resolved_account = mail.resolve_message_reference_items(
            message_id or reference or "",
            account_email=account,
        )
        resolved_ids = [item.id for item in items]
        # The preview only shows sender and subject; loading attachment details
        # would download every attachment body just to print two lines.
        previews = [
            mail.get_message(
                resolved_id,
                account_email=resolved_account,
                include_attachment_details=False,
            )
            for resolved_id in resolved_ids
        ]
    except (ValueError, graph.GraphError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if not json_output:
        if len(previews) == 1:
            console.print("[bold]Message ready to move[/bold]")
            console.print(f"From: {previews[0].from_address}")
            console.print(f"Subject: {previews[0].subject}")
        else:
            console.print(f"[bold]{len(previews)} messages ready to move[/bold]")
            for item, preview in zip(items, previews):
                label = f"#{item.index}" if item.index else preview.id
                console.print(f"{label}: {preview.from_address} | {preview.subject}")
        console.print(f"Destination: {normalized_folder}")

    prompt = "Move this message?" if len(previews) == 1 else f"Move {len(previews)} messages?"
    if not yes and not Confirm.ask(prompt, default=False):
        console.print("[yellow]Move cancelled.[/yellow]")
        raise typer.Exit()

    try:
        results = [
            mail.move_message(
                resolved_id,
                destination_folder=folder or "",
                destination_folder_id=folder_id,
                account_email=resolved_account,
            )
            for resolved_id in resolved_ids
        ]
    except (ValueError, graph.GraphError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if json_output:
        payload = [asdict(result) for result in results]
        console.print_json(json.dumps(payload[0] if len(payload) == 1 else payload))
        return

    console.print(f"[green]{len(results)} message(s) moved[/green]: {normalized_folder}")
