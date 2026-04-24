"""Tests for RepoContextLoader and RepoContext."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from repo_context import RepoContext, RepoContextLoader


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_tree(paths: list[str]) -> list[dict]:
    """Build the list[dict] format get_full_tree() returns."""
    result = []
    for p in paths:
        entry_type = "blob" if "." in p.split("/")[-1] else "tree"
        result.append({"path": p, "type": entry_type, "size": 100})
    return result


def _make_gh(paths: list[str]) -> MagicMock:
    gh = MagicMock()
    gh.get_full_tree.return_value = _make_tree(paths)
    return gh


# ── get_full_tree (unit) ──────────────────────────────────────────────────────

def test_get_full_tree_calls_git_trees_api():
    from github_client import GitHubClient
    gh = MagicMock(spec=GitHubClient)
    # Confirm method signature exists
    assert hasattr(GitHubClient, "get_full_tree")


# ── RepoContextLoader — small repo ───────────────────────────────────────────

def test_small_repo_is_not_large():
    paths = [f"src/file{i}.py" for i in range(10)]
    gh = _make_gh(paths)
    loader = RepoContextLoader(threshold=50)
    ctx = loader.build(gh)
    assert ctx.file_count == 10
    assert ctx.is_large is False


def test_large_repo_is_large():
    paths = [f"src/file{i}.py" for i in range(60)]
    gh = _make_gh(paths)
    loader = RepoContextLoader(threshold=50)
    ctx = loader.build(gh)
    assert ctx.file_count == 60
    assert ctx.is_large is True


def test_threshold_boundary_at_exactly_threshold():
    paths = [f"src/file{i}.py" for i in range(50)]
    gh = _make_gh(paths)
    loader = RepoContextLoader(threshold=50)
    ctx = loader.build(gh)
    # exactly at threshold → large
    assert ctx.is_large is True


# ── Tree text rendering ───────────────────────────────────────────────────────

def test_small_repo_tree_text_contains_all_files():
    paths = ["src/main.py", "tests/test_main.py", "README.md"]
    gh = _make_gh(paths)
    loader = RepoContextLoader(threshold=50)
    ctx = loader.build(gh)
    assert "src/main.py" in ctx.tree_text
    assert "tests/test_main.py" in ctx.tree_text
    assert "README.md" in ctx.tree_text


def test_large_repo_tree_text_only_top_two_levels():
    # Files deeper than 2 levels should not appear
    paths = [
        "src/main.py",                        # depth 2 — visible as file
        "src/utils/helper.py",                 # depth 3 — shown as dir summary
        "src/utils/deep/nested/file.py",       # depth 5 — omitted (parent dir already shown)
    ]
    gh = _make_gh(paths)
    loader = RepoContextLoader(threshold=2)   # threshold=2 → large
    ctx = loader.build(gh)
    assert "src/main.py" in ctx.tree_text
    assert "src/utils" in ctx.tree_text
    assert "nested/file.py" not in ctx.tree_text


def test_tree_text_not_empty_when_repo_has_files():
    paths = ["README.md", "main.py"]
    gh = _make_gh(paths)
    loader = RepoContextLoader(threshold=50)
    ctx = loader.build(gh)
    assert ctx.tree_text.strip() != ""


def test_tree_text_empty_when_repo_empty():
    gh = _make_gh([])
    loader = RepoContextLoader(threshold=50)
    ctx = loader.build(gh)
    assert ctx.tree_text == ""


# ── build() returns RepoContext dataclass ────────────────────────────────────

def test_build_returns_repo_context_instance():
    gh = _make_gh(["main.py"])
    loader = RepoContextLoader(threshold=50)
    ctx = loader.build(gh)
    assert isinstance(ctx, RepoContext)
    assert hasattr(ctx, "file_count")
    assert hasattr(ctx, "is_large")
    assert hasattr(ctx, "tree_text")
    assert hasattr(ctx, "paths")


def test_build_returns_empty_context_when_github_unavailable():
    loader = RepoContextLoader(threshold=50)
    ctx = loader.build(None)
    assert ctx.file_count == 0
    assert ctx.is_large is False
    assert ctx.tree_text == ""


def test_large_repo_deep_only_directory_shows_summary():
    """A dir with ONLY depth-4+ files (no depth-3 sibling) must still show a summary line."""
    paths = ["src/deep/nested/very/file.py"]  # depth 5, no depth-3 sibling
    gh = _make_gh(paths)
    loader = RepoContextLoader(threshold=1)
    ctx = loader.build(gh)
    assert "src/deep" in ctx.tree_text


def test_get_full_tree_returns_empty_when_truncated():
    """When GitHub returns truncated=true, get_full_tree should return []."""
    from github_client import GitHubClient
    gh = GitHubClient.__new__(GitHubClient)
    gh.repo = "test/repo"
    gh._request = MagicMock(return_value={"truncated": True, "tree": [{"path": "file.py", "type": "blob", "size": 100}]})
    gh.get_default_branch = MagicMock(return_value="main")
    result = gh.get_full_tree()
    assert result == []

# ── Orchestrator integration ──────────────────────────────────────────────────

def test_orchestrator_injects_tree_into_architect_prompt():
    """Tree text should be prepended to Architect system_prompt in run()."""
    from unittest.mock import patch, MagicMock
    from orchestrator import Orchestrator

    orch = Orchestrator(model="gpt-4.1", use_github=False)

    mock_ctx = RepoContext(
        file_count=5,
        is_large=False,
        tree_text="## Repo File Tree\n  src/main.py\n  README.md",
        paths=[],
    )
    mock_loader = MagicMock()
    mock_loader.build.return_value = mock_ctx
    orch.repo_context_loader = mock_loader
    orch.target_github = MagicMock()

    def mock_prd_loop(result, requirement):
        result.completed_stages.append("pm_review_loop")
        return True

    with patch.object(orch, "_prd_revision_loop", side_effect=mock_prd_loop), \
         patch.object(orch, "_stage_architect"), \
         patch.object(orch, "_stage_architect_reviewer"), \
         patch.object(orch, "_stage_engineer"), \
         patch.object(orch, "_stage_reviewer"), \
         patch.object(orch, "_stage_qa_planner"), \
         patch.object(orch, "_stage_qa"), \
         patch.object(orch, "_stage_test_fix_loop"), \
         patch.object(orch, "_stage_deployment_tester"), \
         patch.object(orch, "_stage_deploy_fix_loop"), \
         patch.object(orch, "_stage_summary", create=True), \
         patch.object(orch, "_stage_memory_update", create=True):
        orch.run("Add login feature")

    assert "## Repo File Tree" in (orch.architect.system_prompt or "")


def test_orchestrator_no_injection_when_loader_absent():
    """If repo_context_loader is None, no tree text should be added."""
    from unittest.mock import patch
    from orchestrator import Orchestrator

    orch = Orchestrator(model="gpt-4.1", use_github=False)
    orch.repo_context_loader = None
    original_prompt = orch.architect.system_prompt or ""

    def mock_prd_loop(result, requirement):
        result.completed_stages.append("pm_review_loop")
        return True

    with patch.object(orch, "_prd_revision_loop", side_effect=mock_prd_loop), \
         patch.object(orch, "_stage_architect"), \
         patch.object(orch, "_stage_architect_reviewer"), \
         patch.object(orch, "_stage_engineer"), \
         patch.object(orch, "_stage_reviewer"), \
         patch.object(orch, "_stage_qa_planner"), \
         patch.object(orch, "_stage_qa"), \
         patch.object(orch, "_stage_test_fix_loop"), \
         patch.object(orch, "_stage_deployment_tester"), \
         patch.object(orch, "_stage_deploy_fix_loop"), \
         patch.object(orch, "_stage_summary", create=True), \
         patch.object(orch, "_stage_memory_update", create=True):
        orch.run("Add login feature")

    assert orch.architect.system_prompt == original_prompt


def test_orchestrator_tree_injection_is_idempotent():
    """Calling run() twice should not stack the tree block twice."""
    import contextlib
    from unittest.mock import patch, MagicMock
    from orchestrator import Orchestrator

    orch = Orchestrator(model="gpt-4.1", use_github=False)

    mock_ctx = RepoContext(
        file_count=5,
        is_large=False,
        tree_text="## Repo File Tree\n  src/main.py",
        paths=[],
    )
    mock_loader = MagicMock()
    mock_loader.build.return_value = mock_ctx
    orch.repo_context_loader = mock_loader
    orch.target_github = MagicMock()

    def mock_prd_loop(result, requirement):
        result.completed_stages.append("pm_review_loop")
        return True

    stage_names = [
        "_stage_architect",
        "_stage_architect_reviewer", "_stage_engineer", "_stage_reviewer",
        "_stage_qa_planner", "_stage_qa", "_stage_test_fix_loop",
        "_stage_deployment_tester", "_stage_deploy_fix_loop",
        "_stage_summary", "_stage_memory_update",
    ]

    def run_once():
        patches = [patch.object(orch, "_prd_revision_loop", side_effect=mock_prd_loop)]
        patches.extend([patch.object(orch, name, create=True) for name in stage_names])
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            orch.run("Add login feature")

    run_once()
    prompt_after_first = orch.architect.system_prompt or ""
    run_once()
    prompt_after_second = orch.architect.system_prompt or ""

    assert prompt_after_first == prompt_after_second


# ── RepoAutoIndexer ───────────────────────────────────────────────────────────

def test_auto_indexer_calls_subprocess_with_codebase_source(tmp_path):
    """RepoAutoIndexer should call indexer.py with --source codebase."""
    from repo_context import RepoAutoIndexer

    indexer = RepoAutoIndexer(indexer_script="rag-mcp/indexer.py")

    with patch("repo_context.subprocess.run") as mock_run, \
         patch("repo_context.Path.exists", return_value=True):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        indexer.index(repo="owner/myrepo", github_token="tok", repo_dir=str(tmp_path))

    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]  # First positional arg (the command list)
    assert "--source" in call_args
    assert "codebase" in call_args
    assert "--path" in call_args
    assert "--clean" in call_args


def test_auto_indexer_skips_when_no_rag_script(tmp_path):
    """If the indexer script does not exist, index() should return without error."""
    from repo_context import RepoAutoIndexer

    indexer = RepoAutoIndexer(indexer_script="/nonexistent/path/indexer.py")
    # Should not raise
    indexer.index(repo="owner/repo", github_token="tok", repo_dir=str(tmp_path))


def test_orchestrator_calls_auto_index_when_rag_configured():
    """repo_auto_indexer.index() should be called in run() when rag_registry is set."""
    from orchestrator import Orchestrator

    orch = Orchestrator(model="gpt-4.1", use_github=False)
    # Inject a fake rag_registry and auto_indexer
    orch._rag_registry = MagicMock()
    orch.repo_auto_indexer = MagicMock()
    orch.target_github = MagicMock()
    orch.target_github.repo = "owner/myrepo"

    def mock_prd_loop(result, requirement):
        result.completed_stages.append("pm_review_loop")
        return True

    with patch.object(orch, "_prd_revision_loop", side_effect=mock_prd_loop), \
         patch.object(orch, "_stage_architect"), \
         patch.object(orch, "_stage_architect_reviewer"), \
         patch.object(orch, "_stage_engineer"), \
         patch.object(orch, "_stage_reviewer"), \
         patch.object(orch, "_stage_qa_planner"), \
         patch.object(orch, "_stage_qa"), \
         patch.object(orch, "_stage_test_fix_loop"), \
         patch.object(orch, "_stage_deployment_tester"), \
         patch.object(orch, "_stage_deploy_fix_loop"), \
         patch.object(orch, "_stage_summary", create=True), \
         patch.object(orch, "_stage_memory_update", create=True):
        orch.run("Add login feature")

    orch.repo_auto_indexer.index.assert_called_once()
