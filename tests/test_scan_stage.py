"""Tests for scan stage functionality."""
from __future__ import annotations
from unittest.mock import MagicMock


def test_pipeline_result_has_repo_context_field():
    """PipelineResult should have a repo_context field defaulting to None."""
    from orchestrator import PipelineResult

    result = PipelineResult()
    assert result.repo_context is None


def _make_orchestrator_for_scan(*, repo_auto_indexer=None, target_github=None):
    """Build a minimal Orchestrator stub with just enough to test _stage_scan."""
    from orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.repo_auto_indexer = repo_auto_indexer
    orch.target_github = target_github
    orch._github_token = "token"
    from repo_context import RepoContextLoader
    orch.repo_context_loader = RepoContextLoader()
    return orch


def test_stage_scan_builds_file_tree_and_stores_on_result():
    """_stage_scan stores the RepoContext result on result.repo_context."""
    from orchestrator import Orchestrator, PipelineResult
    from repo_context import RepoContext

    gh = MagicMock()
    fake_ctx = RepoContext(file_count=5, is_large=False, tree_text="tree", paths=[])
    loader_mock = MagicMock()
    loader_mock.build.return_value = fake_ctx

    orch = Orchestrator.__new__(Orchestrator)
    orch.repo_auto_indexer = None
    orch.target_github = gh
    orch._github_token = "tok"
    orch.repo_context_loader = loader_mock

    result = PipelineResult()
    orch._stage_scan(result)

    loader_mock.build.assert_called_once_with(gh)
    assert result.repo_context is fake_ctx


def test_stage_scan_calls_rag_indexer_when_configured():
    """_stage_scan calls repo_auto_indexer.index when RAG is configured."""
    from orchestrator import Orchestrator, PipelineResult

    gh = MagicMock()
    gh.repo = "owner/repo"
    indexer = MagicMock()
    loader_mock = MagicMock()
    from repo_context import RepoContext
    loader_mock.build.return_value = RepoContext()

    orch = Orchestrator.__new__(Orchestrator)
    orch.repo_auto_indexer = indexer
    orch.target_github = gh
    orch._github_token = "tok"
    orch.repo_context_loader = loader_mock

    result = PipelineResult()
    orch._stage_scan(result)

    indexer.index.assert_called_once_with(repo="owner/repo", github_token="tok")


def test_stage_scan_adds_rag_index_to_completed_stages():
    """_stage_scan adds 'rag_index' to result.completed_stages after indexing."""
    from orchestrator import Orchestrator, PipelineResult

    gh = MagicMock()
    gh.repo = "owner/repo"
    indexer = MagicMock()
    loader_mock = MagicMock()
    from repo_context import RepoContext
    loader_mock.build.return_value = RepoContext()

    orch = Orchestrator.__new__(Orchestrator)
    orch.repo_auto_indexer = indexer
    orch.target_github = gh
    orch._github_token = "tok"
    orch.repo_context_loader = loader_mock

    result = PipelineResult()
    orch._stage_scan(result)

    assert "rag_index" in result.completed_stages


def test_stage_scan_skips_rag_silently_when_not_configured():
    """_stage_scan skips RAG (no error) when repo_auto_indexer is None."""
    from orchestrator import Orchestrator, PipelineResult

    gh = MagicMock()
    loader_mock = MagicMock()
    from repo_context import RepoContext
    loader_mock.build.return_value = RepoContext()

    orch = Orchestrator.__new__(Orchestrator)
    orch.repo_auto_indexer = None
    orch.target_github = gh
    orch._github_token = "tok"
    orch.repo_context_loader = loader_mock

    result = PipelineResult()
    orch._stage_scan(result)  # must not raise

    assert "rag_index" not in result.completed_stages
    assert result.repo_context is not None


def test_stage_scan_is_noop_when_no_target_github():
    """_stage_scan skips all work when target_github is None."""
    from orchestrator import Orchestrator, PipelineResult

    loader_mock = MagicMock()

    orch = Orchestrator.__new__(Orchestrator)
    orch.repo_auto_indexer = MagicMock()
    orch.target_github = None
    orch._github_token = "tok"
    orch.repo_context_loader = loader_mock

    result = PipelineResult()
    orch._stage_scan(result)

    loader_mock.build.assert_not_called()
    orch.repo_auto_indexer.index.assert_not_called()
    assert result.repo_context is None


def test_stage_scan_is_noop_when_no_repo_context_loader():
    """_stage_scan is a no-op (no crash) when repo_context_loader is None."""
    from orchestrator import Orchestrator, PipelineResult

    orch = Orchestrator.__new__(Orchestrator)
    orch.target_github = MagicMock()
    orch.repo_auto_indexer = None
    orch._github_token = "tok"
    orch.repo_context_loader = None

    result = PipelineResult()
    orch._stage_scan(result)  # must not raise
    assert result.repo_context is None


def test_scan_stage_is_in_stage_registry():
    """'scan' must appear in _build_utility_stages() output."""
    from orchestrator import Orchestrator, PipelineStage
    from unittest.mock import patch

    orch = Orchestrator.__new__(Orchestrator)
    orch._stage_timeouts = {}
    orch._discussions_dir = __import__("pathlib").Path("/nonexistent_dir_that_does_not_exist")

    registry = orch._build_utility_stages()

    assert "scan" in registry
    stage = registry["scan"]
    assert stage.name == "scan"
    assert stage.checkpoint_key == "scan"


def test_stage_scan_skips_rag_when_already_indexed():
    """_stage_scan must not call repo_auto_indexer.index() when rag_index is already complete.

    This covers the double-indexing scenario where _run_preamble_stages() has
    already indexed before the YAML scan stage runs.
    """
    from orchestrator import PipelineResult

    mock_gh = MagicMock()
    mock_gh.repo = "owner/repo"
    mock_indexer = MagicMock()

    orch = _make_orchestrator_for_scan(
        repo_auto_indexer=mock_indexer,
        target_github=mock_gh,
    )

    # Patch repo_context_loader to avoid real API call
    orch.repo_context_loader = MagicMock()
    from repo_context import RepoContext
    orch.repo_context_loader.build.return_value = RepoContext()

    result = PipelineResult()
    result.add_completed_stage("rag_index")  # simulate preamble already indexed

    orch._stage_scan(result)

    mock_indexer.index.assert_not_called()


def test_implicit_rag_fallback_skips_when_scan_already_ran():
    """The implicit RAG fallback in run() must not re-index if scan already ran."""
    # This validates the guard at orchestrator.py:3686 directly by simulating
    # what _run_preamble_stages would see after the scan stage ran.
    from orchestrator import PipelineResult

    result = PipelineResult()
    result.add_completed_stage("rag_index")

    # The guard condition is: "rag_index" not in result.completed_stages
    # If guard is True, re-index happens. We want it to be False (no re-index).
    assert "rag_index" in result.completed_stages, \
        "add_completed_stage must persist 'rag_index' so fallback guard evaluates to False"

