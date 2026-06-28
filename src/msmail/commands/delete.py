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


def _print_batch_summary(previews: list[mail.MessageDetail]) -> None:
    for index, preview in enumerate(previews, start=1):
        console.print(f"{index}. {preview.from_address} | {preview.subject}")


def delete_message(
    reference: Optional[str] = typer.Argument(
        None,
        metavar="INDEX_RANGE_OR_ID",
        help="Message number/range from last list or Graph message ID.",
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

    try:
        resolved_ids, resolved_account = mail.resolve_message_references(
            message_id or reference or "",
            account_email=account,
        )
        previews = [mail.get_message(resolved_id, account_email=resolved_account) for resolved_id in resolved_ids]
    except (ValueError, graph.GraphError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if not json_output:
        if len(previews) == 1:
            console.print("[bold]Message ready to delete[/bold]")
            _print_summary(
                mail.MessageOperationResult(
                    account=previews[0].account,
                    id=previews[0].id,
                    subject=previews[0].subject,
                    from_address=previews[0].from_address,
                )
            )
        else:
            console.print(f"[bold]{len(previews)} messages ready to delete[/bold]")
            _print_batch_summary(previews)

    prompt = "Delete this message?" if len(previews) == 1 else f"Delete {len(previews)} messages?"
    if not yes and not Confirm.ask(prompt, default=False):
        console.print("[yellow]Delete cancelled.[/yellow]")
        raise typer.Exit()

    try:
        results = [mail.delete_message(resolved_id, account_email=resolved_account) for resolved_id in resolved_ids]
    except (ValueError, graph.GraphError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if json_output:
        payload = [asdict(result) for result in results]
        console.print_json(json.dumps(payload[0] if len(payload) == 1 else payload))
        return

    console.print(f"[green]{len(results)} message(s) deleted.[/green]")
