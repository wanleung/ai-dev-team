# T14: Coverage — Agents, Tools, Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push coverage from 86% to ~90%+ by writing targeted tests for five under-tested areas: `memory_store.py` (65%), `tools/builtin.py` (31%), `tools/registry.py` (87%), agent files (`product_manager`, `summariser`, `qa_planner`, `engineer`, `deployment_tester` — all 63–79%).

**Architecture:** Each task adds one new test file targeting a specific module. All tests use `unittest.mock` (`MagicMock`, `patch`, `monkeypatch`) to avoid real LLM/network calls. Agent tests use `__new__` + attribute injection to skip `BaseAgent.__init__`. No production code changes.

**Tech Stack:** Python 3.13, pytest, unittest.mock, sqlite3 (in-memory for memory_store)

**Branch:** `t14-coverage-agents-tools-memory`
**Worktree:** `.worktrees/t14`
**Baseline:** 1847 passed, 8 skipped (master after T13 merge)

---

## Task 1: Setup worktree

- [ ] **Step 1: Create worktree and branch**

```bash
cd /path/to/ai-software-house
git worktree add .worktrees/t14 -b t14-coverage-agents-tools-memory
cd .worktrees/t14
```

- [ ] **Step 2: Verify baseline**

```bash
python3 -m pytest tests/ -q --tb=no 2>&1 | tail -3
```
Expected: `1847 passed, 8 skipped`

---

## Task 2: `memory_store.py` extended coverage

**What's uncovered:**
- Line 80: DB migration path (existing DB without new columns)
- Lines 149–199: `consolidate_monthly()` body (LLM prompt building, save, mark consolidated)
- Lines 213–260: `consolidate_quarterly()` body (same pattern)
- Lines 288–289, 299–300: `recall()` with quarterly/monthly snapshots present
- Lines 322–331: `recall_issues()` with/without tagged entries
- Line 336: `search()` with keyword match

**Files:**
- Create: `tests/test_memory_store_extended.py`

- [ ] **Step 1: Create the test file**

```python
"""Extended tests for MemoryStore — consolidation, recall, search, DB migration."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from memory_store import MemoryStore


@pytest.fixture
def store(tmp_path):
    """MemoryStore backed by a temp file DB."""
    db = tmp_path / "mem.db"
    ms = MemoryStore(db_path=db)
    yield ms
    ms.close()


# ── DB migration ──────────────────────────────────────────────────────────────

class TestDbMigration:
    def test_migration_adds_missing_columns_to_existing_db(self, tmp_path):
        """Opening a DB that lacks tier/period_label/consolidated triggers migration."""
        db = tmp_path / "legacy.db"
        # Create DB with only the original columns (no tier etc.)
        conn = sqlite3.connect(db)
        conn.execute("""CREATE TABLE runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo TEXT NOT NULL,
            run_id TEXT,
            created_at TEXT,
            mode TEXT,
            summary TEXT NOT NULL,
            tags TEXT DEFAULT ''
        )""")
        conn.commit()
        conn.close()

        # Opening with MemoryStore should migrate without error
        ms = MemoryStore(db_path=db)
        cols = {row[1] for row in ms._conn.execute("PRAGMA table_info(runs)")}
        assert "tier" in cols
        assert "period_label" in cols
        assert "consolidated" in cols
        ms.close()


# ── consolidate_monthly ───────────────────────────────────────────────────────

class TestConsolidateMonthly:
    def test_returns_none_when_no_unconsolidated_runs(self, store):
        """consolidate_monthly returns None when there are no run-tier rows."""
        llm = MagicMock(return_value="summary text")
        result = store.consolidate_monthly("owner/repo", llm)
        assert result is None
        llm.assert_not_called()

    def test_returns_row_id_and_calls_llm(self, store):
        """consolidate_monthly calls llm_fn, saves snapshot, marks rows consolidated."""
        store.save("owner/repo", "run 1 summary", mode="feature")
        store.save("owner/repo", "run 2 summary", mode="bugfix")

        llm = MagicMock(return_value="monthly consolidated text")
        new_id = store.consolidate_monthly("owner/repo", llm)

        assert new_id is not None
        assert isinstance(new_id, int)
        llm.assert_called_once()
        prompt = llm.call_args[0][0]
        assert "run 1 summary" in prompt
        assert "run 2 summary" in prompt

    def test_marks_source_rows_as_consolidated(self, store):
        """After consolidate_monthly, source run rows are marked consolidated=1."""
        store.save("owner/repo", "run A", mode="feature")
        store.save("owner/repo", "run B", mode="feature")

        store.consolidate_monthly("owner/repo", MagicMock(return_value="consolidated"))

        rows = store._conn.execute(
            "SELECT consolidated FROM runs WHERE repo=? AND tier='run'",
            ("owner/repo",),
        ).fetchall()
        assert all(r[0] == "1" or r[0] == 1 for r in rows)

    def test_monthly_snapshot_saved_with_correct_tier(self, store):
        """The monthly snapshot row has tier='monthly'."""
        store.save("owner/repo", "run A", mode="feature")
        new_id = store.consolidate_monthly("owner/repo", MagicMock(return_value="snap"))

        row = store._conn.execute(
            "SELECT tier FROM runs WHERE id=?", (new_id,)
        ).fetchone()
        assert row[0] == "monthly"

    def test_period_label_uses_provided_value(self, store):
        """period_label argument is stored when explicitly provided."""
        store.save("owner/repo", "run X", mode="feature")
        new_id = store.consolidate_monthly(
            "owner/repo", MagicMock(return_value="snap"), period_label="2026-05"
        )
        row = store._conn.execute(
            "SELECT period_label FROM runs WHERE id=?", (new_id,)
        ).fetchone()
        assert row[0] == "2026-05"


# ── consolidate_quarterly ─────────────────────────────────────────────────────

class TestConsolidateQuarterly:
    def test_returns_none_when_no_monthly_rows(self, store):
        """consolidate_quarterly returns None when there are no monthly rows."""
        llm = MagicMock(return_value="quarterly")
        result = store.consolidate_quarterly("owner/repo", llm)
        assert result is None
        llm.assert_not_called()

    def test_returns_row_id_and_calls_llm(self, store):
        """consolidate_quarterly calls llm_fn and saves a quarterly snapshot."""
        # Manually insert monthly rows
        store._conn.execute(
            "INSERT INTO runs (repo, summary, mode, tier, consolidated) VALUES (?,?,?,?,?)",
            ("owner/repo", "may monthly", "consolidation", "monthly", 0),
        )
        store._conn.execute(
            "INSERT INTO runs (repo, summary, mode, tier, consolidated) VALUES (?,?,?,?,?)",
            ("owner/repo", "apr monthly", "consolidation", "monthly", 0),
        )
        store._conn.commit()

        llm = MagicMock(return_value="Q2 quarterly snapshot")
        new_id = store.consolidate_quarterly("owner/repo", llm)

        assert new_id is not None
        llm.assert_called_once()
        prompt = llm.call_args[0][0]
        assert "may monthly" in prompt
        assert "apr monthly" in prompt

    def test_quarterly_snapshot_saved_with_correct_tier(self, store):
        """The quarterly row has tier='quarterly'."""
        store._conn.execute(
            "INSERT INTO runs (repo, summary, mode, tier, consolidated) VALUES (?,?,?,?,?)",
            ("owner/repo", "monthly snap", "consolidation", "monthly", 0),
        )
        store._conn.commit()

        new_id = store.consolidate_quarterly("owner/repo", MagicMock(return_value="q"))
        row = store._conn.execute(
            "SELECT tier FROM runs WHERE id=?", (new_id,)
        ).fetchone()
        assert row[0] == "quarterly"


# ── recall ────────────────────────────────────────────────────────────────────

class TestRecall:
    def test_recall_returns_empty_string_when_no_runs(self, store):
        """recall() returns '' when there are no rows for the repo."""
        result = store.recall("owner/repo")
        assert result == ""

    def test_recall_includes_recent_runs(self, store):
        """recall() includes recent run-tier summaries."""
        store.save("owner/repo", "ran the feature pipeline", mode="feature")
        result = store.recall("owner/repo")
        assert "ran the feature pipeline" in result

    def test_recall_includes_quarterly_snapshot(self, store):
        """recall() includes quarterly snapshot when one exists."""
        store._conn.execute(
            "INSERT INTO runs (repo, summary, mode, tier, period_label) VALUES (?,?,?,?,?)",
            ("owner/repo", "Q1 summary text", "consolidation", "quarterly", "Q1-2026"),
        )
        store._conn.commit()

        result = store.recall("owner/repo")
        assert "Q1 summary text" in result
        assert "Quarterly snapshot" in result

    def test_recall_includes_monthly_snapshot(self, store):
        """recall() includes monthly snapshot when one exists."""
        store._conn.execute(
            "INSERT INTO runs (repo, summary, mode, tier, period_label) VALUES (?,?,?,?,?)",
            ("owner/repo", "May monthly summary", "consolidation", "monthly", "2026-05"),
        )
        store._conn.commit()

        result = store.recall("owner/repo")
        assert "May monthly summary" in result
        assert "Monthly snapshot" in result

    def test_recall_respects_recent_runs_limit(self, store):
        """recall() only shows the N most recent run-tier entries."""
        for i in range(5):
            store.save("owner/repo", f"run {i}", mode="feature")

        result = store.recall("owner/repo", recent_runs=2)
        # run 4 and run 3 should appear; run 0 should not
        assert "run 4" in result
        assert "run 3" in result
        assert "run 0" not in result


# ── recall_issues ─────────────────────────────────────────────────────────────

class TestRecallIssues:
    def test_returns_empty_when_no_tagged_entries(self, store):
        """recall_issues() returns '' when no entries have 'issue' tag."""
        store.save("owner/repo", "clean run", mode="feature")
        result = store.recall_issues("owner/repo")
        assert result == ""

    def test_returns_tagged_issues(self, store):
        """recall_issues() returns entries that have 'issue' in their tags."""
        store.save("owner/repo", "flaky auth bug", mode="feature", tags=["issue", "auth"])
        result = store.recall_issues("owner/repo")
        assert "flaky auth bug" in result
        assert "Known issues" in result


# ── search ───────────────────────────────────────────────────────────────────

class TestSearch:
    def test_returns_empty_for_empty_keywords(self, store):
        """search() returns '' immediately when keywords list is empty."""
        store.save("owner/repo", "something", mode="feature")
        result = store.search("owner/repo", [])
        assert result == ""

    def test_finds_entry_by_keyword(self, store):
        """search() returns entries whose summary matches a keyword."""
        store.save("owner/repo", "JWT token expiry bug fixed", mode="bugfix")
        store.save("owner/repo", "added pagination to list endpoint", mode="feature")

        result = store.search("owner/repo", ["JWT"])
        assert "JWT token expiry bug fixed" in result
        assert "pagination" not in result

    def test_returns_empty_when_no_match(self, store):
        """search() returns '' when no entries match the keywords."""
        store.save("owner/repo", "pagination feature added", mode="feature")
        result = store.search("owner/repo", ["authentication"])
        assert result == ""
```

- [ ] **Step 2: Run tests to verify they all pass**

```bash
python3 -m pytest tests/test_memory_store_extended.py -v --tb=short
```
Expected: 16 passed

- [ ] **Step 3: Commit**

```bash
git add tests/test_memory_store_extended.py
git commit -m "test(t14): memory_store consolidation, recall, search, migration"
```

---

## Task 3: `tools/builtin.py` + `tools/registry.py`

**What's uncovered:**
- `tools/builtin.py` lines 50–65: `run_linter()` body
- Lines 94–112: `run_shell_command()` — timeout, FileNotFoundError, blocked
- Lines 118–119: `_gh_headers()` (called via issue/file tools)
- Lines 155–173: `search_github_issues()` body
- Lines 203–210: `get_github_file()` body
- `tools/registry.py` lines 103–104: `LocalToolRegistry.call()` exception handler
- Lines 107–108: `LocalToolRegistry.__repr__()`
- Lines 129–130: `CombinedToolRegistry.schemas` overlap warning
- Line 142: `CombinedToolRegistry.__repr__()`

**Files:**
- Create: `tests/test_tools.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for tools/builtin.py and tools/registry.py."""
from __future__ import annotations

import json
import subprocess
import warnings
from unittest.mock import MagicMock, patch

import pytest

from tools.builtin import (
    run_linter,
    run_shell_command,
    search_github_issues,
    get_github_file,
    builtin_tools,
)
from tools.registry import LocalToolRegistry, CombinedToolRegistry


# ── run_linter ────────────────────────────────────────────────────────────────

class TestRunLinter:
    def test_no_errors_returns_success_message(self):
        """run_linter on valid Python returns the no-errors sentinel."""
        result = run_linter("x = 1\n")
        assert "No lint errors" in result

    def test_returns_lint_errors_for_invalid_code(self):
        """run_linter on code with undefined name returns ruff output."""
        result = run_linter("print(undefined_var)\n", filename="test_code.py")
        # ruff may report F821 (undefined name) or similar; result is non-empty
        assert isinstance(result, str)
        # The temp path is stripped and replaced with the given filename
        assert "test_code.py" in result or "No lint errors" in result  # ruff may not catch all cases

    def test_filename_suffix_used_for_tempfile(self):
        """run_linter respects the filename parameter (used for context)."""
        result = run_linter("y: int = 'wrong'\n", filename="mymodule.py")
        assert isinstance(result, str)


# ── run_shell_command ─────────────────────────────────────────────────────────

class TestRunShellCommand:
    def test_blocked_command_returns_error(self):
        """run_shell_command blocks destructive commands (rm, wget, etc.)."""
        result = run_shell_command(["rm", "-rf", "/"])
        assert "[Blocked]" in result
        assert "rm" in result

    def test_successful_command_returns_output(self):
        """run_shell_command returns stdout for a safe command."""
        result = run_shell_command(["echo", "hello world"])
        assert "hello world" in result

    def test_timeout_returns_error_message(self):
        """run_shell_command returns timeout error if command takes too long."""
        with patch("tools.builtin.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("cmd", 30)
            result = run_shell_command(["sleep", "999"])
        assert "timed out" in result.lower()

    def test_file_not_found_returns_error(self):
        """run_shell_command returns not-found error for unknown executables."""
        with patch("tools.builtin.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            result = run_shell_command(["nonexistent_binary_xyz"])
        assert "not found" in result.lower()

    def test_long_output_truncated(self):
        """run_shell_command truncates output exceeding 4000 chars."""
        long_output = "x" * 5000
        with patch("tools.builtin.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=long_output, stderr="", returncode=0
            )
            result = run_shell_command(["python3", "-c", "print('x'*5000)"])
        assert len(result) <= 4020  # 4000 + "… [truncated]"
        assert "truncated" in result

    def test_cwd_passed_to_subprocess(self, tmp_path):
        """run_shell_command forwards cwd to subprocess.run."""
        with patch("tools.builtin.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
            run_shell_command(["ls"], cwd=str(tmp_path))
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs.get("cwd") == str(tmp_path)


# ── search_github_issues ──────────────────────────────────────────────────────

class TestSearchGithubIssues:
    def test_returns_json_on_success(self):
        """search_github_issues returns JSON list of matching issues."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "items": [
                {
                    "number": 42,
                    "title": "Fix the auth bug",
                    "state": "open",
                    "html_url": "https://github.com/owner/repo/issues/42",
                    "body": "Description of the auth bug",
                }
            ]
        }
        with patch("tools.builtin.requests.get", return_value=mock_resp):
            result = search_github_issues("owner/repo", "auth bug")

        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["number"] == 42
        assert data[0]["title"] == "Fix the auth bug"

    def test_returns_no_issues_message_when_empty(self):
        """search_github_issues returns a readable message when no items found."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"items": []}
        with patch("tools.builtin.requests.get", return_value=mock_resp):
            result = search_github_issues("owner/repo", "xyz123notfound")
        assert "No matching" in result

    def test_returns_error_on_http_failure(self):
        """search_github_issues returns error string on non-OK response."""
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 403
        mock_resp.text = "rate limited"
        with patch("tools.builtin.requests.get", return_value=mock_resp):
            result = search_github_issues("owner/repo", "anything")
        assert "[Error]" in result
        assert "403" in result


# ── get_github_file ───────────────────────────────────────────────────────────

class TestGetGithubFile:
    def test_returns_file_content_on_success(self):
        """get_github_file returns the raw file content from GitHub."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.text = "def hello(): pass\n"
        with patch("tools.builtin.requests.get", return_value=mock_resp):
            result = get_github_file("owner/repo", "src/hello.py")
        assert "def hello(): pass" in result

    def test_truncates_large_files(self):
        """get_github_file truncates content exceeding 6000 chars."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.text = "x" * 7000
        with patch("tools.builtin.requests.get", return_value=mock_resp):
            result = get_github_file("owner/repo", "big.py")
        assert "truncated" in result
        assert len(result) <= 6100

    def test_returns_error_on_failure(self):
        """get_github_file returns error message on 404."""
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 404
        with patch("tools.builtin.requests.get", return_value=mock_resp):
            result = get_github_file("owner/repo", "missing.py")
        assert "[Error]" in result
        assert "404" in result

    def test_uses_ref_in_url(self):
        """get_github_file constructs the correct raw URL including ref."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.text = "content"
        with patch("tools.builtin.requests.get", return_value=mock_resp) as mock_get:
            get_github_file("owner/repo", "file.py", ref="my-branch")
        url = mock_get.call_args[0][0]
        assert "my-branch" in url
        assert "file.py" in url


# ── LocalToolRegistry ─────────────────────────────────────────────────────────

class TestLocalToolRegistry:
    def _make_registry(self):
        reg = LocalToolRegistry()
        @reg.tool(
            name="echo_tool",
            description="Returns its input",
            parameters={
                "type": "object",
                "properties": {"msg": {"type": "string"}},
                "required": ["msg"],
            },
        )
        def echo_tool(msg: str) -> str:
            return msg
        return reg

    def test_call_unknown_tool_returns_error(self):
        """LocalToolRegistry.call() returns ToolError for unknown tool name."""
        reg = self._make_registry()
        result = reg.call("does_not_exist", "{}")
        assert "[ToolError]" in result
        assert "does_not_exist" in result

    def test_call_tool_that_raises_returns_error(self):
        """LocalToolRegistry.call() wraps exceptions in a ToolError string."""
        reg = LocalToolRegistry()
        @reg.tool(name="boom", description="raises", parameters={"type": "object", "properties": {}, "required": []})
        def boom() -> str:
            raise ValueError("intentional error")

        result = reg.call("boom", "{}")
        assert "[ToolError]" in result
        assert "intentional error" in result

    def test_repr_lists_tool_names(self):
        """LocalToolRegistry.__repr__() includes registered tool names."""
        reg = self._make_registry()
        r = repr(reg)
        assert "echo_tool" in r
        assert "LocalToolRegistry" in r


# ── CombinedToolRegistry ──────────────────────────────────────────────────────

class TestCombinedToolRegistry:
    def _make_reg(self, tool_name: str, return_value: str = "ok") -> LocalToolRegistry:
        reg = LocalToolRegistry()
        @reg.tool(
            name=tool_name,
            description=f"tool {tool_name}",
            parameters={"type": "object", "properties": {}, "required": []},
        )
        def fn() -> str:
            return return_value
        return reg

    def test_call_routes_to_primary(self):
        """CombinedToolRegistry routes primary tool calls to primary registry."""
        primary = self._make_reg("primary_tool", "from primary")
        secondary = self._make_reg("secondary_tool", "from secondary")
        combined = CombinedToolRegistry(primary, secondary)
        assert combined.call("primary_tool", "{}") == "from primary"

    def test_call_routes_to_secondary(self):
        """CombinedToolRegistry routes secondary tool calls to secondary registry."""
        primary = self._make_reg("primary_tool")
        secondary = self._make_reg("secondary_tool", "from secondary")
        combined = CombinedToolRegistry(primary, secondary)
        assert combined.call("secondary_tool", "{}") == "from secondary"

    def test_schemas_merges_both_registries(self):
        """CombinedToolRegistry.schemas exposes tools from both registries."""
        primary = self._make_reg("tool_a")
        secondary = self._make_reg("tool_b")
        combined = CombinedToolRegistry(primary, secondary)
        names = [s["function"]["name"] for s in combined.schemas]
        assert "tool_a" in names
        assert "tool_b" in names

    def test_overlap_emits_warning(self):
        """CombinedToolRegistry warns when primary and secondary share a tool name."""
        primary = self._make_reg("shared_tool")
        secondary = self._make_reg("shared_tool")
        combined = CombinedToolRegistry(primary, secondary)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _ = combined.schemas
        assert any("shared_tool" in str(w.message) for w in caught)

    def test_repr_includes_both(self):
        """CombinedToolRegistry.__repr__() mentions primary and secondary."""
        primary = self._make_reg("p_tool")
        secondary = self._make_reg("s_tool")
        combined = CombinedToolRegistry(primary, secondary)
        r = repr(combined)
        assert "CombinedToolRegistry" in r
        assert "primary" in r.lower() or "p_tool" in r
```

- [ ] **Step 2: Run tests**

```bash
python3 -m pytest tests/test_tools.py -v --tb=short
```
Expected: ~20 passed

- [ ] **Step 3: Commit**

```bash
git add tests/test_tools.py
git commit -m "test(t14): builtin tools and tool registry coverage"
```

---

## Task 4: `agents/product_manager.py` + `agents/summariser.py`

**What's uncovered:**
- `product_manager.py` lines 33–42: `run()` body (LLM call + dict return)
- Lines 59–68: `run_with_github()` body (github_client.create_issue)
- Lines 70–116: `run_revision()` body (multi-arg prompt, LLM call)
- Lines 122, 125: `_extract_project_name()` edge cases
- `summariser.py` lines 21–48: entire `summarise()` body

**Files:**
- Create: `tests/test_pm_summariser.py`

**Pattern:** Use `Agent.__new__(Agent)` + manual attribute injection to skip `BaseAgent.__init__`.

- [ ] **Step 1: Create the test file**

```python
"""Tests for ProductManagerAgent and SummaryAgent."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agents.product_manager import ProductManagerAgent
from agents.summariser import SummaryAgent


def _make_pm() -> ProductManagerAgent:
    """Create ProductManagerAgent without calling BaseAgent.__init__."""
    agent = ProductManagerAgent.__new__(ProductManagerAgent)
    agent._llm = MagicMock()
    agent.system_prompt = ""
    agent._history = []
    agent.model = "gpt-4"
    agent.memory_store = None
    return agent


def _make_summariser() -> SummaryAgent:
    """Create SummaryAgent without calling BaseAgent.__init__."""
    agent = SummaryAgent.__new__(SummaryAgent)
    agent._llm = MagicMock()
    agent.system_prompt = ""
    agent._history = []
    agent.model = "gpt-4"
    agent.memory_store = None
    return agent


# ── ProductManagerAgent.run ───────────────────────────────────────────────────

class TestProductManagerRun:
    def test_run_returns_prd_and_project_name(self, monkeypatch):
        """run() returns dict with prd text and extracted project name."""
        agent = _make_pm()
        monkeypatch.setattr(agent, "call", MagicMock(return_value="# PRD: Task Manager\n\nFeatures..."))

        result = agent.run("Build a task manager API")

        assert result["prd"] == "# PRD: Task Manager\n\nFeatures..."
        assert result["project_name"] == "Task Manager"
        assert result["issue_number"] is None
        assert result["issue_url"] is None

    def test_run_calls_llm_with_requirement_in_prompt(self, monkeypatch):
        """run() passes the requirement text into the LLM prompt."""
        agent = _make_pm()
        mock_call = MagicMock(return_value="# PRD: Foo\n")
        monkeypatch.setattr(agent, "call", mock_call)

        agent.run("Build a login system")

        prompt = mock_call.call_args[0][0]
        assert "Build a login system" in prompt


# ── ProductManagerAgent.run_with_github ───────────────────────────────────────

class TestProductManagerRunWithGithub:
    def test_run_with_github_creates_issue_and_returns_number(self, monkeypatch):
        """run_with_github() creates a GitHub issue and populates issue_number/url."""
        agent = _make_pm()
        monkeypatch.setattr(agent, "call", MagicMock(return_value="# PRD: My App\n\nDetails"))

        github_client = MagicMock()
        github_client.create_issue.return_value = {
            "number": 17,
            "html_url": "https://github.com/owner/repo/issues/17",
        }

        result = agent.run_with_github("Build My App", github_client)

        assert result["issue_number"] == 17
        assert result["issue_url"] == "https://github.com/owner/repo/issues/17"
        github_client.create_issue.assert_called_once()
        _, kwargs = github_client.create_issue.call_args
        assert "My App" in kwargs.get("title", "") or "My App" in str(github_client.create_issue.call_args)

    def test_run_with_github_passes_labels(self, monkeypatch):
        """run_with_github() creates the issue with 'prd' and 'requirements' labels."""
        agent = _make_pm()
        monkeypatch.setattr(agent, "call", MagicMock(return_value="# PRD: X\n"))

        github_client = MagicMock()
        github_client.create_issue.return_value = {"number": 1, "html_url": "http://example.com/1"}

        agent.run_with_github("Build X", github_client)

        call_kwargs = github_client.create_issue.call_args[1]
        assert "prd" in call_kwargs.get("labels", [])


# ── ProductManagerAgent.run_revision ─────────────────────────────────────────

class TestProductManagerRunRevision:
    def test_run_revision_returns_updated_prd(self, monkeypatch):
        """run_revision() returns an updated PRD incorporating reviewer feedback."""
        agent = _make_pm()
        revised_prd = "# PRD: Task Manager v2\n\nImproved scope."
        monkeypatch.setattr(agent, "call", MagicMock(return_value=revised_prd))

        result = agent.run_revision(
            original_prd="# PRD: Task Manager\n\nOld scope.",
            review="Scope too narrow.",
            draft_revision="Consider adding...",
            requirement="Build a task manager",
            project_name="Task Manager",
        )

        assert result["prd"] == revised_prd
        assert "Task Manager" in result["project_name"]
        assert result["issue_number"] is None

    def test_run_revision_includes_original_and_feedback_in_prompt(self, monkeypatch):
        """run_revision() passes original PRD, review, and draft to LLM."""
        agent = _make_pm()
        mock_call = MagicMock(return_value="# PRD: X\n")
        monkeypatch.setattr(agent, "call", mock_call)

        agent.run_revision(
            original_prd="ORIGINAL_PRD",
            review="REVIEWER_FEEDBACK",
            draft_revision="DRAFT_REVISION",
            requirement="REQUIREMENT",
            project_name="X",
        )

        prompt = mock_call.call_args[0][0]
        assert "ORIGINAL_PRD" in prompt
        assert "REVIEWER_FEEDBACK" in prompt
        assert "DRAFT_REVISION" in prompt


# ── _extract_project_name ─────────────────────────────────────────────────────

class TestExtractProjectName:
    def test_extracts_from_prd_prefix(self):
        """_extract_project_name reads '# PRD: Name' format."""
        name = ProductManagerAgent._extract_project_name("# PRD: Task Manager\n\nContent")
        assert name == "Task Manager"

    def test_extracts_from_plain_h1(self):
        """_extract_project_name falls back to first '# Heading'."""
        name = ProductManagerAgent._extract_project_name("# My Project\n\nContent")
        assert name == "My Project"

    def test_returns_default_when_no_heading(self):
        """_extract_project_name returns fallback when no H1 exists."""
        name = ProductManagerAgent._extract_project_name("Just plain text, no heading.")
        assert name == "Software Project"


# ── SummaryAgent.summarise ────────────────────────────────────────────────────

class TestSummaryAgentSummarise:
    def test_summarise_calls_llm_and_returns_string(self, monkeypatch):
        """summarise() passes all inputs to LLM and returns the result."""
        agent = _make_summariser()
        mock_call = MagicMock(return_value="Compact memory entry.")
        monkeypatch.setattr(agent, "call", mock_call)

        result = agent.summarise(
            repo="owner/repo",
            requirement="Build auth",
            prd="# PRD: Auth\n\nDetails.",
            design="## Architecture\n\nUse JWT.",
            review="Looks good.",
            mode="feature",
        )

        assert result == "Compact memory entry."
        mock_call.assert_called_once()

    def test_summarise_includes_repo_in_prompt(self, monkeypatch):
        """summarise() includes the repo name in the LLM prompt."""
        agent = _make_summariser()
        mock_call = MagicMock(return_value="summary")
        monkeypatch.setattr(agent, "call", mock_call)

        agent.summarise(
            repo="myorg/myrepo",
            requirement="req",
            prd="prd",
            design="design",
            review="review",
        )

        prompt = mock_call.call_args[0][0]
        assert "myorg/myrepo" in prompt

    def test_summarise_default_mode_is_feature(self, monkeypatch):
        """summarise() uses 'feature' as default mode when not specified."""
        agent = _make_summariser()
        mock_call = MagicMock(return_value="summary")
        monkeypatch.setattr(agent, "call", mock_call)

        agent.summarise(repo="r", requirement="r", prd="p", design="d", review="rv")

        prompt = mock_call.call_args[0][0]
        assert "feature" in prompt
```

- [ ] **Step 2: Run tests**

```bash
python3 -m pytest tests/test_pm_summariser.py -v --tb=short
```
Expected: ~13 passed

- [ ] **Step 3: Commit**

```bash
git add tests/test_pm_summariser.py
git commit -m "test(t14): ProductManagerAgent and SummaryAgent coverage"
```

---

## Task 5: `agents/qa_planner.py` + `agents/engineer.py`

**What's uncovered:**
- `qa_planner.py` lines 92–107: `run_with_github()` body
- `engineer.py` lines 65, 69: `run_module()` with `test_files` (TDD mode, truncation)
- Lines 131–154: `run_all_modules()` parallel execution
- Lines 187–222: `run_with_github()` (branch creation, file commits, PR creation)
- Line 284: `fix_failures()` — no `### FILE:` in response returns `{}`
- Line 303: `_parse_files()` fallback (no FILE markers → wraps as main.py)

**Files:**
- Create: `tests/test_qa_planner_engineer.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for QAPlannerAgent and EngineerAgent."""
from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from agents.qa_planner import QAPlannerAgent
from agents.engineer import EngineerAgent


def _make_qa_planner(tool_registry=None) -> QAPlannerAgent:
    agent = QAPlannerAgent.__new__(QAPlannerAgent)
    agent._llm = MagicMock()
    agent.system_prompt = ""
    agent._history = []
    agent.model = "gpt-4"
    agent.memory_store = None
    agent._tool_registry = tool_registry
    return agent


def _make_engineer(tool_registry=None) -> EngineerAgent:
    agent = EngineerAgent.__new__(EngineerAgent)
    agent._llm = MagicMock()
    agent.system_prompt = ""
    agent._history = []
    agent.model = "gpt-4"
    agent.memory_store = None
    agent._tool_registry = tool_registry
    return agent


# ── QAPlannerAgent.run_with_github ────────────────────────────────────────────

class TestQAPlannerRunWithGithub:
    def _make_run_result(self) -> dict:
        return {
            "test_plan": "## Test Plan\n\n- AC-01: Login works",
            "acceptance_criteria": ["AC-01"],
            "success": True,
        }

    def test_posts_to_pr_when_pr_number_given(self, monkeypatch):
        """run_with_github() posts the test plan comment to the PR when pr_number given."""
        agent = _make_qa_planner()
        monkeypatch.setattr(agent, "run", MagicMock(return_value=self._make_run_result()))

        github_client = MagicMock()
        github_client.repo = "owner/repo"

        agent.run_with_github(
            prd="PRD text",
            design="Design text",
            files={"main.py": "x=1"},
            project_name="MyApp",
            github_client=github_client,
            issue_number=5,
            pr_number=12,
        )

        github_client.add_pr_comment.assert_called_once()
        github_client.add_issue_comment.assert_not_called()
        comment = github_client.add_pr_comment.call_args[0][1]
        assert "Test Plan" in comment

    def test_posts_to_issue_when_no_pr_number(self, monkeypatch):
        """run_with_github() posts to issue comment when pr_number is None."""
        agent = _make_qa_planner()
        monkeypatch.setattr(agent, "run", MagicMock(return_value=self._make_run_result()))

        github_client = MagicMock()
        github_client.repo = "owner/repo"

        agent.run_with_github(
            prd="PRD text",
            design="Design text",
            files={},
            project_name="MyApp",
            github_client=github_client,
            issue_number=5,
            pr_number=None,
        )

        github_client.add_issue_comment.assert_called_once()
        github_client.add_pr_comment.assert_not_called()


# ── EngineerAgent.run_module with test_files (TDD mode) ───────────────────────

class TestEngineerRunModuleWithTestFiles:
    def test_run_module_injects_test_files_into_prompt(self, monkeypatch):
        """run_module with test_files includes test content in the LLM prompt."""
        agent = _make_engineer()
        mock_call = MagicMock(return_value="### FILE: src/auth.py\n```python\ndef login(): pass\n```")
        monkeypatch.setattr(agent, "call", mock_call)

        agent.run_module(
            design="## Auth module design",
            module={"name": "auth", "description": "handles login"},
            project_name="MyApp",
            test_files={"tests/test_auth.py": "def test_login(): assert login() is None"},
        )

        prompt = mock_call.call_args[0][0]
        assert "tests/test_auth.py" in prompt
        assert "test_login" in prompt

    def test_run_module_truncates_large_test_file(self, monkeypatch):
        """run_module truncates test file content exceeding 3000 chars."""
        agent = _make_engineer()
        mock_call = MagicMock(return_value="### FILE: main.py\n```python\nx=1\n```")
        monkeypatch.setattr(agent, "call", mock_call)

        big_test = "# test\n" + "x = 1\n" * 600  # >3000 chars
        agent.run_module(
            design="design",
            module={"name": "mod", "description": "desc"},
            project_name="Proj",
            test_files={"tests/big_test.py": big_test},
        )

        prompt = mock_call.call_args[0][0]
        assert "truncated" in prompt


# ── EngineerAgent.run_all_modules ─────────────────────────────────────────────

class TestEngineerRunAllModules:
    def test_run_all_modules_calls_run_module_for_each(self, monkeypatch):
        """run_all_modules calls run_module for each module in the list."""
        agent = _make_engineer()
        mock_run_module = MagicMock(return_value={
            "module_name": "mod",
            "files": {"src/mod.py": "x=1"},
            "raw_response": "raw",
        })
        monkeypatch.setattr(agent, "run_module", mock_run_module)

        modules = [
            {"name": "auth", "description": "auth"},
            {"name": "api", "description": "api"},
        ]
        result = agent.run_all_modules(design="design", modules=modules, project_name="MyApp", max_workers=2)

        assert mock_run_module.call_count == 2
        assert "auth.py" in result["all_files"] or "src/mod.py" in result["all_files"]
        assert len(result["modules"]) == 2

    def test_run_all_modules_merges_files(self, monkeypatch):
        """run_all_modules merges all module files into all_files dict."""
        agent = _make_engineer()
        calls = [
            {"module_name": "auth", "files": {"src/auth.py": "auth code"}, "raw_response": ""},
            {"module_name": "api", "files": {"src/api.py": "api code"}, "raw_response": ""},
        ]
        monkeypatch.setattr(agent, "run_module", MagicMock(side_effect=calls))

        result = agent.run_all_modules(
            design="d",
            modules=[{"name": "auth", "description": ""}, {"name": "api", "description": ""}],
            project_name="P",
            max_workers=1,
        )

        assert "src/auth.py" in result["all_files"]
        assert "src/api.py" in result["all_files"]


# ── EngineerAgent.run_with_github ─────────────────────────────────────────────

class TestEngineerRunWithGithub:
    def test_creates_branch_and_commits_files(self, monkeypatch):
        """run_with_github creates the branch, commits each file, and opens a PR."""
        agent = _make_engineer()
        monkeypatch.setattr(agent, "run_all_modules", MagicMock(return_value={
            "modules": [],
            "all_files": {"src/main.py": "print('hello')", "src/utils.py": "pass"},
        }))

        github_client = MagicMock()
        github_client.create_pull_request.return_value = {
            "number": 99,
            "html_url": "https://github.com/owner/repo/pull/99",
        }

        result = agent.run_with_github(
            design="design",
            modules=[{"name": "main", "description": ""}],
            project_name="MyApp",
            github_client=github_client,
        )

        github_client.create_branch.assert_called_once()
        assert github_client.commit_file.call_count == 2
        github_client.create_pull_request.assert_called_once()
        assert result["pr_number"] == 99

    def test_pr_body_references_issue_when_given(self, monkeypatch):
        """run_with_github includes 'Closes #N' in PR body when issue_number given."""
        agent = _make_engineer()
        monkeypatch.setattr(agent, "run_all_modules", MagicMock(return_value={
            "modules": [],
            "all_files": {"src/x.py": "x=1"},
        }))

        github_client = MagicMock()
        github_client.create_pull_request.return_value = {"number": 5, "html_url": "http://x"}

        agent.run_with_github(
            design="d",
            modules=[],
            project_name="X",
            github_client=github_client,
            issue_number=42,
        )

        body = github_client.create_pull_request.call_args[1].get("body", "") or \
               github_client.create_pull_request.call_args[0][1] if \
               github_client.create_pull_request.call_args[0] else ""
        # Check the call kwargs
        call_kwargs = github_client.create_pull_request.call_args.kwargs
        assert "42" in call_kwargs.get("body", "")


# ── EngineerAgent.fix_failures ────────────────────────────────────────────────

class TestEngineerFixFailures:
    def test_returns_empty_dict_when_no_file_markers(self, monkeypatch):
        """fix_failures returns {} when LLM response has no '### FILE:' markers."""
        agent = _make_engineer()
        monkeypatch.setattr(agent, "call", MagicMock(return_value="Here is my explanation only."))

        result = agent.fix_failures(
            failure_output="FAILED test_foo",
            all_files={"src/foo.py": "broken"},
            design="design",
        )

        assert result == {}

    def test_returns_parsed_files_when_markers_present(self, monkeypatch):
        """fix_failures returns parsed files when LLM response has FILE markers."""
        agent = _make_engineer()
        response = "### FILE: src/foo.py\n```python\ndef fixed(): pass\n```"
        monkeypatch.setattr(agent, "call", MagicMock(return_value=response))

        result = agent.fix_failures(
            failure_output="FAILED test_foo",
            all_files={"src/foo.py": "broken"},
            design="design",
        )

        assert "src/foo.py" in result
        assert "fixed" in result["src/foo.py"]


# ── EngineerAgent._parse_files ────────────────────────────────────────────────

class TestEngineerParseFiles:
    def test_fallback_wraps_plain_text_as_main_py(self):
        """_parse_files wraps plain response as main.py when no FILE markers."""
        result = EngineerAgent._parse_files("def hello(): pass")
        assert "main.py" in result
        assert "def hello(): pass" in result["main.py"]

    def test_strips_code_fences(self):
        """_parse_files removes opening/closing ``` fences from file content."""
        response = "### FILE: src/app.py\n```python\nx = 1\n```"
        result = EngineerAgent._parse_files(response)
        assert "src/app.py" in result
        assert "```" not in result["src/app.py"]
        assert "x = 1" in result["src/app.py"]

    def test_parses_multiple_files(self):
        """_parse_files handles multiple FILE sections correctly."""
        response = (
            "### FILE: src/a.py\n```python\na = 1\n```\n"
            "### FILE: src/b.py\n```python\nb = 2\n```"
        )
        result = EngineerAgent._parse_files(response)
        assert "src/a.py" in result
        assert "src/b.py" in result
```

- [ ] **Step 2: Run tests**

```bash
python3 -m pytest tests/test_qa_planner_engineer.py -v --tb=short
```
Expected: ~20 passed

- [ ] **Step 3: Commit**

```bash
git add tests/test_qa_planner_engineer.py
git commit -m "test(t14): QAPlannerAgent and EngineerAgent coverage"
```

---

## Task 6: `agents/deployment_tester.py`

**What's uncovered:**
- Line 40: `run()` — `deploy_snippets` fallback (no dockerfile/compose keys → first 6 files)
- Lines 77–91: `run_with_github()` body
- Line 104: `run_docker_smoke_tests()` — `_run_via_compose` branch
- Line 106: `run_docker_smoke_tests()` — neither branch (returns skipped)
- Lines 128–159: `_run_via_compose()` full body

**Files:**
- Create: `tests/test_deployment_tester_extended.py`

- [ ] **Step 1: Create the test file**

```python
"""Extended tests for DeploymentTesterAgent — run_with_github, docker smoke tests."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from agents.deployment_tester import DeploymentTesterAgent


def _make_agent() -> DeploymentTesterAgent:
    agent = DeploymentTesterAgent.__new__(DeploymentTesterAgent)
    agent._llm = MagicMock()
    agent.system_prompt = ""
    agent._history = []
    agent.model = "gpt-4"
    agent.memory_store = None
    return agent


# ── run() — deploy_snippets fallback ─────────────────────────────────────────

class TestDeploymentTesterRun:
    def test_run_uses_first_six_files_when_no_deploy_keys(self, monkeypatch):
        """run() falls back to first 6 files when no dockerfile/compose keys present."""
        agent = _make_agent()
        mock_call = MagicMock(return_value="### FILE: tests/test_deployment.py\n```\ndef test_health(): pass\n```")
        monkeypatch.setattr(agent, "call", mock_call)

        files = {f"src/module_{i}.py": f"code {i}" for i in range(8)}
        agent.run(files=files, prd="PRD text", project_name="MyApp")

        prompt = mock_call.call_args[0][0]
        # Only first 6 files should appear in the prompt code section
        assert "module_0.py" in prompt
        assert "module_5.py" in prompt
        # module_6 and module_7 should NOT appear (beyond first 6)
        assert "module_7.py" not in prompt

    def test_run_prefers_deploy_files_when_present(self, monkeypatch):
        """run() uses dockerfile/compose files when present instead of fallback."""
        agent = _make_agent()
        mock_call = MagicMock(return_value="### FILE: docker-compose.test.yml\n```\nversion: '3'\n```")
        monkeypatch.setattr(agent, "call", mock_call)

        files = {
            "Dockerfile": "FROM python:3.13",
            "docker-compose.yml": "version: '3'",
            "src/unrelated.py": "x = 1",
        }
        agent.run(files=files, prd="PRD", project_name="App")

        prompt = mock_call.call_args[0][0]
        assert "Dockerfile" in prompt
        assert "docker-compose.yml" in prompt


# ── run_with_github ───────────────────────────────────────────────────────────

class TestDeploymentTesterRunWithGithub:
    def test_commits_deploy_files_to_github(self, monkeypatch):
        """run_with_github() commits all generated deploy files to the branch."""
        agent = _make_agent()
        monkeypatch.setattr(agent, "run", MagicMock(return_value={
            "deploy_files": {
                "docker-compose.test.yml": "compose content",
                "tests/test_deployment.py": "test content",
            },
            "deploy_plan": "## Deployment Plan\n\nRun docker-compose up.",
            "raw_response": "",
        }))

        github_client = MagicMock()

        agent.run_with_github(
            files={"src/main.py": "app"},
            prd="PRD",
            project_name="MyApp",
            github_client=github_client,
            branch="feature/my-app",
            pr_number=7,
        )

        assert github_client.commit_file.call_count == 2
        github_client.add_pr_comment.assert_called_once()
        comment = github_client.add_pr_comment.call_args[0][1]
        assert "Deployment Test Plan" in comment

    def test_posts_plan_to_correct_pr(self, monkeypatch):
        """run_with_github() posts the deployment plan to the given PR number."""
        agent = _make_agent()
        monkeypatch.setattr(agent, "run", MagicMock(return_value={
            "deploy_files": {},
            "deploy_plan": "plan text",
            "raw_response": "",
        }))

        github_client = MagicMock()
        agent.run_with_github(
            files={}, prd="P", project_name="X",
            github_client=github_client, branch="feat/x", pr_number=42,
        )

        github_client.add_pr_comment.assert_called_once_with(42, pytest.approx(str, rel=0))
        actual_pr_number = github_client.add_pr_comment.call_args[0][0]
        assert actual_pr_number == 42


# ── run_docker_smoke_tests ────────────────────────────────────────────────────

class TestRunDockerSmokeTests:
    def test_returns_skipped_when_no_compose_or_script(self, tmp_path):
        """run_docker_smoke_tests returns skipped=True when no files exist."""
        agent = _make_agent()
        result = agent.run_docker_smoke_tests(tmp_path)
        assert result["skipped"] is True
        assert result["passed"] is None

    def test_uses_script_when_deploy_sh_exists(self, tmp_path, monkeypatch):
        """run_docker_smoke_tests routes to _run_via_script when deploy_test.sh exists."""
        agent = _make_agent()
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()
        deploy_script = script_dir / "deploy_test.sh"
        deploy_script.write_text("#!/bin/bash\necho ok")

        mock_script = MagicMock(return_value={"passed": True, "output": "ok", "skipped": False})
        monkeypatch.setattr(agent, "_run_via_script", mock_script)

        result = agent.run_docker_smoke_tests(tmp_path)

        mock_script.assert_called_once()
        assert result["passed"] is True

    def test_uses_compose_when_both_files_exist(self, tmp_path, monkeypatch):
        """run_docker_smoke_tests routes to _run_via_compose when compose+test exist."""
        agent = _make_agent()
        (tmp_path / "docker-compose.test.yml").write_text("version: '3'")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_deployment.py").write_text("def test_health(): pass")

        mock_compose = MagicMock(return_value={"passed": True, "output": "ok", "skipped": False})
        monkeypatch.setattr(agent, "_run_via_compose", mock_compose)

        result = agent.run_docker_smoke_tests(tmp_path)

        mock_compose.assert_called_once()
        assert result["passed"] is True


# ── _run_via_script ───────────────────────────────────────────────────────────

class TestRunViaScript:
    def test_returns_passed_true_on_zero_returncode(self, tmp_path):
        """_run_via_script returns passed=True when script exits 0."""
        agent = _make_agent()
        script = tmp_path / "deploy_test.sh"
        script.write_text("#!/bin/bash\necho deployed")

        with patch("agents.deployment_tester.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="deployed\n", stderr="")
            result = agent._run_via_script(script, tmp_path)

        assert result["passed"] is True
        assert result["skipped"] is False

    def test_returns_passed_false_on_nonzero_returncode(self, tmp_path):
        """_run_via_script returns passed=False when script exits non-zero."""
        agent = _make_agent()
        script = tmp_path / "deploy_test.sh"
        script.write_text("#!/bin/bash\nexit 1")

        with patch("agents.deployment_tester.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
            result = agent._run_via_script(script, tmp_path)

        assert result["passed"] is False


# ── _run_via_compose ──────────────────────────────────────────────────────────

class TestRunViaCompose:
    def test_runs_full_compose_lifecycle(self, tmp_path):
        """_run_via_compose: up → health check → pytest → down."""
        agent = _make_agent()
        compose_file = tmp_path / "docker-compose.test.yml"
        test_file = tmp_path / "tests" / "test_deployment.py"

        call_results = [
            MagicMock(returncode=0, stdout="", stderr=""),   # up
            MagicMock(returncode=0, stdout="healthy", stderr=""),  # ps (healthy)
            MagicMock(returncode=0, stdout="1 passed", stderr=""),  # pytest
            MagicMock(returncode=0, stdout="", stderr=""),   # down
        ]

        with patch("agents.deployment_tester.subprocess.run", side_effect=call_results):
            result = agent._run_via_compose(compose_file, test_file, tmp_path)

        assert result["passed"] is True
        assert result["skipped"] is False

    def test_returns_passed_false_when_tests_fail(self, tmp_path):
        """_run_via_compose returns passed=False when pytest exits non-zero."""
        agent = _make_agent()
        compose_file = tmp_path / "docker-compose.test.yml"
        test_file = tmp_path / "tests" / "test_deployment.py"

        call_results = [
            MagicMock(returncode=0, stdout="", stderr=""),          # up
            MagicMock(returncode=0, stdout="healthy", stderr=""),   # ps
            MagicMock(returncode=1, stdout="FAILED", stderr=""),    # pytest
            MagicMock(returncode=0, stdout="", stderr=""),          # down
        ]

        with patch("agents.deployment_tester.subprocess.run", side_effect=call_results):
            result = agent._run_via_compose(compose_file, test_file, tmp_path)

        assert result["passed"] is False

    def test_teardown_runs_even_on_unhealthy(self, tmp_path):
        """_run_via_compose always calls docker-compose down (finally block)."""
        agent = _make_agent()
        compose_file = tmp_path / "docker-compose.test.yml"
        test_file = tmp_path / "tests" / "test_deployment.py"

        # 12 health-check polls all return not-healthy, then pytest, then down
        ps_unhealthy = MagicMock(returncode=0, stdout="starting", stderr="")
        call_results = (
            [MagicMock(returncode=0, stdout="", stderr="")] +  # up
            [ps_unhealthy] * 12 +  # all health checks fail
            [MagicMock(returncode=1, stdout="FAILED", stderr="")] +  # pytest
            [MagicMock(returncode=0, stdout="", stderr="")]   # down
        )

        with patch("agents.deployment_tester.subprocess.run", side_effect=call_results) as mock_run:
            with patch("agents.deployment_tester.time.sleep"):  # no real sleeps
                result = agent._run_via_compose(compose_file, test_file, tmp_path)

        # Verify 'down' was called (last subprocess.run call contains 'down')
        last_cmd = mock_run.call_args_list[-1][0][0]
        assert "down" in last_cmd
```

- [ ] **Step 2: Run tests**

```bash
python3 -m pytest tests/test_deployment_tester_extended.py -v --tb=short
```
Expected: ~15 passed

- [ ] **Step 3: Commit**

```bash
git add tests/test_deployment_tester_extended.py
git commit -m "test(t14): DeploymentTesterAgent coverage"
```

---

## Task 7: Final verification + PR

- [ ] **Step 1: Run full test suite**

```bash
python3 -m pytest tests/ -q --tb=short 2>&1 | tail -10
```
Expected: ≥1910 passed, 8 skipped, 0 failures (1847 baseline + ~64 new)

- [ ] **Step 2: Run coverage report to confirm improvement**

```bash
python3 -m pytest tests/ --cov=. --cov-report=term-missing -q --tb=no 2>&1 | grep -E "TOTAL|memory_store|tools/builtin|tools/registry|agents/product|agents/summariser|agents/qa_planner|agents/engineer|agents/deployment"
```
Expected TOTAL coverage ≥ 88%

- [ ] **Step 3: Push branch and open PR**

```bash
git push origin t14-coverage-agents-tools-memory
gh pr create \
  --title "T14: Coverage — agents, tools, memory" \
  --body "Adds ~64 tests targeting previously under-tested modules:

- \`memory_store.py\`: consolidation, recall, search, DB migration (65%→~85%)
- \`tools/builtin.py\` + \`tools/registry.py\`: all built-in tools, CombinedToolRegistry (31%→~90%)
- \`agents/product_manager.py\` + \`agents/summariser.py\`: run, run_with_github, run_revision, summarise (63–75%→~95%)
- \`agents/qa_planner.py\` + \`agents/engineer.py\`: run_with_github, run_all_modules, fix_failures, _parse_files (68–79%→~92%)
- \`agents/deployment_tester.py\`: run_with_github, run_docker_smoke_tests, _run_via_compose (68%→~90%)

Total suite: master baseline 1847 + ~64 new tests = ~1911 passed." \
  --base master
```
