# tests/test_news_stages.py
"""Tests for news pipeline stages in the orchestrator."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest

from orchestrator import PipelineResult


def test_pipeline_result_has_article_draft():
    r = PipelineResult(requirement="test")
    assert hasattr(r, "article_draft")
    assert r.article_draft == ""


def test_pipeline_result_has_article():
    r = PipelineResult(requirement="test")
    assert hasattr(r, "article")
    assert r.article == ""


def test_pipeline_result_article_draft_in_to_dict():
    r = PipelineResult(requirement="test")
    r.article_draft = "# Draft"
    r.article = "# Final"
    d = r.to_dict()
    assert d["article_draft"] == "# Draft"
    assert d["article"] == "# Final"


def test_pipeline_result_article_from_dict():
    r = PipelineResult.from_dict({
        "requirement": "test",
        "article_draft": "# Draft",
        "article": "# Final",
    })
    assert r.article_draft == "# Draft"
    assert r.article == "# Final"


def test_news_stages_registered():
    """news_writer, news_editor, news_article_pr must be in the stage registry."""
    from orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.model = "gpt-4.1"
    orch.model_overrides = {}
    orch._stage_timeouts = {}
    orch._discussions_dir = None
    with patch.object(Orchestrator, "_make_backend", return_value=MagicMock()), \
         patch.object(Orchestrator, "_make_backend_from_model", return_value=MagicMock()):
        # Manually set required attributes
        orch.news_writer = MagicMock()
        orch.news_editor = MagicMock()
        from pathlib import Path
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmpdir:
            orch._discussions_dir = Path(tmpdir)
            registry = orch._make_stage_registry()
    assert "news_writer" in registry
    assert "news_editor" in registry
    assert "news_article_pr" in registry


def test_stage_news_writer_sets_article_draft():
    from orchestrator import PipelineResult, Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    mock_agent = MagicMock()
    mock_agent.run.return_value = {"article_draft": "# My Draft\n\nContent."}
    orch.news_writer = mock_agent

    result = PipelineResult(requirement="Test article")
    result.issue_body = "https://example.com"
    result.discussion_synthesis = "Key point: important"
    orch._stage_news_writer(result)
    assert result.article_draft == "# My Draft\n\nContent."


def test_stage_news_editor_sets_article():
    from orchestrator import PipelineResult, Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    mock_agent = MagicMock()
    mock_agent.run.return_value = {"article": "---\ntitle: Final\n---\n\nBody."}
    orch.news_editor = mock_agent

    result = PipelineResult(requirement="Test article")
    result.article_draft = "# Draft"
    result.issue_body = "Brief"
    result.discussion_synthesis = ""
    orch._stage_news_editor(result)
    assert result.article == "---\ntitle: Final\n---\n\nBody."


def test_stage_news_article_pr_sets_all_files():
    from orchestrator import PipelineResult, Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.github = None
    orch.target_github = None

    result = PipelineResult(requirement="Test article")
    result.article = "---\ntitle: Test Article\ndate: 2026-01-15T10:30:00\nauthor: AI Press Team\n---\n\nBody."
    result.issue_number = 42

    orch._stage_news_article_pr(result)
    assert len(result.all_files) == 1
    path = list(result.all_files.keys())[0]
    assert path.startswith("articles/")
    assert path.endswith(".md")
    assert "test-article" in path or "2026" in path


def test_pipeline_result_has_article_zh_hk():
    r = PipelineResult(requirement="test")
    assert hasattr(r, "article_zh_hk")
    assert r.article_zh_hk == ""


def test_pipeline_result_has_article_zh_tw():
    r = PipelineResult(requirement="test")
    assert hasattr(r, "article_zh_tw")
    assert r.article_zh_tw == ""


def test_pipeline_result_zh_fields_in_to_dict():
    r = PipelineResult(requirement="test")
    r.article_zh_hk = "# 粵語文章"
    r.article_zh_tw = "# 繁體文章"
    d = r.to_dict()
    assert d["article_zh_hk"] == "# 粵語文章"
    assert d["article_zh_tw"] == "# 繁體文章"


def test_pipeline_result_zh_fields_from_dict():
    r = PipelineResult.from_dict({
        "requirement": "test",
        "article_zh_hk": "# 粵語",
        "article_zh_tw": "# 繁體",
    })
    assert r.article_zh_hk == "# 粵語"
    assert r.article_zh_tw == "# 繁體"


def test_translate_stages_registered():
    """translate_cantonese and translate_zh_traditional must be in the stage registry."""
    from orchestrator import Orchestrator
    from pathlib import Path
    import tempfile
    orch = Orchestrator.__new__(Orchestrator)
    orch.model = "gpt-4.1"
    orch.model_overrides = {}
    orch._stage_timeouts = {}
    with patch.object(Orchestrator, "_make_backend", return_value=MagicMock()), \
         patch.object(Orchestrator, "_make_backend_from_model", return_value=MagicMock()):
        orch.news_writer = MagicMock()
        orch.news_editor = MagicMock()
        orch.translator = MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            orch._discussions_dir = Path(tmpdir)
            registry = orch._make_stage_registry()
    assert "translate_cantonese" in registry
    assert "translate_zh_traditional" in registry


def test_stage_translate_sets_result_field():
    from orchestrator import PipelineResult, Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    mock_agent = MagicMock()
    mock_agent.run.return_value = {"translated_article": "# 粵語文章\n\n內容。"}
    orch.translator = mock_agent

    result = PipelineResult(requirement="Test")
    result.article = "# English Article\n\nContent."
    orch._stage_translate(result, "cantonese", "article_zh_hk")
    assert result.article_zh_hk == "# 粵語文章\n\n內容。"
    mock_agent.run.assert_called_once_with("# English Article\n\nContent.", target_language="cantonese", reviewer_notes="")


def test_stage_translate_uses_article_draft_when_no_article():
    from orchestrator import PipelineResult, Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    mock_agent = MagicMock()
    mock_agent.run.return_value = {"translated_article": "# 草稿翻譯"}
    orch.translator = mock_agent

    result = PipelineResult(requirement="Test")
    result.article = ""
    result.article_draft = "# Draft Article"
    orch._stage_translate(result, "traditional_chinese", "article_zh_tw")
    assert result.article_zh_tw == "# 草稿翻譯"


def test_stage_translate_raises_when_no_source():
    from orchestrator import PipelineResult, Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.translator = MagicMock()

    result = PipelineResult(requirement="Test")
    result.article = ""
    result.article_draft = ""
    with pytest.raises(RuntimeError, match="no source article"):
        orch._stage_translate(result, "cantonese", "article_zh_hk")


def test_stage_translate_raises_on_empty_output():
    from orchestrator import PipelineResult, Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    mock_agent = MagicMock()
    mock_agent.run.return_value = {"translated_article": "   "}
    orch.translator = mock_agent

    result = PipelineResult(requirement="Test")
    result.article = "# Article"
    with pytest.raises(RuntimeError, match="empty output"):
        orch._stage_translate(result, "cantonese", "article_zh_hk")


def test_news_article_pr_includes_translations_when_present():
    """When article_zh_hk and article_zh_tw are set, all_files contains 3 entries."""
    from orchestrator import PipelineResult, Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.model_overrides = {}
    orch._github_token = None
    orch.ollama_url = "http://localhost:11434"

    result = PipelineResult(requirement="test")
    result.issue_number = 42
    result.article = "---\ntitle: Test Article\ndate: 2026-05-19T10:00:00\nauthor: AI Press Team\nsource_url: https://example.com\ntags: [ai]\n---\n\nEnglish body."
    result.article_zh_hk = "---\ntitle: 測試文章\ndate: 2026-05-19T10:00:00\nauthor: AI Press Team\nsource_url: https://example.com\ntags: [人工智能]\n---\n\n粵語內容。"
    result.article_zh_tw = "---\ntitle: 測試文章\ndate: 2026-05-19T10:00:00\nauthor: AI Press Team\nsource_url: https://example.com\ntags: [人工智慧]\n---\n\n繁體中文內容。"

    with patch.object(orch, "_commit_and_open_pr"):
        orch._stage_news_article_pr(result)

    assert len(result.all_files) == 3
    filenames = list(result.all_files.keys())
    en_file = [f for f in filenames if not f.endswith((".zh-hk.md", ".zh-tw.md"))]
    hk_file = [f for f in filenames if f.endswith(".zh-hk.md")]
    tw_file = [f for f in filenames if f.endswith(".zh-tw.md")]
    assert len(en_file) == 1
    assert len(hk_file) == 1
    assert len(tw_file) == 1
    assert result.all_files[hk_file[0]] == result.article_zh_hk
    assert result.all_files[tw_file[0]] == result.article_zh_tw


def test_news_article_pr_only_english_when_no_translations():
    """When translations are empty, all_files contains only the English article."""
    from orchestrator import PipelineResult, Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.model_overrides = {}
    orch._github_token = None
    orch.ollama_url = "http://localhost:11434"

    result = PipelineResult(requirement="test")
    result.issue_number = 1
    result.article = "---\ntitle: English Only\ndate: 2026-05-19T10:00:00\nauthor: AI Press Team\nsource_url: https://example.com\ntags: [ai]\n---\n\nBody."
    result.article_zh_hk = ""
    result.article_zh_tw = ""

    with patch.object(orch, "_commit_and_open_pr"):
        orch._stage_news_article_pr(result)

    assert len(result.all_files) == 1


def test_pipeline_result_has_reviewer_fields():
    from orchestrator import PipelineResult
    r = PipelineResult()
    assert hasattr(r, "article_reviewer_notes")
    assert r.article_reviewer_notes == ""
    assert hasattr(r, "article_review_retry_count")
    assert r.article_review_retry_count == 0


def test_pipeline_result_reviewer_fields_in_to_dict():
    from orchestrator import PipelineResult
    r = PipelineResult()
    r.article_reviewer_notes = "Some issues"
    r.article_review_retry_count = 1
    d = r.to_dict()
    assert d["article_reviewer_notes"] == "Some issues"
    assert d["article_review_retry_count"] == 1


def test_pipeline_result_reviewer_fields_from_dict():
    from orchestrator import PipelineResult
    r = PipelineResult.from_dict({
        "requirement": "test",
        "article_reviewer_notes": "Issues here",
        "article_review_retry_count": 2,
    })
    assert r.article_reviewer_notes == "Issues here"
    assert r.article_review_retry_count == 2


def _make_minimal_orchestrator():
    """Create a minimal Orchestrator with only press-related agents mocked."""
    from unittest.mock import MagicMock
    import orchestrator as orch_mod

    o = object.__new__(orch_mod.Orchestrator)
    o._reviewer_max_retries = 2
    o.news_editor = MagicMock()
    o.news_reviewer = MagicMock()
    o.translator = MagicMock()
    return o


def test_stage_news_reviewer_pass_does_not_retry():
    """PASS verdict — no retry, stage completes normally."""
    from unittest.mock import MagicMock
    from orchestrator import PipelineResult

    result = PipelineResult()
    result.article = "---\ntitle: Test\ndate: 2026-01-01\nsource_url: https://example.com\n---\n\nBody."
    result.article_zh_hk = "# 文章"
    result.article_zh_tw = "# 文章"

    mock_reviewer = MagicMock()
    mock_reviewer.run.return_value = {"verdict": "PASS", "issues": [], "confidence": "high"}

    orch = _make_minimal_orchestrator()
    orch.news_reviewer = mock_reviewer
    orch._stage_news_reviewer(result)

    assert mock_reviewer.run.call_count == 1
    assert result.article_review_retry_count == 0


def test_stage_news_reviewer_english_issue_retries_editor_and_translations():
    """NEEDS_REVISION with English [FACT] — retries editor + both translations."""
    from unittest.mock import MagicMock, call
    from orchestrator import PipelineResult

    result = PipelineResult()
    result.article = "---\ntitle: Test\ndate: 2026-01-01\nsource_url: https://example.com\n---\n\nBody."
    result.article_zh_hk = "# 文章"
    result.article_zh_tw = "# 文章"

    mock_reviewer = MagicMock()
    mock_reviewer.run.side_effect = [
        {"verdict": "NEEDS_REVISION", "issues": ["[FACT] Wrong version"], "confidence": "high"},
        {"verdict": "PASS", "issues": [], "confidence": "high"},
    ]

    orch = _make_minimal_orchestrator()
    orch.news_reviewer = mock_reviewer

    editor_calls = []
    translate_calls = []

    def fake_editor(r, reviewer_notes=""):
        editor_calls.append(reviewer_notes)

    def fake_translate(r, lang, field, reviewer_notes=""):
        translate_calls.append((lang, field))

    orch._stage_news_editor = fake_editor
    orch._stage_translate = fake_translate
    orch._stage_news_reviewer(result)

    assert mock_reviewer.run.call_count == 2
    assert len(editor_calls) == 1
    assert len(translate_calls) == 2  # both languages retried
    assert result.article_review_retry_count == 1


def test_stage_news_reviewer_zh_hk_only_retries_cantonese():
    """NEEDS_REVISION with only [ZH_HK] — retries translate_cantonese only."""
    from unittest.mock import MagicMock
    from orchestrator import PipelineResult

    result = PipelineResult()
    result.article = "---\ntitle: Test\ndate: 2026-01-01\nsource_url: https://example.com\n---\n\nBody."
    result.article_zh_hk = "# 文章"
    result.article_zh_tw = "# 文章"

    mock_reviewer = MagicMock()
    mock_reviewer.run.side_effect = [
        {"verdict": "NEEDS_REVISION", "issues": ["[ZH_HK] Simplified char"], "confidence": "high"},
        {"verdict": "PASS", "issues": [], "confidence": "high"},
    ]

    orch = _make_minimal_orchestrator()
    orch.news_reviewer = mock_reviewer

    editor_calls = []
    translate_calls = []
    orch._stage_news_editor = lambda r, reviewer_notes="": editor_calls.append(reviewer_notes)
    orch._stage_translate = lambda r, lang, field, reviewer_notes="": translate_calls.append(lang)
    orch._stage_news_reviewer(result)

    assert len(editor_calls) == 0
    assert translate_calls == ["cantonese"]


def test_stage_news_reviewer_stops_after_max_retries():
    """After max retries, accept the article and continue regardless."""
    from unittest.mock import MagicMock
    from orchestrator import PipelineResult

    result = PipelineResult()
    result.article = "---\ntitle: Test\ndate: 2026-01-01\nsource_url: https://example.com\n---\n\nBody."
    result.article_zh_hk = "# 文章"
    result.article_zh_tw = "# 文章"

    mock_reviewer = MagicMock()
    mock_reviewer.run.return_value = {
        "verdict": "NEEDS_REVISION",
        "issues": ["[FACT] Wrong version"],
        "confidence": "high",
    }

    orch = _make_minimal_orchestrator()
    orch.news_reviewer = mock_reviewer
    orch._reviewer_max_retries = 2
    orch._stage_news_editor = lambda r, reviewer_notes="": None
    orch._stage_translate = lambda r, lang, field, reviewer_notes="": None

    orch._stage_news_reviewer(result)

    assert result.article_review_retry_count == 2
    assert mock_reviewer.run.call_count == 3  # initial + 2 retries


def test_stage_news_reviewer_english_cascade_passes_notes_to_translations():
    """English cascade must pass reviewer_notes to translations (mixed FACT+ZH issues)."""
    from unittest.mock import MagicMock
    from orchestrator import PipelineResult

    result = PipelineResult()
    result.article = "---\ntitle: Test\ndate: 2026-01-01\nsource_url: https://example.com\n---\n\nBody."
    result.article_zh_hk = "# 文章"
    result.article_zh_tw = "# 文章"

    mock_reviewer = MagicMock()
    mock_reviewer.run.side_effect = [
        {"verdict": "NEEDS_REVISION", "issues": ["[FACT] Wrong version", "[ZH_HK] Simplified char"], "confidence": "high"},
        {"verdict": "PASS", "issues": [], "confidence": "high"},
    ]

    orch = _make_minimal_orchestrator()
    orch.news_reviewer = mock_reviewer

    translate_calls = []
    orch._stage_news_editor = lambda r, reviewer_notes="": None
    orch._stage_translate = lambda r, lang, field, reviewer_notes="": translate_calls.append((lang, reviewer_notes))
    orch._stage_news_reviewer(result)

    # Both translate calls must receive the reviewer notes
    assert len(translate_calls) == 2
    for lang, notes in translate_calls:
        assert "[ZH_HK] Simplified char" in notes, f"reviewer_notes not passed to {lang} translation"


# ── _stage_news_triage() tests ───────────────────────────────────────────────

def _make_triage_orch():
    """Minimal Orchestrator for _stage_news_triage() tests."""
    from unittest.mock import MagicMock
    from orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.model = "gpt-4.1"
    orch.model_overrides = {}
    orch._stage_timeouts = {}
    orch._discussions_dir = None
    orch._cfg = {}
    orch.github = MagicMock()
    orch.target_github = MagicMock()
    return orch


def test_stage_triage_publish_path():
    """PUBLISH verdict: editorial_notes stored, no abort, issue not closed."""
    from unittest.mock import patch, MagicMock

    result = PipelineResult(requirement="test story brief")
    result.issue_number = 42

    synthesis = (
        "This story is highly relevant to our HK tech audience.\n"
        "VERDICT: PUBLISH\n"
        "EDITORIAL_NOTES: Focus on the open-source tooling implications for local DevOps teams."
    )

    orch = _make_triage_orch()
    orch._cfg = {"press": {"triage": {"scope": "AI, cybersecurity", "min_score": 2}}}

    def fake_discuss(r, config_path):
        r.discussion_synthesis = synthesis

    with patch.object(orch, "_stage_discuss", side_effect=fake_discuss):
        orch._stage_news_triage(result)

    assert result.editorial_verdict == "PUBLISH"
    assert "open-source" in result.editorial_notes
    assert result.triage_scope == "AI, cybersecurity"
    orch.target_github.add_issue_comment.assert_not_called()
    orch.target_github.close_issue.assert_not_called()


def test_stage_triage_skip_path():
    """SKIP verdict: editorial_verdict=SKIP, GitHub issue closed with comment."""
    from unittest.mock import patch, MagicMock

    result = PipelineResult(requirement="test story brief")
    result.issue_number = 99

    synthesis = (
        "This story has no tech angle.\n"
        "VERDICT: SKIP\n"
        "EDITORIAL_NOTES: Off-topic — covers entertainment, not IT."
    )

    orch = _make_triage_orch()
    orch._cfg = {"press": {"triage": {"scope": "AI, cybersecurity", "min_score": 2}}}

    def fake_discuss(r, config_path):
        r.discussion_synthesis = synthesis

    with patch.object(orch, "_stage_discuss", side_effect=fake_discuss):
        orch._stage_news_triage(result)

    assert result.editorial_verdict == "SKIP"
    assert "entertainment" in result.editorial_notes
    orch.target_github.add_issue_comment.assert_called_once()
    comment_body = orch.target_github.add_issue_comment.call_args[0][1]
    assert "SKIP" in comment_body
    orch.target_github.close_issue.assert_called_once_with(99)


def test_stage_triage_fail_open():
    """If _stage_discuss raises, verdict defaults to PUBLISH (never blocks pipeline)."""
    from unittest.mock import patch

    result = PipelineResult(requirement="test")
    result.issue_number = 1
    orch = _make_triage_orch()
    orch._cfg = {"press": {"triage": {"scope": "AI", "min_score": 2}}}

    with patch.object(orch, "_stage_discuss", side_effect=RuntimeError("LLM timeout")):
        orch._stage_news_triage(result)

    assert result.editorial_verdict == "PUBLISH"
    assert result.editorial_notes == ""

def test_stage_news_writer_prepends_editorial_notes():
    """If result.editorial_notes is set, issue_body passed to news_writer includes notes."""
    from unittest.mock import patch, MagicMock

    result = PipelineResult(requirement="brief")
    result.editorial_notes = "Focus on the security angle for HK enterprises."
    result.discussion_synthesis = ""

    orch = _make_triage_orch()
    orch.news_writer = MagicMock()
    orch.news_writer.run.return_value = {"article_draft": "# Draft\n\nBody."}

    orch._stage_news_writer(result)

    assert result.article_draft.strip()
    call_args = orch.news_writer.run.call_args
    issue_body_arg = call_args[0][0]  # first positional arg
    assert "EDITORIAL NOTES" in issue_body_arg
    assert "security angle" in issue_body_arg


# ── intake triage fast-pass tests ─────────────────────────────────────────

def _make_triage_orch_with_intake(approved: bool, notes: str = ""):
    """Orchestrator with intake_triage enabled and mocked adapter."""
    from unittest.mock import MagicMock
    from orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.model = "gpt-4.1"
    orch.model_overrides = {}
    orch._stage_timeouts = {}
    orch._discussions_dir = None
    orch._cfg = {"intake_triage": {"enabled": True}}
    orch.github = MagicMock()
    orch.target_github = MagicMock()

    mock_adapter = MagicMock()
    mock_adapter.is_approved.return_value = (approved, notes)
    orch._cached_tracker_adapter = mock_adapter
    return orch


def test_news_triage_fast_pass_when_batch_approved():
    """If triage-approved label present, news_triage sets PUBLISH and returns early."""
    orch = _make_triage_orch_with_intake(approved=True, notes="Focus on HK angle.")
    result = MagicMock()
    result.issue_number = 42
    result.editorial_verdict = None
    result.editorial_notes = ""

    with patch.object(orch, "_stage_discuss") as mock_discuss:
        orch._stage_news_triage(result)

    mock_discuss.assert_not_called()
    assert result.editorial_verdict == "PUBLISH"
    assert result.editorial_notes == "Focus on HK angle."


def test_news_triage_no_fast_pass_when_not_approved():
    """If triage-approved absent, falls through to per-story triage."""
    orch = _make_triage_orch_with_intake(approved=False)
    result = MagicMock()
    result.issue_number = 43
    result.editorial_verdict = None
    result.editorial_notes = ""
    result.errors = []

    with patch.object(orch, "_stage_discuss") as mock_discuss:
        with patch.object(orch, "_parse_triage_verdict", return_value={"verdict": "PUBLISH", "notes": ""}):
            orch._stage_news_triage(result)

    mock_discuss.assert_called_once()


def test_news_triage_fast_pass_disabled_when_no_adapter():
    """When intake_triage is disabled (no adapter), per-story triage always runs."""
    from orchestrator import Orchestrator
    from unittest.mock import MagicMock, patch
    orch = Orchestrator.__new__(Orchestrator)
    orch.model = "gpt-4.1"
    orch.model_overrides = {}
    orch._stage_timeouts = {}
    orch._discussions_dir = None
    orch._cfg = {}   # no intake_triage key
    orch.github = MagicMock()
    orch.target_github = MagicMock()
    orch._cached_tracker_adapter = None

    result = MagicMock()
    result.issue_number = 44
    result.editorial_verdict = None
    result.editorial_notes = ""
    result.errors = []

    with patch.object(orch, "_stage_discuss") as mock_discuss:
        with patch.object(orch, "_parse_triage_verdict", return_value={"verdict": "PUBLISH", "notes": ""}):
            orch._stage_news_triage(result)

    mock_discuss.assert_called_once()
