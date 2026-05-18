"""Integration tests for watcher pipeline dispatch.

Tests that watcher._dispatch() correctly constructs and calls Orchestrator.run()
for labelled issues, with proper parameter passing and error handling.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_environment(tmp_path: Path) -> dict:
    """Set up test environment with mocked GitHub token and log file."""
    log_file = tmp_path / "test_dispatch.log"
    return {
        "log_file": log_file,
        "tracker_repo": "test-org/tracker",
        "target_repo": "test-org/target",
        "issue_number": 42,
        "label": "feature",
        "model": "gpt-4.1",
        "num_engineers": 3,
    }


@pytest.fixture
def mock_github_token(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set GITHUB_TOKEN environment variable for tests."""
    token = "test_github_token_12345"
    monkeypatch.setenv("GITHUB_TOKEN", token)
    return token


@pytest.fixture
def mock_pipeline_config() -> dict:
    """Mock pipeline configuration."""
    return {
        "llm": {
            "model": "gpt-4.1",
            "overrides": {},
            "ollama_url": "http://localhost:11434",
        },
        "pipeline": {
            "retry_delay": 15,
            "max_api_retries": 5,
            "inter_call_delay": 0,
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_dispatch_happy_path_calls_orchestrator_run(
    mock_environment: dict,
    mock_github_token: str,
    mock_pipeline_config: dict,
) -> None:
    """Test that _dispatch constructs Orchestrator and calls run() with correct parameters."""
    from watcher import _dispatch
    from orchestrator import PipelineResult

    mock_logger = MagicMock(spec=logging.Logger)
    mock_issue = {
        "number": 42,
        "title": "Test feature request",
        "body": "Implement a new feature for testing",
        "labels": [{"name": "feature"}],
    }
    mock_pipeline_result = PipelineResult(
        requirement="Test requirement",
        verdict="APPROVED",
    )

    with (
        patch("watcher._load_pipeline_config", return_value=mock_pipeline_config),
        patch("github_client.GitHubClient") as MockGitHubClient,
        patch("orchestrator.Orchestrator") as MockOrchestrator,
        patch("watcher._collect_issue_prior_context", return_value=""),
    ):
        # Setup mocks
        mock_gh_client = MockGitHubClient.return_value
        mock_gh_client.get_issue.return_value = mock_issue

        mock_orch_instance = MockOrchestrator.return_value
        mock_orch_instance.load_pipeline_for_label.return_value = None
        mock_orch_instance.run.return_value = mock_pipeline_result

        # Execute _dispatch
        result = _dispatch(
            label=mock_environment["label"],
            tracker_repo=mock_environment["tracker_repo"],
            target_repo=mock_environment["target_repo"],
            issue_number=mock_environment["issue_number"],
            model=mock_environment["model"],
            num_engineers=mock_environment["num_engineers"],
            log_file=mock_environment["log_file"],
            logger=mock_logger,
        )

        # Verify GitHubClient was instantiated with correct params
        MockGitHubClient.assert_called_once_with(
            mock_environment["tracker_repo"],
            mock_github_token,
        )

        # Verify issue was fetched
        mock_gh_client.get_issue.assert_called_once_with(mock_environment["issue_number"])

        # Verify Orchestrator was instantiated with correct params
        MockOrchestrator.assert_called_once()
        orch_call = MockOrchestrator.call_args
        assert orch_call.kwargs["model"] == mock_environment["model"]
        assert orch_call.kwargs["github_token"] == mock_github_token
        assert orch_call.kwargs["github_repo"] == mock_environment["tracker_repo"]
        assert orch_call.kwargs["target_repo"] == mock_environment["target_repo"]
        assert orch_call.kwargs["num_engineers"] == mock_environment["num_engineers"]
        assert orch_call.kwargs["use_github"] is True

        # Verify Orchestrator.run was called with issue body and number
        mock_orch_instance.run.assert_called_once()
        run_call = mock_orch_instance.run.call_args
        assert mock_issue["body"] in run_call[0][0] or mock_issue["title"] in run_call[0][0]
        assert run_call.kwargs["issue_number"] == mock_environment["issue_number"]

        # Verify result is returned
        assert result == mock_pipeline_result
        assert result.verdict == "APPROVED"


def test_dispatch_with_pipeline_config_override(
    mock_environment: dict,
    mock_github_token: str,
) -> None:
    """Test that _dispatch respects pipeline config model override."""
    from watcher import _dispatch
    from orchestrator import PipelineResult

    mock_logger = MagicMock(spec=logging.Logger)
    mock_issue = {
        "number": 42,
        "title": "Test issue",
        "body": "Test body",
    }

    # Pipeline config with model override
    pipeline_config_with_override = {
        "llm": {
            "model": "claude-sonnet-4",  # Override model
            "overrides": {"architect": "claude-opus-4.7"},
            "ollama_url": "http://localhost:11434",
        },
        "pipeline": {
            "retry_delay": 10,
            "max_api_retries": 3,
            "inter_call_delay": 1,
        },
    }

    with (
        patch("watcher._load_pipeline_config", return_value=pipeline_config_with_override),
        patch("github_client.GitHubClient") as MockGitHubClient,
        patch("orchestrator.Orchestrator") as MockOrchestrator,
        patch("watcher._collect_issue_prior_context", return_value=""),
    ):
        mock_gh_client = MockGitHubClient.return_value
        mock_gh_client.get_issue.return_value = mock_issue

        mock_orch_instance = MockOrchestrator.return_value
        mock_orch_instance.load_pipeline_for_label.return_value = None
        mock_orch_instance.run.return_value = PipelineResult()

        # Execute with a different model that should be overridden
        _dispatch(
            label="feature",
            tracker_repo=mock_environment["tracker_repo"],
            target_repo=mock_environment["target_repo"],
            issue_number=mock_environment["issue_number"],
            model="gpt-4.1",  # This should be overridden
            num_engineers=mock_environment["num_engineers"],
            log_file=mock_environment["log_file"],
            logger=mock_logger,
        )

        # Verify Orchestrator was called with overridden model
        orch_call = MockOrchestrator.call_args
        assert orch_call.kwargs["model"] == "claude-sonnet-4"  # Config override
        assert orch_call.kwargs["model_overrides"] == {"architect": "claude-opus-4.7"}
        assert orch_call.kwargs["retry_delay"] == 10
        assert orch_call.kwargs["max_api_retries"] == 3
        assert orch_call.kwargs["inter_call_delay"] == 1


def test_dispatch_collects_prior_issue_context(
    mock_environment: dict,
    mock_github_token: str,
    mock_pipeline_config: dict,
) -> None:
    """Test that _dispatch collects and appends prior issue comments as context."""
    from watcher import _dispatch
    from orchestrator import PipelineResult

    mock_logger = MagicMock(spec=logging.Logger)
    mock_issue = {
        "number": 42,
        "title": "Test issue",
        "body": "Original issue body",
    }
    prior_context = "\n\n---\n**Prior PRD:**\n..."

    with (
        patch("watcher._load_pipeline_config", return_value=mock_pipeline_config),
        patch("github_client.GitHubClient") as MockGitHubClient,
        patch("orchestrator.Orchestrator") as MockOrchestrator,
        patch("watcher._collect_issue_prior_context", return_value=prior_context),
    ):
        mock_gh_client = MockGitHubClient.return_value
        mock_gh_client.get_issue.return_value = mock_issue

        mock_orch_instance = MockOrchestrator.return_value
        mock_orch_instance.load_pipeline_for_label.return_value = None
        mock_orch_instance.run.return_value = PipelineResult()

        _dispatch(
            label="feature",
            tracker_repo=mock_environment["tracker_repo"],
            target_repo=mock_environment["target_repo"],
            issue_number=mock_environment["issue_number"],
            model=mock_environment["model"],
            num_engineers=mock_environment["num_engineers"],
            log_file=mock_environment["log_file"],
            logger=mock_logger,
        )

        # Verify run was called with concatenated body + prior context
        run_call = mock_orch_instance.run.call_args
        assert run_call.kwargs["trigger_issue_body"] == "Original issue body" + prior_context


def test_dispatch_loads_custom_pipeline_yaml(
    mock_environment: dict,
    mock_github_token: str,
    mock_pipeline_config: dict,
) -> None:
    """Test that _dispatch loads and applies custom pipeline YAML when available."""
    from watcher import _dispatch
    from orchestrator import PipelineResult

    mock_logger = MagicMock(spec=logging.Logger)
    mock_issue = {
        "number": 42,
        "title": "Test issue",
        "body": "Test body",
    }
    custom_stages = [
        {"name": "stage1", "agent": "architect"},
        {"name": "stage2", "agent": "engineer"},
    ]

    with (
        patch("watcher._load_pipeline_config", return_value=mock_pipeline_config),
        patch("github_client.GitHubClient") as MockGitHubClient,
        patch("orchestrator.Orchestrator") as MockOrchestrator,
        patch("watcher._collect_issue_prior_context", return_value=""),
    ):
        mock_gh_client = MockGitHubClient.return_value
        mock_gh_client.get_issue.return_value = mock_issue

        mock_orch_instance = MockOrchestrator.return_value
        mock_orch_instance.load_pipeline_for_label.return_value = custom_stages
        mock_orch_instance.run.return_value = PipelineResult()

        _dispatch(
            label="custom-label",
            tracker_repo=mock_environment["tracker_repo"],
            target_repo=mock_environment["target_repo"],
            issue_number=mock_environment["issue_number"],
            model=mock_environment["model"],
            num_engineers=mock_environment["num_engineers"],
            log_file=mock_environment["log_file"],
            logger=mock_logger,
        )

        # Verify pipeline was loaded for the label
        mock_orch_instance.load_pipeline_for_label.assert_called_once_with("custom-label")

        # Verify custom stages were assigned
        assert mock_orch_instance._pipeline_yaml_stages == custom_stages


def test_dispatch_missing_github_token(
    mock_environment: dict,
    mock_pipeline_config: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that _dispatch handles missing GITHUB_TOKEN gracefully."""
    from watcher import _dispatch
    from orchestrator import PipelineResult

    # Remove GITHUB_TOKEN from environment
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    mock_logger = MagicMock(spec=logging.Logger)

    with (
        patch("watcher._load_pipeline_config", return_value=mock_pipeline_config),
        patch("github_client.GitHubClient") as MockGitHubClient,
        patch("orchestrator.Orchestrator") as MockOrchestrator,
        patch("watcher._collect_issue_prior_context", return_value=""),
    ):
        mock_gh_client = MockGitHubClient.return_value
        mock_gh_client.get_issue.return_value = {"number": 42, "title": "Test", "body": "Test"}
        
        mock_orch_instance = MockOrchestrator.return_value
        mock_orch_instance.load_pipeline_for_label.return_value = None
        mock_orch_instance.run.return_value = PipelineResult()
        
        # GitHubClient should be called with None token
        _dispatch(
            label="feature",
            tracker_repo=mock_environment["tracker_repo"],
            target_repo=mock_environment["target_repo"],
            issue_number=mock_environment["issue_number"],
            model=mock_environment["model"],
            num_engineers=mock_environment["num_engineers"],
            log_file=mock_environment["log_file"],
            logger=mock_logger,
        )

        # Verify GitHubClient was called with None
        MockGitHubClient.assert_called_once_with(
            mock_environment["tracker_repo"],
            None,
        )
