# RSS Topic Deduplication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent duplicate GitHub issues when multiple RSS sources report the same news story, while correctly identifying follow-up coverage as new issues.

**Architecture:** A new `topic_dedup.py` module provides `TopicDeduplicator` which compares incoming RSS entries against recent open GitHub issues using configurable similarity methods (fuzzy/keyword/LLM/all). `rss_watcher.py` is modified to call it before issue creation — either adding a source comment on the existing issue, creating a follow-up issue, or proceeding as normal. If `topic_dedup` is absent from config, behaviour is unchanged.

**Tech Stack:** Python 3.11+, `difflib.SequenceMatcher` (fuzzy), `re` (keyword/CVE), `requests` (GitHub API, LLM), `dataclasses`, `pytest`

---

## Branch Setup

Create and push a feature branch before starting any task:

```bash
cd /home/wanleung/Projects/ai-software-house
git checkout -b feature/rss-topic-dedup
git push -u origin feature/rss-topic-dedup
```

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `topic_dedup.py` | **Create** | `TopicDeduplicator`, `DedupeResult`, all three similarity methods, follow-up detection |
| `tests/test_topic_dedup.py` | **Create** | Unit tests for all similarity methods and `TopicDeduplicator.check()` |
| `rss_watcher.py` | **Modify** | Add `_fetch_open_issues`, `_post_source_comment`, `_enrich_as_followup`; wire into `process_feeds()` |
| `tests/test_rss_watcher.py` | **Modify** | Add integration tests for dedup, add-source, and follow-up paths |

---

## Task 1: `DedupeResult` dataclass + fuzzy similarity

**Files:**
- Create: `topic_dedup.py`
- Create: `tests/test_topic_dedup.py`

- [ ] **Step 1.1: Write failing tests for fuzzy similarity**

```python
# tests/test_topic_dedup.py
"""Tests for topic_dedup.py."""
from __future__ import annotations
import pytest
from topic_dedup import _fuzzy_similar, _keyword_similar


def test_fuzzy_similar_identical_titles():
    assert _fuzzy_similar("GitHub breach exposes 1M repos", "GitHub breach exposes 1M repos", threshold=0.75) is True


def test_fuzzy_similar_slight_variation():
    assert _fuzzy_similar(
        "GitHub traces mass repository breach to stolen credentials",
        "GitHub repository breach traced to stolen credentials report",
        threshold=0.75,
    ) is True


def test_fuzzy_similar_unrelated_titles():
    assert _fuzzy_similar(
        "Linux 6.9 kernel released with new scheduler",
        "Apple announces M4 chip for MacBook Pro",
        threshold=0.75,
    ) is False


def test_fuzzy_similar_at_threshold_boundary():
    # Exact same string → ratio 1.0 → always True regardless of threshold
    assert _fuzzy_similar("same title", "same title", threshold=0.99) is True
```

- [ ] **Step 1.2: Run tests to confirm they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_topic_dedup.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'topic_dedup'`

- [ ] **Step 1.3: Create `topic_dedup.py` with `DedupeResult` and `_fuzzy_similar`**

```python
# topic_dedup.py
"""
topic_dedup.py — RSS topic deduplication for rss_watcher.py.

Compares incoming RSS entries against recent open GitHub issues and decides:
  CREATE_NEW    — no match; proceed to create a new issue
  ADD_SOURCE    — match found; post source URL as comment on existing issue
  CREATE_FOLLOWUP — follow-up story; create new issue with follow-up label
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

import requests

_log = logging.getLogger(__name__)


@dataclass
class DedupeResult:
    action: Literal["CREATE_NEW", "ADD_SOURCE", "CREATE_FOLLOWUP"]
    matched_issue: dict | None = None   # existing issue dict if action != CREATE_NEW
    matched_number: int | None = None


def _fuzzy_similar(title_a: str, title_b: str, threshold: float = 0.75) -> bool:
    """Token-set ratio comparison using SequenceMatcher on sorted word sets."""
    def _token_set(s: str) -> str:
        return " ".join(sorted(s.lower().split()))

    ratio = SequenceMatcher(None, _token_set(title_a), _token_set(title_b)).ratio()
    return ratio >= threshold
```

- [ ] **Step 1.4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_topic_dedup.py -v 2>&1 | head -30
```

Expected: 4 tests PASS (keyword tests will be collected but skip — add them next task).

- [ ] **Step 1.5: Commit**

```bash
git add topic_dedup.py tests/test_topic_dedup.py
GIT_EDITOR=true git commit -m "feat: add DedupeResult dataclass and fuzzy similarity" & sleep 8
```

---

## Task 2: Keyword similarity

**Files:**
- Modify: `topic_dedup.py`
- Modify: `tests/test_topic_dedup.py`

- [ ] **Step 2.1: Add keyword tests**

Add to `tests/test_topic_dedup.py`:

```python
def test_keyword_similar_cve_overlap():
    assert _keyword_similar(
        "CVE-2024-12345 exploited in the wild",
        "Researchers detail CVE-2024-12345 remote code execution",
        min_overlap=1,
    ) is True


def test_keyword_similar_no_overlap():
    assert _keyword_similar(
        "Linux kernel 6.9 released",
        "Apple M4 chip announced for MacBook",
        min_overlap=2,
    ) is False


def test_keyword_similar_company_and_product_overlap():
    assert _keyword_similar(
        "Microsoft Azure outage affects millions of users globally",
        "Azure cloud services disrupted in Microsoft global outage",
        min_overlap=2,
    ) is True


def test_keyword_similar_min_overlap_too_high():
    # Only one keyword in common — below min_overlap of 3
    assert _keyword_similar(
        "GitHub security incident exposes data",
        "GitHub breach confirmed by security team",
        min_overlap=3,
    ) is False
```

- [ ] **Step 2.2: Run to confirm they fail**

```bash
python -m pytest tests/test_topic_dedup.py::test_keyword_similar_cve_overlap -v
```

Expected: `ImportError` — `_keyword_similar` not yet defined.

- [ ] **Step 2.3: Implement `_keyword_similar` in `topic_dedup.py`**

Add after `_fuzzy_similar`:

```python
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
    """Extract CVEs, version strings, and capitalised noun-like tokens."""
    keywords: set[str] = set()
    # CVE IDs (case-normalised)
    keywords.update(m.upper() for m in _CVE_RE.findall(text))
    # Version strings
    keywords.update(_VERSION_RE.findall(text))
    # Capitalised words (likely proper nouns / product names) that aren't stopwords
    for word in text.split():
        clean = re.sub(r"[^A-Za-z0-9]", "", word)
        if clean and clean[0].isupper() and clean.lower() not in _STOPWORDS and len(clean) > 2:
            keywords.add(clean.lower())
    return keywords


def _keyword_similar(title_a: str, title_b: str, min_overlap: int = 2) -> bool:
    """Match if the two titles share at least min_overlap extracted keywords."""
    kw_a = _extract_keywords(title_a)
    kw_b = _extract_keywords(title_b)
    overlap = kw_a & kw_b
    return len(overlap) >= min_overlap
```

- [ ] **Step 2.4: Run all keyword tests**

```bash
python -m pytest tests/test_topic_dedup.py -v -k "keyword"
```

Expected: 4 PASS

- [ ] **Step 2.5: Run full suite**

```bash
python -m pytest tests/test_topic_dedup.py -v
```

Expected: All 8 PASS

- [ ] **Step 2.6: Commit**

```bash
git add topic_dedup.py tests/test_topic_dedup.py
GIT_EDITOR=true git commit -m "feat: add keyword similarity (CVE, version, proper nouns)" & sleep 8
```

---

## Task 3: LLM similarity + `TopicDeduplicator.check()` (no-dedup path)

**Files:**
- Modify: `topic_dedup.py`
- Modify: `tests/test_topic_dedup.py`

- [ ] **Step 3.1: Add tests for LLM similarity and `check()` CREATE_NEW path**

Add to `tests/test_topic_dedup.py`:

```python
from unittest.mock import MagicMock, patch
from topic_dedup import TopicDeduplicator, DedupeResult


def _make_issue(number: int, title: str, body: str = "", created_at: str = "2026-05-23T10:00:00Z") -> dict:
    return {
        "number": number,
        "title": title,
        "body": body,
        "created_at": created_at,
        "html_url": f"https://github.com/owner/repo/issues/{number}",
    }


def test_llm_similar_yes_response():
    from topic_dedup import _llm_similar
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": "YES, same story."}}]}
    mock_resp.raise_for_status = MagicMock()
    with patch("topic_dedup.requests.post", return_value=mock_resp):
        result = _llm_similar(
            "title A", "summary A", "title B", "summary B",
            model="dashscope/qwen3-plus", token="tok",
        )
    assert result is True


def test_llm_similar_no_response():
    from topic_dedup import _llm_similar
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": "NO, different topics."}}]}
    mock_resp.raise_for_status = MagicMock()
    with patch("topic_dedup.requests.post", return_value=mock_resp):
        result = _llm_similar(
            "title A", "summary A", "title B", "summary B",
            model="dashscope/qwen3-plus", token="tok",
        )
    assert result is False


def test_check_creates_new_when_no_issues():
    cfg = {"enabled": True, "dedup_window_hours": 168, "similarity": {"method": "fuzzy"}}
    dedup = TopicDeduplicator(cfg, token="tok")
    entry = {"title": "Article: Linux 6.9 released", "summary": "New kernel."}
    result = dedup.check(entry, open_issues=[])
    assert result.action == "CREATE_NEW"
    assert result.matched_issue is None


def test_check_creates_new_when_no_match():
    cfg = {"enabled": True, "dedup_window_hours": 168, "similarity": {"method": "fuzzy", "fuzzy_threshold": 0.75}}
    dedup = TopicDeduplicator(cfg, token="tok")
    entry = {"title": "Article: Apple M4 chip revealed", "summary": "New chip."}
    issues = [_make_issue(1, "Article: Linux kernel 6.9 released")]
    result = dedup.check(entry, open_issues=issues)
    assert result.action == "CREATE_NEW"
```

- [ ] **Step 3.2: Run to confirm failures**

```bash
python -m pytest tests/test_topic_dedup.py -v -k "llm or check"
```

Expected: `ImportError` — `_llm_similar`, `TopicDeduplicator` not yet defined.

- [ ] **Step 3.3: Implement `_llm_similar` and `TopicDeduplicator` skeleton in `topic_dedup.py`**

Add after `_keyword_similar`:

```python
def _llm_similar(
    title_a: str,
    summary_a: str,
    title_b: str,
    summary_b: str,
    model: str,
    token: str,
) -> bool:
    """Ask an LLM whether two news items cover the same event."""
    prompt = (
        f"Story A title: {title_a}\nStory A summary: {summary_a}\n\n"
        f"Story B title: {title_b}\nStory B summary: {summary_b}\n\n"
        "Are these two news stories about the same event? "
        "Answer YES or NO with one sentence of reasoning."
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip().upper()
        return content.startswith("YES")
    except Exception as exc:  # noqa: BLE001
        _log.warning("LLM similarity check failed (%s); defaulting to no match", exc)
        return False


class TopicDeduplicator:
    """Check incoming RSS entries against recent open issues for topic overlap."""

    def __init__(self, cfg: dict, token: str) -> None:
        self._cfg = cfg
        self._token = token
        self._sim_cfg = cfg.get("similarity", {})
        self._method = self._sim_cfg.get("method", "fuzzy")
        self._fuzzy_threshold = float(self._sim_cfg.get("fuzzy_threshold", 0.75))
        self._keyword_min_overlap = int(self._sim_cfg.get("keyword_min_overlap", 2))
        self._llm_model = self._sim_cfg.get("llm_model", "dashscope/qwen3-plus")
        self._followup_cfg = cfg.get("follow_up", {})
        self._followup_mode = self._followup_cfg.get("mode", "both")
        self._min_age_hours = int(self._followup_cfg.get("min_age_hours", 72))
        self._followup_llm_model = self._followup_cfg.get("llm_model", "dashscope/qwen3-plus")

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
            if m == "llm" and _llm_similar(
                entry_title, entry_summary, issue_title, issue_body,
                model=self._llm_model, token=self._token,
            ):
                return True
        return False

    def check(self, entry: dict, open_issues: list[dict]) -> DedupeResult:
        """Compare entry against open_issues and return the appropriate action."""
        for issue in open_issues:
            if self._is_similar(entry, issue):
                if self._is_followup(entry, issue):
                    return DedupeResult(
                        action="CREATE_FOLLOWUP",
                        matched_issue=issue,
                        matched_number=issue["number"],
                    )
                return DedupeResult(
                    action="ADD_SOURCE",
                    matched_issue=issue,
                    matched_number=issue["number"],
                )
        return DedupeResult(action="CREATE_NEW")

    def _is_followup(self, entry: dict, issue: dict) -> bool:
        """Decide if the matched entry is a follow-up rather than a duplicate."""
        from datetime import datetime, timezone

        if self._followup_mode == "time":
            return self._age_check(issue)
        if self._followup_mode == "content":
            return self._content_check(entry, issue)
        # both
        return self._age_check(issue) and self._content_check(entry, issue)

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
        prompt = (
            f"Original story title: {issue.get('title', '')}\n"
            f"Original story body: {issue.get('body', '')[:400]}\n\n"
            f"New story title: {entry.get('title', '')}\n"
            f"New story summary: {entry.get('summary', '')}\n\n"
            "Does the new story contain significant new facts not present in the original? "
            "Answer YES or NO with one sentence of reasoning."
        )
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._followup_llm_model,
            "messages": [{"role": "user", "content": prompt}],
        }
        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip().upper()
            return content.startswith("YES")
        except Exception as exc:  # noqa: BLE001
            _log.warning("Follow-up content check failed (%s); defaulting to not follow-up", exc)
            return False
```

- [ ] **Step 3.4: Run new tests**

```bash
python -m pytest tests/test_topic_dedup.py -v
```

Expected: All 12 tests PASS.

- [ ] **Step 3.5: Commit**

```bash
git add topic_dedup.py tests/test_topic_dedup.py
GIT_EDITOR=true git commit -m "feat: add LLM similarity and TopicDeduplicator.check()" & sleep 8
```

---

## Task 4: ADD_SOURCE and CREATE_FOLLOWUP paths in `TopicDeduplicator.check()`

**Files:**
- Modify: `tests/test_topic_dedup.py`

(The implementation is already in place from Task 3 — these tests verify the two non-CREATE_NEW branches.)

- [ ] **Step 4.1: Add tests for ADD_SOURCE and CREATE_FOLLOWUP**

Add to `tests/test_topic_dedup.py`:

```python
from datetime import datetime, timezone, timedelta


def test_check_add_source_same_day_match():
    """Recent matching issue → ADD_SOURCE (not a follow-up)."""
    cfg = {
        "enabled": True,
        "dedup_window_hours": 168,
        "similarity": {"method": "fuzzy", "fuzzy_threshold": 0.75},
        "follow_up": {"mode": "time", "min_age_hours": 72},
    }
    dedup = TopicDeduplicator(cfg, token="tok")
    entry = {
        "title": "Article: GitHub breach exposes repository data",
        "summary": "GitHub confirms breach.",
    }
    # Issue created just 1 hour ago — well below min_age_hours=72
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    issues = [_make_issue(10, "Article: GitHub breach exposes repository data", created_at=recent)]
    result = dedup.check(entry, open_issues=issues)
    assert result.action == "ADD_SOURCE"
    assert result.matched_number == 10


def test_check_create_followup_old_matching_issue():
    """Old matching issue (>72 h) and time mode → CREATE_FOLLOWUP."""
    cfg = {
        "enabled": True,
        "dedup_window_hours": 168,
        "similarity": {"method": "fuzzy", "fuzzy_threshold": 0.75},
        "follow_up": {"mode": "time", "min_age_hours": 72},
    }
    dedup = TopicDeduplicator(cfg, token="tok")
    entry = {
        "title": "Article: GitHub breach exposes repository data",
        "summary": "Further details emerge.",
    }
    old = (datetime.now(timezone.utc) - timedelta(hours=96)).strftime("%Y-%m-%dT%H:%M:%SZ")
    issues = [_make_issue(10, "Article: GitHub breach exposes repository data", created_at=old)]
    result = dedup.check(entry, open_issues=issues)
    assert result.action == "CREATE_FOLLOWUP"
    assert result.matched_number == 10


def test_check_content_followup_mocked_llm():
    """Content mode: LLM says YES → CREATE_FOLLOWUP."""
    cfg = {
        "enabled": True,
        "dedup_window_hours": 168,
        "similarity": {"method": "fuzzy", "fuzzy_threshold": 0.75},
        "follow_up": {"mode": "content", "llm_model": "dashscope/qwen3-plus"},
    }
    dedup = TopicDeduplicator(cfg, token="tok")
    entry = {
        "title": "Article: GitHub breach exposes repository data",
        "summary": "GitHub confirms 1.2M repos affected.",
    }
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    issues = [_make_issue(10, "Article: GitHub breach exposes repository data", created_at=recent)]

    yes_resp = MagicMock()
    yes_resp.json.return_value = {"choices": [{"message": {"content": "YES, new facts."}}]}
    yes_resp.raise_for_status = MagicMock()

    with patch("topic_dedup.requests.post", return_value=yes_resp):
        result = dedup.check(entry, open_issues=issues)

    assert result.action == "CREATE_FOLLOWUP"
```

- [ ] **Step 4.2: Run new tests**

```bash
python -m pytest tests/test_topic_dedup.py -v
```

Expected: All 15 tests PASS.

- [ ] **Step 4.3: Commit**

```bash
git add tests/test_topic_dedup.py
GIT_EDITOR=true git commit -m "test: ADD_SOURCE and CREATE_FOLLOWUP path coverage" & sleep 8
```

---

## Task 5: `_fetch_open_issues` and `_post_source_comment` in `rss_watcher.py`

**Files:**
- Modify: `rss_watcher.py`
- Modify: `tests/test_rss_watcher.py`

- [ ] **Step 5.1: Write failing tests**

Add to `tests/test_rss_watcher.py`:

```python
def test_fetch_open_issues_returns_list():
    import rss_watcher
    issues_payload = [
        {"number": 1, "title": "Article: Linux 6.9", "body": "body", "created_at": "2026-05-20T10:00:00Z", "html_url": "https://github.com/r/1"}
    ]
    mock_resp = MagicMock()
    mock_resp.json.return_value = issues_payload
    mock_resp.raise_for_status = MagicMock()
    with patch("rss_watcher.requests.get", return_value=mock_resp):
        result = rss_watcher._fetch_open_issues(
            repo="owner/repo", label="news-article", token="tok", since_hours=168
        )
    assert len(result) == 1
    assert result[0]["number"] == 1


def test_post_source_comment_posts_correct_body():
    import rss_watcher
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    entry = {
        "source_name": "Ars Technica",
        "url": "https://arstechnica.com/story",
        "summary": "Additional details here.",
    }
    with patch("rss_watcher.requests.post", return_value=mock_resp) as mock_post:
        rss_watcher._post_source_comment(
            repo="owner/repo", issue_number=42, entry=entry, token="tok"
        )
    call_args = mock_post.call_args
    body = call_args[1]["json"]["body"]
    assert "🔗 Additional source: Ars Technica" in body
    assert "https://arstechnica.com/story" in body
    assert "Additional details here." in body
```

- [ ] **Step 5.2: Run to confirm failures**

```bash
python -m pytest tests/test_rss_watcher.py::test_fetch_open_issues_returns_list tests/test_rss_watcher.py::test_post_source_comment_posts_correct_body -v
```

Expected: `AttributeError: module 'rss_watcher' has no attribute '_fetch_open_issues'`

- [ ] **Step 5.3: Add `_fetch_open_issues` and `_post_source_comment` to `rss_watcher.py`**

Add after `_create_github_issue` (before `process_feeds`):

```python
def _fetch_open_issues(
    repo: str,
    label: str,
    token: str,
    since_hours: int = 168,
) -> list[dict]:
    """Fetch recent open issues from the press repo for dedup comparison.

    Returns a list of dicts: {number, title, body, created_at, html_url}.
    """
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
    tok = token or os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    params = {
        "state": "open",
        "labels": label,
        "since": cutoff,
        "per_page": 100,
    }
    url = f"https://api.github.com/repos/{repo}/issues"
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
        return [
            {
                "number": i["number"],
                "title": i["title"],
                "body": i.get("body", ""),
                "created_at": i["created_at"],
                "html_url": i["html_url"],
            }
            for i in raw
        ]
    except Exception as exc:  # noqa: BLE001
        _log.warning("Failed to fetch open issues for dedup: %s", exc)
        return []


def _post_source_comment(
    repo: str,
    issue_number: int,
    entry: dict,
    token: str,
) -> None:
    """Post an additional-source comment on an existing issue."""
    tok = token or os.environ.get("GITHUB_TOKEN", "")
    body = (
        f"🔗 Additional source: {entry.get('source_name', 'Unknown')}\n"
        f"**URL:** {entry.get('url', '')}\n"
        f"**Summary:** {entry.get('summary', '')}\n"
    )
    headers = {
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
    resp = requests.post(url, headers=headers, json={"body": body}, timeout=15)
    resp.raise_for_status()
    _log.info("Posted additional source comment on issue #%d", issue_number)
```

- [ ] **Step 5.4: Run new tests**

```bash
python -m pytest tests/test_rss_watcher.py -v
```

Expected: All existing + 2 new tests PASS.

- [ ] **Step 5.5: Commit**

```bash
git add rss_watcher.py tests/test_rss_watcher.py
GIT_EDITOR=true git commit -m "feat: add _fetch_open_issues and _post_source_comment" & sleep 8
```

---

## Task 6: Wire `TopicDeduplicator` into `process_feeds()`

**Files:**
- Modify: `rss_watcher.py`
- Modify: `tests/test_rss_watcher.py`

- [ ] **Step 6.1: Write integration tests for dedup paths**

Add to `tests/test_rss_watcher.py`:

```python
from unittest.mock import call as mock_call
from datetime import datetime, timezone, timedelta


def _recent_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_dedup_add_source_when_match_found():
    """Matching open issue → _post_source_comment called, no new issue created."""
    import rss_watcher
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "rss_seen.db"
        cfg = {
            "press_repo": "owner/repo",
            "label": "news-article",
            "max_age_hours": 48,
            "feeds": [{"url": "https://example.com/feed.rss", "source": "Example"}],
            "topic_dedup": {
                "enabled": True,
                "dedup_window_hours": 168,
                "similarity": {"method": "fuzzy", "fuzzy_threshold": 0.75},
                "follow_up": {"mode": "time", "min_age_hours": 72},
            },
        }
        matching_issue = {
            "number": 5,
            "title": "Article: GitHub breach exposes repository data",
            "body": "body text",
            "created_at": _recent_iso(),
            "html_url": "https://github.com/owner/repo/issues/5",
        }
        with patch("rss_watcher.requests.get", return_value=_mock_feed_response()), \
             patch("rss_watcher.feedparser") as mock_fp, \
             patch("rss_watcher._create_github_issue") as mock_create, \
             patch("rss_watcher._fetch_open_issues", return_value=[matching_issue]), \
             patch("rss_watcher._post_source_comment") as mock_comment:
            mock_fp.parse.return_value = MagicMock(
                entries=[_make_entry(
                    "https://arstechnica.com/story",
                    title="Article: GitHub breach exposes repository data",
                )]
            )
            rss_watcher.process_feeds(cfg, db_path=db_path)
        mock_create.assert_not_called()
        mock_comment.assert_called_once()
        call_kwargs = mock_comment.call_args[1]
        assert call_kwargs["issue_number"] == 5


def test_dedup_disabled_creates_issue_normally():
    """topic_dedup.enabled: false → normal behaviour, issue created."""
    import rss_watcher
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "rss_seen.db"
        cfg = {
            "press_repo": "owner/repo",
            "label": "news-article",
            "max_age_hours": 48,
            "feeds": [{"url": "https://example.com/feed.rss", "source": "Example"}],
            "topic_dedup": {"enabled": False},
        }
        with patch("rss_watcher.requests.get", return_value=_mock_feed_response()), \
             patch("rss_watcher.feedparser") as mock_fp, \
             patch("rss_watcher._create_github_issue") as mock_create:
            mock_fp.parse.return_value = MagicMock(
                entries=[_make_entry("https://example.com/article-99")]
            )
            rss_watcher.process_feeds(cfg, db_path=db_path)
        mock_create.assert_called_once()


def test_dedup_absent_creates_issue_normally():
    """No topic_dedup key in config → no change in behaviour."""
    import rss_watcher
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "rss_seen.db"
        cfg = {
            "press_repo": "owner/repo",
            "label": "news-article",
            "max_age_hours": 48,
            "feeds": [{"url": "https://example.com/feed.rss", "source": "Example"}],
        }
        with patch("rss_watcher.requests.get", return_value=_mock_feed_response()), \
             patch("rss_watcher.feedparser") as mock_fp, \
             patch("rss_watcher._create_github_issue") as mock_create:
            mock_fp.parse.return_value = MagicMock(
                entries=[_make_entry("https://example.com/article-100")]
            )
            rss_watcher.process_feeds(cfg, db_path=db_path)
        mock_create.assert_called_once()


def test_dedup_followup_creates_new_issue_with_label():
    """Old matching issue + time mode → CREATE_FOLLOWUP → new issue with follow-up label."""
    import rss_watcher
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "rss_seen.db"
        cfg = {
            "press_repo": "owner/repo",
            "label": "news-article",
            "max_age_hours": 48,
            "feeds": [{"url": "https://example.com/feed.rss", "source": "Example"}],
            "topic_dedup": {
                "enabled": True,
                "dedup_window_hours": 168,
                "similarity": {"method": "fuzzy", "fuzzy_threshold": 0.75},
                "follow_up": {"mode": "time", "min_age_hours": 72},
            },
        }
        old = (datetime.now(timezone.utc) - timedelta(hours=96)).strftime("%Y-%m-%dT%H:%M:%SZ")
        old_issue = {
            "number": 3,
            "title": "Article: GitHub breach exposes repository data",
            "body": "body",
            "created_at": old,
            "html_url": "https://github.com/owner/repo/issues/3",
        }
        with patch("rss_watcher.requests.get", return_value=_mock_feed_response()), \
             patch("rss_watcher.feedparser") as mock_fp, \
             patch("rss_watcher._create_github_issue") as mock_create, \
             patch("rss_watcher._fetch_open_issues", return_value=[old_issue]), \
             patch("rss_watcher._post_source_comment") as mock_comment:
            mock_fp.parse.return_value = MagicMock(
                entries=[_make_entry(
                    "https://securityweek.com/story",
                    title="Article: GitHub breach exposes repository data",
                )]
            )
            rss_watcher.process_feeds(cfg, db_path=db_path)
        mock_comment.assert_not_called()
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args[1]
        assert "follow-up" in call_kwargs["body"].lower() or "follow-up" in str(call_kwargs.get("labels", []))
```

- [ ] **Step 6.2: Run to confirm failures**

```bash
python -m pytest tests/test_rss_watcher.py -v -k "dedup"
```

Expected: 4 tests FAIL (dedup logic not yet in `process_feeds`).

- [ ] **Step 6.3: Add `_enrich_as_followup` and wire dedup into `process_feeds()`**

Add `_enrich_as_followup` after `_post_source_comment` in `rss_watcher.py`:

```python
def _enrich_as_followup(entry: dict, matched_issue: dict) -> dict:
    """Return a copy of entry enriched with follow-up prefix and label."""
    enriched = dict(entry)
    enriched["followup_prefix"] = (
        f"⚡ Follow-up to #{matched_issue['number']} "
        f"(original: \"{matched_issue['title']}\")\n\n"
    )
    enriched["extra_labels"] = ["follow-up"]
    return enriched
```

Replace the `process_feeds` function in `rss_watcher.py` (lines 104–193) with:

```python
def process_feeds(
    cfg: dict,
    db_path: Path = _DEFAULT_DB,
    token: str | None = None,
) -> int:
    """Process all RSS feeds and create GitHub issues for new entries.

    Returns the number of issues created.
    """
    from topic_dedup import TopicDeduplicator

    press_repo = cfg.get("press_repo", "")
    label = cfg.get("label", "news-article")
    max_age_hours = int(cfg.get("max_age_hours", 48))
    feeds = cfg.get("feeds", [])

    if not press_repo:
        _log.warning("rss_watcher: press_repo not configured — skipping")
        return 0

    tok = token or os.environ.get("GITHUB_TOKEN", "")

    # Dedup setup (optional)
    dedup_cfg = cfg.get("dedup", {})
    dedup_enabled = dedup_cfg.get("enabled", False)
    deduplicator: TopicDeduplicator | None = None
    open_issues: list[dict] = []

    if dedup_enabled:
        deduplicator = TopicDeduplicator(
            method=dedup_cfg.get("method", "all"),
            fuzzy_threshold=float(dedup_cfg.get("fuzzy_threshold", 0.85)),
            keyword_min_overlap=int(dedup_cfg.get("keyword_min_overlap", 2)),
            add_source_max_age_hours=int(dedup_cfg.get("add_source_max_age_hours", 48)),
            followup_mode=dedup_cfg.get("followup_mode", "time"),
            min_age_hours=int(dedup_cfg.get("min_age_hours", 168)),
            followup_llm_model=dedup_cfg.get("followup_llm_model", ""),
            token=token,
        )
        open_issues = _fetch_open_issues(
            repo=press_repo,
            label=label,
            token=tok,
        )

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=max_age_hours)
    created = 0

    _ensure_db(db_path)
    with sqlite3.connect(db_path) as conn:
        for feed_cfg in feeds:
            feed_url = feed_cfg.get("url", "")
            source_name = feed_cfg.get("source", feed_url)
            if not feed_url:
                continue

            _log.info("Fetching feed: %s", feed_url)
            try:
                resp = requests.get(
                    feed_url,
                    timeout=30,
                    headers={"User-Agent": "ai-software-house-rss/1.0"},
                )
                resp.raise_for_status()
                parsed = feedparser.parse(resp.content)
            except requests.RequestException as exc:
                _log.error("Failed to fetch feed %s: %s", feed_url, exc)
                continue
            except Exception as exc:  # noqa: BLE001
                _log.error("Failed to parse feed %s: %s", feed_url, exc)
                continue

            for entry in parsed.entries:
                url = getattr(entry, "link", "")
                if not url:
                    continue
                if conn.execute("SELECT 1 FROM seen_urls WHERE url = ?", (url,)).fetchone():
                    continue

                published = getattr(entry, "published_parsed", None)
                if published:
                    pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue

                title = getattr(entry, "title", "No title")
                summary = getattr(entry, "summary", "")[:500]

                entry_data = {
                    "title": f"Article: {title}",
                    "summary": summary,
                    "url": url,
                    "source_name": source_name,
                    "followup_prefix": "",
                    "extra_labels": [],
                }

                # ── Deduplication check ──────────────────────────────────────
                if deduplicator is not None:
                    result = deduplicator.check(entry_data, open_issues)
                    if result.action == "ADD_SOURCE":
                        _log.info(
                            "topic_dedup: merging %s into issue #%d",
                            url, result.matched_number,
                        )
                        try:
                            _post_source_comment(
                                repo=press_repo,
                                issue_number=result.matched_number,
                                entry=entry_data,
                                token=tok,
                            )
                            conn.execute(
                                "INSERT OR IGNORE INTO seen_urls (url, seen_at) VALUES (?, ?)",
                                (url, datetime.now(timezone.utc).isoformat()),
                            )
                            conn.commit()
                        except Exception as exc:  # noqa: BLE001
                            _log.error("Failed to post source comment for %s: %s", url, exc)
                        continue  # skip issue creation

                    if result.action == "CREATE_FOLLOWUP":
                        entry_data = _enrich_as_followup(entry_data, result.matched_issue)

                issue_title = entry_data["title"]
                issue_body = (
                    entry_data.get("followup_prefix", "")
                    + f"**Source:** {source_name}\n"
                    + f"**URL:** {url}\n"
                    + f"**Title:** {title}\n\n"
                    + f"**Summary:**\n{summary}\n"
                )
                issue_labels = [label] + entry_data.get("extra_labels", [])

                try:
                    _create_github_issue(
                        repo=press_repo,
                        title=issue_title,
                        body=issue_body,
                        label=label,
                        extra_labels=entry_data.get("extra_labels", []),
                        token=tok,
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO seen_urls (url, seen_at) VALUES (?, ?)",
                        (url, datetime.now(timezone.utc).isoformat()),
                    )
                    conn.commit()
                    created += 1
                except Exception as exc:  # noqa: BLE001
                    _log.error("Failed to create issue for %s: %s", url, exc)

    return created
```

Also update `_create_github_issue` to accept `extra_labels`:

```python
def _create_github_issue(
    repo: str,
    title: str,
    body: str,
    label: str,
    token: str | None = None,
    extra_labels: list[str] | None = None,
) -> None:
    """Create a GitHub issue via REST API."""
    tok = token or os.environ.get("GITHUB_TOKEN", "")
    if not tok:
        raise ValueError("GITHUB_TOKEN not set and no token parameter provided")
    headers = {
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    all_labels = [label] + (extra_labels or [])
    url = f"https://api.github.com/repos/{repo}/issues"
    resp = requests.post(
        url,
        headers=headers,
        json={"title": title, "body": body, "labels": all_labels},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    _log.info("Created issue #%d: %s", data["number"], title)
```

- [ ] **Step 6.4: Run all tests**

```bash
python -m pytest tests/test_rss_watcher.py tests/test_topic_dedup.py -v
```

Expected: All tests PASS.

- [ ] **Step 6.5: Run broader test suite to check for regressions**

```bash
python -m pytest tests/ -v --tb=short -q 2>&1 | tail -20
```

Expected: No regressions introduced.

- [ ] **Step 6.6: Commit**

```bash
git add rss_watcher.py tests/test_rss_watcher.py
GIT_EDITOR=true git commit -m "feat: wire TopicDeduplicator into process_feeds()" & sleep 8
```

---

## Task 7: Push and open PR

- [ ] **Step 7.1: Push branch**

```bash
git push origin feature/rss-topic-dedup
```

- [ ] **Step 7.2: Open PR**

```bash
gh pr create \
  --title "feat: RSS topic deduplication" \
  --body "## Summary

Prevents duplicate GitHub issues when multiple RSS feeds cover the same news story.

### Changes
- **New:** \`topic_dedup.py\` — \`TopicDeduplicator\` with fuzzy / keyword / LLM / all similarity methods and configurable follow-up detection
- **Modified:** \`rss_watcher.py\` — \`_fetch_open_issues\`, \`_post_source_comment\`, \`_enrich_as_followup\`; dedup logic wired into \`process_feeds()\`
- **Tests:** \`tests/test_topic_dedup.py\` (new), \`tests/test_rss_watcher.py\` (extended)

### Behaviour
- If \`topic_dedup\` absent or \`enabled: false\` → zero behaviour change
- Matching same-day source → comment added to existing issue, no new issue
- Matching old story (configurable threshold) → new issue with \`follow-up\` label

Closes #(spec: docs/superpowers/specs/2026-05-23-rss-topic-dedup-design.md)" \
  --base master \
  --head feature/rss-topic-dedup
```

---

## Config Example

Add to `config.local.yaml` under `rss_watcher:` to enable:

```yaml
rss_watcher:
  dedup:
    enabled: true
    method: all                    # fuzzy | keyword | llm | all
    fuzzy_threshold: 0.85
    keyword_min_overlap: 2
    followup_llm_model: "dashscope/qwen3-plus"
    add_source_max_age_hours: 48
    followup_mode: time            # time | content | both
    min_age_hours: 168
```
