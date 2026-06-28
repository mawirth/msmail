from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

import typer
from rich.console import Console

from msmail.core import compose
from msmail.core import drafts
from msmail.core import graph


console = Console()


def _response_from_inputs(
    *,
    file: Optional[str],
    body: Optional[str],
    body_file: Optional[str],
    edit: bool,
    to: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    require_to: bool = False,
    html: bool = False,
) -> compose.ResponseDraft:
    if file:
        if any([body, body_file, edit, to, cc, bcc]):
            raise ValueError("--file cannot be combined with body, recipient or --edit options.")
        return compose.read_response_file(file, require_to=require_to, html=html)

    if body and body_file:
        raise ValueError("Use only one of --body or --body-file.")

    body_text = body or ""
    if body_file:
        with open(body_file, encoding="utf-8") as handle:
            body_text = handle.read()

    template = compose.response_template(
        to=to or "",
        cc=cc or "",
        bcc=bcc or "",
        body=body_text,
        include_recipients=require_to,
    )
    if edit or not body_text:
        return compose.response_interactively(template, require_to=require_to, html=html)
    return compose.parse_response_text(template, require_to=require_to, html=html)


def _print_result(result: drafts.ResponseDraftResult) -> None:
    console.print(f"[green]Draft created[/green]: {result.id}")
    console.print(f"Type: {result.response_type}")
    if result.to:
        console.print(f"To: {', '.join(result.to)}")
    if result.subject:
        console.print(f"Subject: {result.subject}")


def reply_message(
    reference: Optional[str] = typer.Argument(
        None,
        metavar="INDEX_OR_ID",
        help="Message number from last list or Graph message ID.",
    ),
    message_id: Optional[str] = typer.Option(None, "--id", help="Graph message ID."),
    body: Optional[str] = typer.Option(None, "--body", help="Reply body text."),
    body_file: Optional[str] = typer.Option(None, "--body-file", help="Read reply body from file."),
    file: Optional[str] = typer.Option(None, "--file", help="Read reply body or response compose file."),
    html: bool = typer.Option(False, "--html", help="Create an HTML reply draft; body input is treated as HTML."),
    sign: bool = typer.Option(False, "--sign", help="Create an S/MIME signed reply draft."),
    encrypt: bool = typer.Option(False, "--encrypt", help="Create an S/MIME encrypted reply draft."),
    no_signature: bool = typer.Option(False, "--no-signature", help="Do not append the account signature."),
    edit: bool = typer.Option(False, "--edit", help="Open reply text in the configured editor before creating the draft."),
    reply_all: bool = typer.Option(False, "--all", help="Create a reply-all draft."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
) -> None:
    if bool(reference) == bool(message_id):
        raise typer.BadParameter("Use either INDEX_OR_ID or --id.")

    try:
        response = _response_from_inputs(
            file=file,
            body=body,
            body_file=body_file,
            edit=edit,
            html=html,
        )
        result = drafts.create_reply_draft(
            message_id or reference or "",
            response,
            reply_all=reply_all,
            sign=sign,
            encrypt=encrypt,
            account_email=account,
            include_signature=not no_signature,
        )
    except compose.ComposeCancelled as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise typer.Exit()
    except (RuntimeError, ValueError, graph.GraphError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if json_output:
        console.print_json(json.dumps(asdict(result)))
        return

    _print_result(result)


def forward_message(
    reference: Optional[str] = typer.Argument(
        None,
        metavar="INDEX_OR_ID",
        help="Message number from last list or Graph message ID.",
    ),
    message_id: Optional[str] = typer.Option(None, "--id", help="Graph message ID."),
    to: Optional[str] = typer.Option(None, "--to", help="Forward recipient address list."),
    cc: Optional[str] = typer.Option(None, "--cc", help="Cc recipient address list."),
    bcc: Optional[str] = typer.Option(None, "--bcc", help="Bcc recipient address list."),
    body: Optional[str] = typer.Option(None, "--body", help="Forward body text."),
    body_file: Optional[str] = typer.Option(None, "--body-file", help="Read forward body from file."),
    file: Optional[str] = typer.Option(None, "--file", help="Read forward response compose file."),
    html: bool = typer.Option(False, "--html", help="Create an HTML forward draft; body input is treated as HTML."),
    sign: bool = typer.Option(False, "--sign", help="Create an S/MIME signed forward draft."),
    encrypt: bool = typer.Option(False, "--encrypt", help="Create an S/MIME encrypted forward draft."),
    no_signature: bool = typer.Option(False, "--no-signature", help="Do not append the account signature."),
    edit: bool = typer.Option(False, "--edit", help="Open forward text in the configured editor before creating the draft."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
) -> None:
    if bool(reference) == bool(message_id):
        raise typer.BadParameter("Use either INDEX_OR_ID or --id.")

    try:
        response = _response_from_inputs(
            file=file,
            body=body,
            body_file=body_file,
            edit=edit,
            to=to,
            cc=cc,
            bcc=bcc,
            require_to=True,
            html=html,
        )
        result = drafts.create_forward_draft(
            message_id or reference or "",
            response,
            sign=sign,
            encrypt=encrypt,
            account_email=account,
            include_signature=not no_signature,
        )
    except compose.ComposeCancelled as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise typer.Exit()
    except (RuntimeError, ValueError, graph.GraphError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if json_output:
        console.print_json(json.dumps(asdict(result)))
        return

    _print_result(result)
