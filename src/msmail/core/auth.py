from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
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


def _account_dir(email: str) -> Path:
    return ACCOUNTS_DIR / account_key(email)


def account_dir(email: str) -> Path:
    return _account_dir(email)


def _token_cache_path(email: str) -> Path:
    return _account_dir(email) / "msal-token-cache.json"


def _profile_path(email: str) -> Path:
    return _account_dir(email) / "profile.json"


def _load_cache(email: str) -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    path = _token_cache_path(email)
    if path.exists():
        cache.deserialize(path.read_text(encoding="utf-8"))
    return cache


def _save_cache(email: str, cache: msal.SerializableTokenCache) -> None:
    if not cache.has_state_changed:
        return
    directory = _account_dir(email)
    directory.mkdir(parents=True, exist_ok=True)
    _token_cache_path(email).write_text(cache.serialize(), encoding="utf-8")


def _app(cache: msal.SerializableTokenCache) -> msal.PublicClientApplication:
    return msal.PublicClientApplication(
        client_id=_client_id(),
        authority=AUTHORITY,
        token_cache=cache,
    )


def _active_email() -> str | None:
    if not STATE_FILE.exists():
        return None
    data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    email = data.get("active_account")
    return email if isinstance(email, str) and email else None


def active_email() -> str | None:
    return _active_email()


def _set_active(email: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"active_account": email}, indent=2) + "\n",
        encoding="utf-8",
    )


def _save_profile(account: Account) -> None:
    if not account.account_key:
        return
    directory = _account_dir(account.email)
    directory.mkdir(parents=True, exist_ok=True)
    data = asdict(account)
    data["last_used"] = datetime.now(timezone.utc).isoformat()
    _profile_path(account.email).write_text(
        json.dumps(data, indent=2) + "\n",
        encoding="utf-8",
    )


def _load_profile(email: str) -> Account | None:
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

    # If Graph reports a different primary address, move the cache to that key
    # as the canonical account reference.
    if account.email != normalized:
        canonical_cache = _load_cache(account.email)
        canonical_cache.deserialize(cache.serialize())
        _save_cache(account.email, canonical_cache)

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
    email = _active_email()
    if not email:
        return False

    if STATE_FILE.exists():
        STATE_FILE.unlink()
    token_cache = _token_cache_path(email)
    if token_cache.exists():
        token_cache.unlink()
    return True
