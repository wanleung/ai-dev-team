# Senior / Junior Engineer Tier System — Design Spec

**Date:** 2026-04-25  
**Project:** ai-software-house / ai-dev-team  
**Status:** Approved

---

## Problem

All engineer agents currently use the same model and run with equal concurrency regardless of module complexity. This is wasteful: simple utility modules (models, schemas, configs) do not need an expensive model, and complex integration modules need more context and reasoning power than a cheap model provides.

---

## Goal

Split the engineer stage into two tiers — **junior** and **senior** — so that:
- Simple, isolated modules use a fast/cheap model with high concurrency.
- Complex, integration-heavy modules use an expensive model with lower concurrency.
- Cost and wall-clock time are both reduced for large projects.
- Code quality is maintained through tier-specific quality gates.

---

## Module Classification

### 1. Architect assigns tier

The `ArchitectAgent` adds a `tier` field (`"junior"` or `"senior"`) to each module in its design output. The architect prompt instructs it to classify modules as:

- **`junior`**: Self-contained modules with no dependency on other modules being built in this run. Examples: database models, Pydantic schemas, utility functions, constants, config loaders, migrations.
- **`senior`**: Modules that integrate, orchestrate, or build on top of other modules. Examples: service layers, API route handlers, feature controllers, authentication flows, background task orchestration.

Module dict schema (extended):

```json
{
  "name": "app/users",
  "description": "User model, schema, CRUD operations",
  "tier": "junior"
}
```

### 2. TierReviewerAgent validates assignments

A new lightweight agent (`TierReviewerAgent`) runs immediately after the architect, using a fast/cheap model. It receives the full module list with tier assignments and may re-classify any module. Its output is a revised module list. This is a single LLM call — not a loop.

### 3. Config override rules (highest priority)

`config.yaml` supports pattern-based overrides that take precedence over both the architect and the tier reviewer:

```yaml
team:
  tier_override_rules:
    - pattern: "*/models*"
      tier: junior
    - pattern: "*/schemas*"
      tier: junior
    - pattern: "*/utils*"
      tier: junior
    - pattern: "*/core*"
      tier: senior
    - pattern: "*/service*"
      tier: senior
```

Patterns use glob-style matching against the module name. First matching rule wins.

---

## Execution Flow

```
Stage 3a: Classify modules
  → Architect assigns tier per module
  → TierReviewerAgent validates / corrects
  → Config override rules applied (highest priority)
  → Modules split into junior_modules[] and senior_modules[]

Stage 3b: Junior batch (parallel, num_junior_engineers workers)
  → Each junior module implemented by JuniorEngineerAgent (junior_model)
  → If junior_quality_gate: true:
      → Unit tests run per module immediately after implementation
      → On failure: retry up to junior_test_retries times
      → On still-failing after retries: escalate module to senior batch
  → Result: junior_files dict (filepath → content)

Stage 3c: Senior batch (parallel, num_senior_engineers workers)
  → junior_files injected as shared context into every senior prompt
  → Each senior module implemented by SeniorEngineerAgent (senior_model)
  → Result: senior_files dict (filepath → content)

Stage 4+: Existing pipeline continues unchanged
  → Code reviewer runs on all_files (junior + senior merged)
  → QA planner, QA engineer, test runner (existing retry loop)
  → Deployment tester
  → PR / commit
```

---

## New Agents

### `JuniorEngineerAgent`

- Subclass of `EngineerAgent`; inherits `run_module`, `run_all_modules`, `run_with_github`
- No additional logic beyond model selection
- `role_name = "junior_engineer"`

### `SeniorEngineerAgent`

- Subclass of `EngineerAgent`; inherits all methods
- `run_module` prompt is extended with a **Junior Code Context** section containing all `junior_files`
- `role_name = "senior_engineer"`

### `TierReviewerAgent`

- New lightweight agent (`agents/tier_reviewer.py`)
- Single `run(modules: list[dict]) -> list[dict]` method
- Returns revised module list with corrected `tier` fields
- Uses fast/cheap model (configurable as `tier_reviewer_model`, defaults to `junior_model`)

---

## Configuration (`config.yaml`)

```yaml
team:
  # Tier models
  senior_model: gpt-4.1            # expensive model for senior engineers
  junior_model: gpt-4.1-mini       # fast model for junior engineers
  tier_reviewer_model: ~           # defaults to junior_model if null

  # Concurrency
  num_senior_engineers: 2          # parallel workers for senior tier
  num_junior_engineers: 5          # parallel workers for junior tier

  # Junior quality gate
  junior_quality_gate: true        # enable per-module test+retry for junior
  junior_test_retries: 3           # retries before escalating to senior

  # Override rules (highest priority, applied after architect + tier reviewer)
  tier_override_rules:
    - pattern: "*/models*"
      tier: junior
    - pattern: "*/utils*"
      tier: junior
```

**Backward compatibility:** If `senior_model`/`junior_model` are absent, both tiers fall back to the existing `model` field. If `num_senior_engineers`/`num_junior_engineers` are absent, both fall back to `num_engineers`.

---

## CLI Flags

| Flag | Description |
|------|-------------|
| `--junior-engineers N` | Override `num_junior_engineers` |
| `--senior-engineers N` | Override `num_senior_engineers` |
| `--engineers N` | Fallback shorthand: sets both (junior=N×2, senior=N, rounded) |

When `--junior-engineers` or `--senior-engineers` are provided, they take precedence over `--engineers`.

---

## Checkpoint Changes

`PipelineResult` gains new fields:

```python
junior_files: dict[str, str]        # files produced by junior batch
tier_classifications: list[dict]    # module list with final tier assignments
completed_stages: [
    ...,
    "tier_review",      # new
    "junior_engineer",  # new (replaces "engineer" split)
    "senior_engineer",  # new
    ...
]
```

The existing `"engineer"` completed_stage key is **kept as an alias** for backward compatibility (old checkpoints resume correctly — they skip the entire engineer stage).

---

## Quality Gates Summary

| Tier | Quality Gate |
|------|-------------|
| Junior | Per-module unit tests; retry up to `junior_test_retries`; escalate to senior on persistent failure |
| Senior | Existing full test runner (pytest/etc.) + existing retry loop (`max_test_retries`) |
| All | Existing code reviewer + deployment tester + PR flow |

---

## What Is Not Changing

- Architect, PM, PM Reviewer, Architect Reviewer stages — unchanged
- Code Reviewer stage — unchanged (reviews all files merged)
- QA Planner, QA Engineer, Test Runner, Deployment Tester — unchanged
- GitHub branch/PR flow — unchanged
- RAG / tool registry injection — both tiers support it

---

## Out of Scope

- Dynamic re-classification mid-run (if a module turns out more complex than expected)
- Cross-tier dependency graph (seniors waiting on specific junior modules, not the full batch)
- Per-module reviewer agents (only per-tier quality gates)
