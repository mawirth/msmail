import stat

from msmail.core import auth


def _configure_state(monkeypatch, tmp_path):
    state_dir = tmp_path / "msmail"
    monkeypatch.setattr(auth, "STATE_DIR", state_dir)
    monkeypatch.setattr(auth, "STATE_FILE", state_dir / "auth-state.json")
    monkeypatch.setattr(auth, "ACCOUNTS_DIR", state_dir / "accounts")
    return state_dir


def test_private_text_is_written_with_private_permissions(monkeypatch, tmp_path):
    state_dir = _configure_state(monkeypatch, tmp_path)
    path = state_dir / "accounts" / "me@example.com" / "token.json"

    auth.write_private_text(path, "secret")

    assert path.read_text(encoding="utf-8") == "secret"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE((state_dir / "accounts").stat().st_mode) == 0o700
    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700


def test_harden_runtime_state_repairs_existing_permissions(monkeypatch, tmp_path):
    state_dir = _configure_state(monkeypatch, tmp_path)
    account_dir = state_dir / "accounts" / "me@example.com"
    account_dir.mkdir(parents=True)
    token_file = account_dir / "msal-token-cache.json"
    token_file.write_text("secret", encoding="utf-8")
    state_dir.chmod(0o755)
    account_dir.chmod(0o755)
    token_file.chmod(0o644)

    auth.harden_runtime_state()

    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(account_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600


def test_login_writes_token_cache_under_canonical_address(monkeypatch, tmp_path):
    """Graph may report a different primary address than the one typed.

    Hermetic: the MSAL app and the Graph call are both fakes, so this never
    contacts Microsoft and never touches a real account.
    """
    state_dir = _configure_state(monkeypatch, tmp_path)

    class FakeApp:
        def __init__(self, cache):
            self.cache = cache

        def initiate_device_flow(self, scopes):
            return {
                "user_code": "CODE",
                "verification_uri": "https://example.invalid/device",
                "message": "Enter CODE",
            }

        def acquire_token_by_device_flow(self, flow):
            self.cache.deserialize('{"AccessToken": {"entry": {"secret": "cached-token"}}}')
            self.cache.has_state_changed = True
            return {"access_token": "access", "id_token_claims": {"tid": "tenant-id"}}

    monkeypatch.setattr(auth, "_app", lambda cache: FakeApp(cache))
    monkeypatch.setattr(
        auth.graph,
        "get_json",
        lambda *args, **kwargs: {
            "mail": "canonical@example.com",
            "displayName": "Canonical",
            "userPrincipalName": "canonical@example.com",
        },
    )

    result = auth.login("alias@example.com")

    assert result.account.email == "canonical@example.com"
    assert auth.active_email() == "canonical@example.com"

    # The active account must have a usable token cache, otherwise every
    # following command fails with "No token cache entry".
    canonical = state_dir / "accounts" / auth.account_key("canonical@example.com") / "msal-token-cache.json"
    assert canonical.exists()
    assert "cached-token" in canonical.read_text(encoding="utf-8")
    assert stat.S_IMODE(canonical.stat().st_mode) == 0o600
