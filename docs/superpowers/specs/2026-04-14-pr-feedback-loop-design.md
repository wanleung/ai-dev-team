# PR Feedback Loop — Design Spec

**Date:** 2026-04-14  
**Feature:** Agents read PR review comments from humans and automatically revise the code.

---

## Problem

The AI pipeline generates code and opens a PR. When human reviewers leave comments or reviews, those are currently ignored — agents never see the feedback and the code is never updated.

## Goal

When anyone posts a review comment on an AI-generated PR, the engineer + reviewer + QA agents automatically re-run, address the feedback, and push updated commits to the same branch. This repeats up to `max_revisions` times (default: 3, configurable).

---

## Trigger

**GitHub Actions event:** `pull_request_review` and `pull_request_review_comment`  
**Filter:** Only fires on PRs that carry the `ai-generated` label (all AI PRs already receive this label).  
**Anti-loop guard:** Commits pushed by the bot (`GITHUB_ACTOR == github-actions[bot]`) do not re-trigger the workflow.

---

## Revision Round Tracking

Each revision round is tracked via a PR label: `ai-revision-1`, `ai-revision-2`, etc.

- Before running, the workflow reads all PR labels and extracts the current revision number (0 if none).
- If `current_revision >= max_revisions`, the workflow posts a comment:  
  > "⏹ Max revisions reached (N/N). No further automated revisions will be made."  
  Then exits without running agents.
- After a successful revision, the old `ai-revision-N` label is removed and `ai-revision-(N+1)` is added.

`max_revisions` is read from `config.yaml → pipeline.max_revisions` (default: 3).

---

## Feedback Collection

`github_client.py` gains four new read methods:

| Method | Endpoint | Purpose |
|---|---|---|
| `get_pr(pr_number)` | `GET /repos/{repo}/pulls/{n}` | PR metadata: head branch, linked issue ref |
| `get_pr_review_comments(pr_number)` | `GET /repos/{repo}/pulls/{n}/comments` | Inline code review comments |
| `get_pr_reviews(pr_number)` | `GET /repos/{repo}/pulls/{n}/reviews` | Review-level bodies (CHANGES_REQUESTED, etc.) |
| `get_pr_files(pr_number)` | `GET /repos/{repo}/pulls/{n}/files` | List of files changed in the PR (for reading current code) |

**Bot comment filtering:** Comments/reviews where `user.login` is `github-actions[bot]` (or matches `GITHUB_ACTOR`) are excluded to avoid the agent reacting to its own previous comments.

---

## Agents That Re-Run

Only the code-related stages run during a revision:

1. **Engineer** — given the full PR feedback, the existing architecture doc (from linked issue), and the current code on the branch. Rewrites or patches files to address every comment.
2. **Code Reviewer** — reviews the revised code the same way it does in the original pipeline.
3. **QA Engineer** — runs / writes tests against the revised code.

PM and Architect stages are skipped (requirement has not changed).

---

## Orchestrator Changes

A new `run_revision(pr_number: int)` method on `Orchestrator`:

1. Calls `github_client.get_pr(pr_number)` → extracts `head_branch`, linked issue number.
2. Calls `get_pr_review_comments` + `get_pr_reviews` → collects all human feedback, deduplicates, formats as a markdown list.
3. Reads existing architecture doc from the linked issue comments (same as original pipeline).
4. Reads current code files from the branch via `get_contents` (existing git client capability).
5. Runs Engineer → Code Reviewer → QA with the feedback injected as additional context.
6. Commits updated files to the same branch (new commits on top — no force push).
7. Posts a PR comment: "✅ Revision N complete — addressed N feedback items."
8. Updates the `ai-revision-N` label.

---

## New GitHub Actions Workflow: `pr-feedback.yml`

```yaml
name: 🔄 AI PR Feedback Loop

on:
  pull_request_review:
    types: [submitted]
  pull_request_review_comment:
    types: [created]

jobs:
  revise:
    if: contains(github.event.pull_request.labels.*.name, 'ai-generated')
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
      issues: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11", cache: "pip" }
      - run: pip install -r requirements.txt
      - run: python main.py --mode revise --pr ${{ github.event.pull_request.number }}
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          TARGET_REPO: ${{ secrets.TARGET_REPO }}
```

---

## Config Changes (`config.yaml`)

```yaml
pipeline:
  max_revisions: 3   # Maximum number of automated revision rounds per PR
```

---

## `main.py` CLI Changes

New `--mode` flag:

```
python main.py --mode build  "Build a REST API..."   # existing (default)
python main.py --mode revise --pr 42                 # new: revise PR #42
```

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| No human comments found (all bot) | Exit silently without running agents |
| Engineer fails | Post error comment on PR, increment label anyway to avoid retry storm |
| Code Reviewer requests changes | Continue to QA (same as original pipeline behaviour) |
| Max revisions exceeded | Post "max revisions reached" comment and stop |

---

## Out of Scope

- Creating a new PR per revision (same-branch updates only)
- Responding to issue comments (only PR review comments / reviews are in scope)
- Running PM or Architect during revisions

---

## Files to Create / Modify

| File | Change |
|---|---|
| `github_client.py` | Add `get_pr`, `get_pr_review_comments`, `get_pr_reviews`, `get_pr_files` |
| `orchestrator.py` | Add `run_revision()` method |
| `main.py` | Add `--mode revise --pr N` CLI flag |
| `.github/workflows/pr-feedback.yml` | New workflow file |
| `config.yaml` | Add `pipeline.max_revisions: 3` |
| `roles/engineer.md` | Add guidance on incorporating PR feedback |
