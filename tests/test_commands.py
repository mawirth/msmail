from typer.testing import CliRunner

from msmail.commands import draft as draft_command
from msmail.commands import read as read_command
from msmail.cli import app
from msmail.core import doctor
from msmail.core import drafts
from msmail.core import mail
from msmail.core import smime


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


def test_draft_edit_does_not_append_signature_again(monkeypatch):
    captured = {}
    updated = drafts.DraftEditResult(
        account="me@example.com",
        id="draft-1",
        subject="Updated",
        to=["alice@example.com"],
        attachments=[],
    )

    monkeypatch.setattr(
        drafts,
        "compose_template_for_draft",
        lambda reference, account_email=None: (
            "To: alice@example.com\nCc:\nBcc:\nSubject: Status\nAttach:\nSign: no\nEncrypt: no\n\n---\nDone.\n\n--\nAlex",
            drafts.DraftInfo(
                account="me@example.com",
                id="draft-1",
                subject="Status",
                from_address="me@example.com",
                to=["alice@example.com"],
                cc=[],
                bcc=[],
                has_attachments=False,
                is_draft=True,
            ),
        ),
    )
    monkeypatch.setattr(
        draft_command.compose,
        "edit_compose_interactively",
        lambda template: draft_command.compose.ComposeDraft(
            to=["alice@example.com"],
            cc=[],
            bcc=[],
            subject="Updated",
            body="Changed.\n\n--\nAlex",
            body_content_type="Text",
            attachments=[],
            sign=False,
            encrypt=False,
        ),
    )

    def update_draft(draft_id, draft, account_email=None, include_signature=True):
        captured["include_signature"] = include_signature
        captured["body"] = draft.body
        return updated

    monkeypatch.setattr(drafts, "update_draft", update_draft)

    result = runner.invoke(app, ["draft", "edit", "1"])

    assert result.exit_code == 0
    assert captured == {
        "include_signature": False,
        "body": "Changed.\n\n--\nAlex",
    }


def test_draft_create_warns_that_smime_draft_cannot_be_edited(monkeypatch):
    monkeypatch.setattr(
        drafts,
        "create_draft",
        lambda draft, account_email=None, include_signature=True: drafts.DraftResult(
            account="me@example.com",
            id="draft-1",
            subject=draft.subject,
            to=draft.to,
            attachments=[],
        ),
    )

    result = runner.invoke(
        app,
        [
            "draft",
            "create",
            "--to",
            "alice@example.com",
            "--subject",
            "Signed",
            "--body",
            "Hi",
            "--sign",
        ],
    )

    assert result.exit_code == 0
    assert "cannot be edited with draft edit" in result.stdout


def test_direct_send_is_noninteractive_with_yes_and_json(monkeypatch):
    captured = {}

    def create_and_send(draft, account_email=None, include_signature=True):
        captured["draft"] = draft
        captured["account"] = account_email
        captured["include_signature"] = include_signature
        return drafts.SentMessageResult(
            account="alerts@example.com",
            id="draft-id",
            subject=draft.subject,
            to=draft.to,
            attachments=draft.attachments,
            sent=True,
        )

    monkeypatch.setattr(drafts, "create_and_send", create_and_send)

    result = runner.invoke(
        app,
        [
            "send",
            "--to",
            "admin@example.com",
            "--subject",
            "Backup failed",
            "--body",
            "See the log.",
            "--account",
            "alerts@example.com",
            "--no-signature",
            "--yes",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert captured["account"] == "alerts@example.com"
    assert captured["include_signature"] is False
    assert captured["draft"].body == "See the log."
    assert '"sent": true' in result.stdout


def test_direct_send_json_requires_yes():
    result = runner.invoke(
        app,
        [
            "send",
            "--to",
            "admin@example.com",
            "--subject",
            "Test",
            "--body",
            "Hello",
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "--json requires --yes" in result.stdout


def test_read_signed_message_renders_raw_mime_body(monkeypatch):
    monkeypatch.setattr(
        mail,
        "resolve_message_reference",
        lambda reference, account_email=None: ("signed-id", "me@example.com"),
    )
    monkeypatch.setattr(
        mail,
        "get_message",
        lambda message_id, account_email=None, include_attachment_details=True: mail.MessageDetail(
            account="me@example.com",
            id=message_id,
            subject="Signed draft",
            from_name="Me",
            from_address="me@example.com",
            to_addresses=["alice@example.com"],
            cc_addresses=[],
            received_date_time="",
            internet_message_id="",
            body_content_type="text",
            body_content="",
            body_preview="",
            has_attachments=True,
            attachment_count=0,
            attachments=[],
            smime_signed=True,
            smime_encrypted=False,
        ),
    )
    monkeypatch.setattr(
        mail,
        "get_message_mime",
        lambda message_id, account_email=None: (
            (
                b'Content-Type: multipart/signed; boundary="sig"; protocol="application/pkcs7-signature"\r\n'
                b"\r\n"
                b"--sig\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n"
                b"\r\n"
                b"Signed body\r\n"
                b"--sig\r\n"
                b"Content-Type: application/pkcs7-signature; name=\"smime.p7s\"\r\n"
                b"Content-Disposition: attachment; filename=\"smime.p7s\"\r\n"
                b"\r\n"
                b"signature\r\n"
                b"--sig--\r\n"
            ),
            "me@example.com",
        ),
    )

    result = runner.invoke(app, ["read", "1", "--attachment-details"])

    assert result.exit_code == 0
    assert "S/MIME:" in result.stdout
    assert "signed" in result.stdout
    assert "Signed body" in result.stdout


def test_read_message_uses_fast_attachment_path_by_default(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        mail,
        "resolve_message_reference",
        lambda reference, account_email=None: ("message-id", "me@example.com"),
    )

    def get_message(message_id, account_email=None, include_attachment_details=True):
        captured["include_attachment_details"] = include_attachment_details
        return mail.MessageDetail(
            account="me@example.com",
            id=message_id,
            subject="Status",
            from_name="Alice",
            from_address="alice@example.com",
            to_addresses=["me@example.com"],
            cc_addresses=[],
            received_date_time="",
            internet_message_id="",
            body_content_type="text",
            body_content="Hello",
            body_preview="Hello",
            has_attachments=True,
            attachment_count=0,
            attachments=[],
            smime_signed=False,
            smime_encrypted=False,
            attachment_details_loaded=False,
        )

    monkeypatch.setattr(mail, "get_message", get_message)

    result = runner.invoke(app, ["read", "1"])

    assert result.exit_code == 0
    assert captured["include_attachment_details"] is False
    assert "Attachments:" in result.stdout
    assert "yes" in result.stdout
    assert "S/MIME:" in result.stdout
    assert "unknown" in result.stdout
    assert "Hello" in result.stdout


def test_read_verified_signed_message_renders_verified_body(monkeypatch, tmp_path):
    verified = tmp_path / "verified.eml"
    verified.write_bytes(b"Content-Type: text/plain; charset=utf-8\r\n\r\nVerified body\r\n")

    monkeypatch.setattr(
        mail,
        "resolve_message_reference",
        lambda reference, account_email=None: ("signed-id", "me@example.com"),
    )
    monkeypatch.setattr(
        mail,
        "get_message",
        lambda message_id, account_email=None, include_attachment_details=True: mail.MessageDetail(
            account="me@example.com",
            id=message_id,
            subject="Signed draft",
            from_name="Me",
            from_address="me@example.com",
            to_addresses=["alice@example.com"],
            cc_addresses=[],
            received_date_time="",
            internet_message_id="",
            body_content_type="text",
            body_content="",
            body_preview="",
            has_attachments=True,
            attachment_count=0,
            attachments=[],
            smime_signed=True,
            smime_encrypted=False,
        ),
    )
    monkeypatch.setattr(mail, "get_message_mime", lambda message_id, account_email=None: (b"signed mime", "me@example.com"))
    monkeypatch.setattr(
        read_command.smime,
        "verify_signed_mime_bytes",
        lambda mime_bytes, account_email=None: smime.VerifyResult(
            verified=True,
            signed=True,
            verified_path=str(verified),
        ),
    )

    result = runner.invoke(app, ["read", "1", "--verify-smime"])

    assert result.exit_code == 0
    assert "trusted" in result.stdout
    assert "Verified body" in result.stdout


def test_doctor_prints_report(monkeypatch):
    monkeypatch.setattr(
        doctor,
        "check",
        lambda account_email=None: doctor.DoctorReport(
            ok=True,
            lines=[
                doctor.DoctorLine("Python", "OK", "3.12.0"),
                doctor.DoctorLine("Account", "OK", "me@example.com"),
            ],
        ),
    )

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Python:" in result.stdout
    assert "OK, 3.12.0" in result.stdout
    assert "Account:" in result.stdout
    assert "me@example.com" in result.stdout


def test_doctor_json_exits_nonzero_for_errors(monkeypatch):
    monkeypatch.setattr(
        doctor,
        "check",
        lambda account_email=None: doctor.DoctorReport(
            ok=False,
            lines=[doctor.DoctorLine("Token", "ERROR", "expired")],
        ),
    )

    result = runner.invoke(app, ["doctor", "--json"])

    assert result.exit_code == 1
    assert '"status": "ERROR"' in result.stdout


def test_doctor_missing_signatures_are_informational(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor.auth, "active_email", lambda: "me@example.com")
    monkeypatch.setattr(
        doctor.auth,
        "get_access_token",
        lambda account_email=None: ("token", doctor.auth.Account(email="me@example.com")),
    )
    monkeypatch.setattr(doctor.auth, "account_dir", lambda email: tmp_path / email)
    monkeypatch.setattr(doctor.graph, "get_json", lambda path, token, params=None: {})
    monkeypatch.setattr(doctor, "_openssl_version", lambda: ("OK", "OpenSSL 3.0.0"))
    monkeypatch.setattr(doctor, "_temp_dir_status", lambda: ("OK", "/tmp"))
    smime_dir = tmp_path / "me@example.com" / "smime"
    smime_dir.mkdir(parents=True)
    (smime_dir / "own-cert.pem").write_text("cert", encoding="utf-8")
    (smime_dir / "own-key.pem").write_text("key", encoding="utf-8")
    (smime_dir / "ca-bundle.pem").write_text("ca", encoding="utf-8")
    monkeypatch.setattr(
        doctor.smime,
        "smime_paths",
        lambda account_email: doctor.smime.SmimePaths(
            account=account_email,
            directory=str(smime_dir),
            cert=str(smime_dir / "own-cert.pem"),
            key=str(smime_dir / "own-key.pem"),
            ca_bundle=str(smime_dir / "ca-bundle.pem"),
            fullchain=str(smime_dir / "own-fullchain.p12"),
            recipients_dir=str(smime_dir / "recipients"),
        ),
    )

    report = doctor.check()

    assert report.ok is True
    assert doctor.DoctorLine("Signature txt", "MISSING", str(tmp_path / "me@example.com" / "signature.txt")) in report.lines
    assert doctor.DoctorLine("Signature html", "MISSING", str(tmp_path / "me@example.com" / "signature.html")) in report.lines
