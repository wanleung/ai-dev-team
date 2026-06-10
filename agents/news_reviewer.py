"""
NewsReviewerAgent: reviews a finalised news article (English + Traditional Chinese translation).

Checks:
  - English: fact plausibility against source URL, wording QA
  - zh-tw: Traditional Chinese characters, Hong Kong vocabulary and press conventions

Input:  article (str), article_zh_tw (str), source_url (str)
Output: dict with 'verdict' (PASS|NEEDS_REVISION), 'issues' (list[str]), 'confidence' (str)
"""
from __future__ import annotations

import ipaddress
import logging
import re
import socket
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

from .base_agent import BaseAgent

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

_log = logging.getLogger("news_reviewer")
_FETCH_TIMEOUT = 10  # seconds


def _is_safe_url(url: str) -> bool:
    """Return True only for public http/https URLs (blocks SSRF vectors).

    Rejects:
    - Non-http/https schemes (file://, ftp://, etc.)
    - Localhost / loopback addresses
    - Private / link-local / reserved IP ranges (RFC 1918, RFC 4193, etc.)
    """
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname or ""
        if not hostname:
            return False
        # Resolve to IP and check for private/reserved ranges
        addr = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        for *_, sockaddr in addr:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except Exception:
        return False


def _fetch_source(url: str) -> str:
    """Fetch source URL content. Returns empty string on any error or unsafe URL."""
    if not url:
        return ""
    if not _is_safe_url(url):
        _log.warning("news_reviewer: blocked fetch of unsafe URL %r", url)
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            raw = resp.read(32_000)  # cap at 32 KB
            return raw.decode("utf-8", errors="replace")
    except Exception as exc:
        _log.warning("news_reviewer: could not fetch source URL %r: %s", url, exc)
        return ""


def _source_unusable_reason(content: str) -> str:
    """Return a reason if fetched source is not useful article text."""
    raw_lower = content.lower()
    text = re.sub(r"<[^>]+>", " ", content)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "empty"
    lower = text.lower()
    boilerplate_terms = (
        "cookie consent",
        "we use cookies",
        "accept reject",
        "manage preferences",
        "privacy policy",
        "cookie settings",
        "consent management",
        "cookie-consent",
    )
    boilerplate_hits = sum(
        1 for term in boilerplate_terms if term in lower or term in raw_lower
    )
    markup_terms = (
        "<script",
        "<style",
        "function ",
        "localstorage",
        "cookieconsent",
        "cookie-consent-modal",
    )
    markup_hits = sum(1 for term in markup_terms if term in raw_lower)
    word_count = len(re.findall(r"\b\w+\b", text))
    if boilerplate_hits >= 2 and (word_count < 120 or markup_hits >= 2):
        return "boilerplate"
    if word_count < 40:
        return "too little article text"
    return ""


def _parse_verdict(output: str) -> dict:
    """Parse structured reviewer output into a result dict.

    Returns {'verdict': 'PASS'|'NEEDS_REVISION', 'issues': list[str], 'confidence': str}.
    On parse failure returns PASS (never block on bad reviewer output).
    """
    verdict_match = re.search(r"VERDICT:\s*(PASS|NEEDS_REVISION)", output)
    if not verdict_match:
        _log.warning("news_reviewer: could not parse VERDICT from output — defaulting to PASS")
        return {"verdict": "PASS", "issues": [], "confidence": "low"}

    verdict = verdict_match.group(1)
    issues: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("- ["):
            issues.append(line.lstrip("- "))

    conf_match = re.search(r"CONFIDENCE:\s*(high|medium|low)", output, re.IGNORECASE)
    confidence = conf_match.group(1).lower() if conf_match else "high"

    return {"verdict": verdict, "issues": issues, "confidence": confidence}


class NewsReviewerAgent(BaseAgent):
    """Review a finalised news article and its translations for quality."""

    role_name = "news_reviewer"
    _tool_registry: "ToolRegistry | None" = None  # set by __init__ when search MCP is available

    def __init__(self, *args, tool_registry: "ToolRegistry | None" = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._tool_registry = tool_registry

    def run(
        self,
        article: str,
        article_zh_tw: str,
        source_url: str = "",
    ) -> dict:
        """Review article quality and translation character correctness.

        Args:
            article: English article markdown
            article_zh_tw: Traditional Chinese translation
            source_url: Source URL for fact-checking

        Returns:
            dict with 'verdict' (PASS|NEEDS_REVISION), 'issues' (list), 'confidence' (str)
        """
        source_content = _fetch_source(source_url)
        unusable_reason = _source_unusable_reason(source_content) if source_content else ""
        source_fetched = bool(source_content) and not unusable_reason
        source_section = self._build_source_section(
            source_url, source_content if source_fetched else "", source_fetched, unusable_reason
        )

        prompt = (
            f"{source_section}"
            f"<ENGLISH_ARTICLE>\n{article}\n</ENGLISH_ARTICLE>\n\n"
            f"<ZH_TW_ARTICLE>\n{article_zh_tw}\n</ZH_TW_ARTICLE>\n\n"
            "Review both articles according to your role instructions.\n"
            "Output ONLY the structured verdict in the exact format specified."
        )

        output = self._call_reviewer(prompt, source_fetched)
        return _parse_verdict(output)

    def _build_source_section(
        self,
        source_url: str,
        source_content: str,
        source_fetched: bool,
        unusable_reason: str = "",
    ) -> str:
        """Build the source content section of the prompt."""
        if source_content:
            return f"<SOURCE_CONTENT>\n{source_content[:8000]}\n</SOURCE_CONTENT>\n\n"
        elif source_url and self._tool_registry is not None:
            reason = f" returned {unusable_reason}" if unusable_reason else " was blocked (HTTP 403 or similar)"
            _log.info("news_reviewer: direct source fetch for %r%s — will use web search tools", source_url, reason)
            return (
                f"<SOURCE_CONTENT>Direct fetch of {source_url!r}{reason}. "
                "Use available search/fetch tools to retrieve the original article or find "
                "corroborating sources for the article's key claims. Perform fact-checking based "
                "on what you find. If the original source remains unavailable but independent "
                "sources verify the claims, allow the article with CONFIDENCE: medium.</SOURCE_CONTENT>\n\n"
            )
        else:
            return "<SOURCE_CONTENT>Not available — skip fact check, still check wording and characters.</SOURCE_CONTENT>\n\n"

    def _call_reviewer(self, prompt: str, source_fetched: bool) -> str:
        """Call the LLM with or without tools depending on source availability."""
        if not source_fetched and self._tool_registry is not None:
            return self.call_with_tools(prompt, self._tool_registry)
        return self.call(prompt)
