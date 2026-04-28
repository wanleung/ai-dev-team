# TDD Pipeline Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `pipeline.mode` config key (`standard` | `tdd`) that reorders pipeline stages so QA writes tests before Engineers implement code, plus a stage registry that makes the sequence extensible.

**Architecture:** A `PipelineStage` dataclass describes each post-architect stage. A `MODES` dict maps mode names to ordered stage name lists. `Orchestrator._build_stage_list()` resolves the active mode to an ordered list; `run()` iterates it instead of using hardcoded calls. A new `qa_write` stage calls `QAEngineerAgent` in `write_only=True` mode (tests-first, no execution). Engineers receive pre-written test files in their prompts when `result.test_files` is populated.

**Tech Stack:** Python 3.11+, dataclasses, pytest, existing orchestrator/agent patterns.

**Spec:** `docs/superpowers/specs/2026-04-27-tdd-pipeline-mode-design.md`

**Delivery:** Pull request `feature/tdd-pipeline-mode` → `master`.

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `agents/qa_engineer.py` | Add `write_only=False` param — skip prompt mentions of existing code and skip test execution |
| Modify | `agents/engineer.py` | Add `test_files=None` to `run_module`, `run_all_modules`, `run_with_github` — inject test content into prompt |
| Modify | `orchestrator.py` | Add `PipelineStage` dataclass, `MODES` dict, `_make_stage_registry()`, `_build_stage_list()`, `_stage_qa_write()`, refactor `run()` post-architect loop, read `mode`/`stages` from config |
| Modify | `config.yaml` | Document `pipeline.mode` and `pipeline.stages.<name>.skip` |
| Create | `tests/test_pipeline_modes.py` | All new tests for this feature |

---

## Task 1: QAEngineerAgent `write_only` mode

**Files:**
- Modify: `agents/qa_engineer.py`
- Test: `tests/test_pipeline_modes.py`

- [ ] **Step 1: Create the test file with a failing test**

```python
# tests/test_pipeline_modes.py
"""Tests for TDD pipeline mode: stage registry, mode config, QA write-only, engineer test injection."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ── Task 1: QAEngineerAgent write_only ───────────────────────────────────────

def test_qa_engineer_write_only_returns_test_files_without_running():
    """write_only=True returns test_files and skips test execution."""
    from agents.qa_engineer import QAEngineerAgent

    agent = QAEngineerAgent.__new__(QAEngineerAgent)
    agent._tool_registry = None
    agent.call = MagicMock(return_value=(
        "### FILE: tests/test_auth.py\n```python\ndef test_login(): pass\n```"
    ))

    result = agent.run({}, "PRD text", project_name="myapp", write_only=True)

    assert "tests/test_auth.py" in result["test_files"]
    assert result.get("tests_ran") is False


def test_qa_engineer_write_only_prompt_does_not_mention_implemented_code():
    """write_only prompt should say 'write tests that define expected behavior', not 'verify implemented code'."""
    from agents.qa_engineer import QAEngineerAgent

    agent = QAEngineerAgent.__new__(QAEngineerAgent)
    agent._tool_registry = None
    captured = {}
    def capture_call(prompt):
        captured["prompt"] = prompt
        return "### FILE: tests/test_foo.py\n```python\npass\n```"
    agent.call = capture_call

    agent.run({}, "PRD text", project_name="myapp", write_only=True)

    assert "define the expected behavior" in captured["prompt"]
    assert "Implemented code" not in captured["prompt"]


def test_qa_engineer_normal_mode_unchanged():
    """Normal run() (write_only=False default) works as before."""
    from agents.qa_engineer import QAEngineerAgent

    agent = QAEngineerAgent.__new__(QAEngineerAgent)
    agent._tool_registry = None
    agent.call = MagicMock(return_value=(
        "### FILE: tests/test_foo.py\n```python\ndef test_x(): pass\n```\n"
        "## Test Plan\nsome plan"
    ))

    result = agent.run({"main.py": "print('hi')"}, "PRD", project_name="p")

    assert "tests/test_foo.py" in result["test_files"]
    # Normal mode does NOT set tests_ran=False
    assert "tests_ran" not in result
```

- [ ] **Step 2: Run to confirm failures**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_pipeline_modes.py::test_qa_engineer_write_only_returns_test_files_without_running tests/test_pipeline_modes.py::test_qa_engineer_write_only_prompt_does_not_mention_implemented_code -v 2>&1 | tail -20
```

Expected: FAIL — `QAEngineerAgent.run() got an unexpected keyword argument 'write_only'`

- [ ] **Step 3: Add `write_only` param to `QAEngineerAgent.run()`**

In `agents/qa_engineer.py`, modify the `run()` signature and body:

```python
def run(self, files: dict[str, str], prd: str, project_name: str = "Project",
        test_plan: str = "", write_only: bool = False) -> dict:
    """Generate tests for the implemented code (or write-first tests in TDD mode).

    Args:
        files: dict of {filepath: file_content} from EngineerAgent. Pass {} in TDD mode.
        prd: PRD markdown for acceptance criteria.
        project_name: Project name for context.
        test_plan: Optional structured Test Plan from QAPlannerAgent.
        write_only: If True (TDD mode), write tests that define expected behaviour without
                    running them. Prompt changes to test-first perspective.

    Returns:
        dict with keys:
            - test_files (dict): {filepath: test_content} for all test files
            - test_plan (str): Test plan summary markdown
            - raw_response (str): Full LLM response
            - tests_ran (bool): False only when write_only=True
    """
    plan_section = (
        f"\n\n**Test Plan from QA Planner (implement these test cases):**\n---\n{test_plan[:4000]}\n---"
        if test_plan
        else ""
    )

    if write_only:
        prompt = (
            f"You are writing tests for the project '{project_name}' BEFORE the code is implemented.\n\n"
            f"**PRD (acceptance criteria that define the expected behavior):**\n---\n{prd}\n---"
            f"{plan_section}\n\n"
            f"Write pytest tests that define the expected behavior of each module. "
            f"These tests will be given to engineers as a specification — they must write code to make them pass.\n"
            f"Focus on interface contracts, inputs/outputs, and acceptance criteria. "
            f"Use '### FILE: tests/test_xxx.py' format for each test file."
        )
    else:
        # Original prompt (unchanged)
        files_for_qa = self.truncate_files(files, max_chars=10_000)
        code_section = "\n\n".join(
            f"### FILE: {path}\n```python\n{content}\n```" for path, content in files_for_qa.items()
        )
        prompt = (
            f"You are writing tests for the project '{project_name}'.\n\n"
            f"**PRD (acceptance criteria to validate):**\n---\n{prd}\n---"
            f"{plan_section}\n\n"
            f"**Implemented code:**\n\n{code_section}\n\n"
            f"Write comprehensive pytest tests following your role instructions. "
            f"Use '### FILE: tests/test_xxx.py' format for each test file."
        )

    if self._tool_registry is not None and not write_only:
        rag_hint = (
            "\n\nYou have access to the `search_codebase` RAG tool. "
            "Use it to find relevant existing code patterns before writing tests."
        )
        try:
            response = self.call_with_tools(prompt + rag_hint, tools=self._tool_registry)
        except NotImplementedError:
            response = self.call(prompt)
    else:
        response = self.call(prompt)

    test_files = self._parse_test_files(response)
    extracted_plan = self._extract_test_plan(response)

    result = {
        "test_files": test_files,
        "test_plan": extracted_plan,
        "raw_response": response,
    }
    if write_only:
        result["tests_ran"] = False
    return result
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_pipeline_modes.py::test_qa_engineer_write_only_returns_test_files_without_running tests/test_pipeline_modes.py::test_qa_engineer_write_only_prompt_does_not_mention_implemented_code tests/test_pipeline_modes.py::test_qa_engineer_normal_mode_unchanged -v 2>&1 | tail -15
```

Expected: 3 passed

- [ ] **Step 5: Verify existing QA tests still pass**

```bash
python -m pytest tests/test_qa_planner.py -v 2>&1 | tail -10
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add agents/qa_engineer.py tests/test_pipeline_modes.py
git commit -m "feat: QAEngineerAgent write_only mode for TDD pipeline

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: EngineerAgent test file injection

**Files:**
- Modify: `agents/engineer.py`
- Test: `tests/test_pipeline_modes.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_pipeline_modes.py`:

```python
# ── Task 2: EngineerAgent test_files injection ───────────────────────────────

def test_engineer_run_module_injects_test_files_into_prompt():
    """When test_files is provided, the prompt includes their content."""
    from agents.engineer import EngineerAgent

    agent = EngineerAgent.__new__(EngineerAgent)
    agent._tool_registry = None
    captured = {}
    def capture_call(prompt):
        captured["prompt"] = prompt
        return "### FILE: auth.py\n```python\npass\n```"
    agent.call = capture_call
    agent._parse_files = MagicMock(return_value={"auth.py": "pass"})

    agent.run_module(
        design="design",
        module={"name": "auth", "description": "auth module"},
        project_name="myapp",
        test_files={"tests/test_auth.py": "def test_login(): pass"},
    )

    assert "Pre-written tests" in captured["prompt"]
    assert "tests/test_auth.py" in captured["prompt"]
    assert "def test_login(): pass" in captured["prompt"]


def test_engineer_run_module_no_test_files_unchanged():
    """When test_files is absent, the prompt is unchanged (no test section)."""
    from agents.engineer import EngineerAgent

    agent = EngineerAgent.__new__(EngineerAgent)
    agent._tool_registry = None
    captured = {}
    def capture_call(prompt):
        captured["prompt"] = prompt
        return "### FILE: auth.py\n```python\npass\n```"
    agent.call = capture_call
    agent._parse_files = MagicMock(return_value={"auth.py": "pass"})

    agent.run_module(
        design="design",
        module={"name": "auth", "description": "auth module"},
        project_name="myapp",
    )

    assert "Pre-written tests" not in captured["prompt"]
```

- [ ] **Step 2: Run to confirm failures**

```bash
python -m pytest tests/test_pipeline_modes.py::test_engineer_run_module_injects_test_files_into_prompt tests/test_pipeline_modes.py::test_engineer_run_module_no_test_files_unchanged -v 2>&1 | tail -10
```

Expected: FAIL — `run_module() got an unexpected keyword argument 'test_files'`

- [ ] **Step 3: Add `test_files` param to `run_module()`**

In `agents/engineer.py`, modify `run_module()`:

```python
def run_module(
    self,
    design: str,
    module: dict,
    project_name: str = "Project",
    framework_context: str = "",
    all_files: dict[str, str] | None = None,
    test_files: dict[str, str] | None = None,
) -> dict:
    """Implement a single module.

    Args:
        design: Full system design markdown.
        module: Module dict with 'name' and 'description' keys.
        project_name: Project name for context.
        framework_context: Optional framework documentation to inject into the prompt.
        all_files: Optional dict of already-implemented files (used by senior engineer).
        test_files: Optional dict of pre-written test files (TDD mode). When provided,
                    the engineer is instructed to make these tests pass.

    Returns:
        dict with keys:
            - module_name (str): The module name
            - files (dict): {filepath: file_content} for all generated files
            - raw_response (str): Full LLM response
    """
    framework_section = f"## Framework Documentation\n\n{framework_context}\n\n" if framework_context else ""
    scaffold_hint = "\n\n> Note: If you scaffold a new project, check for AGENTS.md afterwards for framework-specific guidance." if not framework_context else ""

    test_section = ""
    if test_files:
        test_content = "\n\n".join(
            f"### FILE: {path}\n```python\n{content}\n```"
            for path, content in test_files.items()
        )
        test_section = (
            f"\n\n## Pre-written tests your implementation must pass\n\n"
            f"{test_content}\n\n"
            f"Implement the module so all of the above tests pass. "
            f"Do not modify the test files."
        )

    prompt = (
        f"{framework_section}"
        f"You are implementing the '{module['name']}' module for the project '{project_name}'.\n\n"
        f"Module description: {module.get('description', '')}\n\n"
        f"Full System Design:\n---\n{design}\n---"
        f"{test_section}\n\n"
        f"Please implement ALL files for this module. "
        f"Output each file using the '### FILE: path/to/file.py' format as instructed."
        f"{scaffold_hint}"
    )

    if self._tool_registry is not None:
        rag_hint = (
            "\n\nYou have access to RAG search tools: `search_codebase` and `search_docs`. "
            "Use them to find relevant existing code patterns and documentation before implementing."
        )
        try:
            response = self.call_with_tools(prompt + rag_hint, tools=self._tool_registry)
        except NotImplementedError:
            response = self.call(prompt)
    else:
        response = self.call(prompt)
    files = self._parse_files(response)

    return {
        "module_name": module["name"],
        "files": files,
        "raw_response": response,
    }
```

- [ ] **Step 4: Add `test_files` param to `run_all_modules()`**

```python
def run_all_modules(
    self,
    design: str,
    modules: list[dict],
    project_name: str = "Project",
    max_workers: int = 3,
    framework_context: str = "",
    test_files: dict[str, str] | None = None,
) -> dict:
    """Implement multiple modules in parallel using a thread pool."""
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for i, mod in enumerate(modules):
            if i > 0:
                time.sleep(2)
            futures.append(
                executor.submit(
                    self.run_module, design, mod, project_name, framework_context,
                    None, test_files  # all_files=None, test_files=test_files
                )
            )
        for future in futures:
            result = future.result()
            results.append(result)

    all_files: dict[str, str] = {}
    for result in results:
        all_files.update(result["files"])

    return {"modules": results, "all_files": all_files}
```

- [ ] **Step 5: Add `test_files` param to `run_with_github()`**

```python
def run_with_github(
    self,
    design: str,
    modules: list[dict],
    project_name: str,
    github_client,
    branch_prefix: str = "feature/agent",
    issue_number: Optional[int] = None,
    max_workers: int = 3,
    framework_context: str = "",
    test_files: dict[str, str] | None = None,
) -> dict:
    """Run all modules and commit code to GitHub on a feature branch, then open a PR."""
    result = self.run_all_modules(
        design, modules, project_name, max_workers,
        framework_context=framework_context, test_files=test_files
    )
    # ... rest of method unchanged (branch creation, commits, PR) ...
```

Note: only the `run_all_modules` call changes — add `test_files=test_files`. The rest of the method body is unchanged.

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/test_pipeline_modes.py::test_engineer_run_module_injects_test_files_into_prompt tests/test_pipeline_modes.py::test_engineer_run_module_no_test_files_unchanged -v 2>&1 | tail -10
```

Expected: 2 passed

- [ ] **Step 7: Verify existing engineer tests still pass**

```bash
python -m pytest tests/test_junior_senior_engineer.py -v 2>&1 | tail -10
```

Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add agents/engineer.py tests/test_pipeline_modes.py
git commit -m "feat: EngineerAgent accepts test_files for TDD mode

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: `PipelineStage` dataclass and `MODES` dict

**Files:**
- Modify: `orchestrator.py` (top of file, after imports)
- Test: `tests/test_pipeline_modes.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_pipeline_modes.py`:

```python
# ── Task 3: PipelineStage + MODES ────────────────────────────────────────────

def test_modes_dict_standard_contains_expected_stages():
    from orchestrator import MODES
    standard = MODES["standard"]
    assert "tier_review" in standard
    assert "junior_engineer" in standard
    assert "senior_engineer" in standard
    assert "reviewer" in standard
    assert "qa_planner" in standard
    assert "qa_engineer" in standard
    assert "test_fix" in standard
    assert "deploy_tester" in standard
    assert "deploy_fix" in standard
    # qa_write must NOT be in standard mode
    assert "qa_write" not in standard


def test_modes_dict_tdd_contains_qa_write_before_engineers():
    from orchestrator import MODES
    tdd = MODES["tdd"]
    assert "qa_write" in tdd
    assert "qa_planner" in tdd
    qa_write_idx = tdd.index("qa_write")
    jr_idx = tdd.index("junior_engineer")
    sr_idx = tdd.index("senior_engineer")
    assert qa_write_idx < jr_idx
    assert qa_write_idx < sr_idx


def test_modes_dict_tdd_has_reviewer_after_test_fix():
    from orchestrator import MODES
    tdd = MODES["tdd"]
    reviewer_idx = tdd.index("reviewer")
    test_fix_idx = tdd.index("test_fix")
    assert reviewer_idx > test_fix_idx


def test_modes_dict_tdd_has_no_qa_engineer():
    """TDD mode uses qa_write instead of qa_engineer."""
    from orchestrator import MODES
    assert "qa_engineer" not in MODES["tdd"]
```

- [ ] **Step 2: Run to confirm failures**

```bash
python -m pytest tests/test_pipeline_modes.py::test_modes_dict_standard_contains_expected_stages tests/test_pipeline_modes.py::test_modes_dict_tdd_contains_qa_write_before_engineers -v 2>&1 | tail -10
```

Expected: FAIL — `cannot import name 'MODES' from 'orchestrator'`

- [ ] **Step 3: Add `PipelineStage` dataclass and `MODES` to `orchestrator.py`**

After the existing imports (near the top of `orchestrator.py`, before the `Orchestrator` class), add:

```python
from dataclasses import dataclass, field as dc_field
from typing import Callable


@dataclass
class PipelineStage:
    """Describes a single executable stage in the pipeline."""

    name: str
    """Identifier — used in MODES lists and per-stage config."""

    label: str
    """Display label shown in the Rich console (with emoji)."""

    description: str
    """Progress message shown while the stage runs."""

    checkpoint_key: str
    """Key written to PipelineResult.completed_stages when the stage finishes."""

    fn: "Callable[[PipelineResult], None]"
    """The stage callable. Receives the current PipelineResult."""

    skip_if: "Callable[[PipelineResult], bool]" = dc_field(
        default_factory=lambda: lambda r: False
    )
    """Return True to skip this stage conditionally (e.g. no test_files yet)."""

    stop_if: "Callable[[PipelineResult], bool]" = dc_field(
        default_factory=lambda: lambda r: False
    )
    """Return True after the stage runs to halt the pipeline early."""


MODES: dict[str, list[str]] = {
    # Standard waterfall: engineers then QA
    "standard": [
        "tier_review",
        "junior_engineer",
        "senior_engineer",
        "reviewer",
        "qa_planner",
        "qa_engineer",
        "test_fix",
        "deploy_tester",
        "deploy_fix",
    ],
    # TDD: QA writes tests first, engineers implement against them
    "tdd": [
        "qa_planner",
        "qa_write",
        "tier_review",
        "junior_engineer",
        "senior_engineer",
        "test_fix",
        "reviewer",
        "deploy_tester",
        "deploy_fix",
    ],
}
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_pipeline_modes.py::test_modes_dict_standard_contains_expected_stages tests/test_pipeline_modes.py::test_modes_dict_tdd_contains_qa_write_before_engineers tests/test_pipeline_modes.py::test_modes_dict_tdd_has_reviewer_after_test_fix tests/test_pipeline_modes.py::test_modes_dict_tdd_has_no_qa_engineer -v 2>&1 | tail -10
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py tests/test_pipeline_modes.py
git commit -m "feat: PipelineStage dataclass and MODES registry

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 4: `Orchestrator` config reading and `_build_stage_list()`

**Files:**
- Modify: `orchestrator.py` (`__init__`, `from_config`, `_make_stage_registry`, `_build_stage_list`)
- Test: `tests/test_pipeline_modes.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_pipeline_modes.py`:

```python
# ── Task 4: Orchestrator config + _build_stage_list ──────────────────────────

def _make_minimal_orch(mode: str = "standard", stage_skips: dict | None = None):
    """Build a minimal Orchestrator with mode set, all agents mocked."""
    from orchestrator import Orchestrator
    o = Orchestrator.__new__(Orchestrator)
    # Set all attrs that _make_stage_registry references
    o._mode = mode
    o._stage_skips = stage_skips or {}
    o.stop_on_review_issues = False
    # Minimal agents (lambdas are fine — we only build the list, not run it)
    o._stage_tier_review = lambda r: None
    o._stage_junior_engineer = lambda r: None
    o._stage_senior_engineer = lambda r: None
    o._stage_reviewer = lambda r: None
    o._stage_qa_planner = lambda r: None
    o._stage_qa = lambda r: None
    o._stage_qa_write = lambda r: None
    o._stage_test_fix_loop = lambda r: None
    o._stage_deployment_tester = lambda r: None
    o._stage_deploy_fix_loop = lambda r: None
    return o


def test_build_stage_list_standard_order():
    o = _make_minimal_orch(mode="standard")
    stages = o._build_stage_list()
    names = [s.name for s in stages]
    assert names.index("tier_review") < names.index("junior_engineer")
    assert names.index("junior_engineer") < names.index("reviewer")
    assert names.index("reviewer") < names.index("qa_planner")
    assert names.index("qa_planner") < names.index("qa_engineer")
    assert "qa_write" not in names


def test_build_stage_list_tdd_order():
    o = _make_minimal_orch(mode="tdd")
    stages = o._build_stage_list()
    names = [s.name for s in stages]
    assert names.index("qa_write") < names.index("junior_engineer")
    assert names.index("test_fix") < names.index("reviewer")
    assert "qa_engineer" not in names


def test_build_stage_list_respects_skip_config():
    o = _make_minimal_orch(mode="standard", stage_skips={"reviewer": True})
    stages = o._build_stage_list()
    names = [s.name for s in stages]
    assert "reviewer" not in names


def test_orchestrator_from_config_reads_mode(tmp_path, monkeypatch):
    import yaml, os
    from orchestrator import Orchestrator

    cfg = {
        "llm": {"model": "openai/gpt-4.1-mini"},
        "pipeline": {
            "mode": "tdd",
            "stages": {"reviewer": {"skip": True}},
        },
    }
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(cfg))
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")

    o = Orchestrator.from_config(str(cfg_file))
    assert o._mode == "tdd"
    assert o._stage_skips.get("reviewer") is True


def test_orchestrator_from_config_defaults_to_standard(tmp_path, monkeypatch):
    import yaml
    from orchestrator import Orchestrator

    cfg = {"llm": {"model": "openai/gpt-4.1-mini"}, "pipeline": {}}
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(cfg))
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")

    o = Orchestrator.from_config(str(cfg_file))
    assert o._mode == "standard"
    assert o._stage_skips == {}
```

- [ ] **Step 2: Run to confirm failures**

```bash
python -m pytest tests/test_pipeline_modes.py::test_build_stage_list_standard_order tests/test_pipeline_modes.py::test_build_stage_list_tdd_order -v 2>&1 | tail -10
```

Expected: FAIL — `Orchestrator has no attribute '_build_stage_list'`

- [ ] **Step 3: Add `_mode` and `_stage_skips` to `Orchestrator.__init__`**

In `orchestrator.py`, add to `Orchestrator.__init__` parameters:

```python
def __init__(
    self,
    ...  # existing params
    pipeline_mode: str = "standard",
    stage_skips: dict[str, bool] | None = None,
):
    ...
    self._mode: str = pipeline_mode
    self._stage_skips: dict[str, bool] = stage_skips or {}
```

- [ ] **Step 4: Update `from_config()` to read `mode` and `stages`**

In the `from_config()` method, after `pipeline = cfg.get("pipeline", {})`, add:

```python
pipeline_mode = pipeline.get("mode", "standard")
stage_skips = {
    name: bool(opts.get("skip", False))
    for name, opts in pipeline.get("stages", {}).items()
}
```

And pass to `cls(...)`:

```python
return cls(
    ...  # existing args
    pipeline_mode=pipeline_mode,
    stage_skips=stage_skips,
)
```

- [ ] **Step 5: Add `_make_stage_registry()` and `_build_stage_list()` methods**

Add these two methods to the `Orchestrator` class (after `__init__`):

```python
def _make_stage_registry(self) -> dict[str, "PipelineStage"]:
    """Build the full registry of all known pipeline stages."""
    return {
        "tier_review": PipelineStage(
            name="tier_review",
            label="🏷️  Tier Review",
            description="Classifying modules into junior/senior tiers...",
            checkpoint_key="tier_review",
            fn=lambda r: self._stage_tier_review(r),
        ),
        "junior_engineer": PipelineStage(
            name="junior_engineer",
            label="🟢 Junior Engineers",
            description="Implementing junior module(s)...",
            checkpoint_key="junior_engineer",
            fn=lambda r: self._stage_junior_engineer(r),
            skip_if=lambda r: "engineer" in r.completed_stages,
        ),
        "senior_engineer": PipelineStage(
            name="senior_engineer",
            label="🔵 Senior Engineers",
            description="Implementing senior module(s)...",
            checkpoint_key="senior_engineer",
            fn=lambda r: self._stage_senior_engineer(r),
            skip_if=lambda r: "engineer" in r.completed_stages,
            stop_if=lambda r: bool(r.errors),
        ),
        "reviewer": PipelineStage(
            name="reviewer",
            label="🔍 Code Reviewer",
            description="Reviewing generated code...",
            checkpoint_key="reviewer",
            fn=lambda r: self._stage_reviewer(r),
            stop_if=lambda r: self.stop_on_review_issues and r.verdict == "CHANGES REQUESTED",
        ),
        "qa_planner": PipelineStage(
            name="qa_planner",
            label="📋 QA Planner",
            description="Creating test plan & acceptance criteria...",
            checkpoint_key="qa_planner",
            fn=lambda r: self._stage_qa_planner(r),
        ),
        "qa_engineer": PipelineStage(
            name="qa_engineer",
            label="🧪 QA Engineer",
            description="Writing tests & producing test plan...",
            checkpoint_key="qa",
            fn=lambda r: self._stage_qa(r),
        ),
        "qa_write": PipelineStage(
            name="qa_write",
            label="✍️  QA Write (TDD)",
            description="Writing tests before implementation...",
            checkpoint_key="qa_write",
            fn=lambda r: self._stage_qa_write(r),
        ),
        "test_fix": PipelineStage(
            name="test_fix",
            label="🏃 Test Runner + Fix Loop",
            description="Executing tests (with auto-fix)…",
            checkpoint_key="test_runner",
            fn=lambda r: self._stage_test_fix_loop(r),
            skip_if=lambda r: not r.test_files,
        ),
        "deploy_tester": PipelineStage(
            name="deploy_tester",
            label="🚀 Deployment Tester",
            description="Generating deployment smoke tests...",
            checkpoint_key="deployment_tester",
            fn=lambda r: self._stage_deployment_tester(r),
        ),
        "deploy_fix": PipelineStage(
            name="deploy_fix",
            label="🐳 Deploy Test Runner + Fix Loop",
            description="Running deployment tests (with auto-fix)…",
            checkpoint_key="deploy_test_runner",
            fn=lambda r: self._stage_deploy_fix_loop(r),
            skip_if=lambda r: not r.deploy_files,
        ),
    }

def _build_stage_list(self) -> list["PipelineStage"]:
    """Return the ordered stage list for the active mode, with config skips applied."""
    registry = self._make_stage_registry()
    stage_names = MODES.get(self._mode, MODES["standard"])
    return [
        registry[name]
        for name in stage_names
        if name in registry and not self._stage_skips.get(name, False)
    ]
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/test_pipeline_modes.py::test_build_stage_list_standard_order tests/test_pipeline_modes.py::test_build_stage_list_tdd_order tests/test_pipeline_modes.py::test_build_stage_list_respects_skip_config tests/test_pipeline_modes.py::test_orchestrator_from_config_reads_mode tests/test_pipeline_modes.py::test_orchestrator_from_config_defaults_to_standard -v 2>&1 | tail -15
```

Expected: 5 passed

- [ ] **Step 7: Commit**

```bash
git add orchestrator.py tests/test_pipeline_modes.py
git commit -m "feat: stage registry and _build_stage_list() with mode + skip config

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 5: `_stage_qa_write()` and engineer test injection in orchestrator

**Files:**
- Modify: `orchestrator.py`
- Test: `tests/test_pipeline_modes.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_pipeline_modes.py`:

```python
# ── Task 5: _stage_qa_write + engineer injection ─────────────────────────────

def test_stage_qa_write_populates_result_test_files():
    """_stage_qa_write() calls qa.run(write_only=True) and stores results."""
    from orchestrator import Orchestrator, PipelineResult

    o = Orchestrator.__new__(Orchestrator)
    o.qa = MagicMock()
    o.qa.run.return_value = {
        "test_files": {"tests/test_auth.py": "def test_login(): pass"},
        "test_plan": "plan",
        "raw_response": "raw",
        "tests_ran": False,
    }
    o._save_files_locally = MagicMock()

    result = PipelineResult(requirement="build app")
    result.prd = "PRD text"
    result.project_name = "myapp"
    result.qa_plan = ""

    o._stage_qa_write(result)

    o.qa.run.assert_called_once()
    call_kwargs = o.qa.run.call_args
    assert call_kwargs.kwargs.get("write_only") is True or (
        len(call_kwargs.args) >= 5 and call_kwargs.args[4] is True
    )
    assert "tests/test_auth.py" in result.test_files


def test_stage_junior_engineer_passes_test_files_in_tdd_mode():
    """In TDD mode, _stage_junior_engineer passes result.test_files to run_with_github."""
    from orchestrator import Orchestrator, PipelineResult

    o = Orchestrator.__new__(Orchestrator)
    o._mode = "tdd"
    o.junior_engineer = MagicMock()
    o.junior_engineer.run_with_github.return_value = {
        "all_files": {}, "branch": "feat/x", "pr_number": 1, "pr_url": "http://x",
    }
    o.junior_engineer.run_all_modules.return_value = {"all_files": {}}
    o.workspace_dir = MagicMock()
    o.workspace_dir.__truediv__ = lambda s, x: MagicMock(resolve=lambda: "/tmp/x")
    o.framework_docs_loader = MagicMock(load=MagicMock(return_value=""))
    o.target_github = None
    o.num_junior_engineers = 1
    o._save_files_locally = MagicMock()

    result = PipelineResult(requirement="x")
    result.design = "design"
    result.project_name = "myapp"
    result.modules = [{"name": "auth", "description": "auth", "tier": "junior"}]
    result.test_files = {"tests/test_auth.py": "def test_login(): pass"}
    result.junior_files = {}

    o._stage_junior_engineer(result)

    call_kwargs = o.junior_engineer.run_all_modules.call_args
    # test_files should be passed
    assert call_kwargs.kwargs.get("test_files") == result.test_files or \
           result.test_files in call_kwargs.args
```

- [ ] **Step 2: Run to confirm failures**

```bash
python -m pytest tests/test_pipeline_modes.py::test_stage_qa_write_populates_result_test_files tests/test_pipeline_modes.py::test_stage_junior_engineer_passes_test_files_in_tdd_mode -v 2>&1 | tail -10
```

Expected: FAIL

- [ ] **Step 3: Add `_stage_qa_write()` to `orchestrator.py`**

Add this method to `Orchestrator`, near `_stage_qa()`:

```python
def _stage_qa_write(self, result: PipelineResult) -> None:
    """TDD mode: write tests before engineers implement code.

    Calls QAEngineerAgent in write_only=True mode. Tests are stored in
    result.test_files for consumption by the engineer stages.
    No files are committed to GitHub at this point.
    """
    qa_result = self.qa.run(
        {},                         # no code yet — tests are written from PRD alone
        result.prd,
        result.project_name,
        test_plan=result.qa_plan,
        write_only=True,
    )
    result.test_files = qa_result["test_files"]
    result.test_plan = qa_result.get("test_plan", "")
    self._save_files_locally(result.test_files, result.project_name)
```

- [ ] **Step 4: Update `_stage_junior_engineer()` to pass `test_files` in TDD mode**

In `_stage_junior_engineer()`, find the two call sites (`run_with_github` and `run_all_modules`) and add `test_files`:

```python
# run_with_github call (when target_github is set)
eng_result = self.junior_engineer.run_with_github(
    result.design,
    junior_modules,
    result.project_name,
    self.target_github,
    branch_prefix=self.branch_prefix,
    issue_number=result.issue_number,
    max_workers=self.num_junior_engineers,
    framework_context=framework_context,
    test_files=result.test_files if self._mode == "tdd" else None,
)

# run_all_modules call (local only)
eng_result = self.junior_engineer.run_all_modules(
    result.design,
    junior_modules,
    result.project_name,
    max_workers=self.num_junior_engineers,
    framework_context=framework_context,
    test_files=result.test_files if self._mode == "tdd" else None,
)
```

- [ ] **Step 5: Update `_stage_senior_engineer()` similarly**

In `_stage_senior_engineer()`, find the `executor.submit(self.senior_engineer.run_module, ...)` call and add `test_files`:

```python
futures = [
    executor.submit(
        self.senior_engineer.run_module,
        result.design,
        mod,
        result.project_name,
        framework_context,
        result.junior_files,
        result.test_files if self._mode == "tdd" else None,
    )
    for mod in senior_modules
]
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/test_pipeline_modes.py::test_stage_qa_write_populates_result_test_files tests/test_pipeline_modes.py::test_stage_junior_engineer_passes_test_files_in_tdd_mode -v 2>&1 | tail -10
```

Expected: 2 passed

- [ ] **Step 7: Commit**

```bash
git add orchestrator.py tests/test_pipeline_modes.py
git commit -m "feat: _stage_qa_write and TDD test_files injection into engineer stages

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 6: Refactor `run()` to use the stage loop

**Files:**
- Modify: `orchestrator.py` — replace hardcoded post-architect stages with `_build_stage_list()` loop
- Test: `tests/test_pipeline_modes.py`

- [ ] **Step 1: Write a regression test before refactoring**

Add to `tests/test_pipeline_modes.py`:

```python
# ── Task 6: run() stage loop ──────────────────────────────────────────────────

def _make_full_orch(mode: str = "standard"):
    """Build a minimal but runnable Orchestrator with all stages mocked."""
    from orchestrator import Orchestrator, PipelineResult
    import types

    o = Orchestrator.__new__(Orchestrator)
    o._mode = mode
    o._stage_skips = {}
    o.stop_on_review_issues = False
    o.stop_on_design_issues = False
    o.stop_on_prd_issues = False
    o.max_prd_revisions = 0
    o.max_design_revisions = 0
    o.workspace_dir = MagicMock()
    o.github = None
    o.target_github = None
    o.memory = MagicMock(recall=MagicMock(return_value=None))
    o.skill_loader = None
    o.repo_context_loader = None
    o.repo_auto_indexer = None
    o._github_token = None

    # Minimal result fixture
    def fake_load_checkpoint(req):
        return None
    def fake_save_checkpoint(r): pass
    def fake_clear_checkpoint(r): pass
    def fake_finish(r, t):
        return r
    o._load_checkpoint = fake_load_checkpoint
    o._save_checkpoint = fake_save_checkpoint
    o._clear_checkpoint = fake_clear_checkpoint
    o._finish = fake_finish

    # All stage methods stubbed — record calls
    called = []
    def make_stub(name):
        def stub(r):
            called.append(name)
        return stub

    stage_names = [
        "_stage_tier_review", "_stage_junior_engineer", "_stage_senior_engineer",
        "_stage_reviewer", "_stage_qa_planner", "_stage_qa", "_stage_qa_write",
        "_stage_test_fix_loop", "_stage_deployment_tester", "_stage_deploy_fix_loop",
    ]
    for name in stage_names:
        setattr(o, name, make_stub(name))

    # Minimal PRD/design loop stubs
    def fake_prd_loop(r, req):
        r.prd = "PRD"
        r.project_name = "myapp"
        r.completed_stages.append("pm_review_loop")
        return True
    def fake_design_loop(r):
        r.design = "design"
        r.modules = [{"name": "auth", "description": "auth", "tier": "junior"}]
        r.completed_stages.append("architect_review_loop")
        return True

    o._prd_revision_loop = fake_prd_loop
    o._design_revision_loop = fake_design_loop
    o._run_stage = MagicMock(side_effect=lambda label, desc, r, fn: fn())

    return o, called


def test_run_standard_mode_calls_qa_engineer_not_qa_write():
    from orchestrator import PipelineResult
    o, called = _make_full_orch(mode="standard")
    result = PipelineResult(requirement="build x")
    # need test_files to avoid test_fix skip
    # (skip_if checks r.test_files — leave empty to skip test_fix)
    o.run("build x")
    assert "_stage_qa" in called
    assert "_stage_qa_write" not in called


def test_run_tdd_mode_calls_qa_write_not_qa_engineer():
    from orchestrator import PipelineResult
    o, called = _make_full_orch(mode="tdd")
    o.run("build x")
    assert "_stage_qa_write" in called
    assert "_stage_qa" not in called


def test_run_tdd_mode_qa_write_before_junior_engineer():
    o, called = _make_full_orch(mode="tdd")
    o.run("build x")
    assert called.index("_stage_qa_write") < called.index("_stage_junior_engineer")


def test_run_tdd_mode_test_fix_before_reviewer():
    o, called = _make_full_orch(mode="tdd")
    # give test_files so test_fix isn't skipped
    def fake_qa_write(r):
        r.test_files = {"tests/test_foo.py": "pass"}
        called.append("_stage_qa_write")
    o._stage_qa_write = fake_qa_write
    o.run("build x")
    assert called.index("_stage_test_fix_loop") < called.index("_stage_reviewer")
```

- [ ] **Step 2: Run tests before refactor (they should fail)**

```bash
python -m pytest tests/test_pipeline_modes.py::test_run_standard_mode_calls_qa_engineer_not_qa_write tests/test_pipeline_modes.py::test_run_tdd_mode_calls_qa_write_not_qa_engineer -v 2>&1 | tail -10
```

Expected: FAIL — the stage loop doesn't exist yet.

- [ ] **Step 3: Refactor `run()` — replace post-architect hardcoded blocks**

In `run()`, find the section starting from "Stage 3: Engineers" (after the design revision loop) through the end of the method (before `self._clear_checkpoint(result)`). Replace it with:

```python
        # ── RAG index (always before engineer, not mode-dependent) ─────────────
        if self.repo_auto_indexer and self.target_github and "rag_index" not in result.completed_stages:
            self._run_stage(
                "📦 RAG Index",
                "Indexing repo codebase into RAG...",
                result,
                lambda: self._stage_repo_index(result),
            )
            result.completed_stages.append("rag_index")

        # ── Mode-driven stage loop ────────────────────────────────────────────
        for stage in self._build_stage_list():
            # Checkpoint resume: skip if already completed
            if stage.checkpoint_key in result.completed_stages or stage.name in result.completed_stages:
                console.print(f"  ⏭️  [dim]{stage.label} — skipped (checkpoint)[/dim]")
                continue

            # Conditional skip (e.g. test_fix skipped when no test_files)
            if stage.skip_if(result):
                console.print(f"  ⏭️  [dim]{stage.label} — skipped[/dim]")
                continue

            self._run_stage(stage.label, stage.description, result, lambda s=stage: s.fn(result))

            if result.errors:
                self._save_checkpoint(result)
                return self._finish(result, start_time)

            # Backward-compat: senior_engineer stage also marks old "engineer" key
            if stage.name == "senior_engineer":
                result.completed_stages.append("engineer")

            result.completed_stages.append(stage.checkpoint_key)
            self._save_checkpoint(result)

            # Early pipeline stop (e.g. code review: CHANGES REQUESTED)
            if stage.stop_if(result):
                if stage.name == "reviewer":
                    console.print("[bold red]⛔ Pipeline stopped: code reviewer requested changes.[/bold red]")
                return self._finish(result, start_time)
```

- [ ] **Step 4: Run all new mode tests**

```bash
python -m pytest tests/test_pipeline_modes.py -v 2>&1 | tail -25
```

Expected: all pass

- [ ] **Step 5: Run the full test suite to check for regressions**

```bash
python -m pytest tests/ -v --ignore=tests/integration -x \
  --ignore=tests/test_deployment.py \
  --ignore=tests/test_oauth_manager.py \
  2>&1 | tail -30
```

Expected: all pass (pre-existing failures in deployment/oauth are unrelated)

- [ ] **Step 6: Commit**

```bash
git add orchestrator.py tests/test_pipeline_modes.py
git commit -m "feat: run() driven by _build_stage_list() stage loop

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 7: Config documentation and `config.yaml` update

**Files:**
- Modify: `config.yaml`

- [ ] **Step 1: Add `mode` and `stages` documentation to `config.yaml`**

Find the `pipeline:` section and add after `max_prd_revisions` / `max_design_revisions`:

```yaml
  # ── Pipeline mode ──────────────────────────────────────────────────────────
  # Controls the stage execution order.
  #
  # standard (default): waterfall order — engineers code first, QA tests after
  #   PM → Architect → Tier → Engineers → Reviewer → QA Planner → QA → Tests → Deploy
  #
  # tdd: test-driven order — QA writes tests before engineers implement
  #   PM → Architect → QA Planner → QA Write → Tier → Engineers → Tests → Reviewer → Deploy
  #
  mode: standard

  # ── Per-stage skip overrides ────────────────────────────────────────────────
  # Set skip: true for any named stage to remove it from the active pipeline.
  # Stage names: tier_review, junior_engineer, senior_engineer, reviewer,
  #              qa_planner, qa_engineer, qa_write, test_fix,
  #              deploy_tester, deploy_fix
  #
  # Example: skip Code Reviewer in TDD mode (tests already validate quality)
  # stages:
  #   reviewer:
  #     skip: false
  #   deploy_tester:
  #     skip: false
```

- [ ] **Step 2: Verify config still parses**

```bash
cd /home/wanleung/Projects/ai-software-house
python -c "import yaml; yaml.safe_load(open('config.yaml'))" && echo "OK"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add config.yaml
git commit -m "docs: document pipeline.mode and pipeline.stages in config.yaml

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 8: Final test run and pull request

**Files:** None — verification and PR only.

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest tests/ -v --ignore=tests/integration \
  --ignore=tests/test_deployment.py \
  --ignore=tests/test_oauth_manager.py \
  2>&1 | tail -20
```

Expected: all pass (same pre-existing failures as before this feature)

- [ ] **Step 2: Confirm new test file passes clean**

```bash
python -m pytest tests/test_pipeline_modes.py -v 2>&1 | tail -20
```

Expected: all pass

- [ ] **Step 3: Push branch and open PR**

```bash
git push -u origin feature/tdd-pipeline-mode

gh pr create \
  --title "feat: TDD pipeline mode with stage registry" \
  --body "$(cat <<'EOF'
## Summary

- Adds `pipeline.mode: tdd` config option that reorders stages: QA writes tests before Engineers code
- Introduces `PipelineStage` dataclass + `MODES` registry — `run()` is now driven by a stage list instead of hardcoded calls
- New `_stage_qa_write` stage calls `QAEngineerAgent(write_only=True)` — test-first perspective, no execution
- Engineers receive pre-written test files in their prompts when `result.test_files` is populated (TDD mode)
- Per-stage skip config: `pipeline.stages.<name>.skip: true`
- Backward-compatible — existing configs with no `mode` key default to `standard`

## Test Plan
- [ ] `tests/test_pipeline_modes.py` — all new tests pass
- [ ] Full test suite passes (no regressions)
- [ ] Manual: run pipeline with `mode: tdd` and confirm QA Write appears before Engineers in console output

## Spec
`docs/superpowers/specs/2026-04-27-tdd-pipeline-mode-design.md`
EOF
)"
```

- [ ] **Step 4: Verify PR was created**

```bash
gh pr view --json number,title,url | python -m json.tool
```

Expected: PR number, title, and URL printed.
