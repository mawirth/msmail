from typing import Optional

import typer

from msmail.console import console
from msmail.core import auth as auth_core


app = typer.Typer(
    rich_markup_mode=None,
    pretty_exceptions_enable=False,
    help="Authenticate and inspect Microsoft mail accounts.",
    invoke_without_command=True,
    no_args_is_help=True,
)


@app.callback()
def auth(
    login: Optional[str] = typer.Option(
        None,
        "--login",
        metavar="EMAIL",
        help="Start login for the given mail account.",
    ),
    whoami: bool = typer.Option(
        False,
        "--whoami",
        help="Show the active authenticated mail account.",
    ),
    logout: bool = typer.Option(
        False,
        "--logout",
        help="Log out the active mail account.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Confirm switching the active account without prompting.",
    ),
) -> None:
    requested = [login is not None, whoami, logout]
    if sum(1 for item in requested if item) != 1:
        raise typer.BadParameter(
            "Use exactly one of --login EMAIL, --whoami or --logout."
        )

    if login is not None:
        requested_email = login.strip().lower()
        active_email = auth_core.active_email()
        if active_email and active_email != requested_email and not yes:
            switch = typer.confirm(
                "Active account is "
                f"{active_email}. Log in as {requested_email} and make it active?"
            )
            if not switch:
                console.print("Login cancelled.")
                raise typer.Exit(code=1)

        def show_device_code(device_login: auth_core.DeviceLogin) -> None:
            console.print(device_login.message)

        result = auth_core.login(requested_email, on_device_code=show_device_code)
        console.print(f"Logged in: {result.account.email}")
        if result.account.display_name:
            console.print(f"Name: {result.account.display_name}")
        raise typer.Exit()

    if whoami:
        account = auth_core.whoami()
        if account is None:
            console.print("No active account.")
        else:
            console.print(account.email)
            if account.display_name:
                console.print(f"Name: {account.display_name}")
            if account.tenant_id:
                console.print(f"Tenant: {account.tenant_id}")
        raise typer.Exit()

    if logout:
        result = auth_core.logout()
        if result:
            console.print("Logged out.")
        else:
            console.print("No active account to log out.")
        raise typer.Exit()
