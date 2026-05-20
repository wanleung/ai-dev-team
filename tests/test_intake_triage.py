"""Tests for intake triage config schema, tracker adapter, verdict parser, and main script."""
from __future__ import annotations
import pytest
from config_schema import AppConfig, IntakeTriageConfig, load_config
import yaml, tempfile, os


# ── Task 1: Config schema ──────────────────────────────────────────────────

def test_intake_triage_config_defaults():
    cfg = IntakeTriageConfig()
    assert cfg.enabled is False
    assert cfg.tracker == "github"
    assert cfg.labels["pending"] == "triage-pending"
    assert cfg.labels["approved"] == "triage-approved"
    assert cfg.labels["skipped"] == "triage-skipped"
    assert cfg.labels["trigger"] == "press"
    assert cfg.trigger.min_count == 5
    assert cfg.trigger.max_age_hours == 6
    assert cfg.trigger.schedule is None
    assert cfg.batch.max_size == 10
    assert cfg.batch.body_preview_chars == 300
    assert cfg.verdict.mode == "binary"
    assert cfg.verdict.score_threshold is None


def test_app_config_accepts_intake_triage():
    raw = {"llm": {"model": "gpt-4.1"}, "intake_triage": {"enabled": True, "trigger": {"min_count": 3}}}
    cfg = AppConfig(**raw)
    assert cfg.intake_triage.enabled is True
    assert cfg.intake_triage.trigger.min_count == 3


def test_app_config_intake_triage_disabled_by_default():
    cfg = AppConfig(**{"llm": {"model": "gpt-4.1"}})
    assert cfg.intake_triage is not None
    assert cfg.intake_triage.enabled is False


def test_intake_triage_config_from_yaml():
    content = """
llm:
  model: gpt-4.1
intake_triage:
  enabled: true
  labels:
    pending: triage-pending
    approved: triage-approved
    skipped: triage-skipped
    trigger: ai-press
  trigger:
    min_count: 3
    max_age_hours: 12
    schedule: "0 8 * * *"
  batch:
    max_size: 5
    body_preview_chars: 200
  verdict:
    mode: binary
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(content)
        f.flush()
        cfg = load_config(f.name)
    os.unlink(f.name)
    assert cfg.intake_triage.enabled is True
    assert cfg.intake_triage.labels["trigger"] == "ai-press"
    assert cfg.intake_triage.trigger.min_count == 3
    assert cfg.intake_triage.batch.max_size == 5


# ── Task 2: TrackerAdapter ─────────────────────────────────────────────────

from tracker_adapter import TriageItem, TrackerAdapter, GitHubTrackerAdapter
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock


def _make_item(n: int = 1) -> TriageItem:
    return TriageItem(
        id=str(n),
        title=f"Story {n}",
        body="Body content here",
        url=f"https://github.com/org/repo/issues/{n}",
        created_at=datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc),
        metadata={"number": n, "labels": ["triage-pending"]},
    )


def test_triage_item_fields():
    item = _make_item(42)
    assert item.id == "42"
    assert item.title == "Story 42"
    assert item.created_at.tzinfo is not None


def test_tracker_adapter_is_abstract():
    """TrackerAdapter cannot be instantiated directly."""
    with pytest.raises(TypeError):
        TrackerAdapter()


def test_github_adapter_list_pending_empty():
    mock_resp = MagicMock()
    mock_resp.json.return_value = []
    mock_resp.raise_for_status = MagicMock()
    with patch("tracker_adapter.requests.get", return_value=mock_resp):
        adapter = GitHubTrackerAdapter(
            repo="org/repo",
            token="test-token",
            pending_label="triage-pending",
            approved_label="triage-approved",
            skipped_label="triage-skipped",
            trigger_label="press",
        )
        result = adapter.list_pending()
    assert result == []


def test_github_adapter_list_pending_returns_items():
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {
            "number": 5,
            "title": "Big story",
            "body": "Some body text",
            "html_url": "https://github.com/org/repo/issues/5",
            "created_at": "2026-05-20T08:00:00Z",
            "labels": [{"name": "triage-pending"}],
        }
    ]
    mock_resp.raise_for_status = MagicMock()
    with patch("tracker_adapter.requests.get", return_value=mock_resp):
        adapter = GitHubTrackerAdapter(
            repo="org/repo", token="t", pending_label="triage-pending",
            approved_label="triage-approved", skipped_label="triage-skipped",
            trigger_label="press",
        )
        items = adapter.list_pending()
    assert len(items) == 1
    assert items[0].id == "5"
    assert items[0].title == "Big story"


def test_github_adapter_is_approved_false_when_label_absent():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"labels": [{"name": "triage-pending"}], "body": "x"}
    mock_resp.raise_for_status = MagicMock()
    with patch("tracker_adapter.requests.get", return_value=mock_resp):
        adapter = GitHubTrackerAdapter(
            repo="org/repo", token="t", pending_label="triage-pending",
            approved_label="triage-approved", skipped_label="triage-skipped",
            trigger_label="press",
        )
        approved, notes = adapter.is_approved("5")
    assert approved is False
    assert notes == ""


def test_github_adapter_is_approved_true_when_label_present():
    issue_resp = MagicMock()
    issue_resp.json.return_value = {"labels": [{"name": "triage-approved"}]}
    issue_resp.raise_for_status = MagicMock()
    comments_resp = MagicMock()
    comments_resp.json.return_value = [
        {"body": "[INTAKE TRIAGE]\nVERDICT: PUBLISH\nNOTES: Focus on HK angle."}
    ]
    comments_resp.raise_for_status = MagicMock()
    with patch("tracker_adapter.requests.get", side_effect=[issue_resp, comments_resp]):
        adapter = GitHubTrackerAdapter(
            repo="org/repo", token="t", pending_label="triage-pending",
            approved_label="triage-approved", skipped_label="triage-skipped",
            trigger_label="press",
        )
        approved, notes = adapter.is_approved("5")
    assert approved is True
    assert "HK angle" in notes


# ── Task 3: Batch verdict parser ───────────────────────────────────────────

from intake_triage import _parse_batch_verdicts


def test_parse_batch_verdicts_all_publish():
    text = (
        "ITEM 1: PUBLISH\nNOTES: Focus on HK angle.\n\n"
        "ITEM 2: PUBLISH\nNOTES: Strong security story.\n"
    )
    results = _parse_batch_verdicts(text, item_count=2)
    assert results == [("PUBLISH", "Focus on HK angle."), ("PUBLISH", "Strong security story.")]


def test_parse_batch_verdicts_mixed():
    text = (
        "ITEM 1: PUBLISH\nNOTES: Lead with Cantonese angle.\n\n"
        "ITEM 2: SKIP\nNOTES: No HK relevance.\n\n"
        "ITEM 3: PUBLISH\nNOTES: Strong enterprise angle.\n"
    )
    results = _parse_batch_verdicts(text, item_count=3)
    assert results[0] == ("PUBLISH", "Lead with Cantonese angle.")
    assert results[1] == ("SKIP", "No HK relevance.")
    assert results[2] == ("PUBLISH", "Strong enterprise angle.")


def test_parse_batch_verdicts_fail_open_on_missing():
    """Missing items default to PUBLISH (fail-open)."""
    text = "ITEM 1: PUBLISH\nNOTES: Good.\n"
    results = _parse_batch_verdicts(text, item_count=3)
    assert results[0] == ("PUBLISH", "Good.")
    assert results[1] == ("PUBLISH", "")   # missing → fail-open
    assert results[2] == ("PUBLISH", "")   # missing → fail-open


def test_parse_batch_verdicts_skip_all():
    text = "ITEM 1: SKIP\nNOTES: Not relevant.\n\nITEM 2: SKIP\nNOTES: Old news.\n"
    results = _parse_batch_verdicts(text, item_count=2)
    assert results == [("SKIP", "Not relevant."), ("SKIP", "Old news.")]


def test_parse_batch_verdicts_case_insensitive_verdict():
    text = "ITEM 1: publish\nNOTES: ok\n"
    results = _parse_batch_verdicts(text, item_count=1)
    assert results[0][0] == "PUBLISH"


def test_parse_batch_verdicts_notes_optional():
    """NOTES line is optional — verdict still parsed."""
    text = "ITEM 1: PUBLISH\n\nITEM 2: SKIP\n"
    results = _parse_batch_verdicts(text, item_count=2)
    assert results[0] == ("PUBLISH", "")
    assert results[1] == ("SKIP", "")


def test_parse_batch_verdicts_empty_text():
    results = _parse_batch_verdicts("", item_count=2)
    assert results == [("PUBLISH", ""), ("PUBLISH", "")]
