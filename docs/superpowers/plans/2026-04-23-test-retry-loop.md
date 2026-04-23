# Test & Deploy Retry Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When generated tests fail, automatically send failure output back to the engineer agent for targeted fixes and re-run tests — up to 5 times — before flagging for human review. Applies to both the feature pipeline (unit + deploy tests) and the bug fix pipeline (regression tests).

**Architecture:** A new `TestFixLoopMixin` in `test_fix_loop.py` provides the shared retry loop via `run_test_fix_loop()`. Both `Orchestrator` and `BugFixOrchestrator` inherit the mixin and wire it up with closures. `EngineerAgent` gets a new `fix_failures()` method that takes failure output + all project files and returns targeted patches.

**Tech Stack:** Python 3.11+, pytest (already installed), rich Console, existing GitHub API client (`GitHubClient.commit_file`).

**Spec:** `docs/superpowers/specs/2026-04-21-test-retry-loop-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `agents/engineer.py` | Modify | Add `fix_failures()` method |
| `test_fix_loop.py` | **Create** | `TestFixLoopMixin` with `run_test_fix_loop()` |
| `orchestrator.py` | Modify | Add retry fields to `PipelineResult`; add `max_test_retries`/`max_deploy_retries` constructor params; `Orchestrator` inherits mixin; add `_stage_test_fix_loop()` and `_stage_deploy_fix_loop()`; wire pipeline |
| `bug_fix_orchestrator.py` | Modify | Add retry fields to `BugFixResult`; `BugFixOrchestrator` inherits mixin; add `_stage_test_runner()` and `_stage_test_fix_loop()`; wire pipeline |
| `config.yaml` | Modify | Add `max_test_retries: 5` and `max_deploy_retries: 5` under `pipeline:` |
| `tests/test_engineer_fix.py` | **Create** | Unit tests for `fix_failures()` |
| `tests/test_test_fix_loop.py` | **Create** | Unit tests for `TestFixLoopMixin.run_test_fix_loop()` |
| `tests/test_bug_fix_retry.py` | **Create** | Integration tests for `BugFixOrchestrator` retry wiring |

---

## Task 1: `EngineerAgent.fix_failures()`

**Files:**
- Modify: `agents/engineer.py`
- Create: `tests/test_engineer_fix.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_engineer_fix.py`:

```python
"""Tests for EngineerAgent.fix_failures()."""
from unittest.mock import MagicMock, patch
import pytest
from agents.engineer import EngineerAgent


def _make_agent():
    agent = EngineerAgent.__new__(EngineerAgent)
    agent._tool_registry = None
    return agent


def test_fix_failures_returns_parsed_files():
    agent = _make_agent()
    agent.call = MagicMock(return_value=(
        "### FILE: app/models/user.py\n"
        "class User:\n    pass\n"
    ))
    patches = agent.fix_failures(
        failure_output="FAILED tests/test_user.py::test_create",
        all_files={"app/models/user.py": "# broken", "app/main.py": "# ok"},
        design="System design here.",
        project_name="MyApp",
    )
    assert "app/models/user.py" in patches
    assert "class User" in patches["app/models/user.py"]


def test_fix_failures_returns_empty_on_no_file_blocks():
    agent = _make_agent()
    agent.call = MagicMock(return_value="I could not identify the issue.")
    patches = agent.fix_failures(
        failure_output="FAILED tests/test_user.py",
        all_files={"app/main.py": "# code"},
        design="design",
    )
    assert patches == {}


def test_fix_failures_prompt_includes_failure_output():
    agent = _make_agent()
    captured_prompt = []
    agent.call = MagicMock(side_effect=lambda p: captured_prompt.append(p) or "")
    agent.fix_failures(
        failure_output="AssertionError: expected 1 got 2",
        all_files={"app/main.py": "x = 1"},
        design="design",
    )
    assert "AssertionError: expected 1 got 2" in captured_prompt[0]


def test_fix_failures_prompt_includes_all_files():
    agent = _make_agent()
    captured_prompt = []
    agent.call = MagicMock(side_effect=lambda p: captured_prompt.append(p) or "")
    agent.fix_failures(
        failure_output="err",
        all_files={"app/foo.py": "def foo(): pass", "app/bar.py": "x = 1"},
        design="design",
    )
    assert "app/foo.py" in captured_prompt[0]
    assert "app/bar.py" in captured_prompt[0]
    assert "def foo(): pass" in captured_prompt[0]


def test_fix_failures_prepends_framework_context():
    agent = _make_agent()
    captured_prompt = []
    agent.call = MagicMock(side_effect=lambda p: captured_prompt.append(p) or "")
    agent.fix_failures(
        failure_output="err",
        all_files={},
        design="design",
        framework_context="## Next.js Docs\n\nUse App Router.",
    )
    prompt = captured_prompt[0]
    assert prompt.startswith("## Framework Documentation")
    assert "Next.js Docs" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate
pytest tests/test_engineer_fix.py -v
```
Expected: 5 failures — `AttributeError: 'EngineerAgent' object has no attribute 'fix_failures'`

- [ ] **Step 3: Implement `fix_failures()` in `agents/engineer.py`**

Add after the `run_with_github` method and before `_parse_files` (around line 188):

```python
def fix_failures(
    self,
    failure_output: str,
    all_files: dict,
    design: str,
    project_name: str = "Project",
    framework_context: str = "",
) -> dict:
    """Produce targeted code fixes for failing tests.

    Returns:
        {filepath: content} of ONLY the files that need to change.
        Empty dict if the LLM returns no parseable file blocks.
    """
    framework_section = (
        f"## Framework Documentation\n\n{framework_context}\n\n"
        if framework_context else ""
    )
    files_section = "\n\n".join(
        f"## File: {path}\n\n```\n{content}\n```"
        for path, content in all_files.items()
    )
    prompt = (
        f"{framework_section}"
        f"You are fixing test failures in the project '{project_name}'.\n\n"
        f"## Test Failure Output\n\n```\n{failure_output}\n```\n\n"
        f"## Current Project Files\n\n{files_section}\n\n"
        f"## System Design\n\n{design}\n\n"
        f"Read the test failure output carefully. Identify the root cause.\n"
        f"Fix ONLY the broken source files. Do NOT modify test files.\n"
        f"Return ONLY the files that need to change, using the '### FILE: path/to/file.py' format.\n"
        f"Do not return files that do not need to change."
    )
    response = self.call(prompt)
    return self._parse_files(response)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_engineer_fix.py -v
```
Expected: 5 passed

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
pytest tests/ -v --tb=short -q
```
Expected: all previously passing tests still pass

- [ ] **Step 6: Commit**

```bash
git add agents/engineer.py tests/test_engineer_fix.py
git commit -m "feat(engineer): add fix_failures() method for targeted test-failure patches"
```

---

## Task 2: `TestFixLoopMixin`

**Files:**
- Create: `test_fix_loop.py`
- Create: `tests/test_test_fix_loop.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_test_fix_loop.py`:

```python
"""Tests for TestFixLoopMixin.run_test_fix_loop()."""
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import MagicMock, call
import pytest
from test_fix_loop import TestFixLoopMixin


@dataclass
class FakeResult:
    tests_passed: Optional[bool] = None
    test_results: str = ""
    test_retry_count: int = 0
    test_fix_history: list = field(default_factory=list)


class FakeMixin(TestFixLoopMixin):
    pass


def _make_mixin():
    return FakeMixin()


def _run_tests_pass(result):
    result.tests_passed = True
    result.test_results = "1 passed"


def _run_tests_fail(result):
    result.tests_passed = False
    result.test_results = "FAILED test_foo"


def test_returns_immediately_when_first_run_passes():
    mixin = _make_mixin()
    result = FakeResult()
    run_tests_fn = MagicMock(side_effect=_run_tests_pass)
    fix_fn = MagicMock()

    mixin.run_test_fix_loop(
        result=result,
        run_tests_fn=run_tests_fn,
        get_all_files_fn=lambda: {},
        write_files_fn=MagicMock(),
        commit_fn=MagicMock(return_value=True),
        post_comment_fn=MagicMock(),
        fix_fn=fix_fn,
        max_retries=3,
    )

    run_tests_fn.assert_called_once()
    fix_fn.assert_not_called()
    assert result.test_retry_count == 0


def test_calls_fix_and_retests_on_failure():
    mixin = _make_mixin()
    result = FakeResult()
    call_count = [0]

    def run_tests_fn(r):
        call_count[0] += 1
        if call_count[0] == 1:
            _run_tests_fail(r)
        else:
            _run_tests_pass(r)

    fix_fn = MagicMock(return_value={"app/foo.py": "fixed"})
    write_fn = MagicMock()
    commit_fn = MagicMock(return_value=True)

    mixin.run_test_fix_loop(
        result=result,
        run_tests_fn=run_tests_fn,
        get_all_files_fn=lambda: {"app/foo.py": "broken"},
        write_files_fn=write_fn,
        commit_fn=commit_fn,
        post_comment_fn=MagicMock(),
        fix_fn=fix_fn,
        max_retries=3,
    )

    assert call_count[0] == 2         # initial run + 1 retry
    fix_fn.assert_called_once()
    write_fn.assert_called_once_with({"app/foo.py": "fixed"})
    assert result.test_retry_count == 1
    assert len(result.test_fix_history) == 1
    assert "Attempt 1" in result.test_fix_history[0]


def test_stops_loop_when_tests_pass_midway():
    mixin = _make_mixin()
    result = FakeResult()
    runs = [0]

    def run_tests_fn(r):
        runs[0] += 1
        if runs[0] <= 2:
            _run_tests_fail(r)
        else:
            _run_tests_pass(r)

    fix_fn = MagicMock(return_value={"app/foo.py": "v2"})

    mixin.run_test_fix_loop(
        result=result,
        run_tests_fn=run_tests_fn,
        get_all_files_fn=lambda: {},
        write_files_fn=MagicMock(),
        commit_fn=MagicMock(return_value=True),
        post_comment_fn=MagicMock(),
        fix_fn=fix_fn,
        max_retries=5,
    )

    assert runs[0] == 3              # fail, fail, pass
    assert result.test_retry_count == 2
    assert result.tests_passed is True


def test_exhausts_retries_and_posts_comment():
    mixin = _make_mixin()
    result = FakeResult()
    post_fn = MagicMock()

    mixin.run_test_fix_loop(
        result=result,
        run_tests_fn=lambda r: _run_tests_fail(r),
        get_all_files_fn=lambda: {"app/foo.py": "broken"},
        write_files_fn=MagicMock(),
        commit_fn=MagicMock(return_value=True),
        post_comment_fn=post_fn,
        fix_fn=MagicMock(return_value={"app/foo.py": "fix"}),
        max_retries=3,
    )

    assert result.test_retry_count == 3
    post_fn.assert_called_once()
    msg = post_fn.call_args[0][0]
    assert "Automatic Test Fix Exhausted" in msg
    assert "Human review required" in msg
    assert "Attempt 1" in msg


def test_breaks_on_empty_patch():
    mixin = _make_mixin()
    result = FakeResult()
    fix_fn = MagicMock(return_value={})
    run_count = [0]

    def run_tests(r):
        run_count[0] += 1
        _run_tests_fail(r)

    mixin.run_test_fix_loop(
        result=result,
        run_tests_fn=run_tests,
        get_all_files_fn=lambda: {},
        write_files_fn=MagicMock(),
        commit_fn=MagicMock(return_value=True),
        post_comment_fn=MagicMock(),
        fix_fn=fix_fn,
        max_retries=5,
    )

    # Only the initial run + 1 fix attempt (which returned {}) — loop breaks
    assert run_count[0] == 1
    assert result.test_retry_count == 0


def test_retry_count_and_history_accurate():
    mixin = _make_mixin()
    result = FakeResult()

    def fix_fn(failure, files):
        return {"app/a.py": "v1", "app/b.py": "v2"}

    mixin.run_test_fix_loop(
        result=result,
        run_tests_fn=lambda r: _run_tests_fail(r),
        get_all_files_fn=lambda: {},
        write_files_fn=MagicMock(),
        commit_fn=MagicMock(return_value=True),
        post_comment_fn=MagicMock(),
        fix_fn=fix_fn,
        max_retries=2,
    )

    assert result.test_retry_count == 2
    assert len(result.test_fix_history) == 2
    assert "2 file(s) patched" in result.test_fix_history[0]
    assert "2 file(s) patched" in result.test_fix_history[1]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_test_fix_loop.py -v
```
Expected: `ModuleNotFoundError: No module named 'test_fix_loop'`

- [ ] **Step 3: Create `test_fix_loop.py`**

```python
"""TestFixLoopMixin — shared retry loop for test-failure auto-fixing.

Both Orchestrator and BugFixOrchestrator inherit this mixin.
"""
from __future__ import annotations

from typing import Callable

from rich.console import Console

console = Console()


class TestFixLoopMixin:
    """Mixin providing run_test_fix_loop() for orchestrators with an engineer agent.

    The mixin holds no state. All side-effectful operations are injected as
    callables so the mixin can be unit-tested independently.
    """

    def run_test_fix_loop(
        self,
        result,
        run_tests_fn: Callable,
        get_all_files_fn: Callable[[], dict],
        write_files_fn: Callable[[dict], None],
        commit_fn: Callable[[int, dict], bool],
        post_comment_fn: Callable[[str], None],
        fix_fn: Callable[[str, dict], dict],
        max_retries: int = 5,
    ) -> None:
        """Run tests, then retry engineer fixes up to max_retries times on failure.

        Args:
            result:            PipelineResult or BugFixResult (duck-typed).
                               Must have: tests_passed (bool|None), test_results (str),
                               test_retry_count (int), test_fix_history (list[str]).
            run_tests_fn:      callable(result) — runs tests and sets
                               result.tests_passed + result.test_results.
            get_all_files_fn:  callable() → dict[str, str] of current files on disk.
            write_files_fn:    callable(patches: dict) — writes patched files to disk.
            commit_fn:         callable(attempt: int, patches: dict) → bool.
                               Should commit the patches; return True on success,
                               False if nothing changed (triggers early break).
            post_comment_fn:   callable(message: str) — post to PR or Issue.
            fix_fn:            callable(failure_output: str, all_files: dict) → dict.
                               Calls engineer.fix_failures(); returns patched files.
            max_retries:       Maximum fix attempts before giving up.
        """
        run_tests_fn(result)

        if getattr(result, "tests_passed", None) is True:
            return

        for attempt in range(1, max_retries + 1):
            console.print(f"    🔁 Test fix attempt {attempt}/{max_retries}…")

            all_files = get_all_files_fn()
            failure_output = getattr(result, "test_results", "") or ""

            patches = fix_fn(failure_output, all_files)
            if not patches:
                console.print(
                    "    ⚠️  Engineer returned no patches — stopping retry loop."
                )
                break

            write_files_fn(patches)

            committed = commit_fn(attempt, patches)
            if not committed:
                console.print(
                    "    ⚠️  No code changes after fix — stopping retry loop."
                )
                break

            result.test_fix_history.append(
                f"Attempt {attempt}: {len(patches)} file(s) patched"
            )
            result.test_retry_count += 1

            run_tests_fn(result)
            if getattr(result, "tests_passed", None) is True:
                console.print(
                    f"    ✅ Tests passed after {attempt} fix attempt(s)."
                )
                return

        if getattr(result, "tests_passed", None) is not True:
            console.print(
                f"    ⚠️  All {result.test_retry_count} fix attempt(s) failed."
            )
            history_md = "\n".join(
                f"- {h}" for h in result.test_fix_history
            ) or "(no attempts completed)"
            failure_lines = (
                getattr(result, "test_results", "") or ""
            ).strip().splitlines()
            truncated = (
                "\n".join(failure_lines[-60:])
                if len(failure_lines) > 60
                else "\n".join(failure_lines)
            )
            message = (
                f"## ⚠️ Automatic Test Fix Exhausted\n\n"
                f"After {result.test_retry_count} attempt(s), tests are still "
                f"failing. Human review required.\n\n"
                f"### Fix History\n\n{history_md}\n\n"
                f"### Final Failure Output\n\n```\n{truncated}\n```"
            )
            post_comment_fn(message)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_test_fix_loop.py -v
```
Expected: 6 passed

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v --tb=short -q
```
Expected: all previously passing tests still pass

- [ ] **Step 6: Commit**

```bash
git add test_fix_loop.py tests/test_test_fix_loop.py
git commit -m "feat: add TestFixLoopMixin with run_test_fix_loop() shared retry logic"
```

---

## Task 3: `PipelineResult` additions + config + Orchestrator wiring

**Files:**
- Modify: `orchestrator.py`
- Modify: `config.yaml`

- [ ] **Step 1: Add retry fields to `PipelineResult` dataclass**

In `orchestrator.py`, find the `PipelineResult` dataclass. After the `clarification_history` field (around line 119), add:

```python
    # Test-fix retry tracking
    test_retry_count: int = 0
    test_fix_history: list[str] = field(default_factory=list)
    deploy_retry_count: int = 0
    deploy_fix_history: list[str] = field(default_factory=list)
```

- [ ] **Step 2: Update `to_dict()` in `PipelineResult`**

In the `to_dict()` method, add after `"clarification_history": self.clarification_history,`:

```python
            "test_retry_count": self.test_retry_count,
            "test_fix_history": self.test_fix_history,
            "deploy_retry_count": self.deploy_retry_count,
            "deploy_fix_history": self.deploy_fix_history,
```

- [ ] **Step 3: Update `from_dict()` in `PipelineResult`**

In the `from_dict()` class method, add `"test_retry_count"`, `"test_fix_history"`, `"deploy_retry_count"`, `"deploy_fix_history"` to the key list used in the `for key in [...]` loop.

- [ ] **Step 4: Add `max_test_retries` and `max_deploy_retries` to `Orchestrator.__init__`**

In `Orchestrator.__init__`, after `inter_call_delay: int = 0` (line ~203), add:

```python
        max_test_retries: int = 5,
        max_deploy_retries: int = 5,
```

And in the body after `self.inter_call_delay = inter_call_delay` (store them):

```python
        self.max_test_retries = max_test_retries
        self.max_deploy_retries = max_deploy_retries
```

- [ ] **Step 5: Update `Orchestrator.from_config()` to read new config keys**

In `from_config()`, after `inter_call_delay=pipeline.get("inter_call_delay", 0),`, add:

```python
            max_test_retries=pipeline.get("max_test_retries", 5),
            max_deploy_retries=pipeline.get("max_deploy_retries", 5),
```

- [ ] **Step 6: Make `Orchestrator` inherit `TestFixLoopMixin`**

Change the class declaration (around line 170):

```python
# Before
class Orchestrator:

# After
from test_fix_loop import TestFixLoopMixin

class Orchestrator(TestFixLoopMixin):
```

(The `from test_fix_loop import TestFixLoopMixin` import should go with the other imports at the top of the file, not inline.)

- [ ] **Step 7: Add `_stage_test_fix_loop()` to `Orchestrator`**

Add this method after `_stage_test_runner()` (after line ~1042):

```python
def _stage_test_fix_loop(self, result: PipelineResult) -> None:
    """Run tests and automatically retry engineer fixes on failure."""
    safe = "".join(
        c if c.isalnum() or c in "-_" else "_"
        for c in result.project_name.lower()
    )
    project_dir = (self.workspace_dir / safe).resolve()
    skip = {".git", "__pycache__", "node_modules"}

    def get_all_files_fn() -> dict:
        files = {}
        for path in sorted(project_dir.rglob("*")):
            if any(part in skip for part in path.parts):
                continue
            if path.is_file() and path.suffix not in {".pyc", ".pyo"}:
                try:
                    files[str(path.relative_to(project_dir))] = path.read_text(
                        encoding="utf-8", errors="replace"
                    )
                except OSError:
                    pass
        return files

    def write_files_fn(patches: dict) -> None:
        for filepath, content in patches.items():
            full_path = project_dir / filepath
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")

    def commit_fn(attempt: int, patches: dict) -> bool:
        if self.target_github and result.branch:
            for filepath, content in patches.items():
                self.target_github.commit_file(
                    path=filepath,
                    content=content,
                    message=f"fix(auto): test retry {attempt}/{self.max_test_retries}",
                    branch=result.branch,
                )
        return True

    def post_comment_fn(message: str) -> None:
        if self.target_github and result.pr_number:
            self.target_github.add_pr_comment(result.pr_number, message)

    def fix_fn(failure_output: str, all_files: dict) -> dict:
        return self.engineer.fix_failures(
            failure_output=failure_output,
            all_files=all_files,
            design=result.design,
            project_name=result.project_name,
        )

    self.run_test_fix_loop(
        result=result,
        run_tests_fn=lambda r: self._stage_test_runner(r),
        get_all_files_fn=get_all_files_fn,
        write_files_fn=write_files_fn,
        commit_fn=commit_fn,
        post_comment_fn=post_comment_fn,
        fix_fn=fix_fn,
        max_retries=self.max_test_retries,
    )
```

- [ ] **Step 8: Add `_stage_deploy_fix_loop()` to `Orchestrator`**

Add after `_stage_deploy_test_runner()` (after line ~1097):

```python
def _stage_deploy_fix_loop(self, result: PipelineResult) -> None:
    """Run deployment tests and retry engineer fixes on failure.

    Only called when unit tests have passed (result.tests_passed is True).
    Uses result.deploy_retry_count and result.deploy_fix_history.
    """
    if result.tests_passed is not True:
        console.print("    ⏭️  Skipping deploy fix loop — unit tests did not pass.")
        return

    safe = "".join(
        c if c.isalnum() or c in "-_" else "_"
        for c in result.project_name.lower()
    )
    project_dir = (self.workspace_dir / safe).resolve()
    skip = {".git", "__pycache__", "node_modules"}

    def get_all_files_fn() -> dict:
        files = {}
        for path in sorted(project_dir.rglob("*")):
            if any(part in skip for part in path.parts):
                continue
            if path.is_file() and path.suffix not in {".pyc", ".pyo"}:
                try:
                    files[str(path.relative_to(project_dir))] = path.read_text(
                        encoding="utf-8", errors="replace"
                    )
                except OSError:
                    pass
        return files

    def write_files_fn(patches: dict) -> None:
        for filepath, content in patches.items():
            full_path = project_dir / filepath
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")

    def commit_fn(attempt: int, patches: dict) -> bool:
        if self.target_github and result.branch:
            for filepath, content in patches.items():
                self.target_github.commit_file(
                    path=filepath,
                    content=content,
                    message=f"fix(auto): deploy retry {attempt}/{self.max_deploy_retries}",
                    branch=result.branch,
                )
        return True

    def post_comment_fn(message: str) -> None:
        if self.target_github and result.pr_number:
            self.target_github.add_pr_comment(result.pr_number, message)

    def fix_fn(failure_output: str, all_files: dict) -> dict:
        return self.engineer.fix_failures(
            failure_output=failure_output,
            all_files=all_files,
            design=result.design,
            project_name=result.project_name,
        )

    # Temporarily alias deploy fields to the standard names the mixin expects,
    # then restore. This lets us reuse run_test_fix_loop without modification.
    _orig_passed = result.tests_passed
    _orig_results = result.test_results
    _orig_count = result.test_retry_count
    _orig_history = result.test_fix_history
    result.tests_passed = result.deploy_tests_passed
    result.test_results = result.deploy_test_results
    result.test_retry_count = result.deploy_retry_count
    result.test_fix_history = result.deploy_fix_history

    def run_deploy_tests(r):
        self._stage_deploy_test_runner(r)
        # Mirror deploy fields back to standard names for mixin
        r.tests_passed = r.deploy_tests_passed
        r.test_results = r.deploy_test_results

    self.run_test_fix_loop(
        result=result,
        run_tests_fn=run_deploy_tests,
        get_all_files_fn=get_all_files_fn,
        write_files_fn=write_files_fn,
        commit_fn=commit_fn,
        post_comment_fn=post_comment_fn,
        fix_fn=fix_fn,
        max_retries=self.max_deploy_retries,
    )

    # Restore and sync deploy fields
    result.deploy_retry_count = result.test_retry_count
    result.deploy_fix_history = result.test_fix_history
    result.tests_passed = _orig_passed
    result.test_results = _orig_results
    result.test_retry_count = _orig_count
    result.test_fix_history = _orig_history
```

- [ ] **Step 9: Wire pipeline — replace Stage 6 and Stage 8**

In `run()` (around lines 801–823), replace the two existing stage calls:

```python
# Replace this (Stage 6):
if "test_runner" not in result.completed_stages and result.test_files:
    self._run_stage("🏃 Test Runner", "Executing tests...", result, lambda: self._stage_test_runner(result))
    result.completed_stages.append("test_runner")
    self._save_checkpoint(result)
else:
    console.print("  ⏭️  [dim]🏃 Test Runner — skipped (checkpoint)[/dim]")

# With this:
if "test_runner" not in result.completed_stages and result.test_files:
    self._run_stage("🏃 Test Runner + Fix Loop", "Executing tests (with auto-fix)…", result, lambda: self._stage_test_fix_loop(result))
    result.completed_stages.append("test_runner")
    self._save_checkpoint(result)
else:
    console.print("  ⏭️  [dim]🏃 Test Runner + Fix Loop — skipped (checkpoint)[/dim]")
```

```python
# Replace this (Stage 8):
if "deploy_test_runner" not in result.completed_stages and result.deploy_files:
    self._run_stage("🐳 Deploy Test Runner", "Running docker smoke tests...", result, lambda: self._stage_deploy_test_runner(result))
    result.completed_stages.append("deploy_test_runner")
    self._save_checkpoint(result)
else:
    console.print("  ⏭️  [dim]🐳 Deploy Test Runner — skipped (checkpoint)[/dim]")

# With this:
if "deploy_test_runner" not in result.completed_stages and result.deploy_files:
    self._run_stage("🐳 Deploy Test Runner + Fix Loop", "Running deployment tests (with auto-fix)…", result, lambda: self._stage_deploy_fix_loop(result))
    result.completed_stages.append("deploy_test_runner")
    self._save_checkpoint(result)
else:
    console.print("  ⏭️  [dim]🐳 Deploy Test Runner + Fix Loop — skipped (checkpoint)[/dim]")
```

- [ ] **Step 10: Add config keys to `config.yaml`**

In `config.yaml` under the `pipeline:` section, after `max_revisions: 3`, add:

```yaml
  # Auto-fix retry loop: maximum engineer fix attempts when tests fail.
  # Set to 0 to disable. Applies to both unit tests and deployment tests.
  max_test_retries: 5
  max_deploy_retries: 5
```

- [ ] **Step 11: Run full test suite**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate
pytest tests/ -v --tb=short -q
```
Expected: all previously passing tests still pass

- [ ] **Step 12: Commit**

```bash
git add orchestrator.py config.yaml test_fix_loop.py
git commit -m "feat(orchestrator): wire TestFixLoopMixin for unit + deploy test auto-fix retry"
```

---

## Task 4: `BugFixOrchestrator` regression test runner + retry loop

**Files:**
- Modify: `bug_fix_orchestrator.py`
- Create: `tests/test_bug_fix_retry.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_bug_fix_retry.py`:

```python
"""Tests for BugFixOrchestrator test runner and retry wiring."""
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import MagicMock, patch
import pytest
from bug_fix_orchestrator import BugFixOrchestrator, BugFixResult


def _make_orchestrator():
    orch = BugFixOrchestrator.__new__(BugFixOrchestrator)
    orch.workspace_dir = __import__("pathlib").Path("/tmp/test_bug_fix_workspace")
    orch.github = None
    orch._target_gh = None
    orch._github_token = None
    orch.engineer = MagicMock()
    orch.max_test_retries = 3
    return orch


def test_bug_fix_result_has_retry_fields():
    result = BugFixResult(issue_number=1, issue_title="Bug", issue_body="desc")
    assert hasattr(result, "test_retry_count")
    assert result.test_retry_count == 0
    assert hasattr(result, "test_fix_history")
    assert result.test_fix_history == []
    assert hasattr(result, "tests_passed")
    assert result.tests_passed is None


def test_bug_fix_orchestrator_inherits_mixin():
    from test_fix_loop import TestFixLoopMixin
    assert issubclass(BugFixOrchestrator, TestFixLoopMixin)


def test_stage_test_runner_sets_passed_on_success(tmp_path):
    orch = _make_orchestrator()
    orch.workspace_dir = tmp_path
    result = BugFixResult(issue_number=42, issue_title="T", issue_body="B")
    result.test_files = {"tests/test_foo.py": "def test_dummy(): assert True"}

    # Write test file to disk so pytest can run it
    project_dir = tmp_path / "fix-issue-42"
    project_dir.mkdir()
    tests_dir = project_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_foo.py").write_text("def test_dummy(): assert True")

    orch._stage_test_runner(result)

    assert result.tests_passed is True
    assert "passed" in result.test_results.lower()


def test_stage_test_fix_loop_called_after_qa(tmp_path):
    orch = _make_orchestrator()
    orch.workspace_dir = tmp_path

    result = BugFixResult(issue_number=1, issue_title="Bug", issue_body="b")
    result.test_files = {}
    result.fixed_files = {}

    run_loop_calls = []

    with patch.object(orch, "_stage_test_runner"), \
         patch.object(orch, "run_test_fix_loop", side_effect=lambda **kw: run_loop_calls.append(kw)):
        orch._stage_test_fix_loop(result)

    assert len(run_loop_calls) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_bug_fix_retry.py -v
```
Expected: failures on missing `test_retry_count`, missing mixin inheritance, missing `_stage_test_runner`.

- [ ] **Step 3: Add retry fields to `BugFixResult`**

In `bug_fix_orchestrator.py`, find the `BugFixResult` dataclass. After `errors: list[str] = field(default_factory=list)`, add:

```python
    # Test-fix retry tracking
    tests_passed: Optional[bool] = None
    test_results: str = ""
    test_retry_count: int = 0
    test_fix_history: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Make `BugFixOrchestrator` inherit `TestFixLoopMixin`**

Change the class declaration:

```python
# Before
class BugFixOrchestrator:

# After
from test_fix_loop import TestFixLoopMixin

class BugFixOrchestrator(TestFixLoopMixin):
```

(Move the import to the top of the file with other imports.)

- [ ] **Step 5: Add `max_test_retries` to `BugFixOrchestrator.__init__`**

In `__init__`, after the last parameter, add:

```python
        max_test_retries: int = 5,
```

And store it:

```python
        self.max_test_retries = max_test_retries
```

- [ ] **Step 6: Update `BugFixOrchestrator.from_config()` to read `max_test_retries`**

In `from_config()`, add to the `return cls(...)` call:

```python
            max_test_retries=pipeline.get("max_test_retries", 5),
```

- [ ] **Step 7: Add `_stage_test_runner()` to `BugFixOrchestrator`**

Add after `_stage_qa()`:

```python
def _stage_test_runner(self, result: BugFixResult) -> None:
    """Run pytest on regression test files written to the local workspace."""
    import subprocess, sys
    project_dir = self.workspace_dir / f"fix-issue-{result.issue_number}"

    # Write test files to disk if not already present
    tests_dir = project_dir / "tests"
    if result.test_files:
        tests_dir.mkdir(parents=True, exist_ok=True)
        for filepath, content in result.test_files.items():
            full_path = project_dir / filepath
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")

    if not tests_dir.exists():
        console.print("    ⚠️  No tests/ directory found — skipping execution.")
        result.test_results = "No tests directory found."
        return

    console.print(f"    🏃 Running pytest in {tests_dir}…")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(tests_dir), "-v", "--tb=short",
             f"--rootdir={project_dir}", "-p", "no:cacheprovider", "--timeout=30"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        result.test_results = "Tests timed out after 5 minutes."
        result.tests_passed = False
        return

    output = proc.stdout + proc.stderr
    result.tests_passed = proc.returncode == 0
    result.test_results = output
    status = "✅ All tests passed" if result.tests_passed else "❌ Some tests failed"
    console.print(f"    {status}")

    lines = output.strip().splitlines()
    for line in lines[-20:]:
        console.print(f"    [dim]{line}[/dim]")

    if hasattr(self, "_target_gh") and self._target_gh and result.pr_number:
        truncated = "\n".join(lines[-60:]) if len(lines) > 60 else output
        self._target_gh.add_pr_comment(
            result.pr_number,
            f"## 🏃 Regression Test Results\n\n"
            f"**Status:** {status}\n\n```\n{truncated}\n```",
        )
```

- [ ] **Step 8: Add `_stage_test_fix_loop()` to `BugFixOrchestrator`**

Add after `_stage_test_runner()`:

```python
def _stage_test_fix_loop(self, result: BugFixResult) -> None:
    """Run regression tests and retry engineer fixes on failure."""
    project_dir = self.workspace_dir / f"fix-issue-{result.issue_number}"
    skip = {".git", "__pycache__", "node_modules"}

    def get_all_files_fn() -> dict:
        # Merge fixed_files and test_files; re-read from disk to capture prior patches
        files = {}
        if project_dir.exists():
            for path in sorted(project_dir.rglob("*")):
                if any(part in skip for part in path.parts):
                    continue
                if path.is_file() and path.suffix not in {".pyc", ".pyo"}:
                    try:
                        files[str(path.relative_to(project_dir))] = path.read_text(
                            encoding="utf-8", errors="replace"
                        )
                    except OSError:
                        pass
        return files or {**result.fixed_files, **result.test_files}

    def write_files_fn(patches: dict) -> None:
        for filepath, content in patches.items():
            full_path = project_dir / filepath
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
        # Keep result.fixed_files in sync so _finish() reports correctly
        result.fixed_files.update(patches)

    def commit_fn(attempt: int, patches: dict) -> bool:
        if hasattr(self, "_target_gh") and self._target_gh and result.branch:
            for filepath, content in patches.items():
                self._target_gh.commit_file(
                    path=filepath,
                    content=content,
                    message=f"fix(auto): regression test retry {attempt}/{self.max_test_retries}",
                    branch=result.branch,
                )
        return True

    def post_comment_fn(message: str) -> None:
        # Post on the tracker issue (self.github), not the code PR
        if self.github:
            self.github.add_issue_comment(result.issue_number, message)

    def fix_fn(failure_output: str, all_files: dict) -> dict:
        return self.engineer.fix_failures(
            failure_output=failure_output,
            all_files=all_files,
            design=result.diagnosis,
            project_name=f"Bug Fix #{result.issue_number}",
        )

    self.run_test_fix_loop(
        result=result,
        run_tests_fn=lambda r: self._stage_test_runner(r),
        get_all_files_fn=get_all_files_fn,
        write_files_fn=write_files_fn,
        commit_fn=commit_fn,
        post_comment_fn=post_comment_fn,
        fix_fn=fix_fn,
        max_retries=self.max_test_retries,
    )
```

- [ ] **Step 9: Wire pipeline — add Stage 5 and Stage 6 in `BugFixOrchestrator.run()`**

After the `_stage_qa` call (Stage 4), add:

```python
        # ── Stage 5: Run Regression Tests ────────────────────────────────────
        self._run_stage("🏃 Test Runner", "Running regression tests…", result, lambda: self._stage_test_runner(result))

        # ── Stage 6: Test Fix Loop ────────────────────────────────────────────
        if result.test_files and result.tests_passed is False:
            self._run_stage("🔁 Test Fix Loop", "Auto-fixing regression test failures…", result, lambda: self._stage_test_fix_loop(result))
```

- [ ] **Step 10: Run failing tests to verify they now pass**

```bash
pytest tests/test_bug_fix_retry.py -v
```
Expected: 4 passed

- [ ] **Step 11: Run full test suite**

```bash
pytest tests/ -v --tb=short -q
```
Expected: all previously passing tests still pass

- [ ] **Step 12: Commit**

```bash
git add bug_fix_orchestrator.py tests/test_bug_fix_retry.py
git commit -m "feat(bug-fix): add regression test runner + auto-fix retry loop to BugFixOrchestrator"
```

---

## Final verification

- [ ] **Run the complete test suite one last time**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate
pytest tests/ -v --tb=short
```
Expected: all tests pass. Count should include new tests from:
- `tests/test_engineer_fix.py` (5 tests)
- `tests/test_test_fix_loop.py` (6 tests)
- `tests/test_bug_fix_retry.py` (4 tests)

- [ ] **Verify `config.yaml` has both new keys**

```bash
grep "max_test_retries\|max_deploy_retries" config.yaml
```
Expected:
```
  max_test_retries: 5
  max_deploy_retries: 5
```

- [ ] **Final commit (if anything unstaged)**

```bash
git status
# If clean: nothing to do
# If dirty:
git add -A
git commit -m "chore: final cleanup for test retry loop feature"
```
