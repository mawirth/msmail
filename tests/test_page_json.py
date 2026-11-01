import base64
from dataclasses import asdict
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from typer.testing import CliRunner

from msmail.cli import app
from msmail.core import auth, cursors, graph, mail


runner = CliRunner()
ACCOUNT = "reader@example.com"
LIST_URL = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"
SEARCH_URL = "https://graph.microsoft.com/v1.0/me/messages"


def message(identifier):
    return {
        "id": identifier,
        "subject": f"Subject {identifier}",
        "from": {"emailAddress": {"name": "Alice", "address": "alice@example.com"}},
        "receivedDateTime": "2026-11-01T09:00:00Z",
        "isRead": False,
        "hasAttachments": False,
    }


@pytest.fixture
def mailbox(monkeypatch):
    active = [ACCOUNT]
    token_accounts = []
    requests = []

    def token(email=None):
        email = email or active[0]
        token_accounts.append(email)
        return "synthetic-token", SimpleNamespace(email=email)

    redirects = []

    def get_json(path, access_token, params=None, *, follow_redirects=True):
        requests.append((path, access_token, params))
        redirects.append(follow_redirects)
        source = "list" if "mailfolders" in path.lower() else "search"
        if params is not None:
            query = params.get("$search", params.get("$filter", ""))
            stream = "a" if "alice" in query else "b" if "bob" in query else "interactive"
            number = 1
        else:
            position = parse_qs(urlsplit(path).query)["$skiptoken"][0]
            stream, number = position.rsplit(":", 1)
            number = int(number)
        result = {"value": [message(f"{stream}-{number}")]}
        if number < 3:
            url = LIST_URL if source == "list" else SEARCH_URL
            result["@odata.nextLink"] = f"{url}?$skiptoken={stream}:{number + 1}"
        return result

    monkeypatch.setattr(auth, "get_access_token", token)
    monkeypatch.setattr(auth, "resolve_account_email", lambda email=None: (email or active[0]).strip().lower())
    monkeypatch.setattr(graph, "get_json", get_json)
    return SimpleNamespace(active=active, tokens=token_accounts, requests=requests, redirects=redirects)


def invoke_page(args):
    result = runner.invoke(app, args + ["--page-json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def start_args(source, stream):
    return ["list", "--from", f"{stream}@example.com"] if source == "list" else ["search", stream]


@pytest.mark.parametrize("source", ["list", "search"])
def test_interleaved_queries_and_interactive_lists_are_independent(mailbox, source):
    # Seed the shared cache, then prove both private streams leave it untouched.
    assert runner.invoke(app, ["list", "--fetch", "1"]).exit_code == 0
    cache = mail._last_list_path(ACCOUNT)
    initial_cache = cache.read_bytes()
    first_a = invoke_page(start_args(source, "alice") + ["--fetch", "1"])
    first_b = invoke_page(start_args(source, "bob") + ["--fetch", "1"])
    assert cache.read_bytes() == initial_cache

    # Ordinary list/--more calls replace their own cache between cursor calls.
    assert runner.invoke(app, ["list", "--fetch", "1", "--other"]).exit_code == 0
    assert runner.invoke(app, ["list", "--more"]).exit_code == 0
    interactive_cache = cache.read_bytes()

    second_a = invoke_page([source, "--cursor", first_a["next_cursor"]])
    second_b = invoke_page([source, "--cursor", first_b["next_cursor"]])
    assert cache.read_bytes() == interactive_cache
    third_b = invoke_page([source, "--cursor", second_b["next_cursor"]])
    third_a = invoke_page([source, "--cursor", second_a["next_cursor"]])

    for stream, pages in [("a", [first_a, second_a, third_a]), ("b", [first_b, second_b, third_b])]:
        assert [page["messages"][0]["id"] for page in pages] == [f"{stream}-{n}" for n in range(1, 4)]
        assert [page["offset"] for page in pages] == [0, 1, 2]
        assert all(page["account"] == ACCOUNT and page["source"] == source for page in pages)
        assert pages[-1]["next_cursor"] is None
        assert pages[0]["messages"][0] == asdict(mail._message_to_summary(ACCOUNT, 1, message(f"{stream}-1")))
        state = cursors.decode(pages[0]["next_cursor"])
        assert "synthetic-token" not in json.dumps(asdict(state))
    assert cache.read_bytes() == interactive_cache
    assert mail.load_last_list(ACCOUNT)[0].id == "interactive-2"


@pytest.mark.parametrize("source", ["list", "search"])
def test_page_mode_never_accesses_last_list(mailbox, monkeypatch, source):
    def forbidden(*args, **kwargs):
        raise AssertionError("Page mode accessed last-list cache")

    monkeypatch.setattr(mail, "_last_list_path", forbidden)
    monkeypatch.setattr(mail, "load_last_list_state", forbidden)
    monkeypatch.setattr(mail, "save_last_list", forbidden)
    first = invoke_page(start_args(source, "alice"))
    invoke_page([source, "--cursor", first["next_cursor"]])
    assert mailbox.redirects == [False, False]


def test_cursor_pins_account_after_active_account_changes(mailbox):
    first = invoke_page(["list"])
    mailbox.active[0] = "other@example.com"
    second = invoke_page(["list", "--cursor", first["next_cursor"]])
    assert second["account"] == ACCOUNT
    assert mailbox.tokens == [ACCOUNT, ACCOUNT]
    invoke_page(["list", "--cursor", first["next_cursor"], "--account", ACCOUNT.upper()])


def test_conflicting_account_and_query_type_fail_before_authentication(mailbox):
    first = invoke_page(["list"])
    mailbox.tokens.clear()
    mailbox.requests.clear()
    for args in [
        ["list", "--account", "other@example.com"],
        ["search"],
    ]:
        result = runner.invoke(app, args + ["--cursor", first["next_cursor"], "--page-json"])
        assert result.exit_code == 1
    assert mailbox.tokens == []
    assert mailbox.requests == []


@pytest.mark.parametrize("args", [
    ["list", "--cursor", "invalid"],
    ["search", "--cursor", "invalid"],
    ["list", "--page-json", "--more"],
    ["list", "--page-json", "--json"],
    ["search", "alice", "--page-json", "--json"],
    ["search"],
    ["search", "--page-json"],
    ["search", "alice", "--cursor", "invalid", "--page-json"],
    ["search", "--fetch", "1", "--cursor", "invalid", "--page-json"],
] + [
    ["list", "--cursor", "invalid", "--page-json"] + options
    for options in [
        ["--folder", "inbox"], ["--from", ""], ["--after", "2026-01-01"],
        ["--before", "2026-12-01"], ["--all"], ["--other"], ["--fetch", "1"],
        ["--attachment-details"],
    ]
])
def test_conflicting_options_are_usage_errors_before_any_requests(mailbox, args):
    result = runner.invoke(app, args)
    assert result.exit_code == 2, result.output
    assert mailbox.tokens == []
    assert mailbox.requests == []


def encoded(data):
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


def cursor_data(**changes):
    return {
        "version": 1, "account": ACCOUNT, "source": "list", "offset": 1,
        "next_link": LIST_URL + "?$skiptoken=a:2", "attachment_details": False,
        **changes,
    }


@pytest.mark.parametrize("url", [
    "https://attacker.example/messages", "http://graph.microsoft.com/v1.0/me/messages",
    "https://graph.microsoft.com.attacker.example/v1.0/me/messages",
    "https://graph.microsoft.com@attacker.example/v1.0/me/messages",
    "https://attacker.example@graph.microsoft.com/v1.0/me/messages",
    "https://graph.microsoft.com:443/v1.0/me/messages", "//attacker.example/messages",
    "/me/messages", "file:///tmp/messages", "https://127.0.0.1/messages",
    "https://graph.microsoft.com/v1.0/users", LIST_URL + "/../messages",
    LIST_URL.replace("/inbox/", "/%2e%2e/"), LIST_URL + "#fragment",
    LIST_URL + "\n?$skip=1", LIST_URL + "?access_token=synthetic-token",
    LIST_URL + "?%61ccess_token=synthetic-token", LIST_URL + "?client_secret=synthetic-secret",
])
def test_untrusted_urls_are_rejected_without_auth_or_http(mailbox, url):
    result = runner.invoke(app, ["list", "--cursor", encoded(cursor_data(next_link=url)), "--page-json"])
    assert result.exit_code == 1
    assert "Invalid mail cursor" in result.output
    assert mailbox.tokens == []
    assert mailbox.requests == []


@pytest.mark.parametrize("data", [
    [], None, {}, cursor_data(version=2), cursor_data(version=True),
    cursor_data(offset=-1), cursor_data(offset=True), cursor_data(offset="1"),
    cursor_data(account=""), cursor_data(account=[]), cursor_data(source=[]),
    cursor_data(attachment_details="yes"), cursor_data(next_link=[]),
    cursor_data(access_token="synthetic-token"),
])
def test_malformed_cursor_schema_is_rejected(mailbox, data):
    result = runner.invoke(app, ["list", "--cursor", encoded(data), "--page-json"])
    assert result.exit_code == 1
    assert "Invalid mail cursor" in result.output
    assert mailbox.tokens == []
    assert mailbox.requests == []


@pytest.mark.parametrize("value", ["", "not-a-cursor", "!invalid!", "a" * (cursors.MAX_CURSOR_LENGTH + 1)])
def test_malformed_encoding_is_rejected(mailbox, value):
    result = runner.invoke(app, ["list", "--cursor", value, "--page-json"])
    assert result.exit_code == 1
    assert "Invalid mail cursor" in result.output
    assert mailbox.requests == []


@pytest.mark.parametrize("source", ["list", "search"])
@pytest.mark.parametrize("fetch", ["all", "101", "0"])
def test_page_fetch_has_a_bounded_page_size(mailbox, source, fetch):
    result = runner.invoke(app, start_args(source, "alice") + ["--page-json", "--fetch", fetch])
    assert result.exit_code == 2
    assert mailbox.requests == []


@pytest.mark.parametrize("count", [0, 1, 3])
def test_page_mode_keeps_entire_graph_page_even_if_size_differs(mailbox, monkeypatch, count):
    monkeypatch.setattr(graph, "get_json", lambda *args, **kwargs: {
        "value": [message(str(n)) for n in range(count)],
        "@odata.nextLink": LIST_URL + "?$skiptoken=opaque%2Bvalue%3D",
    })
    page = invoke_page(["list", "--fetch", "2"])
    assert len(page["messages"]) == count
    state = cursors.decode(page["next_cursor"])
    assert state.offset == count
    assert state.next_link.endswith("opaque%2Bvalue%3D")


def test_unsafe_server_next_link_is_not_returned_or_followed(mailbox, monkeypatch):
    calls = []

    def response(*args, **kwargs):
        calls.append(args)
        return {"value": [], "@odata.nextLink": "https://attacker.example/messages"}

    monkeypatch.setattr(graph, "get_json", response)
    result = runner.invoke(app, ["list", "--page-json"])
    assert result.exit_code == 1
    assert len(calls) == 1


@pytest.mark.parametrize("path", [
    "/v1.0/me/mailfolders/inbox/messages",
    "/v1.0/me/mailFolders('inbox')/messages",
    "/v1.0/me/mailFolders/AAMkAGExample%2B%2F%3D/messages",
    "/v1.0/me/mailfolders('AAMkAGExample=')/messages",
])
def test_graph_folder_url_forms_are_preserved(mailbox, path):
    url = "https://graph.microsoft.com" + path + "?$skiptoken=a:2"
    value = encoded(cursor_data(next_link=url))
    invoke_page(["list", "--cursor", value])
    assert mailbox.requests[0][0] == url


@pytest.mark.parametrize("source", ["list", "search"])
def test_legacy_json_is_still_an_array_and_updates_cache(mailbox, source):
    result = runner.invoke(app, start_args(source, "alice") + ["--json", "--fetch", "1"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert data == [asdict(mail._message_to_summary(ACCOUNT, 1, message("a-1")))]
    assert mail.load_last_list(ACCOUNT)[0].id == "a-1"


@pytest.mark.parametrize("source", ["list", "search"])
def test_final_empty_page_still_identifies_account(mailbox, monkeypatch, source):
    monkeypatch.setattr(graph, "get_json", lambda *args, **kwargs: {"value": []})
    page = invoke_page(start_args(source, "alice"))
    assert page == {"messages": [], "next_cursor": None, "account": ACCOUNT, "source": source, "offset": 0}


def test_attachment_details_setting_survives_in_cursor(mailbox, monkeypatch):
    seen = []
    monkeypatch.setattr(mail, "list_attachments", lambda message_id, account_email: seen.append(message_id) or [])
    original = graph.get_json

    def response(*args, **kwargs):
        page = original(*args, **kwargs)
        page["value"][0]["hasAttachments"] = True
        return page

    monkeypatch.setattr(graph, "get_json", response)
    first = invoke_page(["list", "--attachment-details"])
    invoke_page(["list", "--cursor", first["next_cursor"]])
    assert seen == ["interactive-1", "interactive-2"]


def test_stale_cursor_failure_leaves_existing_cache_untouched(mailbox, monkeypatch):
    mail.list_messages(fetch=1)
    cache = mail._last_list_path(ACCOUNT)
    before = cache.read_bytes()
    first = invoke_page(["search", "alice"])

    def fail(*args, **kwargs):
        raise graph.GraphError("HTTP 410 Gone")

    monkeypatch.setattr(graph, "get_json", fail)
    result = runner.invoke(app, ["search", "--cursor", first["next_cursor"], "--page-json"])
    assert result.exit_code == 1
    assert "start a new --page-json query" in result.output
    assert cache.read_bytes() == before
