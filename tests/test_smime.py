from pathlib import Path

import pytest

from msmail.core import smime


def fake_certificate_info(path):
    return smime.CertificateInfo(
        subject="emailAddress=user@example.com",
        issuer="D-Trust",
        not_before="Jun 17 11:16:46 2026 GMT",
        not_after="Jun 17 11:16:46 2027 GMT",
        emails=["user@example.com"],
        email_protection=True,
    )


def test_smime_paths_are_account_scoped(monkeypatch, tmp_path):
    monkeypatch.setattr(smime.auth, "account_dir", lambda account: tmp_path / account)

    paths = smime.smime_paths("user@example.com")

    assert paths.directory == str(tmp_path / "user@example.com" / "smime")
    assert paths.cert.endswith("/smime/own-cert.pem")
    assert paths.key.endswith("/smime/own-key.pem")
    assert paths.ca_bundle.endswith("/smime/ca-bundle.pem")
    assert paths.fullchain.endswith("/smime/own-fullchain.p12")
    assert paths.recipients_dir.endswith("/smime/recipients")


def test_setup_copies_material_and_sets_private_modes(monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    cert = source / "cert.cer"
    key = source / "key.pem"
    ca_bundle = source / "ca.pem"
    fullchain = source / "fullchain.p12"
    for path in [cert, key, ca_bundle, fullchain]:
        path.write_text(path.name, encoding="utf-8")

    state = tmp_path / "state"
    monkeypatch.setattr(smime.auth, "account_dir", lambda account: state / account)
    monkeypatch.setattr(smime, "certificate_info", fake_certificate_info)

    result = smime.setup(
        cert=str(cert),
        key=str(key),
        ca_bundle=str(ca_bundle),
        fullchain=str(fullchain),
        account_email="user@example.com",
    )

    smime_dir = state / "user@example.com" / "smime"
    assert result.paths.directory == str(smime_dir)
    assert (smime_dir / "own-cert.pem").read_text(encoding="utf-8") == "cert.cer"
    assert (smime_dir / "own-key.pem").read_text(encoding="utf-8") == "key.pem"
    assert (smime_dir / "ca-bundle.pem").read_text(encoding="utf-8") == "ca.pem"
    assert (smime_dir / "own-fullchain.p12").read_text(encoding="utf-8") == "fullchain.p12"
    assert oct(smime_dir.stat().st_mode & 0o777) == "0o700"
    assert oct((smime_dir / "recipients").stat().st_mode & 0o777) == "0o700"
    assert oct((smime_dir / "own-key.pem").stat().st_mode & 0o777) == "0o600"


def test_setup_rejects_certificate_for_different_account(monkeypatch, tmp_path):
    cert = tmp_path / "cert.cer"
    key = tmp_path / "key.pem"
    ca_bundle = tmp_path / "ca.pem"
    for path in [cert, key, ca_bundle]:
        path.write_text(path.name, encoding="utf-8")

    monkeypatch.setattr(
        smime,
        "certificate_info",
        lambda path: smime.CertificateInfo(
            subject="emailAddress=other@example.com",
            issuer="D-Trust",
            not_before="",
            not_after="",
            emails=["other@example.com"],
            email_protection=True,
        ),
    )

    with pytest.raises(ValueError, match="does not match account"):
        smime.setup(
            cert=str(cert),
            key=str(key),
            ca_bundle=str(ca_bundle),
            account_email="user@example.com",
        )


def test_status_reports_existing_material(monkeypatch, tmp_path):
    state = tmp_path / "state"
    smime_dir = state / "user@example.com" / "smime"
    smime_dir.mkdir(parents=True)
    (smime_dir / "recipients").mkdir()
    for name in ["own-cert.pem", "own-key.pem", "ca-bundle.pem"]:
        (smime_dir / name).write_text(name, encoding="utf-8")

    monkeypatch.setattr(smime.auth, "account_dir", lambda account: state / account)
    monkeypatch.setattr(smime, "certificate_info", fake_certificate_info)

    result = smime.status(account_email="user@example.com")

    assert result.cert_exists is True
    assert result.key_exists is True
    assert result.ca_bundle_exists is True
    assert result.fullchain_exists is False
    assert result.recipients_dir_exists is True
    assert result.certificate and result.certificate.email_protection is True


def test_import_recipient_certificate_uses_certificate_email(monkeypatch, tmp_path):
    cert = tmp_path / "alice.pem"
    cert.write_text("cert", encoding="utf-8")
    state = tmp_path / "state"

    monkeypatch.setattr(smime.auth, "account_dir", lambda account: state / account)
    monkeypatch.setattr(
        smime,
        "certificate_info",
        lambda path: smime.CertificateInfo(
            subject="emailAddress=alice@example.com",
            issuer="CA",
            not_before="",
            not_after="",
            emails=["alice@example.com"],
            email_protection=True,
        ),
    )

    result = smime.import_recipient_certificate(cert=str(cert), account_email="me@example.com")

    assert result.email == "alice@example.com"
    assert Path(result.path).read_text(encoding="utf-8") == "cert"
    assert result.path.endswith("/smime/recipients/alice@example.com.pem")
    assert oct(Path(result.path).stat().st_mode & 0o777) == "0o600"


def test_recipient_certificates_use_own_cert_for_self_and_recipient_dir_for_others(monkeypatch, tmp_path):
    smime_dir = tmp_path / "smime"
    recipients_dir = smime_dir / "recipients"
    recipients_dir.mkdir(parents=True)
    own_cert = smime_dir / "own-cert.pem"
    own_cert.write_text("own", encoding="utf-8")
    alice_cert = recipients_dir / "alice@example.com.pem"
    alice_cert.write_text("alice", encoding="utf-8")
    paths = smime.SmimePaths(
        account="me@example.com",
        directory=str(smime_dir),
        cert=str(own_cert),
        key=str(smime_dir / "own-key.pem"),
        ca_bundle=str(smime_dir / "ca-bundle.pem"),
        fullchain=str(smime_dir / "own-fullchain.p12"),
        recipients_dir=str(recipients_dir),
    )

    monkeypatch.setattr(smime, "require_configured", lambda account_email=None: ("me@example.com", paths))
    monkeypatch.setattr(smime, "verification_material", lambda account_email=None: ("me@example.com", paths))

    assert smime.recipient_certificates(
        ["alice@example.com", "me@example.com", "alice@example.com"],
        account_email="me@example.com",
    ) == [str(alice_cert), str(own_cert)]


def test_recipient_certificates_reports_missing_cert(monkeypatch, tmp_path):
    smime_dir = tmp_path / "smime"
    recipients_dir = smime_dir / "recipients"
    recipients_dir.mkdir(parents=True)
    paths = smime.SmimePaths(
        account="me@example.com",
        directory=str(smime_dir),
        cert=str(smime_dir / "own-cert.pem"),
        key=str(smime_dir / "own-key.pem"),
        ca_bundle=str(smime_dir / "ca-bundle.pem"),
        fullchain=str(smime_dir / "own-fullchain.p12"),
        recipients_dir=str(recipients_dir),
    )

    monkeypatch.setattr(smime, "require_configured", lambda account_email=None: ("me@example.com", paths))
    monkeypatch.setattr(smime, "verification_material", lambda account_email=None: ("me@example.com", paths))

    with pytest.raises(ValueError, match="Missing S/MIME recipient certificate"):
        smime.recipient_certificates(["alice@example.com"], account_email="me@example.com")


def test_build_text_mime_contains_expected_headers():
    mime_bytes = smime.build_text_mime(
        sender="me@example.com",
        to=["you@example.com"],
        subject="Status",
        body="Hello",
    )
    text = mime_bytes.decode("utf-8")

    assert "From: me@example.com" in text
    assert "To: you@example.com" in text
    assert "Subject: Status" in text
    assert "Hello" in text


def test_wrap_signed_entity_keeps_message_headers_outside_signature():
    wrapped = smime.wrap_signed_entity(
        sender="me@example.com",
        to=["you@example.com"],
        cc=[],
        bcc=[],
        subject="Status",
        signed_entity=b'MIME-Version: 1.0\r\nContent-Type: multipart/signed\r\n\r\nsigned',
    )

    assert wrapped.startswith(b"From: me@example.com\r\nTo: you@example.com\r\nSubject: Status\r\n")
    assert b"\r\nMIME-Version: 1.0\r\nContent-Type: multipart/signed" in wrapped


def test_sign_mime_calls_openssl_with_configured_paths(monkeypatch, tmp_path):
    smime_dir = tmp_path / "smime"
    smime_dir.mkdir()
    for name in ["own-cert.pem", "own-key.pem", "ca-bundle.pem"]:
        (smime_dir / name).write_text(name, encoding="utf-8")
    paths = smime.SmimePaths(
        account="me@example.com",
        directory=str(smime_dir),
        cert=str(smime_dir / "own-cert.pem"),
        key=str(smime_dir / "own-key.pem"),
        ca_bundle=str(smime_dir / "ca-bundle.pem"),
        fullchain=str(smime_dir / "own-fullchain.p12"),
        recipients_dir=str(smime_dir / "recipients"),
    )
    calls = []

    monkeypatch.setattr(smime, "require_configured", lambda account_email=None: ("me@example.com", paths))
    monkeypatch.setattr(smime, "verification_material", lambda account_email=None: ("me@example.com", paths))

    def run_openssl_file(args):
        calls.append(args)
        Path(args[args.index("-out") + 1]).write_text("signed", encoding="utf-8")

    monkeypatch.setattr(smime, "_run_openssl_file", run_openssl_file)

    unsigned_path, signed_path = smime.sign_mime(
        b"From: me@example.com\r\n\r\nHello",
        account_email="me@example.com",
        output_dir=str(tmp_path),
    )

    assert Path(unsigned_path).read_bytes() == b"From: me@example.com\r\n\r\nHello"
    assert Path(signed_path).read_text(encoding="utf-8") == "signed"
    assert calls == [
        [
            "smime",
            "-sign",
            "-in",
            str(tmp_path / "unsigned.eml"),
            "-signer",
            paths.cert,
            "-inkey",
            paths.key,
            "-certfile",
            paths.ca_bundle,
            "-out",
            str(tmp_path / "signed.eml"),
            "-outform",
            "SMIME",
        ]
    ]


def test_encrypt_mime_calls_openssl_with_recipient_certs(monkeypatch, tmp_path):
    smime_dir = tmp_path / "smime"
    recipients_dir = smime_dir / "recipients"
    recipients_dir.mkdir(parents=True)
    for name in ["own-cert.pem", "own-key.pem", "ca-bundle.pem"]:
        (smime_dir / name).write_text(name, encoding="utf-8")
    recipient_cert = recipients_dir / "alice@example.com.pem"
    recipient_cert.write_text("alice", encoding="utf-8")
    paths = smime.SmimePaths(
        account="me@example.com",
        directory=str(smime_dir),
        cert=str(smime_dir / "own-cert.pem"),
        key=str(smime_dir / "own-key.pem"),
        ca_bundle=str(smime_dir / "ca-bundle.pem"),
        fullchain=str(smime_dir / "own-fullchain.p12"),
        recipients_dir=str(recipients_dir),
    )
    calls = []

    monkeypatch.setattr(smime, "require_configured", lambda account_email=None: ("me@example.com", paths))
    monkeypatch.setattr(smime, "verification_material", lambda account_email=None: ("me@example.com", paths))

    def run_openssl_file(args):
        calls.append(args)
        Path(args[args.index("-out") + 1]).write_text("encrypted", encoding="utf-8")

    monkeypatch.setattr(smime, "_run_openssl_file", run_openssl_file)

    clear_path, encrypted_path = smime.encrypt_mime(
        b"Content-Type: text/plain\r\n\r\nsecret",
        recipients=["alice@example.com"],
        account_email="me@example.com",
        output_dir=str(tmp_path),
    )

    assert Path(clear_path).read_bytes() == b"Content-Type: text/plain\r\n\r\nsecret"
    assert Path(encrypted_path).read_text(encoding="utf-8") == "encrypted"
    assert calls == [
        [
            "smime",
            "-encrypt",
            "-aes256",
            "-in",
            str(tmp_path / "clear.eml"),
            "-out",
            str(tmp_path / "encrypted.eml"),
            "-outform",
            "SMIME",
            str(recipient_cert),
        ]
    ]


def test_decrypt_mime_bytes_calls_openssl_with_own_cert_and_key(monkeypatch, tmp_path):
    smime_dir = tmp_path / "smime"
    smime_dir.mkdir()
    paths = smime.SmimePaths(
        account="me@example.com",
        directory=str(smime_dir),
        cert=str(smime_dir / "own-cert.pem"),
        key=str(smime_dir / "own-key.pem"),
        ca_bundle=str(smime_dir / "ca-bundle.pem"),
        fullchain=str(smime_dir / "own-fullchain.p12"),
        recipients_dir=str(smime_dir / "recipients"),
    )
    calls = []

    monkeypatch.setattr(smime, "require_configured", lambda account_email=None: ("me@example.com", paths))
    monkeypatch.setattr(smime, "verification_material", lambda account_email=None: ("me@example.com", paths))

    def run_openssl_file(args):
        calls.append(args)
        Path(args[args.index("-out") + 1]).write_text("decrypted", encoding="utf-8")

    monkeypatch.setattr(smime, "_run_openssl_file", run_openssl_file)

    result = smime.decrypt_mime_bytes(
        b"encrypted",
        account_email="me@example.com",
        output_dir=str(tmp_path),
    )

    assert result.decrypted is True
    assert Path(result.encrypted_path).read_bytes() == b"encrypted"
    assert Path(result.decrypted_path).read_text(encoding="utf-8") == "decrypted"
    assert calls == [
        [
            "smime",
            "-decrypt",
            "-in",
            str(tmp_path / "encrypted.eml"),
            "-recip",
            paths.cert,
            "-inkey",
            paths.key,
            "-out",
            str(tmp_path / "decrypted.eml"),
        ]
    ]


def test_decrypt_mime_bytes_reports_decrypt_error(monkeypatch, tmp_path):
    paths = smime.SmimePaths(
        account="me@example.com",
        directory=str(tmp_path),
        cert=str(tmp_path / "own-cert.pem"),
        key=str(tmp_path / "own-key.pem"),
        ca_bundle=str(tmp_path / "ca-bundle.pem"),
        fullchain=str(tmp_path / "own-fullchain.p12"),
        recipients_dir=str(tmp_path / "recipients"),
    )

    monkeypatch.setattr(smime, "require_configured", lambda account_email=None: ("me@example.com", paths))
    monkeypatch.setattr(smime, "verification_material", lambda account_email=None: ("me@example.com", paths))
    monkeypatch.setattr(
        smime,
        "_run_openssl_file",
        lambda args: (_ for _ in ()).throw(ValueError("openssl failed: decrypt error")),
    )

    result = smime.decrypt_mime_bytes(
        b"encrypted",
        account_email="me@example.com",
        output_dir=str(tmp_path),
    )

    assert result.decrypted is False
    assert result.error == "openssl failed: decrypt error"


def test_verify_signed_mime_calls_openssl_verify(monkeypatch, tmp_path):
    smime_dir = tmp_path / "smime"
    smime_dir.mkdir()
    ca_bundle = smime_dir / "ca-bundle.pem"
    ca_bundle.write_text("ca", encoding="utf-8")
    paths = smime.SmimePaths(
        account="me@example.com",
        directory=str(smime_dir),
        cert=str(smime_dir / "own-cert.pem"),
        key=str(smime_dir / "own-key.pem"),
        ca_bundle=str(ca_bundle),
        fullchain=str(smime_dir / "own-fullchain.p12"),
        recipients_dir=str(smime_dir / "recipients"),
    )
    signed = tmp_path / "signed.eml"
    signed.write_text("signed", encoding="utf-8")
    calls = []

    monkeypatch.setattr(smime, "require_configured", lambda account_email=None: ("me@example.com", paths))
    monkeypatch.setattr(smime, "verification_material", lambda account_email=None: ("me@example.com", paths))

    def run_openssl_file(args):
        calls.append(args)
        Path(args[args.index("-out") + 1]).write_text("verified", encoding="utf-8")

    monkeypatch.setattr(smime, "_run_openssl_file", run_openssl_file)

    verified_path = smime.verify_signed_mime(
        str(signed),
        account_email="me@example.com",
        output_dir=str(tmp_path),
    )

    assert Path(verified_path).read_text(encoding="utf-8") == "verified"
    assert calls == [
        [
            "smime",
            "-verify",
            "-in",
            str(signed),
            "-CAfile",
            paths.ca_bundle,
            "-out",
            str(tmp_path / "verified.eml"),
        ]
    ]


def test_verify_signed_mime_bytes_returns_verified_result(monkeypatch, tmp_path):
    smime_dir = tmp_path / "smime"
    smime_dir.mkdir()
    ca_bundle = smime_dir / "ca-bundle.pem"
    ca_bundle.write_text("ca", encoding="utf-8")
    paths = smime.SmimePaths(
        account="me@example.com",
        directory=str(smime_dir),
        cert=str(smime_dir / "own-cert.pem"),
        key=str(smime_dir / "own-key.pem"),
        ca_bundle=str(ca_bundle),
        fullchain=str(smime_dir / "own-fullchain.p12"),
        recipients_dir=str(smime_dir / "recipients"),
    )

    monkeypatch.setattr(smime, "require_configured", lambda account_email=None: ("me@example.com", paths))
    monkeypatch.setattr(smime, "verification_material", lambda account_email=None: ("me@example.com", paths))

    def run_openssl_file(args):
        Path(args[args.index("-out") + 1]).write_text("verified", encoding="utf-8")

    monkeypatch.setattr(smime, "_run_openssl_file", run_openssl_file)

    result = smime.verify_signed_mime_bytes(
        b'Content-Type: multipart/signed\r\n\r\nbody',
        account_email="me@example.com",
        output_dir=str(tmp_path),
    )

    assert result.verified is True
    assert result.signed is True
    assert Path(result.verified_path).read_text(encoding="utf-8") == "verified"


def test_verify_signed_mime_bytes_reports_failed_signature(monkeypatch, tmp_path):
    paths = smime.SmimePaths(
        account="me@example.com",
        directory=str(tmp_path),
        cert=str(tmp_path / "own-cert.pem"),
        key=str(tmp_path / "own-key.pem"),
        ca_bundle=str(tmp_path / "ca-bundle.pem"),
        fullchain=str(tmp_path / "own-fullchain.p12"),
        recipients_dir=str(tmp_path / "recipients"),
    )
    monkeypatch.setattr(smime, "require_configured", lambda account_email=None: ("me@example.com", paths))
    monkeypatch.setattr(smime, "verification_material", lambda account_email=None: ("me@example.com", paths))
    monkeypatch.setattr(
        smime,
        "_run_openssl_file",
        lambda args: (_ for _ in ()).throw(ValueError("openssl failed: bad signature")),
    )

    result = smime.verify_signed_mime_bytes(
        b'Content-Type: multipart/signed\r\n\r\nbody',
        account_email="me@example.com",
        output_dir=str(tmp_path),
    )

    assert result.verified is False
    assert result.signed is True
    assert result.error == "openssl failed: bad signature"


def _fake_paths(tmp_path):
    smime_dir = tmp_path / "smime"
    smime_dir.mkdir(exist_ok=True)
    ca_bundle = smime_dir / "ca-bundle.pem"
    ca_bundle.write_text("ca", encoding="utf-8")
    return smime.SmimePaths(
        account="me@example.com",
        directory=str(smime_dir),
        cert=str(smime_dir / "own-cert.pem"),
        key=str(smime_dir / "own-key.pem"),
        ca_bundle=str(ca_bundle),
        fullchain=str(smime_dir / "own-fullchain.p12"),
        recipients_dir=str(smime_dir / "recipients"),
    )


def test_decrypt_removes_its_own_working_directory(monkeypatch, tmp_path):
    paths = _fake_paths(tmp_path)
    monkeypatch.setattr(smime, "require_configured", lambda account_email=None: ("me@example.com", paths))
    monkeypatch.setattr(smime, "verification_material", lambda account_email=None: ("me@example.com", paths))
    seen = {}

    def run_openssl_file(args):
        out = Path(args[args.index("-out") + 1])
        seen["directory"] = out.parent
        out.write_bytes(b"decrypted body")

    monkeypatch.setattr(smime, "_run_openssl_file", run_openssl_file)

    result = smime.decrypt_mime_bytes(b"encrypted", account_email="me@example.com")

    assert result.decrypted is True
    assert result.data == b"decrypted body"
    # No cleartext left behind, and no path handed out that points at it.
    assert not seen["directory"].exists()
    assert result.decrypted_path == ""
    assert result.encrypted_path == ""


def test_decrypt_failure_also_removes_the_working_directory(monkeypatch, tmp_path):
    paths = _fake_paths(tmp_path)
    monkeypatch.setattr(smime, "require_configured", lambda account_email=None: ("me@example.com", paths))
    monkeypatch.setattr(smime, "verification_material", lambda account_email=None: ("me@example.com", paths))
    seen = {}

    def run_openssl_file(args):
        seen["directory"] = Path(args[args.index("-out") + 1]).parent
        raise ValueError("openssl failed: no recipient matches")

    monkeypatch.setattr(smime, "_run_openssl_file", run_openssl_file)

    result = smime.decrypt_mime_bytes(b"encrypted", account_email="me@example.com")

    assert result.decrypted is False
    assert not seen["directory"].exists()


def test_verify_removes_its_own_working_directory(monkeypatch, tmp_path):
    paths = _fake_paths(tmp_path)
    monkeypatch.setattr(smime, "require_configured", lambda account_email=None: ("me@example.com", paths))
    monkeypatch.setattr(smime, "verification_material", lambda account_email=None: ("me@example.com", paths))
    seen = {}

    def run_openssl_file(args):
        out = Path(args[args.index("-out") + 1])
        seen["directory"] = out.parent
        out.write_bytes(b"verified body")

    monkeypatch.setattr(smime, "_run_openssl_file", run_openssl_file)

    result = smime.verify_signed_mime_bytes(
        b"Content-Type: multipart/signed\r\n\r\nbody",
        account_email="me@example.com",
    )

    assert result.verified is True
    assert result.data == b"verified body"
    assert not seen["directory"].exists()
    assert result.verified_path == ""


def test_caller_supplied_output_dir_is_kept(monkeypatch, tmp_path):
    paths = _fake_paths(tmp_path)
    monkeypatch.setattr(smime, "require_configured", lambda account_email=None: ("me@example.com", paths))
    monkeypatch.setattr(smime, "verification_material", lambda account_email=None: ("me@example.com", paths))
    monkeypatch.setattr(
        smime,
        "_run_openssl_file",
        lambda args: Path(args[args.index("-out") + 1]).write_bytes(b"decrypted body"),
    )
    output_dir = tmp_path / "keep"

    result = smime.decrypt_mime_bytes(
        b"encrypted",
        account_email="me@example.com",
        output_dir=str(output_dir),
    )

    assert output_dir.exists()
    assert result.decrypted_path == str(output_dir / "decrypted.eml")
    assert Path(result.decrypted_path).read_bytes() == b"decrypted body"


def test_discard_working_dir_refuses_foreign_directories(tmp_path):
    foreign = tmp_path / "important"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("keep", encoding="utf-8")

    smime.discard_working_dir(foreign)

    assert (foreign / "keep.txt").exists()


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("alice@example.com", "alice@example.com"),
        ("Alice@Example.COM", "alice@example.com"),
        ("../../../../tmp/pwned", ".._.._.._.._tmp_pwned"),
        ("a/b@example.com", "a_b@example.com"),
    ],
)
def test_recipient_filename_cannot_escape_the_recipients_directory(address, expected):
    filename = smime._recipient_filename(address)

    assert filename == expected
    assert "/" not in filename and ".." != filename
    target = Path("/state/smime/recipients") / f"{filename}.pem"
    assert target.resolve().parent == Path("/state/smime/recipients")


def test_verification_does_not_need_our_own_key(monkeypatch, tmp_path):
    """Verifying somebody else's signature must not require our private key."""
    smime_dir = tmp_path / "smime"
    smime_dir.mkdir()
    monkeypatch.setattr(smime.auth, "account_dir", lambda account: tmp_path)

    account, paths = smime.verification_material("me@example.com")

    assert account == "me@example.com"
    # Nothing exists yet, and that is fine.
    assert not Path(paths.key).exists()
    assert not Path(paths.cert).exists()


def test_trust_bundle_falls_back_to_the_system_store(tmp_path):
    paths = smime.SmimePaths(
        account="me@example.com",
        directory=str(tmp_path),
        cert=str(tmp_path / "own-cert.pem"),
        key=str(tmp_path / "own-key.pem"),
        ca_bundle=str(tmp_path / "missing-ca.pem"),
        fullchain=str(tmp_path / "own-fullchain.p12"),
        recipients_dir=str(tmp_path / "recipients"),
        trusted_ca=str(tmp_path / "missing-trusted.pem"),
    )

    # No local material: no -CAfile, so OpenSSL uses its default store.
    assert smime._trust_bundle(paths, tmp_path) is None


def test_trust_bundle_combines_own_ca_and_extra_anchors(tmp_path):
    ca_bundle = tmp_path / "ca-bundle.pem"
    ca_bundle.write_text("-----OWN CA-----", encoding="utf-8")
    trusted = tmp_path / "trusted-ca.pem"
    trusted.write_text("-----EXTRA CA-----", encoding="utf-8")
    paths = smime.SmimePaths(
        account="me@example.com",
        directory=str(tmp_path),
        cert=str(tmp_path / "own-cert.pem"),
        key=str(tmp_path / "own-key.pem"),
        ca_bundle=str(ca_bundle),
        fullchain=str(tmp_path / "own-fullchain.p12"),
        recipients_dir=str(tmp_path / "recipients"),
        trusted_ca=str(trusted),
    )

    bundle = smime._trust_bundle(paths, tmp_path)

    assert bundle is not None
    content = bundle.read_text(encoding="utf-8")
    assert "-----OWN CA-----" in content
    assert "-----EXTRA CA-----" in content


def test_empty_trusted_ca_path_is_not_mistaken_for_a_file(tmp_path):
    """SmimePaths built by callers leaves trusted_ca empty; Path("") is "."."""
    ca_bundle = tmp_path / "ca-bundle.pem"
    ca_bundle.write_text("-----OWN CA-----", encoding="utf-8")
    paths = smime.SmimePaths(
        account="me@example.com",
        directory=str(tmp_path),
        cert=str(tmp_path / "own-cert.pem"),
        key=str(tmp_path / "own-key.pem"),
        ca_bundle=str(ca_bundle),
        fullchain=str(tmp_path / "own-fullchain.p12"),
        recipients_dir=str(tmp_path / "recipients"),
    )

    bundle = smime._trust_bundle(paths, tmp_path)

    assert bundle is not None
    assert bundle.read_text(encoding="utf-8").strip() == "-----OWN CA-----"
