from __future__ import annotations

import html
import re

from msmail.core import auth


DEFAULT_HTML_STYLE = "font-family: Arial, sans-serif; font-size: 10pt;"
HTML_TAG_RE = re.compile(
    r"</?(?:html|body|div|span|p|br|hr|table|thead|tbody|tr|td|th|ul|ol|li|"
    r"a|strong|b|em|i|u|font|h[1-6]|blockquote|pre|code|img|style)"
    r"(?:\s[^>]*)?/?>",
    re.IGNORECASE,
)


def _signature_path(account_email: str, suffix: str):
    return auth.account_dir(account_email) / f"signature.{suffix}"


def _read_signature(account_email: str, suffix: str) -> str | None:
    path = _signature_path(account_email, suffix)
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8").strip()
    return content or None


def _text_to_html(text: str) -> str:
    escaped = html.escape(text)
    return escaped.replace("\n", "<br>\n")


def looks_like_html(body: str) -> bool:
    return bool(HTML_TAG_RE.search(body or ""))


def format_html_body(body: str) -> str:
    if looks_like_html(body):
        return body

    paragraphs = re.split(r"\n\s*\n", (body or "").strip())
    rendered = []
    for paragraph in paragraphs:
        lines = paragraph.splitlines() or [""]
        rendered.append("<p>" + "<br>\n".join(html.escape(line) for line in lines) + "</p>")
    content = "\n".join(rendered) if rendered else ""
    return f'<div style="{DEFAULT_HTML_STYLE}">\n{content}\n</div>'


def append_signature(
    body: str,
    *,
    account_email: str,
    content_type: str,
    enabled: bool = True,
) -> str:
    if not enabled:
        return body

    if content_type.lower() == "html":
        signature = _read_signature(account_email, "html")
        if signature is None:
            text_signature = _read_signature(account_email, "txt")
            if text_signature is None:
                return body
            signature = _text_to_html(text_signature)
        separator = "<br><br>\n" if body.strip() else ""
        return body + separator + signature

    signature = _read_signature(account_email, "txt")
    if signature is None:
        return body
    separator = "\n\n" if body.strip() else ""
    return body + separator + signature
