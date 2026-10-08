from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

import typer
from rich.prompt import Confirm

from msmail.commands.common import run_batch
from msmail.console import console
from msmail.core import mail


def _print_summary(result: mail.MessageDetail) -> None:
    console.print(f"From: {result.from_address}", markup=False)
    console.print(f"Subject: {result.subject}", markup=False)


def _print_batch_summary(items: list[mail.MessageSummary], previews: list[mail.MessageDetail]) -> None:
    for item, preview in zip(items, previews):
        label = f"#{item.index}" if item.index else preview.id
        console.print(f"{label}: {preview.from_address} | {preview.subject}", markup=False)


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

    items, resolved_account = mail.resolve_message_reference_items(
        message_id or reference or "",
        account_email=account,
    )
    # The preview only shows sender and subject; loading attachment details
    # would download every attachment body just to print two lines.
    previews = [
        mail.get_message(
            item.id,
            account_email=resolved_account,
            include_attachment_details=False,
        )
        for item in items
    ]

    if not json_output:
        if len(previews) == 1:
            console.print("[bold]Message ready to delete[/bold]")
            _print_summary(previews[0])
        else:
            console.print(f"[bold]{len(previews)} messages ready to delete[/bold]")
            _print_batch_summary(items, previews)

    prompt = "Delete this message?" if len(previews) == 1 else f"Delete {len(previews)} messages?"
    if not yes and not Confirm.ask(prompt, default=False, console=console):
        console.print("Delete cancelled.")
        raise typer.Exit()

    results = run_batch(
        previews,
        lambda message: mail.delete_message(message.id, account_email=resolved_account, message=message),
        identify=lambda message: message.id,
    )

    if json_output:
        payload = [asdict(result) for result in results]
        console.print_json(json.dumps(payload[0] if len(payload) == 1 else payload))
        return

    console.print(f"{len(results)} message(s) deleted.")
