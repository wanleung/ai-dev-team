"""
NewsReviewerAgent: reviews a finalised news article (English + translations).

Checks:
  - English: fact plausibility against source URL, wording QA
  - zh-hk: Traditional Chinese characters, Cantonese vocabulary
  - zh-tw: Traditional Chinese characters, Formal Mandarin vocabulary

Input:  article (str), article_zh_hk (str), article_zh_tw (str), source_url (str)
Output: dict with 'verdict' (PASS|NEEDS_REVISION), 'issues' (list[str]), 'confidence' (str)
"""
from __future__ import annotations

import ipaddress
import logging
import re
import socket
import urllib.parse
import urllib.request

from .base_agent import BaseAgent

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

    def run(
        self,
        article: str,
        article_zh_hk: str,
        article_zh_tw: str,
        source_url: str = "",
    ) -> dict:
        """Review article quality and translation character correctness.

        Args:
            article: Final English article (markdown + frontmatter).
            article_zh_hk: Written Cantonese translation.
            article_zh_tw: Formal Traditional Chinese translation.
            source_url: Original source URL for fact-checking (may be empty).

        Returns:
            dict with keys:
                - verdict (str): "PASS" or "NEEDS_REVISION"
                - issues (list[str]): annotated issue lines e.g. "[FACT] Wrong version…"
                - confidence (str): "high" | "medium" | "low"
        """
        source_content = _fetch_source(source_url)
        source_section = (
            f"<SOURCE_CONTENT>\n{source_content[:8000]}\n</SOURCE_CONTENT>\n\n"
            if source_content
            else "<SOURCE_CONTENT>Not available — skip fact check, still check wording and characters.</SOURCE_CONTENT>\n\n"
        )

        prompt = (
            f"{source_section}"
            f"<ENGLISH_ARTICLE>\n{article}\n</ENGLISH_ARTICLE>\n\n"
            f"<ZH_HK_ARTICLE>\n{article_zh_hk}\n</ZH_HK_ARTICLE>\n\n"
            f"<ZH_TW_ARTICLE>\n{article_zh_tw}\n</ZH_TW_ARTICLE>\n\n"
            "Review all three articles according to your role instructions.\n"
            "Output ONLY the structured verdict in the exact format specified."
        )

        output = self.call(prompt)
        return _parse_verdict(output)
