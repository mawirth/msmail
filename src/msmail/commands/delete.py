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


def _print_summary(result: mail.MessageOperationResult) -> None:
    console.print(f"From: {result.from_address}")
    console.print(f"Subject: {result.subject}")


def delete_message(
    reference: Optional[str] = typer.Argument(
        None,
        metavar="INDEX_OR_ID",
        help="Message number from last list or Graph message ID.",
    ),
    message_id: Optional[str] = typer.Option(None, "--id", help="Graph message ID."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Delete without interactive confirmation."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
) -> None:
    if bool(reference) == bool(message_id):
        raise typer.BadParameter("Use either INDEX_OR_ID or --id.")
    if json_output and not yes:
        raise typer.BadParameter("--json requires --yes for delete.")

    selected = message_id or reference or ""
    try:
        resolved_id, resolved_account = mail.resolve_message_reference(
            selected,
            account_email=account,
        )
        preview = mail.get_message(resolved_id, account_email=resolved_account)
    except (ValueError, graph.GraphError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if not json_output:
        console.print("[bold]Message ready to delete[/bold]")
        _print_summary(
            mail.MessageOperationResult(
                account=preview.account,
                id=preview.id,
                subject=preview.subject,
                from_address=preview.from_address,
            )
        )

    if not yes and not Confirm.ask("Delete this message?", default=False):
        console.print("[yellow]Delete cancelled.[/yellow]")
        raise typer.Exit()

    try:
        result = mail.delete_message(resolved_id, account_email=resolved_account)
    except (ValueError, graph.GraphError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if json_output:
        console.print_json(json.dumps(asdict(result)))
        return

    console.print("[green]Message deleted.[/green]")
