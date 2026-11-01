import json
import os
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from msmail.cli import app
from msmail.core import auth, graph, mail


runner = CliRunner()
ACCOUNT = "export@example.com"
MESSAGE_ID = "message/id+with-hyphen="
MIME = (
    b"From: alice@example.com\r\nTo: export@example.com\r\n"
    b"Subject: Export\r\nMIME-Version: 1.0\r\n"
    b'Content-Type: multipart/mixed; boundary="example"\r\n\r\n'
    b"--example\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nGr\xc3\xbc\xc3\x9fe\r\n"
    b"--example\r\nContent-Type: application/octet-stream\r\n"
    b'Content-Disposition: attachment; filename="test.bin"\r\n'
    b"Content-Transfer-Encoding: base64\r\n\r\nAP8=\r\n--example--\r\n"
)


@pytest.fixture
def mailbox(monkeypatch):
    calls = []
    monkeypatch.setattr(auth, "resolve_account_email", lambda email=None: email or ACCOUNT)
    monkeypatch.setattr(
        auth, "get_access_token",
        lambda email=None: ("synthetic-token", SimpleNamespace(email=email or ACCOUNT)),
    )
    monkeypatch.setattr(
        mail, "load_last_list",
        lambda email: [SimpleNamespace(index=1, id=MESSAGE_ID)],
    )

    def get_bytes(path, token, *, accept):
        calls.append((path, token, accept))
        return MIME

    monkeypatch.setattr(graph, "get_bytes", get_bytes)
    return calls


def test_export_index_preserves_complete_mime_and_reports_json(mailbox, tmp_path):
    destination = tmp_path / "message.eml"
    result = runner.invoke(app, ["export", "1", "--to", str(destination), "--json"])

    assert result.exit_code == 0, result.output
    assert destination.read_bytes() == MIME
    assert json.loads(result.stdout) == {
        "account": ACCOUNT, "id": MESSAGE_ID, "path": str(destination), "size": len(MIME),
    }
    assert mailbox == [
        ("/me/messages/message%2Fid%2Bwith-hyphen%3D/$value", "synthetic-token", "message/rfc822"),
    ]
    if os.name == "posix":
        assert destination.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("message_id", ["123", "1-3", MESSAGE_ID])
def test_export_explicit_id_and_account(mailbox, tmp_path, message_id):
    destination = tmp_path / "message.eml"
    result = runner.invoke(app, [
        "export", "--id", message_id, "--account", "other@example.com",
        "--to", str(destination), "--json",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["account"] == "other@example.com"
    assert json.loads(result.stdout)["id"] == message_id
    assert mailbox[0][0] == f"/me/messages/{graph.quote_path_segment(message_id)}/$value"


def test_export_refuses_existing_file_unless_overwrite(mailbox, tmp_path):
    destination = tmp_path / "message.eml"
    destination.write_bytes(b"existing")
    args = ["export", "1", "--to", str(destination)]

    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert "--overwrite" in result.output
    assert destination.read_bytes() == b"existing"
    assert mailbox == []

    result = runner.invoke(app, args + ["--overwrite"])
    assert result.exit_code == 0, result.output
    assert "Saved message:" in result.stdout
    assert destination.read_bytes() == MIME


@pytest.mark.parametrize("existing", [False, True])
def test_export_network_failure_preserves_destination(mailbox, monkeypatch, tmp_path, existing):
    destination = tmp_path / "message.eml"
    if existing:
        destination.write_bytes(b"existing")

    def fail(*args, **kwargs):
        raise graph.GraphError("Download failed")

    monkeypatch.setattr(graph, "get_bytes", fail)
    result = runner.invoke(app, ["export", "1", "--to", str(destination), "--overwrite"])
    assert result.exit_code == 1
    assert "Download failed" in result.output
    if existing:
        assert destination.read_bytes() == b"existing"
    else:
        assert not destination.exists()


def test_export_refuses_file_created_during_download(mailbox, monkeypatch, tmp_path):
    destination = tmp_path / "message.eml"

    def download(*args, **kwargs):
        destination.write_bytes(b"concurrent file")
        return MIME

    monkeypatch.setattr(graph, "get_bytes", download)
    result = runner.invoke(app, ["export", "1", "--to", str(destination)])
    assert result.exit_code == 1
    assert destination.read_bytes() == b"concurrent file"


@pytest.mark.parametrize("args", [[], ["1"], ["--to", "message.eml"], ["1", "--id", "id", "--to", "message.eml"]])
def test_export_requires_one_reference_and_destination(args):
    result = runner.invoke(app, ["export"] + args)
    assert result.exit_code == 2


@pytest.mark.parametrize("content_type", ["multipart/signed", "application/pkcs7-mime"])
def test_export_smime_is_not_transformed(mailbox, monkeypatch, tmp_path, content_type):
    data = f"MIME-Version: 1.0\r\nContent-Type: {content_type}\r\n\r\n".encode() + b"\x00\xff\r\n"
    monkeypatch.setattr(graph, "get_bytes", lambda *args, **kwargs: data)
    destination = tmp_path / "smime.eml"
    mail.export_message("1", destination=str(destination))
    assert destination.read_bytes() == data
