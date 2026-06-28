from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from msmail.core import graph
from msmail.core import mail
from msmail.commands.list import render_table


console = Console()


def search_messages(
    query: str = typer.Argument(..., help="Microsoft Graph mail search query."),
    limit: int = typer.Option(25, "--limit", "-n", help="Maximum number of messages."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
) -> None:
    try:
        messages = mail.search_messages(query, limit=limit, account_email=account)
    except (RuntimeError, ValueError, graph.GraphError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if json_output:
        console.print_json(json.dumps([asdict(message) for message in messages]))
        return

    render_table(messages)


def list_folders(
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
) -> None:
    try:
        folders = mail.list_folders(account_email=account)
    except (RuntimeError, graph.GraphError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if json_output:
        console.print_json(json.dumps([asdict(folder) for folder in folders]))
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Unread", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Children", justify="right")
    table.add_column("ID")
    for folder in folders:
        table.add_row(
            folder.display_name,
            str(folder.unread_item_count),
            str(folder.total_item_count),
            str(folder.child_folder_count),
            folder.id,
        )
    console.print(table)
