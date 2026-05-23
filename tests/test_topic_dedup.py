"""Tests for topic_dedup.py."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from topic_dedup import DedupeResult, TopicDeduplicator, _fuzzy_similar, _keyword_similar


def _make_issue(number: int, title: str, body: str = "", created_at: str = "2026-05-23T10:00:00Z") -> dict:
    return {
        "number": number,
        "title": title,
        "body": body,
        "created_at": created_at,
        "html_url": f"https://github.com/owner/repo/issues/{number}",
    }


def _make_llm_agent(response: str) -> MagicMock:
    """Return a mock BaseAgent whose .call() returns the given string."""
    agent = MagicMock()
    agent.call.return_value = response
    return agent


def test_fuzzy_similar_identical_titles():
    assert _fuzzy_similar("GitHub breach exposes 1M repos", "GitHub breach exposes 1M repos", threshold=0.75) is True


def test_fuzzy_similar_slight_variation():
    assert (
        _fuzzy_similar(
            "GitHub traces mass repository breach to stolen credentials",
            "GitHub repository breach traced to stolen credentials report",
            threshold=0.75,
        )
        is True
    )


def test_fuzzy_similar_unrelated_titles():
    assert (
        _fuzzy_similar(
            "Linux 6.9 kernel released with new scheduler",
            "Apple announces M4 chip for MacBook Pro",
            threshold=0.75,
        )
        is False
    )


def test_fuzzy_similar_at_threshold_boundary():
    # Exact same string → ratio 1.0 → always True regardless of threshold
    assert _fuzzy_similar("same title", "same title", threshold=0.99) is True


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


def test_llm_similar_yes_via_agent():
    """LLM method returns True when injected agent replies YES."""
    agent = _make_llm_agent("YES, same story.")
    dedup = TopicDeduplicator(method="llm", llm=agent)
    issue = _make_issue(1, "title B", body="summary B")
    entry = {"title": "title A", "summary": "summary A"}
    result = dedup.check(entry, [issue])
    assert result.action != "CREATE_NEW"  # match found
    agent.call.assert_called_once()


def test_llm_similar_no_via_agent():
    """LLM method returns CREATE_NEW when injected agent replies NO."""
    agent = _make_llm_agent("NO, different topics.")
    dedup = TopicDeduplicator(method="llm", llm=agent)
    issue = _make_issue(1, "title B", body="summary B")
    entry = {"title": "title A", "summary": "summary A"}
    result = dedup.check(entry, [issue])
    assert result.action == "CREATE_NEW"


def test_check_creates_new_when_no_issues():
    dedup = TopicDeduplicator(method="fuzzy")
    entry = {"title": "Article: Linux 6.9 released", "summary": "New kernel."}
    result = dedup.check(entry, open_issues=[])
    assert result.action == "CREATE_NEW"
    assert result.matched_issue is None


def test_check_creates_new_when_no_match():
    dedup = TopicDeduplicator(method="fuzzy", fuzzy_threshold=0.75)
    entry = {"title": "Article: Apple M4 chip revealed", "summary": "New chip."}
    issues = [_make_issue(1, "Article: Linux kernel 6.9 released")]
    result = dedup.check(entry, open_issues=issues)
    assert result.action == "CREATE_NEW"


def test_check_add_source_same_day_match():
    """When a duplicate issue exists that is less than min_age_hours old,
    check() should return ADD_SOURCE with the matched issue."""
    dedup = TopicDeduplicator(
        method="keyword",
        keyword_min_overlap=1,
        followup_mode="time",
        min_age_hours=168,
    )
    recent_issue = _make_issue(
        number=1,
        title="OpenAI launches GPT-5 language model",
        created_at=(datetime.now(timezone.utc) - timedelta(hours=6)).isoformat(),
    )
    entry = {"title": "OpenAI releases GPT-5 AI model", "summary": ""}
    result = dedup.check(entry, open_issues=[recent_issue])
    assert result.action == "ADD_SOURCE"
    assert result.matched_issue == recent_issue


def test_check_create_followup_old_matching_issue():
    """When a duplicate issue is older than min_age_hours, check() should return
    CREATE_FOLLOWUP with the matched issue."""
    dedup = TopicDeduplicator(
        method="keyword",
        keyword_min_overlap=1,
        followup_mode="time",
        min_age_hours=24,
    )
    old_issue = _make_issue(
        number=1,
        title="OpenAI launches GPT-5 language model",
        created_at=(datetime.now(timezone.utc) - timedelta(hours=72)).isoformat(),
    )
    entry = {"title": "OpenAI releases GPT-5 AI model", "summary": ""}
    result = dedup.check(entry, open_issues=[old_issue])
    assert result.action == "CREATE_FOLLOWUP"
    assert result.matched_issue == old_issue


def test_check_content_followup_mocked_llm():
    """When followup_mode='content' and LLM says YES (new facts), check() should return
    CREATE_FOLLOWUP even for a recent matching issue."""
    agent = _make_llm_agent("YES, contains significant new facts.")
    dedup = TopicDeduplicator(
        method="keyword",
        keyword_min_overlap=1,
        followup_mode="content",
        min_age_hours=168,
        llm=agent,
    )
    recent_issue = _make_issue(
        number=1,
        title="OpenAI launches GPT-5 language model",
        body="Initial announcement of GPT-5.",
        created_at=(datetime.now(timezone.utc) - timedelta(hours=12)).isoformat(),
    )
    entry = {
        "title": "OpenAI GPT-5 now available for all users",
        "summary": "Rollout begins.",
    }
    result = dedup.check(entry, open_issues=[recent_issue])
    assert result.action == "CREATE_FOLLOWUP"
    assert result.matched_issue == recent_issue
    agent.call.assert_called_once()
