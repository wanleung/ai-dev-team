# Agent ≤30-Line Function Rule — Design Spec

**Date:** 2026-05-24  
**Status:** Approved  
**Scope:** ai-software-house — agents/ directory and agent system prompts

---

## Problem

The orchestrator refactor (PR #88) proved that applying a ≤30-line function rule
produces cleaner, more testable code and surfaces pre-existing bugs in the process.
The same benefits should apply to:

1. The agent Python files themselves (base_agent, engineer, discussion_agent, etc.)
2. The code that AI agents generate for client projects

Small functions have a single responsibility, clear inputs/outputs, and fit within
an LLM's working context — making them easier to both generate and review accurately.

---

## Goals

- Every function in agents/ has a body ≤30 lines
- Code-generating agents enforce the ≤30-line rule in the code they produce
- Agents generate a function hierarchy (fn_map) alongside every module they write
- Agents flag (but do not auto-fix) violations in existing code they read
- The existing `tools/fn_map.py` HTML map covers agents/ so the hierarchy is always visible

---

## Non-Goals

- Applying the rule to non-agent Python files (orchestrator already done; others are separate)
- Auto-refactoring existing client code (agents flag violations; refactoring is user-initiated)
- Enforcing the rule on test files

---

## Architecture

Three independent workstreams, shippable as separate PRs:

```
Part A: Refactor agent .py files    (≤30-line rule applied to agents themselves)
Part B: Prompt injection            (coding_standards block in system prompts)
Part C: Post-generation validator   (fn_map.py called after agent file writes)
```

Part B must ship before Part C (agents need the rule before the validator enforces it).
Part A is independent and can ship in parallel with B+C.

---

## Part A — Agent File Refactoring

### Scope

24 agent files contain at least one function over 30 lines:

| File | Worst violator | Lines |
|------|---------------|-------|
| `base_agent.py` | `_build_backend` | 107 |
| `deploy_backends.py` | `run` | 76 |
| `discussion_agent.py` | `_call_participant` | 84 |
| `conflict_resolver.py` | `_resolve` | 77 |
| `engineer.py` | `run_module` | 68 |
| `qa_engineer.py` | `run` | 70 |
| `bootstrap_patterns_agent.py` | `run` | 59 |
| `architect.py` | `_parse_modules` | 56 |
| `senior_engineer.py` | `run_module` | 56 |
| `discussion_agent.py` | `run` | 65 |
| `token_ledger.py` | `flush_to_db` | 66 |
| `pr_proposal.py` | `_create_pr_with_retry` | 62 |
| `engineer.py` | `run_with_github` | 55 |
| `deploy_backends.py` | `_wait_for_ssh` | 48 |
| + 3 more files | | 31–46 |

### Method

Same methodology as orchestrator.py refactor:
- Extract private helpers with descriptive names (`_build_xyz`, `_parse_xyz`, `_validate_xyz`)
- Public API unchanged — no callers broken
- Each extracted helper is ≤30 lines
- All existing tests must pass after refactoring

### Output

A single PR covering all 24 files. `python tools/fn_map.py` must show zero violations
in agents/ after the PR merges.

---

## Part B — Prompt Injection

### Which Agents

Code-generating agents that write or significantly modify Python/code files:

- `engineer` (primary code writer)
- `senior_engineer`
- `qa_engineer` (writes test files)
- `architect` (writes module specs and scaffolding)
- `conflict_resolver` (rewrites conflicting code)
- `code_reviewer` (reviews and suggests fixes)
- `documentation_agent` (writes docstrings and docs)

### Prompt Block

Each agent's system prompt gets a `<coding_standards>` block:

```
<coding_standards>
FUNCTION SIZE RULE:
- Every function body must be ≤30 lines.
- If a function needs more than 30 lines, it is doing too much.
  Break it into named helpers with clear single responsibilities.
  Name helpers descriptively: _parse_xyz, _build_xyz, _validate_xyz.
- When reading existing code that violates this rule, include a
  "Violations flagged:" note in your output listing the offending
  function names and their line counts. Do NOT refactor them unless
  explicitly instructed to do so.

FUNCTION MAP:
- At the end of every module you write or significantly modify,
  append a `# --- fn_map ---` comment block listing every function
  in the module and the functions it calls.
  Format (one function per line):
    # parent_function -> [child1, child2]
  This block is used by automated tooling to verify function hierarchy.
</coding_standards>
```

### Placement

Injected at the end of each agent's existing system prompt, before any
`<output_format>` or `<constraints>` sections.

---

## Part C — Post-generation Validator

### New Helper in tools/fn_map.py

```python
def validate_function_sizes(
    files: list[Path],
    limit: int = 30,
) -> list[str]:
    """Return list of violation strings for any function exceeding limit lines.
    
    Each string has the format: "path.py::function_name (N lines)"
    Returns an empty list if all functions are within the limit.
    """
```

This helper is called by `base_agent.py` after any file-write operation.

### Validation Flow

```
1. Agent writes file(s) to disk
2. base_agent calls validate_function_sizes(written_files)
3. Violations?
   - No  → continue normally
   - Yes → inject violation report into agent's next message:
           "The following functions exceed 30 lines: [list].
            Please split them before finalising."
4. Agent revises (max 1 retry)
5. validate_function_sizes runs again
6. Persistent violations → logged to issue comment as a warning
   (pipeline continues — progress > perfection)
```

### Where the Hook Lives

`base_agent._after_write(files: list[Path])` — a new private method called
at the end of any code-write operation. Keeps the validation logic out of
individual agent `run()` methods.

---

## fn_map.yaml Coverage Update

`agents/` is already present in `fn_map.yaml`'s include list — no change needed.
The HTML map at `fn_map.html` will automatically show the full agents/ hierarchy
once Part A ships (zero violations).

---

## Testing

### Part A
- All existing tests pass after refactoring
- `python tools/fn_map.py` reports zero violations in agents/ 

### Part B
- Each modified system prompt file has a snapshot test confirming
  `<coding_standards>` block is present
- No existing agent behaviour tests broken

### Part C
- Unit tests for `validate_function_sizes`:
  - Returns empty list for compliant files
  - Returns correct violation strings for oversized functions
  - Handles files with syntax errors gracefully (returns empty list, logs warning)
- Integration test: mock agent that writes a >30-line function gets the violation
  feedback message injected

---

## Delivery Order

| PR | Contents | Depends on |
|----|----------|------------|
| PR-A | Refactor 24 agent files | — |
| PR-B | Prompt injection (7 agents) | — |
| PR-C | `validate_function_sizes` + `_after_write` hook | PR-B |

All three can be reviewed in parallel; PR-C merges last.
