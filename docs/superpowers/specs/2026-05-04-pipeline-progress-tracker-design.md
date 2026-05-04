# Pipeline Progress Tracker — Design Spec

**Date:** 2026-05-04  
**Status:** Approved

---

## Problem

When the pipeline runs, GitHub issues only show output comments from individual agents (design, review, etc.). There is no structured, live view of which stages have completed, which are running, and which are pending. Users and agents cannot tell the overall pipeline state at a glance.

---

## Goal

Post a progress tracker comment to the GitHub issue when the pipeline starts. Update it as stages complete, fail, or are skipped. Two modes: **summary** (one evolving comment) and **verbose** (per-stage individual comments), controlled by config.

---

## Architecture

### New class: `ProgressTracker`

Location: `orchestrator.py` (inline class, before `Orchestrator`).

Responsibilities:
- Maintains an ordered list of `ProgressStage(key, label, status)` entries
- In **summary** mode: deletes the previous progress comment and re-posts a fresh one on every state change
- In **verbose** mode: posts individual "🔄 Starting…" and "✅ Done / ❌ Failed" comments per stage
- In **off** mode: all methods are no-ops

```python
@dataclass
class ProgressStage:
    key: str        # checkpoint key, e.g. "pm", "architect_reviewer"
    label: str      # display label with emoji, e.g. "📋 Product Manager"
    status: str = "pending"   # pending | in_progress | done | failed | skipped
```

**Public API:**
```python
class ProgressTracker:
    def __init__(self, github, issue_number: int, mode: str): ...
    def set_stages(self, stages: list[ProgressStage]): ...          # call once at start
    def add_stage(self, stage: ProgressStage): ...                   # for dynamic revision rounds
    def restore(self, comment_id: int): ...                          # on checkpoint resume
    def mark_in_progress(self, key: str): ...
    def mark_done(self, key: str): ...
    def mark_failed(self, key: str, error: str = ""): ...
    def mark_skipped(self, key: str): ...
```

**Status rendering (summary mode):**
```
## 🤖 Pipeline Progress

- ✅ 📋 Product Manager
- ✅ 🔎 PM Reviewer
- 🔄 🏗️ Architect  ← in progress
- ⬜ 🔎 Architect Reviewer
- ⬜ 👷 Engineer
- ⬜ 🔍 Code Reviewer
- ⬜ 🧪 QA Planner
- ⬜ 🧪 QA Engineer
```

Status icons:
- `⬜` pending
- `🔄` in progress
- `✅` done
- `❌` failed — includes short error message on same line
- `⏭️` skipped (checkpoint resume or condition skip)

**Delete-and-repost logic (summary mode):**
```python
def _post(self):
    if self.comment_id:
        self.github.delete_issue_comment(self.comment_id)
    resp = self.github.add_issue_comment(self.issue_number, self._render())
    self.comment_id = resp["id"]
```

---

### `GitHubClient` additions

Add one new method:
```python
def delete_issue_comment(self, comment_id: int) -> None:
    """DELETE /repos/{owner}/{repo}/issues/comments/{comment_id}"""
    self._request("DELETE", f"/issues/comments/{comment_id}")
```

The existing `_request()` retry logic covers transient 5xx errors. A 404 (comment already deleted) is treated as success (no-op).

---

### `PipelineResult` additions

```python
progress_comment_id: Optional[int] = None
```

- Serialised in `to_dict()` / `from_dict()` so checkpoint resume re-uses the existing comment slot
- On resume: `tracker.restore(result.progress_comment_id)` before first stage hook

---

### `Orchestrator` changes

**Config loading (`from_config`):**
```python
self.progress_tracker_mode = cfg.get("pipeline", {}).get("progress_tracker", "summary")
```

**`run()` method:**
1. After `result` is created/loaded, build the expected stage list (`_expected_stages(result)`)
2. Instantiate `self._tracker = ProgressTracker(self.github, result.issue_number, self.progress_tracker_mode)`
3. Call `tracker.set_stages(expected_stages)`
4. If resuming from checkpoint: `tracker.restore(result.progress_comment_id)` then replay `completed_stages` as done/skipped
5. Store `tracker.comment_id` back to `result.progress_comment_id` after each post

**`_expected_stages(result)` helper:**
Returns an ordered list of `ProgressStage` for the current pipeline config:
- Standard pipeline: PM, PM Reviewer, Architect, Architect Reviewer, then `_build_stage_list()` entries
- YAML pipeline: just `_build_stage_list()` entries
- Revision stages (`prd_revision_1`, `design_revision_1`, …) are NOT included upfront — added dynamically via `add_stage()` when they actually begin

**Hook points:**

All existing stage completions already call `result.completed_stages.append(key)` and `_save_checkpoint()`. Tracker calls are added immediately before/after:

| Location | Call |
|---|---|
| Before `_run_stage(…)` | `tracker.mark_in_progress(key)` |
| After successful stage + `completed_stages.append` | `tracker.mark_done(key)` |
| After `result.errors` check (stage failed) | `tracker.mark_failed(key)` |
| On checkpoint-skip console print | `tracker.mark_skipped(key)` |
| Before a revision loop round | `tracker.add_stage(...)` then `tracker.mark_in_progress(key)` |

---

### Config

**`config.yaml`** (add under `pipeline:`):
```yaml
pipeline:
  progress_tracker: summary   # summary | verbose | off
```

**`config.local.yaml`** (same addition).

---

## Error Handling

- If the initial progress comment post fails (GitHub unavailable), log a warning and continue without a tracker — pipeline must not abort due to a cosmetic feature
- If a delete-and-repost fails, log warning and store the new comment ID anyway; old comment orphaned but harmless
- 404 on delete is treated as success

---

## Non-goals (out of scope)

- Editing comments in-place (GitHub edit API) — chosen approach is delete-and-repost
- Showing time elapsed per stage
- Progress tracker in non-GitHub (no-github) mode — tracker is a no-op when `self.github` is None or `issue_number` is None

---

## Files changed

| File | Change |
|---|---|
| `orchestrator.py` | New `ProgressStage` dataclass, `ProgressTracker` class; `PipelineResult` field; `_expected_stages()`; hooks in `run()`, `_prd_revision_loop()`, `_design_revision_loop()`, mode-driven loop |
| `github_client.py` | `delete_issue_comment()` method |
| `config.yaml` | `pipeline.progress_tracker` key |
| `config.local.yaml` | Same |
