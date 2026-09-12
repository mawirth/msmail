"""Tests must never use a developer's real mailbox or account state."""
import pytest

from msmail.core import auth, graph


@pytest.fixture(autouse=True)
def isolated_account_state(monkeypatch, tmp_path):
    state = tmp_path / "msmail-state"
    monkeypatch.setattr(auth, "STATE_DIR", state)
    monkeypatch.setattr(auth, "STATE_FILE", state / "auth-state.json")
    monkeypatch.setattr(auth, "ACCOUNTS_DIR", state / "accounts")
    monkeypatch.setattr(auth, "_hardened_state_dirs", set())

    def no_network(*args, **kwargs):
        raise AssertionError("Unit tests must stub Microsoft authentication and Graph requests")

    monkeypatch.setattr(auth, "_app", no_network)
    monkeypatch.setattr(graph.request, "urlopen", no_network)
