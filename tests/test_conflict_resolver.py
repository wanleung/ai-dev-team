"""Tests for ConflictResolverAgent."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from unittest.mock import MagicMock, patch, call
import pytest

from agents.conflict_resolver import ConflictResolverAgent, PRContext, ResolveResult


CONFLICT_CONTENT = """\
<<<<<<< HEAD
def hello():
    return "from PR"
=======
def hello():
    return "from base"
>>>>>>> origin/main
"""

RESOLVED_CONTENT = 'def hello():\n    return "merged"\n'


@pytest.fixture
def agent():
    a = ConflictResolverAgent.__new__(ConflictResolverAgent)
    a.call = MagicMock(return_value=RESOLVED_CONTENT)
    return a


@pytest.fixture
def pr_ctx():
    return PRContext(
        pr_title="My PR",
        pr_body="Implements feature X",
        design_doc="",
        skills="",
    )


def _make_run(conflict_files=("src/hello.py",), push_ok=True):
    """Return a side_effect function for subprocess.run mock."""
    calls = []

    def _run(cmd, **kwargs):
        calls.append(cmd)
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        if isinstance(cmd, list) and "merge" in cmd:
            result.returncode = 1  # conflict
        if isinstance(cmd, list) and "--diff-filter=U" in " ".join(cmd):
            result.stdout = "\n".join(conflict_files) + "\n"
            result.returncode = 0
        if isinstance(cmd, list) and "push" in cmd and not push_ok:
            result.returncode = 1
            result.stderr = "push rejected"
        return result

    return _run, calls


# ── resolve: single file success ──────────────────────────────────────────────

def test_resolve_single_file(agent, pr_ctx, tmp_path):
    run_fn, run_calls = _make_run(["src/hello.py"])

    with patch("agents.conflict_resolver.subprocess.run", side_effect=run_fn), \
         patch("agents.conflict_resolver.tempfile.mkdtemp", return_value=str(tmp_path)), \
         patch("agents.conflict_resolver.shutil.rmtree") as mock_rm:

        # Write conflict content so agent can read it
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "hello.py").write_text(CONFLICT_CONTENT)

        result = agent.resolve(
            "https://x-access-token:tok@github.com/owner/repo.git",
            "feature/x",
            "main",
            pr_ctx,
        )

    assert result.status == "resolved"
    assert "src/hello.py" in result.resolved_files
    assert result.failed_files == []
    mock_rm.assert_called_once_with(str(tmp_path), ignore_errors=True)


# ── resolve: no conflicts after merge (race condition) ────────────────────────

def test_resolve_no_conflicts(agent, pr_ctx, tmp_path):
    def _run(cmd, **kwargs):
        r = MagicMock()
        r.returncode = 0
        r.stdout = ""
        r.stderr = ""
        return r  # merge succeeds cleanly

    with patch("agents.conflict_resolver.subprocess.run", side_effect=_run), \
         patch("agents.conflict_resolver.tempfile.mkdtemp", return_value=str(tmp_path)), \
         patch("agents.conflict_resolver.shutil.rmtree"):

        result = agent.resolve(
            "https://x-access-token:tok@github.com/owner/repo.git",
            "feature/x", "main", pr_ctx,
        )

    assert result.status == "resolved"
    assert result.resolved_files == []


# ── resolve: clone failure ─────────────────────────────────────────────────────

def test_resolve_clone_failure(agent, pr_ctx, tmp_path):
    def _run(cmd, **kwargs):
        r = MagicMock()
        r.returncode = 1
        r.stderr = "authentication failed"
        return r

    with patch("agents.conflict_resolver.subprocess.run", side_effect=_run), \
         patch("agents.conflict_resolver.tempfile.mkdtemp", return_value=str(tmp_path)), \
         patch("agents.conflict_resolver.shutil.rmtree"):

        result = agent.resolve(
            "https://x-access-token:tok@github.com/owner/repo.git",
            "feature/x", "main", pr_ctx,
        )

    assert result.status == "failed"
    assert "clone failed" in result.reason


# ── resolve: push failure ──────────────────────────────────────────────────────

def test_resolve_push_failure(agent, pr_ctx, tmp_path):
    run_fn, _ = _make_run(["src/hello.py"], push_ok=False)

    with patch("agents.conflict_resolver.subprocess.run", side_effect=run_fn), \
         patch("agents.conflict_resolver.tempfile.mkdtemp", return_value=str(tmp_path)), \
         patch("agents.conflict_resolver.shutil.rmtree"):

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "hello.py").write_text(CONFLICT_CONTENT)

        result = agent.resolve(
            "https://x-access-token:tok@github.com/owner/repo.git",
            "feature/x", "main", pr_ctx,
        )

    assert result.status == "failed"
    assert "push failed" in result.reason


# ── resolve: LLM fails for one file → failed_files ────────────────────────────

def test_resolve_llm_failure_for_file(agent, pr_ctx, tmp_path):
    agent.call.side_effect = RuntimeError("LLM unavailable")

    run_fn, _ = _make_run(["src/hello.py"])

    with patch("agents.conflict_resolver.subprocess.run", side_effect=run_fn), \
         patch("agents.conflict_resolver.tempfile.mkdtemp", return_value=str(tmp_path)), \
         patch("agents.conflict_resolver.shutil.rmtree"):

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "hello.py").write_text(CONFLICT_CONTENT)

        result = agent.resolve(
            "https://x-access-token:tok@github.com/owner/repo.git",
            "feature/x", "main", pr_ctx,
        )

    assert result.status == "failed"
    assert "src/hello.py" in result.failed_files


# ── resolve: multi-file success ───────────────────────────────────────────────

def test_resolve_multi_file(agent, pr_ctx, tmp_path):
    run_fn, _ = _make_run(["a.py", "b.py"])

    with patch("agents.conflict_resolver.subprocess.run", side_effect=run_fn), \
         patch("agents.conflict_resolver.tempfile.mkdtemp", return_value=str(tmp_path)), \
         patch("agents.conflict_resolver.shutil.rmtree"):

        for name in ["a.py", "b.py"]:
            (tmp_path / name).write_text(CONFLICT_CONTENT)

        result = agent.resolve(
            "https://x-access-token:tok@github.com/owner/repo.git",
            "feature/x", "main", pr_ctx,
        )

    assert result.status == "resolved"
    assert sorted(result.resolved_files) == ["a.py", "b.py"]


# ── tempdir always cleaned up ─────────────────────────────────────────────────

def test_tempdir_cleaned_on_exception(agent, pr_ctx, tmp_path):
    with patch("agents.conflict_resolver.subprocess.run", side_effect=RuntimeError("boom")), \
         patch("agents.conflict_resolver.tempfile.mkdtemp", return_value=str(tmp_path)), \
         patch("agents.conflict_resolver.shutil.rmtree") as mock_rm:

        result = agent.resolve(
            "https://x-access-token:tok@github.com/owner/repo.git",
            "feature/x", "main", pr_ctx,
        )

    mock_rm.assert_called_once_with(str(tmp_path), ignore_errors=True)
    assert result.status == "failed"
