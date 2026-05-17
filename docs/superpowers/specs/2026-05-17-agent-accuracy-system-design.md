# Agent Accuracy System — Design Spec

**Date:** 2026-05-17
**Status:** Approved, pending implementation plan
**Context:** Post-mortem of PR #64 (7 critical bugs in AI-generated code)

---

## Problem

AI agents generating code for this codebase produce errors because they:
1. Hallucinate APIs they cannot verify (e.g. `self.llm.generate()` doesn't exist)
2. Rewrite existing config files from scratch without reading them first
3. Miss cross-file integration requirements (e.g. `_make_stage_registry()` wiring)
4. Bypass RAG — new stage methods don't pass `tool_registry` to agents
5. Have no validation gate between code generation and PR creation
6. Have no mechanism to learn from failures and update role files

---

## Scope

Applies to:
- All code-writing pipelines (engineer, junior-engineer, senior-engineer agents)
- All content pipelines (PR campaign, docs, etc.) via schema validation
- A general opt-in framework that any pipeline stage can use

---

## Architecture

Three independent layers, each shippable independently:

```
Issue → [Layer 1: Prevention] → Agent writes → [Layer 2: Detection] → PR opened
                                                        │
                                              [Layer 3: Learning]
                                          Updates role files + memory-bank
```

---

## Layer 1: Prevention

### 1a. Role file cheatsheets

Add a `## Codebase Patterns` section to `roles/engineer.md` (and any agent role that writes code) containing:

- Correct method to call LLM: `self.call(user_message)` not `self.llm.generate()`
- `role_name` class attribute requirement for `BaseAgent` subclasses
- How to add a new pipeline stage (3-step pattern with registry)
- Rule: never rewrite config files — read first, append only
- `GitHubClient(repo=..., github_token=...)` constructor signature

**Format:** Plain `## Anti-patterns` section at end of role file. Append-only — never remove entries. Each entry includes the date it was learned.

### 1b. Auto-attached source context

`Orchestrator._build_engineer_context(task: str) -> str` inspects task description and attaches:
- If task mentions `BaseAgent` or creating an agent → first 120 lines of `base_agent.py`
- If task mentions `repos.yaml` or watchers → current `repos.yaml` contents
- If task mentions pipeline/stage/registry → `_make_stage_registry()` method signature block
- If task mentions `GitHubClient` → constructor and key method signatures

Context injected as an additional system message or appended to the user prompt.

### 1c. RAG wiring for all new agents

All agent stage methods in orchestrator must pass `tool_registry=self._rag_registry`. This is enforced in a new test: `test_all_stage_methods_pass_rag_registry.py`.

---

## Layer 2: Detection (validation_gate stage)

### Pipeline position

Inserted between the last code-generating stage and the PR-creation stage in every code pipeline YAML:

```yaml
stages:
  - engineer
  - validation_gate   # new
  - commit_pr
```

### Code validation checks

Runs in sequence; halts at first failure category:

1. **Syntax** — `python -m py_compile` on each `.py` file
2. **Lint** — `ruff check --select E,F` (errors and undefined names only, not style)
3. **Tests** — `pytest -x --timeout=30` scoped to files touched by the generated code

### Content validation checks

For JSON-output agents (pr_analyst, pr_creative, etc.):
- Schema validation against `STAGE_OUTPUT_SCHEMAS` registry
- Required field presence check
- Type checks (arrays must be arrays, etc.)

### Retry loop

On failure:
- If `result.validation_attempts < 2`: re-prompt the generating agent with the exact error output, retry
- If `result.validation_attempts >= 2`: mark PR as draft, add label `needs-human-fix`, log error

**Re-prompt format:**
```
Your previous code has validation errors:

{error_list}

Here is the code that failed:
{generated_files}

Fix only the errors listed. Do not change anything else.
Output all files in the same ### FILE: format.
```

### New fields on PipelineResult

- `validation_attempts: int = 0`
- `validation_errors: list[str] = field(default_factory=list)`
- `pr_draft: bool = False`

---

## Layer 3: Learning (LearningAgent)

### Trigger conditions

1. `validation_gate` catches an error that required human intervention (after 2 retries)
2. A PR with `ai-generated` label receives a review with `changes-requested` or rejection comments

### LearningAgent behaviour

Receives a `FailureRecord`:
```python
@dataclass
class FailureRecord:
    agent_role: str          # e.g. "engineer"
    error: str               # the error message / review comment
    fix: str                 # the corrected code or human explanation
    pipeline: str            # which pipeline triggered this
    timestamp: str
```

Steps:
1. Reads current `roles/{agent_role}.md`
2. Reads `memory-bank/systemPatterns.md`
3. Calls LLM to derive a concise "DO NOT" anti-pattern rule
4. Appends rule to `roles/{agent_role}.md` under `## Anti-patterns`
5. Appends to `memory-bank/systemPatterns.md` under `## Anti-patterns`
6. Commits both files with message: `chore(learning): add anti-pattern from {pipeline} failure`

### Anti-pattern format

```markdown
- DO NOT {wrong thing} — {correct thing instead}. ({date})
```

Example (from PR #64):
```markdown
- DO NOT call `self.llm.generate()` — use `self.call(user_message)` instead.
  BaseAgent does not expose `.llm` directly. (2026-05-17)
```

### Role file convention

`## Anti-patterns` section lives at the bottom of each role file. Learning agent appends. Never removes. Entries are dated for auditability.

---

## Implementation Milestones

**Milestone 1 — Prevention (no new infrastructure)**
- Update `roles/engineer.md` with `## Codebase Patterns` cheatsheet
- Implement `Orchestrator._build_engineer_context()`
- Add `tool_registry=self._rag_registry` to all stage methods
- Add test: `test_all_stage_methods_pass_rag_registry`

**Milestone 2 — Detection**
- Implement `_stage_validation_gate()` in orchestrator
- Add `validation_gate` to `pipelines/feature.yaml` and `pipelines/bug-fix.yaml`
- Add `validation_attempts`, `validation_errors`, `pr_draft` to `PipelineResult`
- Add `STAGE_OUTPUT_SCHEMAS` registry for content agents
- Tests: validation gate catches syntax error, lint error, triggers retry, marks draft on exhaustion

**Milestone 3 — Learning**
- Define `FailureRecord` dataclass
- Implement `LearningAgent` with `run(failure: FailureRecord)`
- Wire `LearningAgent` trigger in `validation_gate` (on human-fix path)
- Wire `LearningAgent` trigger in PR feedback watcher (on `changes-requested`)
- Add `roles/learning_agent.md` role file
- Tests: anti-pattern appended to role file, memory-bank updated, commit created

---

## What this prevents (PR #64 mapping)

| Bug | Prevented by |
|-----|-------------|
| `self.llm.generate()` doesn't exist | Cheatsheet (M1) + py_compile (M2) + anti-pattern (M3) |
| `repos.yaml` wiped | Cheatsheet: read-first rule (M1) + anti-pattern (M3) |
| Wrong YAML format | Cheatsheet: stage format (M1) + anti-pattern (M3) |
| Missing `_make_stage_registry()` entries | Cheatsheet: 3-step pattern (M1) + anti-pattern (M3) |
| Fragile relative path | ruff/runtime on retry (M2) + anti-pattern (M3) |
| Redundant `_load_system_prompt` | Cheatsheet: BaseAgent provides this (M1) |
| `GitHubClient()` no args | Cheatsheet: constructor sig (M1) + anti-pattern (M3) |

---

## Non-goals

- This does not replace human code review
- This does not make agents infallible
- Layer 3 does not automatically merge — all anti-patterns are committed to a branch for human review before merging to main role files
