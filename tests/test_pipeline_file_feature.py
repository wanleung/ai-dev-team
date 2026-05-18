# tests/test_pipeline_file_feature.py
"""Tests for pipeline_file: feature — loading pipeline YAML from target repo."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest
import yaml


def _make_orch_mock(stages=None):
    """Return a mock Orchestrator that records _pipeline_yaml_stages."""
    m = MagicMock()
    m._pipeline_yaml_stages = None
    m.load_pipeline_for_label.return_value = stages
    return m


def test_pipeline_file_fetched_and_applied():
    """When pipeline_file: is set, watcher fetches YAML and sets orch._pipeline_yaml_stages."""
    from watcher import _dispatch

    pipeline_yaml = yaml.dump({
        "stages": ["news_writer", "news_editor", "news_article_pr"]
    })

    mock_result = MagicMock()
    mock_result.verdict = "ok"
    mock_result.next_label = None

    with patch("orchestrator.Orchestrator") as mock_cls, \
         patch("github_client.GitHubClient") as mock_gh_cls, \
         patch("watcher._load_pipeline_config", return_value={}), \
         patch("watcher._collect_issue_prior_context", return_value=""):

        mock_gh = MagicMock()
        mock_gh.get_issue.return_value = {"number": 1, "title": "Article: Test", "body": "brief"}
        mock_gh.get_file_content.return_value = pipeline_yaml
        mock_gh_cls.return_value = mock_gh

        mock_orch = _make_orch_mock()
        mock_orch.run.return_value = mock_result
        mock_cls.return_value = mock_orch

        import tempfile, logging
        from pathlib import Path
        log = logging.getLogger("test")
        with tempfile.NamedTemporaryFile(suffix=".log") as f:
            _dispatch(
                label="news-article",
                tracker_repo="wanleung/ai-it-press",
                target_repo="wanleung/ai-it-press",
                issue_number=1,
                model="gpt-4.1",
                num_engineers=1,
                log_file=Path(f.name),
                logger=log,
                pipeline_file="pipelines/news-article.yaml",
            )

    # Verify get_file_content was called with the pipeline file path
    mock_gh.get_file_content.assert_called_with("pipelines/news-article.yaml")
    # Verify _pipeline_yaml_stages was set on the orchestrator
    assert mock_orch._pipeline_yaml_stages == ["news_writer", "news_editor", "news_article_pr"]


def test_pipeline_file_missing_falls_back_gracefully():
    """If pipeline_file cannot be fetched, pipeline falls back to label-based lookup."""
    from watcher import _dispatch

    mock_result = MagicMock()
    mock_result.verdict = "ok"
    mock_result.next_label = None

    with patch("orchestrator.Orchestrator") as mock_cls, \
         patch("github_client.GitHubClient") as mock_gh_cls, \
         patch("watcher._load_pipeline_config", return_value={}), \
         patch("watcher._collect_issue_prior_context", return_value=""):

        mock_gh = MagicMock()
        mock_gh.get_issue.return_value = {"number": 1, "title": "Article: Test", "body": "brief"}
        mock_gh.get_file_content.return_value = None  # file not found
        mock_gh_cls.return_value = mock_gh

        mock_orch = _make_orch_mock()
        mock_orch.run.return_value = mock_result
        mock_cls.return_value = mock_orch

        import tempfile, logging
        from pathlib import Path
        log = logging.getLogger("test")
        with tempfile.NamedTemporaryFile(suffix=".log") as f:
            _dispatch(
                label="news-article",
                tracker_repo="wanleung/ai-it-press",
                target_repo="wanleung/ai-it-press",
                issue_number=1,
                model="gpt-4.1",
                num_engineers=1,
                log_file=Path(f.name),
                logger=log,
                pipeline_file="pipelines/news-article.yaml",
            )

    # _pipeline_yaml_stages should NOT have been set (fallback to load_pipeline_for_label)
    assert mock_orch._pipeline_yaml_stages is None


def test_build_watch_tasks_includes_pipeline_file():
    """_build_watch_tasks returns tasks with pipeline_file from repo config."""
    import watcher
    repo_config = {
        "tracker_repo": "wanleung/ai-it-press",
        "pipeline_file": "pipelines/news-article.yaml",
        "labels": {"news-article": {}},
        "enabled": True,
    }

    with patch.object(watcher, "_load_pipeline_config", return_value={}), \
         patch.object(watcher, "get_open_issues", return_value=[
             {"number": 1, "title": "Article: X", "labels": [{"name": "news-article"}],
              "body": None, "state": "open", "pull_request": None, "html_url": ""}
         ]), \
         patch.object(watcher, "add_label"):
        built = watcher._build_watch_tasks(
            watchers=[repo_config],
            model="gpt-4.1",
            num_engineers=1,
            github_token="fake-token",
        )
    pipeline_files = [t.get("pipeline_file") for t in built]
    assert "pipelines/news-article.yaml" in pipeline_files
