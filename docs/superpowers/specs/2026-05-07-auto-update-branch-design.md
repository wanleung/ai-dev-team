# Auto-Update Branch Design

**Date:** 2026-05-07  
**Status:** Approved

## Problem

When `run_revision()` runs on an outdated PR (branch behind `master`), the engineer has no visibility of changes on `master` that may conflict with or supersede the PR. This can cause the fix to be applied on stale code, or create merge conflicts when the user eventually tries to merge.

## Goal

Allow `run_revision()` to automatically merge `master` into the PR branch before running the fix, with AI-assisted conflict resolution and a human fallback.

---

## Configuration

Opt-in per repo in `repos-enabled/*.yaml`:

```yaml
update_branch: true   # enables auto-update-branch feature for this repo
```

Default: `false` (feature disabled unless explicitly opted in).

---

## Trigger

The branch update runs at the **start** of `run_revision()` (before feedback collection) when **both** conditions are met:

1. `update_branch: true` in the repo's YAML config
2. A PR comment contains the directive `update-branch` (case-insensitive)

Supported comment formats:
```
update-branch
update-branch: true
```

If only the config is set but no comment directive is present, the feature does not activate. This prevents accidental updates on every `ai-fix` run.

---

## Core Flow

```
run_revision(pr_number)
  └─ (new) step 0: detect "update-branch" directive in PR issue comments
  └─ if directive found AND self._update_branch_enabled:
       └─ _update_branch_from_base(head_branch, base_branch="master")
            ├─ call target_github.merge_base_into_branch(base="master", head=head_branch)
            ├─ 204 (no-op)  → log "already up to date", continue
            ├─ 201 (merged) → log "merged cleanly", continue
            └─ 409 (conflict) → conflict resolution path (see below)
  └─ (existing) step 1: collect feedback
  └─ ... (rest of run_revision unchanged)
```

---

## Conflict Resolution Path

When `merge_base_into_branch()` returns 409:

1. **Find conflicting files:** Intersect files changed in the PR (`get_pr_files()`) with files modified on `master` since the branch diverged (compare branch base SHA tree vs master tree using `get_full_tree(ref=branch)` and `get_full_tree(ref="master")`).

2. **Fetch both versions:** For each conflicting file, fetch:
   - PR branch version: `get_file_content(path, ref=head_branch)`
   - Master version: `get_file_content(path, ref="master")`

3. **AI resolves each file:** Prompt the thinker/engineer LLM with:
   ```
   File: <path>

   === Version on PR branch (<head_branch>) ===
   <content>

   === Version on master ===
   <content>

   Produce a single merged version that preserves both sets of changes.
   Output ONLY the file content, no explanation.
   ```

4. **Commit resolved files** to the PR branch using `commit_file()`.

5. **Retry merge:** Call `merge_base_into_branch()` again.
   - 201/204 → continue with `run_revision()`
   - 409 again or any exception → **fallback**

6. **Fallback:** Post a PR comment:
   ```
   ⚠️ Could not automatically resolve merge conflicts.
   
   Conflicting files:
   - `app/main.py`
   - `src/utils.py`
   
   Please resolve these conflicts manually and re-trigger ai-fix.
   ```
   Return `{"status": "conflict", "conflicting_files": [...]}` and abort `run_revision()`.

---

## New Components

### `github_client.py` — `merge_base_into_branch()`

```python
def merge_base_into_branch(self, base_branch: str, head_branch: str, commit_message: str = "") -> int:
    """Merge base_branch INTO head_branch via GitHub API.

    Returns:
        201 — merge commit created
        204 — already up to date (no action needed)
        409 — merge conflict (caller must resolve)
    """
```

Uses `POST /repos/{owner}/{repo}/merges` with `{"base": head_branch, "head": base_branch}`.

### `orchestrator.py` — `_parse_update_directive(feedback)`

```python
def _parse_update_directive(self, feedback: list[dict]) -> bool:
    """Return True if any feedback item contains an 'update-branch' directive."""
```

Separate from `_parse_merge_directives` — different concern.

### `orchestrator.py` — `_update_branch_from_base(head_branch, base_branch)`

```python
def _update_branch_from_base(self, head_branch: str, base_branch: str = "master") -> dict:
    """Merge base_branch into head_branch. Returns status dict."""
```

Encapsulates the full merge → conflict detect → AI resolve → retry → fallback flow.

### `watcher.py`

Read `update_branch` from repo config dict, pass as `update_branch_enabled=True/False` to `Orchestrator.__init__()`.

### `orchestrator.py — run_revision()` wiring

New step 0 added before existing step 1 (feedback collection):

```python
# ── 0. Update branch from base if requested ───────────────────────────────
pr_comments = self.target_github.get_issue_comments(pr_number)
if self._update_branch_enabled and self._parse_update_directive(
    [{"body": c.get("body", ""), "author": c.get("user", {}).get("login", "")} for c in pr_comments]
):
    update_result = self._update_branch_from_base(head_branch)
    if update_result["status"] == "conflict":
        return update_result
```

---

## Config Propagation

```
repos-enabled/repo.yaml
  update_branch: true
    ↓
watcher.py _run_pr_revision()
  passes update_branch_enabled=True to Orchestrator(...)
    ↓
Orchestrator.__init__()
  self._update_branch_enabled = update_branch_enabled
    ↓
run_revision()
  checks self._update_branch_enabled
```

`Orchestrator.__init__()` gains a new optional kwarg `update_branch_enabled: bool = False`.

---

## Files Changed

| File | Change |
|------|--------|
| `github_client.py` | Add `merge_base_into_branch(base_branch, head_branch)` |
| `orchestrator.py` | Add `_parse_update_directive()`, `_update_branch_from_base()`; update `__init__()` and `run_revision()` |
| `watcher.py` | Read `update_branch` from config, pass to `Orchestrator` |
| `tests/test_revision.py` | Tests for directive parsing, clean merge, up-to-date, AI conflict resolution, conflict fallback |

---

## Test Cases

| Test | Description |
|------|-------------|
| `test_parse_update_directive_detects_update_branch` | `update-branch` in comment → returns `True` |
| `test_parse_update_directive_no_match` | No directive → returns `False` |
| `test_update_branch_already_up_to_date` | merge returns 204 → status `up_to_date` |
| `test_update_branch_clean_merge` | merge returns 201 → status `merged` |
| `test_update_branch_conflict_ai_resolves` | 409 → AI resolves → retry 201 → status `merged` |
| `test_update_branch_conflict_fallback` | 409 → AI resolves → retry still 409 → posts PR comment, returns `conflict` |
| `test_run_revision_skips_update_when_disabled` | `update_branch_enabled=False` → `merge_base_into_branch` never called |
| `test_run_revision_skips_update_when_no_directive` | Enabled but no comment → `merge_base_into_branch` never called |
| `test_run_revision_aborts_on_conflict` | Update returns conflict → `run_revision` returns conflict status |

---

## Non-Goals

- Rebase strategy (out of scope — merge commit chosen for simplicity and history preservation)
- Auto-triggering without a PR comment (requires explicit `update-branch` comment)
- Updating branches on repos where `update_branch` is not set in config
