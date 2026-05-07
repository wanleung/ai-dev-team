# Conflict Resolver Agent — Design Spec

**Date:** 2026-05-07  
**Status:** Approved

---

## Problem

When `update-branch` triggers a merge and GitHub returns 409 (conflict), the current inline resolution logic fails to fix the conflict. It compares only two file versions (PR branch vs base branch) using the junior engineer model with no PR context. The retry merge then returns 409 again because the committed files do not resolve the actual git conflict state.

Root cause: the approach is a naive 2-way comparison. A correct resolution requires 3-way merge data (ancestor + ours + theirs) and semantically aware reasoning grounded in the PR's intent.

---

## Solution: `ConflictResolverAgent`

A new standalone agent class (`agents/conflict_resolver.py`) that clones the repository locally, runs `git merge` to obtain real conflict markers, resolves each conflict with a strong LLM using full PR context, and pushes the result.

---

## Architecture

### New file: `agents/conflict_resolver.py`

Single public method:

```python
def resolve(
    repo_url: str,
    head_branch: str,
    base_branch: str,
    pr_context: PRContext,
) -> ResolveResult
```

`PRContext` dataclass:
- `pr_title: str`
- `pr_body: str`
- `design_doc: str`   # linked issue design, may be empty
- `skills: str`       # loaded skills markdown

`ResolveResult` dataclass:
- `status: Literal["resolved", "failed"]`
- `resolved_files: list[str]`
- `failed_files: list[str]`
- `reason: str`       # populated on failure

### Resolution flow

1. Clone repo to `tempfile.mkdtemp()` using token auth:  
   `https://x-access-token:<token>@github.com/<owner>/<repo>.git`
2. `git checkout <head_branch>`
3. `git merge origin/<base_branch>` — writes `<<<<<<<` / `=======` / `>>>>>>>` markers into conflicting files
4. Detect conflicting files: `git diff --name-only --diff-filter=U`
5. For each conflicting file:
   - Read raw file content (with conflict markers)
   - Build LLM prompt: conflict text + PR title/body + design doc + skills
   - Call LLM; write resolved content back to file
   - `git add <file>`
6. `git commit -m "chore: resolve merge conflicts with <base_branch>"`
7. `git push origin <head_branch>`
8. Clean up temp dir in `finally`

### LLM prompt structure

```
You are resolving a git merge conflict in a pull request.

PR Title: <title>
PR Description: <body>

Design context:
<design_doc>

Skills:
<skills>

Resolve the following conflict. Output ONLY the resolved file content, no explanation.

File: <path>
<file content with <<<, ===, >>> markers>
```

---

## Integration with Orchestrator

### Changes to `_update_branch_from_base()`

The existing 409 inline resolution block is replaced:

```
409 received
  → build PRContext from already-available pr, design, skills
  → instantiate ConflictResolverAgent(token, model=conflict_resolver_model)
  → result = agent.resolve(repo_url, head_branch, base_branch, pr_context)
  → if result.status == "resolved":
      retry GitHub merge API (expect 201/204)
      post ✅ comment + _UPDATE_BRANCH_MARKER
      return {"status": "merged"}
  → if result.status == "failed":
      post ⚠️ comment listing failed_files + _UPDATE_BRANCH_MARKER
      return {"status": "conflict", "conflicting_files": result.failed_files}
```

### Changes to `Orchestrator.__init__()`

New optional parameter:
```python
conflict_resolver_model: Optional[str] = None
```

Stored as `self._conflict_resolver_model`. Falls back to the senior engineer model if `None`.

### Changes to `watcher.py`

Reads `conflict_resolver_model` from per-repo YAML config alongside `update_branch: true`, passes to `Orchestrator`.

---

## Configuration

In `repos.yaml` (per repo, optional):

```yaml
repos:
  - repo: wanleung/custom-blog
    update_branch: true
    conflict_resolver_model: qwen3.6-plus   # omit to use senior_model
```

---

## Error Handling

| Failure point | Behaviour |
|---|---|
| Clone fails (auth/network) | Return `failed`, reason: "clone failed: <stderr>" |
| `git merge` — no conflicts (race) | Return `resolved`, `resolved_files: []` |
| LLM call fails for a file | Add to `failed_files`; continue with remaining files |
| Any `failed_files` after push | Return `failed`, reason lists unresolved files |
| `git push` fails | Return `failed`, reason: "push failed: <stderr>" |
| Temp dir | Always cleaned up in `finally` |

---

## Testing

New file: `tests/test_conflict_resolver.py`

- Mock `subprocess.run` for all git commands
- Mock LLM backend (`agent.call`)
- Test: successful single-file resolution → `resolved`
- Test: successful multi-file resolution → `resolved`, all files listed
- Test: LLM fails on one file → `failed`, that file in `failed_files`
- Test: clone failure → `failed`
- Test: push failure → `failed`
- Test: no conflicts after merge (race) → `resolved`, empty list
- Test: temp dir always cleaned up

---

## Out of Scope

- Binary file conflicts (skip and report as unresolvable)
- Conflict resolution for files deleted in one branch and modified in the other (treat as unresolvable, add to `failed_files`)
