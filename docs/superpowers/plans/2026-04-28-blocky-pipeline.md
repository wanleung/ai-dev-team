# Blocky Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `pipeline.yaml` support for fully custom stage sequences with explicit loop blocks, plus a GUI config builder (`python main.py --config-builder`).

**Architecture:** A separate `pipeline.yaml` file defines the complete execution sequence including explicit `loop:` blocks. When present it fully replaces `pipeline.mode` in `config.yaml`. `_make_stage_registry()` remains the single source of truth for valid stage names — used by both the validator and the GUI palette. The GUI is a self-contained single-file HTML app served by a minimal Python HTTP server.

**Tech Stack:** Python 3.11+, PyYAML (already present), Python `http.server` stdlib, vanilla JS (no npm), Rich console (already present), pytest

**Branch:** `feature/blocky-pipeline` (PR against `master`)

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `orchestrator.py` | Modify | PipelineStage loop fields, last_verdict, pm/arch registry, `_load_pipeline_yaml()`, `_run_loop_stage()`, integration into `from_config()`/`_build_stage_list()`/`run()` |
| `tests/test_pipeline_yaml.py` | Create | All tests for T1–T3 |
| `pipeline_builder/__init__.py` | Create | Empty package marker |
| `pipeline_builder/server.py` | Create | Minimal HTTP server serving GUI + POST /save endpoint |
| `pipeline_builder/index.html` | Create | Self-contained drag-and-drop GUI |
| `main.py` | Modify | `--config-builder` CLI flag |
| `config.yaml` | Modify | Comment noting pipeline.yaml takes precedence |

---

## Task 1: Extend PipelineStage + PipelineResult + registry

**Files:**
- Modify: `orchestrator.py` (PipelineStage dataclass ~line 205, PipelineResult ~line 91, `_make_stage_registry()` ~line 711)
- Create: `tests/test_pipeline_yaml.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_pipeline_yaml.py
"""Tests for pipeline.yaml custom stage flow: parser, validator, loop execution, GUI registry."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch


def _make_orch() -> "Orchestrator":
    from orchestrator import Orchestrator
    o = Orchestrator.__new__(Orchestrator)
    o.model = "gpt-4.1"
    o._github_token = "tok"
    o.github = None
    o.target_github = None
    o._mode = "standard"
    o._stage_skips = {}
    o._pipeline_yaml_stages = None
    o.max_prd_revisions = 3
    o.max_design_revisions = 3
    return o


# T1: PipelineStage has loop fields
def test_pipeline_stage_has_loop_fields():
    from orchestrator import PipelineStage
    s = PipelineStage(
        name="loop_0", label="🔁 Loop", description="looping",
        checkpoint_key="loop_0", fn=lambda r: None,
        loop_stages=["pm", "pm_reviewer"], loop_max=3, loop_until="APPROVED",
    )
    assert s.loop_stages == ["pm", "pm_reviewer"]
    assert s.loop_max == 3
    assert s.loop_until == "APPROVED"


# T1: PipelineStage loop fields default to empty/zero (non-loop stages unaffected)
def test_pipeline_stage_loop_fields_default_empty():
    from orchestrator import PipelineStage
    s = PipelineStage(
        name="tier_review", label="🏷️ Tier", description="tier",
        checkpoint_key="tier_review", fn=lambda r: None,
    )
    assert s.loop_stages == []
    assert s.loop_max == 1
    assert s.loop_until == ""


# T1: PipelineResult has last_verdict field
def test_pipeline_result_has_last_verdict():
    from orchestrator import PipelineResult
    r = PipelineResult(requirement="test")
    assert r.last_verdict == ""
    r.last_verdict = "APPROVED"
    assert r.last_verdict == "APPROVED"


# T1: Registry includes pm, pm_reviewer, architect, architect_reviewer
def test_registry_includes_pm_and_architect_stages():
    o = _make_orch()
    # Provide stubs so registry can build fn lambdas
    o.pm = MagicMock()
    o.pm_reviewer = MagicMock()
    o.architect = MagicMock()
    o.architect_reviewer = MagicMock()
    o.engineer = MagicMock()
    o.junior_engineer = MagicMock()
    o.senior_engineer = MagicMock()
    o.reviewer = MagicMock()
    o.qa = MagicMock()
    o.qa_planner = MagicMock()
    o.deployment_tester = MagicMock()
    o.tier_reviewer = MagicMock()
    registry = o._make_stage_registry()
    for name in ("pm", "pm_reviewer", "architect", "architect_reviewer"):
        assert name in registry, f"Expected {name!r} in registry"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/wanleung/Projects/ai-software-house && source venv/bin/activate && pytest tests/test_pipeline_yaml.py -v 2>&1 | head -40
```
Expected: 4 FAILs (`AttributeError` or `TypeError` on missing fields/registry entries)

- [ ] **Step 3: Add loop fields to PipelineStage**

In `orchestrator.py`, after `stop_message: str = ""` (around line 234), add:

```python
    loop_stages: list[str] = field(default_factory=list)
    """Stage names to run repeatedly. Non-empty = this is a loop block."""

    loop_max: int = 1
    """Maximum iterations for a loop block."""

    loop_until: str = ""
    """Verdict string that exits a loop block early (e.g. 'APPROVED')."""
```

- [ ] **Step 4: Add `last_verdict` to PipelineResult**

In `PipelineResult` dataclass (after `design_revision_count: int = 0` ~line 136), add:

```python
    last_verdict: str = ""
    """Set by reviewer stages inside a loop block; checked against loop_until."""
```

- [ ] **Step 5: Add pm/arch entries to `_make_stage_registry()`**

At the START of the returned dict in `_make_stage_registry()` (before `"tier_review"`), add:

```python
            "pm": PipelineStage(
                name="pm",
                label="📋 Product Manager",
                description="Analyzing requirements & writing PRD...",
                checkpoint_key="pm",
                fn=lambda r: self._stage_pm(r, r.requirement),
            ),
            "pm_reviewer": PipelineStage(
                name="pm_reviewer",
                label="📝 PM Reviewer",
                description="Reviewing PRD for completeness...",
                checkpoint_key="pm_reviewer",
                fn=lambda r: self._stage_pm_reviewer(r, r.requirement),
            ),
            "architect": PipelineStage(
                name="architect",
                label="🏗️  Architect",
                description="Designing system architecture...",
                checkpoint_key="architect",
                fn=lambda r: self._stage_architect(r),
            ),
            "architect_reviewer": PipelineStage(
                name="architect_reviewer",
                label="🔎 Architect Reviewer",
                description="Reviewing system design...",
                checkpoint_key="architect_reviewer",
                fn=lambda r: self._stage_architect_reviewer(r),
            ),
```

- [ ] **Step 6: Run tests — expect pass**

```bash
pytest tests/test_pipeline_yaml.py::test_pipeline_stage_has_loop_fields tests/test_pipeline_yaml.py::test_pipeline_stage_loop_fields_default_empty tests/test_pipeline_yaml.py::test_pipeline_result_has_last_verdict tests/test_pipeline_yaml.py::test_registry_includes_pm_and_architect_stages -v
```
Expected: 4 PASSED

- [ ] **Step 7: Run full test suite to verify no regressions**

```bash
pytest tests/ -x -q 2>&1 | tail -10
```
Expected: all passing (same count as before)

- [ ] **Step 8: Commit**

```bash
git add orchestrator.py tests/test_pipeline_yaml.py
git commit -m "feat: add PipelineStage loop fields, PipelineResult.last_verdict, pm/arch registry entries"
```

---

## Task 2: `_load_pipeline_yaml()` parser + validator

**Files:**
- Modify: `orchestrator.py` (new method after `_make_stage_registry()`)
- Modify: `tests/test_pipeline_yaml.py`

- [ ] **Step 1: Write failing tests — append to `tests/test_pipeline_yaml.py`**

```python
import pathlib
import tempfile
import yaml as _yaml


def _write_pipeline_yaml(content: str) -> str:
    """Write content to a temp pipeline.yaml and return path to its parent dir."""
    tmpdir = tempfile.mkdtemp()
    path = pathlib.Path(tmpdir) / "pipeline.yaml"
    path.write_text(content)
    # also write a dummy config.yaml so from_config can locate it
    (pathlib.Path(tmpdir) / "config.yaml").write_text("llm:\n  model: gpt-4.1\n")
    return str(pathlib.Path(tmpdir) / "config.yaml")


# Helper to get a minimal orch with all agent stubs
def _make_orch_full():
    o = _make_orch()
    for attr in ("pm", "pm_reviewer", "architect", "architect_reviewer",
                 "engineer", "junior_engineer", "senior_engineer", "reviewer",
                 "qa", "qa_planner", "deployment_tester", "tier_reviewer"):
        setattr(o, attr, MagicMock())
    return o


# T2: Valid flat stage list parses correctly
def test_load_pipeline_yaml_flat_list():
    o = _make_orch_full()
    cfg_path = _write_pipeline_yaml("stages:\n  - pm\n  - architect\n  - junior_engineer\n")
    stages = o._load_pipeline_yaml(cfg_path)
    assert stages is not None
    assert [s.name for s in stages] == ["pm", "architect", "junior_engineer"]


# T2: Valid loop block parses and expands
def test_load_pipeline_yaml_loop_block():
    o = _make_orch_full()
    cfg_path = _write_pipeline_yaml("""
stages:
  - loop:
      max: 3
      until: APPROVED
      stages:
        - pm
        - pm_reviewer
  - architect
""")
    stages = o._load_pipeline_yaml(cfg_path)
    assert stages is not None
    assert len(stages) == 2
    loop_stage = stages[0]
    assert loop_stage.loop_stages == ["pm", "pm_reviewer"]
    assert loop_stage.loop_max == 3
    assert loop_stage.loop_until == "APPROVED"
    assert stages[1].name == "architect"


# T2: Returns None when pipeline.yaml absent
def test_load_pipeline_yaml_returns_none_when_absent():
    o = _make_orch_full()
    import tempfile
    tmpdir = tempfile.mkdtemp()
    cfg_path = str(pathlib.Path(tmpdir) / "config.yaml")
    pathlib.Path(cfg_path).write_text("llm:\n  model: gpt-4.1\n")
    result = o._load_pipeline_yaml(cfg_path)
    assert result is None


# T2: Unknown stage name raises ValueError
def test_load_pipeline_yaml_unknown_stage_raises():
    o = _make_orch_full()
    cfg_path = _write_pipeline_yaml("stages:\n  - pm\n  - nonexistent_stage\n")
    with pytest.raises(ValueError, match="nonexistent_stage"):
        o._load_pipeline_yaml(cfg_path)


# T2: Missing stages key raises ValueError
def test_load_pipeline_yaml_missing_stages_raises():
    o = _make_orch_full()
    cfg_path = _write_pipeline_yaml("mode: custom\n")
    with pytest.raises(ValueError, match="stages"):
        o._load_pipeline_yaml(cfg_path)


# T2: Loop block missing 'max' raises ValueError
def test_load_pipeline_yaml_loop_missing_max_raises():
    o = _make_orch_full()
    cfg_path = _write_pipeline_yaml("""
stages:
  - loop:
      until: APPROVED
      stages:
        - pm
""")
    with pytest.raises(ValueError, match="max"):
        o._load_pipeline_yaml(cfg_path)


# T2: Loop block with max <= 0 raises ValueError
def test_load_pipeline_yaml_loop_max_zero_raises():
    o = _make_orch_full()
    cfg_path = _write_pipeline_yaml("""
stages:
  - loop:
      max: 0
      until: APPROVED
      stages:
        - pm
""")
    with pytest.raises(ValueError, match="max"):
        o._load_pipeline_yaml(cfg_path)


# T2: Empty loop stages raises ValueError
def test_load_pipeline_yaml_empty_loop_stages_raises():
    o = _make_orch_full()
    cfg_path = _write_pipeline_yaml("""
stages:
  - loop:
      max: 3
      until: APPROVED
      stages: []
""")
    with pytest.raises(ValueError, match="non-empty"):
        o._load_pipeline_yaml(cfg_path)
```

- [ ] **Step 2: Run to verify failures**

```bash
pytest tests/test_pipeline_yaml.py -k "load_pipeline_yaml" -v 2>&1 | tail -20
```
Expected: all FAILs (`AttributeError: _load_pipeline_yaml`)

- [ ] **Step 3: Implement `_load_pipeline_yaml()`**

Add as a new method in `Orchestrator` directly after `_make_stage_registry()` (around line 791):

```python
    def _load_pipeline_yaml(self, config_path: str) -> "list[PipelineStage] | None":
        """Parse and validate pipeline.yaml from the same directory as config_path.

        Returns an ordered list of PipelineStage objects, or None if the file
        does not exist. Raises ValueError on any schema violation.
        """
        import pathlib
        import yaml

        pipeline_yaml_path = pathlib.Path(config_path).parent / "pipeline.yaml"
        if not pipeline_yaml_path.exists():
            return None

        try:
            with open(pipeline_yaml_path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise yaml.YAMLError(f"Error parsing {pipeline_yaml_path}: {exc}") from exc

        if not data or not isinstance(data.get("stages"), list):
            raise ValueError(
                f"pipeline.yaml must define a 'stages' list. "
                f"Found: {type(data.get('stages')).__name__ if data else 'empty file'}"
            )

        registry = self._make_stage_registry()
        valid_names = set(registry.keys())
        stages: list[PipelineStage] = []

        for i, entry in enumerate(data["stages"]):
            if isinstance(entry, str):
                if entry not in valid_names:
                    raise ValueError(
                        f"Unknown stage {entry!r} at index {i} in pipeline.yaml. "
                        f"Valid names: {sorted(valid_names)}"
                    )
                stages.append(registry[entry])

            elif isinstance(entry, dict) and "loop" in entry:
                loop = entry["loop"]
                if not isinstance(loop, dict):
                    raise ValueError(f"Loop block at index {i} must be a mapping.")
                for required_key in ("max", "until", "stages"):
                    if required_key not in loop:
                        raise ValueError(
                            f"Loop block at index {i} missing required field '{required_key}'."
                        )
                if not isinstance(loop["stages"], list) or len(loop["stages"]) == 0:
                    raise ValueError(
                        f"Loop block at index {i} 'stages' must be a non-empty list."
                    )
                if not isinstance(loop["max"], int) or loop["max"] <= 0:
                    raise ValueError(
                        f"Loop block at index {i} 'max' must be a positive integer."
                    )
                for inner_name in loop["stages"]:
                    if inner_name not in valid_names:
                        raise ValueError(
                            f"Unknown stage {inner_name!r} inside loop block at index {i}. "
                            f"Valid names: {sorted(valid_names)}"
                        )
                inner_label = ", ".join(loop["stages"])
                stages.append(PipelineStage(
                    name=f"loop_{i}",
                    label=f"🔁 Loop ({inner_label})",
                    description=f"Running loop: {inner_label}...",
                    checkpoint_key=f"loop_{i}",
                    fn=lambda r: None,  # execution handled by _run_loop_stage()
                    loop_stages=list(loop["stages"]),
                    loop_max=int(loop["max"]),
                    loop_until=str(loop["until"]),
                ))

            else:
                raise ValueError(
                    f"Invalid stage entry at index {i}: {entry!r}. "
                    f"Expected a stage name (string) or a loop block (dict with 'loop' key)."
                )

        return stages
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_pipeline_yaml.py -k "load_pipeline_yaml" -v 2>&1 | tail -20
```
Expected: all PASSED

- [ ] **Step 5: Full suite regression check**

```bash
pytest tests/ -x -q 2>&1 | tail -10
```

- [ ] **Step 6: Commit**

```bash
git add orchestrator.py tests/test_pipeline_yaml.py
git commit -m "feat: add _load_pipeline_yaml() parser and validator"
```

---

## Task 3: Integrate pipeline.yaml into orchestrator + `_run_loop_stage()`

**Files:**
- Modify: `orchestrator.py` (`__init__`, `from_config()`, `_build_stage_list()`, `run()`, new `_run_loop_stage()`, `_stage_pm_reviewer()`, `_stage_architect_reviewer()`)
- Modify: `tests/test_pipeline_yaml.py`

- [ ] **Step 1: Write failing integration tests — append to `tests/test_pipeline_yaml.py`**

```python
import os


def _make_full_orch_with_pipeline_yaml(yaml_content: str):
    """Write pipeline.yaml, call from_config, return orchestrator."""
    import tempfile, pathlib
    from orchestrator import Orchestrator

    tmpdir = tempfile.mkdtemp()
    cfg = pathlib.Path(tmpdir) / "config.yaml"
    cfg.write_text("llm:\n  model: gpt-4.1\ngithub:\n  repo: ''\n")
    (pathlib.Path(tmpdir) / "pipeline.yaml").write_text(yaml_content)

    with patch.dict(os.environ, {"GITHUB_TOKEN": "tok"}):
        orch = Orchestrator.from_config(str(cfg), github_token="tok")
    return orch


# T3: from_config sets _pipeline_yaml_stages when pipeline.yaml present
def test_from_config_loads_pipeline_yaml_stages():
    orch = _make_full_orch_with_pipeline_yaml(
        "stages:\n  - junior_engineer\n  - reviewer\n"
    )
    assert orch._pipeline_yaml_stages is not None
    assert [s.name for s in orch._pipeline_yaml_stages] == ["junior_engineer", "reviewer"]


# T3: _build_stage_list uses pipeline_yaml_stages when set
def test_build_stage_list_uses_pipeline_yaml():
    orch = _make_full_orch_with_pipeline_yaml(
        "stages:\n  - junior_engineer\n  - reviewer\n"
    )
    stages = orch._build_stage_list()
    assert [s.name for s in stages] == ["junior_engineer", "reviewer"]


# T3: _build_stage_list falls back to MODES when pipeline.yaml absent
def test_build_stage_list_falls_back_to_modes_when_no_pipeline_yaml():
    import tempfile, pathlib
    from orchestrator import Orchestrator
    tmpdir = tempfile.mkdtemp()
    cfg = pathlib.Path(tmpdir) / "config.yaml"
    cfg.write_text("llm:\n  model: gpt-4.1\ngithub:\n  repo: ''\n")
    with patch.dict(os.environ, {"GITHUB_TOKEN": "tok"}):
        orch = Orchestrator.from_config(str(cfg), github_token="tok")
    assert orch._pipeline_yaml_stages is None
    stages = orch._build_stage_list()
    # standard mode: starts with tier_review
    assert stages[0].name == "tier_review"


# T3: pipeline_yaml_stages respects stage_skips
def test_pipeline_yaml_stages_respects_skips():
    orch = _make_full_orch_with_pipeline_yaml(
        "stages:\n  - junior_engineer\n  - reviewer\n"
    )
    orch._stage_skips = {"reviewer": True}
    stages = orch._build_stage_list()
    assert [s.name for s in stages] == ["junior_engineer"]


# T3: reviewer stages set last_verdict
def test_pm_reviewer_sets_last_verdict():
    from orchestrator import Orchestrator, PipelineResult
    from agents.pm_reviewer import PMReviewerAgent

    orch = Orchestrator.__new__(Orchestrator)
    mock_pm_rev = MagicMock()
    mock_pm_rev.run.return_value = {
        "review": "Looks good",
        "verdict": "APPROVED",
        "needs_revision": False,
        "revised_prd": None,
        "revised_project_name": "proj",
    }
    orch.pm_reviewer = mock_pm_rev
    orch.github = None
    orch.max_prd_revisions = 3

    result = PipelineResult(requirement="req", prd="some prd", project_name="proj")
    orch._stage_pm_reviewer(result, "req")

    assert result.last_verdict == "APPROVED"


def test_architect_reviewer_sets_last_verdict():
    from orchestrator import Orchestrator, PipelineResult
    from agents.architect_reviewer import ArchitectReviewerAgent

    orch = Orchestrator.__new__(Orchestrator)
    mock_arch_rev = MagicMock()
    mock_arch_rev.run.return_value = {
        "review": "Design ok",
        "verdict": "APPROVED",
        "needs_revision": False,
        "revised_design": None,
        "revised_modules": [],
    }
    orch.architect_reviewer = mock_arch_rev
    orch.github = None
    orch.max_design_revisions = 3

    result = PipelineResult(requirement="req", prd="prd", design="design", modules=[])
    orch._stage_architect_reviewer(result)

    assert result.last_verdict == "APPROVED"
```

- [ ] **Step 2: Run to verify failures**

```bash
pytest tests/test_pipeline_yaml.py -k "from_config or build_stage_list or last_verdict or pipeline_yaml" -v 2>&1 | tail -30
```
Expected: FAILs on missing `_pipeline_yaml_stages` attribute and missing `last_verdict` being set.

- [ ] **Step 3: Add `_pipeline_yaml_stages` to `Orchestrator.__init__`**

In `__init__` signature, add after `stage_skips: dict[str, bool] | None = None,`:

```python
        pipeline_yaml_stages: "list[PipelineStage] | None" = None,
```

In the `__init__` body, after `self._stage_skips = stage_skips or {}`, add:

```python
        self._pipeline_yaml_stages: "list[PipelineStage] | None" = pipeline_yaml_stages
```

- [ ] **Step 4: Update `from_config()` to load pipeline.yaml**

In `from_config()`, after the line `pipeline_mode = pipeline.get("mode", "standard")` (around line 639), add:

```python
        # Load pipeline.yaml from same directory as config file (overrides pipeline.mode)
        _temp_orch_for_load = cls.__new__(cls)
        _temp_orch_for_load._stage_skips = {}
        _temp_orch_for_load._pipeline_yaml_stages = None
        _temp_orch_for_load._mode = pipeline_mode
        # Stub agent attributes so _make_stage_registry() can build fn lambdas
        for _attr in ("pm", "pm_reviewer", "architect", "architect_reviewer",
                      "engineer", "junior_engineer", "senior_engineer", "reviewer",
                      "qa", "qa_planner", "deployment_tester", "tier_reviewer"):
            setattr(_temp_orch_for_load, _attr, None)
        pipeline_yaml_stages = _temp_orch_for_load._load_pipeline_yaml(config_path)
        if pipeline_yaml_stages is not None:
            import logging
            logging.debug("pipeline.yaml found — pipeline.mode in config.yaml is ignored.")
```

Then in the `cls(...)` constructor call at the end of `from_config()`, add:

```python
            pipeline_yaml_stages=pipeline_yaml_stages,
```

- [ ] **Step 5: Update `_build_stage_list()` to use pipeline_yaml_stages**

Replace the existing `_build_stage_list()` method body with:

```python
    def _build_stage_list(self) -> list[PipelineStage]:
        """Return the ordered stage list, applying skip overrides.

        When _pipeline_yaml_stages is set (pipeline.yaml present), that list
        takes full precedence. Otherwise falls back to MODES[_mode].
        """
        if self._pipeline_yaml_stages is not None:
            return [
                s for s in self._pipeline_yaml_stages
                if not self._stage_skips.get(s.name, False)
            ]

        registry = self._make_stage_registry()
        if self._mode not in MODES:
            raise ValueError(
                f"Unknown pipeline.mode {self._mode!r}. Valid modes: {list(MODES)}"
            )
        stage_names = MODES[self._mode]
        return [
            registry[name]
            for name in stage_names
            if name in registry and not self._stage_skips.get(name, False)
        ]
```

- [ ] **Step 6: Make reviewer stages set `last_verdict`**

In `_stage_pm_reviewer()` (around line 1258), after `result.prd_verdict = rev_result["verdict"]` add:

```python
        result.last_verdict = result.prd_verdict
```

In `_stage_architect_reviewer()` (around line 1529), after `result.design_verdict = rev_result["verdict"]` add:

```python
        result.last_verdict = result.design_verdict
```

- [ ] **Step 7: Add `_run_loop_stage()` method**

Add after `_build_stage_list()`:

```python
    def _run_loop_stage(self, loop_stage: "PipelineStage", result: "PipelineResult") -> bool:
        """Execute a loop block from pipeline.yaml.

        Runs inner stages repeatedly until loop_until verdict is seen or loop_max
        iterations are exhausted. Returns True to continue pipeline, False on error.
        """
        registry = self._make_stage_registry()
        console.print(f"\n  {loop_stage.label}")

        for iteration in range(loop_stage.loop_max):
            result.last_verdict = ""
            for inner_name in loop_stage.loop_stages:
                inner = registry[inner_name]
                self._run_stage(
                    inner.label, inner.description, result,
                    lambda s=inner: s.fn(result)
                )
                if result.errors:
                    return False

            if result.last_verdict == loop_stage.loop_until:
                console.print(
                    f"  ✅ [green]Loop condition met: {loop_stage.loop_until} "
                    f"(round {iteration + 1})[/green]"
                )
                break

            if iteration < loop_stage.loop_max - 1:
                console.print(
                    f"  🔄 [yellow]Round {iteration + 1}/{loop_stage.loop_max} — "
                    f"verdict: {result.last_verdict or 'none'}, retrying...[/yellow]"
                )

        return True
```

- [ ] **Step 8: Update `run()` to handle loop stages + skip hardcoded PM/arch loops when pipeline.yaml is active**

In `run()`, find the two hardcoded loop guard blocks (around lines 1167–1181):

```python
        # ── Stage 1: PM + PM Reviewer revision loop ───────────────────────────
        if "pm_review_loop" not in result.completed_stages:
            ...
        # ── Stage 2: Architect + Architect Reviewer revision loop ─────────────
        if "architect_review_loop" not in result.completed_stages:
            ...
```

Wrap BOTH blocks with a `if self._pipeline_yaml_stages is None:` guard:

```python
        if self._pipeline_yaml_stages is None:
            # ── Stage 1: PM + PM Reviewer revision loop ───────────────────────
            if "pm_review_loop" not in result.completed_stages:
                ok = self._prd_revision_loop(result, requirement)
                if not ok:
                    return self._finish(result, start_time)
            else:
                console.print("  ⏭️  [dim]PRD revision loop — skipped (checkpoint)[/dim]")

            # ── Stage 2: Architect + Architect Reviewer revision loop ─────────
            if "architect_review_loop" not in result.completed_stages:
                ok = self._design_revision_loop(result)
                if not ok:
                    return self._finish(result, start_time)
            else:
                console.print("  ⏭️  [dim]Design revision loop — skipped (checkpoint)[/dim]")
```

Then in the `_build_stage_list()` loop (around line 1205), add loop-stage dispatch:

```python
        for stage in self._build_stage_list():
            if stage.checkpoint_key in result.completed_stages or stage.name in result.completed_stages:
                console.print(f"  ⏭️  [dim]{stage.label} — skipped (checkpoint)[/dim]")
                continue

            if stage.skip_if(result):
                console.print(f"  ⏭️  [dim]{stage.label} — skipped[/dim]")
                continue

            if stage.loop_stages:
                # Loop block from pipeline.yaml
                ok = self._run_loop_stage(stage, result)
                if not ok:
                    self._save_checkpoint(result)
                    return self._finish(result, start_time)
            else:
                self._run_stage(stage.label, stage.description, result, lambda s=stage: s.fn(result))
                if result.errors:
                    self._save_checkpoint(result)
                    return self._finish(result, start_time)

            if stage.name == "senior_engineer":
                result.completed_stages.append("engineer")

            result.completed_stages.append(stage.checkpoint_key)
            self._save_checkpoint(result)

            if stage.stop_if(result):
                if stage.stop_message:
                    console.print(f"[bold red]{stage.stop_message}[/bold red]")
                return self._finish(result, start_time)
```

- [ ] **Step 9: Run integration tests**

```bash
pytest tests/test_pipeline_yaml.py -v 2>&1 | tail -30
```
Expected: all PASSED

- [ ] **Step 10: Full regression check**

```bash
pytest tests/ -x -q 2>&1 | tail -10
```

- [ ] **Step 11: Commit**

```bash
git add orchestrator.py tests/test_pipeline_yaml.py
git commit -m "feat: integrate pipeline.yaml into orchestrator — from_config, _build_stage_list, run, _run_loop_stage"
```

---

## Task 4: GUI Config Builder (`pipeline_builder/`)

**Files:**
- Create: `pipeline_builder/__init__.py`
- Create: `pipeline_builder/server.py`
- Create: `pipeline_builder/index.html`

No automated tests for the GUI (manual smoke test in Step 4).

- [ ] **Step 1: Create package marker**

```bash
mkdir -p /home/wanleung/Projects/ai-software-house/pipeline_builder
touch /home/wanleung/Projects/ai-software-house/pipeline_builder/__init__.py
```

- [ ] **Step 2: Create `pipeline_builder/server.py`**

```python
"""Minimal HTTP server for the pipeline.yaml config builder GUI.

Usage (via main.py --config-builder):
    from pipeline_builder.server import run_builder
    run_builder(config_path="config.yaml")
"""
from __future__ import annotations

import json
import os
import pathlib
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

_STATIC_DIR = pathlib.Path(__file__).parent


def _get_stage_palette() -> list[dict]:
    """Return stage metadata for the GUI palette, derived from _make_stage_registry()."""
    try:
        from orchestrator import Orchestrator
        # Build a minimal stub orchestrator just to call _make_stage_registry()
        orch = Orchestrator.__new__(Orchestrator)
        orch._stage_skips = {}
        orch._pipeline_yaml_stages = None
        orch._mode = "standard"
        for attr in ("pm", "pm_reviewer", "architect", "architect_reviewer",
                     "engineer", "junior_engineer", "senior_engineer", "reviewer",
                     "qa", "qa_planner", "deployment_tester", "tier_reviewer"):
            setattr(orch, attr, None)
        registry = orch._make_stage_registry()
        return [
            {"name": name, "label": stage.label, "description": stage.description}
            for name, stage in registry.items()
        ]
    except Exception as exc:
        return [{"name": "error", "label": f"Registry error: {exc}", "description": ""}]


def _load_existing_pipeline_yaml(config_path: str) -> Optional[str]:
    """Return raw pipeline.yaml text if it exists, else None."""
    p = pathlib.Path(config_path).parent / "pipeline.yaml"
    return p.read_text(encoding="utf-8") if p.exists() else None


def _save_pipeline_yaml(config_path: str, content: str) -> None:
    p = pathlib.Path(config_path).parent / "pipeline.yaml"
    p.write_text(content, encoding="utf-8")


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def run_builder(config_path: str = "config.yaml") -> None:
    """Start the pipeline config builder server and open the browser."""
    config_path = str(pathlib.Path(config_path).resolve())
    port = _find_free_port()
    palette = _get_stage_palette()
    existing_yaml = _load_existing_pipeline_yaml(config_path)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # silence default access log
            pass

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                html_path = _STATIC_DIR / "index.html"
                body = html_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/palette":
                body = json.dumps(palette).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/current":
                body = json.dumps({"yaml": existing_yaml}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == "/save":
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                try:
                    data = json.loads(body)
                    _save_pipeline_yaml(config_path, data["yaml"])
                    resp = json.dumps({"ok": True}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(resp)
                except Exception as exc:
                    resp = json.dumps({"ok": False, "error": str(exc)}).encode()
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(resp)
            else:
                self.send_response(404)
                self.end_headers()

    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://localhost:{port}"
    print(f"\n🧩 Pipeline Config Builder ready at {url}")
    print(f"   Editing: {pathlib.Path(config_path).parent / 'pipeline.yaml'}")
    print("   Press Ctrl+C to exit.\n")

    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n✅ Builder closed.")
```

- [ ] **Step 3: Create `pipeline_builder/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>🧩 Pipeline Config Builder</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #1e1e2e; color: #cdd6f4; min-height: 100vh; }
  header { background: #181825; padding: 12px 20px; display: flex;
           justify-content: space-between; align-items: center;
           border-bottom: 1px solid #313244; }
  header h1 { font-size: 16px; }
  .btn { background: #a6e3a1; color: #1e1e2e; border: none; border-radius: 6px;
         padding: 6px 16px; font-size: 13px; cursor: pointer; font-weight: 600; }
  .btn:hover { background: #94d49a; }
  .btn-secondary { background: #313244; color: #cdd6f4; }
  .btn-secondary:hover { background: #45475a; }
  .layout { display: flex; height: calc(100vh - 49px); }
  .palette { width: 160px; background: #181825; border-right: 1px solid #313244;
             padding: 12px; overflow-y: auto; }
  .palette h3 { font-size: 11px; text-transform: uppercase; color: #6c7086;
                margin-bottom: 10px; letter-spacing: 0.05em; }
  .palette-item { background: #313244; border-radius: 6px; padding: 7px 10px;
                  font-size: 12px; cursor: grab; margin-bottom: 5px;
                  border: 1px solid transparent; user-select: none; }
  .palette-item:hover { border-color: #89b4fa; }
  .palette-item.loop-block { border-color: #f9e2af; color: #f9e2af; }
  .canvas { flex: 1; padding: 16px; overflow-y: auto; }
  .canvas h3 { font-size: 11px; text-transform: uppercase; color: #6c7086;
               margin-bottom: 12px; letter-spacing: 0.05em; }
  .stage-list { min-height: 120px; display: flex; flex-direction: column; gap: 6px; }
  .stage-item { background: #313244; border: 1px solid #45475a; border-radius: 8px;
                padding: 8px 12px; display: flex; justify-content: space-between;
                align-items: center; font-size: 13px; cursor: grab; }
  .stage-item:hover { border-color: #89b4fa; }
  .loop-item { border: 2px solid #f9e2af; border-radius: 8px; padding: 10px 12px; }
  .loop-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
                 font-size: 12px; color: #f9e2af; }
  .loop-header input[type=number] { width: 44px; background: #1e1e2e; border: 1px solid #6c7086;
                                     color: #cdd6f4; border-radius: 4px; padding: 2px 5px; }
  .loop-inner { min-height: 40px; background: #1e1e2e; border-radius: 6px; padding: 8px;
                display: flex; flex-direction: column; gap: 5px;
                border: 1px dashed #45475a; }
  .loop-inner .stage-item { font-size: 12px; padding: 5px 10px; }
  .remove-btn { background: none; border: none; color: #f38ba8; cursor: pointer;
                font-size: 16px; line-height: 1; padding: 0 4px; }
  .drop-zone { border: 2px dashed #45475a; border-radius: 8px; padding: 14px;
               text-align: center; color: #6c7086; font-size: 12px; margin-top: 8px; }
  .drop-zone.drag-over { border-color: #89b4fa; background: #1e3a5f22; }
  .preview { width: 280px; background: #181825; border-left: 1px solid #313244;
             padding: 12px; overflow-y: auto; }
  .preview h3 { font-size: 11px; text-transform: uppercase; color: #6c7086;
                margin-bottom: 10px; letter-spacing: 0.05em; }
  pre { font-size: 11px; color: #a6e3a1; white-space: pre-wrap; word-break: break-all; }
  .toast { position: fixed; bottom: 20px; right: 20px; background: #a6e3a1; color: #1e1e2e;
           padding: 10px 18px; border-radius: 8px; font-size: 13px; font-weight: 600;
           display: none; z-index: 100; }
</style>
</head>
<body>
<header>
  <h1>🧩 Pipeline Config Builder</h1>
  <div style="display:flex;gap:8px">
    <button class="btn btn-secondary" onclick="clearAll()">Clear</button>
    <button class="btn" onclick="saveYaml()">Save pipeline.yaml ↓</button>
  </div>
</header>
<div class="layout">
  <div class="palette">
    <h3>Blocks</h3>
    <div id="palette-stages"></div>
    <div style="margin-top:12px;border-top:1px solid #313244;padding-top:12px">
      <div class="palette-item loop-block" draggable="true"
           ondragstart="dragStartLoop(event)">🔁 Loop</div>
    </div>
  </div>
  <div class="canvas">
    <h3>Pipeline Sequence — drag to reorder</h3>
    <div class="stage-list" id="stage-list"
         ondragover="allowDrop(event)" ondrop="dropOnList(event)"></div>
    <div class="drop-zone" id="main-drop"
         ondragover="allowDrop(event,true)" ondrop="dropOnList(event)">
      Drop blocks here
    </div>
  </div>
  <div class="preview">
    <h3>pipeline.yaml preview</h3>
    <pre id="yaml-preview"></pre>
  </div>
</div>
<div class="toast" id="toast">✅ Saved!</div>

<script>
let stages = [];          // array of {type:'stage',name,label} | {type:'loop',max,until,stages:[]}
let dragSource = null;    // {context:'palette'|'list', index, loopIndex}
let palette = [];

async function init() {
  const [palRes, curRes] = await Promise.all([
    fetch('/palette').then(r => r.json()),
    fetch('/current').then(r => r.json()),
  ]);
  palette = palRes;
  renderPalette();
  if (curRes.yaml) {
    stages = parseYaml(curRes.yaml);
    render();
  }
}

function renderPalette() {
  const el = document.getElementById('palette-stages');
  el.innerHTML = '';
  palette.forEach(s => {
    const div = document.createElement('div');
    div.className = 'palette-item';
    div.draggable = true;
    div.textContent = s.label;
    div.title = s.description;
    div.ondragstart = e => dragStartPalette(e, s.name, s.label);
    el.appendChild(div);
  });
}

function dragStartPalette(e, name, label) {
  dragSource = {context:'palette', name, label};
  e.dataTransfer.effectAllowed = 'copy';
}

function dragStartLoop(e) {
  dragSource = {context:'palette', type:'loop'};
  e.dataTransfer.effectAllowed = 'copy';
}

function dragStartListItem(e, idx, loopIdx) {
  dragSource = {context:'list', index:idx, loopIndex:loopIdx};
  e.dataTransfer.effectAllowed = 'move';
  e.stopPropagation();
}

function allowDrop(e, highlight) {
  e.preventDefault();
  if (highlight) e.currentTarget.classList.add('drag-over');
}

function dropOnList(e) {
  e.preventDefault();
  document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
  if (!dragSource) return;
  if (dragSource.context === 'palette') {
    if (dragSource.type === 'loop') {
      stages.push({type:'loop', max:3, until:'APPROVED', stages:[]});
    } else {
      stages.push({type:'stage', name:dragSource.name, label:dragSource.label});
    }
  }
  dragSource = null;
  render();
}

function dropOnLoop(e, loopIdx) {
  e.preventDefault(); e.stopPropagation();
  document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
  if (!dragSource || dragSource.context !== 'palette' || dragSource.type === 'loop') return;
  stages[loopIdx].stages.push({name:dragSource.name, label:dragSource.label});
  dragSource = null;
  render();
}

function removeItem(idx, loopIdx) {
  if (loopIdx !== undefined) {
    stages[idx].stages.splice(loopIdx, 1);
  } else {
    stages.splice(idx, 1);
  }
  render();
}

function clearAll() { stages = []; render(); }

function render() {
  const list = document.getElementById('stage-list');
  list.innerHTML = '';
  stages.forEach((item, idx) => {
    if (item.type === 'stage') {
      const div = document.createElement('div');
      div.className = 'stage-item';
      div.draggable = true;
      div.ondragstart = e => dragStartListItem(e, idx);
      div.innerHTML = `<span>${item.label}</span>
        <button class="remove-btn" onclick="removeItem(${idx})">×</button>`;
      list.appendChild(div);
    } else {
      const wrap = document.createElement('div');
      wrap.className = 'loop-item';
      wrap.innerHTML = `
        <div class="loop-header">
          🔁 Loop — max:
          <input type="number" min="1" max="10" value="${item.max}"
            oninput="stages[${idx}].max=parseInt(this.value)||1;updatePreview()">
          until:
          <select style="background:#1e1e2e;color:#cdd6f4;border:1px solid #6c7086;border-radius:4px;padding:2px"
            onchange="stages[${idx}].until=this.value;updatePreview()">
            <option ${item.until==='APPROVED'?'selected':''}>APPROVED</option>
            <option ${item.until==='CHANGES_REQUESTED'?'selected':''}>CHANGES_REQUESTED</option>
          </select>
          <button class="remove-btn" style="margin-left:auto" onclick="removeItem(${idx})">×</button>
        </div>
        <div class="loop-inner" id="loop-inner-${idx}"
          ondragover="allowDrop(event,true)" ondrop="dropOnLoop(event,${idx})">
          ${item.stages.map((s,si) => `
            <div class="stage-item">
              <span>${s.label}</span>
              <button class="remove-btn" onclick="removeItem(${idx},${si})">×</button>
            </div>`).join('')}
          ${item.stages.length===0?'<div style="color:#6c7086;font-size:11px;text-align:center">Drop stages here</div>':''}
        </div>`;
      list.appendChild(wrap);
    }
  });
  updatePreview();
}

function toYaml() {
  if (!stages.length) return '';
  let out = 'stages:\n';
  stages.forEach(item => {
    if (item.type === 'stage') {
      out += `  - ${item.name}\n`;
    } else {
      out += `  - loop:\n`;
      out += `      max: ${item.max}\n`;
      out += `      until: ${item.until}\n`;
      out += `      stages:\n`;
      item.stages.forEach(s => { out += `        - ${s.name}\n`; });
    }
  });
  return out;
}

function updatePreview() {
  document.getElementById('yaml-preview').textContent = toYaml() || '# Empty pipeline';
}

function parseYaml(text) {
  // Minimal YAML parser for pipeline.yaml format (no external deps)
  const result = [];
  const lines = text.split('\n');
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const stageMatch = line.match(/^\s{2}-\s+(\w+)\s*$/);
    const loopMatch = line.match(/^\s{2}-\s+loop:\s*$/);
    if (stageMatch) {
      const name = stageMatch[1];
      const pal = palette.find(p => p.name === name);
      result.push({type:'stage', name, label: pal ? pal.label : name});
    } else if (loopMatch) {
      const loop = {type:'loop', max:3, until:'APPROVED', stages:[]};
      i++;
      while (i < lines.length) {
        const l = lines[i];
        const maxM = l.match(/^\s+max:\s+(\d+)/);
        const untilM = l.match(/^\s+until:\s+(\S+)/);
        const innerM = l.match(/^\s{8}-\s+(\w+)/);
        if (maxM) loop.max = parseInt(maxM[1]);
        else if (untilM) loop.until = untilM[1];
        else if (innerM) {
          const name = innerM[1];
          const pal = palette.find(p => p.name === name);
          loop.stages.push({name, label: pal ? pal.label : name});
        } else if (l.match(/^\s{2}-/)) { i--; break; }
        i++;
      }
      result.push(loop);
      continue;
    }
    i++;
  }
  return result;
}

async function saveYaml() {
  const yaml = toYaml();
  if (!yaml) { alert('Pipeline is empty — add some stages first.'); return; }
  const resp = await fetch('/save', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({yaml}),
  });
  const data = await resp.json();
  if (data.ok) {
    const toast = document.getElementById('toast');
    toast.style.display = 'block';
    setTimeout(() => toast.style.display = 'none', 2500);
  } else {
    alert('Save failed: ' + data.error);
  }
}

init();
</script>
</body>
</html>
```

- [ ] **Step 4: Manual smoke test**

```bash
cd /home/wanleung/Projects/ai-software-house && source venv/bin/activate
python -c "from pipeline_builder.server import run_builder; run_builder('config.yaml')"
```

Expected: browser opens at `http://localhost:<port>`, shows stage palette on left, drag a few stages to canvas, click "Save pipeline.yaml", verify file written:

```bash
cat pipeline.yaml
```

Press Ctrl+C to stop.

- [ ] **Step 5: Commit**

```bash
git add pipeline_builder/
git commit -m "feat: add pipeline_builder GUI server and drag-and-drop index.html"
```

---

## Task 5: `main.py --config-builder` + `config.yaml` comment

**Files:**
- Modify: `main.py`
- Modify: `config.yaml`

- [ ] **Step 1: Add `--config-builder` flag to `parse_args()` in `main.py`**

After the `--update-skills` argument (around line 151), add:

```python
    parser.add_argument(
        "--config-builder",
        action="store_true",
        dest="config_builder",
        help="Open the visual pipeline.yaml config builder in your browser, then exit.",
    )
```

- [ ] **Step 2: Handle `--config-builder` in `main()`**

In `main()`, before the `# ── Token` block (around line 185), add an early-exit block:

```python
    # ── Config builder ───────────────────────────────────────────────────────
    if args.config_builder:
        from pipeline_builder.server import run_builder
        run_builder(config_path=args.config)
        return 0
```

- [ ] **Step 3: Update `config.yaml` comment for `pipeline.mode`**

Find the existing comment block above `mode: standard` in `config.yaml` and replace it with:

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
  # Note: if pipeline.yaml exists in this directory, it takes full control and
  # this setting is ignored. Generate pipeline.yaml with:
  #   python main.py --config-builder
  #
  mode: standard
```

- [ ] **Step 4: Verify CLI works**

```bash
python main.py --help | grep config-builder
```
Expected: `--config-builder  Open the visual pipeline.yaml config builder...`

- [ ] **Step 5: Full test suite — final check**

```bash
pytest tests/ -x -q 2>&1 | tail -10
```
Expected: all passing

- [ ] **Step 6: Commit**

```bash
git add main.py config.yaml
git commit -m "feat: add --config-builder CLI flag and update config.yaml comment"
```

---

## Task 6: Open PR

- [ ] **Step 1: Push branch**

```bash
git push -u origin feature/blocky-pipeline
```

- [ ] **Step 2: Create PR**

```bash
gh pr create \
  --title "feat: blocky pipeline — pipeline.yaml + GUI config builder" \
  --body "## Summary

- Adds \`pipeline.yaml\` support: a separate file defining a fully custom stage sequence with explicit \`loop:\` blocks
- \`pipeline.yaml\` fully replaces \`pipeline.mode\` in \`config.yaml\` when present (backwards compatible — existing configs unchanged)
- Loop blocks: \`loop.max\`, \`loop.until\`, \`loop.stages\` — reviewer stages set \`result.last_verdict\` as exit condition
- \`_make_stage_registry()\` is the single source of truth for valid stage names — GUI palette and validator both derive from it
- \`pipeline_builder/\`: self-contained drag-and-drop GUI (vanilla JS + Python stdlib HTTP server)
- \`python main.py --config-builder\` launches the GUI, opens browser, saves \`pipeline.yaml\`
- pm, pm_reviewer, architect, architect_reviewer added to stage registry (usable in custom pipelines)

## Test Plan
- [ ] \`pytest tests/test_pipeline_yaml.py\` — all tests pass
- [ ] \`pytest tests/ -x -q\` — no regressions
- [ ] Manual: \`python main.py --config-builder\`, drag stages, save, run pipeline

## Spec
\`docs/superpowers/specs/2026-04-28-blocky-pipeline-design.md\`
" \
  --base master
```

---

## Self-Review Notes

**Spec coverage check:**
- ✅ `pipeline.yaml` format (T2)
- ✅ Schema validation with clear errors (T2)
- ✅ `_make_stage_registry()` as single source of truth (T1 — pm/arch added; T4 — GUI reads it)
- ✅ GUI builder via `python main.py --config-builder` (T4, T5)
- ✅ `pipeline.yaml` fully replaces `pipeline.mode` when present (T3)
- ✅ Falls back to `pipeline.mode` when absent (T3)
- ✅ Loop blocks execute inner stages, exit on `loop_until` verdict (T3 — `_run_loop_stage`)
- ✅ Reviewer stages set `last_verdict` (T3)
- ✅ Backwards compatibility: hardcoded PM/arch loops guarded by `pipeline_yaml_stages is None` (T3)
- ✅ `config.yaml` comment update (T5)

**Type consistency:**
- `PipelineStage.loop_stages: list[str]` — used in T1 (definition), T2 (parser output), T3 (`_run_loop_stage` checks `stage.loop_stages`)
- `PipelineResult.last_verdict: str` — set in T1 (definition), T3 (reviewer stages + `_run_loop_stage` reset), checked in T3
- `Orchestrator._pipeline_yaml_stages` — set in T3 (`__init__`, `from_config`), read in T3 (`_build_stage_list`, `run`)
