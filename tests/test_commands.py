from typer.testing import CliRunner

from msmail.cli import app
from msmail.core import mail


runner = CliRunner()


def test_mark_accepts_message_ranges(monkeypatch):
    calls = []

    monkeypatch.setattr(
        mail,
        "resolve_message_references",
        lambda reference, account_email=None: (["id-1", "id-2", "id-4"], "me@example.com"),
    )

    def mark_message(reference, *, is_read, account_email=None):
        calls.append((reference, is_read, account_email))
        return mail.MessageOperationResult(
            account="me@example.com",
            id=reference,
            subject=f"Subject {reference}",
            from_address="alice@example.com",
        )

    monkeypatch.setattr(mail, "mark_message", mark_message)

    result = runner.invoke(app, ["mark", "1-2,4", "--read", "--json"])

    assert result.exit_code == 0
    assert calls == [
        ("id-1", True, "me@example.com"),
        ("id-2", True, "me@example.com"),
        ("id-4", True, "me@example.com"),
    ]
    assert '"id": "id-4"' in result.stdout
