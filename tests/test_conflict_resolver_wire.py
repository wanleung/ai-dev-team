"""Tests for ConflictResolverAgent wired into Orchestrator._update_branch_from_base."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.conflict_resolver import PRContext, ResolveResult
from orchestrator import Orchestrator


# ── shared fixture ──────────────────────────────────────────────────────────

@pytest.fixture
def orch():
    """Minimal Orchestrator with no real API calls."""
    o = Orchestrator.__new__(Orchestrator)
    o.model = "gpt-4.1"
    o.senior_model = None
    o.conflict_resolver_model = None
    o.agent_kwargs = {"github_token": "tok"}
    o.target_github = MagicMock()
    o.target_github.repo = "owner/repo"
    o.target_github.token = "ghp_test"
    return o


@pytest.fixture
def pr_ctx():
    return PRContext(
        pr_title="My PR",
        pr_body="Implements feature X",
        design_doc="",
        skills="",
    )


# ── test_conflict_resolver_called_on_409 ───────────────────────────────────

def test_conflict_resolver_called_on_409(orch, pr_ctx):
    """When merge returns 409, ConflictResolverAgent is called and retries merge."""
    # First merge attempt → 409 conflict; retry after resolution → 201 success
    orch.target_github.merge_base_into_branch.side_effect = [409, 201]

    resolved_result = ResolveResult(
        status="resolved",
        resolved_files=["src/app.py"],
    )

    with patch(
        "orchestrator.ConflictResolverAgent", autospec=True
    ) as MockResolver:
        instance = MockResolver.return_value
        instance.resolve.return_value = resolved_result

        result = orch._update_branch_from_base(
            head_branch="feature/my-branch",
            base_branch="main",
            pr_context=pr_ctx,
        )

    # ConflictResolverAgent must have been constructed
    MockResolver.assert_called_once()
    call_kwargs = MockResolver.call_args

    # resolve() must have been called with the correct branches and pr_context
    instance.resolve.assert_called_once_with(
        repo_url="https://ghp_test@github.com/owner/repo.git",
        head_branch="feature/my-branch",
        base_branch="main",
        pr_context=pr_ctx,
    )

    # After resolution the retry merge was called and we got "merged"
    assert result == {"status": "merged"}
    assert orch.target_github.merge_base_into_branch.call_count == 2


# ── test_conflict_resolver_failed_returns_false ────────────────────────────

def test_conflict_resolver_failed_returns_false(orch, pr_ctx):
    """When ConflictResolverAgent returns status='failed', returns conflict dict."""
    orch.target_github.merge_base_into_branch.return_value = 409

    failed_result = ResolveResult(
        status="failed",
        failed_files=["src/app.py"],
        reason="LLM resolution failed for: src/app.py",
    )

    with patch(
        "orchestrator.ConflictResolverAgent", autospec=True
    ) as MockResolver:
        instance = MockResolver.return_value
        instance.resolve.return_value = failed_result

        result = orch._update_branch_from_base(
            head_branch="feature/my-branch",
            base_branch="main",
            pr_context=pr_ctx,
        )

    assert result["status"] == "conflict"
    # Retry merge should NOT have been called (agent reported failure)
    assert orch.target_github.merge_base_into_branch.call_count == 1


# ── test_no_pr_context_returns_false_on_conflict ───────────────────────────

def test_no_pr_context_returns_false_on_conflict(orch):
    """When pr_context=None and merge returns 409, returns conflict immediately."""
    orch.target_github.merge_base_into_branch.return_value = 409

    with patch(
        "orchestrator.ConflictResolverAgent", autospec=True
    ) as MockResolver:
        result = orch._update_branch_from_base(
            head_branch="feature/my-branch",
            base_branch="main",
            pr_context=None,  # no context
        )

    # ConflictResolverAgent must NOT be instantiated or called
    MockResolver.assert_not_called()

    assert result["status"] == "conflict"
    assert result["conflicting_files"] == []
    # Only one merge call (no retry)
    assert orch.target_github.merge_base_into_branch.call_count == 1
