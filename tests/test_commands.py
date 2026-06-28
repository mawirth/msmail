from typer.testing import CliRunner

from msmail.cli import app
from msmail.core import drafts
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


def test_draft_send_accepts_message_ranges(monkeypatch):
    loaded = []
    sent = []
    monkeypatch.setattr(
        mail,
        "resolve_message_reference_items",
        lambda reference, account_email=None: (
            [mail.MessageSummary(
                account="me@example.com",
                index=1,
                id="draft-1",
                subject="Draft 1",
                from_name="Alice",
                from_address="alice@example.com",
                received_date_time="",
                is_read=True,
                has_attachments=False,
                has_user_attachments=False,
                smime_signed=False,
                smime_encrypted=False,
                inference_classification=None,
                body_preview="",
            ), mail.MessageSummary(
                account="me@example.com",
                index=2,
                id="draft-2",
                subject="Draft 2",
                from_name="Alice",
                from_address="alice@example.com",
                received_date_time="",
                is_read=True,
                has_attachments=False,
                has_user_attachments=False,
                smime_signed=False,
                smime_encrypted=False,
                inference_classification=None,
                body_preview="",
            )],
            "me@example.com",
        ),
    )

    def get_draft_info(reference, account_email=None):
        loaded.append((reference, account_email))
        return drafts.DraftInfo(
            account="me@example.com",
            id=reference,
            subject=f"Subject {reference}",
            from_address="me@example.com",
            to=["alice@example.com"],
            cc=[],
            bcc=[],
            has_attachments=False,
            is_draft=True,
        )

    monkeypatch.setattr(drafts, "get_draft_info", get_draft_info)
    monkeypatch.setattr(drafts, "send_draft", lambda draft_id, account_email=None: sent.append((draft_id, account_email)))

    result = runner.invoke(app, ["draft", "send", "1-2", "--yes"])

    assert result.exit_code == 0
    assert loaded == [("draft-1", "me@example.com"), ("draft-2", "me@example.com")]
    assert sent == [("draft-1", "me@example.com"), ("draft-2", "me@example.com")]
    assert "2 draft(s) sent" in result.stdout
