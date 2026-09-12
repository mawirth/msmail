from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

import typer
from rich.console import Console

from msmail.core import graph
from msmail.core import mail


console = Console()


def mark_message(
    reference: Optional[str] = typer.Argument(
        None,
        metavar="INDEX_RANGE_OR_ID",
        help="Message number/range from last list or Graph message ID.",
    ),
    message_id: Optional[str] = typer.Option(None, "--id", help="Graph message ID."),
    read: bool = typer.Option(False, "--read", help="Mark message as read."),
    unread: bool = typer.Option(False, "--unread", help="Mark message as unread."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
) -> None:
    if bool(reference) == bool(message_id):
        raise typer.BadParameter("Use either INDEX_OR_ID or --id.")
    if read == unread:
        raise typer.BadParameter("Use exactly one of --read or --unread.")

    try:
        resolved_ids, resolved_account = mail.resolve_message_references(
            message_id or reference or "",
            account_email=account,
        )
        results = [
            mail.mark_message(
                resolved_id,
                is_read=read,
                account_email=resolved_account,
            )
            for resolved_id in resolved_ids
        ]
    except (ValueError, graph.GraphError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if json_output:
        payload = []
        for result in results:
            data = asdict(result)
            data["is_read"] = read
            payload.append(data)
        console.print_json(json.dumps(payload[0] if len(payload) == 1 else payload))
        return

    state = "read" if read else "unread"
    console.print(f"[green]{len(results)} message(s) marked {state}.[/green]")
    if len(results) == 1:
        console.print(f"Subject: {results[0].subject}", markup=False)
