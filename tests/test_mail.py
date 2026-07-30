import pytest

from msmail.core import mail
from msmail.commands import read as read_command


class Account:
    email = "me@example.com"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("inbox", "inbox"),
        ("drafts", "drafts"),
        ("sent", "sentitems"),
        ("sentitems", "sentitems"),
        ("deleted", "deleteditems"),
        ("junk", "junkemail"),
    ],
)
def test_normalize_folder_accepts_aliases(value, expected):
    assert mail.normalize_folder(value) == expected


def test_normalize_folder_rejects_unknown_folder():
    with pytest.raises(ValueError, match="Unknown folder"):
        mail.normalize_folder("archive")


def test_build_filter_combines_inbox_class_sender_and_dates():
    filter_expression = mail._build_filter(
        folder_id="inbox",
        inbox_class="focused",
        from_address="Alice.O'Hara@example.com",
        after="2026-06-01",
        before="2026-07-01",
    )

    assert filter_expression == (
        "inferenceClassification eq 'focused' and "
        "from/emailAddress/address eq 'alice.o''hara@example.com' and "
        "receivedDateTime ge 2026-06-01T00:00:00Z and "
        "receivedDateTime lt 2026-07-01T00:00:00Z"
    )


def test_build_filter_omits_inbox_class_for_non_inbox():
    assert (
        mail._build_filter(
            folder_id="sentitems",
            inbox_class="all",
            from_address=None,
            after=None,
            before=None,
        )
        is None
    )


def test_parse_date_rejects_invalid_format():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        mail._build_filter(
            folder_id="inbox",
            inbox_class="all",
            from_address=None,
            after="06/01/2026",
            before=None,
        )


def make_summary(index, message_id):
    return mail.MessageSummary(
        account="me@example.com",
        index=index,
        id=message_id,
        subject=f"Subject {index}",
        from_name="Alice",
        from_address="alice@example.com",
        received_date_time="2026-06-28T10:00:00Z",
        is_read=False,
        has_attachments=False,
        has_user_attachments=False,
        smime_signed=False,
        smime_encrypted=False,
        inference_classification="focused",
        body_preview="Preview",
    )


def make_detail(message_id="message/id"):
    return mail.MessageDetail(
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


def test_remove_from_last_list_deletes_matching_message(monkeypatch, tmp_path):
    monkeypatch.setattr(mail.auth, "account_dir", lambda account: tmp_path / account)
    mail.save_last_list("me@example.com", [make_summary(1, "keep"), make_summary(2, "remove")])

    mail.remove_from_last_list("me@example.com", "remove")

    remaining = mail.load_last_list("me@example.com")
    assert [message.id for message in remaining] == ["keep"]


def test_resolve_message_references_accepts_ranges_and_deduplicates(monkeypatch, tmp_path):
    monkeypatch.setattr(mail.auth, "account_dir", lambda account: tmp_path / account)
    monkeypatch.setattr(
        mail.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    mail.save_last_list(
        "me@example.com",
        [make_summary(index, f"id-{index}") for index in range(1, 8)],
    )

    ids, account = mail.resolve_message_references("3-5,1,4,7")

    assert account == "me@example.com"
    assert ids == ["id-3", "id-4", "id-5", "id-1", "id-7"]


def test_resolve_message_reference_items_keeps_original_indexes(monkeypatch, tmp_path):
    monkeypatch.setattr(mail.auth, "account_dir", lambda account: tmp_path / account)
    monkeypatch.setattr(
        mail.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    mail.save_last_list(
        "me@example.com",
        [make_summary(index, f"id-{index}") for index in range(1, 5)],
    )

    items, account = mail.resolve_message_reference_items("2-3,1")

    assert account == "me@example.com"
    assert [(item.index, item.id) for item in items] == [(2, "id-2"), (3, "id-3"), (1, "id-1")]


@pytest.mark.parametrize("reference", ["3-1", "1,a", "1-", ",1"])
def test_resolve_message_references_rejects_invalid_ranges(monkeypatch, tmp_path, reference):
    monkeypatch.setattr(mail.auth, "account_dir", lambda account: tmp_path / account)
    monkeypatch.setattr(
        mail.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    mail.save_last_list("me@example.com", [make_summary(1, "id-1")])

    with pytest.raises(ValueError):
        mail.resolve_message_references(reference)


def test_delete_message_calls_graph_and_updates_last_list(monkeypatch, tmp_path):
    deleted = {}
    monkeypatch.setattr(mail.auth, "account_dir", lambda account: tmp_path / account)
    monkeypatch.setattr(
        mail.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    mail.save_last_list("me@example.com", [make_summary(1, "message/id")])
    monkeypatch.setattr(mail, "get_message", lambda message_id, account_email=None, include_attachment_details=True: make_detail(message_id))

    def delete_empty(path, access_token):
        deleted["path"] = path
        deleted["access_token"] = access_token

    monkeypatch.setattr(mail.graph, "delete_empty", delete_empty)

    result = mail.delete_message("1")

    assert result.subject == "Status"
    assert deleted == {
        "path": "/me/messages/message%2Fid",
        "access_token": "token",
    }
    assert mail.load_last_list("me@example.com") == []


def test_move_message_calls_graph_and_updates_last_list(monkeypatch, tmp_path):
    posted = {}
    monkeypatch.setattr(mail.auth, "account_dir", lambda account: tmp_path / account)
    monkeypatch.setattr(
        mail.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    mail.save_last_list("me@example.com", [make_summary(1, "message/id")])
    monkeypatch.setattr(mail, "get_message", lambda message_id, account_email=None, include_attachment_details=True: make_detail(message_id))

    def post_json(path, access_token, body):
        posted["path"] = path
        posted["access_token"] = access_token
        posted["body"] = body
        return {"id": "moved-id", "subject": "Moved status"}

    monkeypatch.setattr(mail.graph, "post_json", post_json)

    result = mail.move_message("1", destination_folder="junk")

    assert result.id == "moved-id"
    assert result.subject == "Moved status"
    assert result.destination_folder == "junkemail"
    assert posted == {
        "path": "/me/messages/message%2Fid/move",
        "access_token": "token",
        "body": {"destinationId": "junkemail"},
    }
    assert mail.load_last_list("me@example.com") == []


def test_move_message_can_use_graph_folder_id(monkeypatch, tmp_path):
    posted = {}
    monkeypatch.setattr(mail.auth, "account_dir", lambda account: tmp_path / account)
    monkeypatch.setattr(
        mail.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    mail.save_last_list("me@example.com", [make_summary(1, "message/id")])
    monkeypatch.setattr(mail, "get_message", lambda message_id, account_email=None, include_attachment_details=True: make_detail(message_id))

    def post_json(path, access_token, body):
        posted["body"] = body
        return {"id": "moved-id", "subject": "Moved status"}

    monkeypatch.setattr(mail.graph, "post_json", post_json)

    result = mail.move_message("1", destination_folder="", destination_folder_id="custom-folder-id")

    assert result.destination_folder == "custom-folder-id"
    assert posted["body"] == {"destinationId": "custom-folder-id"}


def test_search_messages_calls_graph_search_and_saves_last_list(monkeypatch, tmp_path):
    monkeypatch.setattr(mail.auth, "account_dir", lambda account: tmp_path / account)
    monkeypatch.setattr(
        mail.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    captured = {}

    def get_json(path, access_token, params=None):
        captured["path"] = path
        captured["params"] = params
        return {
            "value": [
                {
                    "id": "message-id",
                    "subject": "Status",
                    "from": {"emailAddress": {"name": "Alice", "address": "alice@example.com"}},
                    "receivedDateTime": "2026-06-28T10:00:00Z",
                    "isRead": True,
                    "hasAttachments": False,
                }
            ]
        }

    monkeypatch.setattr(mail.graph, "get_json", get_json)

    result = mail.search_messages("status", limit=10)

    assert result[0].subject == "Status"
    assert captured["path"] == "/me/messages"
    assert captured["params"]["$search"] == '"status"'
    assert mail.load_last_list("me@example.com")[0].id == "message-id"


def test_list_messages_does_not_fetch_attachment_details_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(mail.auth, "account_dir", lambda account: tmp_path / account)
    monkeypatch.setattr(
        mail.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    calls = []

    def get_json(path, access_token, params=None):
        calls.append(path)
        if path == "/me/mailFolders/inbox/messages":
            return {
                "value": [
                    {
                        "id": "message-id",
                        "subject": "Status",
                        "from": {"emailAddress": {"name": "Alice", "address": "alice@example.com"}},
                        "receivedDateTime": "2026-06-28T10:00:00Z",
                        "isRead": True,
                        "hasAttachments": True,
                    }
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(mail.graph, "get_json", get_json)

    result = mail.list_messages()

    assert calls == ["/me/mailFolders/inbox/messages"]
    assert result[0].has_attachments is True
    assert result[0].has_user_attachments is True
    assert result[0].smime_signed is False
    assert result[0].smime_encrypted is False


def test_list_messages_can_fetch_attachment_details(monkeypatch, tmp_path):
    monkeypatch.setattr(mail.auth, "account_dir", lambda account: tmp_path / account)
    monkeypatch.setattr(
        mail.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    calls = []

    def get_json(path, access_token, params=None):
        calls.append(path)
        if path == "/me/mailFolders/inbox/messages":
            return {
                "value": [
                    {
                        "id": "message/id",
                        "subject": "Signed",
                        "from": {"emailAddress": {"name": "Alice", "address": "alice@example.com"}},
                        "receivedDateTime": "2026-06-28T10:00:00Z",
                        "isRead": True,
                        "hasAttachments": True,
                    }
                ]
            }
        if path == "/me/messages/message%2Fid/attachments":
            return {
                "value": [
                    {
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "id": "sig",
                        "name": "smime.p7m",
                        "contentType": "multipart/signed",
                        "size": 200,
                        "isInline": False,
                    }
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(mail.graph, "get_json", get_json)

    result = mail.list_messages(include_attachment_details=True)

    assert calls == [
        "/me/mailFolders/inbox/messages",
        "/me/messages/message%2Fid/attachments",
    ]
    assert result[0].has_user_attachments is False
    assert result[0].smime_signed is True
    assert result[0].smime_encrypted is False


def test_list_folders_returns_folder_metadata(monkeypatch):
    monkeypatch.setattr(
        mail.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    def get_json(path, access_token, params=None):
        if path == "/me/mailFolders":
            return {
                "value": [
                    {
                        "id": "folder-id",
                        "displayName": "Archive",
                        "parentFolderId": "parent-id",
                        "childFolderCount": 1,
                        "totalItemCount": 10,
                        "unreadItemCount": 3,
                    }
                ]
            }
        if path == "/me/mailFolders/folder-id/childFolders":
            return {
                "value": [
                    {
                        "id": "child-id",
                        "displayName": "2026",
                        "parentFolderId": "folder-id",
                        "childFolderCount": 0,
                        "totalItemCount": 4,
                        "unreadItemCount": 1,
                    }
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(mail.graph, "get_json", get_json)

    result = mail.list_folders()

    assert result == [
        mail.FolderInfo(
            account="me@example.com",
            id="folder-id",
            display_name="Archive",
            parent_folder_id="parent-id",
            depth=0,
            child_folder_count=1,
            total_item_count=10,
            unread_item_count=3,
        ),
        mail.FolderInfo(
            account="me@example.com",
            id="child-id",
            display_name="2026",
            parent_folder_id="folder-id",
            depth=1,
            child_folder_count=0,
            total_item_count=4,
            unread_item_count=1,
        ),
    ]


def test_mark_message_patches_read_state_and_updates_last_list(monkeypatch, tmp_path):
    patched = {}
    monkeypatch.setattr(mail.auth, "account_dir", lambda account: tmp_path / account)
    monkeypatch.setattr(
        mail.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    mail.save_last_list("me@example.com", [make_summary(1, "message/id")])
    monkeypatch.setattr(mail, "get_message", lambda message_id, account_email=None, include_attachment_details=True: make_detail(message_id))

    def patch_json(path, access_token, body):
        patched["path"] = path
        patched["access_token"] = access_token
        patched["body"] = body

    monkeypatch.setattr(mail.graph, "patch_json", patch_json)

    result = mail.mark_message("1", is_read=True)

    assert result.subject == "Status"
    assert patched == {
        "path": "/me/messages/message%2Fid",
        "access_token": "token",
        "body": {"isRead": True},
    }
    assert mail.load_last_list("me@example.com")[0].is_read is True


def test_get_message_mime_fetches_raw_mime(monkeypatch):
    monkeypatch.setattr(
        mail.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    captured = {}

    def get_bytes(path, access_token, accept):
        captured["path"] = path
        captured["access_token"] = access_token
        captured["accept"] = accept
        return b"raw mime"

    monkeypatch.setattr(mail.graph, "get_bytes", get_bytes)

    mime_bytes, account = mail.get_message_mime("message/id")

    assert mime_bytes == b"raw mime"
    assert account == "me@example.com"
    assert captured == {
        "path": "/me/messages/message%2Fid/$value",
        "access_token": "token",
        "accept": "message/rfc822",
    }


def test_save_attachments_writes_file_attachments(monkeypatch, tmp_path):
    monkeypatch.setattr(
        mail.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    monkeypatch.setattr(mail, "resolve_message_reference", lambda reference, account_email=None: ("message/id", "me@example.com"))
    monkeypatch.setattr(mail, "get_message", lambda message_id, account_email=None, include_attachment_details=True: make_detail(message_id))

    def get_json(path, access_token, params=None):
        assert path == "/me/messages/message%2Fid/attachments"
        assert access_token == "token"
        assert params is None
        return {
            "value": [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": "report.txt",
                    "isInline": False,
                    "contentBytes": "aGVsbG8=",
                },
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": "inline.png",
                    "isInline": True,
                    "contentBytes": "aGVsbG8=",
                },
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": "smime.p7m",
                    "contentType": "multipart/signed",
                    "isInline": False,
                    "contentBytes": "c2ln",
                },
                {
                    "@odata.type": "#microsoft.graph.itemAttachment",
                    "name": "message.eml",
                },
            ]
        }

    monkeypatch.setattr(mail.graph, "get_json", get_json)

    result = mail.save_attachments("message/id", destination=str(tmp_path))

    assert result.skipped == 3
    assert [(item.name, item.size) for item in result.saved] == [("report.txt", 5)]
    assert (tmp_path / "report.txt").read_text(encoding="utf-8") == "hello"


def test_save_attachments_can_include_inline_file_attachments(monkeypatch, tmp_path):
    monkeypatch.setattr(
        mail.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    monkeypatch.setattr(mail, "resolve_message_reference", lambda reference, account_email=None: ("message/id", "me@example.com"))
    monkeypatch.setattr(mail, "get_message", lambda message_id, account_email=None, include_attachment_details=True: make_detail(message_id))
    monkeypatch.setattr(
        mail.graph,
        "get_json",
        lambda path, access_token, params=None: {
            "value": [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": "image.png",
                    "isInline": True,
                    "contentBytes": "aW1hZ2U=",
                }
            ]
        },
    )

    result = mail.save_attachments("message/id", destination=str(tmp_path), include_inline=True)

    assert result.skipped == 0
    assert result.saved[0].name == "image.png"
    assert (tmp_path / "image.png").read_text(encoding="utf-8") == "image"


def test_save_attachments_uses_unique_filename_without_overwrite(monkeypatch, tmp_path):
    (tmp_path / "report.txt").write_text("existing", encoding="utf-8")
    monkeypatch.setattr(
        mail.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    monkeypatch.setattr(mail, "resolve_message_reference", lambda reference, account_email=None: ("message/id", "me@example.com"))
    monkeypatch.setattr(mail, "get_message", lambda message_id, account_email=None, include_attachment_details=True: make_detail(message_id))
    monkeypatch.setattr(
        mail.graph,
        "get_json",
        lambda path, access_token, params=None: {
            "value": [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": "../report.txt",
                    "isInline": False,
                    "contentBytes": "bmV3",
                }
            ]
        },
    )

    result = mail.save_attachments("message/id", destination=str(tmp_path))

    assert result.saved[0].name == "report.txt"
    assert result.saved[0].path.endswith("report-1.txt")
    assert (tmp_path / "report.txt").read_text(encoding="utf-8") == "existing"
    assert (tmp_path / "report-1.txt").read_text(encoding="utf-8") == "new"


def test_save_attachments_can_decrypt_smime_container(monkeypatch, tmp_path):
    decrypted = tmp_path / "decrypted.eml"
    decrypted.write_bytes(
        b'Content-Type: multipart/mixed; boundary="mix"\r\n'
        b"\r\n"
        b"--mix\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"body\r\n"
        b"--mix\r\n"
        b"Content-Type: text/plain\r\n"
        b"Content-Disposition: attachment; filename=\"secret.txt\"\r\n"
        b"\r\n"
        b"secret\r\n"
        b"--mix--\r\n"
    )
    monkeypatch.setattr(mail, "resolve_message_reference", lambda reference, account_email=None: ("message/id", "me@example.com"))
    monkeypatch.setattr(mail, "get_message", lambda message_id, account_email=None, include_attachment_details=True: make_detail(message_id))
    monkeypatch.setattr(
        mail.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    monkeypatch.setattr(mail, "get_message_mime", lambda message_id, account_email=None: (b"encrypted", "me@example.com"))
    monkeypatch.setattr(
        mail.smime,
        "decrypt_mime_bytes",
        lambda mime_bytes, account_email=None: mail.smime.DecryptResult(
            decrypted=True,
            encrypted_path="",
            decrypted_path="",
            data=decrypted.read_bytes(),
        ),
    )

    result = mail.save_attachments("message/id", destination=str(tmp_path / "out"), decrypt=True)

    assert result.saved[0].name == "secret.txt"
    assert (tmp_path / "out" / "secret.txt").read_text(encoding="utf-8") == "secret"


def test_list_attachments_returns_file_and_inline_metadata(monkeypatch):
    monkeypatch.setattr(
        mail.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    monkeypatch.setattr(
        mail.graph,
        "get_json",
        lambda path, access_token: {
            "value": [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "id": "a1",
                    "name": "../image.png",
                    "contentType": "image/png",
                    "size": 42,
                    "isInline": True,
                    "contentBytes": "aW1hZ2U=",
                },
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "id": "sig",
                    "name": "smime.p7m",
                    "contentType": "multipart/signed",
                    "size": 200,
                    "isInline": False,
                    "contentBytes": "c2ln",
                },
                {
                    "@odata.type": "#microsoft.graph.itemAttachment",
                    "id": "a2",
                    "name": "forwarded.eml",
                    "size": 100,
                },
            ]
        },
    )

    attachments = mail.list_attachments("message/id")

    assert attachments == [
        mail.AttachmentInfo(
            id="a1",
            name="image.png",
            content_type="image/png",
            size=42,
            is_inline=True,
            attachment_type="fileAttachment",
            can_save=True,
            is_smime_signature=False,
            is_smime_encrypted=False,
        ),
        mail.AttachmentInfo(
            id="sig",
            name="smime.p7m",
            content_type="multipart/signed",
            size=200,
            is_inline=False,
            attachment_type="fileAttachment",
            can_save=False,
            is_smime_signature=True,
            is_smime_encrypted=False,
        ),
        mail.AttachmentInfo(
            id="a2",
            name="forwarded.eml",
            content_type="",
            size=100,
            is_inline=False,
            attachment_type="itemAttachment",
            can_save=False,
            is_smime_signature=False,
            is_smime_encrypted=False,
        ),
    ]


def test_message_summary_classifies_smime_signature_without_user_attachment():
    summary = mail._message_to_summary(
        "me@example.com",
        1,
        {
            "id": "message-id",
            "subject": "Signed",
            "hasAttachments": True,
            "isRead": True,
        },
        [
            mail.AttachmentInfo(
                id="sig",
                name="smime.p7m",
                content_type="multipart/signed",
                size=200,
                is_inline=False,
                attachment_type="fileAttachment",
                can_save=False,
                is_smime_signature=True,
                is_smime_encrypted=False,
            )
        ],
    )

    assert summary.has_attachments is True
    assert summary.has_user_attachments is False
    assert summary.smime_signed is True
    assert summary.smime_encrypted is False


def test_get_message_reports_smime_metadata_without_user_attachment(monkeypatch):
    monkeypatch.setattr(
        mail.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )

    def get_json(path, access_token, params=None):
        if path == "/me/messages/message%2Fid":
            return {
                "id": "message/id",
                "subject": "Signed",
                "from": {"emailAddress": {"name": "Alice", "address": "alice@example.com"}},
                "toRecipients": [{"emailAddress": {"address": "me@example.com"}}],
                "ccRecipients": [],
                "receivedDateTime": "2026-06-28T10:00:00Z",
                "internetMessageId": "<message@example.com>",
                "body": {"contentType": "text", "content": "Hello"},
                "bodyPreview": "Hello",
                "hasAttachments": True,
            }
        if path == "/me/messages/message%2Fid/attachments":
            return {
                "value": [
                    {
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "id": "sig",
                        "name": "smime.p7m",
                        "contentType": "multipart/signed",
                        "size": 200,
                        "isInline": False,
                        "contentBytes": "c2ln",
                    }
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(mail.graph, "get_json", get_json)

    detail = mail.get_message("message/id")

    assert detail.has_attachments is True
    assert detail.attachment_count == 0
    assert detail.attachments == []
    assert detail.smime_signed is True
    assert detail.smime_encrypted is False
    assert read_command._smime_metadata(detail) == {
        "signed": True,
        "encrypted": False,
        "known": True,
        "decrypted": None,
        "verified": None,
        "trusted": None,
        "error": None,
    }


def test_get_message_can_skip_attachment_details(monkeypatch):
    monkeypatch.setattr(
        mail.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    calls = []

    def get_json(path, access_token, params=None):
        calls.append(path)
        if path == "/me/messages/message%2Fid":
            return {
                "id": "message/id",
                "subject": "Status",
                "from": {"emailAddress": {"name": "Alice", "address": "alice@example.com"}},
                "toRecipients": [{"emailAddress": {"address": "me@example.com"}}],
                "ccRecipients": [],
                "receivedDateTime": "2026-06-28T10:00:00Z",
                "internetMessageId": "<message@example.com>",
                "body": {"contentType": "text", "content": "Hello"},
                "bodyPreview": "Hello",
                "hasAttachments": True,
            }
        raise AssertionError(path)

    monkeypatch.setattr(mail.graph, "get_json", get_json)

    detail = mail.get_message("message/id", include_attachment_details=False)

    assert calls == ["/me/messages/message%2Fid"]
    assert detail.has_attachments is True
    assert detail.attachment_count == 0
    assert detail.attachments == []
    assert detail.smime_signed is False
    assert detail.smime_encrypted is False
    assert detail.attachment_details_loaded is False


def test_smime_attachment_is_never_both_signed_and_encrypted():
    """smime.p7m carries either encrypted data or an opaque signature.

    Classifying it by name alone marked every encrypted message as signed too,
    which showed a spurious S in the UASE column.
    """
    cases = [
        # name, content type, expected (signature, encrypted)
        ("smime.p7m", "application/pkcs7-mime; smime-type=enveloped-data", (False, True)),
        ("smime.p7m", "application/pkcs7-mime; smime-type=signed-data", (True, False)),
        ("smime.p7m", "multipart/signed", (True, False)),
        ("smime.p7s", "application/pkcs7-signature", (True, False)),
        ("smime.p7s", "application/x-pkcs7-signature", (True, False)),
        ("smime.p7c", "", (False, True)),
        ("report.pdf", "application/pdf", (False, False)),
    ]

    for name, content_type, expected in cases:
        actual = (
            mail._is_smime_signature_attachment(name, content_type),
            mail._is_smime_encrypted_attachment(name, content_type),
        )
        assert actual == expected, f"{name} / {content_type!r}: {actual} != {expected}"
        assert not all(actual), f"{name} / {content_type!r} classified as both"


def test_encrypted_message_is_not_reported_as_signed(monkeypatch):
    summary = mail._message_to_summary(
        "me@example.com",
        1,
        {"id": "message-id", "subject": "Encrypted", "hasAttachments": True, "isRead": True},
        [
            mail.AttachmentInfo(
                id="enc",
                name="smime.p7m",
                content_type="application/pkcs7-mime; smime-type=enveloped-data",
                size=400,
                is_inline=False,
                attachment_type="fileAttachment",
                can_save=False,
                is_smime_signature=False,
                is_smime_encrypted=True,
            )
        ],
    )

    assert summary.smime_encrypted is True
    assert summary.smime_signed is False
    assert summary.has_user_attachments is False
