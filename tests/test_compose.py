import pytest

from msmail.core import compose


def test_parse_compose_text_accepts_headers_and_body():
    draft = compose.parse_compose_text(
        "\n".join(
            [
                "To: alice@example.com; bob@example.com",
                "Cc: carol@example.com",
                "Bcc: dan@example.com",
                "Subject: Status",
                "Attach: report.pdf, chart.png",
                "Sign: yes",
                "Encrypt: no",
                "",
                "---",
                "Hello",
                "World",
            ]
        )
    )

    assert draft.to == ["alice@example.com", "bob@example.com"]
    assert draft.cc == ["carol@example.com"]
    assert draft.bcc == ["dan@example.com"]
    assert draft.subject == "Status"
    assert draft.attachments == ["report.pdf", "chart.png"]
    assert draft.body_content_type == "Text"
    assert draft.sign is True
    assert draft.encrypt is False
    assert draft.body == "Hello\nWorld"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("To: alice@example.com\nSubject: Missing separator\nBody", "separator"),
        ("Subject: Missing recipient\n---\nHello", "To recipient"),
        ("To: alice@example.com\n---\nHello", "Subject"),
        ("To: alice@example.com\nSubject: Empty\n---\n", "body is empty"),
        ("To alice@example.com\nSubject: Invalid\n---\nHello", "Invalid compose header"),
    ],
)
def test_parse_compose_text_rejects_invalid_content(content, message):
    with pytest.raises(ValueError, match=message):
        compose.parse_compose_text(content)


def test_compose_template_round_trips_through_parser():
    template = compose.compose_template(
        to="alice@example.com",
        cc="carol@example.com",
        subject="Status",
        attach="report.pdf",
        body="Done.",
    )

    draft = compose.parse_compose_text(template)

    assert draft.to == ["alice@example.com"]
    assert draft.cc == ["carol@example.com"]
    assert draft.subject == "Status"
    assert draft.attachments == ["report.pdf"]
    assert draft.body == "Done."


def test_parse_response_text_accepts_plain_body_for_reply():
    draft = compose.parse_response_text("Thanks, I will check this.")

    assert draft.to == []
    assert draft.cc == []
    assert draft.bcc == []
    assert draft.body == "Thanks, I will check this."
    assert draft.body_content_type == "Text"


def test_parse_compose_text_can_mark_html_body():
    draft = compose.parse_compose_text(
        "To: alice@example.com\nSubject: HTML\n---\n<p>Hello</p>",
        html=True,
    )

    assert draft.body_content_type == "HTML"
    assert draft.body == "<p>Hello</p>"


def test_parse_response_text_can_mark_html_body():
    draft = compose.parse_response_text("<p>Thanks</p>", html=True)

    assert draft.body_content_type == "HTML"
    assert draft.body == "<p>Thanks</p>"


def test_parse_response_text_accepts_forward_recipients():
    draft = compose.parse_response_text(
        "\n".join(
            [
                "To: alice@example.com, bob@example.com",
                "Cc: carol@example.com",
                "",
                "---",
                "Please see below.",
            ]
        ),
        require_to=True,
    )

    assert draft.to == ["alice@example.com", "bob@example.com"]
    assert draft.cc == ["carol@example.com"]
    assert draft.body == "Please see below."


def test_parse_response_text_requires_forward_recipient_when_requested():
    with pytest.raises(ValueError, match="To recipient"):
        compose.parse_response_text("Please see below.", require_to=True)


@pytest.mark.parametrize('outcome', ['unchanged', 'invalid', 'interrupted'])
def test_editor_cancellation_and_parse_failure_preserve_correct_files(monkeypatch, tmp_path, caplog, outcome):
    from pathlib import Path
    from types import SimpleNamespace
    monkeypatch.setattr(compose.tempfile, 'tempdir', str(tmp_path))
    files = []

    def editor(args, **kwargs):
        path = Path(args[-1])
        files.append(path)
        if outcome == 'invalid':
            path.write_text('Unfinished text without headers')
        if outcome == 'interrupted':
            path.write_text('Text typed before interruption')
            raise KeyboardInterrupt()
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(compose.subprocess, 'run', editor)
    expected = {'unchanged': compose.ComposeCancelled, 'invalid': ValueError, 'interrupted': KeyboardInterrupt}[outcome]
    with pytest.raises(expected):
        compose.compose_interactively(compose.compose_template())
    assert files[0].exists() == (outcome != 'unchanged')
    if outcome != 'unchanged':
        assert str(files[0]) in caplog.text


def test_editor_cleanup_failure_does_not_hide_success(monkeypatch, tmp_path, caplog):
    from pathlib import Path
    path = tmp_path / 'edited.txt'
    path.write_text('saved input')
    draft = compose.parse_response_text('Reply')
    draft = compose.replace(draft, recovery_file=path)

    def fail_unlink(*args, **kwargs):
        raise OSError('synthetic permission failure')

    monkeypatch.setattr(Path, 'unlink', fail_unlink)
    with compose.pending_edit(draft):
        pass  # Server operation succeeded.
    assert path.exists()
    assert 'Draft saved' in caplog.text
    assert str(path) in caplog.text
