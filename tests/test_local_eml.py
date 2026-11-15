import hashlib
import json
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path
import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from msmail.cli import app
from msmail.core import auth, graph, mail, smime


runner = CliRunner()
SENDER = "alice@example.invalid"
ACCOUNT = "reader@example.invalid"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Local EML reading must not access mailbox/authentication/list cache")

    for module, names in [
        (auth, ["get_access_token", "active_email"]),
        (graph, ["get_json", "get_bytes"]),
        (mail, ["resolve_message_reference", "load_last_list", "load_last_list_state", "save_last_list"]),
    ]:
        for name in names:
            monkeypatch.setattr(module, name, forbidden)


def sample():
    message = EmailMessage(policy=SMTP)
    message["From"] = f"Alice Beispiel <{SENDER}>"
    message["To"] = ACCOUNT
    message["Cc"] = "copy@example.invalid"
    message["Subject"] = "Grüße aus dem Archiv"
    message["Date"] = "Sun, 15 Nov 2026 10:15:00 +0100"
    message["Message-ID"] = "<archive@example.invalid>"
    message.set_content("Synthetic archived content")
    return message


def read(tmp_path, data, *options):
    path = tmp_path / "source.eml"
    path.write_bytes(data)
    before = (hashlib.sha256(data).digest(), path.stat().st_mtime_ns)
    result = runner.invoke(app, ["read", "--file", str(path), *options])
    assert (hashlib.sha256(path.read_bytes()).digest(), path.stat().st_mtime_ns) == before
    return result


def json_read(tmp_path, data, *options):
    result = read(tmp_path, data, *options, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_local_identity_date_headers_and_body(tmp_path):
    payload = json_read(tmp_path, sample().as_bytes())
    assert payload["source"] == "file"
    assert payload["id"] is None
    assert payload["account"] is None
    assert payload["smime_account"] is None
    assert payload["received_date_time"] is None
    assert payload["internet_message_id"] == "<archive@example.invalid>"
    assert payload["date_source"] == "Date header"
    assert payload["sent_date_time"] == "2026-11-15T10:15:00+01:00"
    assert payload["subject"] == "Grüße aus dem Archiv"
    assert payload["from_name"] == "Alice Beispiel"
    assert payload["to_addresses"] == [ACCOUNT]
    assert payload["cc_addresses"] == ["copy@example.invalid"]
    assert payload["rendered_body"].strip() == "Synthetic archived content"
    assert payload["smime"]["signed"] is False
    assert payload["smime"]["verified"] is None


def test_terminal_uses_common_headers_and_marks_date_origin(tmp_path):
    result = read(tmp_path, sample().as_bytes())
    assert result.exit_code == 0, result.output
    assert "S/MIME:" in result.stdout and "none" in result.stdout
    assert "From:" in result.stdout and "Subject:" in result.stdout
    assert "EML header; receipt time unknown" in result.stdout
    assert "Synthetic archived content" in result.stdout


@pytest.mark.parametrize("date", [None, "not a date", "Sun, 15 Nov 2026 10:15:00 -0000"])
def test_missing_invalid_or_timezone_unknown_date_is_not_invented(tmp_path, date):
    message = sample()
    del message["Date"]
    data = message.as_bytes()
    if date is not None:
        data = f"Date: {date}\r\n".encode() + data
    payload = json_read(tmp_path, data)
    assert payload["received_date_time"] is None
    if date and "-0000" in date:
        assert payload["sent_date_time"] == "2026-11-15T10:15:00"
    else:
        assert payload["sent_date_time"] is None


@pytest.mark.parametrize("options", [[], ["--html"]])
def test_html_safelinks_charset_and_terminal_controls(tmp_path, options):
    message = sample()
    message.set_content(
        '<p>Grüße \x1b[31mRED\x1b[0m</p><script>hidden()</script>'
        '<a href="https://nam.safelinks.protection.outlook.com/?url=https%3A%2F%2Fexample.invalid%2Fdoc">Document</a>'
        '\x1b]0;window title\x07',
        subtype="html", charset="iso-8859-1", cte="quoted-printable",
    )
    payload = json_read(tmp_path, message.as_bytes(), *options)
    body = payload["rendered_body"]
    assert "Grüße RED" in body
    assert "https://example.invalid/doc" in body
    assert "<p>" not in body and "hidden()" not in body
    assert "\x1b" not in body and "\x07" not in body and "window title" not in body
    assert payload["body_content_type"] == "html"
    assert "<p>" in payload["body_content"]
    terminal = read(tmp_path, message.as_bytes(), *options)
    assert terminal.exit_code == 0
    assert ("<p>" in terminal.stdout) == bool(options)


def test_alternatives_and_inline_and_empty_attachment_details(tmp_path):
    message = sample()
    message.add_alternative("<p>HTML alternative</p>", subtype="html")
    message.add_attachment(b"", maintype="application", subtype="octet-stream", filename="empty.bin")
    message.add_attachment(b"image", maintype="image", subtype="png", filename="inline.png", disposition="inline")
    payload = json_read(tmp_path, message.as_bytes(), "--attachment-details")
    assert payload["rendered_body"].strip() == "Synthetic archived content"
    assert [(item["name"], item["size"], item["is_inline"]) for item in payload["attachments"]] == [
        ("empty.bin", 0, False), ("inline.png", 5, True),
    ]
    assert all(item["id"] is None for item in payload["attachments"])
    html = json_read(tmp_path, message.as_bytes(), "--html")
    assert html["rendered_body"] == "HTML alternative"


@pytest.mark.parametrize("other", [["1"], ["--id", "id"], ["1", "--id", "id"]])
def test_local_source_excludes_other_sources(tmp_path, other):
    result = runner.invoke(app, ["read", "--file", str(tmp_path / "missing.eml"), *other])
    assert result.exit_code == 2
    assert "exactly one" in result.output


@pytest.mark.parametrize("data", [
    b"", b"not an email", b"Subject: broken\r\nContent-Type: multipart/mixed; boundary=missing\r\n\r\nbody",
    b"Subject: broken\r\nContent-Transfer-Encoding: base64\r\n\r\n@@@",
])
def test_invalid_mime_reports_a_clean_error(tmp_path, data):
    result = read(tmp_path, data)
    assert result.exit_code == 1
    assert "Invalid MIME" in result.output
    assert "Traceback" not in result.output


def test_missing_directory_and_unreadable_files(tmp_path, monkeypatch):
    for path in (tmp_path / "missing.eml", tmp_path):
        result = runner.invoke(app, ["read", "--file", str(path)])
        assert result.exit_code == 1
        assert "Cannot read EML file" in result.output
    monkeypatch.setattr(Path, "read_bytes", lambda path: (_ for _ in ()).throw(PermissionError("Denied")))
    result = runner.invoke(app, ["read", "--file", str(tmp_path / "denied.eml")])
    assert result.exit_code == 1
    assert "Cannot read EML file" in result.output


def test_account_is_configuration_only_and_unsigned_flags_need_no_account(tmp_path):
    payload = json_read(tmp_path, sample().as_bytes(), "--account", ACCOUNT, "--verify-smime", "--decrypt")
    assert payload["account"] is None
    assert payload["smime_account"] == ACCOUNT
    assert payload["smime"]["verified"] is None
    assert payload["smime"]["decrypted"] is None


def test_unknown_charset_falls_back_without_false_smime_classification(tmp_path):
    data = (
        b'Subject: Charset fallback\r\nContent-Type: text/plain; charset=not-a-charset; name="signed-data.txt"\r\n\r\n'
        + "Grüße".encode()
    )
    payload = json_read(tmp_path, data)
    assert payload["rendered_body"] == "Grüße"
    assert payload["smime"]["signed"] is False


def test_cached_list_is_byte_identical_after_local_read(tmp_path):
    path = auth.account_dir(ACCOUNT) / "last-list.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    before = b'{"synthetic": "untouched cache"}\n'
    path.write_bytes(before)
    json_read(tmp_path, sample().as_bytes(), "--account", ACCOUNT)
    assert path.read_bytes() == before


@pytest.fixture
def crypto(tmp_path, monkeypatch):
    if not shutil.which("openssl"):
        pytest.skip("OpenSSL required for synthetic S/MIME tests")
    root = tmp_path / "crypto"
    root.mkdir()
    cert, key = root / "cert.pem", root / "key.pem"
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
        "-subj", f"/CN=Synthetic sender/emailAddress={SENDER}",
        "-addext", "extendedKeyUsage=emailProtection",
        "-addext", f"subjectAltName=email:{SENDER}",
        "-keyout", str(key), "-out", str(cert),
    ], check=True, capture_output=True)
    working = root / "temporary"
    working.mkdir()
    original = smime._working_dir

    def working_dir(output_dir, prefix):
        import tempfile
        if output_dir:
            return original(output_dir, prefix)
        return Path(tempfile.mkdtemp(prefix=prefix, dir=working)), True

    monkeypatch.setattr(smime, "_working_dir", working_dir)

    def transform(data, operation, *, opaque=False, configure=False):
        if configure:
            paths = smime.smime_paths(ACCOUNT)
            Path(paths.directory).mkdir(parents=True, exist_ok=True)
            Path(paths.cert).write_bytes(cert.read_bytes())
            Path(paths.key).write_bytes(key.read_bytes())
            Path(paths.ca_bundle).write_bytes(cert.read_bytes())
        source, target = root / "input.eml", root / "output.eml"
        source.write_bytes(data)
        args = ["openssl", "smime", f"-{operation}", "-in", str(source), "-out", str(target)]
        if operation == "sign":
            args += ["-signer", str(cert), "-inkey", str(key)]
            if opaque:
                args += ["-nodetach"]
        else:
            args += ["-aes256", str(cert)]
        subprocess.run(args, check=True, capture_output=True)
        return smime.wrap_mime_entity(
            sender=SENDER, to=[ACCOUNT], cc=[], bcc=[], subject="Synthetic S/MIME",
            entity=target.read_bytes(),
        )

    yield transform
    assert list(working.iterdir()) == [], "S/MIME temporary material must be removed"


@pytest.mark.parametrize("opaque", [False, True])
def test_signed_content_can_be_read_unverified_without_account(tmp_path, crypto, opaque):
    signed = crypto(sample().as_bytes(), "sign", opaque=opaque)
    payload = json_read(tmp_path, signed)
    assert "Synthetic archived content" in payload["rendered_body"]
    assert payload["smime"]["signed"] is True
    assert payload["smime"]["verified"] is None
    assert payload["smime"]["signature_valid"] is None


@pytest.mark.parametrize("opaque", [False, True])
def test_valid_but_untrusted_signature_needs_no_mailbox(tmp_path, crypto, opaque):
    signed = crypto(sample().as_bytes(), "sign", opaque=opaque)
    payload = json_read(tmp_path, signed, "--verify-smime")
    assert "Synthetic archived content" in payload["rendered_body"]
    assert payload["smime"]["signature_valid"] is True
    assert payload["smime"]["certificate_trusted"] is False
    assert payload["smime"]["verified"] is False
    assert payload["smime"]["trusted"] is False
    assert payload["smime"]["sender_matches"] is True
    terminal = read(tmp_path, signed, "--verify-smime")
    assert "signature valid, certificate not trusted" in terminal.output


def test_trusted_and_tampered_signatures_are_distinguished(tmp_path, crypto):
    signed = crypto(sample().as_bytes(), "sign", configure=True)
    payload = json_read(tmp_path, signed, "--verify-smime", "--account", ACCOUNT)
    assert payload["smime"]["signature_valid"] is True
    assert payload["smime"]["certificate_trusted"] is True
    assert payload["smime"]["trusted"] is True
    assert payload["smime"]["verified_path"] is None
    modified = signed.replace(b"Synthetic archived content", b"Tampered archived content")
    assert modified != signed
    payload = json_read(tmp_path, modified, "--verify-smime", "--account", ACCOUNT)
    assert payload["smime"]["signature_valid"] is False
    assert payload["smime"]["trusted"] is False
    terminal = read(tmp_path, modified, "--verify-smime", "--account", ACCOUNT)
    assert "signature invalid" in terminal.output


def test_sender_mismatch_does_not_become_trusted(tmp_path, crypto):
    signed = crypto(sample().as_bytes(), "sign", configure=True)
    signed = signed.replace(f"From: {SENDER}".encode(), b"From: other@example.invalid", 1)
    payload = json_read(tmp_path, signed, "--verify-smime", "--account", ACCOUNT)
    assert payload["smime"]["signature_valid"] is True
    assert payload["smime"]["certificate_trusted"] is True
    assert payload["smime"]["sender_matches"] is False
    assert payload["smime"]["trusted"] is False


@pytest.mark.parametrize("signed", [False, True])
def test_encrypted_messages_hide_signing_state_until_decrypted(tmp_path, crypto, signed):
    message = sample()
    message.add_attachment(b"attachment", maintype="application", subtype="octet-stream", filename="report.bin")
    data = message.as_bytes()
    if signed:
        data = crypto(data, "sign")
    encrypted = crypto(data, "encrypt", configure=True)
    unread = json_read(tmp_path, encrypted)
    assert unread["smime"]["encrypted"] is True
    assert unread["smime"]["signed"] is None
    assert unread["rendered_body"] == ""
    checked = json_read(tmp_path, encrypted, "--verify-smime")
    assert "decrypt" in checked["smime"]["error"]
    payload = json_read(tmp_path, encrypted, "--decrypt", "--verify-smime", "--account", ACCOUNT)
    assert payload["smime"]["decrypted"] is True
    assert payload["smime"]["signed"] is signed
    assert payload["smime"]["trusted"] is (True if signed else None)
    assert "Synthetic archived content" in payload["rendered_body"]
    assert payload["attachments"][0]["name"] == "report.bin"
    assert payload["smime"]["decrypted_path"] is None


def test_missing_keys_and_wrong_key_report_decryption_failure(tmp_path, crypto):
    encrypted = crypto(sample().as_bytes(), "encrypt")
    no_account = json_read(tmp_path, encrypted, "--decrypt")
    assert no_account["smime"]["decrypted"] is False
    assert "--account" in no_account["smime"]["decrypt_error"]
    no_keys = json_read(tmp_path, encrypted, "--decrypt", "--account", ACCOUNT)
    assert no_keys["smime"]["decrypted"] is False
    assert "private key" in no_keys["smime"]["decrypt_error"]
    crypto(sample().as_bytes(), "encrypt", configure=True)
    Path(smime.smime_paths(ACCOUNT).key).write_bytes(b"not a key")
    bad_key = json_read(tmp_path, encrypted, "--decrypt", "--account", ACCOUNT)
    assert bad_key["smime"]["decrypted"] is False
    assert bad_key["smime"]["decrypt_error"]
    assert bad_key["rendered_body"] == ""


def test_opaque_signature_inside_encryption_remains_unchecked_without_verify(tmp_path, crypto):
    signed = crypto(sample().as_bytes(), "sign", opaque=True)
    encrypted = crypto(signed, "encrypt", configure=True)
    payload = json_read(tmp_path, encrypted, "--decrypt", "--account", ACCOUNT)
    assert payload["smime"]["signed"] is True
    assert payload["smime"]["decrypted"] is True
    assert payload["smime"]["verified"] is None
    assert "Synthetic archived content" in payload["rendered_body"]
