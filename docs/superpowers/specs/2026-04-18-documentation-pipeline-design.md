# Documentation Pipeline Design

**Date:** 2026-04-18  
**Status:** Approved  
**Feature:** Lightweight documentation-only pipeline triggered by a GitHub issue label

---

## Problem

The existing watcher only supports two pipeline types: `feature` (full PM → Architect → Engineers chain) and `bug` (bug-fix orchestrator). There is no way to trigger a targeted documentation update without running the entire pipeline. Users need a way to file a GitHub issue labeled `documentation` and have an agent write/update only the relevant docs, then open a PR.

---

## Approach

Option A: Standalone `DocumentationAgent` + `DocOrchestrator`, following the same pattern as `Orchestrator` and `BugFixOrchestrator`. The watcher gains a `doc_label` config key and a new `pipeline_type="documentation"` dispatch path.

---

## Architecture

### New Files

#### `agents/documentation_agent.py`
An LLM agent that:
- Accepts the issue title and body as its primary prompt
- Has three tool calls available (executed via GitHub API, no local clone):
  - `read_file(path)` — fetch a single file's content from the target repo
  - `list_files(path)` — list directory contents
  - `search_files(pattern)` — find files matching a glob (e.g. `**/*.md`, `**/*.py`)
- Reads existing docs and relevant source files as context (iterative tool calls)
- Returns a structured list of file writes: `[{path, content, action: "create"|"update"}]`

The agent's system prompt instructs it to:
1. Parse any structured targets from the issue body (`**Docs:** README.md, docs/api.md`)
2. Read those files (and discover related files via list/search)
3. Read relevant source files when writing API or usage docs
4. Produce complete file content (not diffs) for every file it changes

#### `doc_orchestrator.py`
A thin orchestrator that:
1. Parses the issue body for `**Target repo:**` (reuses `parse_target_repo()`)
2. Instantiates `DocumentationAgent` with the target repo's GitHub client
3. Runs the agent → receives `file_writes[]`
4. Creates branch `doc/<issue-number>-<title-slug>` via GitHub API
5. Commits each file write to that branch
6. Opens a PR with a summary of changes and `Closes #<issue_number>` in the body
7. The PR creation causes GitHub to auto-close the issue on merge

### Modified Files

#### `watcher.py`
- `get_open_issues()` called for `doc_label` in addition to `feature_label` / `bug_label`
- Issues queued as `pipeline_type="documentation"`
- `_dispatch()` gains a `"documentation"` case that imports and runs `DocOrchestrator`
- `run_pipeline()` passes `pipeline_type` through unchanged

#### `repos.yaml`
New optional key per watcher entry:
```yaml
doc_label: documentation   # default value if omitted
```

#### `config.yaml`
No changes needed — `DocOrchestrator` inherits `retry_delay`, `max_api_retries`, and `inter_call_delay` from the global `pipeline:` config section via `BaseAgent`.

---

## Data Flow

```
GitHub issue (label: documentation)
  → Watcher polls → queues as pipeline_type="documentation"
  → _dispatch("documentation")
  → DocOrchestrator.run(issue_number)
      → fetch issue body from GitHub
      → parse target_repo (from body or default)
      → parse structured doc targets from body
      → DocumentationAgent.run(issue_title, issue_body, target_repo)
          → tool calls: search_files, read_file (iterative)
          → LLM generates file_writes[]
      → create branch: doc/<issue-number>-<slug>
      → commit each file in file_writes[]
      → open PR: "docs: <issue title>" → Closes #<issue>
  → Watcher marks agent-complete on tracker issue
```

---

## Issue Body Format

The agent supports both free-form and structured targets:

```
Update the README installation section and add a troubleshooting guide.

**Docs:** README.md, docs/troubleshooting.md
**Target repo:** wanleung/my-app
```

- `**Docs:**` — comma-separated list of files to update/create (optional; agent discovers relevant files if omitted)
- `**Target repo:**` — existing directive, already parsed by watcher

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| Agent returns no file writes | Fail with error, post comment, label `agent-failed` |
| Target repo inaccessible | Fail fast, post comment explaining, label `agent-failed` |
| GitHub API error (branch/commit/PR) | Retry with `retry_delay` / `max_api_retries` |
| Branch already exists | Append timestamp suffix to branch name |
| General unhandled exception | Follow existing watcher error pattern (comment + log path) |

---

## Testing

- **Unit — `DocumentationAgent`**: mock tool calls (list/read → returns file writes), assert structured output
- **Unit — `DocOrchestrator`**: mock GitHub API (issue fetch, branch create, file commit, PR open), assert correct calls
- **Regression**: existing 132-test suite must pass unchanged

---

## Out of Scope

- Doc linting or validation
- Multiple PRs per issue (one PR with all changes)
- Memory bank updates from documentation runs
- Changelog / release-notes generation
