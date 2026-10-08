from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

import typer
from rich.prompt import Confirm

from msmail.commands.common import run_batch
from msmail.console import console
from msmail.core import compose
from msmail.core import drafts
from msmail.core import mail


app = typer.Typer(
    rich_markup_mode=None,
    pretty_exceptions_enable=False,
    help="Create and manage drafts.",
    no_args_is_help=True,
)


def _recipient_summary(info: drafts.DraftInfo) -> str:
    parts = []
    if info.to:
        parts.append(f"To: {', '.join(info.to)}")
    if info.cc:
        parts.append(f"Cc: {', '.join(info.cc)}")
    if info.bcc:
        parts.append(f"Bcc: {', '.join(info.bcc)}")
    return " | ".join(parts) if parts else "(no recipients)"


def _print_draft_summary(info: drafts.DraftInfo) -> None:
    console.print(f"From: {info.from_address}", markup=False)
    console.print(f"To: {', '.join(info.to)}", markup=False)
    if info.cc:
        console.print(f"Cc: {', '.join(info.cc)}", markup=False)
    if info.bcc:
        console.print(f"Bcc: {', '.join(info.bcc)}", markup=False)
    console.print(f"Subject: {info.subject}", markup=False)
    if info.has_attachments:
        console.print("Attachments: yes")


@app.command("create")
def create(
    file: Optional[str] = typer.Option(None, "--file", help="Create draft from compose file."),
    to: Optional[str] = typer.Option(None, "--to", help="Recipient address list."),
    subject: Optional[str] = typer.Option(None, "--subject", help="Draft subject."),
    body: Optional[str] = typer.Option(None, "--body", help="Plain text body."),
    body_file: Optional[str] = typer.Option(None, "--body-file", help="Read plain text body from file."),
    attach: Optional[list[str]] = typer.Option(
        None,
        "--attach",
        "-a",
        help="Attach a local file. Can be used more than once.",
    ),
    html: bool = typer.Option(False, "--html", help="Create an HTML draft; body input is treated as HTML."),
    sign: bool = typer.Option(False, "--sign", help="Create an S/MIME signed MIME draft."),
    encrypt: bool = typer.Option(False, "--encrypt", help="Create an S/MIME encrypted MIME draft."),
    no_signature: bool = typer.Option(False, "--no-signature", help="Do not append the account signature."),
    edit: bool = typer.Option(False, "--edit", help="Open the compose template in the configured editor before creating the draft."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
) -> None:
    try:
        draft = compose.draft_from_inputs(
            file=file, to=to, subject=subject, body=body, body_file=body_file,
            attachments=attach, html=html, sign=sign, encrypt=encrypt,
            edit=edit, interactive=True,
        )

        result = drafts.create_draft(
            draft,
            account_email=account,
            include_signature=not no_signature,
        )
    except compose.ComposeCancelled as exc:
        console.print(f"{exc}")
        raise typer.Exit()

    if json_output:
        console.print_json(json.dumps(asdict(result)))
        return

    console.print(f"Draft created: {result.id}")
    console.print(f"To: {', '.join(result.to)}", markup=False)
    console.print(f"Subject: {result.subject}", markup=False)
    if result.attachments:
        console.print(f"Attachments: {', '.join(result.attachments)}", markup=False)
    if draft.sign or draft.encrypt:
        console.print("This S/MIME MIME draft cannot be edited with draft edit; review before sending.")


@app.command("edit")
def edit(
    reference: Optional[str] = typer.Argument(
        None,
        metavar="INDEX_OR_ID",
        help="Draft number from last list or Graph draft ID.",
    ),
    draft_id: Optional[str] = typer.Option(None, "--id", help="Graph draft message ID."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
) -> None:
    if bool(reference) == bool(draft_id):
        raise typer.BadParameter("Use either INDEX_OR_ID or --id.")

    try:
        template, info, body_content_type = drafts.compose_template_for_draft(
            draft_id or reference or "",
            account_email=account,
        )
        # Keep an HTML draft an HTML draft; the template holds its raw markup.
        updated = compose.edit_compose_interactively(
            template,
            html=body_content_type.lower() == "html",
        )
        if updated is None:
            console.print("Draft not modified.")
            raise typer.Exit()
        result = drafts.update_draft(info.id, updated, account_email=info.account, include_signature=False)
    except compose.ComposeCancelled as exc:
        console.print(f"{exc}")
        raise typer.Exit()

    if json_output:
        console.print_json(json.dumps(asdict(result)))
        return

    console.print(f"Draft updated: {result.id}")
    console.print(f"To: {', '.join(result.to)}", markup=False)
    console.print(f"Subject: {result.subject}", markup=False)


@app.command("send")
def send(
    reference: Optional[str] = typer.Argument(
        None,
        metavar="INDEX_RANGE_OR_ID",
        help="Draft number/range from last list or Graph draft ID.",
    ),
    draft_id: Optional[str] = typer.Option(None, "--id", help="Graph draft message ID."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Send without interactive confirmation."),
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
) -> None:
    if bool(reference) == bool(draft_id):
        raise typer.BadParameter("Use either INDEX_OR_ID or --id.")

    if draft_id:
        infos = [drafts.get_draft_info(draft_id, account_email=account)]
        labels = [draft_id]
    else:
        items, resolved_account = mail.resolve_message_reference_items(
            reference or "",
            account_email=account,
        )
        infos = [drafts.get_draft_info(item.id, account_email=resolved_account) for item in items]
        labels = [f"#{item.index}" if item.index else item.id for item in items]

    if len(infos) == 1:
        console.print("[bold]Draft ready to send[/bold]")
        _print_draft_summary(infos[0])
    else:
        console.print(f"[bold]{len(infos)} drafts ready to send[/bold]")
        for label, info in zip(labels, infos):
            recipients = _recipient_summary(info)
            console.print(f"{label}: {recipients} | Subject: {info.subject}", markup=False)

    prompt = "Send this draft?" if len(infos) == 1 else f"Send {len(infos)} drafts?"
    if not yes and not Confirm.ask(prompt, default=False, console=console):
        console.print("Send cancelled.")
        raise typer.Exit()

    run_batch(
        infos,
        lambda info: drafts.send_draft(info.id, account_email=info.account),
        identify=lambda info: info.id,
    )

    console.print(f"{len(infos)} draft(s) sent.")


@app.command("delete")
def delete(
    reference: Optional[str] = typer.Argument(
        None,
        metavar="INDEX_OR_ID",
        help="Draft number from last list or Graph draft ID.",
    ),
    draft_id: Optional[str] = typer.Option(None, "--id", help="Graph draft message ID."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Delete without interactive confirmation."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
) -> None:
    if bool(reference) == bool(draft_id):
        raise typer.BadParameter("Use either INDEX_OR_ID or --id.")
    if json_output and not yes:
        raise typer.BadParameter("--json requires --yes for delete.")

    info = drafts.get_draft_info(draft_id or reference or "", account_email=account)

    if not json_output:
        console.print("[bold]Draft ready to delete[/bold]")
        _print_draft_summary(info)

    if not yes and not Confirm.ask("Delete this draft?", default=False, console=console):
        console.print("Delete cancelled.")
        raise typer.Exit()

    deleted = drafts.delete_draft(info.id, account_email=info.account)

    if json_output:
        console.print_json(json.dumps(asdict(deleted)))
        return

    console.print("Draft deleted.")
