# T15: Coverage — run_with_github, BaseAgent Utilities, Small Modules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push overall coverage from 87% to ≥88% by writing targeted tests for uncovered `run_with_github` methods, `BaseAgent` utility helpers, and small-module edge cases.

**Architecture:** Each task adds one new test file targeting specific modules. All tests use `unittest.mock` (`MagicMock`, `patch`) to avoid real LLM/network calls. Agent tests use `Agent.__new__(Agent)` + attribute injection to skip `BaseAgent.__init__`. No production code changes unless a genuine bug is found.

**Tech Stack:** Python 3.13, pytest, unittest.mock

**Branch:** `t15-coverage-runwithgithub-utils`  
**Worktree:** `.worktrees/t15`

---

## Task 1: Worktree + Branch Setup

**Files:**
- No files changed; this task only sets up the isolated workspace.

- [ ] **Step 1: Verify T14 PR is merged**

```bash
cd /home/wanleung/Projects/ai-software-house
git fetch origin
git log --oneline origin/master | head -5
```

Expected: commits from T14 (`t14-coverage-agents-tools-memory` branch) are present.
If not yet merged, branch from the T14 worktree head instead:

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t14
git log --oneline | head -3
```

- [ ] **Step 2: Create T15 worktree**

If T14 is merged to master:
```bash
cd /home/wanleung/Projects/ai-software-house
git worktree add .worktrees/t15 -b t15-coverage-runwithgithub-utils origin/master
```

If T14 is not yet merged, branch from T14:
```bash
cd /home/wanleung/Projects/ai-software-house
git worktree add .worktrees/t15 -b t15-coverage-runwithgithub-utils t14-coverage-agents-tools-memory
```

- [ ] **Step 3: Confirm baseline**

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t15
python3 -m pytest tests/ -q 2>&1 | tail -5
```

Expected: 1926 passed (or more if T14 added tests), 0 failures.

---

## Task 2: QAEngineerAgent + ConflictResolverAgent Coverage

**Files:**
- Create: `tests/test_qa_engineer_conflict_resolver.py`

**Context:** `agents/qa_engineer.py` has 16 uncovered lines — `run_with_github` (lines 100–160) is almost entirely missing, and `_parse_test_files` path normalisation (no `tests/` prefix) is untested. `agents/conflict_resolver.py` has 5 uncovered lines — checkout failure (lines 108–109), fetch failure (lines 114–115), and no-conflict clean merge (line 130).

- [ ] **Step 1: Write the tests**

Create `tests/test_qa_engineer_conflict_resolver.py`:

```python
"""Tests for QAEngineerAgent.run_with_github and ConflictResolverAgent error paths."""
from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from agents.qa_engineer import QAEngineerAgent
from agents.conflict_resolver import ConflictResolverAgent


# ──────────────────────────────────────────────────────────────────────────
# QAEngineerAgent.run_with_github
# ──────────────────────────────────────────────────────────────────────────

def _make_qa_agent() -> QAEngineerAgent:
    agent = QAEngineerAgent.__new__(QAEngineerAgent)
    agent._llm = MagicMock()
    agent.system_prompt = ""
    agent._history = []
    agent.model = "gpt-4.1"
    agent._backend = "github_models"
    return agent


def test_run_with_github_commits_and_comments():
    """run_with_github() should commit each test file and post a PR comment."""
    agent = _make_qa_agent()
    agent.run = MagicMock(return_value={
        "test_files": {
            "tests/test_foo.py": "def test_foo(): pass",
            "tests/test_bar.py": "def test_bar(): pass",
        },
        "test_plan": "## Test Plan\n- test_foo\n- test_bar",
    })

    mock_gh = MagicMock()

    result = agent.run_with_github(
        files={"src/foo.py": "x = 1"},
        prd="Build Foo",
        project_name="foo",
        github_client=mock_gh,
        branch="feat/foo",
        pr_number=7,
    )

    assert result["test_plan"] == "## Test Plan\n- test_foo\n- test_bar"
    assert mock_gh.commit_file.call_count == 2
    mock_gh.add_pr_comment.assert_called_once()
    comment_text = mock_gh.add_pr_comment.call_args[0][1]
    assert "QA Test Plan" in comment_text


def test_run_with_github_closes_issue_when_provided():
    """run_with_github() should close the tracker issue when issue_number is supplied."""
    agent = _make_qa_agent()
    agent.run = MagicMock(return_value={
        "test_files": {"tests/test_x.py": "pass"},
        "test_plan": "plan",
    })

    mock_gh = MagicMock()

    agent.run_with_github(
        files={"src/x.py": ""},
        prd="PRD",
        project_name="proj",
        github_client=mock_gh,
        branch="feat/x",
        pr_number=3,
        issue_number=42,
    )

    mock_gh.close_issue.assert_called_once_with(42, comment=pytest.approx(str, rel=1))
    # Verify the close comment mentions the project name
    close_call = mock_gh.close_issue.call_args
    assert "proj" in close_call[1]["comment"]


def test_run_with_github_uses_tracker_client_for_issue():
    """When tracker_github_client is different, use it to close the issue."""
    agent = _make_qa_agent()
    agent.run = MagicMock(return_value={
        "test_files": {},
        "test_plan": "plan",
    })

    mock_gh = MagicMock()
    mock_tracker = MagicMock()

    agent.run_with_github(
        files={},
        prd="PRD",
        project_name="proj",
        github_client=mock_gh,
        branch="feat/x",
        pr_number=3,
        issue_number=10,
        tracker_github_client=mock_tracker,
    )

    mock_tracker.close_issue.assert_called_once()
    mock_gh.close_issue.assert_not_called()


def test_run_with_github_no_issue_no_close():
    """run_with_github() must NOT call close_issue when issue_number is None."""
    agent = _make_qa_agent()
    agent.run = MagicMock(return_value={"test_files": {}, "test_plan": "plan"})
    mock_gh = MagicMock()

    agent.run_with_github(
        files={},
        prd="PRD",
        project_name="proj",
        github_client=mock_gh,
        branch="feat/x",
        pr_number=3,
    )

    mock_gh.close_issue.assert_not_called()


def test_parse_test_files_normalises_paths_without_tests_prefix():
    """_parse_test_files() must prepend 'tests/' when path lacks it."""
    response = """
### FILE: test_thing.py
```
def test_it(): pass
```
"""
    result = QAEngineerAgent._parse_test_files(response)
    # Path missing "tests/" prefix should be normalised
    assert "tests/test_thing.py" in result
    assert result["tests/test_thing.py"] == "def test_it(): pass"


def test_parse_test_files_leaves_tests_prefix_intact():
    """_parse_test_files() must not double-prefix paths already starting with 'tests/'."""
    response = """
### FILE: tests/test_bar.py
```
def test_bar(): assert True
```
"""
    result = QAEngineerAgent._parse_test_files(response)
    assert "tests/test_bar.py" in result
    assert "tests/tests/test_bar.py" not in result


# ──────────────────────────────────────────────────────────────────────────
# ConflictResolverAgent error paths
# ──────────────────────────────────────────────────────────────────────────

def _make_conflict_agent() -> ConflictResolverAgent:
    agent = ConflictResolverAgent.__new__(ConflictResolverAgent)
    agent._llm = MagicMock()
    agent.system_prompt = ""
    agent._history = []
    agent.model = "gpt-4.1"
    agent._backend = "github_models"
    agent._token = None
    return agent


def _make_completed_process(returncode: int, stdout: str = "", stderr: str = "") -> object:
    from unittest.mock import MagicMock
    cp = MagicMock()
    cp.returncode = returncode
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


def test_conflict_resolver_checkout_failure_returns_failed():
    """When git checkout fails, _resolve() should return status='failed'."""
    agent = _make_conflict_agent()

    # Clone succeeds, checkout fails
    def _run_side(cmd, **kwargs):
        if "checkout" in cmd:
            return _make_completed_process(1, stderr="error: pathspec 'feat/x' did not match")
        if "config" in cmd:
            return _make_completed_process(0)
        return _make_completed_process(0)

    agent._run = MagicMock(side_effect=_run_side)

    import tempfile, shutil
    tmpdir = tempfile.mkdtemp()
    try:
        from agents.conflict_resolver import PRContext
        ctx = PRContext(number=1, title="fix", body="", diff="", comments=[])
        result = agent._resolve(tmpdir, "https://github.com/x/y", "feat/x", "master", ctx)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    assert result.status == "failed"
    assert "checkout failed" in result.reason


def test_conflict_resolver_fetch_failure_returns_failed():
    """When git fetch fails, _resolve() should return status='failed'."""
    agent = _make_conflict_agent()

    def _run_side(cmd, **kwargs):
        if "fetch" in cmd:
            return _make_completed_process(1, stderr="fatal: couldn't find remote ref master")
        if "config" in cmd:
            return _make_completed_process(0)
        return _make_completed_process(0)

    agent._run = MagicMock(side_effect=_run_side)

    import tempfile, shutil
    tmpdir = tempfile.mkdtemp()
    try:
        from agents.conflict_resolver import PRContext
        ctx = PRContext(number=1, title="fix", body="", diff="", comments=[])
        result = agent._resolve(tmpdir, "https://github.com/x/y", "feat/x", "master", ctx)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    assert result.status == "failed"
    assert "fetch failed" in result.reason


def test_conflict_resolver_clean_merge_returns_resolved():
    """When merge succeeds with no conflicts, _resolve() returns status='resolved' with empty list."""
    agent = _make_conflict_agent()

    # All git commands succeed, including merge
    agent._run = MagicMock(return_value=_make_completed_process(0))

    import tempfile, shutil
    tmpdir = tempfile.mkdtemp()
    try:
        from agents.conflict_resolver import PRContext
        ctx = PRContext(number=1, title="fix", body="", diff="", comments=[])
        result = agent._resolve(tmpdir, "https://github.com/x/y", "feat/x", "master", ctx)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    assert result.status == "resolved"
    assert result.resolved_files == []
```

- [ ] **Step 2: Run to verify they fail (before any prod changes)**

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t15
python3 -m pytest tests/test_qa_engineer_conflict_resolver.py -v 2>&1 | tail -25
```

Expected: tests run (most should pass immediately since we're testing existing behaviour, not new code). If anything fails, fix the test — do **not** change production code unless you find a real bug.

- [ ] **Step 3: Run full suite to confirm no regressions**

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t15
python3 -m pytest tests/ -q 2>&1 | tail -5
```

Expected: 0 failures.

- [ ] **Step 4: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t15
git add tests/test_qa_engineer_conflict_resolver.py
git commit -m "test: QAEngineerAgent run_with_github + ConflictResolver error paths"
```

---

## Task 3: DocumentationAgent Edge Cases

**Files:**
- Create: `tests/test_documentation_agent_extended.py`

**Context:** `agents/documentation_agent.py` has 13 uncovered lines.
- `_detect_ref` exception handler (returns `"main"` on failure)
- `_build_file_context`: `gh.list_files` raises → warning logged, section skipped
- `_build_file_context`: no `doc_targets` → auto-discover via `gh.search_files`
- `_build_file_context`: `gh.search_files` raises → `paths_to_read = []`
- `_build_file_context`: `gh.get_file_content` returns `None` → `"(does not exist yet — create it)"`
- `run()` JSON fallback: regex finds `[...]` block but inner `json.loads` fails → returns `[]`

- [ ] **Step 1: Write the tests**

Create `tests/test_documentation_agent_extended.py`:

```python
"""Extended tests for DocumentationAgent edge cases."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.documentation_agent import DocumentationAgent


def _make_doc_agent() -> DocumentationAgent:
    agent = DocumentationAgent.__new__(DocumentationAgent)
    agent._llm = MagicMock()
    agent.system_prompt = ""
    agent._history = []
    agent.model = "gpt-4.1"
    agent._backend = "github_models"
    return agent


# ──────────────────────────────────────────────────────────────────────────
# _detect_ref
# ──────────────────────────────────────────────────────────────────────────

def test_detect_ref_falls_back_to_main_on_exception():
    """_detect_ref() must return 'main' when the API call raises."""
    agent = _make_doc_agent()
    mock_gh = MagicMock()
    mock_gh._request.side_effect = RuntimeError("network error")

    result = agent._detect_ref(mock_gh)

    assert result == "main"


def test_detect_ref_returns_default_branch():
    """_detect_ref() returns the repo's default_branch field."""
    agent = _make_doc_agent()
    mock_gh = MagicMock()
    mock_gh._request.return_value = {"default_branch": "develop"}

    result = agent._detect_ref(mock_gh)

    assert result == "develop"


# ──────────────────────────────────────────────────────────────────────────
# _build_file_context
# ──────────────────────────────────────────────────────────────────────────

def test_build_file_context_handles_list_files_exception():
    """_build_file_context() must skip root listing when gh.list_files raises."""
    agent = _make_doc_agent()
    mock_gh = MagicMock()
    mock_gh.list_files.side_effect = RuntimeError("forbidden")
    mock_gh.get_file_content.return_value = "# README"

    result = agent._build_file_context(mock_gh, ["README.md"], ref="main")

    # Should still include file content despite root listing failure
    assert "README.md" in result
    assert "# README" in result


def test_build_file_context_auto_discovers_md_when_no_targets():
    """When doc_targets is empty, _build_file_context() should call gh.search_files."""
    agent = _make_doc_agent()
    mock_gh = MagicMock()
    mock_gh.list_files.return_value = [{"type": "file", "path": "README.md"}]
    mock_gh.search_files.return_value = ["README.md", "CHANGELOG.md"]
    mock_gh.get_file_content.return_value = "# Content"

    result = agent._build_file_context(mock_gh, [], ref="main")

    mock_gh.search_files.assert_called_once()
    assert "README.md" in result


def test_build_file_context_handles_search_files_exception():
    """When gh.search_files raises, paths_to_read should default to []."""
    agent = _make_doc_agent()
    mock_gh = MagicMock()
    mock_gh.list_files.return_value = [{"type": "file", "path": "src"}]
    mock_gh.search_files.side_effect = RuntimeError("search unavailable")

    result = agent._build_file_context(mock_gh, [], ref="main")

    # No file content but also no crash; root listing still present
    assert "Repository root" in result


def test_build_file_context_handles_none_file_content():
    """When gh.get_file_content returns None, include a 'does not exist yet' message."""
    agent = _make_doc_agent()
    mock_gh = MagicMock()
    mock_gh.list_files.return_value = []
    mock_gh.get_file_content.return_value = None

    result = agent._build_file_context(mock_gh, ["docs/missing.md"], ref="main")

    assert "does not exist yet" in result
    assert "docs/missing.md" in result


def test_build_file_context_handles_get_file_content_exception():
    """When gh.get_file_content raises, the file section should be skipped (no crash)."""
    agent = _make_doc_agent()
    mock_gh = MagicMock()
    mock_gh.list_files.return_value = []
    mock_gh.get_file_content.side_effect = RuntimeError("timeout")

    # Should not raise
    result = agent._build_file_context(mock_gh, ["some/file.md"], ref="main")

    assert isinstance(result, str)
```

- [ ] **Step 2: Run to confirm tests pass**

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t15
python3 -m pytest tests/test_documentation_agent_extended.py -v 2>&1 | tail -20
```

Expected: all pass. If any fail, fix the test (check actual method signatures by reading the source file directly).

- [ ] **Step 3: Full suite check**

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t15
python3 -m pytest tests/ -q 2>&1 | tail -5
```

Expected: 0 failures.

- [ ] **Step 4: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t15
git add tests/test_documentation_agent_extended.py
git commit -m "test: DocumentationAgent _detect_ref + _build_file_context edge cases"
```

---

## Task 4: ArchitectAgent + ArchitectReviewerAgent Coverage

**Files:**
- Create: `tests/test_architect_extended.py`

**Context:**
- `agents/architect.py` (10 missing): `run_with_github`, `_call_with_tools_or_fallback` NotImplementedError fallback, `_parse_modules` section-stop (hits `## ` heading without "module") and no-colon item (name without description).
- `agents/architect_reviewer.py` (12 missing): `run_with_github`, `_extract_verdict` APPROVED path (without SUGGESTIONS), `_extract_revised_design` stop-at-next-heading, `_parse_revised_modules` bold `**name**:` format.

- [ ] **Step 1: Write the tests**

Create `tests/test_architect_extended.py`:

```python
"""Extended tests for ArchitectAgent and ArchitectReviewerAgent."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agents.architect import ArchitectAgent
from agents.architect_reviewer import ArchitectReviewerAgent


# ──────────────────────────────────────────────────────────────────────────
# ArchitectAgent
# ──────────────────────────────────────────────────────────────────────────

def _make_architect() -> ArchitectAgent:
    agent = ArchitectAgent.__new__(ArchitectAgent)
    agent._llm = MagicMock()
    agent.system_prompt = ""
    agent._history = []
    agent.model = "gpt-4.1"
    agent._backend = "github_models"
    agent._tool_registry = None
    return agent


def test_architect_run_with_github_posts_comment():
    """run_with_github() should call run() and post the design as an issue comment."""
    agent = _make_architect()
    agent.run = MagicMock(return_value={
        "design": "## System Design\n...",
        "modules": [],
    })
    mock_gh = MagicMock()

    result = agent.run_with_github("PRD text", "MyProject", mock_gh, issue_number=5)

    agent.run.assert_called_once_with("PRD text", "MyProject")
    mock_gh.add_issue_comment.assert_called_once()
    comment = mock_gh.add_issue_comment.call_args[0][1]
    assert "System Design" in comment
    assert result["design"] == "## System Design\n..."


def test_architect_call_with_tools_or_fallback_uses_call_when_notimplementederror():
    """_call_with_tools_or_fallback() must fall back to call() when call_with_tools raises NotImplementedError."""
    agent = _make_architect()
    agent._tool_registry = MagicMock()  # non-None triggers call_with_tools path
    agent.call_with_tools = MagicMock(side_effect=NotImplementedError("not supported"))
    agent.call = MagicMock(return_value="design via plain call")

    result = agent._call_with_tools_or_fallback("design this")

    assert result == "design via plain call"
    agent.call.assert_called_once()


def test_parse_modules_stops_at_next_section_heading():
    """_parse_modules() should stop collecting modules when it hits a non-module '## ' heading."""
    design = """\
## Implementation Modules
1. **auth**: handles auth
2. **db**: stores data

## Other Section
3. **should_not_appear**: ignored
"""
    modules = ArchitectAgent._parse_modules(design)

    names = [m["name"] for m in modules]
    assert "auth" in names
    assert "db" in names
    assert "should_not_appear" not in names


def test_parse_modules_item_without_colon():
    """_parse_modules() should handle a numbered item with no ':' (desc='', tier='senior')."""
    design = """\
## Implementation Modules
1. **simple_module**
"""
    modules = ArchitectAgent._parse_modules(design)

    assert len(modules) == 1
    assert modules[0]["name"] == "simple_module"
    assert modules[0]["description"] == ""
    assert modules[0]["tier"] == "senior"


# ──────────────────────────────────────────────────────────────────────────
# ArchitectReviewerAgent
# ──────────────────────────────────────────────────────────────────────────

def _make_reviewer() -> ArchitectReviewerAgent:
    agent = ArchitectReviewerAgent.__new__(ArchitectReviewerAgent)
    agent._llm = MagicMock()
    agent.system_prompt = ""
    agent._history = []
    agent.model = "gpt-4.1"
    agent._backend = "github_models"
    return agent


def test_architect_reviewer_run_with_github_posts_comment():
    """run_with_github() should call run() and post the review as an issue comment."""
    agent = _make_reviewer()
    agent.run = MagicMock(return_value={
        "review": "All good.",
        "verdict": ArchitectReviewerAgent.VERDICT_APPROVED,
        "revised_design": None,
        "revised_modules": [],
    })
    mock_gh = MagicMock()

    result = agent.run_with_github("design", "PRD", "Proj", mock_gh, issue_number=3)

    mock_gh.add_issue_comment.assert_called_once()
    comment = mock_gh.add_issue_comment.call_args[0][1]
    assert "Design Review" in comment
    # APPROVED verdict should use ✅
    assert "✅" in comment
    assert result["verdict"] == ArchitectReviewerAgent.VERDICT_APPROVED


def test_architect_reviewer_run_with_github_revision_verdict_emoji():
    """run_with_github() should use 🔄 emoji for REVISION verdict."""
    agent = _make_reviewer()
    agent.run = MagicMock(return_value={
        "review": "Needs changes.",
        "verdict": ArchitectReviewerAgent.VERDICT_REVISION,
        "revised_design": None,
        "revised_modules": [],
    })
    mock_gh = MagicMock()

    agent.run_with_github("design", "PRD", "Proj", mock_gh, issue_number=3)

    comment = mock_gh.add_issue_comment.call_args[0][1]
    assert "🔄" in comment


def test_extract_verdict_approved_no_suggestions():
    """_extract_verdict() should return APPROVED for plain 'DESIGN APPROVED' without suggestions."""
    review = "The design looks clean.\n\nDESIGN APPROVED\n"
    verdict = ArchitectReviewerAgent._extract_verdict(review)
    assert verdict == ArchitectReviewerAgent.VERDICT_APPROVED


def test_extract_verdict_approved_with_suggestions():
    """_extract_verdict() should return SUGGESTIONS for 'DESIGN APPROVED WITH SUGGESTIONS'."""
    review = "Mostly fine.\n\nDESIGN APPROVED WITH SUGGESTIONS\n"
    verdict = ArchitectReviewerAgent._extract_verdict(review)
    assert verdict == ArchitectReviewerAgent.VERDICT_SUGGESTIONS


def test_extract_revised_design_stops_at_next_heading():
    """_extract_revised_design() should stop collecting text at the next '## ' heading."""
    review = """\
Some text.

## Revised Design
This is the revised design content.
With multiple lines.

## Some Other Section
Should not be included.
"""
    from agents.architect_reviewer import ArchitectReviewerAgent
    result = ArchitectReviewerAgent._extract_revised_design(review)

    assert "revised design content" in result
    assert "Some Other Section" not in result


def test_parse_revised_modules_bold_colon_format():
    """_parse_revised_modules() should handle '**module_name**: description' bold format."""
    review = """\
## Revised Module List
1. **auth_service**: handles authentication
2. **db_layer**: manages database access
"""
    modules = ArchitectReviewerAgent._parse_revised_modules(review)

    assert len(modules) == 2
    assert modules[0]["name"] == "auth_service"
    assert "authentication" in modules[0]["description"]
    assert modules[1]["name"] == "db_layer"
```

- [ ] **Step 2: Run the tests**

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t15
python3 -m pytest tests/test_architect_extended.py -v 2>&1 | tail -25
```

Expected: all pass. If `_extract_revised_design` isn't a static method on the class, check the import path and adjust.

- [ ] **Step 3: Full suite check**

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t15
python3 -m pytest tests/ -q 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t15
git add tests/test_architect_extended.py
git commit -m "test: ArchitectAgent + ArchitectReviewerAgent run_with_github + static method edge cases"
```

---

## Task 5: BaseAgent Utility Coverage

**Files:**
- Create: `tests/test_base_agent_utilities.py`

**Context:** `agents/base_agent.py` has 34 uncovered lines across utility methods:
- `client` getter/setter non-OAI path (lines 163–177): when `_llm` is not `_OAIBackend`, falls through to `getattr(llm, "_oai_backend", None)`.
- `_anthropic_client` getter/setter (lines 179–195): non-AnthropicBackend fallback paths.
- `_build_backend` paths (lines 290–360): `opencode_zen`, `nvidia_nim`, `opencode`, `anthropic`, `ollama` branches.
- `_call_anthropic` body (lines 386–396): builds messages and calls `llm_pool`.
- `_call_opencode` with `timeout` param (lines 415, 423): the `if timeout is not None` branches.
- `truncate_files` truncation (line 538) and skipped files (lines 559–562): per-file cap and budget overflow.
- `__repr__` (line 570).

- [ ] **Step 1: Write the tests**

Create `tests/test_base_agent_utilities.py`:

```python
"""Tests for BaseAgent utility methods: client properties, _build_backend, _call_anthropic,
_call_opencode timeout path, truncate_files edge cases, and __repr__."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
from contextlib import contextmanager

import pytest

from agents.base_agent import BaseAgent


def _bare_agent() -> BaseAgent:
    """Construct a BaseAgent bypassing __init__."""
    agent = BaseAgent.__new__(BaseAgent)
    agent.model = "gpt-4.1"
    agent._backend = "github_models"
    agent.system_prompt = ""
    agent._history = []
    agent.role_name = None
    return agent


# ──────────────────────────────────────────────────────────────────────────
# client property — non-OAI path
# ──────────────────────────────────────────────────────────────────────────

def test_client_getter_returns_none_when_no_oai_backend():
    """client getter should return None when _llm is not _OAIBackend and has no _oai_backend attr."""
    agent = _bare_agent()
    agent._llm = MagicMock(spec=[])  # no _oai_backend attribute

    assert agent.client is None


def test_client_getter_returns_oai_backend_client():
    """client getter should follow _oai_backend chain when _llm has that attribute."""
    agent = _bare_agent()
    mock_oai = MagicMock()
    mock_oai._client = "inner_client"
    agent._llm = MagicMock(spec=["_oai_backend"])
    agent._llm._oai_backend = mock_oai

    # _llm is not _OAIBackend instance but has _oai_backend
    result = agent.client
    assert result == "inner_client"


def test_client_setter_updates_oai_backend_client():
    """client setter should update _oai_backend._client when _llm is not _OAIBackend."""
    agent = _bare_agent()
    mock_oai = MagicMock()
    agent._llm = MagicMock(spec=["_oai_backend"])
    agent._llm._oai_backend = mock_oai

    agent.client = "new_client"

    assert mock_oai._client == "new_client"


# ──────────────────────────────────────────────────────────────────────────
# _anthropic_client property — non-AnthropicBackend path
# ──────────────────────────────────────────────────────────────────────────

def test_anthropic_client_getter_fallback_returns_none():
    """_anthropic_client getter returns None when _llm lacks _anthropic_client attr."""
    agent = _bare_agent()
    agent._llm = MagicMock(spec=[])  # no _anthropic_client attr

    from agents.backends.anthropic import AnthropicBackend
    # _llm is not AnthropicBackend
    assert not isinstance(agent._llm, AnthropicBackend)
    assert agent._anthropic_client is None


def test_anthropic_client_getter_fallback_returns_attr():
    """_anthropic_client getter delegates to llm._anthropic_client when present."""
    agent = _bare_agent()
    mock_llm = MagicMock(spec=["_anthropic_client"])
    mock_llm._anthropic_client = "anthropic_obj"
    agent._llm = mock_llm

    assert agent._anthropic_client == "anthropic_obj"


def test_anthropic_client_setter_sets_attr_on_llm():
    """_anthropic_client setter should set llm._anthropic_client when llm has that attr."""
    agent = _bare_agent()
    mock_llm = MagicMock(spec=["_anthropic_client"])
    mock_llm._anthropic_client = None
    agent._llm = mock_llm

    agent._anthropic_client = "new_anthropic"

    assert mock_llm._anthropic_client == "new_anthropic"


# ──────────────────────────────────────────────────────────────────────────
# _build_backend — specific backend branches
# ──────────────────────────────────────────────────────────────────────────

def _build(model: str = "gpt-4.1", backend: str | None = None) -> object:
    """Call _build_backend via a full BaseAgent construction to exercise the branch."""
    # Patch each backend constructor so we don't need real credentials
    with (
        patch("agents.backends.opencode_zen.OpenCodeZenBackend") as mock_zen,
        patch("agents.backends.nvidia_nim.NvidiaNimBackend") as mock_nim,
        patch("agents.backends.opencode.OpenCodeBackend") as mock_oc,
        patch("agents.backends.anthropic.AnthropicBackend") as mock_ant,
        patch("agents.backends.ollama.OllamaBackend") as mock_ollama,
        patch("agents.backends.github_models.GitHubModelsBackend") as mock_gh,
        patch("agents.backends.copilot.CopilotBackend") as mock_cop,
        patch("agents.backends.opencode_go.OpenCodeGoBackend") as mock_go,
    ):
        mock_zen.return_value = MagicMock()
        mock_nim.return_value = MagicMock()
        mock_oc.return_value = MagicMock()
        mock_ant.return_value = MagicMock()
        mock_ollama.return_value = MagicMock()
        mock_gh.return_value = MagicMock()
        mock_cop.return_value = MagicMock()
        mock_go.return_value = MagicMock()

        agent = BaseAgent.__new__(BaseAgent)
        result = agent._build_backend(
            model=model,
            github_token=None,
            backend=backend,
            ollama_url="http://localhost:11434",
            ollama_think=False,
            ollama_preserve_thinking=False,
            ollama_stream=False,
            opencode_stream=False,
            github_models_stream=False,
            opencode_zen_api_key=None,
            opencode_zen_base_url=None,
            opencode_go_base_url=None,
            nvidia_nim_api_key=None,
            nvidia_nim_base_url=None,
            retry_delay=1,
            max_api_retries=3,
            inter_call_delay=0,
        )
        return result, mock_zen, mock_nim, mock_oc, mock_ant, mock_ollama, mock_gh


def test_build_backend_opencode_zen():
    """_build_backend() should construct OpenCodeZenBackend when backend='opencode_zen'."""
    result, mock_zen, *_ = _build(backend="opencode_zen")
    mock_zen.assert_called_once()


def test_build_backend_nvidia_nim():
    """_build_backend() should construct NvidiaNimBackend when backend='nvidia_nim'."""
    result, _, mock_nim, *_ = _build(backend="nvidia_nim")
    mock_nim.assert_called_once()


def test_build_backend_opencode():
    """_build_backend() should construct OpenCodeBackend when backend='opencode'."""
    result, _, _, mock_oc, *_ = _build(backend="opencode")
    mock_oc.assert_called_once()


def test_build_backend_anthropic():
    """_build_backend() should construct AnthropicBackend for claude- models."""
    result, _, _, _, mock_ant, *_ = _build(model="claude-opus-4-5")
    mock_ant.assert_called_once()


def test_build_backend_ollama():
    """_build_backend() should construct OllamaBackend when backend='ollama'."""
    result, _, _, _, _, mock_ollama, _ = _build(backend="ollama")
    mock_ollama.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────
# _call_anthropic body
# ──────────────────────────────────────────────────────────────────────────

def _pool_context_manager():
    """Return a mock pool whose acquire() is a working context manager."""
    pool = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=None)
    ctx.__exit__ = MagicMock(return_value=False)
    pool.acquire.return_value = ctx
    return pool


def test_call_anthropic_builds_messages_and_returns_reply():
    """_call_anthropic() should build messages with history and return the llm reply."""
    agent = _bare_agent()
    agent._llm = MagicMock()
    agent._llm.call.return_value = "the reply"
    agent._history = [{"role": "user", "content": "prior"}, {"role": "assistant", "content": "prior reply"}]
    agent._backend = "anthropic"

    mock_pool = _pool_context_manager()

    with patch("llm_pool.get_pool", return_value=mock_pool):
        result = agent._call_anthropic("new prompt")

    assert result == "the reply"
    # Verify the llm was called with a messages list containing prior history + new message
    messages_arg = agent._llm.call.call_args[0][0]
    assert messages_arg[-1] == {"role": "user", "content": "new prompt"}
    assert len(messages_arg) >= 3  # prior user + prior assistant + new user


def test_call_anthropic_records_exchange():
    """_call_anthropic() should update _history after the call."""
    agent = _bare_agent()
    agent._llm = MagicMock()
    agent._llm.call.return_value = "reply"
    agent._history = []
    agent._backend = "anthropic"

    mock_pool = _pool_context_manager()

    with patch("llm_pool.get_pool", return_value=mock_pool):
        agent._call_anthropic("hello")

    assert len(agent._history) == 2
    assert agent._history[0]["role"] == "user"
    assert agent._history[1]["role"] == "assistant"


# ──────────────────────────────────────────────────────────────────────────
# _call_opencode timeout path
# ──────────────────────────────────────────────────────────────────────────

def test_call_opencode_with_timeout_sets_and_restores():
    """_call_opencode(timeout=N) must temporarily set llm._timeout and restore it."""
    agent = _bare_agent()
    mock_llm = MagicMock()
    mock_llm._max_retries = 3
    mock_llm._timeout = 600
    mock_llm.call.return_value = "opencode reply"
    agent._llm = mock_llm
    agent._backend = "opencode"

    mock_pool = _pool_context_manager()

    with patch("llm_pool.get_pool", return_value=mock_pool):
        result = agent._call_opencode("do stuff", timeout=30)

    assert result == "opencode reply"
    # Timeout should be restored to original value
    assert mock_llm._timeout == 600


# ──────────────────────────────────────────────────────────────────────────
# truncate_files — truncation and skipped files
# ──────────────────────────────────────────────────────────────────────────

def test_truncate_files_truncates_content_exceeding_per_file_cap():
    """truncate_files() must truncate file content longer than max_per_file."""
    files = {
        "src/big.py": "x" * 5000,
    }
    result = BaseAgent.truncate_files(files, max_chars=100_000, max_per_file=200)

    assert "big.py" in result
    assert len(result["big.py"]) < 5000
    assert "truncated" in result["big.py"]


def test_truncate_files_adds_summary_when_files_exceed_budget():
    """truncate_files() must add __summary__ key listing skipped files when budget is exceeded."""
    # 3 files, only the first fits within the budget
    files = {
        "src/a.py": "a" * 100,
        "src/b.py": "b" * 100,
        "src/c.py": "c" * 100,
    }
    # Very small budget so b.py and c.py are skipped
    result = BaseAgent.truncate_files(files, max_chars=200, max_per_file=100)

    assert "__summary__" in result
    summary = result["__summary__"]
    assert "omitted" in summary.lower() or "additional" in summary.lower()


def test_truncate_files_all_fit_no_summary():
    """truncate_files() must NOT add __summary__ when all files fit."""
    files = {"src/small.py": "tiny"}
    result = BaseAgent.truncate_files(files, max_chars=100_000)

    assert "__summary__" not in result
    assert "src/small.py" in result


# ──────────────────────────────────────────────────────────────────────────
# __repr__
# ──────────────────────────────────────────────────────────────────────────

def test_repr_includes_class_name_and_model():
    """__repr__() should return a string with the class name and model."""
    agent = _bare_agent()
    r = repr(agent)
    assert "BaseAgent" in r
    assert "gpt-4.1" in r
```

- [ ] **Step 2: Run tests**

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t15
python3 -m pytest tests/test_base_agent_utilities.py -v 2>&1 | tail -35
```

Expected: all pass. The `_build_backend` tests patch at the import path inside each backend module — if any fail with `ModuleNotFoundError`, adjust the patch path to match the actual import location in `_build_backend`.

- [ ] **Step 3: Full suite check**

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t15
python3 -m pytest tests/ -q 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t15
git add tests/test_base_agent_utilities.py
git commit -m "test: BaseAgent client props, _build_backend branches, _call_anthropic, truncate_files, __repr__"
```

---

## Task 6: Small Agents — PMReviewer, CodeReviewer, + Utility Modules

**Files:**
- Create: `tests/test_small_agents_coverage.py`

**Context:**
- `agents/pm_reviewer.py` (5 missing): `run_with_github` (posts issue comment with emoji verdict).
- `agents/code_reviewer.py` (3 missing): `run_with_github` (posts PR review with COMMENT event).
- `skills_loader.py` (33 missing) and `repo_context.py` (18 missing) and `tools/mcp_registry.py` (9 missing): read the source files before writing tests, identify uncovered branches, then write targeted tests.

### Sub-step 6a: PMReviewer + CodeReviewer

- [ ] **Step 1: Write run_with_github tests**

Read the source first to confirm signatures:
```bash
sed -n '58,80p' agents/pm_reviewer.py
sed -n '69,100p' agents/code_reviewer.py
```

Create `tests/test_small_agents_coverage.py`:

```python
"""Coverage tests for PMReviewerAgent, CodeReviewerAgent run_with_github methods."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agents.pm_reviewer import PMReviewerAgent
from agents.code_reviewer import CodeReviewerAgent


# ──────────────────────────────────────────────────────────────────────────
# PMReviewerAgent.run_with_github
# ──────────────────────────────────────────────────────────────────────────

def _make_pm_reviewer() -> PMReviewerAgent:
    agent = PMReviewerAgent.__new__(PMReviewerAgent)
    agent._llm = MagicMock()
    agent.system_prompt = ""
    agent._history = []
    agent.model = "gpt-4.1"
    agent._backend = "github_models"
    return agent


def test_pm_reviewer_run_with_github_approved():
    """run_with_github() with APPROVED verdict should post ✅ comment."""
    agent = _make_pm_reviewer()
    agent.run = MagicMock(return_value={
        "review": "Looks good.",
        "verdict": PMReviewerAgent.VERDICT_APPROVED,
        "revised_prd": None,
    })
    mock_gh = MagicMock()

    result = agent.run_with_github("PRD text", "requirement", "MyProject", mock_gh, issue_number=1)

    mock_gh.add_issue_comment.assert_called_once()
    comment = mock_gh.add_issue_comment.call_args[0][1]
    assert "✅" in comment
    assert "PRD Review" in comment
    assert result["verdict"] == PMReviewerAgent.VERDICT_APPROVED


def test_pm_reviewer_run_with_github_revision():
    """run_with_github() with REVISION verdict should post 🔄 comment."""
    agent = _make_pm_reviewer()
    agent.run = MagicMock(return_value={
        "review": "Needs work.",
        "verdict": PMReviewerAgent.VERDICT_REVISION,
        "revised_prd": None,
    })
    mock_gh = MagicMock()

    agent.run_with_github("PRD text", "requirement", "Proj", mock_gh, issue_number=2)

    comment = mock_gh.add_issue_comment.call_args[0][1]
    assert "🔄" in comment


def test_pm_reviewer_run_with_github_suggestions():
    """run_with_github() with SUGGESTIONS verdict should post 💡 comment."""
    agent = _make_pm_reviewer()
    agent.run = MagicMock(return_value={
        "review": "Minor things.",
        "verdict": PMReviewerAgent.VERDICT_SUGGESTIONS,
        "revised_prd": None,
    })
    mock_gh = MagicMock()

    agent.run_with_github("PRD text", "requirement", "Proj", mock_gh, issue_number=2)

    comment = mock_gh.add_issue_comment.call_args[0][1]
    assert "💡" in comment


# ──────────────────────────────────────────────────────────────────────────
# CodeReviewerAgent.run_with_github
# ──────────────────────────────────────────────────────────────────────────

def _make_code_reviewer() -> CodeReviewerAgent:
    agent = CodeReviewerAgent.__new__(CodeReviewerAgent)
    agent._llm = MagicMock()
    agent.system_prompt = ""
    agent._history = []
    agent.model = "gpt-4.1"
    agent._backend = "github_models"
    agent._tool_registry = None
    return agent


def test_code_reviewer_run_with_github_posts_pr_review():
    """run_with_github() should call add_pr_review with COMMENT event."""
    agent = _make_code_reviewer()
    agent.run = MagicMock(return_value={
        "review": "Code looks good.",
        "verdict": CodeReviewerAgent.VERDICT_APPROVED,
    })
    mock_gh = MagicMock()

    result = agent.run_with_github(
        files={"src/app.py": "x = 1"},
        prd="PRD",
        project_name="App",
        github_client=mock_gh,
        pr_number=10,
    )

    mock_gh.add_pr_review.assert_called_once()
    review_call = mock_gh.add_pr_review.call_args
    assert review_call[1]["event"] == "COMMENT"
    assert "Code Review" in review_call[1]["body"]
    assert result["verdict"] == CodeReviewerAgent.VERDICT_APPROVED
```

### Sub-step 6b: skills_loader, repo_context, mcp_registry

- [ ] **Step 2: Inspect the uncovered files**

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t15
python3 -m pytest tests/ --cov=skills_loader --cov=repo_context --cov=tools/mcp_registry \
    --cov-report=term-missing -q 2>&1 | grep -A 5 "skills_loader\|repo_context\|mcp_registry"
```

This prints the exact missing line numbers. Read those lines in the source:

```bash
cat skills_loader.py | head -80
cat repo_context.py | head -80
cat tools/mcp_registry.py | head -60
```

- [ ] **Step 3: Add targeted tests to `tests/test_small_agents_coverage.py`**

After reading the source, append tests for each uncovered branch. Common patterns to expect:
- `skills_loader.py`: a `SkillsLoader` class (or module-level functions) that reads YAML/JSON from disk. Test: mock `open`/`pathlib.Path.read_text` returning various content, including malformed content (exception path).
- `repo_context.py`: `RepoContext` or similar — test constructor edge cases and methods that query git or GitHub. Mock subprocess/GitHub calls.
- `tools/mcp_registry.py`: MCPRegistry registry — test `register`, `get`, and iteration. Look for branches on duplicate registration or missing-key lookup.

After adding tests, run:

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t15
python3 -m pytest tests/test_small_agents_coverage.py -v 2>&1 | tail -30
```

- [ ] **Step 4: Full suite check**

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t15
python3 -m pytest tests/ -q 2>&1 | tail -5
```

Expected: 0 failures.

- [ ] **Step 5: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t15
git add tests/test_small_agents_coverage.py
git commit -m "test: PMReviewer + CodeReviewer run_with_github + skills_loader/repo_context/mcp_registry edge cases"
```

---

## Task 7: Final Verification + PR

**Files:**
- No new files. Run coverage and open PR.

- [ ] **Step 1: Run full suite with coverage**

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t15
python3 -m pytest tests/ -q --cov=. --cov-report=term-missing 2>&1 | tail -20
```

Expected: ≥88% total coverage, 0 failures.

- [ ] **Step 2: If coverage is below 88%, add more tests**

Re-run coverage and look at the `MISS` columns. Pick the highest-miss files not yet targeted and add tests to the appropriate test file. Commit and re-run.

- [ ] **Step 3: Push branch**

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t15
git push -u origin t15-coverage-runwithgithub-utils
```

- [ ] **Step 4: Open PR**

```bash
gh pr create \
  --title "T15: Coverage sprint — run_with_github, BaseAgent utilities, small modules" \
  --body "Pushes overall coverage from 87% to ≥88%.

## Changes
- New tests for all \`run_with_github\` methods (QAEngineer, Architect, ArchitectReviewer, PMReviewer, CodeReviewer)
- New tests for ConflictResolver error paths (checkout/fetch failure, clean merge)
  
- New tests for DocumentationAgent exception handlers
- New tests for BaseAgent: client/anthropic_client non-OAI paths, _build_backend branches, _call_anthropic, _call_opencode timeout, truncate_files, __repr__
- New tests for skills_loader, repo_context, mcp_registry edge cases

## Coverage
- Before: 87%
- After: ≥88%" \
  --base master \
  --repo wanleung/ai-software-house
```

- [ ] **Step 5: Post coverage summary as PR comment**

```bash
python3 -m pytest tests/ -q --cov=. --cov-report=term-missing 2>&1 \
  | grep -E "TOTAL|agents/|skills_loader|repo_context|mcp_registry" \
  | head -20
```

Copy the relevant lines and post as a PR comment:

```bash
gh pr comment <PR_NUMBER> --body "## Coverage summary
\`\`\`
<paste output here>
\`\`\`"
```
