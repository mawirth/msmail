from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from msmail.core import graph
from msmail.core import mail
from msmail.commands.list import render_position, render_table, resolve_fetch


console = Console()


def search_messages(
    query: str = typer.Argument(..., help="Microsoft Graph mail search query."),
    fetch: Optional[str] = typer.Option(
        None,
        "--fetch",
        "-n",
        help="How many messages to fetch: a number, 'auto' (default) or 'all'.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
) -> None:
    try:
        state = mail.search_messages(query, fetch=resolve_fetch(fetch), account_email=account)
    except (RuntimeError, ValueError, graph.GraphError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if json_output:
        console.print_json(json.dumps([asdict(message) for message in state.messages]))
        return

    render_table(state.messages)
    render_position(state)


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
        name = f"{'  ' * folder.depth}{folder.display_name}"
        table.add_row(
            Text(name),
            str(folder.unread_item_count),
            str(folder.total_item_count),
            str(folder.child_folder_count),
            Text(folder.id),
        )
    console.print(table)
