"""
fetch_url — HTTP page fetcher tool.

Uses stdlib html.parser to strip tags. No extra dependencies beyond requests.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests

from .registry import LocalToolRegistry

fetch_url_tools = LocalToolRegistry()

_SKIP_TAGS = frozenset(["script", "style", "nav", "footer", "head", "noscript"])

# Hostnames/prefixes that must never be fetched (SSRF guard)
_BLOCKED_HOSTS = frozenset(["localhost", "0.0.0.0"])
_BLOCKED_PREFIXES = ("127.", "169.254.", "10.", "192.168.", "[::1]", "::1")
_MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024  # 5 MB hard cap


def _is_blocked_host(url: str) -> bool:
    """Return True if the URL targets a private/loopback address."""
    try:
        host = urlparse(url).hostname or ""
    except Exception:  # noqa: BLE001
        return True
    if host in _BLOCKED_HOSTS:
        return True
    return any(host.startswith(p) for p in _BLOCKED_PREFIXES)


class _TextExtractor(HTMLParser):
    """Strip HTML tags; skip content inside script/style/nav/footer."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip: int = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:  # noqa: ARG002
        if tag.lower() in _SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data: str) -> None:
        if self._skip == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        raw = " ".join(self._parts)
        return re.sub(r"\s+", " ", raw).strip()


@fetch_url_tools.tool(
    name="fetch_url",
    description=(
        "Fetch the text content of a web page. "
        "Returns clean plain text extracted from the HTML body (scripts and nav removed). "
        "Use this to read source articles during research."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Full URL of the page to fetch (https://...)",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return (default 8000)",
            },
        },
        "required": ["url"],
    },
)
def fetch_url(url: str, max_chars: int = 8000) -> str:
    """Fetch and return plain text from a URL."""
    if not url.startswith(("http://", "https://")):
        return f"[Error fetching {url}]: only http/https URLs are supported"
    if _is_blocked_host(url):
        return f"[Error fetching {url}]: private/loopback addresses are not allowed"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ai-software-house/1.0)"}
    try:
        resp = requests.get(url, headers=headers, timeout=15, stream=True)
        resp.raise_for_status()
        chunks: list[bytes] = []
        downloaded = 0
        for chunk in resp.iter_content(chunk_size=65536):
            chunks.append(chunk)
            downloaded += len(chunk)
            if downloaded >= _MAX_DOWNLOAD_BYTES:
                break
    except requests.RequestException as exc:
        return f"[Error fetching {url}]: {exc}"
    html = b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")
    extractor = _TextExtractor()
    extractor.feed(html)
    text = extractor.get_text()
    return text[:max_chars]
