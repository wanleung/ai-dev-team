# Conflict Resolver Agent

> Automatically resolves git merge conflicts on pull requests using real 3-way merge markers and a configurable LLM.

## Overview

When the AI Software House watcher detects an `update-branch` directive on a pull request, it calls GitHub's merge-base API to rebase the PR branch onto the latest base branch. Most of the time this succeeds cleanly. Occasionally GitHub returns `409 Conflict` — meaning the two branches have diverged in ways git cannot automatically reconcile.

Rather than stopping and asking a human to fix the conflict manually, `ConflictResolverAgent` takes over. It clones the repository locally, runs a real `git merge` to materialize the conflict markers, and sends each conflicting file to an LLM for resolution. The LLM uses the PR's title and description as context to understand _intent_ — critical for choosing correctly between competing changes. Once all files are resolved, the agent commits and pushes the branch, and the orchestrator retries the merge API call.

The agent is fully integrated into the PR revision loop via `Orchestrator._update_branch_from_base()` and is configured per-repo in `repos.yaml` via the `conflict_resolver_model` key. It is designed to be a best-effort helper: if resolution fails or the push is rejected, it reports the failure cleanly and posts a descriptive comment on the PR so a human can take over.

## Why 3-Way Merge?

A naive 2-way diff compares only the PR's `HEAD` to the base branch `HEAD`. It can show you which lines differ, but cannot tell you _which side changed_ relative to the common ancestor. This makes automated resolution unreliable: the "correct" resolution often depends on knowing whether a line was added by the PR, added by the base branch, or was present in both.

Git's built-in 3-way merge engine knows the common merge-base. When it writes conflict markers it embeds all three versions:

```
<<<<<<< HEAD
# PR's version of the line
=======
# base branch's version of the line
>>>>>>> origin/main
```

This gives the LLM exactly the information it needs: what the PR author intended (`HEAD`), what the target branch now looks like, and implicitly what the shared ancestor was. Feeding these real markers to the LLM produces dramatically more accurate resolutions than any 2-way approach.

## Architecture

### Components

#### `PRContext` dataclass

```python
@dataclass
class PRContext:
    pr_title: str      # PR title — summarises the PR's intent
    pr_body: str       # PR description — more detailed intent
    design_doc: str    # linked design doc (currently passed as "" — future use)
    skills: str        # agent skills context (currently passed as "" — future use)
```

Passed to the agent to steer LLM resolution. The more accurate the PR title and body, the better the conflict resolution.

#### `ResolveResult` dataclass

```python
@dataclass
class ResolveResult:
    status: Literal["resolved", "failed"]
    resolved_files: list[str]   # files successfully resolved
    failed_files: list[str]     # files the LLM could not resolve
    reason: str                 # human-readable failure reason (empty on success)
```

Returned by `ConflictResolverAgent.resolve()`. The orchestrator inspects `status` to decide whether to retry the GitHub merge API.

#### `ConflictResolverAgent(BaseAgent)`

Extends `BaseAgent` and adds:

- `resolve(repo_url, head_branch, base_branch, pr_context) → ResolveResult` — the public entry point; creates a temp dir, delegates to `_resolve()`, and always cleans up.
- `_resolve(tmpdir, ...)` — core logic: clone → config → checkout → merge → diff → per-file LLM → commit → push.
- `_resolve_file(path, content, ctx) → str` — builds the LLM prompt for a single file and calls `self.call()`.
- `_run(cmd, cwd) → CompletedProcess` — thin wrapper around `subprocess.run`.
- `_sanitise(text) → str` — strips the GitHub token from any string before surfacing it.
- `role_name = "conflict_resolver"` — loads `roles/conflict_resolver.md` as the system prompt.

### Resolution Flow

1. **Clone** — `git clone --filter=blob:none <repo_url> <tmpdir>` (blobless for speed)
2. **Configure** — set `user.email` and `user.name` in the local clone
3. **Checkout** — `git checkout <head_branch>`
4. **Fetch base** — `git fetch origin <base_branch>`
5. **Merge** — `git merge origin/<base_branch>`; if exit code 0 → clean merge, return `resolved` immediately
6. **Diff for conflicts** — `git diff --name-only --diff-filter=U` lists unmerged files
7. **Per-file LLM resolution** — for each conflicting file: read raw content (with markers), send to LLM via `_resolve_file()`, write resolved content back, `git add <file>`
8. **Commit** — `git commit -m "chore: resolve merge conflicts with <base_branch>"`
9. **Push** — `git push origin <head_branch>`; on failure return `ResolveResult(status="failed", ...)`
10. **Return** — `ResolveResult(status="resolved", resolved_files=[...])`

Full command sequence:

```
git clone --filter=blob:none https://<token>@github.com/owner/repo.git /tmp/xyz
git config user.email conflict-resolver@bot
git config user.name "Conflict Resolver Bot"
git checkout feature/my-branch
git fetch origin main
git merge origin/main                          # exits 1 on conflict
git diff --name-only --diff-filter=U           # → [src/app.py, ...]
# for each conflicting file:
#   LLM resolves → write file → git add <file>
git commit -m "chore: resolve merge conflicts with main"
git push origin feature/my-branch
```

## Configuration

### `repos.yaml`

```yaml
watchers:
  - tracker_repo: wanleung/my-app
    target_repo: wanleung/my-app
    update_branch: true                          # enable auto update-branch
    conflict_resolver_model: "gpt-4o"            # optional; see fallback chain below
    model: "gpt-4.1-mini"
    senior_model: "gpt-4.1"
```

`conflict_resolver_model` is optional. If omitted, the agent falls back through the model hierarchy.

### Model Selection Fallback

The orchestrator selects the model using this chain:

```
conflict_resolver_model  →  senior_model  →  model
```

1. `conflict_resolver_model` (from `repos.yaml` → `_w_settings`) — explicit override for conflict resolution
2. `senior_model` — the repo's "senior" model (used for complex tasks)
3. `model` — the repo's default model (last resort)

A stronger model is recommended for conflict resolution because the agent must _understand PR intent_ to choose between competing changes. Weaker models may produce syntactically clean but semantically wrong resolutions.

## Integration Points

### Orchestrator (`orchestrator.py`)

`_update_branch_from_base()` is the primary integration point:

```python
def _update_branch_from_base(
    self,
    head_branch: str,
    base_branch: str = "master",
    pr_number: int | None = None,
    pr_context: "PRContext | None" = None,
) -> dict:
```

1. Calls `self.target_github.merge_base_into_branch(base_branch, head_branch)`.
2. If `204` → already up to date, posts ℹ️ comment, returns `{"status": "up_to_date"}`.
3. If `201` → clean merge, posts ✅ comment, returns `{"status": "merged"}`.
4. If `409` → conflict path:
   - If `pr_context is None` → posts ⚠️ comment, returns `{"status": "conflict", "conflicting_files": []}`.
   - Selects model via fallback chain.
   - Constructs `repo_url = f"https://{token}@github.com/{repo}.git"`.
   - Instantiates `ConflictResolverAgent(model=model, **self.agent_kwargs)`.
   - Calls `resolver.resolve(...)`.
   - On `status="resolved"`: retries `merge_base_into_branch`; if 201/204 posts ✅ and returns `{"status": "merged"}`.
   - On retry still 409: posts ⚠️ "resolved locally but merge still failed", returns `{"status": "conflict", "conflicting_files": []}`.
   - On `status="failed"`: posts ⚠️ with `failed_files` list, returns `{"status": "conflict", "conflicting_files": result.failed_files}`.

`_update_branch_from_base()` is called from `run_revision()` at **step 0** — before feedback collection. The `PRContext` is built inline from the live PR object:

```python
pr_ctx = PRContext(
    pr_title=pr.get("title", ""),
    pr_body=pr.get("body", "") or "",
    design_doc="",
    skills="",
)
```

### Watcher (`watcher.py`)

`_watch_prs()` reads the watcher settings for each repo and passes both flags to `_run_pr_revision()`, which forwards them to the `Orchestrator` constructor:

```python
update_branch_enabled = bool(_w_settings.get("update_branch", False))
conflict_resolver_model = _w_settings.get("conflict_resolver_model")
```

These are then passed to `Orchestrator.__init__()` via `_run_pr_revision()`:

```python
update_branch_enabled=update_branch_enabled,
conflict_resolver_model=conflict_resolver_model,
```

## Error Handling

| Scenario | Behaviour |
|---|---|
| Clone fails | `ResolveResult(status="failed", reason="clone failed: <sanitised stderr>")` |
| `git checkout` fails | `ResolveResult(status="failed", reason="checkout failed: ...")` |
| `git fetch` fails | `ResolveResult(status="failed", reason="fetch failed: ...")` |
| No conflicts after merge (race condition) | `ResolveResult(status="resolved", resolved_files=[])` — treated as success |
| LLM raises exception on a file | File added to `failed_files`; returns `ResolveResult(status="failed")` with partial `resolved_files` |
| Push fails | `ResolveResult(status="failed", resolved_files=[already fixed files], reason="push failed: ...")` |
| Retry merge still 409 | `conflicting_files=[]`; PR comment: "resolved locally but merge still failed" |
| `pr_context is None` | Immediate return `{"status": "conflict", "conflicting_files": []}` — no agent instantiated |
| Unexpected exception in `resolve()` | Caught by outer `try/except`; `ResolveResult(status="failed", reason=str(exc))`; temp dir always cleaned up |

## Security

Git prints the clone URL in error messages and some progress output, which means a GitHub token embedded in an HTTPS URL can appear in `stderr`. The `_sanitise()` helper strips the token before any stderr text is included in a `ResolveResult.reason` or logged:

```python
def _sanitise(self, text: str) -> str:
    token = getattr(self, "_token", None)
    if token:
        return text.replace(token, "***")
    return text
```

`_sanitise()` is called on every `r.stderr` path (clone, checkout, fetch, push failures). The token is read from `self._token`, which `BaseAgent` sets from the `github_token` kwarg.

## Testing

### Unit tests (`tests/test_conflict_resolver.py`) — 7 tests

| Test | What it covers |
|---|---|
| `test_resolve_single_file` | Happy path: single conflicting file resolved, written, pushed |
| `test_resolve_no_conflicts` | Race condition: merge exits 0 (no markers) → `status="resolved"`, `resolved_files=[]` |
| `test_resolve_clone_failure` | Clone exits 1 → `status="failed"`, `reason` contains `"clone failed"` |
| `test_resolve_push_failure` | Push exits 1 → `status="failed"`, `reason` contains `"push failed"`, partial `resolved_files` preserved |
| `test_resolve_llm_failure_for_file` | `agent.call` raises `RuntimeError` → file in `failed_files`, `status="failed"` |
| `test_resolve_multi_file` | Two conflicting files both resolved → `resolved_files == ["a.py", "b.py"]` |
| `test_tempdir_cleaned_on_exception` | `subprocess.run` raises → `shutil.rmtree` still called, `status="failed"` |

### Wire tests (`tests/test_conflict_resolver_wire.py`) — 5 tests

| Test | What it covers |
|---|---|
| `test_conflict_resolver_called_on_409` | 409 → agent called → retry merge → `{"status": "merged"}`, merge called twice |
| `test_conflict_resolver_failed_returns_false` | Agent returns `status="failed"` → returns `{"status": "conflict"}`, no retry |
| `test_no_pr_context_returns_false_on_conflict` | `pr_context=None` + 409 → agent NOT instantiated, returns `{"status": "conflict", "conflicting_files": []}` |
| `test_conflict_resolver_uses_override_model` | `conflict_resolver_model="gpt-4o"` → agent constructed with `model="gpt-4o"` |
| `test_conflict_resolver_falls_back_to_senior_model` | `conflict_resolver_model=None`, `senior_model="claude-3-opus"` → agent uses `"claude-3-opus"` |

## File Map

| File | Purpose |
|---|---|
| `agents/conflict_resolver.py` | Agent implementation (`PRContext`, `ResolveResult`, `ConflictResolverAgent`) |
| `tests/test_conflict_resolver.py` | Unit tests (7 tests) |
| `tests/test_conflict_resolver_wire.py` | Orchestrator integration tests (5 tests) |
| `roles/conflict_resolver.md` | LLM system prompt — instructs the model to output only resolved file content |

## Limitations & Known Trade-offs

- **Blobless clone** (`--filter=blob:none`) saves bandwidth but requires git ≥ 2.27. Older git versions will fall back to a full clone or error — check your runtime git version.
- **Best-effort resolution** — if the LLM misunderstands the PR intent, the resolution may be semantically wrong even if syntactically clean (no remaining conflict markers). Human review of AI-resolved conflicts is still advisable for production-critical branches.
- **`design_doc` and `skills` on `PRContext`** are currently passed as empty strings. A future improvement could populate `design_doc` from the linked GitHub Issue body and `skills` from the `roles/` directory, giving the LLM richer context.
- **No partial-success retry** — if one file fails LLM resolution, the whole operation is aborted. Files that were already resolved and staged are listed in `resolved_files` but not committed; the next run will start fresh.
- **Token in clone URL** — while `_sanitise()` scrubs tokens from logged stderr, the token appears in the `git clone` command itself in any verbose shell trace. Avoid verbose logging of subprocess commands in production.
