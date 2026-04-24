# PRD & Design Revision Loops — Design Spec

**Goal:** Add iterative back-and-forth revision loops to the PM→PM Reviewer and Architect→Architect Reviewer stages, so the original author improves their work based on reviewer feedback instead of the reviewer self-patching.

**Architecture:** Replace the single-shot review stage blocks with `_prd_revision_loop()` and `_design_revision_loop()` methods in the orchestrator. Each method runs a PM/Architect → Reviewer → rewrite cycle up to a configurable limit. The original agents gain a `run_revision()` method that takes the reviewer's feedback and suggested draft. Reviewer agents are unchanged.

**Tech Stack:** Python, existing `ProductManagerAgent`, `ArchitectAgent`, `PMReviewerAgent`, `ArchitectReviewerAgent`, `Orchestrator`, `PipelineResult`, `config.yaml`.

---

## Loop Flow

```
PM writes PRD (round 0)
    ↓
PM Reviewer reviews → returns: feedback + draft suggested PRD
    ├─ APPROVED / APPROVED WITH SUGGESTIONS
    │       → continue to Architect stage
    └─ NEEDS REVISION  AND  round < max_prd_revisions
    │       PM.run_revision(original_prd, review, draft_revision, requirement)
    │       → PM rewrites PRD incorporating feedback + draft
    │       → checkpoint "prd_revision_{round}"
    │       → return to PM Reviewer
    └─ NEEDS REVISION  AND  round == max_prd_revisions
            log warning + post GitHub comment (if github enabled)
            if stop_on_prd_issues: halt pipeline
            else: continue with current best PRD

[Identical loop for Architect / Architect Reviewer]
```

### Checkpoint keys written per round

| Round | Key written |
|---|---|
| 0 (initial review) | `pm_reviewer` (existing) |
| 1 (first revision + re-review) | `prd_revision_1` |
| 2 (second revision + re-review) | `prd_revision_2` |
| 3 (third revision + re-review) | `prd_revision_3` |
| loop complete | `pm_review_loop` |

- Parallel keys for design: `design_revision_1`, `design_revision_2`, `design_revision_3`, `architect_review_loop`
- Resume logic: loop method checks for presence of `pm_review_loop` (skip entire loop) or `prd_revision_N` (skip that round)

---

## New Agent Methods

### `ProductManagerAgent.run_revision()`

```python
def run_revision(
    self,
    original_prd: str,
    review: str,
    draft_revision: str,
    requirement: str,
    project_name: str,
) -> dict:
    """
    Rewrite the PRD incorporating the reviewer's feedback and draft suggestion.
    Returns same shape as run(): {"prd": str, "project_name": str}
    """
```

**Prompt structure:**
```
You previously wrote a PRD that was reviewed and needs improvement.

## Original PRD
{original_prd}

## Reviewer Feedback
{review}

## Reviewer's Suggested Draft (use as direction, not copy-paste)
{draft_revision}

Rewrite the PRD addressing the reviewer's concerns. Maintain all requirements
that were already correct. Output a complete, improved PRD.
```

### `ArchitectAgent.run_revision()`

```python
def run_revision(
    self,
    original_design: str,
    review: str,
    draft_revision: str,
    prd: str,
    project_name: str,
) -> dict:
    """
    Rewrite the system design incorporating reviewer feedback and draft.
    Returns same shape as run(): {"design": str, "modules": list[str]}
    """
```

---

## Orchestrator Changes

### New `PipelineResult` fields

```python
prd_revision_count: int = 0       # how many revision rounds ran for PRD
design_revision_count: int = 0    # how many revision rounds ran for design
prd_reviewer_draft: str = ""      # reviewer's suggested PRD rewrite (passed to PM.run_revision)
design_reviewer_draft: str = ""   # reviewer's suggested design rewrite (passed to Architect.run_revision)
```

Also serialised to/from `checkpoint.json`.

### `_prd_revision_loop(result, requirement)`

Replaces the separate `pm` + `pm_reviewer` stage blocks in `run()`.

```python
def _prd_revision_loop(self, result: PipelineResult, requirement: str) -> bool:
    """
    Run PM → PM Reviewer revision loop.
    Returns True if loop completed normally, False if pipeline should halt.
    """
    # Step 1: run PM if not already done
    if "pm" not in result.completed_stages:
        ...  # existing _stage_pm logic

    # Step 2: initial review if not done
    if "pm_reviewer" not in result.completed_stages:
        ...  # existing _stage_pm_reviewer logic
        result.completed_stages.append("pm_reviewer")
        self._save_checkpoint(result)

    # Step 3: revision loop
    for round_num in range(1, self.max_prd_revisions + 1):
        if result.prd_verdict != PMReviewerAgent.VERDICT_REVISION:
            break  # already approved

        key = f"prd_revision_{round_num}"
        if key not in result.completed_stages:
            # PM rewrites
            # draft_revision = the reviewer's own suggested rewrite (from rev_result["revised_prd"])
            pm_result = self.pm.run_revision(
                result.prd, result.prd_review, result.prd_reviewer_draft, requirement, result.project_name
            )
            # prd_reviewer_draft is a new PipelineResult field storing rev_result["revised_prd"]
            result.prd = pm_result["prd"]
            result.project_name = pm_result["project_name"]
            result.prd_revision_count = round_num

            # Reviewer re-checks
            rev_result = self.pm_reviewer.run(result.prd, requirement, result.project_name)
            result.prd_review = rev_result["review"]
            result.prd_verdict = rev_result["verdict"]

            result.completed_stages.append(key)
            self._save_checkpoint(result)
    else:
        # Exited loop without APPROVED
        if self.stop_on_prd_issues:
            # post comment, return False to halt
            return False
        # else: continue with current best, log warning

    result.completed_stages.append("pm_review_loop")
    self._save_checkpoint(result)
    return True
```

### `_design_revision_loop(result)`

Identical structure to `_prd_revision_loop` but uses `ArchitectAgent`, `ArchitectReviewerAgent`, `design_revision_N`, `architect_review_loop`, `max_design_revisions`, `stop_on_design_issues`.

### `run()` changes

```python
# Replace:
if "pm" not in result.completed_stages:
    ...  # pm stage
if "pm_reviewer" not in result.completed_stages:
    ...  # pm_reviewer stage

# With:
if "pm_review_loop" not in result.completed_stages:
    ok = self._prd_revision_loop(result, requirement)
    if not ok:
        return self._finish(result, start_time)
else:
    console.print("  ⏭️  [dim]PRD revision loop — skipped (checkpoint)[/dim]")

# Same replacement for architect + architect_reviewer
```

---

## Config Changes

```yaml
pipeline:
  max_retries: 2
  max_revisions: 3        # existing — PR revision rounds
  max_prd_revisions: 3    # new — PRD revision loop rounds (0 = disable loop)
  max_design_revisions: 3 # new — Design revision loop rounds (0 = disable loop)
  stop_on_review_issues: false   # existing
  stop_on_prd_issues: false      # new — halt instead of warn+continue
  stop_on_design_issues: false   # new
```

### Backwards compatibility
- `max_prd_revisions` defaults to `3` if absent
- `max_design_revisions` defaults to `3` if absent
- `0` disables the loop entirely (single-pass, existing behaviour)
- Old checkpoints without `pm_review_loop` key: loop re-runs from `pm_reviewer` stage

---

## Console Output

```
📝 PM Reviewer       Reviewing PRD for completeness...
  🔄 PRD NEEDS REVISION (round 1/3) — sending back to PM...
📋 Product Manager   Revising PRD based on reviewer feedback...
📝 PM Reviewer       Re-reviewing revised PRD...
  ✅ PRD APPROVED (round 2)

🔎 Architect Reviewer  Reviewing system design...
  ✅ DESIGN APPROVED
```

When max rounds hit without approval:
```
  ⚠️  Max PRD revisions reached (3/3). Continuing with current best.
```

---

## Halting Behaviour (stop_on_prd_issues / stop_on_design_issues)

When halt is triggered:
1. Pipeline saves checkpoint at current `prd_revision_N` key
2. Posts a GitHub Issue comment: `"⚠️ PRD revision limit reached after N rounds. Human review required. Remove label and re-trigger to retry."`
3. Returns `_finish(result)` early (same pattern as `stop_on_review_issues`)
4. To re-trigger: remove `agent-failed` label (watcher) or re-run with `--no-resume`

---

## Test Plan

- `test_prd_revision_loop_approves_on_round_2` — reviewer returns NEEDS_REVISION once then APPROVED
- `test_prd_revision_loop_max_rounds_continue` — 3 NEEDS_REVISION rounds → loop ends, pipeline continues, revision_count == 3
- `test_prd_revision_loop_max_rounds_halt` — `stop_on_prd_issues=True` → pipeline returns early
- `test_prd_revision_loop_checkpoint_resume` — checkpoint after round 1, resume skips round 1
- `test_design_revision_loop_approves_on_round_1` — architect reviewer approves on re-review
- `test_run_revision_pm_agent` — `ProductManagerAgent.run_revision()` includes feedback in prompt
- `test_run_revision_architect_agent` — `ArchitectAgent.run_revision()` includes feedback in prompt
