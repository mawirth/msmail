import json

import pytest
from typer.testing import CliRunner

from msmail.cli import app
from msmail.commands import list as list_command
from msmail.core import mail


runner = CliRunner()


class Account:
    email = "me@example.com"


def _message(index):
    return {
        "id": f"id-{index}",
        "subject": f"Subject {index}",
        "from": {"emailAddress": {"name": "Alice", "address": "alice@example.com"}},
        "receivedDateTime": "2026-07-29T09:00:00Z",
        "isRead": True,
        "hasAttachments": False,
    }


def _stub_graph(monkeypatch, tmp_path, pages):
    """Serve `pages` as a chain of Graph responses and record the requests."""
    monkeypatch.setattr(mail.auth, "account_dir", lambda account: tmp_path / account)
    monkeypatch.setattr(
        mail.auth,
        "get_access_token",
        lambda account_email=None: ("token", Account()),
    )
    requests = []

    def get_json(path, access_token, params=None):
        requests.append((path, params))
        return pages[len(requests) - 1]

    monkeypatch.setattr(mail.graph, "get_json", get_json)
    return requests


def _page(count, start=1, next_link=None):
    page = {"value": [_message(i) for i in range(start, start + count)]}
    if next_link:
        page["@odata.nextLink"] = next_link
    return page


def test_a_single_page_keeps_the_cursor(monkeypatch, tmp_path):
    requests = _stub_graph(monkeypatch, tmp_path, [_page(25, next_link="https://graph/next")])

    state = mail.list_messages(fetch=25)

    assert len(state.messages) == 25
    assert state.next_link == "https://graph/next"
    assert state.offset == 0
    assert len(requests) == 1
    assert requests[0][1]["$top"] == "25"


def test_fetch_all_follows_every_page(monkeypatch, tmp_path):
    requests = _stub_graph(
        monkeypatch,
        tmp_path,
        [
            _page(100, start=1, next_link="https://graph/p2"),
            _page(100, start=101, next_link="https://graph/p3"),
            _page(40, start=201),
        ],
    )

    state = mail.list_messages(fetch=None)

    assert len(state.messages) == 240
    assert state.next_link is None
    assert state.truncated is False
    assert len(requests) == 3
    assert requests[0][1]["$top"] == "100"


def test_a_trimmed_multi_page_fetch_drops_the_cursor(monkeypatch, tmp_path):
    """Continuing from a trimmed result would silently skip the trimmed tail."""
    _stub_graph(
        monkeypatch,
        tmp_path,
        [
            _page(100, start=1, next_link="https://graph/p2"),
            _page(100, start=101, next_link="https://graph/p3"),
            _page(100, start=201, next_link="https://graph/p4"),
        ],
    )

    state = mail.list_messages(fetch=250)

    assert len(state.messages) == 250
    assert state.next_link is None


def test_the_page_ceiling_is_reported_not_silent(monkeypatch, tmp_path):
    pages = [_page(100, start=1 + i * 100, next_link=f"https://graph/p{i + 2}") for i in range(mail.MAX_PAGES)]
    _stub_graph(monkeypatch, tmp_path, pages)

    state = mail.list_messages(fetch=None)

    assert state.truncated is True
    assert len(state.messages) == mail.MAX_PAGES * 100


def test_more_restarts_indexes_and_tracks_the_offset(monkeypatch, tmp_path):
    _stub_graph(
        monkeypatch,
        tmp_path,
        [
            _page(25, start=1, next_link="https://graph/p2"),
            _page(25, start=26, next_link="https://graph/p3"),
        ],
    )

    first = mail.list_messages(fetch=25)
    assert [m.index for m in first.messages][:3] == [1, 2, 3]
    assert first.offset == 0

    second = mail.list_more()

    # Indexes restart, so the numbers always describe what is on screen.
    assert [m.index for m in second.messages][:3] == [1, 2, 3]
    assert second.messages[0].id == "id-26"
    assert second.offset == 25
    # And the cached numbering is the new page, not the old one.
    assert mail.load_last_list("me@example.com")[0].id == "id-26"


def test_more_refuses_to_continue_a_search(monkeypatch, tmp_path):
    _stub_graph(monkeypatch, tmp_path, [_page(5)])
    mail.search_messages("invoice", fetch=5)

    with pytest.raises(ValueError, match="cannot be paged"):
        mail.list_more()


def test_more_without_a_further_page_says_so(monkeypatch, tmp_path):
    _stub_graph(monkeypatch, tmp_path, [_page(5)])
    mail.list_messages(fetch=25)

    with pytest.raises(ValueError, match="No further page"):
        mail.list_more()


def test_a_stale_cursor_gives_a_readable_error(monkeypatch, tmp_path):
    _stub_graph(monkeypatch, tmp_path, [_page(25, next_link="https://graph/next")])
    mail.list_messages(fetch=25)

    def fail(path, access_token, params=None):
        raise mail.graph.GraphError("Graph request failed: HTTP 400 Bad Request")

    monkeypatch.setattr(mail.graph, "get_json", fail)

    with pytest.raises(ValueError, match="no longer valid"):
        mail.list_more()


def test_a_legacy_cache_still_loads(monkeypatch, tmp_path):
    """A last-list.json written before paging was a bare array."""
    monkeypatch.setattr(mail.auth, "account_dir", lambda account: tmp_path / account)
    path = tmp_path / "me@example.com" / "last-list.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps([{"index": 1, "id": "old-id", "subject": "Old"}]),
        encoding="utf-8",
    )

    state = mail.load_last_list_state("me@example.com")

    assert [m.id for m in state.messages] == ["old-id"]
    assert state.next_link is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [("all", None), ("5", 5), ("250", 250)],
)
def test_resolve_fetch_accepts_numbers_and_all(value, expected):
    assert list_command.resolve_fetch(value) == expected


@pytest.mark.parametrize("value", ["0", "-3", "many"])
def test_resolve_fetch_rejects_nonsense(value):
    with pytest.raises(Exception):
        list_command.resolve_fetch(value)


def test_resolve_fetch_auto_is_fixed_when_piped(monkeypatch):
    monkeypatch.setattr(list_command.sys.stdout, "isatty", lambda: False)

    assert list_command.resolve_fetch(None) == list_command.AUTO_PIPED_FETCH
    assert list_command.resolve_fetch("auto") == list_command.AUTO_PIPED_FETCH


def test_more_cannot_be_combined_with_a_filter(monkeypatch):
    called = []
    monkeypatch.setattr(mail, "list_more", lambda **kwargs: called.append(kwargs))

    result = runner.invoke(app, ["list", "--more", "--from", "alice@example.com"])

    assert result.exit_code != 0
    assert "--from" in result.stdout
    assert called == []


def test_more_alone_is_accepted(monkeypatch):
    monkeypatch.setattr(
        mail,
        "list_more",
        lambda **kwargs: mail.MessageList(messages=[], next_link=None, offset=25),
    )

    result = runner.invoke(app, ["list", "--more"])

    assert result.exit_code == 0
