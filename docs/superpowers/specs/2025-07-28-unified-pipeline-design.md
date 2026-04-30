# Unified Pipeline Architecture — Design Spec

**Date:** 2025-07-28  
**Status:** Approved  
**Scope:** Unify all pipeline entry points into one watcher-driven process, configurable by GitHub label

---

## Problem

The project currently has multiple hardwired pipeline entry points:

- `build_feature.py` — GitHub Actions entry for `ai-feature` label → `Orchestrator`
- `fix_issue.py` — GitHub Actions entry for `ai-fix` label → `BugFixOrchestrator`
- `doc_orchestrator.py` — Documentation pipeline class (manual only)
- `watcher.py` — Hourly poller that still hardcodes 3 pipeline type dispatches
- `main.py` — CLI for local dev (kept as-is)

Adding a new pipeline type requires a new Python file, a new GitHub Actions workflow, and a change to the watcher dispatch logic. There is no way to use the existing `pipeline.yaml` blocky format per label.

---

## Goals

1. One entry point (`watcher.py`) handles all GitHub label triggers
2. Each label maps to a pipeline YAML file (`pipelines/<label>.yaml`)
3. Per-repo parallel issue handling (`parallel_issues: N` in repos.yaml)
4. Per-LLM-backend connection pools prevent overloading Ollama or any rate-limited API
5. Adding a new pipeline = create a YAML file only (no new Python, no new workflow)
6. All changes are backwards-compatible; existing config works without modification

---

## Out of Scope

- Changes to individual agent logic or prompts
- Skills system (already implemented)
- MCP integration (already implemented)
- PR feedback watcher (separate process, unaffected)

---

## Architecture

### Section 1: Unified Orchestrator

**Files deleted:** `bug_fix_orchestrator.py`, `doc_orchestrator.py`

The logic from `BugFixOrchestrator` and `DocOrchestrator` is absorbed into `orchestrator.py` as named stages registered in the existing `_make_stage_registry()`. No new dispatch logic is needed; the stage registry already acts as the single source of truth for available stages.

**New directory:** `pipelines/`

Three built-in pipeline YAML files are created:

- `pipelines/ai-feature.yaml` — full PM → Architect → Engineer → Test → Review → QA sequence
- `pipelines/ai-fix.yaml` — minimal Engineer → Review sequence (bug-fix)
- `pipelines/ai-docs.yaml` — documentation generation sequence

**Pipeline selection priority (highest to lowest):**

1. `pipeline.yaml` at the project root (already implemented — the blocky custom pipeline)
2. `pipelines/<label>.yaml` in the ai-software-house repo
3. Built-in default (current hardcoded feature pipeline)

This means a target repo can still override the pipeline at the project level, and the watcher's `pipelines/` directory provides per-label defaults.

---

### Section 2: Watcher Redesign

#### repos.yaml — new `parallel_issues` field

```yaml
repos:
  - repo: owner/repo-A
    tracker_repo: owner/tracker-A
    parallel_issues: 2        # optional, default: 1
    labels:
      ai-feature:
        pipeline: ai-feature  # optional override; defaults to label name
      ai-fix: {}
  - repo: owner/repo-B
    tracker_repo: owner/tracker-B
    # parallel_issues omitted → defaults to 1 (sequential)
    labels:
      ai-feature: {}
```

The `pipeline` key within a label entry is optional. If omitted, the label name is used as the pipeline file name (e.g., label `ai-fix` → `pipelines/ai-fix.yaml`).

#### config.yaml — new `llm.pools` section

```yaml
llm:
  # ... existing settings unchanged ...
  pools:                        # optional, all keys optional
    ollama: 1                   # default: 1 (serial — safe for local Ollama)
    openai: 10
    opencode-zen: 5
    opencode-go: 5
    anthropic: 5
    # unlisted backends default to 5
```

#### watcher.py internals

A new `LLMPoolManager` class (extracted to `llm_pool.py`) holds one `threading.Semaphore` per backend, initialised from `config.yaml llm.pools`. Default: 1 for `ollama`, 5 for all others.

The watcher maintains one `ThreadPoolExecutor(max_workers=parallel_issues)` per repo. Each worker:

1. Dequeues an `(issue_number, label)` work item
2. Resolves the pipeline YAML path
3. Constructs an `Orchestrator` and calls `run()`
4. The `Orchestrator` (via `base_agent.py`) acquires/releases the correct LLM pool semaphore on each LLM call

With `parallel_issues=1` (default), all issues for a repo process sequentially. With `parallel_issues=2`, up to 2 run simultaneously — but if both are using Ollama and `pools.ollama=1`, only one LLM call happens at a time across both.

The watcher also gains a `--once` mode for GitHub Actions:

```
python watcher.py --once --repo owner/repo --issue 42 --label ai-feature
```

`--once` processes the specified issue and exits immediately (no polling loop).

---

### Section 3: GitHub Actions Workflows

**Files deleted:** `build_feature.py`, `fix_issue.py`

**Workflows updated:** `.github/workflows/feature-build.yml`, `.github/workflows/bug-fix.yml`

The run step in each workflow becomes:

```yaml
- name: Run pipeline
  run: |
    python watcher.py \
      --once \
      --repo ${{ github.repository }} \
      --issue ${{ github.event.issue.number }} \
      --label ${{ github.event.label.name }}
```

This is identical for all label workflows. A new label only needs a new `pipelines/<label>.yaml` file — no new workflow required.

---

### Section 4: main.py CLI

`main.py` stays as the local development entry point. New optional flags:

```
python main.py "Build a todo app"                    # uses pipelines/ai-feature.yaml or built-in
python main.py "Fix the login bug" --pipeline ai-fix  # uses pipelines/ai-fix.yaml
python main.py --list-pipelines                       # lists all available pipeline YAML files
```

The `--pipeline` flag is optional. If omitted, `main.py` uses the same pipeline selection priority as the watcher.

---

## New Files

| File | Purpose |
|---|---|
| `llm_pool.py` | `LLMPoolManager` — semaphore per backend, acquired by `base_agent.py` |
| `pipelines/ai-feature.yaml` | Built-in feature pipeline (PM → Arch → Eng → Test → Review → QA) |
| `pipelines/ai-fix.yaml` | Built-in bug-fix pipeline (Eng → Review) |
| `pipelines/ai-docs.yaml` | Built-in docs pipeline |
| `tests/test_watcher_queues.py` | Tests for per-repo queues and `--once` mode |
| `tests/test_llm_pool.py` | Tests for LLMPoolManager semaphore behaviour |

## Modified Files

| File | Change |
|---|---|
| `orchestrator.py` | Absorb BugFix+Doc stages; add pipeline file loading priority logic |
| `watcher.py` | Per-repo `ThreadPoolExecutor`; `--once` mode; pipeline YAML dispatch |
| `base_agent.py` | Acquire/release LLM pool semaphore around each LLM call |
| `repos.yaml` | Add `parallel_issues` field (optional) |
| `config.yaml` | Add `llm.pools` section (optional) |
| `main.py` | Add `--pipeline` and `--list-pipelines` flags |
| `.github/workflows/feature-build.yml` | Use `watcher.py --once` |
| `.github/workflows/bug-fix.yml` | Use `watcher.py --once` |

## Deleted Files

| File | Reason |
|---|---|
| `bug_fix_orchestrator.py` | Logic absorbed into `orchestrator.py` |
| `doc_orchestrator.py` | Logic absorbed into `orchestrator.py` |
| `build_feature.py` | Replaced by `watcher.py --once` |
| `fix_issue.py` | Replaced by `watcher.py --once` |

---

## Backwards Compatibility

- All new `repos.yaml` and `config.yaml` fields are optional with safe defaults
- `parallel_issues` defaults to `1` (sequential — same as today)
- `llm.pools` entries default to `5` (or `1` for `ollama`)
- Existing `pipeline.yaml` at project root continues to take highest priority
- `main.py` without `--pipeline` flag behaves identically to today

---

## Testing Strategy

Each step in the incremental implementation plan has tests that run before moving to the next step. The 52 existing tests must pass throughout.

| Step | New Tests |
|---|---|
| 1: Merge orchestrators | BugFix+Doc stages available in `_make_stage_registry()` |
| 2: Pipeline YAML loading | Load `ai-feature.yaml`, fallback to built-in when no file |
| 3: Watcher queues + pools | `parallel_issues=2` runs concurrently; LLM pool blocks at limit |
| 4: Actions + `--once` | Watcher `--once` processes 1 issue and exits |

---

## Implementation Order (Incremental Plan)

1. Merge `BugFixOrchestrator` + `DocOrchestrator` into `orchestrator.py`
2. Add `pipelines/` YAML loading and three built-in pipeline files
3. Refactor `watcher.py`: per-repo queues, `--once` mode, LLM pool integration
4. Update GitHub Actions workflows, delete `build_feature.py` + `fix_issue.py`
5. Update `main.py` CLI flags
