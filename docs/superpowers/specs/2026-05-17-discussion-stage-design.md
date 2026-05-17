# Discussion Stage — Design Spec

**Date:** 2026-05-17  
**Status:** Approved  
**Milestone A:** Named preset stages (this spec)  
**Milestone B:** Inline `discuss` block in pipeline builder UI (future)

---

## Problem

ai-software-house pipelines pass context sequentially: each stage produces output consumed by the next. There is no mechanism for multiple agents with different perspectives to discuss a topic and produce a richer, more creative, or more critically examined result before passing to the next stage. This gap means complex tasks (proposals, news analysis, architecture decisions) skip the internal debate a real team would have.

---

## Goal

Add a reusable **discussion stage** to the pipeline system. Any pipeline YAML can include a `discuss:` stage that spins up a configurable round-table of agents, runs their debate, and writes a transcript and/or synthesis to `PipelineResult` for downstream stages to use.

---

## Architecture

Three additions, no changes to existing agents:

```
orchestrator.py
  └─ auto-discovers discussions/*.yaml at startup
  └─ registers each as a named PipelineStage ("discuss:brainstorm", etc.)
  └─ palette endpoint returns discovered discuss stages automatically

agents/discussion_agent.py          ← NEW
  └─ DiscussionConfig               dataclass (parsed from preset YAML)
  └─ Participant                    role + persona (file or inline) + optional llm override
  └─ Turn                           role + content (one message in transcript)
  └─ DiscussionAgent.run(result)    entry point called by PipelineStage.fn

PipelineResult
  └─ discussion_transcript: str     ← NEW (formatted turn-by-turn log)
  └─ discussion_synthesis:  str     ← NEW (moderator output)
```

---

## File Structure

```
ai-software-house/
  discussions/               preset discussion configs (one file per use-case)
    brainstorm.yaml          generic idea/proposal brainstorm
    news-analysis.yaml       news discussion with analyst, skeptic, optimist
  roles/                     reusable persona markdown files
    analyst.md
    skeptic.md
    optimist.md
    moderator.md
  agents/
    discussion_agent.py      new module
```

---

## Preset Config Schema (`discussions/*.yaml`)

```yaml
participants:
  - role: analyst
    persona_file: roles/analyst.md       # reference a file
  - role: skeptic
    persona: "You challenge every assumption ruthlessly."  # or inline
  - role: optimist
    persona_file: roles/optimist.md
    llm: opencode-go/qwen3.6-plus        # optional per-participant LLM override

homework_round: true      # if true: round 0 runs all participants in parallel
                          # (blind — no transcript yet). Good for "do your research first".
max_rounds: 3             # ceiling on discussion rounds AFTER homework (homework = round 0)
early_exit: CONSENSUS_REACHED   # any participant emitting this string ends the loop

moderator:
  persona_file: roles/moderator.md
  # if omitted: last participant acts as moderator when synthesis is needed

output_mode: both         # transcript | synthesis | both

context_fields:           # PipelineResult fields fed into the opening context
  - spec
  - design
  - issue_body
```

**Rules:**
- `persona_file` and `persona` are mutually exclusive per participant.
- `llm` is optional; if absent, the stage's assigned `FallbackLLMBackend` is used.
- `moderator` is optional; if absent and `output_mode` includes synthesis, the last participant in the list writes the synthesis.
- `context_fields` defaults to `[issue_body]` if not specified.

---

## Pipeline YAML Usage

```yaml
stages:
  - pm
  - architect
  - discuss:brainstorm        # references discussions/brainstorm.yaml
  - reviewer
  - engineer
```

The `discuss:` prefix is the convention. `brainstorm` maps to `discussions/brainstorm.yaml`.

---

## DiscussionAgent Execution Flow

```
DiscussionAgent.run(result: PipelineResult)
│
├── 1. Build context
│      Concatenate selected PipelineResult fields (per context_fields)
│      into a single context string passed to all participants.
│
├── 2. Homework round  [only if homework_round: true]
│      All participants run in parallel via ThreadPoolExecutor.
│      Each receives:  system=persona, user=context
│      No transcript visible to any participant yet.
│      All outputs appended to transcript as round 0.
│
├── 3. Discussion rounds  [up to max_rounds, or remaining after homework]
│      For each round:
│        For each participant (sequential within a round):
│          Receives: system=persona, user=context + full transcript so far
│          Appends Turn(role, content) to transcript
│          If early_exit signal found in content → break all rounds
│
├── 4. Synthesis  [if output_mode in (synthesis, both)]
│      Moderator receives: system=moderator_persona, user=context + full transcript
│      Moderator writes structured output (proposal / decision / insight).
│
└── 5. Write outputs
       result.discussion_transcript ← formatted log   (if output_mode in transcript, both)
       result.discussion_synthesis  ← moderator text  (if output_mode in synthesis, both)
```

---

## Orchestrator Integration

### Auto-discovery

At orchestrator startup, `_make_stage_registry()` scans `discussions/` relative to the config file location. For each `*.yaml` found:

```python
"discuss:brainstorm" → PipelineStage(
    name="discuss:brainstorm",
    label="💬 Discuss: Brainstorm",
    description="Multi-agent round-table discussion (brainstorm preset)",
    checkpoint_key="discuss_brainstorm",
    fn=lambda r, cfg=cfg_path: DiscussionAgent.from_file(cfg, backend).run(r),
)
```

`_get_stage_palette()` already calls `_make_stage_registry()`, so discovered discuss stages appear in the pipeline builder UI palette with no additional changes.

### PipelineResult fields

Two new optional fields added to `PipelineResult`:

```python
discussion_transcript: str = ""
discussion_synthesis:  str = ""
```

Downstream stages (e.g. `reviewer`, `engineer`) can read these fields normally.

---

## Error Handling

| Condition | Behaviour |
|-----------|-----------|
| Participant LLM call fails | Retry via `FallbackLLMBackend`; if all backends exhausted, log and skip that turn |
| `discussions/` directory missing | No discuss stages registered; no error |
| Preset YAML malformed | `DiscussionConfig` raises `ValueError` with clear message at stage setup |
| `persona_file` not found | `ValueError` at startup, not at runtime |
| `max_rounds: 0` | Treated as 1 |

---

## Transcript Format

```
=== Discussion: brainstorm ===

[Round 0 — Homework]
ANALYST: ...
SKEPTIC: ...
OPTIMIST: ...

[Round 1]
ANALYST: ...
SKEPTIC: ... CONSENSUS_REACHED
--- Early exit: consensus reached after round 1 ---

=== Synthesis ===
MODERATOR: ...
```

---

## Milestone B — Future UI Enhancement

When implemented, the pipeline builder UI will support an inline `discuss` block (similar to the existing Loop block):

- New `💬 Discuss` palette item (purple, draggable)
- Dropped block shows form: participant list, rounds slider, output_mode dropdown
- Generates inline YAML (no separate preset file needed):
  ```yaml
  - discuss:
      participants:
        - role: analyst
          persona: "..."
      max_rounds: 3
      output_mode: both
  ```
- Extends `index.html` YAML parser + renderer
- Preset files remain supported alongside inline blocks

**This is deferred to Milestone B. No changes to `index.html` in Milestone A.**

---

## Out of Scope (Milestone A)

- Agents responding to each other with @mentions (each participant sees the full transcript, not individual messages)
- Persistent discussion history across pipeline runs (memory bank integration is future)
- Dynamic participant count based on issue content
- Streaming output during discussion (log is written after each turn, but no live UI update)
