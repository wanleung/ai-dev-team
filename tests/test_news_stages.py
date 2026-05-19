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
    mock_agent.run.assert_called_once_with("# English Article\n\nContent.", target_language="cantonese")


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
