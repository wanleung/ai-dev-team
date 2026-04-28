# Blocky Pipeline Design

**Date:** 2026-04-28  
**Status:** Approved

## Problem

The pipeline execution order is currently controlled by `pipeline.mode` in `config.yaml`, offering only two built-in sequences (`standard`, `tdd`). Users cannot define a fully custom stage sequence, reorder stages arbitrarily, or configure review loops with custom iteration counts. Editing `config.yaml` directly for complex flow changes is error-prone with no validation.

## Proposed Approach

Introduce a **separate `pipeline.yaml` file** for stage flow configuration, with an **explicit `loop:` block syntax** for review loops. A **GUI config builder** (`python main.py --config-builder`) generates valid `pipeline.yaml` via a browser-based drag-and-drop interface.

`pipeline.yaml` fully replaces `pipeline.mode` in `config.yaml` when present. When absent, the system falls back to the existing `pipeline.mode` behaviour (backwards compatible).

---

## 1. `pipeline.yaml` Format

A standalone file in the project root (alongside `config.yaml`) defining the complete stage execution sequence.

### Simple stage list

```yaml
# pipeline.yaml
stages:
  - pm
  - architect
  - junior_engineer
  - reviewer
  - qa_planner
  - qa_engineer
  - deploy_tester
```

### With loop blocks

```yaml
stages:
  - loop:
      max: 3
      until: APPROVED
      stages:
        - pm
        - pm_reviewer

  - loop:
      max: 3
      until: APPROVED
      stages:
        - architect
        - architect_reviewer

  - qa_planner
  - qa_write           # TDD: write tests before code
  - tier_review
  - junior_engineer
  - senior_engineer
  - test_fix
  - reviewer
  - deploy_tester
  - deploy_fix
```

### Schema rules

| Field | Type | Description |
|---|---|---|
| `stages` | list | Ordered list of stage entries |
| Stage entry | string | Name of a known stage (see valid names below) |
| `loop.max` | int | Maximum iterations before exiting the loop |
| `loop.until` | string | Verdict string that exits the loop early (e.g. `APPROVED`) |
| `loop.stages` | list | Ordered list of stage names inside the loop |

**Valid stage names** are derived at runtime from `_make_stage_registry()` in `orchestrator.py` — this is the single source of truth. Current names: `pm`, `pm_reviewer`, `architect`, `architect_reviewer`, `tier_review`, `junior_engineer`, `senior_engineer`, `reviewer`, `qa_planner`, `qa_write`, `qa_engineer`, `test_fix`, `deploy_tester`, `deploy_fix`

> **Adding a new agent:** Register it in `_make_stage_registry()`. The GUI palette and `pipeline.yaml` validator both derive valid names from the registry at startup, so no other registration step is needed.

**Validation errors** (raised at startup, before any LLM call):
- Unknown stage name
- `loop` block missing `stages`, `max`, or `until`
- `loop.max` ≤ 0
- Empty `stages` list
- `pipeline.yaml` present but `stages` key is missing or not a list

---

## 2. Pipeline Loading Logic

```
1. Look for pipeline.yaml in the project root (same dir as config.yaml)
2. If found → parse and validate; build stage list from pipeline.yaml
   - pipeline.mode in config.yaml is ignored (log a debug note)
3. If not found → fall back to existing MODES[pipeline.mode] logic
```

`Orchestrator.from_config()` is the load point. A new `_load_pipeline_yaml()` helper reads and validates the file, returning a flat list of `PipelineStage` objects (loops are expanded into the existing `PipelineStage` structure with a `loop_max` and `loop_until` field pair added to the dataclass).

### Loop execution

A loop block becomes a named pseudo-stage internally with an auto-generated name (e.g. `loop_0`, `loop_1`) based on its position in the stage list. The `PipelineStage` dataclass gains two new optional fields: `loop_stages: list[str] | None` and `loop_until: str | None`. The orchestrator's `run()` loop detects `stage.loop_stages` and runs the inner stages repeatedly until the `loop.until` verdict is returned or `loop.max` iterations are reached — reusing the existing revision-loop pattern already present for PM and Architect reviewers.

---

## 3. GUI Config Builder

Launched with `python main.py --config-builder`. Opens a local browser page.

### Interface

- **Left palette**: all available stage blocks, colour-coded by role
- **Canvas**: drag blocks into sequence; drag a `🔁 Loop` block to create a loop group, then drop stages inside it
- **Loop block controls**: numeric `max` input, `until` dropdown (APPROVED, CHANGES_REQUESTED)
- **Validation indicator**: live error display if sequence is invalid (e.g. unknown stage, empty loop)
- **Save button**: writes `pipeline.yaml` to the project root; shows success confirmation

### Technology

- Single-file HTML + vanilla JS served by a minimal Python HTTP server (no extra dependencies)
- Server endpoint `POST /save` writes `pipeline.yaml`
- On startup, the server calls `Orchestrator._make_stage_registry()` to build the live stage palette — new stages registered there appear in the GUI automatically with no extra steps
- On startup, if `pipeline.yaml` already exists, the builder loads and renders the current config so the user can edit in place

### Launch flow

```
python main.py --config-builder
→ starts HTTP server on random local port
→ prints: "Config builder ready at http://localhost:<PORT>"
→ opens browser automatically (webbrowser.open)
→ user edits and saves → pipeline.yaml written
→ Ctrl+C to exit builder
```

---

## 4. config.yaml Changes

`pipeline.mode` and `pipeline.stages` remain in `config.yaml` for backwards compatibility. A new comment is added noting that `pipeline.yaml` takes precedence:

```yaml
pipeline:
  # Stage execution mode: standard | tdd
  # Note: if pipeline.yaml exists in this directory, it takes full control
  # and this setting is ignored.
  mode: standard
```

No fields are removed. Existing configs with only `config.yaml` continue to work unchanged.

---

## 5. Error Handling

| Scenario | Behaviour |
|---|---|
| Unknown stage name in `pipeline.yaml` | `ValueError` at startup with clear message |
| Malformed YAML | `yaml.YAMLError` propagated with file path |
| Empty loop | `ValueError`: "loop block must contain at least one stage" |
| `pipeline.yaml` present but empty | `ValueError`: "pipeline.yaml must define a `stages` list" |
| Stage in `pipeline.yaml` not in registry | `ValueError` with list of valid names |

---

## 6. Testing

- Unit tests in `tests/test_pipeline_yaml.py`:
  - Valid flat list parses correctly
  - Valid loop block parses and expands correctly
  - Each validation error case raises expected `ValueError`
  - Falls back to `pipeline.mode` when `pipeline.yaml` absent
  - `pipeline.mode` is ignored (not raises) when `pipeline.yaml` present
- GUI builder: manual smoke test (no automated browser tests)

---

## 7. Files Affected

| File | Change |
|---|---|
| `orchestrator.py` | Add `_load_pipeline_yaml()`, extend `PipelineStage` with `loop_max`/`loop_until`, update `from_config()` and `run()` loop |
| `main.py` | Add `--config-builder` CLI flag; launch GUI server |
| `pipeline_builder/` | New directory: `server.py`, `index.html` (self-contained GUI) |
| `config.yaml` | Add comment about `pipeline.yaml` precedence |
| `tests/test_pipeline_yaml.py` | New test file |
| `docs/superpowers/specs/` | This document |

---

## Out of Scope

- Parallel stage execution (stages always run sequentially)
- Conditional branching (if/else blocks) — loops are the only control flow
- Nested loops
- Cloud/shared storage of pipeline configs
