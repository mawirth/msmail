from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Callable, Optional

import msal

from msmail.core import graph


STATE_DIR = Path.home() / ".local" / "share" / "msmail"
STATE_FILE = STATE_DIR / "auth-state.json"
ACCOUNTS_DIR = STATE_DIR / "accounts"

DEFAULT_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
AUTHORITY = "https://login.microsoftonline.com/common"
SCOPES = [
    "Mail.ReadWrite",
    "Mail.Send",
    "User.Read",
    "People.Read",
    "Contacts.Read",
]


@dataclass(frozen=True)
class Account:
    email: str
    display_name: str | None = None
    user_principal_name: str | None = None
    tenant_id: str | None = None
    account_key: str | None = None


@dataclass(frozen=True)
class DeviceLogin:
    user_code: str
    verification_uri: str
    message: str


@dataclass(frozen=True)
class LoginResult:
    account: Account
    device_login: DeviceLogin


def _client_id() -> str:
    return os.environ.get("MSMAIL_CLIENT_ID", DEFAULT_CLIENT_ID)


def account_key(email: str) -> str:
    normalized = email.strip().lower()
    return "".join(ch if ch.isalnum() or ch in "@._-" else "_" for ch in normalized)


def _set_private_mode(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        # Windows protects these files through the user's inherited ACLs and
        # does not implement POSIX permission bits in the same way.
        if os.name != "nt":
            raise


def ensure_private_directory(path: Path) -> Path:
    if path.is_symlink():
        raise RuntimeError(f"Refusing to use symlink as private state directory: {path}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    current = path
    while True:
        _set_private_mode(current, 0o700)
        if current == STATE_DIR or STATE_DIR not in current.parents:
            break
        current = current.parent
    return path


def write_private_text(path: Path, content: str) -> None:
    ensure_private_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _set_private_mode(temporary_path, 0o600)
        os.replace(temporary_path, path)
        _set_private_mode(path, 0o600)
    finally:
        temporary_path.unlink(missing_ok=True)


# Directories already walked in this process, so that a command touching the
# token cache, the profile and the account directory does not repeat the walk.
_hardened_state_dirs: set[str] = set()


def _harden_runtime_state_once() -> None:
    """Harden the state directory at most once per process and state directory.

    Permissions cannot drift while a single command runs, so repeating the
    recursive walk on every token load only costs time -- noticeably so with
    many imported recipient certificates.
    """
    key = str(STATE_DIR)
    if key in _hardened_state_dirs:
        return
    harden_runtime_state()
    _hardened_state_dirs.add(key)


def harden_runtime_state() -> None:
    """Restrict existing runtime state to the current user on POSIX systems."""
    if not STATE_DIR.exists():
        return
    if STATE_DIR.is_symlink():
        raise RuntimeError(f"Refusing to use symlink as private state directory: {STATE_DIR}")

    _set_private_mode(STATE_DIR, 0o700)
    for path in STATE_DIR.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_dir():
            _set_private_mode(path, 0o700)
        elif path.is_file():
            _set_private_mode(path, 0o600)


def _account_dir(email: str) -> Path:
    return ACCOUNTS_DIR / account_key(email)


def account_dir(email: str) -> Path:
    _harden_runtime_state_once()
    return ensure_private_directory(_account_dir(email))


def _token_cache_path(email: str) -> Path:
    return _account_dir(email) / "msal-token-cache.json"


def _profile_path(email: str) -> Path:
    return _account_dir(email) / "profile.json"


def _load_cache(email: str) -> msal.SerializableTokenCache:
    _harden_runtime_state_once()
    cache = msal.SerializableTokenCache()
    path = _token_cache_path(email)
    if path.exists():
        cache.deserialize(path.read_text(encoding="utf-8"))
    return cache


def _save_cache(email: str, cache: msal.SerializableTokenCache) -> None:
    if not cache.has_state_changed:
        return
    ensure_private_directory(_account_dir(email))
    write_private_text(_token_cache_path(email), cache.serialize())


def _app(cache: msal.SerializableTokenCache) -> msal.PublicClientApplication:
    return msal.PublicClientApplication(
        client_id=_client_id(),
        authority=AUTHORITY,
        token_cache=cache,
    )


def _active_email() -> str | None:
    _harden_runtime_state_once()
    if not STATE_FILE.exists():
        return None
    data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    email = data.get("active_account")
    return email if isinstance(email, str) and email else None


def active_email() -> str | None:
    return _active_email()


def _set_active(email: str) -> None:
    ensure_private_directory(STATE_DIR)
    write_private_text(
        STATE_FILE,
        json.dumps({"active_account": email}, indent=2) + "\n",
    )


def _save_profile(account: Account) -> None:
    if not account.account_key:
        return
    ensure_private_directory(_account_dir(account.email))
    data = asdict(account)
    data["last_used"] = datetime.now(timezone.utc).isoformat()
    write_private_text(
        _profile_path(account.email),
        json.dumps(data, indent=2) + "\n",
    )


def _load_profile(email: str) -> Account | None:
    _harden_runtime_state_once()
    path = _profile_path(email)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return Account(
        email=data["email"],
        display_name=data.get("display_name"),
        user_principal_name=data.get("user_principal_name"),
        tenant_id=data.get("tenant_id"),
        account_key=data.get("account_key"),
    )


def _profile_from_me(requested_email: str, me: dict, token_result: dict | None = None) -> Account:
    actual_email = (me.get("mail") or me.get("userPrincipalName") or requested_email).strip().lower()
    claims = (token_result or {}).get("id_token_claims") or {}
    return Account(
        email=actual_email,
        display_name=me.get("displayName"),
        user_principal_name=me.get("userPrincipalName"),
        tenant_id=claims.get("tid"),
        account_key=account_key(actual_email),
    )


def login(
    email: str,
    on_device_code: Optional[Callable[[DeviceLogin], None]] = None,
) -> LoginResult:
    """Authenticate with Microsoft identity platform using device code flow."""
    normalized = email.strip().lower()
    if "@" not in normalized:
        raise ValueError("Account must be referenced by email address.")

    cache = _load_cache(normalized)
    app = _app(cache)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(f"Could not create device flow: {flow}")

    device_login = DeviceLogin(
        user_code=flow["user_code"],
        verification_uri=flow["verification_uri"],
        message=flow["message"],
    )
    if on_device_code:
        on_device_code(device_login)

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        error = result.get("error_description") or result.get("error") or "unknown auth error"
        raise RuntimeError(error)

    me = graph.get_json(
        "/me",
        result["access_token"],
        params={"$select": "displayName,mail,userPrincipalName,id"},
    )
    account = _profile_from_me(normalized, me, result)
    _save_cache(normalized, cache)

    # If Graph reports a different primary address, copy the cache to that key
    # as the canonical account reference. Write it out directly: deserialize()
    # resets has_state_changed, so _save_cache would skip the write and leave
    # the active account pointing at a key without a token cache.
    if account.email != normalized:
        write_private_text(_token_cache_path(account.email), cache.serialize())

    _save_profile(account)
    _set_active(account.email)
    return LoginResult(
        account=account,
        device_login=device_login,
    )


def whoami() -> Optional[Account]:
    email = _active_email()
    if not email:
        return None

    profile = _load_profile(email)
    cache = _load_cache(email)
    try:
        app = _app(cache)
        accounts = app.get_accounts(username=email)
        token_result = None
        if accounts:
            token_result = app.acquire_token_silent(SCOPES, account=accounts[0])
    except Exception:
        return profile or Account(email=email, account_key=account_key(email))

    if not token_result or "access_token" not in token_result:
        return profile or Account(email=email, account_key=account_key(email))

    try:
        me = graph.get_json(
            "/me",
            token_result["access_token"],
            params={"$select": "displayName,mail,userPrincipalName,id"},
        )
    except Exception:
        return profile or Account(email=email, account_key=account_key(email))

    account = _profile_from_me(email, me, token_result)
    _save_cache(email, cache)
    _save_profile(account)
    return account


def get_access_token(email: Optional[str] = None) -> tuple[str, Account]:
    active = email.strip().lower() if email else _active_email()
    if not active:
        raise RuntimeError("No active account. Run: msmail auth --login <email>")

    cache = _load_cache(active)
    try:
        app = _app(cache)
        accounts = app.get_accounts(username=active)
        if not accounts:
            raise RuntimeError(f"No token cache entry for {active}. Run auth --login again.")

        result = app.acquire_token_silent(SCOPES, account=accounts[0])
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not initialize auth for {active}: {exc}") from exc

    if not result or "access_token" not in result:
        raise RuntimeError(f"Could not acquire token for {active}. Run auth --login again.")

    _save_cache(active, cache)
    profile = _load_profile(active)
    account = profile or Account(email=active, account_key=account_key(active))
    return result["access_token"], account


def logout() -> bool:
    """Drop the session for the active account.

    Removes the token cache and the cached message list, which holds subjects
    and body previews. Configuration the user set up -- profile, signatures and
    S/MIME material -- is deliberately kept so that logging back in does not
    mean setting the account up again.
    """
    email = _active_email()
    if not email:
        return False

    if STATE_FILE.exists():
        STATE_FILE.unlink()
    for path in (_token_cache_path(email), _account_dir(email) / "last-list.json"):
        if path.exists():
            path.unlink()
    return True
