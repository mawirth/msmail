from __future__ import annotations

import html
import re
from urllib import parse

from bs4 import BeautifulSoup


SAFELINK_RE = re.compile(
    r"https?://[^\s<>\"']*safelinks\.protection\.outlook\.com[^\s<>\"']*",
    re.IGNORECASE,
)


def unwrap_safelink(url: str) -> str:
    parsed = parse.urlparse(html.unescape(url))
    host = (parsed.hostname or "").lower()
    if host != "safelinks.protection.outlook.com" and not host.endswith(".safelinks.protection.outlook.com"):
        return url

    query = parse.parse_qs(parsed.query)
    original = query.get("url", [None])[0]
    if not original:
        return url
    return original


def unwrap_safelinks_in_text(text: str) -> str:
    normalized = (text or "").replace("\xa0", " ")
    return SAFELINK_RE.sub(lambda match: unwrap_safelink(match.group(0)), normalized)


def html_to_text(markup: str) -> str:
    if not markup:
        return ""

    soup = BeautifulSoup(markup, "html.parser")
    for element in soup(["script", "style", "meta", "head", "title"]):
        element.decompose()

    for link in soup.find_all("a"):
        label = link.get_text(" ", strip=True)
        href = link.get("href")
        if not href:
            continue
        href = unwrap_safelink(href)
        if label and label != href:
            link.replace_with(f"{label} <{href}>")
        else:
            link.replace_with(href)

    for br in soup.find_all("br"):
        br.replace_with("\n")

    for element in soup.find_all(["p", "div", "li", "tr", "table", "blockquote", "h1", "h2", "h3"]):
        element.append("\n")

    text = soup.get_text("\n")
    text = html.unescape(text).replace("\xa0", " ")
    text = unwrap_safelinks_in_text(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
