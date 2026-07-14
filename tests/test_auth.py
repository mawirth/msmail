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
