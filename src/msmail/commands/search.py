from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

import typer
from rich.table import Table
from rich.text import Text

from msmail.console import console
from msmail.core import mail
from msmail.commands.list import (
    print_page, render_position, render_table, resolve_fetch, resolve_page_fetch, validate_page_options,
)


def search_messages(
    query: Optional[str] = typer.Argument(None, help="Microsoft Graph mail search query (omit with --cursor)."),
    fetch: Optional[str] = typer.Option(
        None,
        "--fetch",
        "-n",
        help="How many messages to fetch: a number, 'auto' (default) or 'all'. With --page-json: page size 1-100 (default 25).",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
    page_json: bool = typer.Option(False, "--page-json", help="Print one page with an independent cursor; leave the list cache untouched."),
    cursor: Optional[str] = typer.Option(None, "--cursor", help="Continue a previous --page-json search."),
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
) -> None:
    validate_page_options(page_json, json_output, cursor)
    if cursor is not None:
        if query is not None or fetch is not None:
            raise typer.BadParameter("--cursor cannot be combined with a new query or --fetch.")
        state = mail.continue_page(cursor, source="search", account_email=account)
    else:
        if query is None or not query.strip():
            raise typer.BadParameter("Provide a search query or use --cursor with --page-json.")
        state = mail.search_messages(
            query,
            fetch=resolve_page_fetch(fetch) if page_json else resolve_fetch(fetch),
            account_email=account,
            page_mode=page_json,
        )

    if page_json:
        print_page(state)
        return

    if json_output:
        console.print_json(json.dumps([asdict(message) for message in state.messages]))
        return

    render_table(state.messages)
    render_position(state)


def list_folders(
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
) -> None:
    folders = mail.list_folders(account_email=account)

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
