"""Regression tests for the September 2026 review.

All accounts, Graph responses and mail are synthetic. OpenSSL is real.
"""
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import msal
import pytest
from typer.testing import CliRunner

from msmail.cli import app
from msmail.core import auth, compose, drafts, graph, mail, render, smime


@pytest.fixture(autouse=True)
def isolate_state(monkeypatch, tmp_path):
    root = tmp_path / "state"
    monkeypatch.setattr(auth, "STATE_DIR", root)
    monkeypatch.setattr(auth, "STATE_FILE", root / "auth-state.json")
    monkeypatch.setattr(auth, "ACCOUNTS_DIR", root / "accounts")
    monkeypatch.setattr(auth, "_hardened_state_dirs", set())

    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected live network/auth call")

    monkeypatch.setattr(graph.request, "urlopen", forbidden)
    monkeypatch.setattr(auth, "_app", forbidden)


def fake_auth(monkeypatch):
    monkeypatch.setattr(auth, "get_access_token", lambda email=None: (
        "synthetic-token", auth.Account(email=email or "me@example.invalid")))


def make_draft(**kwargs):
    values = dict(to=["alice@example.invalid"], cc=[], bcc=[], subject="Review",
                  body="Synthetic review message", body_content_type="Text",
                  attachments=[], sign=False, encrypt=False)
    values.update(kwargs)
    return compose.ComposeDraft(**values)


def test_fetch_limit_applies_to_final_page(monkeypatch):
    pages = iter([
        {"value": [{"id": str(i)} for i in range(100)], "@odata.nextLink": "https://example.invalid/p2"},
        {"value": [{"id": str(i)} for i in range(100, 200)]},
    ])
    monkeypatch.setattr(graph, "get_json", lambda *a, **kw: next(pages))
    rows, _, _ = mail._collect_pages("/me/messages", "fake", {}, fetch=150)
    assert len(rows) == 150


def test_default_list_filter_contains_all_orderby_properties(monkeypatch):
    fake_auth(monkeypatch)
    requests = []
    monkeypatch.setattr(graph, "get_json", lambda path, token, params=None:
                        requests.append(params) or {"value": []})
    mail.list_messages()
    query = requests[0]
    for ordering in query["$orderby"].split(","):
        assert ordering.split()[0] in query["$filter"], query


def test_forward_cc_bcc_are_nested_in_message(monkeypatch):
    fake_auth(monkeypatch)
    calls = []
    monkeypatch.setattr(graph, "post_json", lambda path, token, body:
                        calls.append(body) or {"id": "draft-id"})
    response = compose.ResponseDraft(
        to=["alice@example.invalid"], cc=["cc@example.invalid"],
        bcc=["bcc@example.invalid"], body="FYI", body_content_type="Text")
    drafts.create_forward_draft("message-id", response, include_signature=False)
    assert calls[0].get("message", {}).get("ccRecipients")
    assert calls[0]["message"].get("bccRecipients")


@pytest.fixture
def certificates(tmp_path):
    if not shutil.which("openssl"):
        pytest.skip("OpenSSL is required for the S/MIME integration tests")
    certs = {}
    for name in ("me", "alice"):
        cert = tmp_path / f"{name}.pem"
        key = tmp_path / f"{name}.key"
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-days", "1", "-subj", f"/CN={name}/emailAddress={name}@example.invalid",
            "-addext", "extendedKeyUsage=emailProtection",
            "-addext", f"subjectAltName=email:{name}@example.invalid",
            "-keyout", str(key), "-out", str(cert),
        ], check=True, capture_output=True)
        certs[name] = (cert, key)
    bundle = tmp_path / "bundle.pem"
    bundle.write_bytes(b"".join(cert.read_bytes() for cert, _ in certs.values()))
    for name, (cert, key) in certs.items():
        smime.setup(cert=str(cert), key=str(key), ca_bundle=str(bundle),
                    account_email=f"{name}@example.invalid")
    smime.import_recipient_certificate(cert=str(certs["alice"][0]),
                                      account_email="me@example.invalid")
    return certs


def test_sender_can_decrypt_own_encrypted_draft(monkeypatch, certificates):
    fake_auth(monkeypatch)
    uploaded = []
    monkeypatch.setattr(graph, "post_mime_json", lambda path, token, data:
                        uploaded.append(data) or {"id": "encrypted-draft"})
    drafts.create_draft(make_draft(encrypt=True), include_signature=False)
    recipient = smime.decrypt_mime_bytes(uploaded[0], account_email="alice@example.invalid")
    assert recipient.decrypted, recipient.error
    sender = smime.decrypt_mime_bytes(uploaded[0], account_email="me@example.invalid")
    assert sender.decrypted, sender.error


def test_signature_trust_requires_matching_from_address(monkeypatch, certificates):
    fake_auth(monkeypatch)
    entity = smime.build_mime_entity(body="Synthetic content", content_type="Text")
    _, signed_path = smime.sign_mime(entity, account_email="alice@example.invalid")
    try:
        signed = Path(signed_path).read_bytes()
    finally:
        smime.discard_working_dir(Path(signed_path).parent)
    # Positive control: the content signature and trusted test certificate work.
    verified = smime.verify_signed_mime_bytes(signed, account_email="me@example.invalid")
    assert verified.verified, verified.error
    assert verified.signer_certificate.emails == ["alice@example.invalid"]
    forged = smime.wrap_mime_entity(
        sender="different-person@example.invalid", to=["me@example.invalid"],
        cc=[], bcc=[], subject="Synthetic sender mismatch", entity=signed)
    monkeypatch.setattr(graph, "get_json", lambda *a, **kw: {
        "id": "message-id", "subject": "Synthetic sender mismatch",
        "from": {"emailAddress": {"address": "different-person@example.invalid"}},
        "body": {"contentType": "text", "content": "Synthetic content"},
        "hasAttachments": False,
    })
    monkeypatch.setattr(mail, "get_message_mime", lambda *a, **kw:
                        (forged, "me@example.invalid"))
    result = CliRunner().invoke(app, ["read", "--id", "message-id", "--verify-smime", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["smime"]["trusted"] is False, payload["smime"]


@pytest.fixture
def alias_login(monkeypatch):
    class OfflineApp:
        # Real MSAL cache lookup/filtering; only the authentication is synthetic.
        get_accounts = msal.PublicClientApplication.get_accounts
        _find_msal_accounts = msal.PublicClientApplication._find_msal_accounts

        def __init__(self, cache):
            self.token_cache = cache
            self.authority = SimpleNamespace(instance="login.microsoftonline.com")

        def _get_authority_aliases(self, instance):
            return []

        def initiate_device_flow(self, scopes):
            return dict(user_code="TEST", verification_uri="https://example.invalid", message="test")

        def acquire_token_by_device_flow(self, flow):
            self.token_cache.deserialize(json.dumps({"Account": {"test-account": {
                "home_account_id": "test.tenant", "environment": self.authority.instance,
                "username": "login@example.invalid", "authority_type": "MSSTS",
                "realm": "test-tenant", "local_account_id": "test",
            }}}))
            self.token_cache.has_state_changed = True
            return {"access_token": "synthetic-token"}

        def acquire_token_silent(self, scopes, account):
            return {"access_token": "synthetic-token"}

    monkeypatch.setattr(auth, "_app", OfflineApp)
    monkeypatch.setattr(graph, "get_json", lambda *a, **kw: {
        "mail": "canonical@example.invalid", "userPrincipalName": "login@example.invalid"})
    return auth.login("login@example.invalid")


def test_login_with_different_primary_mail_remains_usable(alias_login):
    token, account = auth.get_access_token()
    assert token == "synthetic-token"
    assert account.email == "canonical@example.invalid"
    alias_token, alias_account = auth.get_access_token("login@example.invalid")
    assert alias_token == token
    assert alias_account.email == account.email


def test_logout_removes_alias_token_copy(alias_login):
    assert auth.logout()
    assert list(auth.ACCOUNTS_DIR.glob("*/msal-token-cache.json")) == []


def test_mail_body_is_rendered_as_literal_text(monkeypatch):
    fake_auth(monkeypatch)
    monkeypatch.setattr(graph, "get_json", lambda *a, **kw: {
        "id": "message-id", "subject": "Review",
        "body": {"contentType": "text", "content": "Literal text [/unexpected]"},
        "hasAttachments": False,
    })
    result = CliRunner().invoke(app, ["read", "--id", "message-id"])
    assert result.exit_code == 0, repr(result.exception)
    assert "Literal text [/unexpected]" in result.output


def test_safelink_preserves_original_percent_encoding():
    original = "https://example.invalid/a%2Fb?x=%2520"
    wrapped = "https://eur01.safelinks.protection.outlook.com/?" + urlencode({"url": original})
    assert render.unwrap_safelink(wrapped) == original


def test_compose_preserves_attachment_with_comma_in_name():
    path = "/tmp/report,final.pdf"
    template = compose.compose_template(
        to="alice@example.invalid", subject="Report", attach=path, body="Review")
    parsed = compose.parse_compose_text(template)
    assert parsed.attachments == [path]


def test_sign_verify_checks_matching_and_missing_sender(monkeypatch, certificates):
    entity = smime.build_mime_entity(body="Review content", content_type="Text")
    _, signed_path = smime.sign_mime(entity, account_email="alice@example.invalid")
    try:
        signed = Path(signed_path).read_bytes()
    finally:
        smime.discard_working_dir(Path(signed_path).parent)
    matching = smime.verify_signed_mime_bytes(
        signed, account_email="me@example.invalid", expected_sender="ALICE@example.invalid")
    assert matching.verified and matching.trusted and matching.sender_matches
    missing = smime.verify_signed_mime_bytes(
        signed, account_email="me@example.invalid", expected_sender="")
    assert missing.verified and not missing.trusted and missing.sender_matches is False
    tampered = smime.verify_signed_mime_bytes(
        signed.replace(b"Review content", b"Changed content"),
        account_email="me@example.invalid", expected_sender="alice@example.invalid")
    assert not tampered.verified and not tampered.trusted


def test_logout_removes_legacy_alias_copy_but_preserves_other_account(alias_login):
    original = auth._token_cache_path("canonical@example.invalid")
    alias = auth._token_cache_path("old-alias@example.invalid")
    auth.write_private_text(alias, original.read_text())
    other = auth._token_cache_path("unrelated@example.invalid")
    auth.write_private_text(other, json.dumps({"Account": {"other": {
        "home_account_id": "other.tenant", "username": "unrelated@example.invalid"}}}))
    assert auth.logout()
    assert not original.exists() and not alias.exists()
    assert other.exists()


def test_saved_identity_takes_precedence_over_changed_username():
    identity = {"home_account_id": "stable.tenant", "username": "new@example.invalid"}
    profile = auth.Account(email="old@example.invalid", home_account_id="stable.tenant")
    assert auth._select_account([identity], profile.email, profile) == identity
    unrelated = {"home_account_id": "unrelated.tenant", "username": profile.email}
    assert auth._select_account([unrelated], profile.email, profile) is None


def test_legacy_profile_resolves_by_upn_without_guessing():
    correct = {"home_account_id": "a", "username": "login@example.invalid"}
    other = {"home_account_id": "b", "username": "other@example.invalid"}
    profile = auth.Account(email="primary@example.invalid", user_principal_name=correct["username"])
    assert auth._select_account([correct, other], profile.email, profile) == correct
    assert auth._select_account([correct, other], "unknown@example.invalid", None) is None


@pytest.mark.parametrize("action", ["reply", "forward"])
def test_html_response_retains_content_type_and_recipients(monkeypatch, action):
    fake_auth(monkeypatch)
    calls = []
    monkeypatch.setattr(graph, "post_json", lambda path, token, body:
                        calls.append(body) or {"id": "draft-id"})
    response = compose.ResponseDraft(to=["alice@example.invalid"], cc=[], bcc=[],
                                     body="<p>HTML reply</p>", body_content_type="HTML")
    create = drafts.create_reply_draft if action == "reply" else drafts.create_forward_draft
    create("message-id", response, include_signature=False)
    assert "comment" not in calls[0]
    assert calls[0]["message"]["body"] == {"contentType": "HTML", "content": response.body}
    assert calls[0]["message"]["toRecipients"][0]["emailAddress"]["address"] == response.to[0]


@pytest.mark.parametrize("paths", [
    ["report,final.pdf", "data;2026.csv"],
    ['a "quote".txt', r"C:\Users\Example\file,final.txt"],
    [" leading and trailing spaces ", "[report].pdf"],
])
def test_attachment_paths_round_trip_without_ambiguity(paths):
    template = compose.compose_template(to="a@example.invalid", subject="Files",
                                        attachments=paths, body="Review")
    assert compose.parse_compose_text(template).attachments == paths


def test_draft_create_preserves_repeated_attachment_arguments(monkeypatch):
    captured = []

    def create(draft, **kwargs):
        captured.append(draft)
        return drafts.DraftResult("me@example.invalid", "draft", draft.subject, draft.to, draft.attachments)

    monkeypatch.setattr(drafts, "create_draft", create)
    result = CliRunner().invoke(app, ["draft", "create", "--to", "a@example.invalid",
        "--subject", "Files", "--body", "Review", "-a", "report,final.pdf", "-a", "data;2026.csv"])
    assert result.exit_code == 0, result.output
    assert captured[0].attachments == ["report,final.pdf", "data;2026.csv"]


def test_safelink_lookalike_domain_is_not_unwrapped():
    url = "https://safelinks.protection.outlook.com.example.invalid/?url=https%3A%2F%2Fexample.invalid"
    assert render.unwrap_safelink(url) == url


@pytest.mark.parametrize("sender", ["alice@example.invalid", "different@example.invalid"])
def test_save_signed_attachments_checks_sender_without_decrypt(monkeypatch, certificates, tmp_path, sender):
    fake_auth(monkeypatch)
    entity = smime.build_mime_entity(body="Review", content_type="Text",
                                     attachments=[("review.txt", "text/plain", b"attachment data")])
    _, signed_path = smime.sign_mime(entity, account_email="alice@example.invalid")
    try:
        signed = Path(signed_path).read_bytes()
    finally:
        smime.discard_working_dir(Path(signed_path).parent)
    monkeypatch.setattr(graph, "get_json", lambda *a, **kw: {
        "id": "message-id", "from": {"emailAddress": {"address": sender}}, "hasAttachments": False})
    monkeypatch.setattr(mail, "get_message_mime", lambda *a, **kw: (signed, "me@example.invalid"))
    destination = tmp_path / "saved"
    if sender == "alice@example.invalid":
        result = mail.save_attachments("message-id", destination=str(destination), verify_smime=True)
        assert len(result.saved) == 1
        assert (destination / "review.txt").read_bytes() == b"attachment data"
    else:
        with pytest.raises(ValueError, match="does not match"):
            mail.save_attachments("message-id", destination=str(destination), verify_smime=True)
        assert not list(destination.iterdir())


def test_missing_created_draft_id_does_not_report_success(monkeypatch):
    fake_auth(monkeypatch)
    monkeypatch.setattr(graph, "post_json", lambda *a, **kw: {})
    with pytest.raises(graph.GraphError, match="no usable draft ID"):
        drafts.create_draft(make_draft(), include_signature=False)


def test_attachment_upload_failure_reports_retained_draft(monkeypatch, tmp_path):
    fake_auth(monkeypatch)
    attachment = tmp_path / "file.txt"
    attachment.write_text("Synthetic attachment")

    def post(path, *a, **kw):
        if path == "/me/messages":
            return {"id": "retained-draft"}
        raise graph.GraphError("synthetic upload failure")

    monkeypatch.setattr(graph, "post_json", post)
    with pytest.raises(graph.GraphError, match="Draft retained-draft was created, but attachment upload failed"):
        drafts.create_draft(make_draft(attachments=[str(attachment)]), include_signature=False)
