from __future__ import annotations

import base64
import json
from typing import Any, Mapping, Optional
from urllib import error, parse, request


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


class GraphError(RuntimeError):
    pass


def quote_path_segment(value: str) -> str:
    return parse.quote(value, safe="")


def get_json(
    path: str,
    access_token: str,
    params: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    if path.startswith("https://"):
        url = path
    else:
        url = GRAPH_BASE_URL + path

    if params:
        separator = "&" if "?" in url else "?"
        url = url + separator + parse.urlencode(params)

    graph_request = request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with request.urlopen(graph_request, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GraphError(f"Graph request failed: HTTP {exc.code} {exc.reason}: {detail}") from exc
    except Exception as exc:
        raise GraphError(f"Graph request failed: {exc}") from exc

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise GraphError("Graph returned invalid JSON") from exc


def post_json(path: str, access_token: str, body: Mapping[str, Any]) -> dict[str, Any]:
    url = path if path.startswith("https://") else GRAPH_BASE_URL + path
    payload = json.dumps(body).encode("utf-8")
    graph_request = request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(graph_request, timeout=30) as response:
            response_payload = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GraphError(f"Graph request failed: HTTP {exc.code} {exc.reason}: {detail}") from exc
    except Exception as exc:
        raise GraphError(f"Graph request failed: {exc}") from exc

    try:
        return json.loads(response_payload)
    except json.JSONDecodeError as exc:
        raise GraphError("Graph returned invalid JSON") from exc


def post_mime_json(path: str, access_token: str, mime_bytes: bytes) -> dict[str, Any]:
    url = path if path.startswith("https://") else GRAPH_BASE_URL + path
    payload = base64.b64encode(mime_bytes)
    graph_request = request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "text/plain",
        },
        method="POST",
    )

    try:
        with request.urlopen(graph_request, timeout=30) as response:
            response_payload = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GraphError(f"Graph request failed: HTTP {exc.code} {exc.reason}: {detail}") from exc
    except Exception as exc:
        raise GraphError(f"Graph request failed: {exc}") from exc

    try:
        return json.loads(response_payload)
    except json.JSONDecodeError as exc:
        raise GraphError("Graph returned invalid JSON") from exc


def post_empty(path: str, access_token: str) -> None:
    url = path if path.startswith("https://") else GRAPH_BASE_URL + path
    graph_request = request.Request(
        url,
        data=b"",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(graph_request, timeout=30) as response:
            response.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GraphError(f"Graph request failed: HTTP {exc.code} {exc.reason}: {detail}") from exc
    except Exception as exc:
        raise GraphError(f"Graph request failed: {exc}") from exc


def patch_json(path: str, access_token: str, body: Mapping[str, Any]) -> None:
    url = path if path.startswith("https://") else GRAPH_BASE_URL + path
    payload = json.dumps(body).encode("utf-8")
    graph_request = request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="PATCH",
    )

    try:
        with request.urlopen(graph_request, timeout=30) as response:
            response.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GraphError(f"Graph request failed: HTTP {exc.code} {exc.reason}: {detail}") from exc
    except Exception as exc:
        raise GraphError(f"Graph request failed: {exc}") from exc


def delete_empty(path: str, access_token: str) -> None:
    url = path if path.startswith("https://") else GRAPH_BASE_URL + path
    graph_request = request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        method="DELETE",
    )

    try:
        with request.urlopen(graph_request, timeout=30) as response:
            response.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GraphError(f"Graph request failed: HTTP {exc.code} {exc.reason}: {detail}") from exc
    except Exception as exc:
        raise GraphError(f"Graph request failed: {exc}") from exc


def put_bytes(
    url: str,
    data: bytes,
    headers: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    graph_request = request.Request(
        url,
        data=data,
        headers=dict(headers or {}),
        method="PUT",
    )

    try:
        with request.urlopen(graph_request, timeout=120) as response:
            response_payload = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GraphError(f"Graph request failed: HTTP {exc.code} {exc.reason}: {detail}") from exc
    except Exception as exc:
        raise GraphError(f"Graph request failed: {exc}") from exc

    if not response_payload:
        return {}

    try:
        return json.loads(response_payload)
    except json.JSONDecodeError as exc:
        raise GraphError("Graph returned invalid JSON") from exc


def get_bytes(
    path: str,
    access_token: str,
    accept: str = "application/octet-stream",
) -> bytes:
    url = path if path.startswith("https://") else GRAPH_BASE_URL + path
    graph_request = request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": accept,
        },
        method="GET",
    )

    try:
        with request.urlopen(graph_request, timeout=30) as response:
            return response.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GraphError(f"Graph request failed: HTTP {exc.code} {exc.reason}: {detail}") from exc
    except Exception as exc:
        raise GraphError(f"Graph request failed: {exc}") from exc
