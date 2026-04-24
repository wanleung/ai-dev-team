# PRD & Design Revision Loops — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add iterative back-and-forth revision loops to the PM→PM Reviewer and Architect→Architect Reviewer stages so the original author rewrites their work based on reviewer feedback, up to N configurable rounds.

**Architecture:** Add four new fields to `PipelineResult`, four config keys to `Orchestrator.__init__/from_config`, a `run_revision()` method to both `ProductManagerAgent` and `ArchitectAgent`, and two loop methods `_prd_revision_loop()` + `_design_revision_loop()` to `Orchestrator` that replace the separate PM/PM-reviewer and Architect/Architect-reviewer stage blocks in `run()`.

**Tech Stack:** Python, existing dataclass serialisation pattern (`to_dict`/`from_dict`), `_run_stage()` helper, `_save_checkpoint()`, `PMReviewerAgent.VERDICT_REVISION`, `ArchitectReviewerAgent.VERDICT_REVISION`.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `orchestrator.py` | Modify | `PipelineResult` new fields, `__init__` + `from_config` new params, `_prd_revision_loop()`, `_design_revision_loop()`, wire into `run()` |
| `agents/product_manager.py` | Modify | Add `run_revision()` method |
| `agents/architect.py` | Modify | Add `run_revision()` method |
| `config.yaml` | Modify | 4 new `pipeline:` keys |
| `tests/test_prd_design_loops.py` | Create | 7 test cases from spec |

---

## Task 1: `PipelineResult` new fields + serialisation

**Files:**
- Modify: `orchestrator.py` lines 85–180 (`PipelineResult` dataclass, `to_dict`, `from_dict`)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_prd_design_loops.py`:

```python
"""Tests for PRD/Design revision loops."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, call
from orchestrator import Orchestrator, PipelineResult
from agents.pm_reviewer import PMReviewerAgent
from agents.architect_reviewer import ArchitectReviewerAgent


# ── PipelineResult serialisation ─────────────────────────────────────────────

def test_pipeline_result_new_fields_defaults():
    r = PipelineResult(requirement="build a todo app")
    assert r.prd_revision_count == 0
    assert r.design_revision_count == 0
    assert r.prd_reviewer_draft == ""
    assert r.design_reviewer_draft == ""


def test_pipeline_result_round_trips_new_fields():
    r = PipelineResult(requirement="x")
    r.prd_revision_count = 2
    r.design_revision_count = 1
    r.prd_reviewer_draft = "## Draft PRD"
    r.design_reviewer_draft = "## Draft Design"
    data = r.to_dict()
    r2 = PipelineResult.from_dict(data)
    assert r2.prd_revision_count == 2
    assert r2.design_revision_count == 1
    assert r2.prd_reviewer_draft == "## Draft PRD"
    assert r2.design_reviewer_draft == "## Draft Design"
```

Run:
```bash
cd /home/wanleung/Projects/ai-software-house && source venv/bin/activate && pytest tests/test_prd_design_loops.py::test_pipeline_result_new_fields_defaults tests/test_prd_design_loops.py::test_pipeline_result_round_trips_new_fields -v 2>&1 | tail -10
```

Expected: FAIL — `PipelineResult` has no `prd_revision_count`

- [ ] **Step 2: Add the four new fields to `PipelineResult`**

In `orchestrator.py`, after the `deploy_fix_history` field (line ~126):

```python
    # PRD/Design revision loop tracking
    prd_revision_count: int = 0
    design_revision_count: int = 0
    prd_reviewer_draft: str = ""      # reviewer's suggested PRD (for PM.run_revision)
    design_reviewer_draft: str = ""   # reviewer's suggested design (for Architect.run_revision)
```

- [ ] **Step 3: Add new fields to `to_dict()`**

After the `"deploy_fix_history": self.deploy_fix_history,` entry in `to_dict()`:

```python
            "prd_revision_count": self.prd_revision_count,
            "design_revision_count": self.design_revision_count,
            "prd_reviewer_draft": self.prd_reviewer_draft,
            "design_reviewer_draft": self.design_reviewer_draft,
```

- [ ] **Step 4: Add new fields to `from_dict()` key list**

In `from_dict()`, extend the key list to include the four new fields. Find the line with `"deploy_fix_history"` and add after it:

```python
                    "prd_revision_count", "design_revision_count",
                    "prd_reviewer_draft", "design_reviewer_draft",
```

- [ ] **Step 5: Run the two serialisation tests**

```bash
cd /home/wanleung/Projects/ai-software-house && source venv/bin/activate && pytest tests/test_prd_design_loops.py::test_pipeline_result_new_fields_defaults tests/test_prd_design_loops.py::test_pipeline_result_round_trips_new_fields -v 2>&1 | tail -10
```

Expected: Both PASS.

- [ ] **Step 6: Run full suite to verify no regressions**

```bash
pytest tests/ -q 2>&1 | tail -5
```

Expected: All existing tests pass.

- [ ] **Step 7: Commit**

```bash
git add orchestrator.py tests/test_prd_design_loops.py
git commit -m "feat(pipeline): add prd/design revision count + draft fields to PipelineResult"
```

---

## Task 2: `Orchestrator` new config params

**Files:**
- Modify: `orchestrator.py` — `__init__` signature + body, `from_config()`
- Modify: `config.yaml` — add 4 new keys under `pipeline:`

- [ ] **Step 1: Write failing test**

Append to `tests/test_prd_design_loops.py`:

```python
def test_orchestrator_new_config_defaults():
    """Orchestrator reads new config keys and stores them as instance attributes."""
    o = Orchestrator.__new__(Orchestrator)
    o.max_prd_revisions = 3
    o.max_design_revisions = 3
    o.stop_on_prd_issues = False
    o.stop_on_design_issues = False
    assert o.max_prd_revisions == 3
    assert o.stop_on_prd_issues is False


def test_from_config_reads_new_keys(tmp_path, monkeypatch):
    """from_config() passes new pipeline keys through to __init__."""
    import yaml, os
    cfg = {
        "llm": {"model": "gpt-4.1"},
        "github": {"repo": "", "use_github": False},
        "team": {},
        "pipeline": {
            "max_prd_revisions": 2,
            "max_design_revisions": 1,
            "stop_on_prd_issues": True,
            "stop_on_design_issues": False,
        },
    }
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(cfg))
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    o = Orchestrator.from_config(str(cfg_file))
    assert o.max_prd_revisions == 2
    assert o.max_design_revisions == 1
    assert o.stop_on_prd_issues is True
    assert o.stop_on_design_issues is False
```

Run:
```bash
pytest tests/test_prd_design_loops.py::test_from_config_reads_new_keys -v 2>&1 | tail -10
```

Expected: FAIL — `Orchestrator` has no `max_prd_revisions`

- [ ] **Step 2: Add 4 new params to `Orchestrator.__init__`**

In `orchestrator.py`, in `__init__`'s parameter list, after `max_revisions: int = 3,` add:

```python
        max_prd_revisions: int = 3,
        max_design_revisions: int = 3,
        stop_on_prd_issues: bool = False,
        stop_on_design_issues: bool = False,
```

In the `__init__` body, after `self.max_revisions = max_revisions` add:

```python
        self.max_prd_revisions = max_prd_revisions
        self.max_design_revisions = max_design_revisions
        self.stop_on_prd_issues = stop_on_prd_issues
        self.stop_on_design_issues = stop_on_design_issues
```

- [ ] **Step 3: Pass new keys through `from_config()`**

In `from_config()`, in the `return cls(...)` call, after `max_revisions=pipeline.get("max_revisions", 3),` add:

```python
            max_prd_revisions=pipeline.get("max_prd_revisions", 3),
            max_design_revisions=pipeline.get("max_design_revisions", 3),
            stop_on_prd_issues=pipeline.get("stop_on_prd_issues", False),
            stop_on_design_issues=pipeline.get("stop_on_design_issues", False),
```

- [ ] **Step 4: Add keys to `config.yaml`**

In `config.yaml`, under the `pipeline:` section, after the `stop_on_review_issues: false` line:

```yaml
  # Revision loop rounds for PRD (PM ↔ PM Reviewer back-and-forth). 0 = disable loop.
  max_prd_revisions: 3
  # Revision loop rounds for System Design (Architect ↔ Architect Reviewer). 0 = disable.
  max_design_revisions: 3
  # If true, halt the pipeline when max PRD revisions hit without APPROVED.
  stop_on_prd_issues: false
  # If true, halt the pipeline when max Design revisions hit without APPROVED.
  stop_on_design_issues: false
```

- [ ] **Step 5: Run new config tests**

```bash
pytest tests/test_prd_design_loops.py::test_orchestrator_new_config_defaults tests/test_prd_design_loops.py::test_from_config_reads_new_keys -v 2>&1 | tail -10
```

Expected: Both PASS.

- [ ] **Step 6: Full suite**

```bash
pytest tests/ -q 2>&1 | tail -5
```

- [ ] **Step 7: Commit**

```bash
git add orchestrator.py config.yaml
git commit -m "feat(config): add max_prd_revisions, max_design_revisions, stop_on_prd/design_issues"
```

---

## Task 3: `ProductManagerAgent.run_revision()`

**Files:**
- Modify: `agents/product_manager.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_prd_design_loops.py`:

```python
def test_run_revision_pm_agent():
    """ProductManagerAgent.run_revision() sends original PRD, review, and draft to the LLM."""
    from agents.product_manager import ProductManagerAgent

    agent = ProductManagerAgent.__new__(ProductManagerAgent)
    captured = {}

    def fake_call(prompt):
        captured["prompt"] = prompt
        return "# Revised PRD\n## Project Name\nTodo App\n## Overview\nFixed version."

    agent.call = fake_call

    result = agent.run_revision(
        original_prd="# Original PRD",
        review="Missing acceptance criteria.",
        draft_revision="# Draft PRD by reviewer",
        requirement="Build a todo app",
        project_name="Todo App",
    )

    assert "prd" in result
    assert "project_name" in result
    assert "Original PRD" in captured["prompt"]
    assert "Missing acceptance criteria" in captured["prompt"]
    assert "Draft PRD by reviewer" in captured["prompt"]
    assert "Revised PRD" in result["prd"]
```

Run:
```bash
pytest tests/test_prd_design_loops.py::test_run_revision_pm_agent -v 2>&1 | tail -10
```

Expected: FAIL — `ProductManagerAgent` has no `run_revision`

- [ ] **Step 2: Implement `run_revision()` in `agents/product_manager.py`**

After the `run_with_github()` method, add:

```python
    def run_revision(
        self,
        original_prd: str,
        review: str,
        draft_revision: str,
        requirement: str,
        project_name: str,
    ) -> dict:
        """Rewrite the PRD incorporating reviewer feedback and the reviewer's draft suggestion.

        Args:
            original_prd: The PRD that was reviewed.
            review: Reviewer's feedback text.
            draft_revision: Reviewer's suggested rewrite (use as direction, not copy-paste).
            requirement: Original client requirement (for context).
            project_name: Current project name.

        Returns:
            dict with keys:
                - prd (str): Improved PRD markdown
                - project_name (str): Re-extracted project name
                - issue_number (None): Unchanged — GitHub issue was already created
                - issue_url (None): Unchanged
        """
        prompt = (
            f"You previously wrote a PRD for the project '{project_name}' that was reviewed "
            f"and needs improvement.\n\n"
            f"## Original Client Requirement\n---\n{requirement}\n---\n\n"
            f"## Your Original PRD\n---\n{original_prd}\n---\n\n"
            f"## Reviewer Feedback\n---\n{review}\n---\n\n"
            f"## Reviewer's Suggested Draft (use as direction, not copy-paste)\n"
            f"---\n{draft_revision}\n---\n\n"
            f"Rewrite the PRD addressing the reviewer's concerns. Preserve all requirements "
            f"that were already correct. Output a complete, improved PRD following your role instructions."
        )

        prd = self.call(prompt)
        new_project_name = self._extract_project_name(prd) or project_name

        return {
            "prd": prd,
            "project_name": new_project_name,
            "issue_number": None,
            "issue_url": None,
        }
```

- [ ] **Step 3: Run the test**

```bash
pytest tests/test_prd_design_loops.py::test_run_revision_pm_agent -v 2>&1 | tail -10
```

Expected: PASS.

- [ ] **Step 4: Full suite**

```bash
pytest tests/ -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add agents/product_manager.py
git commit -m "feat(pm): add ProductManagerAgent.run_revision() for PRD revision loop"
```

---

## Task 4: `ArchitectAgent.run_revision()`

**Files:**
- Modify: `agents/architect.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_prd_design_loops.py`:

```python
def test_run_revision_architect_agent():
    """ArchitectAgent.run_revision() sends original design, review, draft, and PRD to the LLM."""
    from agents.architect import ArchitectAgent

    agent = ArchitectAgent.__new__(ArchitectAgent)
    agent._tool_registry = None
    captured = {}

    def fake_call(prompt):
        captured["prompt"] = prompt
        return (
            "# Revised Design\n## Overview\nFixed.\n"
            "## Implementation Modules\n1. **api**: REST layer\n2. **db**: Database layer\n"
        )

    agent.call = fake_call

    result = agent.run_revision(
        original_design="# Original Design",
        review="Missing database schema.",
        draft_revision="# Draft Design by reviewer",
        prd="# PRD content",
        project_name="Todo App",
    )

    assert "design" in result
    assert "modules" in result
    assert "Original Design" in captured["prompt"]
    assert "Missing database schema" in captured["prompt"]
    assert "Draft Design by reviewer" in captured["prompt"]
    assert "Revised Design" in result["design"]
    assert len(result["modules"]) >= 1
```

Run:
```bash
pytest tests/test_prd_design_loops.py::test_run_revision_architect_agent -v 2>&1 | tail -10
```

Expected: FAIL — `ArchitectAgent` has no `run_revision`

- [ ] **Step 2: Implement `run_revision()` in `agents/architect.py`**

After the `run_with_github()` method, add:

```python
    def run_revision(
        self,
        original_design: str,
        review: str,
        draft_revision: str,
        prd: str,
        project_name: str,
    ) -> dict:
        """Rewrite the system design incorporating reviewer feedback and the reviewer's draft.

        Args:
            original_design: The system design that was reviewed.
            review: Reviewer's feedback text.
            draft_revision: Reviewer's suggested rewrite (use as direction, not copy-paste).
            prd: Current PRD (for context).
            project_name: Current project name.

        Returns:
            dict with keys:
                - design (str): Improved system design markdown
                - modules (list[dict]): Re-parsed implementation modules
        """
        prompt = (
            f"You previously wrote a System Design for the project '{project_name}' that was "
            f"reviewed and needs improvement.\n\n"
            f"## PRD (unchanged)\n---\n{prd}\n---\n\n"
            f"## Your Original System Design\n---\n{original_design}\n---\n\n"
            f"## Reviewer Feedback\n---\n{review}\n---\n\n"
            f"## Reviewer's Suggested Draft (use as direction, not copy-paste)\n"
            f"---\n{draft_revision}\n---\n\n"
            f"Rewrite the System Design addressing the reviewer's concerns. Preserve correct "
            f"decisions. Output a complete, improved System Design following your role instructions. "
            f"Make sure to include an 'Implementation Modules' section."
        )

        if self._tool_registry is not None:
            try:
                design = self.call_with_tools(prompt, tools=self._tool_registry)
            except NotImplementedError:
                design = self.call(prompt)
        else:
            design = self.call(prompt)

        modules = self._parse_modules(design)
        return {
            "design": design,
            "modules": modules,
        }
```

- [ ] **Step 3: Run the test**

```bash
pytest tests/test_prd_design_loops.py::test_run_revision_architect_agent -v 2>&1 | tail -10
```

Expected: PASS.

- [ ] **Step 4: Full suite**

```bash
pytest tests/ -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add agents/architect.py
git commit -m "feat(architect): add ArchitectAgent.run_revision() for design revision loop"
```

---

## Task 5: `Orchestrator._prd_revision_loop()` + wire into `run()`

**Files:**
- Modify: `orchestrator.py` — new `_prd_revision_loop()` method, update `run()`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_prd_design_loops.py`:

```python
# ── helpers ────────────────────────────────────────────────────────────────

def _make_orch(max_prd=3, stop=False):
    """Minimal orchestrator for loop testing."""
    o = Orchestrator.__new__(Orchestrator)
    o.max_prd_revisions = max_prd
    o.max_design_revisions = 3
    o.stop_on_prd_issues = stop
    o.stop_on_design_issues = False
    o.github = None
    o.target_github = None
    o._github_token = "tok"
    # Stub agents
    o.pm = MagicMock()
    o.pm_reviewer = MagicMock()
    o.architect = MagicMock()
    o.architect_reviewer = MagicMock()
    return o


def _make_result(stages=None):
    r = PipelineResult(requirement="build a todo app")
    r.prd = "# Initial PRD"
    r.project_name = "Todo App"
    r.completed_stages = list(stages or [])
    return r


# ── PRD revision loop ──────────────────────────────────────────────────────

def test_prd_revision_loop_approves_on_round_2():
    """Reviewer returns NEEDS_REVISION on first review, APPROVED on round 2."""
    o = _make_orch()

    # pm.run already done — we pre-populate prd
    r = _make_result(stages=["pm"])

    # First pm_reviewer call → NEEDS REVISION
    o.pm_reviewer.run.side_effect = [
        {
            "review": "Missing AC.",
            "verdict": PMReviewerAgent.VERDICT_REVISION,
            "needs_revision": True,
            "revised_prd": "# Reviewer Draft v1",
            "revised_project_name": "Todo App",
        },
        # After PM rewrites, second review → APPROVED
        {
            "review": "Looks good.",
            "verdict": PMReviewerAgent.VERDICT_APPROVED,
            "needs_revision": False,
            "revised_prd": None,
            "revised_project_name": "Todo App",
        },
    ]
    o.pm.run_revision.return_value = {
        "prd": "# Revised PRD v1",
        "project_name": "Todo App",
        "issue_number": None,
        "issue_url": None,
    }

    with patch.object(o, "_save_checkpoint"):
        ok = o._prd_revision_loop(r, "build a todo app")

    assert ok is True
    assert r.prd_revision_count == 1
    assert "pm_review_loop" in r.completed_stages
    assert r.prd == "# Revised PRD v1"


def test_prd_revision_loop_max_rounds_continue():
    """3 NEEDS_REVISION rounds → loop completes, pipeline continues, prd_revision_count == 3."""
    o = _make_orch(max_prd=3, stop=False)
    r = _make_result(stages=["pm"])

    needs_revision_resp = {
        "review": "Still not good.",
        "verdict": PMReviewerAgent.VERDICT_REVISION,
        "needs_revision": True,
        "revised_prd": "# Reviewer Draft",
        "revised_project_name": "Todo App",
    }
    o.pm_reviewer.run.side_effect = [needs_revision_resp] * 4  # initial + 3 rounds
    o.pm.run_revision.return_value = {
        "prd": "# Revised PRD",
        "project_name": "Todo App",
        "issue_number": None,
        "issue_url": None,
    }

    with patch.object(o, "_save_checkpoint"):
        ok = o._prd_revision_loop(r, "build a todo app")

    assert ok is True  # continues (stop_on_prd_issues=False)
    assert r.prd_revision_count == 3
    assert "pm_review_loop" in r.completed_stages


def test_prd_revision_loop_max_rounds_halt():
    """stop_on_prd_issues=True → pipeline returns False after max rounds."""
    o = _make_orch(max_prd=2, stop=True)
    r = _make_result(stages=["pm"])

    needs_revision_resp = {
        "review": "Needs work.",
        "verdict": PMReviewerAgent.VERDICT_REVISION,
        "needs_revision": True,
        "revised_prd": "# Draft",
        "revised_project_name": "Todo App",
    }
    o.pm_reviewer.run.side_effect = [needs_revision_resp] * 3
    o.pm.run_revision.return_value = {
        "prd": "# Revised",
        "project_name": "Todo App",
        "issue_number": None,
        "issue_url": None,
    }

    with patch.object(o, "_save_checkpoint"):
        ok = o._prd_revision_loop(r, "build a todo app")

    assert ok is False


def test_prd_revision_loop_checkpoint_resume():
    """Round 1 already in completed_stages → it is skipped on resume."""
    o = _make_orch(max_prd=3, stop=False)
    r = _make_result(stages=["pm", "pm_reviewer", "prd_revision_1"])
    r.prd_verdict = PMReviewerAgent.VERDICT_REVISION  # still needs revision

    # Only one more round should run (round 2)
    approved_resp = {
        "review": "LGTM.",
        "verdict": PMReviewerAgent.VERDICT_APPROVED,
        "needs_revision": False,
        "revised_prd": None,
        "revised_project_name": "Todo App",
    }
    o.pm_reviewer.run.return_value = approved_resp
    o.pm.run_revision.return_value = {
        "prd": "# Revised v2",
        "project_name": "Todo App",
        "issue_number": None,
        "issue_url": None,
    }

    with patch.object(o, "_save_checkpoint"):
        ok = o._prd_revision_loop(r, "build a todo app")

    # run_revision called once (round 2 only, not round 1)
    assert o.pm.run_revision.call_count == 1
    assert ok is True
```

Run:
```bash
pytest tests/test_prd_design_loops.py::test_prd_revision_loop_approves_on_round_2 tests/test_prd_design_loops.py::test_prd_revision_loop_max_rounds_continue tests/test_prd_design_loops.py::test_prd_revision_loop_max_rounds_halt tests/test_prd_design_loops.py::test_prd_revision_loop_checkpoint_resume -v 2>&1 | tail -15
```

Expected: FAIL — `Orchestrator` has no `_prd_revision_loop`

- [ ] **Step 2: Implement `_prd_revision_loop()` in `orchestrator.py`**

Add the following method after `_stage_pm_reviewer()` (around line 930):

```python
    def _prd_revision_loop(self, result: PipelineResult, requirement: str) -> bool:
        """Run PM → PM Reviewer revision loop (up to max_prd_revisions rounds).

        Returns True if pipeline should continue, False if it should halt.
        """
        # Step 1: PM writes initial PRD
        if "pm" not in result.completed_stages:
            try:
                self._run_stage(
                    "📋 Product Manager",
                    "Analyzing requirements & writing PRD...",
                    result,
                    lambda: self._stage_pm(result, requirement),
                )
            except ClarificationNeeded as exc:
                self._pause_for_clarification(result, "pm", exc.questions)
                return False
            if result.errors:
                self._save_checkpoint(result)
                return False
            result.completed_stages.append("pm")
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]📋 Product Manager — skipped (checkpoint)[/dim]")

        # Step 2: Initial PM Reviewer pass
        if "pm_reviewer" not in result.completed_stages:
            self._run_stage(
                "📝 PM Reviewer",
                "Reviewing PRD for completeness...",
                result,
                lambda: self._stage_pm_reviewer(result, requirement),
            )
            if result.errors:
                self._save_checkpoint(result)
                return False
            result.completed_stages.append("pm_reviewer")
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]📝 PM Reviewer — skipped (checkpoint)[/dim]")

        # Step 3: Revision loop
        if self.max_prd_revisions == 0:
            # Loop disabled — mark complete and continue
            result.completed_stages.append("pm_review_loop")
            self._save_checkpoint(result)
            return True

        for round_num in range(1, self.max_prd_revisions + 1):
            if result.prd_verdict != PMReviewerAgent.VERDICT_REVISION:
                break  # Already approved

            key = f"prd_revision_{round_num}"
            if key in result.completed_stages:
                console.print(f"  ⏭️  [dim]PRD revision round {round_num} — skipped (checkpoint)[/dim]")
                continue

            # PM rewrites PRD
            console.print(
                f"  🔄 [yellow]PRD NEEDS REVISION (round {round_num}/{self.max_prd_revisions})"
                f" — sending back to PM...[/yellow]"
            )
            self._run_stage(
                "📋 Product Manager",
                f"Revising PRD based on reviewer feedback (round {round_num})...",
                result,
                lambda rn=round_num: self._stage_pm_revision(result, requirement, rn),
            )
            if result.errors:
                self._save_checkpoint(result)
                return False

            # Reviewer re-checks
            self._run_stage(
                "📝 PM Reviewer",
                f"Re-reviewing revised PRD (round {round_num})...",
                result,
                lambda: self._stage_pm_reviewer(result, requirement),
            )
            if result.errors:
                self._save_checkpoint(result)
                return False

            result.completed_stages.append(key)
            self._save_checkpoint(result)
        else:
            # for-else: exited without break → max rounds hit, still NEEDS REVISION
            console.print(
                f"  ⚠️  [yellow]Max PRD revisions reached ({self.max_prd_revisions}/"
                f"{self.max_prd_revisions}). "
                + ("Halting pipeline." if self.stop_on_prd_issues else "Continuing with current best.")
                + "[/yellow]"
            )
            if self.stop_on_prd_issues:
                if self.github and result.issue_number:
                    self.github.add_issue_comment(
                        result.issue_number,
                        f"⚠️ PRD revision limit reached after {self.max_prd_revisions} rounds. "
                        f"Human review required. Remove `agent-failed` label and re-trigger to retry.",
                    )
                result.completed_stages.append("pm_review_loop")
                self._save_checkpoint(result)
                return False

        if result.prd_verdict != PMReviewerAgent.VERDICT_REVISION:
            console.print(
                f"  ✅ [green]PRD APPROVED (round {result.prd_revision_count})[/green]"
            )

        result.completed_stages.append("pm_review_loop")
        self._save_checkpoint(result)
        return True
```

- [ ] **Step 3: Add `_stage_pm_revision()` helper method**

Add immediately after `_stage_pm_reviewer()`:

```python
    def _stage_pm_revision(self, result: PipelineResult, requirement: str, round_num: int) -> None:
        """PM rewrites the PRD using reviewer feedback and reviewer's draft."""
        pm_result = self.pm.run_revision(
            original_prd=result.prd,
            review=result.prd_review,
            draft_revision=result.prd_reviewer_draft,
            requirement=requirement,
            project_name=result.project_name,
        )
        result.prd = pm_result["prd"]
        result.project_name = pm_result["project_name"]
        result.prd_revision_count = round_num
```

- [ ] **Step 4: Update `_stage_pm_reviewer()` to store the reviewer's draft in `result`**

In the existing `_stage_pm_reviewer()` method, after `result.prd_verdict = rev_result["verdict"]`:

Replace:
```python
        if rev_result["needs_revision"] and rev_result["revised_prd"]:
            result.prd = rev_result["revised_prd"]
            result.project_name = rev_result["revised_project_name"]
```

With:
```python
        # Store reviewer's draft for use in run_revision() (new revision loop)
        result.prd_reviewer_draft = rev_result.get("revised_prd") or ""
        # Legacy single-pass behaviour preserved when loop is disabled (max_prd_revisions == 0)
        if getattr(self, "max_prd_revisions", 3) == 0 and rev_result["needs_revision"] and rev_result["revised_prd"]:
            result.prd = rev_result["revised_prd"]
            result.project_name = rev_result["revised_project_name"]
```

- [ ] **Step 5: Update `run()` to call `_prd_revision_loop()` instead of separate stage blocks**

In `run()`, replace the existing Stage 1 and Stage 1b blocks:

```python
        # ── Stage 1: Product Manager ─────────────────────────────────────────
        if "pm" not in result.completed_stages:
            ...
        # ── Stage 1b: PM Reviewer ─────────────────────────────────────────────
        if "pm_reviewer" not in result.completed_stages:
            ...
```

With:

```python
        # ── Stage 1: PM + PM Reviewer revision loop ───────────────────────────
        if "pm_review_loop" not in result.completed_stages:
            ok = self._prd_revision_loop(result, requirement)
            if not ok:
                return self._finish(result, start_time)
        else:
            console.print("  ⏭️  [dim]PRD revision loop — skipped (checkpoint)[/dim]")
```

- [ ] **Step 6: Run PRD loop tests**

```bash
pytest tests/test_prd_design_loops.py::test_prd_revision_loop_approves_on_round_2 tests/test_prd_design_loops.py::test_prd_revision_loop_max_rounds_continue tests/test_prd_design_loops.py::test_prd_revision_loop_max_rounds_halt tests/test_prd_design_loops.py::test_prd_revision_loop_checkpoint_resume -v 2>&1 | tail -15
```

Expected: All 4 PASS.

- [ ] **Step 7: Full suite**

```bash
pytest tests/ -q 2>&1 | tail -8
```

Fix any regressions (likely tests that mock `_stage_pm` + `_stage_pm_reviewer` separately — they now run inside `_prd_revision_loop` which is also mockable at the loop level).

- [ ] **Step 8: Commit**

```bash
git add orchestrator.py
git commit -m "feat(orchestrator): add _prd_revision_loop() — PM rewrites PRD up to N times"
```

---

## Task 6: `Orchestrator._design_revision_loop()` + wire into `run()`

**Files:**
- Modify: `orchestrator.py` — new `_design_revision_loop()` method, `_stage_arch_revision()`, update `run()`

- [ ] **Step 1: Write failing test**

Append to `tests/test_prd_design_loops.py`:

```python
def test_design_revision_loop_approves_on_round_1():
    """Architect reviewer returns NEEDS_REVISION once then APPROVED."""
    o = _make_orch()
    r = _make_result(stages=["pm", "pm_review_loop", "architect"])
    r.design = "# Initial Design"
    r.prd = "# PRD"

    o.architect_reviewer.run.side_effect = [
        {
            "review": "Missing DB schema.",
            "verdict": ArchitectReviewerAgent.VERDICT_REVISION,
            "needs_revision": True,
            "revised_design": "# Reviewer Draft Design",
            "revised_modules": [{"name": "api", "description": "REST layer"}],
        },
        {
            "review": "Looks good.",
            "verdict": ArchitectReviewerAgent.VERDICT_APPROVED,
            "needs_revision": False,
            "revised_design": None,
            "revised_modules": None,
        },
    ]
    o.architect.run_revision.return_value = {
        "design": "# Revised Design v1",
        "modules": [{"name": "api", "description": "REST layer"}],
    }

    with patch.object(o, "_save_checkpoint"):
        ok = o._design_revision_loop(r)

    assert ok is True
    assert r.design_revision_count == 1
    assert "architect_review_loop" in r.completed_stages
    assert r.design == "# Revised Design v1"
```

Run:
```bash
pytest tests/test_prd_design_loops.py::test_design_revision_loop_approves_on_round_1 -v 2>&1 | tail -10
```

Expected: FAIL — `Orchestrator` has no `_design_revision_loop`

- [ ] **Step 2: Implement `_design_revision_loop()` in `orchestrator.py`**

Add the following method after `_prd_revision_loop()`:

```python
    def _design_revision_loop(self, result: PipelineResult) -> bool:
        """Run Architect → Architect Reviewer revision loop (up to max_design_revisions rounds).

        Returns True if pipeline should continue, False if it should halt.
        """
        # Step 1: Architect writes initial design
        if "architect" not in result.completed_stages:
            try:
                self._run_stage(
                    "🏗️  Architect",
                    "Designing system architecture...",
                    result,
                    lambda: self._stage_architect(result),
                )
            except ClarificationNeeded as exc:
                self._pause_for_clarification(result, "architect", exc.questions)
                return False
            if result.errors:
                self._save_checkpoint(result)
                return False
            result.completed_stages.append("architect")
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]🏗️  Architect — skipped (checkpoint)[/dim]")

        # Step 2: Initial Architect Reviewer pass
        if "architect_reviewer" not in result.completed_stages:
            self._run_stage(
                "🔎 Architect Reviewer",
                "Reviewing system design...",
                result,
                lambda: self._stage_architect_reviewer(result),
            )
            if result.errors:
                self._save_checkpoint(result)
                return False
            result.completed_stages.append("architect_reviewer")
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]🔎 Architect Reviewer — skipped (checkpoint)[/dim]")

        # Step 3: Revision loop
        if self.max_design_revisions == 0:
            result.completed_stages.append("architect_review_loop")
            self._save_checkpoint(result)
            return True

        for round_num in range(1, self.max_design_revisions + 1):
            if result.design_verdict != ArchitectReviewerAgent.VERDICT_REVISION:
                break

            key = f"design_revision_{round_num}"
            if key in result.completed_stages:
                console.print(f"  ⏭️  [dim]Design revision round {round_num} — skipped (checkpoint)[/dim]")
                continue

            console.print(
                f"  🔄 [yellow]DESIGN NEEDS REVISION (round {round_num}/{self.max_design_revisions})"
                f" — sending back to Architect...[/yellow]"
            )
            self._run_stage(
                "🏗️  Architect",
                f"Revising design based on reviewer feedback (round {round_num})...",
                result,
                lambda rn=round_num: self._stage_arch_revision(result, rn),
            )
            if result.errors:
                self._save_checkpoint(result)
                return False

            self._run_stage(
                "🔎 Architect Reviewer",
                f"Re-reviewing revised design (round {round_num})...",
                result,
                lambda: self._stage_architect_reviewer(result),
            )
            if result.errors:
                self._save_checkpoint(result)
                return False

            result.completed_stages.append(key)
            self._save_checkpoint(result)
        else:
            console.print(
                f"  ⚠️  [yellow]Max Design revisions reached ({self.max_design_revisions}/"
                f"{self.max_design_revisions}). "
                + ("Halting pipeline." if self.stop_on_design_issues else "Continuing with current best.")
                + "[/yellow]"
            )
            if self.stop_on_design_issues:
                if self.github and result.issue_number:
                    self.github.add_issue_comment(
                        result.issue_number,
                        f"⚠️ Design revision limit reached after {self.max_design_revisions} rounds. "
                        f"Human review required. Remove `agent-failed` label and re-trigger to retry.",
                    )
                result.completed_stages.append("architect_review_loop")
                self._save_checkpoint(result)
                return False

        if result.design_verdict != ArchitectReviewerAgent.VERDICT_REVISION:
            console.print(
                f"  ✅ [green]DESIGN APPROVED (round {result.design_revision_count})[/green]"
            )

        result.completed_stages.append("architect_review_loop")
        self._save_checkpoint(result)
        return True
```

- [ ] **Step 3: Add `_stage_arch_revision()` helper**

Add immediately after `_stage_architect_reviewer()`:

```python
    def _stage_arch_revision(self, result: PipelineResult, round_num: int) -> None:
        """Architect rewrites the design using reviewer feedback and reviewer's draft."""
        arch_result = self.architect.run_revision(
            original_design=result.design,
            review=result.design_review,
            draft_revision=result.design_reviewer_draft,
            prd=result.prd,
            project_name=result.project_name,
        )
        result.design = arch_result["design"]
        result.modules = arch_result["modules"]
        result.design_revision_count = round_num
```

- [ ] **Step 4: Update `_stage_architect_reviewer()` to store reviewer's draft**

In the existing `_stage_architect_reviewer()` method, after `result.design_verdict = rev_result["verdict"]` (and before the existing `if rev_result.get("revised_design"):` block):

Add:
```python
        # Store reviewer's draft for use in run_revision() (new revision loop)
        result.design_reviewer_draft = rev_result.get("revised_design") or ""
```

Then replace the existing block:
```python
        if rev_result.get("revised_design"):
            console.print(...)
            result.design = rev_result["revised_design"]
            if rev_result.get("revised_modules"):
                result.modules = rev_result["revised_modules"]
```

With (only apply legacy self-patch when loop is disabled):
```python
        # Legacy single-pass behaviour preserved when loop is disabled (max_design_revisions == 0)
        if getattr(self, "max_design_revisions", 3) == 0 and rev_result.get("revised_design"):
            console.print(
                f"  🔄 [yellow]Design revised by reviewer "
                f"({rev_result['verdict']})[/yellow]"
            )
            result.design = rev_result["revised_design"]
            if rev_result.get("revised_modules"):
                result.modules = rev_result["revised_modules"]
```

- [ ] **Step 5: Update `run()` to call `_design_revision_loop()` instead of separate stage blocks**

In `run()`, replace the existing Stage 2 and Stage 2b blocks:

```python
        # ── Stage 2: Architect ────────────────────────────────────────────────
        if "architect" not in result.completed_stages:
            ...
        # ── Stage 2b: Architect Reviewer ──────────────────────────────────────
        if "architect_reviewer" not in result.completed_stages:
            ...
```

With:

```python
        # ── Stage 2: Architect + Architect Reviewer revision loop ─────────────
        if "architect_review_loop" not in result.completed_stages:
            ok = self._design_revision_loop(result)
            if not ok:
                return self._finish(result, start_time)
        else:
            console.print("  ⏭️  [dim]Design revision loop — skipped (checkpoint)[/dim]")
```

- [ ] **Step 6: Run design loop test**

```bash
pytest tests/test_prd_design_loops.py::test_design_revision_loop_approves_on_round_1 -v 2>&1 | tail -10
```

Expected: PASS.

- [ ] **Step 7: Run full test suite**

```bash
pytest tests/ -q 2>&1 | tail -8
```

Fix any regressions. The most likely breakage: tests that mock `_stage_architect` or `_stage_architect_reviewer` at the top-level in `run()` — they now run inside `_design_revision_loop()`, which is itself easy to mock.

- [ ] **Step 8: Commit**

```bash
git add orchestrator.py
git commit -m "feat(orchestrator): add _design_revision_loop() — Architect rewrites design up to N times"
```

---

## Task 7: Final integration — run full tests + push

**Files:** None (verification only)

- [ ] **Step 1: Run all 7 new loop tests together**

```bash
cd /home/wanleung/Projects/ai-software-house && source venv/bin/activate && pytest tests/test_prd_design_loops.py -v 2>&1 | tail -20
```

Expected: All 9 tests pass (2 serialisation + 2 config + 1 PM revision + 1 Architect revision + 4 PRD loop + 1 design loop = 11 tests).

- [ ] **Step 2: Full regression suite**

```bash
pytest tests/ -q 2>&1 | tail -10
```

Expected: All tests pass (was 132 before this feature).

- [ ] **Step 3: Smoke test `config.yaml` new keys parse correctly**

```bash
python -c "
from orchestrator import Orchestrator
o = Orchestrator.from_config('config.yaml')
print('max_prd_revisions:', o.max_prd_revisions)
print('max_design_revisions:', o.max_design_revisions)
print('stop_on_prd_issues:', o.stop_on_prd_issues)
print('stop_on_design_issues:', o.stop_on_design_issues)
"
```

Expected:
```
max_prd_revisions: 3
max_design_revisions: 3
stop_on_prd_issues: False
stop_on_design_issues: False
```

- [ ] **Step 4: Push**

```bash
git push
```

---

## Regression Notes

Tests that mock `_stage_pm` / `_stage_pm_reviewer` / `_stage_architect` / `_stage_architect_reviewer` directly in `run()` will no longer receive those calls — they now happen inside the loop methods. The cleanest fix is to also mock `_prd_revision_loop` and `_design_revision_loop` in those tests:

```python
with patch.object(orch, "_prd_revision_loop", return_value=True), \
     patch.object(orch, "_design_revision_loop", return_value=True):
    result = orch.run(requirement)
```

Check `tests/test_repo_context.py` lines ~169-234 and any other tests that patch the four individual stage methods.
