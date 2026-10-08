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


def test_logout_removes_the_cached_message_list(monkeypatch, tmp_path):
    """last-list.json holds subjects and body previews."""
    state_dir = _configure_state(monkeypatch, tmp_path)
    account = state_dir / "accounts" / auth.account_key("me@example.com")
    account.mkdir(parents=True)
    (account / "msal-token-cache.json").write_text("token", encoding="utf-8")
    (account / "last-list.json").write_text('[{"body_preview": "secret"}]', encoding="utf-8")
    (account / "signature.txt").write_text("Alex", encoding="utf-8")
    (account / "profile.json").write_text("{}", encoding="utf-8")
    auth.write_private_text(state_dir / "auth-state.json", '{"active_account": "me@example.com"}')

    assert auth.logout() is True

    assert not (account / "msal-token-cache.json").exists()
    assert not (account / "last-list.json").exists()
    # Configuration survives, so logging back in does not mean setting up again.
    assert (account / "signature.txt").exists()
    assert (account / "profile.json").exists()


def test_state_is_hardened_once_per_process(monkeypatch, tmp_path):
    state_dir = _configure_state(monkeypatch, tmp_path)
    state_dir.mkdir(parents=True)
    monkeypatch.setattr(auth, "_hardened_state_dirs", set())
    walks = []
    monkeypatch.setattr(auth, "harden_runtime_state", lambda: walks.append(str(auth.STATE_DIR)))

    for _ in range(5):
        auth._harden_runtime_state_once()

    assert walks == [str(state_dir)]


def test_a_different_state_directory_is_hardened_again(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "_hardened_state_dirs", set())
    walks = []
    monkeypatch.setattr(auth, "harden_runtime_state", lambda: walks.append(str(auth.STATE_DIR)))

    for name in ("first", "second", "first"):
        monkeypatch.setattr(auth, "STATE_DIR", tmp_path / name)
        auth._harden_runtime_state_once()

    assert walks == [str(tmp_path / "first"), str(tmp_path / "second")]


def test_token_reuse_is_scoped_by_account_expiry_and_invocation(monkeypatch):
    from types import SimpleNamespace

    acquisitions = []
    now = [100.0]
    monkeypatch.setattr(auth, 'monotonic', lambda: now[0])
    monkeypatch.setattr(auth, '_load_profile', lambda email: None)
    monkeypatch.setattr(auth, '_load_cache', lambda email: email)
    monkeypatch.setattr(auth, '_save_cache', lambda *args: None)

    def app(email):
        def acquire(scopes, account):
            acquisitions.append(email)
            return {'access_token': email, 'expires_in': 120}
        return SimpleNamespace(get_accounts=lambda: [{'username': email}], acquire_token_silent=acquire)

    monkeypatch.setattr(auth, '_app', app)
    with auth.token_session():
        assert auth.get_access_token('first@example.invalid')[0] == 'first@example.invalid'
        auth.get_access_token('first@example.invalid')
        assert auth.get_access_token('second@example.invalid')[0] == 'second@example.invalid'
        assert len(acquisitions) == 2
        now[0] += 61
        auth.get_access_token('first@example.invalid')
        assert len(acquisitions) == 3
    with auth.token_session():
        auth.get_access_token('first@example.invalid')
    assert len(acquisitions) == 4


def test_failed_token_session_does_not_retain_credentials(monkeypatch):
    import pytest

    with pytest.raises(RuntimeError, match='cancelled'):
        with auth.token_session():
            raise RuntimeError('cancelled')
    assert auth._token_session.get() is None


def test_reference_resolution_uses_local_canonical_account_without_auth(monkeypatch):
    from msmail.core import mail

    auth._save_profile(auth.Account(email='alias@example.invalid', account_key='alias'))
    path = auth._profile_path('alias@example.invalid')
    auth.write_private_text(path, '{"email": "canonical@example.invalid"}')
    monkeypatch.setattr(auth, 'get_access_token', lambda *args: (_ for _ in ()).throw(AssertionError('must not acquire token')))
    assert mail.resolve_message_reference('messageID', 'alias@example.invalid') == ('messageID', 'canonical@example.invalid')


def test_corrupt_auth_state_has_actionable_error():
    import pytest
    from msmail.core.errors import MsmailError

    auth.write_private_text(auth.STATE_FILE, '{broken')
    with pytest.raises(MsmailError, match='account state'):
        auth.active_email()
