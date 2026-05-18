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
