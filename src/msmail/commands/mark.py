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
        metavar="INDEX_OR_ID",
        help="Message number from last list or Graph message ID.",
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
        result = mail.mark_message(
            message_id or reference or "",
            is_read=read,
            account_email=account,
        )
    except (ValueError, graph.GraphError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if json_output:
        data = asdict(result)
        data["is_read"] = read
        console.print_json(json.dumps(data))
        return

    state = "read" if read else "unread"
    console.print(f"[green]Message marked {state}.[/green]")
    console.print(f"Subject: {result.subject}")
