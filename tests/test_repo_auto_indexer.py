"""Tests for RepoAutoIndexer."""
from unittest.mock import MagicMock, patch
import subprocess
import pytest


def test_index_calls_subprocess_with_workspace_path(tmp_path):
    """Test that index() calls subprocess with the workspace path."""
    from repo_context import RepoAutoIndexer

    indexer = RepoAutoIndexer(indexer_script="rag-mcp/indexer.py")

    with patch("repo_context.subprocess.run") as mock_run, \
         patch("repo_context.Path.exists", return_value=True):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        indexer.index(repo="owner/myrepo", github_token="tok", repo_dir=str(tmp_path))

    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]  # First positional arg (the command list)
    assert str(tmp_path) in call_args
    assert "--path" in call_args


def test_index_subprocess_exception_propagates(tmp_path):
    """Test that subprocess exceptions other than returncode are propagated."""
    from repo_context import RepoAutoIndexer

    indexer = RepoAutoIndexer(indexer_script="rag-mcp/indexer.py")

    with patch("repo_context.subprocess.run") as mock_run, \
         patch("repo_context.Path.exists", return_value=True):
        # Simulate timeout or other subprocess error
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 300)
        
        # Should raise the exception
        with pytest.raises(subprocess.TimeoutExpired):
            indexer.index(repo="owner/myrepo", github_token="tok", repo_dir=str(tmp_path))


def test_index_nonzero_exit_logged_no_exception(tmp_path, caplog):
    """Test that non-zero subprocess exit is logged but no exception propagated."""
    from repo_context import RepoAutoIndexer
    import logging

    indexer = RepoAutoIndexer(indexer_script="rag-mcp/indexer.py")

    with patch("repo_context.subprocess.run") as mock_run, \
         patch("repo_context.Path.exists", return_value=True), \
         caplog.at_level(logging.WARNING):
        mock_run.return_value = MagicMock(returncode=1, stderr="Index failed")
        
        # Should not raise
        indexer.index(repo="owner/myrepo", github_token="tok", repo_dir=str(tmp_path))

    # Check that a warning was logged
    assert any("RAG indexer exited" in record.message for record in caplog.records)
    assert any("1" in record.message for record in caplog.records)


def test_index_skips_when_script_missing(tmp_path):
    """Test that index() returns early when indexer script doesn't exist."""
    from repo_context import RepoAutoIndexer

    indexer = RepoAutoIndexer(indexer_script="/nonexistent/indexer.py")

    with patch("repo_context.subprocess.run") as mock_run:
        # Should not call subprocess at all
        indexer.index(repo="owner/myrepo", github_token="tok", repo_dir=str(tmp_path))
        
    mock_run.assert_not_called()


def test_index_downloads_repo_when_no_repo_dir():
    """Test that index() downloads repo zip when repo_dir is not provided."""
    from repo_context import RepoAutoIndexer

    indexer = RepoAutoIndexer(indexer_script="rag-mcp/indexer.py")

    with patch("repo_context.subprocess.run") as mock_run, \
         patch("repo_context.Path.exists", return_value=True), \
         patch.object(indexer, "_download_repo_zip", return_value="/tmp/extracted") as mock_download, \
         patch.object(indexer, "_run_indexer") as mock_index:
        
        indexer.index(repo="owner/myrepo", github_token="tok", ref="main")

    mock_download.assert_called_once()
    mock_index.assert_called_once_with("/tmp/extracted")
