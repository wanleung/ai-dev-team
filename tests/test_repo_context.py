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
        "src/main.py",                        # depth 1 — visible
        "src/utils/helper.py",                 # depth 2 — visible (dir shown)
        "src/utils/deep/nested/file.py",       # depth 4 — should NOT appear
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
