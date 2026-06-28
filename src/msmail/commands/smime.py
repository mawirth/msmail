from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

import typer
from rich.console import Console

from msmail.core import smime as smime_core


app = typer.Typer(
    help="Configure and inspect S/MIME material.",
    no_args_is_help=True,
)
console = Console()


@app.command("setup")
def setup(
    cert: str = typer.Option(..., "--cert", help="Own public S/MIME certificate."),
    key: str = typer.Option(..., "--key", help="Own private key."),
    ca_bundle: str = typer.Option(..., "--ca-bundle", help="CA bundle for verification."),
    fullchain: Optional[str] = typer.Option(None, "--fullchain", help="Optional PKCS#12 fullchain archive."),
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
) -> None:
    try:
        result = smime_core.setup(
            cert=cert,
            key=key,
            ca_bundle=ca_bundle,
            fullchain=fullchain,
            account_email=account,
        )
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if json_output:
        console.print_json(json.dumps(asdict(result)))
        return

    console.print(f"[green]S/MIME configured[/green]: {result.account}")
    console.print(f"Directory: {result.paths.directory}")
    console.print(f"Certificate: {result.certificate.subject}")
    console.print(f"Issuer: {result.certificate.issuer}")
    console.print(f"Valid until: {result.certificate.not_after}")


@app.command("status")
def status(
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
) -> None:
    try:
        result = smime_core.status(account_email=account)
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if json_output:
        console.print_json(json.dumps(asdict(result)))
        return

    console.print(f"Account: {result.account}")
    console.print(f"Directory: {result.directory}")
    console.print(f"Certificate: {'yes' if result.cert_exists else 'no'}")
    console.print(f"Private key: {'yes' if result.key_exists else 'no'}")
    console.print(f"CA bundle: {'yes' if result.ca_bundle_exists else 'no'}")
    console.print(f"PKCS#12 fullchain: {'yes' if result.fullchain_exists else 'no'}")
    console.print(f"Recipients directory: {'yes' if result.recipients_dir_exists else 'no'}")
    if result.certificate:
        console.print(f"Subject: {result.certificate.subject}")
        console.print(f"Issuer: {result.certificate.issuer}")
        console.print(f"Valid until: {result.certificate.not_after}")
        console.print(f"Emails: {', '.join(result.certificate.emails)}")
        console.print(f"E-mail Protection: {'yes' if result.certificate.email_protection else 'no'}")


@app.command("import-recipient")
def import_recipient(
    cert: str = typer.Option(..., "--cert", help="Recipient public S/MIME certificate."),
    email: Optional[str] = typer.Option(None, "--email", help="Recipient email address; inferred from certificate if omitted."),
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
) -> None:
    try:
        result = smime_core.import_recipient_certificate(
            cert=cert,
            email=email,
            account_email=account,
        )
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if json_output:
        console.print_json(json.dumps(asdict(result)))
        return

    console.print(f"[green]Recipient certificate imported[/green]: {result.email}")
    console.print(f"Path: {result.path}")
    console.print(f"Subject: {result.certificate.subject}")
    console.print(f"Valid until: {result.certificate.not_after}")


@app.command("test-sign")
def test_sign(
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
    output_dir: Optional[str] = typer.Option(None, "--output-dir", help="Directory for unsigned/signed/verified test files."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
) -> None:
    try:
        result = smime_core.local_sign_verify_smoke(
            account_email=account,
            output_dir=output_dir,
        )
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if json_output:
        console.print_json(json.dumps(asdict(result)))
        return

    console.print(f"[green]S/MIME local sign/verify OK[/green]: {result.account}")
    console.print(f"Unsigned: {result.unsigned_path}")
    console.print(f"Signed: {result.signed_path}")
    console.print(f"Verified: {result.verified_path}")
