"""
topic_dedup.py — RSS topic deduplication for rss_watcher.py.

Compares incoming RSS entries against recent open GitHub issues and decides:
  CREATE_NEW    — no match; proceed to create a new issue
  ADD_SOURCE    — match found; post source URL as comment on existing issue
  CREATE_FOLLOWUP — follow-up story; create new issue with follow-up label

LLM calls (when method includes "llm" or followup_mode includes "content") are
delegated to an injected ``BaseAgent`` instance.  If no agent is provided, LLM
paths return False with a warning.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from agents.base_agent import BaseAgent

_log = logging.getLogger(__name__)

_VALID_METHODS = frozenset({"fuzzy", "keyword", "llm", "all"})
_VALID_FOLLOWUP_MODES = frozenset({"time", "content", "both"})


@dataclass
class DedupeResult:
    """Result of deduplication check against existing GitHub issues.

    Attributes:
        action: One of CREATE_NEW, ADD_SOURCE, or CREATE_FOLLOWUP
        matched_issue: Dictionary of matched issue if action != CREATE_NEW
        matched_number: Issue number if match found
    """

    action: Literal["CREATE_NEW", "ADD_SOURCE", "CREATE_FOLLOWUP"]
    matched_issue: dict | None = None
    matched_number: int | None = None


def _fuzzy_similar(title_a: str, title_b: str, threshold: float = 0.75) -> bool:
    """Token-set ratio comparison using SequenceMatcher on sorted word tokens.

    Lowercases and sorts all words (including duplicates) before comparing,
    making the score order-insensitive but sensitive to word frequency.

    Compares two titles by tokenizing into words, sorting them, and using
    SequenceMatcher to compute a similarity ratio. This approach is more
    robust to word order variations than direct string comparison.

    Args:
        title_a: First title to compare
        title_b: Second title to compare
        threshold: Minimum ratio required (default 0.75)

    Returns:
        True if similarity ratio >= threshold, False otherwise
    """

    def _token_set(s: str) -> str:
        """Convert string to sorted, lowercased word tokens (duplicates preserved)."""
        return " ".join(sorted(s.lower().split()))

    ratio = SequenceMatcher(None, _token_set(title_a), _token_set(title_b)).ratio()
    return ratio >= threshold


# Patterns for named entities worth matching
_CVE_RE = re.compile(r"CVE-\d{4}-\d+", re.IGNORECASE)
_VERSION_RE = re.compile(r"\b\d+\.\d+(?:\.\d+)?\b")
# Common English stopwords to filter noun candidates
_STOPWORDS = {
    "the", "a", "an", "in", "on", "at", "of", "for", "to", "and", "or",
    "but", "is", "are", "was", "were", "be", "been", "being", "have",
    "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "with", "from", "by", "as", "this", "that", "its",
    "it", "new", "over", "after", "amid", "into", "than", "says", "said",
    "via", "how", "why", "what", "who", "which", "when", "users", "data",
    "million", "millions", "billion",
}


def _extract_keywords(text: str) -> set[str]:
    """Extract CVEs, version strings, and capitalised noun-like tokens.

    Identifies meaningful keywords from text including:
    - CVE IDs (e.g., CVE-2024-12345) → normalized to uppercase
    - Version strings (e.g., 6.9, 1.2.3) → preserved as-is
    - Capitalised words (likely proper nouns / product names) → lowercased,
      filtered by stopwords and length (> 2 chars)

    CVE tokens are excluded from proper noun detection to prevent
    double-extraction.

    Args:
        text: Text to extract keywords from

    Returns:
        Set of extracted keywords (CVEs uppercase, versions as-is,
        proper nouns lowercase).
    """
    keywords: set[str] = set()

    # Extract CVE IDs and record the raw tokens to skip in proper noun loop
    cve_tokens: set[str] = set()
    for m in _CVE_RE.finditer(text):
        normalised = m.group(0).upper()
        keywords.add(normalised)
        # Record each hyphen-free lowercase form that the proper noun loop would produce
        cve_tokens.add(re.sub(r"[^A-Za-z0-9]", "", m.group(0)).lower())

    # Version strings
    keywords.update(_VERSION_RE.findall(text))

    # Capitalised words (likely proper nouns / product names) that aren't stopwords
    for word in text.split():
        clean = re.sub(r"[^A-Za-z0-9]", "", word)
        if (
            clean
            and clean[0].isupper()
            and clean.lower() not in _STOPWORDS
            and len(clean) > 2
            and clean.lower() not in cve_tokens   # ← skip CVE tokens
        ):
            keywords.add(clean.lower())
    return keywords


def _keyword_similar(title_a: str, title_b: str, min_overlap: int = 2) -> bool:
    """Match if the two titles share at least min_overlap extracted keywords.

    Extracts meaningful keywords (CVEs, versions, proper nouns) from both titles
    and compares them. Returns True if the intersection has at least min_overlap
    keywords in common.

    Args:
        title_a: First title to compare
        title_b: Second title to compare
        min_overlap: Minimum number of shared keywords required (default 2)

    Returns:
        True if overlap >= min_overlap, False otherwise
    """
    kw_a = _extract_keywords(title_a)
    kw_b = _extract_keywords(title_b)
    overlap = kw_a & kw_b
    return len(overlap) >= min_overlap


class TopicDeduplicator:
    """Check incoming RSS entries against recent open issues for topic overlap.

    LLM calls are delegated to the injected ``llm`` agent.  Pass a
    ``BaseAgent`` instance configured with the desired model/backend.
    If ``llm`` is None, any LLM-dependent path returns False with a warning.
    """

    def __init__(
        self,
        method: str = "all",
        fuzzy_threshold: float = 0.85,
        keyword_min_overlap: int = 2,
        add_source_max_age_hours: int = 48,
        followup_mode: str = "time",
        min_age_hours: int = 168,
        llm: "BaseAgent | None" = None,
    ) -> None:
        if method not in _VALID_METHODS:
            _log.warning(
                "TopicDeduplicator: unknown method %r — defaulting to 'all'. "
                "Valid values: %s",
                method,
                ", ".join(sorted(_VALID_METHODS)),
            )
            method = "all"
        self._method = method

        if followup_mode not in _VALID_FOLLOWUP_MODES:
            _log.warning(
                "TopicDeduplicator: unknown followup_mode %r — defaulting to 'time'. "
                "Valid values: %s",
                followup_mode,
                ", ".join(sorted(_VALID_FOLLOWUP_MODES)),
            )
            followup_mode = "time"
        self._followup_mode = followup_mode

        self._fuzzy_threshold = fuzzy_threshold
        self._keyword_min_overlap = keyword_min_overlap
        self._add_source_max_age_hours = add_source_max_age_hours
        self._min_age_hours = min_age_hours
        self._llm = llm

    def _is_similar(self, entry: dict, issue: dict) -> bool:
        """Return True if entry and issue cover the same topic."""
        entry_title = entry.get("title", "")
        issue_title = issue.get("title", "")
        entry_summary = entry.get("summary", "")
        issue_body = issue.get("body", "")

        methods = (
            ["fuzzy", "keyword", "llm"] if self._method == "all"
            else [self._method]
        )
        for m in methods:
            if m == "fuzzy" and _fuzzy_similar(entry_title, issue_title, self._fuzzy_threshold):
                return True
            if m == "keyword" and _keyword_similar(entry_title, issue_title, self._keyword_min_overlap):
                return True
            if m == "llm":
                if self._llm is None:
                    _log.warning("TopicDeduplicator: LLM similarity requested but no agent injected — skipping")
                    continue
                prompt = (
                    f"Story A title: {entry_title}\nStory A summary: {entry_summary}\n\n"
                    f"Story B title: {issue_title}\nStory B summary: {issue_body}\n\n"
                    "Are these two news stories about the same event? "
                    "Answer YES or NO with one sentence of reasoning."
                )
                try:
                    reply = self._llm.call(prompt)
                    if reply.strip().upper().startswith("YES"):
                        return True
                except Exception as exc:  # noqa: BLE001
                    _log.warning("LLM similarity check failed (%s); skipping", exc)
        return False

    def check(self, entry: dict, open_issues: list[dict]) -> DedupeResult:
        """Compare entry against open_issues and return the appropriate action."""
        from datetime import datetime, timezone
        for issue in open_issues:
            if self._is_similar(entry, issue):
                if self._is_followup(entry, issue):
                    return DedupeResult(
                        action="CREATE_FOLLOWUP",
                        matched_issue=issue,
                        matched_number=issue["number"],
                    )
                # Gate ADD_SOURCE by age: only comment on recent issues
                created_str = issue.get("created_at", "")
                is_recent = True  # default to recent if we can't parse
                if created_str:
                    try:
                        created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                        age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600
                        is_recent = age_hours <= self._add_source_max_age_hours
                    except ValueError:
                        pass
                if is_recent:
                    return DedupeResult(
                        action="ADD_SOURCE",
                        matched_issue=issue,
                        matched_number=issue["number"],
                    )
                # Match found but too old for ADD_SOURCE and not a followup → treat as CREATE_NEW
                continue
        return DedupeResult(action="CREATE_NEW")

    def _is_followup(self, entry: dict, issue: dict) -> bool:
        """Decide if the matched entry is a follow-up rather than a duplicate."""
        mode = self._followup_mode
        if mode == "time":
            return self._age_check(issue)
        if mode == "content":
            return self._content_check(entry, issue)
        if mode == "both":
            return self._age_check(issue) and self._content_check(entry, issue)
        # Unknown mode — log and default to time-based check (no LLM call)
        _log.warning(
            "TopicDeduplicator: unknown followup_mode %r — defaulting to 'time'. "
            "Valid values: time, content, both",
            mode,
        )
        return self._age_check(issue)

    def _age_check(self, issue: dict) -> bool:
        from datetime import datetime, timezone
        created_str = issue.get("created_at", "")
        if not created_str:
            return False
        try:
            created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600
            return age_hours >= self._min_age_hours
        except ValueError:
            return False

    def _content_check(self, entry: dict, issue: dict) -> bool:
        """Use an LLM to check whether the new story contains significant new facts."""
        if self._llm is None:
            _log.warning("TopicDeduplicator: content follow-up check requested but no agent injected — defaulting to False")
            return False
        prompt = (
            f"Original story title: {issue.get('title', '')}\n"
            f"Original story body: {issue.get('body', '')[:400]}\n\n"
            f"New story title: {entry.get('title', '')}\n"
            f"New story summary: {entry.get('summary', '')}\n\n"
            "Does the new story contain significant new facts not present in the original? "
            "Answer YES or NO with one sentence of reasoning."
        )
        try:
            reply = self._llm.call(prompt)
            return reply.strip().upper().startswith("YES")
        except Exception as exc:  # noqa: BLE001
            _log.warning("Follow-up content check failed (%s); defaulting to False", exc)
            return False
