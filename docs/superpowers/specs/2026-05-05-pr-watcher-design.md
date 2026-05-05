# PR Watcher — Design Spec

**Date:** 2026-05-05  
**Status:** Approved

---

## Problem

The watcher only processes GitHub Issues. When a pipeline creates a PR and that PR has failing tests or review problems (detected via label or comment pattern), the watcher ignores it. A human must manually move labels around to re-trigger the fix pipeline.

## Goal

Allow the watcher to monitor open PRs, detect failures, and automatically invoke `run_revision()` to push fixes — with a configurable retry cap.

---

## Approach

Add a `_watch_prs()` function to `watcher.py` that runs in the same `watch()` cycle as issue watching. For each enabled repo that opts in, it:

1. Fetches open PRs
2. Detects failures (label OR comment pattern)
3. Dispatches `orchestrator.run_revision(pr_number)` (already exists)
4. Tracks retry count via `ai-pr-fix-N` labels
5. Labels the PR `agent-complete` or `agent-failed` based on outcome

---

## Detection Triggers

Both triggers are configurable per repo (or globally). Either one is sufficient to trigger a fix run.

### Label trigger
If the PR has a label matching `pr_fix_label` (e.g. `ai-fix`), the watcher treats it as a fix request. The pipeline can add this label automatically via chaining config when tests fail.

### Comment pattern trigger
If any PR comment body matches the configured `pr_failure_pattern` regex, the watcher flags the PR for fixing. Default pattern covers common failure indicators:

```
❌|FAILED|tests? failed|test suite failed
```

The watcher scans only comments posted after the last `ai-pr-fix-N` label was applied (to avoid re-triggering on old failure comments after a fix has been pushed).

---

## Skip Conditions

A PR is skipped if it:
- Already has `agent-running` label (fix in progress)
- Already has `agent-failed` label (gave up)
- Has reached the `max_pr_retries` count (determined by counting `ai-pr-fix-N` labels present)
- Is a draft PR (unless `watch_draft_prs: true` is set)

---

## Retry Tracking

Each fix attempt adds a label `ai-pr-fix-1`, `ai-pr-fix-2`, etc. to the PR. The current attempt number is `max(N)` across all `ai-pr-fix-N` labels present.

When the attempt count equals `max_pr_retries`:
- Add `agent-failed` label
- Post a comment: "Max fix attempts (N) reached. Human review required."
- Do not run `run_revision()` again.

Resetting: a human can remove all `ai-pr-fix-N` labels and `agent-failed` to allow retrying.

---

## Execution

On detection, the watcher:

1. Adds `agent-running` label to the PR
2. Increments the attempt counter (adds `ai-pr-fix-N` label)
3. Calls `orchestrator.run_revision(pr_number)` — this already:
   - Reads PR branch, diff, and review comments
   - Runs engineer → code reviewer → QA agents
   - Pushes fix commits to the PR branch
   - Posts a summary comment on the PR
4. On success: removes `agent-running`, removes trigger label (`pr_fix_label`), adds `agent-complete`
5. On failure (exception or `run_revision` returns `agent-failed` status): removes `agent-running`, adds `agent-failed`, posts error comment

---

## Configuration

### Global default (in `config.yaml` under `pipeline:`)

```yaml
pipeline:
  watch_prs: false                          # disabled by default
  pr_fix_label: "ai-fix"                   # label on PR that triggers a fix run
  pr_failure_pattern: "❌|FAILED|tests? failed|test suite failed"  # regex
  max_pr_retries: 3
  watch_draft_prs: false
```

### Per-repo override (in `repos-available/<repo>.yaml` under `settings:`)

```yaml
settings:
  watch_prs: true
  pr_fix_label: "ai-fix"
  pr_failure_pattern: "❌|FAILED"
  max_pr_retries: 3
  watch_draft_prs: false
```

Per-repo `settings:` override global defaults (same `_settings` merge mechanism already used for `model` and `num_engineers`).

---

## Changes to `watcher.py`

| Function | Change |
|---|---|
| `watch()` | Call `_watch_prs()` after `_watch_issues()` each cycle |
| `_watch_prs()` | New function: scan PRs, detect triggers, dispatch fix |
| `_should_fix_pr()` | New helper: check labels + comment pattern, return bool |
| `_pr_attempt_count()` | New helper: count `ai-pr-fix-N` labels on a PR |
| `get_open_prs()` | New GitHub API helper (mirrors `get_open_issues()`) |
| `get_pr_comments()` | New GitHub API helper (or reuse existing in `github_client.py`) |

No changes to `orchestrator.py` — `run_revision()` is used as-is.

---

## Testing

- `test_watch_prs_label_trigger` — PR with `ai-fix` label → `run_revision` called
- `test_watch_prs_comment_trigger` — PR with matching comment → `run_revision` called
- `test_watch_prs_skip_running` — PR with `agent-running` → skipped
- `test_watch_prs_skip_failed` — PR with `agent-failed` → skipped
- `test_watch_prs_max_retries` — PR at `max_pr_retries` → `agent-failed` added, no run
- `test_watch_prs_disabled` — `watch_prs: false` → no PRs scanned
- `test_watch_prs_comment_after_fix` — old failure comment before last fix → not re-triggered
- `test_pr_attempt_count` — label counting helper
- `test_watch_prs_draft_skipped` — draft PR skipped unless `watch_draft_prs: true`

---

## Out of Scope

- GitHub Actions CI status integration (webhook/event-based triggers)
- Watching PRs across repos not listed in `repos-available/`
- Auto-merging PRs after a successful fix
