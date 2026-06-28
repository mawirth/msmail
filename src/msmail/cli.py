import typer

from msmail.commands import auth
from msmail.commands import delete as delete_command
from msmail.commands import draft as draft_command
from msmail.commands import list as list_command
from msmail.commands import mark as mark_command
from msmail.commands import move as move_command
from msmail.commands import read as read_command
from msmail.commands import save_attachments as save_attachments_command
from msmail.commands import search as search_command
from msmail.commands import respond as respond_command
from msmail.commands import smime as smime_command


app = typer.Typer(
    help="Microsoft Graph mail CLI.",
    no_args_is_help=True,
)

app.add_typer(auth.app, name="auth")
app.add_typer(draft_command.app, name="draft")
app.add_typer(smime_command.app, name="smime")
app.command("list")(list_command.list_messages)
app.command("read")(read_command.read_message)
app.command("delete")(delete_command.delete_message)
app.command("move")(move_command.move_message)
app.command("mark")(mark_command.mark_message)
app.command("save-attachments")(save_attachments_command.save_attachments)
app.command("search")(search_command.search_messages)
app.command("folders")(search_command.list_folders)
app.command("reply")(respond_command.reply_message)
app.command("forward")(respond_command.forward_message)
