import io
import json
from urllib import error

import pytest

from msmail.core import graph


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_get_json_retries_while_throttled(monkeypatch):
    attempts = []
    sleeps = []

    def urlopen(graph_request, timeout=None):
        attempts.append(graph_request.full_url)
        if len(attempts) < 3:
            raise error.HTTPError(
                graph_request.full_url,
                429,
                "Too Many Requests",
                {"Retry-After": "0"},
                None,
            )
        return FakeResponse(b'{"value": []}')

    monkeypatch.setattr(graph.request, "urlopen", urlopen)
    monkeypatch.setattr(graph.time, "sleep", lambda seconds: sleeps.append(seconds))

    assert graph.get_json("/me/messages", "token") == {"value": []}
    assert len(attempts) == 3
    assert sleeps == [0.0, 0.0]


def test_retry_honours_retry_after_header(monkeypatch):
    sleeps = []
    attempts = []

    def urlopen(graph_request, timeout=None):
        attempts.append(graph_request.full_url)
        if len(attempts) < 2:
            raise error.HTTPError(
                graph_request.full_url,
                503,
                "Service Unavailable",
                {"Retry-After": "7"},
                None,
            )
        return FakeResponse(b"{}")

    monkeypatch.setattr(graph.request, "urlopen", urlopen)
    monkeypatch.setattr(graph.time, "sleep", lambda seconds: sleeps.append(seconds))

    graph.get_json("/me", "token")

    assert sleeps == [7.0]


def test_gives_up_after_max_attempts(monkeypatch):
    attempts = []

    def urlopen(graph_request, timeout=None):
        attempts.append(graph_request.full_url)
        raise error.HTTPError(
            graph_request.full_url,
            429,
            "Too Many Requests",
            {"Retry-After": "0"},
            io.BytesIO(b"throttled"),
        )

    monkeypatch.setattr(graph.request, "urlopen", urlopen)
    monkeypatch.setattr(graph.time, "sleep", lambda seconds: None)

    with pytest.raises(graph.GraphError) as excinfo:
        graph.get_json("/me/messages", "token")

    assert len(attempts) == graph.MAX_ATTEMPTS
    assert "HTTP 429" in str(excinfo.value)


def test_client_errors_are_not_retried(monkeypatch):
    attempts = []

    def urlopen(graph_request, timeout=None):
        attempts.append(graph_request.full_url)
        raise error.HTTPError(
            graph_request.full_url,
            404,
            "Not Found",
            {},
            io.BytesIO(b'{"error": {"message": "message not found"}}'),
        )

    monkeypatch.setattr(graph.request, "urlopen", urlopen)

    with pytest.raises(graph.GraphError) as excinfo:
        graph.get_json("/me/messages/missing", "token")

    assert len(attempts) == 1
    assert "HTTP 404" in str(excinfo.value)
    assert "message not found" in str(excinfo.value)


def test_get_all_pages_follows_next_link(monkeypatch):
    second_page = "https://graph.microsoft.com/v1.0/me/mailFolders?page=2"
    pages = {
        "https://graph.microsoft.com/v1.0/me/mailFolders?%24top=100": {
            "value": [{"id": "a"}],
            "@odata.nextLink": second_page,
        },
        second_page: {"value": [{"id": "b"}, {"id": "c"}]},
    }

    def urlopen(graph_request, timeout=None):
        return FakeResponse(json.dumps(pages[graph_request.full_url]).encode("utf-8"))

    monkeypatch.setattr(graph.request, "urlopen", urlopen)

    result = graph.get_all_pages("/me/mailFolders", "token", params={"$top": "100"})

    assert [item["id"] for item in result] == ["a", "b", "c"]


def test_upload_url_does_not_receive_the_bearer_token(monkeypatch):
    captured = {}

    def urlopen(graph_request, timeout=None):
        captured["headers"] = dict(graph_request.headers)
        captured["timeout"] = timeout
        return FakeResponse(b"")

    monkeypatch.setattr(graph.request, "urlopen", urlopen)

    assert graph.put_bytes("https://upload.example/session", b"chunk") == {}
    assert not any(key.lower() == "authorization" for key in captured["headers"])
    assert captured["timeout"] == graph.UPLOAD_TIMEOUT


def test_ambiguous_gateway_timeout_is_not_replayed(monkeypatch):
    """A 504 may mean the send already happened; replaying it would send twice."""
    attempts = []

    def urlopen(graph_request, timeout=None):
        attempts.append(graph_request.full_url)
        raise error.HTTPError(
            graph_request.full_url,
            504,
            "Gateway Timeout",
            {},
            io.BytesIO(b"gateway timeout"),
        )

    monkeypatch.setattr(graph.request, "urlopen", urlopen)
    monkeypatch.setattr(graph.time, "sleep", lambda seconds: pytest.fail("must not sleep for a retry"))

    with pytest.raises(graph.GraphError):
        graph.post_empty("/me/messages/draft-id/send", "token")

    assert len(attempts) == 1
