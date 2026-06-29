from __future__ import annotations

import json
import shutil
import sys
from dataclasses import asdict
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from msmail.core import graph
from msmail.core import mail


console = Console()


def shorten_middle(value: str, width: int) -> str:
    text = " ".join((value or "").split())
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width == 1:
        return "…"
    if width <= 8:
        return text[: width - 1] + "…"

    tail_len = min(5, max(2, width // 4))
    head_len = width - tail_len - 1
    return text[:head_len] + "…" + text[-tail_len:]


def resolve_limit(value: str) -> int:
    normalized = value.strip().lower()
    if normalized == "auto":
        if not sys.stdout.isatty():
            return 25
        rows = shutil.get_terminal_size(fallback=(100, 30)).lines
        return min(50, max(5, rows - 3))

    try:
        limit = int(normalized)
    except ValueError as exc:
        raise typer.BadParameter("--limit must be an integer or 'auto'.") from exc

    if limit < 1:
        raise typer.BadParameter("--limit must be at least 1.")
    return min(limit, 100)


def render_table(messages: list[mail.MessageSummary]) -> None:
    terminal_width = console.size.width or 100
    fixed_width = 4 + 17 + 7 + 4
    flexible_width = max(30, terminal_width - fixed_width)
    from_width = max(12, min(24, flexible_width // 3))
    subject_width = max(18, flexible_width - from_width)

    table = Table(
        show_header=True,
        header_style="bold",
        box=None,
        pad_edge=False,
        collapse_padding=True,
    )
    table.add_column("#", justify="right", width=3, no_wrap=True)
    table.add_column("UASE", width=4, no_wrap=True)
    table.add_column("Date", width=16, no_wrap=True)
    table.add_column("From", width=from_width, no_wrap=True, overflow="crop")
    table.add_column("Subject", width=subject_width, no_wrap=True, overflow="crop")

    for message in messages:
        status = "".join(
            [
                "*" if not message.is_read else "-",
                "*" if message.has_user_attachments else "-",
                "*" if message.smime_signed else "-",
                "*" if message.smime_encrypted else "-",
            ]
        )
        table.add_row(
            str(message.index),
            status,
            message.received_date_time[:16].replace("T", " "),
            shorten_middle(message.from_name or message.from_address, from_width),
            shorten_middle(message.subject, subject_width),
        )

    console.print(table)


def list_messages(
    folder: str = typer.Option("inbox", "--folder", help="Folder to list."),
    other: bool = typer.Option(False, "--other", help="List Other inbox messages."),
    all_messages: bool = typer.Option(False, "--all", help="List Focused and Other inbox messages."),
    limit: str = typer.Option("auto", "--limit", help="Message limit or 'auto'."),
    from_address: Optional[str] = typer.Option(None, "--from", help="Filter by exact sender email address."),
    after: Optional[str] = typer.Option(None, "--after", help="Only messages on or after YYYY-MM-DD."),
    before: Optional[str] = typer.Option(None, "--before", help="Only messages before YYYY-MM-DD."),
    attachment_details: bool = typer.Option(
        False,
        "--attachment-details",
        help="Inspect attachments to distinguish user files from S/MIME metadata.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
) -> None:
    if other and all_messages:
        raise typer.BadParameter("Use only one of --other or --all.")

    inbox_class: mail.InboxClass = "focused"
    folder_id = mail.normalize_folder(folder)
    if other:
        inbox_class = "other"
    elif all_messages:
        inbox_class = "all"
    elif folder_id != "inbox":
        inbox_class = "all"

    resolved_limit = resolve_limit(limit)
    try:
        messages = mail.list_messages(
            folder=folder,
            inbox_class=inbox_class,
            limit=resolved_limit,
            account_email=account,
            from_address=from_address,
            after=after,
            before=before,
            include_attachment_details=attachment_details,
        )
    except (ValueError, graph.GraphError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if json_output:
        console.print_json(json.dumps([asdict(message) for message in messages]))
        return

    render_table(messages)
