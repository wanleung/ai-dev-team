# TDD Pipeline Mode Design

**Date:** 2026-04-27
**Status:** Approved

## Problem

The pipeline has a fixed hardcoded stage sequence: engineers write code, then QA writes and runs tests. This is the standard waterfall order. TDD requires inverting it — QA writes tests first, engineers implement against them. There is no way to select this behaviour without editing Python source.

## Goal

Add a `pipeline.mode` config key that selects between named stage sequences. Implement two modes: `standard` (current behaviour, default) and `tdd` (QA before engineers). Lay the groundwork for a future user-defined `custom` mode without implementing it yet.

---

## Architecture

### Stage Registry

Each pipeline stage is described by a `PipelineStage` dataclass:

```python
@dataclass
class PipelineStage:
    name: str                                        # identifier used in MODES and config
    label: str                                       # display label (emoji + text)
    fn: Callable[[PipelineResult], None]             # the stage callable
    skip_if: Callable[[PipelineResult], bool] = ...  # default: never skip
```

A module-level `MODES` dict maps mode name → ordered list of stage names:

```python
MODES: dict[str, list[str]] = {
    "standard": [
        "pm", "architect", "tier_review", "engineers",
        "reviewer", "qa_planner", "qa_engineer",
        "test_fix", "deploy_tester", "deploy_fix",
    ],
    "tdd": [
        "pm", "architect", "qa_planner", "qa_write",
        "tier_review", "engineers",
        "test_fix", "reviewer",
        "deploy_tester", "deploy_fix",
    ],
}
```

> **Note:** The stage registry covers post-architect stages only. The PM (PRD) and
> Architect (design) revision loops are hardcoded before the stage loop and are not
> part of `MODES`.

### `run()` refactor

The ~15 hardcoded `_run_stage(...)` calls in `run()` are replaced by:

```python
for stage in self._build_stage_list():
    if stage.skip_if(result):
        continue
    self._run_stage(stage.label, ..., result, stage.fn)
```

`_build_stage_list()` reads `self._mode`, looks up `MODES[mode]`, applies per-stage `skip` overrides from config, and returns the ordered list.

---

## Stage Sequence Comparison

| Order | standard | tdd |
|-------|----------|-----|
| 1 | PM + PRD revision loop | PM + PRD revision loop |
| 2 | Architect + design revision loop | Architect + design revision loop |
| 3 | Tier Review | QA Planner |
| 4 | Engineers (parallel) | **QA Write** (new stage) |
| 5 | Code Reviewer | Tier Review |
| 6 | QA Planner | Engineers (parallel, with test files) |
| 7 | QA Engineer (write + run) | Test Fix Loop |
| 8 | Test Fix Loop | Code Reviewer* |
| 9 | Deployment Tester | Deployment Tester |
| 10 | Deploy Fix Loop | Deploy Fix Loop |

*Code Reviewer in TDD mode is optional — skippable via `stages.reviewer.skip: true`.

---

## New `qa_write` Stage

A new stage `qa_write` calls `QAEngineerAgent` with a `write_only=True` flag:

- Generates test files and stores them in `result.test_files`
- Does **not** execute tests
- Does **not** write a test report

`QAEngineerAgent.run()` gains a `write_only: bool = False` parameter:

```python
def run(self, ..., write_only: bool = False) -> dict:
    test_files = self._generate_tests(prd, design, code_files)
    if write_only:
        return {"test_files": test_files}
    # ... write to workspace, run pytest, return results
```

---

## Engineers in TDD Mode

When `result.test_files` is non-empty at the start of the engineer stage, each engineer's prompt includes the relevant test files:

```
Here are the pre-written tests your module must pass:

### FILE: tests/test_<module>.py
<content>

Implement the module so these tests pass.
```

The engineer stage passes **all** test files to every engineer. Each engineer sees the full test suite and implements only its assigned module. This avoids brittle name-matching logic and lets engineers understand the expected interfaces of other modules.

---

## Data Flow

No new `PipelineResult` fields are needed. `result.test_files` already exists and is populated in the normal QA stage. In TDD mode, it is populated by `qa_write` before the engineer stage.

```
qa_write → result.test_files → engineer stage reads → test_fix runs → result.test_output
```

---

## Config Changes

```yaml
pipeline:
  mode: standard        # standard (default) or tdd

  stages:
    reviewer:
      skip: false       # set true to skip Code Reviewer (useful in TDD mode)
    deploy_tester:
      skip: false       # existing skip patterns work the same way
```

`mode` defaults to `standard` — all existing configs work unchanged.

---

## Backward Compatibility

- `mode` key is optional; defaults to `standard`
- All existing tests continue to pass
- No changes to agent classes except `QAEngineerAgent.run()` gaining `write_only=False`
- `PipelineResult` schema unchanged

---

## Future: Custom Mode

When the user wants to define a custom sequence:

```yaml
pipeline:
  mode: custom
  custom_stages: [pm, architect, qa_planner, qa_write, engineers, test_fix]
```

`_build_stage_list()` would read `custom_stages` as a third mode. No changes to `MODES` or the registry are required — the extension point is already present.

---

## Files to Change

| File | Change |
|------|--------|
| `orchestrator.py` | Add `PipelineStage` dataclass, `MODES` dict, `_build_stage_list()`, refactor `run()`, read `mode` + `stages` from config |
| `agents/qa_engineer.py` | Add `write_only: bool = False` parameter to `run()` |
| `config.yaml` | Document `pipeline.mode` and `pipeline.stages.<name>.skip` |
| `tests/test_pipeline_modes.py` | New test file: standard mode produces same order, tdd mode reorders stages, qa_write populates test_files, engineers receive test files |
| `tests/test_orchestrator.py` | Update any tests that assert hardcoded stage call order |

---

## Delivery

Via pull request: `feature/tdd-pipeline-mode` → `master`.
