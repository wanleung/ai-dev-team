# Discussion Stage Milestone B — Inline Block in Pipeline Builder

**Date:** 2026-05-28  
**Status:** Approved  
**Milestone:** B (Milestone A — backend + watcher — is already complete and live)

---

## Overview

Extend `pipeline_builder/index.html` so the existing `💬 Discuss` palette item can define participants inline, directly in the pipeline builder UI. Two modes: **Inline** (define participants in the UI) and **Preset** (reference an external YAML file). This removes the requirement to create a separate `discussions/*.yaml` file for simple use cases.

---

## What Already Exists

- `pipeline_builder/index.html` — the pipeline builder UI (~440 lines)
- A `💬 Discuss` palette item already exists with basic form fields:
  - Participants: single textarea (role names only, one per line)
  - Max rounds: number input
  - Output mode: dropdown (both / synthesis / transcript)
- YAML generator writes `- discuss:` with `participants:` as flat role list
- YAML parser (reverse) reads `- discuss:` blocks back into the UI

These are the parts being extended; the block structure and styling remain consistent.

---

## UI Design

### Mode Toggle

Each discuss block gains a mode toggle at the top: **Inline** | **Preset file**

Default is Inline. Switching modes replaces the participant section with the appropriate fields.

---

### Inline Mode

Replaces the current textarea with structured participant rows.

**Each participant row** (collapsed by default):
- Role name input (short text, e.g. `analyst`)
- Persona preview (truncated, first ~60 chars of persona text)
- Edit ✏️ button → expands the row
- Remove ✕ button

**Expanded row** (triggered by ✏️):
- Role name input
- Persona textarea (multi-line, optional — leave blank if role name is sufficient)
- LLM dropdown (optional — select a specific backend; defaults to repo default)
  - Populated from `_get_stage_palette()` backend list, or hardcoded to: `(default)`, `openai`, `grok`, `codex`
- Done / collapse button

**Below the rows:** `+ Add participant` link

**Other fields** (unchanged from current): Max rounds number input, Output mode dropdown.

**Generated YAML (inline mode):**

```yaml
  - discuss:
      participants:
        - role: analyst
          persona: "You are a critical analyst who examines data objectively."
          llm: gpt-4o           # omitted if not set
        - role: skeptic
          persona: "You always challenge assumptions."
        - role: optimist         # persona omitted if blank
      max_rounds: 3
      output_mode: both
```

---

### Preset Mode

Replaces the participant section with a single text input:
- **Preset file:** e.g. `discussions/my-debate.yaml`

**Generated YAML (preset mode):**

```yaml
  - discuss:
      preset: my-debate.yaml
      max_rounds: 3
      output_mode: both
```

The orchestrator already supports preset files — no backend change needed.

---

## YAML Parser Changes

The reverse parser (which loads existing pipeline YAML back into the UI) must handle both forms:

| Pattern | Mode |
|---------|------|
| `preset: <filename>` key present | Preset mode |
| `participants:` list with objects (`- role: …`) | Inline mode with structured rows |
| `participants:` list with plain strings (`- analyst`) | Inline mode, role-name-only rows (backward compat) |

Backward compatibility: existing pipelines with plain role-name strings load as inline mode with empty persona fields.

---

## File Changes

| File | Change |
|------|--------|
| `pipeline_builder/index.html` | Extend discuss block: mode toggle, participant row add/remove/collapse, LLM dropdown, updated YAML generator, updated YAML parser |

No backend changes required. The `DiscussionAgent` already supports inline participant definitions with persona and per-participant LLM.

---

## LLM Dropdown Values

Options shown in the per-participant LLM dropdown:
- `(default)` — uses the repo-level LLM, no `llm:` key emitted
- `openai`
- `grok`
- `codex`

If more backends are added to the system, the dropdown list is updated here too.

---

## Error Handling

- If inline mode has zero participants added, generate no `participants:` key (backend falls back to `DEFAULT_PARTICIPANTS`)
- If preset mode field is blank, generate no `preset:` key (backend will error at runtime — acceptable, same as other misconfigured fields)
- Role name sanitisation: trim whitespace, disallow spaces (replace with `_`)

---

## Testing

- Manual: load pipeline builder, drag in a discuss block, switch modes, add/remove/edit participants, verify YAML preview updates
- Manual: paste existing YAML with preset and inline forms into the importer, verify correct mode and fields load
- No automated tests for the UI (consistent with current pipeline builder test strategy)
