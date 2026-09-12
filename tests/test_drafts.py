import pytest

from msmail.core import compose, drafts


class Account:
    email = "me@example.com"


def make_draft(**overrides):
    values = {
        "to": ["alice@example.com"],
        "cc": [],
        "bcc": [],
        "subject": "Status",
        "body": "Done.",
        "body_content_type": "Text",
        "attachments": [],
        "sign": False,
        "encrypt": False,
    }
    values.update(overrides)
    return compose.ComposeDraft(**values)


def make_detail(message_id="message/id"):
    return drafts.mail.MessageDetail(
        account="me@example.com",
        id=message_id,
        subject="Status",
        from_name="Alice",
        from_address="alice@example.com",
        to_addresses=["me@example.com"],
        cc_addresses=[],
        received_date_time="2026-06-28T10:00:00Z",
        internet_message_id="<message@example.com>",
        body_content_type="text",
        body_content="Hello",
        body_preview="Hello",
        has_attachments=False,
        attachment_count=0,
        attachments=[],
        smime_signed=False,
        smime_encrypted=False,
    )


def test_create_draft_posts_expected_graph_payload(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )

    def post_json(path, access_token, body):
        captured["path"] = path
        captured["access_token"] = access_token
        captured["body"] = body
        return {"id": "draft-id", "subject": "Status"}

    monkeypatch.setattr(drafts.graph, "post_json", post_json)

    result = drafts.create_draft(
        make_draft(cc=["carol@example.com"], bcc=["dan@example.com"])
    )

    assert result.id == "draft-id"
    assert result.account == "me@example.com"
    assert captured == {
        "path": "/me/messages",
        "access_token": "token",
        "body": {
            "subject": "Status",
            "body": {"contentType": "Text", "content": "Done."},
            "toRecipients": [{"emailAddress": {"address": "alice@example.com"}}],
            "ccRecipients": [{"emailAddress": {"address": "carol@example.com"}}],
            "bccRecipients": [{"emailAddress": {"address": "dan@example.com"}}],
        },
    }


def test_create_draft_appends_text_signature(monkeypatch, tmp_path):
    captured = {}
    account_dir = tmp_path / "account"
    account_dir.mkdir()
    (account_dir / "signature.txt").write_text("--\nAlex", encoding="utf-8")

    monkeypatch.setattr(drafts.auth, "account_dir", lambda account: account_dir)
    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )

    def post_json(path, access_token, body):
        captured["body"] = body
        return {"id": "draft-id", "subject": "Status"}

    monkeypatch.setattr(drafts.graph, "post_json", post_json)

    drafts.create_draft(make_draft())

    assert captured["body"]["body"] == {
        "contentType": "Text",
        "content": "Done.\n\n--\nAlex",
    }


def test_create_draft_appends_html_signature(monkeypatch, tmp_path):
    captured = {}
    account_dir = tmp_path / "account"
    account_dir.mkdir()
    (account_dir / "signature.html").write_text("<p>Alex</p>", encoding="utf-8")

    monkeypatch.setattr(drafts.auth, "account_dir", lambda account: account_dir)
    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )

    def post_json(path, access_token, body):
        captured["body"] = body
        return {"id": "draft-id", "subject": "Status"}

    monkeypatch.setattr(drafts.graph, "post_json", post_json)

    drafts.create_draft(make_draft(body="<p>Done.</p>", body_content_type="HTML"))

    assert captured["body"]["body"] == {
        "contentType": "HTML",
        "content": "<p>Done.</p><br><br>\n<p>Alex</p>",
    }


def test_create_draft_formats_plain_text_html_body(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )

    def post_json(path, access_token, body):
        captured["body"] = body
        return {"id": "draft-id", "subject": "Status"}

    monkeypatch.setattr(drafts.graph, "post_json", post_json)

    drafts.create_draft(
        make_draft(
            body="Hello <Alex>\nsecond line\n\nNext paragraph",
            body_content_type="HTML",
        ),
        include_signature=False,
    )

    assert captured["body"]["body"] == {
        "contentType": "HTML",
        "content": (
            '<div style="font-family: Arial, sans-serif; font-size: 10pt;">\n'
            "<p>Hello &lt;Alex&gt;<br>\nsecond line</p>\n"
            "<p>Next paragraph</p>\n"
            "</div>"
        ),
    }


def test_create_draft_keeps_explicit_html_body(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )

    def post_json(path, access_token, body):
        captured["body"] = body
        return {"id": "draft-id", "subject": "Status"}

    monkeypatch.setattr(drafts.graph, "post_json", post_json)

    drafts.create_draft(
        make_draft(body="<h1>Hello</h1>", body_content_type="HTML"),
        include_signature=False,
    )

    assert captured["body"]["body"] == {
        "contentType": "HTML",
        "content": "<h1>Hello</h1>",
    }


def test_create_draft_can_skip_signature(monkeypatch, tmp_path):
    captured = {}
    account_dir = tmp_path / "account"
    account_dir.mkdir()
    (account_dir / "signature.txt").write_text("--\nAlex", encoding="utf-8")

    monkeypatch.setattr(drafts.auth, "account_dir", lambda account: account_dir)
    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )

    def post_json(path, access_token, body):
        captured["body"] = body
        return {"id": "draft-id", "subject": "Status"}

    monkeypatch.setattr(drafts.graph, "post_json", post_json)

    drafts.create_draft(make_draft(), include_signature=False)

    assert captured["body"]["body"]["content"] == "Done."


def test_create_and_send_uses_created_draft_account(monkeypatch):
    sent = []
    monkeypatch.setattr(
        drafts,
        "create_draft",
        lambda draft, account_email=None, include_signature=True: drafts.DraftResult(
            account="me@example.com",
            id="draft-id",
            subject=draft.subject,
            to=draft.to,
            attachments=["report.txt"],
        ),
    )
    monkeypatch.setattr(
        drafts,
        "send_draft",
        lambda draft_id, account_email=None: sent.append((draft_id, account_email)),
    )

    result = drafts.create_and_send(make_draft(), account_email="alias@example.com")

    assert sent == [("draft-id", "me@example.com")]
    assert result == drafts.SentMessageResult(
        account="me@example.com",
        id="draft-id",
        subject="Status",
        to=["alice@example.com"],
        attachments=["report.txt"],
        sent=True,
    )


def test_create_signed_draft_posts_only_signed_mime(monkeypatch, tmp_path):
    posted = {}
    signed = tmp_path / "signed.eml"
    signed.write_bytes(b"signed mime")

    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    monkeypatch.setattr(
        drafts.smime,
        "build_mime_message",
        lambda **kwargs: b"unsigned mime",
    )
    monkeypatch.setattr(
        drafts.smime,
        "sign_mime",
        lambda mime_bytes, account_email=None: (str(tmp_path / "unsigned.eml"), str(signed)),
    )

    def post_mime_json(path, access_token, mime_bytes):
        posted["path"] = path
        posted["access_token"] = access_token
        posted["mime_bytes"] = mime_bytes
        return {"id": "signed-draft-id", "subject": "Status"}

    def fail_post_json(*args, **kwargs):
        raise AssertionError("signed draft must not use JSON message creation")

    monkeypatch.setattr(drafts.graph, "post_mime_json", post_mime_json)
    monkeypatch.setattr(drafts.graph, "post_json", fail_post_json)

    result = drafts.create_draft(make_draft(sign=True))

    assert result.id == "signed-draft-id"
    assert posted["path"] == "/me/messages"
    assert posted["access_token"] == "token"
    assert b"From: me@example.com" in posted["mime_bytes"]
    assert b"To: alice@example.com" in posted["mime_bytes"]
    assert b"Subject: Status" in posted["mime_bytes"]
    assert posted["mime_bytes"].endswith(b"signed mime")


def test_create_encrypted_draft_posts_only_encrypted_mime(monkeypatch, tmp_path):
    posted = {}
    attachment = tmp_path / "report.txt"
    attachment.write_text("hello", encoding="utf-8")
    encrypted = tmp_path / "encrypted.eml"
    encrypted.write_bytes(b"encrypted mime")

    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    monkeypatch.setattr(
        drafts.smime,
        "encrypt_mime",
        lambda mime_bytes, recipients, account_email=None: (str(tmp_path / "clear.eml"), str(encrypted)),
    )

    def post_mime_json(path, access_token, mime_bytes):
        posted["path"] = path
        posted["access_token"] = access_token
        posted["mime_bytes"] = mime_bytes
        return {"id": "encrypted-draft-id", "subject": "Status"}

    def fail_post_json(*args, **kwargs):
        raise AssertionError("encrypted draft must not use JSON message creation")

    monkeypatch.setattr(drafts.graph, "post_mime_json", post_mime_json)
    monkeypatch.setattr(drafts.graph, "post_json", fail_post_json)

    result = drafts.create_draft(make_draft(encrypt=True, attachments=[str(attachment)]))

    assert result.id == "encrypted-draft-id"
    assert result.attachments == ["report.txt"]
    assert posted["path"] == "/me/messages"
    assert posted["access_token"] == "token"
    assert b"From: me@example.com" in posted["mime_bytes"]
    assert b"To: alice@example.com" in posted["mime_bytes"]
    assert b"Subject: Status" in posted["mime_bytes"]
    assert posted["mime_bytes"].endswith(b"encrypted mime")


def test_create_sign_and_encrypt_draft_signs_before_encrypting(monkeypatch, tmp_path):
    calls = []
    signed = tmp_path / "signed.eml"
    signed.write_bytes(b"signed mime")
    encrypted = tmp_path / "encrypted.eml"
    encrypted.write_bytes(b"encrypted mime")

    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )

    def sign_mime(mime_bytes, account_email=None):
        calls.append(("sign", mime_bytes, account_email))
        return str(tmp_path / "unsigned.eml"), str(signed)

    def encrypt_mime(mime_bytes, recipients, account_email=None):
        calls.append(("encrypt", mime_bytes, recipients, account_email))
        return str(tmp_path / "clear.eml"), str(encrypted)

    monkeypatch.setattr(drafts.smime, "sign_mime", sign_mime)
    monkeypatch.setattr(drafts.smime, "encrypt_mime", encrypt_mime)
    monkeypatch.setattr(
        drafts.graph,
        "post_mime_json",
        lambda path, access_token, mime_bytes: {"id": "draft-id", "subject": "Status"},
    )

    drafts.create_draft(make_draft(sign=True, encrypt=True, cc=["carol@example.com"]))

    assert calls[0][0] == "sign"
    assert calls[1] == ("encrypt", b"signed mime", ["alice@example.com", "carol@example.com"], "me@example.com")


def test_create_draft_uploads_attachments(monkeypatch, tmp_path):
    attachment = tmp_path / "report.txt"
    attachment.write_text("hello", encoding="utf-8")
    calls = []

    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )

    def post_json(path, access_token, body):
        calls.append((path, access_token, body))
        if path == "/me/messages":
            return {"id": "draft/id", "subject": "Status"}
        return {"id": "attachment-id"}

    monkeypatch.setattr(drafts.graph, "post_json", post_json)

    result = drafts.create_draft(make_draft(attachments=[str(attachment)]))

    assert result.attachments == ["report.txt"]
    assert calls[1] == (
        "/me/messages/draft%2Fid/attachments",
        "token",
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "report.txt",
            "contentType": "text/plain",
            "contentBytes": "aGVsbG8=",
        },
    )


@pytest.mark.parametrize("overrides", [{"sign": True}, {"encrypt": True}, {"sign": True, "encrypt": True}])
def test_update_draft_rejects_smime_features(overrides):
    with pytest.raises(ValueError, match="cannot be edited"):
        drafts.update_draft("draft-id", make_draft(**overrides))


def test_create_draft_rejects_missing_attachment(monkeypatch):
    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    monkeypatch.setattr(
        drafts.graph,
        "post_json",
        lambda path, access_token, body: {"id": "draft-id", "subject": "Status"},
    )

    with pytest.raises(ValueError, match="Attachment not found"):
        drafts.create_draft(make_draft(attachments=["missing.pdf"]))


def test_create_draft_uses_upload_session_for_large_attachment(monkeypatch, tmp_path):
    attachment = tmp_path / "large.bin"
    attachment.write_bytes(b"x" * (drafts.MAX_SIMPLE_ATTACHMENT_BYTES + 1))
    post_calls = []
    put_calls = []

    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )

    def post_json(path, access_token, body):
        post_calls.append((path, access_token, body))
        if path == "/me/messages":
            return {"id": "draft-id", "subject": "Status"}
        return {"uploadUrl": "https://upload.example/session"}

    def put_bytes(url, data, headers=None):
        put_calls.append((url, data, headers))
        return {}

    monkeypatch.setattr(drafts.graph, "post_json", post_json)
    monkeypatch.setattr(drafts.graph, "put_bytes", put_bytes)

    result = drafts.create_draft(make_draft(attachments=[str(attachment)]))

    assert result.attachments == ["large.bin"]
    assert post_calls[1] == (
        "/me/messages/draft-id/attachments/createUploadSession",
        "token",
        {
            "AttachmentItem": {
                "attachmentType": "file",
                "name": "large.bin",
                "size": drafts.MAX_SIMPLE_ATTACHMENT_BYTES + 1,
                "contentType": "application/octet-stream",
            }
        },
    )
    assert put_calls == [
        (
            "https://upload.example/session",
            b"x" * (drafts.MAX_SIMPLE_ATTACHMENT_BYTES + 1),
            {
                "Content-Length": str(drafts.MAX_SIMPLE_ATTACHMENT_BYTES + 1),
                "Content-Range": f"bytes 0-{drafts.MAX_SIMPLE_ATTACHMENT_BYTES}/{drafts.MAX_SIMPLE_ATTACHMENT_BYTES + 1}",
            },
        )
    ]


def test_create_draft_rejects_attachment_above_session_limit(monkeypatch, tmp_path):
    attachment = tmp_path / "too-large.bin"
    with attachment.open("wb") as handle:
        handle.truncate(drafts.MAX_UPLOAD_SESSION_ATTACHMENT_BYTES + 1)

    with pytest.raises(ValueError, match="too large"):
        drafts.create_draft(make_draft(attachments=[str(attachment)]))


def test_send_draft_posts_to_send_endpoint(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )

    def post_empty(path, access_token):
        captured["path"] = path
        captured["access_token"] = access_token

    monkeypatch.setattr(drafts.graph, "post_empty", post_empty)

    drafts.send_draft("AAMk/id with spaces")

    assert captured == {
        "path": "/me/messages/AAMk%2Fid%20with%20spaces/send",
        "access_token": "token",
    }


def test_create_reply_draft_posts_to_create_reply(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        drafts.mail,
        "resolve_message_reference",
        lambda reference, account_email=None: ("message/id", "me@example.com"),
    )
    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )

    def post_json(path, access_token, body):
        captured["path"] = path
        captured["access_token"] = access_token
        captured["body"] = body
        return {
            "id": "reply-draft-id",
            "subject": "Re: Status",
            "toRecipients": [{"emailAddress": {"address": "alice@example.com"}}],
        }

    monkeypatch.setattr(drafts.graph, "post_json", post_json)

    result = drafts.create_reply_draft(
        "1",
        compose.ResponseDraft(to=[], cc=[], bcc=[], body="Thanks.", body_content_type="Text"),
    )

    assert result.id == "reply-draft-id"
    assert result.response_type == "reply"
    assert result.to == ["alice@example.com"]
    assert captured == {
        "path": "/me/messages/message%2Fid/createReply",
        "access_token": "token",
        "body": {"comment": "Thanks."},
    }


def test_create_reply_all_draft_posts_to_create_reply_all(monkeypatch):
    monkeypatch.setattr(
        drafts.mail,
        "resolve_message_reference",
        lambda reference, account_email=None: ("message/id", "me@example.com"),
    )
    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    captured = {}

    def post_json(path, access_token, body):
        captured["path"] = path
        return {"id": "reply-draft-id", "subject": "Re: Status"}

    monkeypatch.setattr(drafts.graph, "post_json", post_json)

    result = drafts.create_reply_draft(
        "1",
        compose.ResponseDraft(to=[], cc=[], bcc=[], body="Thanks.", body_content_type="Text"),
        reply_all=True,
    )

    assert result.response_type == "reply-all"
    assert captured["path"] == "/me/messages/message%2Fid/createReplyAll"


def test_create_signed_reply_uses_mime_draft(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        drafts.mail,
        "resolve_message_reference",
        lambda reference, account_email=None: ("message/id", "me@example.com"),
    )
    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    monkeypatch.setattr(drafts.mail, "get_message", lambda message_id, account_email=None, include_attachment_details=True: make_detail(message_id))

    def create_draft(draft, account_email=None, include_signature=True):
        captured["draft"] = draft
        return drafts.DraftResult(
            account="me@example.com",
            id="draft-id",
            subject=draft.subject,
            to=draft.to,
            attachments=[],
        )

    monkeypatch.setattr(drafts, "create_draft", create_draft)

    result = drafts.create_reply_draft(
        "1",
        compose.ResponseDraft(to=[], cc=[], bcc=[], body="Thanks.", body_content_type="Text"),
        sign=True,
    )

    assert result.id == "draft-id"
    assert captured["draft"].to == ["alice@example.com"]
    assert captured["draft"].subject == "Re: Status"
    assert captured["draft"].sign is True


def test_create_forward_draft_posts_to_create_forward(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        drafts.mail,
        "resolve_message_reference",
        lambda reference, account_email=None: ("message/id", "me@example.com"),
    )
    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )

    def post_json(path, access_token, body):
        captured["path"] = path
        captured["access_token"] = access_token
        captured["body"] = body
        return {"id": "forward-draft-id", "subject": "Fwd: Status"}

    monkeypatch.setattr(drafts.graph, "post_json", post_json)

    response = compose.ResponseDraft(
        to=["bob@example.com"],
        cc=["carol@example.com"],
        bcc=[],
        body="FYI",
        body_content_type="Text",
    )
    result = drafts.create_forward_draft("1", response)

    assert result.id == "forward-draft-id"
    assert result.response_type == "forward"
    assert result.to == ["bob@example.com"]
    assert captured == {
        "path": "/me/messages/message%2Fid/createForward",
        "access_token": "token",
        "body": {
            "comment": "FYI",
            "message": {
                "toRecipients": [{"emailAddress": {"address": "bob@example.com"}}],
                "ccRecipients": [{"emailAddress": {"address": "carol@example.com"}}],
            },
        },
    }


def test_create_forward_draft_requires_recipient():
    with pytest.raises(ValueError, match="To recipient"):
        drafts.create_forward_draft(
            "1",
            compose.ResponseDraft(to=[], cc=[], bcc=[], body="FYI", body_content_type="Text"),
        )


def test_create_encrypted_forward_uses_mime_draft(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        drafts.mail,
        "resolve_message_reference",
        lambda reference, account_email=None: ("message/id", "me@example.com"),
    )
    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    monkeypatch.setattr(drafts.mail, "get_message", lambda message_id, account_email=None, include_attachment_details=True: make_detail(message_id))

    def create_draft(draft, account_email=None, include_signature=True):
        captured["draft"] = draft
        return drafts.DraftResult(
            account="me@example.com",
            id="draft-id",
            subject=draft.subject,
            to=draft.to,
            attachments=[],
        )

    monkeypatch.setattr(drafts, "create_draft", create_draft)

    result = drafts.create_forward_draft(
        "1",
        compose.ResponseDraft(to=["bob@example.com"], cc=[], bcc=[], body="FYI", body_content_type="Text"),
        encrypt=True,
    )

    assert result.id == "draft-id"
    assert captured["draft"].to == ["bob@example.com"]
    assert captured["draft"].subject == "Fwd: Status"
    assert captured["draft"].encrypt is True


def test_compose_template_for_draft_allows_existing_normal_attachments(monkeypatch):
    calls = []

    monkeypatch.setattr(
        drafts.mail,
        "resolve_message_reference",
        lambda reference, account_email=None: ("draft/id", "me@example.com"),
    )
    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )

    def get_json(path, access_token, params=None):
        calls.append((path, access_token, params))
        if path == "/me/messages/draft%2Fid":
            return {
                "id": "draft/id",
                "subject": "Status",
                "from": {"emailAddress": {"address": "me@example.com"}},
                "toRecipients": [{"emailAddress": {"address": "alice@example.com"}}],
                "ccRecipients": [],
                "bccRecipients": [],
                "body": {"contentType": "text", "content": "Done."},
                "hasAttachments": True,
                "isDraft": True,
            }
        if path == "/me/messages/draft%2Fid/attachments":
            return {
                "value": [
                    {
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "id": "attachment-id",
                        "name": "report.pdf",
                        "contentType": "application/pdf",
                        "size": 123,
                        "isInline": False,
                    }
                ]
            }
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(drafts.graph, "get_json", get_json)

    template, info, body_content_type = drafts.compose_template_for_draft("1")

    assert info.has_attachments is True
    assert "Subject: Status" in template
    assert "Attach:" in template
    assert "report.pdf" not in template
    assert calls[1][0] == "/me/messages/draft%2Fid/attachments"


def test_compose_template_for_draft_rejects_existing_smime_attachment(monkeypatch):
    monkeypatch.setattr(
        drafts.mail,
        "resolve_message_reference",
        lambda reference, account_email=None: ("draft/id", "me@example.com"),
    )
    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )

    def get_json(path, access_token, params=None):
        if path == "/me/messages/draft%2Fid":
            return {
                "id": "draft/id",
                "subject": "Status",
                "from": {"emailAddress": {"address": "me@example.com"}},
                "toRecipients": [{"emailAddress": {"address": "alice@example.com"}}],
                "ccRecipients": [],
                "bccRecipients": [],
                "body": {"contentType": "text", "content": "Done."},
                "hasAttachments": True,
                "isDraft": True,
            }
        if path == "/me/messages/draft%2Fid/attachments":
            return {
                "value": [
                    {
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "id": "smime-id",
                        "name": "smime.p7m",
                        "contentType": "application/pkcs7-mime",
                        "size": 123,
                        "isInline": False,
                    }
                ]
            }
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(drafts.graph, "get_json", get_json)

    with pytest.raises(ValueError, match="cannot be edited"):
        drafts.compose_template_for_draft("1")


def test_update_draft_patches_body_without_removing_existing_attachments(monkeypatch):
    attachment = []
    patched = {}

    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    monkeypatch.setattr(
        drafts.graph,
        "patch_json",
        lambda path, access_token, body: patched.update({"path": path, "access_token": access_token, "body": body}),
    )
    monkeypatch.setattr(
        drafts.graph,
        "post_json",
        lambda path, access_token, body: attachment.append((path, access_token, body)) or {"id": "new-attachment-id"},
    )

    result = drafts.update_draft("draft/id", make_draft(subject="Updated", body="Changed"), include_signature=False)

    assert result.subject == "Updated"
    assert result.attachments == []
    assert attachment == []
    assert patched == {
        "path": "/me/messages/draft%2Fid",
        "access_token": "token",
        "body": {
            "subject": "Updated",
            "body": {"contentType": "Text", "content": "Changed"},
            "toRecipients": [{"emailAddress": {"address": "alice@example.com"}}],
            "ccRecipients": [],
            "bccRecipients": [],
        },
    }


def _stub_draft_fetch(monkeypatch, body):
    monkeypatch.setattr(
        drafts.mail,
        "resolve_message_reference",
        lambda reference, account_email=None: ("draft/id", "me@example.com"),
    )
    monkeypatch.setattr(
        drafts.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )

    def get_json(path, access_token, params=None):
        if path == "/me/messages/draft%2Fid":
            return {
                "id": "draft/id",
                "subject": "Status",
                "from": {"emailAddress": {"address": "me@example.com"}},
                "toRecipients": [{"emailAddress": {"address": "alice@example.com"}}],
                "ccRecipients": [],
                "bccRecipients": [],
                "body": body,
                "hasAttachments": False,
                "isDraft": True,
            }
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(drafts.graph, "get_json", get_json)


def test_html_draft_keeps_its_markup_and_content_type(monkeypatch):
    """Editing an HTML draft must not silently turn it into a text message."""
    markup = '<div style="font-size: 10pt;"><p>Done.</p><p><b>Regards</b></p></div>'
    _stub_draft_fetch(monkeypatch, {"contentType": "html", "content": markup})

    template, _info, body_content_type = drafts.compose_template_for_draft("1")

    assert body_content_type == "HTML"
    # The raw markup is offered for editing, not a lossy text conversion.
    assert markup in template
    assert "<b>Regards</b>" in template


def test_text_draft_stays_text(monkeypatch):
    _stub_draft_fetch(monkeypatch, {"contentType": "text", "content": "Done."})

    template, _info, body_content_type = drafts.compose_template_for_draft("1")

    assert body_content_type == "Text"
    assert "Done." in template
