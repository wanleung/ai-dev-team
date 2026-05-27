# TDD Reviewer Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `TDDReviewerAgent` that reviews generated test files for correctness (bad imports, wrong conftest scope) and quality (PRD coverage, meaningful assertions) before tests are committed or run.

**Architecture:** New `agents/tdd_reviewer.py` with `TDDReviewerAgent(BaseAgent)`. Orchestrator gains a `tdd_review` pipeline stage inserted between `qa_write` and `test_fix`. `PipelineResult` gains a `tdd_review_summary` field. The agent makes one LLM call, parses revised `### FILE:` blocks + a `### REVIEW SUMMARY:` block, retries once on syntax errors.

**Tech Stack:** Python 3.11+, `ast` (stdlib), existing `BaseAgent` pattern, `QAEngineerAgent._parse_test_files` logic reused.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `agents/tdd_reviewer.py` | **Create** | `TDDReviewerAgent` — LLM review + fix of test files |
| `agents/__init__.py` | **Modify** | Export `TDDReviewerAgent` |
| `orchestrator.py` | **Modify** | `PipelineResult.tdd_review_summary` field, `to_dict`/`from_dict`, `_stage_tdd_review()`, `tdd_review` stage in `_build_engineering_stages_test()`, `self.tdd_reviewer` init in `_init_agents()`, `_original_system_prompts` snapshot |
| `tests/test_tdd_reviewer.py` | **Create** | Unit tests for `TDDReviewerAgent` |

---

### Task 1: Create `TDDReviewerAgent`

**Files:**
- Create: `agents/tdd_reviewer.py`
- Test: `tests/test_tdd_reviewer.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tdd_reviewer.py`:

```python
"""Tests for TDDReviewerAgent."""
from unittest.mock import MagicMock, patch
import pytest


def _make_agent(response: str = ""):
    """Helper: create TDDReviewerAgent with a mocked LLM backend."""
    from agents.tdd_reviewer import TDDReviewerAgent
    agent = TDDReviewerAgent.__new__(TDDReviewerAgent)
    agent.model = "gpt-4.1"
    agent._history = []
    mock_llm = MagicMock()
    mock_llm.model = "gpt-4.1"
    mock_llm.call.return_value = response
    agent._llm = mock_llm
    return agent


class TestParseReviewResponse:
    """Test _parse_review_response static method."""

    def test_parses_file_blocks_and_summary(self):
        from agents.tdd_reviewer import TDDReviewerAgent
        response = """
### FILE: tests/conftest.py
```python
import pytest

class MockModel:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
```

### REVIEW SUMMARY:
- Correctness fixes: moved MockModel to root conftest
- Quality additions: none
- Remaining concerns: none
"""
        files, summary = TDDReviewerAgent._parse_review_response(response)
        assert "tests/conftest.py" in files
        assert "MockModel" in files["tests/conftest.py"]
        assert "Correctness fixes" in summary

    def test_returns_empty_files_when_no_file_blocks(self):
        from agents.tdd_reviewer import TDDReviewerAgent
        response = "### REVIEW SUMMARY:\n- Nothing to fix"
        files, summary = TDDReviewerAgent._parse_review_response(response)
        assert files == {}
        assert "Nothing to fix" in summary

    def test_summary_empty_string_when_missing(self):
        from agents.tdd_reviewer import TDDReviewerAgent
        response = "### FILE: tests/test_foo.py\n```python\nassert True\n```"
        files, summary = TDDReviewerAgent._parse_review_response(response)
        assert "tests/test_foo.py" in files
        assert summary == ""


class TestCollectSyntaxErrors:
    """Test _collect_syntax_errors static method."""

    def test_no_errors_on_valid_python(self):
        from agents.tdd_reviewer import TDDReviewerAgent
        files = {"tests/test_foo.py": "def test_x():\n    assert 1 == 1\n"}
        assert TDDReviewerAgent._collect_syntax_errors(files) == []

    def test_detects_syntax_error(self):
        from agents.tdd_reviewer import TDDReviewerAgent
        files = {"tests/test_foo.py": "def test_x(\n    assert 1 == 1\n"}
        errors = TDDReviewerAgent._collect_syntax_errors(files)
        assert len(errors) == 1
        assert "test_foo.py" in errors[0]

    def test_skips_non_python_files(self):
        from agents.tdd_reviewer import TDDReviewerAgent
        files = {"requirements-test.txt": "pytest\n---\nbad"}
        assert TDDReviewerAgent._collect_syntax_errors(files) == []


class TestRun:
    """Test TDDReviewerAgent.run() end-to-end."""

    def test_run_returns_revised_files_and_summary(self):
        llm_response = """
### FILE: tests/conftest.py
```python
import pytest

class MockModel:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

@pytest.fixture
def mock_db():
    return MockModel()
```

### REVIEW SUMMARY:
- Correctness fixes: added MockModel to conftest
- Quality additions: none
- Remaining concerns: none
"""
        agent = _make_agent(llm_response)
        original = {"tests/conftest.py": "import pytest\n"}
        revised, summary = agent.run(original, prd="Build a REST API", project_name="myapp")
        assert "MockModel" in revised.get("tests/conftest.py", "")
        assert "Correctness fixes" in summary

    def test_run_returns_original_on_llm_failure(self):
        from agents.tdd_reviewer import TDDReviewerAgent
        agent = TDDReviewerAgent.__new__(TDDReviewerAgent)
        agent.model = "gpt-4.1"
        agent._history = []
        mock_llm = MagicMock()
        mock_llm.model = "gpt-4.1"
        mock_llm.call.side_effect = RuntimeError("LLM unavailable")
        agent._llm = mock_llm
        original = {"tests/test_foo.py": "def test_x():\n    assert True\n"}
        revised, summary = agent.run(original, prd="Build something", project_name="proj")
        assert revised == original
        assert summary == ""

    def test_run_returns_original_when_no_file_blocks_returned(self):
        agent = _make_agent("### REVIEW SUMMARY:\n- All good")
        original = {"tests/test_foo.py": "def test_x():\n    assert 1 == 1\n"}
        revised, summary = agent.run(original, prd="PRD", project_name="proj")
        assert revised == original
        assert "All good" in summary
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_tdd_reviewer.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'agents.tdd_reviewer'`

- [ ] **Step 3: Create `agents/tdd_reviewer.py`**

```python
"""TDDReviewerAgent: reviews TDD test files for correctness and PRD coverage.

Sits between qa_write (test generation) and test_fix (test execution) in the
TDD pipeline. Makes one LLM call to:
  1. Fix correctness issues (wrong conftest scope, bad imports, syntax errors).
  2. Improve quality (flag weak assertions, add missing PRD coverage).

Returns revised test files + a plain-text review summary.
Never raises — on any failure it returns the original files unchanged.
"""
from __future__ import annotations

import ast
import logging

from .base_agent import BaseAgent

_log = logging.getLogger(__name__)

_REVIEW_SUMMARY_HEADER = "### REVIEW SUMMARY:"
_FILE_HEADER_PREFIX = "### FILE:"


class TDDReviewerAgent(BaseAgent):
    """Reviews and auto-fixes generated TDD test files.

    Input:  test_files dict, PRD string, project name
    Output: (revised_files dict, review_summary str)
    """

    role_name = "tdd_reviewer"

    def run(
        self,
        test_files: dict[str, str],
        prd: str,
        project_name: str = "Project",
    ) -> tuple[dict[str, str], str]:
        """Review test files for correctness and PRD coverage; auto-fix issues.

        Args:
            test_files: dict of {filepath: content} from QAEngineerAgent.
            prd: PRD markdown — used to check coverage.
            project_name: project name for context.

        Returns:
            (revised_files, review_summary) — revised_files equals test_files
            if the LLM call fails or returns no file blocks.
        """
        if not test_files:
            return test_files, ""

        prompt = self._build_prompt(test_files, prd, project_name)
        try:
            response = self.call(prompt)
        except Exception as exc:  # noqa: BLE001
            _log.warning("TDDReviewer LLM call failed: %s — returning original files", exc)
            return test_files, ""

        revised, summary = self._parse_review_response(response)

        if not revised:
            _log.info("TDDReviewer returned no file blocks — keeping original files")
            return test_files, summary

        # Validate syntax; retry once if errors remain.
        errors = self._collect_syntax_errors(revised)
        if errors:
            _log.info("TDDReviewer: syntax errors after review, retrying: %s", errors)
            try:
                revised, summary = self._retry_syntax_fix(prompt, revised, errors)
            except Exception as exc:  # noqa: BLE001
                _log.warning("TDDReviewer syntax-fix retry failed: %s — keeping pre-retry files", exc)

        return revised, summary

    # ── Prompt builder ──────────────────────────────────────────────────────

    def _build_prompt(
        self, test_files: dict[str, str], prd: str, project_name: str
    ) -> str:
        files_section = "\n\n".join(
            f"### FILE: {path}\n```python\n{content}\n```"
            for path, content in test_files.items()
        )
        return (
            f"You are a senior Python test engineer reviewing TDD test files "
            f"before implementation begins.\n\n"
            f"## Project: {project_name}\n\n"
            f"## PRD:\n{prd}\n\n"
            f"## Test Files to Review:\n{files_section}\n\n"
            f"## Your Task\n\n"
            f"Perform TWO passes:\n\n"
            f"### Pass 1 — Correctness\n"
            f"Fix any issues that would prevent pytest from collecting or running tests:\n"
            f"- `from conftest import X` patterns: if X is a plain class or helper "
            f"(not decorated with @pytest.fixture), it must live in the ROOT conftest.py "
            f"so `from conftest import X` resolves correctly when pytest runs from the "
            f"project root. Move such helpers to conftest.py (root level).\n"
            f"- Import paths that assume an app structure not guaranteed by the PRD "
            f"(e.g. `from app.main import app` when the PRD does not specify that path).\n"
            f"- Any syntax errors.\n\n"
            f"### Pass 2 — Quality\n"
            f"Check coverage against the PRD:\n"
            f"- Every major feature/endpoint mentioned in the PRD should have at least "
            f"one test.\n"
            f"- Every test should have a meaningful assertion (not just `assert True` "
            f"or `assert response is not None`).\n"
            f"- Every tested feature should have at least one error/edge-case test.\n"
            f"- Add concise tests for any obvious gaps (keep each function ≤30 lines).\n\n"
            f"## Output Format\n\n"
            f"Output ALL test files (modified or unchanged) using the ### FILE: format:\n\n"
            f"### FILE: tests/conftest.py\n"
            f"```python\n"
            f"# ... file content ...\n"
            f"```\n\n"
            f"Then output:\n\n"
            f"### REVIEW SUMMARY:\n"
            f"- Correctness fixes: [list what was fixed, or 'none']\n"
            f"- Quality additions: [list what was added/improved, or 'none']\n"
            f"- Remaining concerns: [anything the engineer should know, or 'none']\n"
        )

    # ── Response parser ─────────────────────────────────────────────────────

    @staticmethod
    def _parse_review_response(response: str) -> tuple[dict[str, str], str]:
        """Parse ### FILE: blocks and ### REVIEW SUMMARY: from LLM response.

        Returns (files_dict, summary_str). Either may be empty.
        """
        files: dict[str, str] = {}
        summary = ""
        current_path: str | None = None
        current_lines: list[str] = []
        in_code_block = False
        saw_fence = False
        in_summary = False
        summary_lines: list[str] = []

        for line in response.splitlines():
            stripped = line.strip()

            # Summary section starts after ### REVIEW SUMMARY: and runs to end.
            if stripped.startswith(_REVIEW_SUMMARY_HEADER):
                if current_path and current_lines:
                    files[current_path] = "\n".join(current_lines).strip()
                    current_path, current_lines = None, []
                in_summary = True
                continue

            if in_summary:
                summary_lines.append(line)
                continue

            if stripped.startswith(_FILE_HEADER_PREFIX):
                if current_path and current_lines:
                    files[current_path] = "\n".join(current_lines).strip()
                current_path = stripped.removeprefix(_FILE_HEADER_PREFIX).strip()
                current_lines, in_code_block, saw_fence = [], False, False
                continue

            if current_path is not None:
                if stripped.startswith("```"):
                    if not in_code_block:
                        saw_fence = True
                    in_code_block = not in_code_block
                    continue
                if not saw_fence or in_code_block:
                    current_lines.append(line)

        if current_path and current_lines:
            files[current_path] = "\n".join(current_lines).strip()

        summary = "\n".join(summary_lines).strip()
        return files, summary

    # ── Syntax helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _collect_syntax_errors(files: dict[str, str]) -> list[str]:
        """Return list of 'filename: SyntaxError msg (line N)' for invalid .py files."""
        errors = []
        for filename, source in files.items():
            if not filename.endswith(".py"):
                continue
            try:
                ast.parse(source)
            except SyntaxError as exc:
                errors.append(f"{filename}: {exc.msg} (line {exc.lineno})")
        return errors

    def _retry_syntax_fix(
        self,
        original_prompt: str,
        files: dict[str, str],
        errors: list[str],
    ) -> tuple[dict[str, str], str]:
        """Ask LLM to fix syntax errors; return (revised_files, summary)."""
        error_list = "\n".join(f"  - {e}" for e in errors)
        retry_prompt = (
            f"{original_prompt}\n\n---\n"
            f"The previous output had Python syntax errors:\n{error_list}\n\n"
            f"Fix the syntax errors and output ALL files again in ### FILE: format."
        )
        response = self.call(retry_prompt)
        revised, summary = TDDReviewerAgent._parse_review_response(response)
        return revised or files, summary
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_tdd_reviewer.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add agents/tdd_reviewer.py tests/test_tdd_reviewer.py
git commit -m "feat(tdd_reviewer): add TDDReviewerAgent with correctness + quality review

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Export `TDDReviewerAgent` from `agents/__init__.py`

**Files:**
- Modify: `agents/__init__.py`

- [ ] **Step 1: Add import and export**

In `agents/__init__.py`, add after `from .news_reviewer import NewsReviewerAgent`:

```python
from .tdd_reviewer import TDDReviewerAgent
```

And add `"TDDReviewerAgent"` to the `__all__` list.

- [ ] **Step 2: Verify import works**

```bash
cd /home/wanleung/Projects/ai-software-house
python -c "from agents import TDDReviewerAgent; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add agents/__init__.py
git commit -m "feat(agents): export TDDReviewerAgent

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Add `tdd_review_summary` to `PipelineResult`

**Files:**
- Modify: `orchestrator.py` — `PipelineResult` dataclass, `to_dict()`, `from_dict()`

- [ ] **Step 1: Write failing test**

Add to `tests/test_tdd_reviewer.py` (new class at the bottom):

```python
class TestPipelineResultTddReviewSummary:
    """PipelineResult must carry tdd_review_summary through checkpoint round-trip."""

    def test_tdd_review_summary_field_exists(self):
        from orchestrator import PipelineResult
        r = PipelineResult(requirement="test")
        assert hasattr(r, "tdd_review_summary")
        assert r.tdd_review_summary == ""

    def test_tdd_review_summary_round_trips_through_dict(self):
        from orchestrator import PipelineResult
        r = PipelineResult(requirement="test")
        r.tdd_review_summary = "Correctness fixes: moved MockModel"
        d = r.to_dict()
        assert d["tdd_review_summary"] == "Correctness fixes: moved MockModel"
        r2 = PipelineResult.from_dict(d)
        assert r2.tdd_review_summary == "Correctness fixes: moved MockModel"
```

- [ ] **Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_tdd_reviewer.py::TestPipelineResultTddReviewSummary -v
```

Expected: `AttributeError: 'PipelineResult' object has no attribute 'tdd_review_summary'`

- [ ] **Step 3: Add field to `PipelineResult`**

In `orchestrator.py`, find the `PipelineResult` dataclass (line ~359). Add after `triage_scope: str = ""`:

```python
    tdd_review_summary: str = ""
```

- [ ] **Step 4: Add to `to_dict()`**

In `PipelineResult.to_dict()`, add after `"triage_scope": self.triage_scope,`:

```python
            "tdd_review_summary": self.tdd_review_summary,
```

- [ ] **Step 5: Add to `from_dict()`**

In `PipelineResult.from_dict()`, add `"tdd_review_summary"` to the list of keys passed to `setattr`:

Find the list starting with `"project_name", "prd",` and add `"tdd_review_summary"` alongside `"triage_scope"`.

- [ ] **Step 6: Run tests to verify they pass**

```bash
python -m pytest tests/test_tdd_reviewer.py::TestPipelineResultTddReviewSummary -v
```

Expected: both tests PASS.

- [ ] **Step 7: Commit**

```bash
git add orchestrator.py
git commit -m "feat(orchestrator): add tdd_review_summary to PipelineResult

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Wire orchestrator — init agent + stage + stage function

**Files:**
- Modify: `orchestrator.py` — imports, `_init_agents()`, `_build_engineering_stages_test()`, new `_stage_tdd_review()`, `_original_system_prompts` snapshot

- [ ] **Step 1: Write failing test**

Add to `tests/test_tdd_reviewer.py`:

```python
class TestTddReviewerStageWiring:
    """The tdd_review stage must be present in the TDD pipeline stages."""

    def _make_orchestrator(self):
        """Create a minimal Orchestrator instance with mocked agents."""
        from orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        # Minimal attrs the stage builders inspect
        orch.stop_on_review_issues = False
        orch.tdd_commit_tests = True
        orch.workspace_dir = __import__("pathlib").Path("/tmp/orch_test")
        orch.model_overrides = {}
        orch.junior_model = None
        orch.senior_model = None
        orch.tier_reviewer_model = None
        orch.junior_engineer_use_mcp = False
        orch.senior_engineer_use_mcp = False
        # Mock tdd_reviewer
        mock_reviewer = MagicMock()
        mock_reviewer.run.return_value = ({}, "")
        orch.tdd_reviewer = mock_reviewer
        return orch

    def test_tdd_review_stage_in_build_engineering_stages_test(self):
        orch = self._make_orchestrator()
        stages = orch._build_engineering_stages_test()
        assert "tdd_review" in stages

    def test_tdd_review_stage_is_between_qa_write_and_test_fix(self):
        orch = self._make_orchestrator()
        stages = orch._build_engineering_stages_test()
        keys = list(stages.keys())
        assert keys.index("tdd_review") > keys.index("qa_write")
        assert keys.index("tdd_review") < keys.index("test_fix")
```

- [ ] **Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_tdd_reviewer.py::TestTddReviewerStageWiring -v
```

Expected: `KeyError: 'tdd_review'` (stage not yet added)

- [ ] **Step 3: Add import to orchestrator**

At the top of `orchestrator.py`, alongside other agent imports add:

```python
from agents.tdd_reviewer import TDDReviewerAgent
```

- [ ] **Step 4: Add `self.tdd_reviewer` to `_init_agents()`**

In `_init_agents()` in `orchestrator.py`, after `self.qa = QAEngineerAgent(...)` (line ~996), add:

```python
        self.tdd_reviewer = TDDReviewerAgent(**{**agent_kwargs, **mk("tdd_reviewer")})
```

- [ ] **Step 5: Add `self.tdd_reviewer` to `_original_system_prompts` snapshot**

In `_init_support_agents()`, find the `_original_system_prompts` dict comprehension (line ~1040). Add `self.tdd_reviewer` to the agent list:

```python
        self._original_system_prompts: dict = {
            agent: agent.system_prompt
            for agent in (
                self.pm, self.news_writer, self.news_editor, self.news_reviewer,
                self.pm_reviewer, self.architect, self.architect_reviewer,
                self.engineer, self.junior_engineer, self.senior_engineer,
                self.tier_reviewer,
                self.reviewer, self.qa_planner, self.qa, self.tdd_reviewer,
                self.deployment_tester,
            )
            if agent is not None
        }
```

- [ ] **Step 6: Add `_stage_tdd_review()` method**

Find `_stage_qa_write()` in `orchestrator.py` (line ~4428). Add the following method right after it:

```python
    def _stage_tdd_review(self, result: PipelineResult) -> None:
        """Review and auto-fix TDD test files for correctness and PRD coverage."""
        console.print("\n[bold cyan]🔬 TDD Reviewer[/bold cyan]")
        revised, summary = self.tdd_reviewer.run(
            result.test_files,
            result.prd or "",
            result.project_name or "project",
        )
        result.test_files = revised
        result.tdd_review_summary = summary
        if summary:
            console.print(f"[dim]{summary[:400]}[/dim]")
        # Overwrite locally saved files so test_fix picks up revised versions.
        if revised:
            self._save_files_locally(revised, result.project_name)
            console.print(f"[green]✅ TDD review complete — {len(revised)} file(s) updated[/green]")
```

- [ ] **Step 7: Add `tdd_review` stage to `_build_engineering_stages_test()`**

Find `_build_engineering_stages_test()` (line ~2094). Insert the `tdd_review` stage **after** `qa_write` and **before** `test_fix`:

```python
    def _build_engineering_stages_test(self) -> dict[str, "PipelineStage"]:
        """Build TDD write, test-runner loop, and validation-gate stages."""
        stages: dict[str, "PipelineStage"] = {}
        stages["qa_write"] = PipelineStage(
            name="qa_write",
            label="✍️  QA Write (TDD)",
            description="Writing tests before implementation...",
            checkpoint_key="qa_write",
            fn=lambda r: self._stage_qa_write(r),
        )
        stages["tdd_review"] = PipelineStage(
            name="tdd_review",
            label="🔬 TDD Reviewer",
            description="Reviewing test files for correctness and PRD coverage...",
            checkpoint_key="tdd_review",
            fn=lambda r: self._stage_tdd_review(r),
            skip_if=lambda r: not r.test_files,
        )
        stages["test_fix"] = PipelineStage(
            name="test_fix",
            label="🏃 Test Runner + Fix Loop",
            description="Executing tests (with auto-fix)…",
            checkpoint_key="test_runner",
            fn=lambda r: self._stage_test_fix_loop(r),
            skip_if=lambda r: not r.test_files,
        )
        stages["validation_gate"] = PipelineStage(
            name="validation_gate",
            label="🔍 Validation Gate",
            description="Syntax-checking and linting generated code...",
            checkpoint_key="validation_gate",
            fn=lambda r: self._stage_validation_gate(r),
        )
        return stages
```

- [ ] **Step 8: Run wiring tests**

```bash
python -m pytest tests/test_tdd_reviewer.py -v
```

Expected: all tests PASS.

- [ ] **Step 9: Run full test suite to check for regressions**

```bash
python -m pytest tests/ -x -q --timeout=30 2>&1 | tail -20
```

Expected: no new failures.

- [ ] **Step 10: Commit**

```bash
git add orchestrator.py
git commit -m "feat(orchestrator): wire TDDReviewerAgent as tdd_review pipeline stage

- Add tdd_reviewer agent init in _init_agents()
- Add tdd_review stage between qa_write and test_fix
- Add _stage_tdd_review() method
- Include tdd_reviewer in system-prompt snapshot

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Add role file for TDDReviewerAgent

**Files:**
- Create: `roles/tdd_reviewer.md` (or check existing roles dir for correct path)

- [ ] **Step 1: Find where role files live**

```bash
ls /home/wanleung/Projects/ai-software-house/roles/ | head -10
```

- [ ] **Step 2: Create role file**

Create `roles/tdd_reviewer.md`:

```markdown
# TDD Reviewer

You are a senior Python test engineer. Your job is to review TDD test files
written by a QA Engineer before any implementation code is written.

You have two responsibilities:

## 1. Correctness

Fix issues that would prevent pytest from collecting or running the tests:

- **conftest import scope**: If test files use `from conftest import X` where X
  is a plain class (not decorated with `@pytest.fixture`), that class MUST live
  in the ROOT `conftest.py` (not `tests/conftest.py`). When pytest runs from the
  project root, `from conftest import X` resolves to the root `conftest.py`.
  Move such helpers there.

- **Import path assumptions**: Do not import from paths that assume a specific
  project layout not guaranteed by the PRD (e.g. `from app.main import app`
  unless the PRD explicitly specifies `app/main.py`).

- **Syntax errors**: Fix any invalid Python syntax.

## 2. Quality

Check test coverage against the PRD:

- Every major feature or API endpoint in the PRD must have at least one test.
- Every test must have a meaningful assertion — not just `assert True` or
  `assert response is not None`.
- Every tested feature must include at least one error/edge-case test.
- Use pytest fixtures from conftest where appropriate; avoid inline mock setup
  repeated across multiple tests.

## Output Format

Always output ALL test files (modified or unchanged) using `### FILE:` headers
and fenced code blocks. Then output a review summary:

```
### REVIEW SUMMARY:
- Correctness fixes: [what was fixed]
- Quality additions: [what was added]
- Remaining concerns: [anything the engineer should know]
```

Keep every function ≤ 30 lines. Split helpers into fixtures if needed.
```

- [ ] **Step 3: Verify agent loads role file**

```bash
cd /home/wanleung/Projects/ai-software-house
python -c "
from agents.tdd_reviewer import TDDReviewerAgent
a = TDDReviewerAgent.__new__(TDDReviewerAgent)
from pathlib import Path
prompt = a._load_system_prompt(Path('roles'))
print('Loaded:', len(prompt), 'chars')
print(prompt[:100])
"
```

Expected: prints the role file content (not empty).

- [ ] **Step 4: Commit**

```bash
git add roles/tdd_reviewer.md
git commit -m "feat(roles): add tdd_reviewer system prompt

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 6: Final verification

- [ ] **Step 1: Run full test suite**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_tdd_reviewer.py tests/test_execution_agents.py tests/test_reviewer_agents.py -v --timeout=30
```

Expected: all tests PASS, no regressions in reviewer/execution agent tests.

- [ ] **Step 2: Verify stage ordering in a complete pipeline build**

```bash
python -c "
from unittest.mock import MagicMock
from orchestrator import Orchestrator
import pathlib

orch = Orchestrator.__new__(Orchestrator)
orch.stop_on_review_issues = False
orch.tdd_commit_tests = True
orch.workspace_dir = pathlib.Path('/tmp')
orch.model_overrides = {}
orch.junior_model = None
orch.senior_model = None
orch.tier_reviewer_model = None
orch.junior_engineer_use_mcp = False
orch.senior_engineer_use_mcp = False
orch.tdd_reviewer = MagicMock()
orch.tdd_reviewer.run.return_value = ({}, '')

stages = orch._build_engineering_stages_test()
keys = list(stages.keys())
print('Stage order:', keys)
assert 'tdd_review' in keys
assert keys.index('tdd_review') > keys.index('qa_write')
assert keys.index('tdd_review') < keys.index('test_fix')
print('Stage ordering: OK')
"
```

Expected: `Stage order: ['qa_write', 'tdd_review', 'test_fix', 'validation_gate']` and `Stage ordering: OK`.

- [ ] **Step 3: Final commit if any cleanup needed, then push**

```bash
git push
```
