from __future__ import annotations

from dataclasses import asdict
import json
from typing import Optional

import typer
from rich.console import Console

from msmail.core import doctor as doctor_core


console = Console()


def doctor(
    account: Optional[str] = typer.Option(None, "--account", help="Mail account email address."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
) -> None:
    report = doctor_core.check(account_email=account)

    if json_output:
        console.print_json(json.dumps(asdict(report)))
        if not report.ok:
            raise typer.Exit(code=1)
        return

    width = max(len(line.name) for line in report.lines)
    for line in report.lines:
        value = line.status if line.detail is None else f"{line.status}, {line.detail}"
        console.print(f"{line.name + ':':<{width + 1}} {value}")

    if not report.ok:
        raise typer.Exit(code=1)
