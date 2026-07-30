from __future__ import annotations

import base64
import json
import time
from typing import Any, Mapping, Optional
from urllib import error, parse, request


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

DEFAULT_TIMEOUT = 30
UPLOAD_TIMEOUT = 120

# Graph throttles aggressively during batch operations. 429 and 503 mean the
# request was rejected before it was applied, so replaying it is safe for every
# verb this module uses -- including POST /send.
#
# 504 is deliberately absent: a gateway timeout is ambiguous, the backend may
# have applied the request and only lost the response. Replaying that would
# send a message twice.
RETRY_STATUS_CODES = frozenset({429, 503})
MAX_ATTEMPTS = 3
MAX_RETRY_DELAY_SECONDS = 30.0


class GraphError(RuntimeError):
    pass


def quote_path_segment(value: str) -> str:
    return parse.quote(value, safe="")


def _absolute_url(path: str, params: Optional[Mapping[str, str]] = None) -> str:
    url = path if path.startswith("https://") else GRAPH_BASE_URL + path
    if params:
        separator = "&" if "?" in url else "?"
        url = url + separator + parse.urlencode(params)
    return url


def _retry_delay(exc: error.HTTPError, attempt: int) -> float:
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    if retry_after:
        try:
            return min(float(retry_after), MAX_RETRY_DELAY_SECONDS)
        except (TypeError, ValueError):
            pass
    return min(2.0**attempt, MAX_RETRY_DELAY_SECONDS)


def _request(
    method: str,
    path: str,
    *,
    access_token: Optional[str] = None,
    params: Optional[Mapping[str, str]] = None,
    data: Optional[bytes] = None,
    headers: Optional[Mapping[str, str]] = None,
    accept: str = "application/json",
    timeout: int = DEFAULT_TIMEOUT,
) -> bytes:
    url = _absolute_url(path, params)
    request_headers = {"Accept": accept}
    if access_token:
        request_headers["Authorization"] = f"Bearer {access_token}"
    request_headers.update(headers or {})

    for attempt in range(MAX_ATTEMPTS):
        graph_request = request.Request(
            url,
            data=data,
            headers=request_headers,
            method=method,
        )
        try:
            with request.urlopen(graph_request, timeout=timeout) as response:
                return response.read()
        except error.HTTPError as exc:
            if exc.code in RETRY_STATUS_CODES and attempt < MAX_ATTEMPTS - 1:
                time.sleep(_retry_delay(exc, attempt))
                continue
            detail = exc.read().decode("utf-8", errors="replace")
            raise GraphError(f"Graph request failed: HTTP {exc.code} {exc.reason}: {detail}") from exc
        except Exception as exc:
            raise GraphError(f"Graph request failed: {exc}") from exc

    raise GraphError(f"Graph request failed: still throttled after {MAX_ATTEMPTS} attempts")


def _json_response(payload: bytes, *, allow_empty: bool = False) -> dict[str, Any]:
    if allow_empty and not payload:
        return {}
    try:
        return json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GraphError("Graph returned invalid JSON") from exc


def get_json(
    path: str,
    access_token: str,
    params: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    return _json_response(_request("GET", path, access_token=access_token, params=params))


def get_all_pages(
    path: str,
    access_token: str,
    params: Optional[Mapping[str, str]] = None,
) -> list[dict[str, Any]]:
    """Collect `value` entries across every `@odata.nextLink` page."""
    values: list[dict[str, Any]] = []
    response = get_json(path, access_token, params=params)
    while True:
        values.extend(response.get("value") or [])
        next_link = response.get("@odata.nextLink")
        if not isinstance(next_link, str) or not next_link:
            return values
        response = get_json(next_link, access_token)


def post_json(path: str, access_token: str, body: Mapping[str, Any]) -> dict[str, Any]:
    return _json_response(
        _request(
            "POST",
            path,
            access_token=access_token,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
    )


def post_mime_json(path: str, access_token: str, mime_bytes: bytes) -> dict[str, Any]:
    return _json_response(
        _request(
            "POST",
            path,
            access_token=access_token,
            data=base64.b64encode(mime_bytes),
            headers={"Content-Type": "text/plain"},
        )
    )


def post_empty(path: str, access_token: str) -> None:
    _request("POST", path, access_token=access_token, data=b"")


def patch_json(path: str, access_token: str, body: Mapping[str, Any]) -> None:
    _request(
        "PATCH",
        path,
        access_token=access_token,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )


def delete_empty(path: str, access_token: str) -> None:
    _request("DELETE", path, access_token=access_token)


def put_bytes(
    url: str,
    data: bytes,
    headers: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    # Upload-session URLs carry their own credentials; sending the Graph bearer
    # token alongside them is rejected.
    return _json_response(
        _request("PUT", url, data=data, headers=headers, timeout=UPLOAD_TIMEOUT),
        allow_empty=True,
    )


def get_bytes(
    path: str,
    access_token: str,
    accept: str = "application/octet-stream",
) -> bytes:
    return _request("GET", path, access_token=access_token, accept=accept)
