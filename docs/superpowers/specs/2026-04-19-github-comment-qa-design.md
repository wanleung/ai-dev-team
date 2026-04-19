# Design: GitHub Comment Q&A for Pipeline Agents

**Date:** 2026-04-19  
**Status:** Approved  

## Problem

The pipeline runs fully automated via cron. When PM or Architect agents encounter ambiguous requirements, they currently proceed with assumptions. This leads to incorrect implementations. There is no mechanism for agents to ask the repository owner clarifying questions and wait for answers.

## Scope

- **In scope:** PM and Architect agents can pause the pipeline, post questions to the GitHub issue, and resume when answered.
- **Out of scope:** Bug-fix pipeline, documentation pipeline, agents after Architect Reviewer (code is already being written by then).
- **Max Q&A rounds:** 3 per agent (to prevent infinite loops). After max rounds, proceed with best-guess assumptions.
- **Timeout:** 24 hours without an answer → proceed with assumptions.

---

## Architecture

### Label State Machine

A new `agent-waiting` label is added to the existing label lifecycle:

```
agent-queued
  → agent-running       (pipeline dispatched)
    → agent-waiting     (agent needs clarification, pipeline paused)
      → agent-running   (human answered, pipeline resumed)
    → agent-complete    (pipeline finished)
    → agent-failed      (pipeline error)
```

`agent-waiting` is **not** in `SKIP_LABELS` — the watcher picks up waiting issues on every cron run to check for answers.

---

## Components

### 1. `ClarificationNeeded` exception (`orchestrator.py`)

```python
class ClarificationNeeded(Exception):
    def __init__(self, questions: list[str]):
        self.questions = questions
```

PM and Architect agents raise this when they determine they need input. The orchestrator catches it at the stage level.

### 2. `request_clarification()` on BaseAgent (`agents/base_agent.py`)

Agents call `self.request_clarification(questions)` which raises `ClarificationNeeded`. The agent decides when to call this based on its system prompt guidance (a new instruction section tells it: "If the requirements are ambiguous, list your questions and call request_clarification").

### 3. Checkpoint extensions (`orchestrator.py` — `PipelineResult`)

New fields added to the checkpoint JSON:

```json
{
  "pending_clarification": {
    "stage": "pm",
    "questions": ["Q1: ...", "Q2: ..."],
    "question_comment_id": 12345678,
    "asked_at": "2026-04-19T17:30:00Z",
    "qa_rounds": 1
  },
  "clarification_history": [
    {
      "stage": "pm",
      "round": 1,
      "questions": ["Q1: ...", "Q2: ..."],
      "answers": ["A1: ...", "A2: ..."],
      "answered_at": "2026-04-19T18:00:00Z"
    }
  ]
}
```

### 4. Orchestrator pause logic (`orchestrator.py`)

When `_run_stage()` catches `ClarificationNeeded`:

1. Format questions as a GitHub comment with HTML marker:
   ```markdown
   <!-- ai-question:pm:round-1 -->
   🤖 **AI needs clarification before proceeding**
   
   Please answer the following questions by replying to this comment:
   
   **Q1:** What database should we use?
   **Q2:** Should endpoints be async?
   
   _Pipeline paused. I will resume automatically when you reply. If no answer is received within 24 hours, I will proceed with my best assumptions._
   ```
2. Save `pending_clarification` to checkpoint (including comment ID for later lookup).
3. Apply `agent-waiting` label, remove `agent-running`.
4. Exit the pipeline cleanly (no error).

### 5. Watcher resume logic (`watcher.py`)

On each cron run, after checking for new issues, the watcher also checks issues labelled `agent-waiting`:

1. Load the checkpoint to get `pending_clarification.question_comment_id` and `asked_at`.
2. Fetch comments from the GitHub issue API after the question comment.
3. **If a human reply exists** (any comment not from the bot, posted after the question comment):
   - Extract comment body as the answer.
   - Append to `clarification_history` in checkpoint.
   - Clear `pending_clarification`.
   - Remove `agent-waiting`, apply `agent-running`.
   - Resume pipeline — the interrupted stage re-runs with answers injected.
4. **If no reply and 24h elapsed:**
   - Add a comment: "No answer received. Proceeding with assumptions."
   - Clear `pending_clarification`, set `clarification_answers = []`.
   - Remove `agent-waiting`, apply `agent-running`.
   - Resume with a note in the injected context.
5. **If no reply and < 24h:** Do nothing, check again next cron run.

### 6. Answer injection (`orchestrator.py`)

Before re-running the interrupted stage, the orchestrator builds an answer context block from `clarification_history` and passes it to the agent via an additional system prompt section:

```
## Clarification Answers (from repository owner)

### Round 1
Q1: What database should we use?
A1: PostgreSQL, use the existing connection pool in db/connection.py.

Q2: Should endpoints be async?
A2: Yes, all endpoints should be async.
```

This is injected between the agent's role system prompt and the main task. The agent treats it as authoritative requirements.

---

## Data Flow

```
Cron → watcher.py
  ├─ New issues → dispatch pipeline (existing flow)
  └─ agent-waiting issues → check for answer
       ├─ Answer found → inject into checkpoint → resume orchestrator
       ├─ Timeout (24h) → proceed with assumptions → resume orchestrator
       └─ No answer yet → skip (check next cron run)

orchestrator.py (PM/Architect stage)
  ├─ Agent runs normally → stage completes → next stage
  └─ Agent raises ClarificationNeeded
       → post GitHub comment with questions
       → save to checkpoint
       → set agent-waiting label
       → exit pipeline (paused)

orchestrator.py (on resume)
  → load checkpoint, find clarification_history
  → build answer context block
  → re-run interrupted stage with answers injected
  → if ClarificationNeeded again (round < 3) → pause again
  → if round >= 3 → proceed with assumptions
```

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Agent asks questions > 3 times | Proceed with assumptions on round 4, log warning |
| GitHub comment post fails | Log error, still pause pipeline (watcher will retry on next run) |
| Answer comment deleted before watcher reads it | Treated as no answer; proceeds after 24h timeout |
| Pipeline killed while agent-waiting | Lock file removed, label stays as agent-waiting, cron resumes correctly |

---

## Files to Modify

| File | Changes |
|---|---|
| `orchestrator.py` | Add `ClarificationNeeded`, extend `PipelineResult`, catch in `_run_stage`, add pause/resume/inject logic |
| `agents/base_agent.py` | Add `request_clarification()` method |
| `agents/product_manager.py` | Add clarification instruction to system prompt + call logic |
| `agents/architect.py` | Add clarification instruction to system prompt + call logic |
| `watcher.py` | Add `agent-waiting` label constant, check waiting issues, detect answers, trigger resume |
| `config.yaml` | Add `agent-waiting` to label colour map |

---

## Testing

- Unit test: `ClarificationNeeded` raised → orchestrator posts comment, saves checkpoint, exits cleanly.
- Unit test: Watcher detects human comment after question → resumes with injected answers.
- Unit test: 24h timeout → proceeds with assumptions, correct context injected.
- Unit test: Round limit (3) → proceeds without further pausing.
- Integration test (manual): Create a `documentation` issue → PM asks questions → answer in GitHub → verify pipeline resumes and completes.
