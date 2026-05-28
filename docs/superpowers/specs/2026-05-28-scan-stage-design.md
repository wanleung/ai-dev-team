# Scan Stage — Design Spec

**Date:** 2026-05-28  
**Status:** Approved

---

## Overview

Add a `scan` pipeline stage that explicitly fetches the target repo's file tree and indexes it into RAG at the start of a pipeline run. This makes codebase context available to all subsequent agents from the first stage, rather than relying on the implicit RAG index that currently runs just before the engineer stage.

---

## Goals

- Give agents accurate file-tree context from the very first stage (PM, architect, etc.)
- Trigger RAG indexing once, early, so search-codebase calls work throughout the pipeline
- Make scan behaviour explicit and configurable per pipeline YAML
- No breaking changes to pipelines that don't include `scan`

---

## Stage Behaviour

### Stage name: `scan`

When invoked, the stage performs two actions in order:

1. **File tree build** — calls `RepoContextLoader.build(self.target_github)` and stores the result on `result.repo_context`. Always runs when `target_github` is set. No-op if `target_github` is `None`.

2. **RAG index** — calls `self.repo_auto_indexer.index(...)` to push the repo into the RAG MCP codebase collection. Only runs when `self.repo_auto_indexer` is configured. Silently skipped if RAG is not configured — no warning, no pipeline failure.

After both steps, `"rag_index"` is added to `result.completed_stages`. The existing implicit RAG index in `Orchestrator.run()` checks for this flag before re-running, so it becomes a fallback for pipelines that omit `scan`.

### Graceful degradation

| Condition | Behaviour |
|---|---|
| `target_github` is None | Both steps skipped silently |
| RAG not configured | Step 2 skipped; step 1 still runs |
| RAG configured, index fails | Error logged; pipeline continues |

---

## Changes Required

### `orchestrator.py`

1. **`PipelineResult`** — add `repo_context: RepoContext | None = None` field so downstream agents can read the pre-fetched tree without re-fetching.

2. **`_stage_scan`** — new method:
   ```python
   def _stage_scan(self, result: PipelineResult) -> None:
       """Fetch repo file tree and optionally index into RAG."""
       if self.target_github:
           result.repo_context = self._repo_context_loader.build(self.target_github)
       if self.repo_auto_indexer and self.target_github:
           self.repo_auto_indexer.index(
               repo=self.target_github.repo,
               github_token=self._github_token or "",
           )
           result.add_completed_stage("rag_index")
   ```

3. **`_make_stage_registry`** — register `scan` stage:
   ```python
   stages["scan"] = PipelineStage(
       name="scan",
       label="🔍 Scan",
       description="Fetching repo file tree and indexing into RAG...",
       checkpoint_key="scan",
       fn=lambda r: self._stage_scan(r),
   )
   ```

### Pipeline YAML files

Add `scan` as the first stage in all code-touching pipelines:

- `pipelines/ai-feature.yaml`
- `pipelines/tdd.yaml`
- `pipelines/ai-fix.yaml`
- `pipelines/ai-smart-fix.yaml`

Pipelines that do not touch code (`ai-docs`, `bootstrap-patterns`, `news-article`, `pr-campaign`, `pr-social-post`) are **not** changed.

---

## `PipelineResult.repo_context` usage

Agents that currently call `RepoContextLoader.build()` themselves (or receive `repo_context` via constructor) can be updated to read from `result.repo_context` instead, avoiding duplicate API calls. This is an optional follow-on; the scan stage is useful without it.

---

## What Is Not Changed

- The implicit RAG index in `Orchestrator.run()` (lines ~3677–3684) is kept as a fallback. It checks `"rag_index" not in result.completed_stages` before running.
- `_stage_repo_index` is kept unchanged — it is still used by the implicit fallback path.
- No agent prompt logic is changed.

---

## Testing

- Unit test: `_stage_scan` calls `RepoContextLoader.build` and stores result on `result.repo_context`
- Unit test: `_stage_scan` calls `repo_auto_indexer.index` when RAG is configured
- Unit test: `_stage_scan` skips RAG silently when `repo_auto_indexer` is None
- Unit test: `_stage_scan` skips entirely when `target_github` is None
- Unit test: `"rag_index"` added to `completed_stages` after RAG index runs
- Unit test: implicit RAG index fallback does NOT re-run when `"rag_index"` already in `completed_stages`
- Integration: `scan` appears in `_make_stage_registry()` output
