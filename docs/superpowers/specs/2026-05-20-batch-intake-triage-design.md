# Batch Intake Triage — Design Spec
_Date: 2026-05-20_

## Problem

The current `news_triage` stage evaluates stories **one at a time** inside the pipeline. Editors never see stories relative to each other, cannot rank or compare them, and every story triggers its own LLM discussion even before it's known to be worth pursuing. As the volume of incoming items grows (news sources, future client requests), this becomes wasteful and produces lower-quality editorial decisions.

The same pattern applies beyond news: future client project requests arriving by email need a similar pre-screening layer before the expensive build pipeline runs.

## Goal

A **generic, reusable batch intake triage module** that:
1. Holds incoming items in a `triage-pending` state
2. Convenes an AI editorial/partner team to evaluate a batch together (with relative ranking)
3. Approves items into the normal pipeline or skips/closes them
4. Is opt-in per repo — **zero impact on existing pipelines when disabled**
5. Abstracts the issue tracker so GitHub (today) and JIRA (future) are interchangeable

---

## Architecture

### New Files

| File | Purpose |
|---|---|
| `intake_triage.py` | Standalone script. Cron-runnable + manual. Orchestrates the full batch triage flow. |
| `tracker_adapter.py` | Abstract `TrackerAdapter` base class + `GitHubTrackerAdapter` implementation. |
| `discussions/intake-triage.yaml` | Batch discussion preset. Presents N items together; emits per-item verdicts. |
| `tests/test_intake_triage.py` | Unit + integration tests. |

### Modified Files (minimal)

| File | Change |
|---|---|
| `orchestrator.py` | ~10 lines: `_stage_news_triage()` fast-passes if item already batch-triaged. |
| `config_schema.py` | Add `IntakeTriageConfig` Pydantic model. |
| `config.yaml` | Add `intake_triage:` section (disabled by default). |

---

## TrackerAdapter Interface

```python
@dataclass
class TriageItem:
    id: str           # issue number, ticket ID, etc.
    title: str
    body: str         # full content
    url: str
    created_at: datetime
    metadata: dict    # tracker-specific extras (labels, repo, etc.)

class TrackerAdapter(ABC):
    @abstractmethod
    def list_pending(self) -> list[TriageItem]:
        """Return all items currently in triage-pending state."""

    @abstractmethod
    def approve(self, item: TriageItem, notes: str) -> None:
        """Mark approved: post comment, transition to approved state, add trigger label."""

    @abstractmethod
    def skip(self, item: TriageItem, reason: str) -> None:
        """Mark skipped: post comment, close/archive item."""

    @abstractmethod
    def is_approved(self, item_id: str) -> tuple[bool, str]:
        """Check if item was already approved. Returns (approved, notes).
        Used by orchestrator's news_triage fast-pass."""
```

### GitHubTrackerAdapter (day 1)

- `list_pending()` → issues with label `triage-pending`
- `approve()` → remove `triage-pending`, add `triage-approved` + pipeline trigger label, post structured comment with editorial notes
- `skip()` → add `triage-skipped`, post comment with reason, close issue
- `is_approved()` → check labels on issue; extract notes from most recent triage comment

### JiraTrackerAdapter (future)

- `list_pending()` → JQL: `status = "Triage Pending"`
- `approve()` → transition to "Approved", add comment
- `skip()` → transition to "Won't Do", add comment, resolve
- `is_approved()` → check ticket status field

**Human override:** A human can manually add `triage-approved` label (GitHub) or transition status (JIRA). The system respects it automatically — no special handling needed.

---

## Trigger Logic

Four triggers, evaluated in order. All configurable. Any can be disabled by setting to `null`.

1. **`--run` flag** (manual) — fires unconditionally
2. **min_count** — fires when ≥ N items are pending
3. **max_age_hours** — fires when oldest pending item age ≥ N hours
4. **schedule** — fires when current time matches cron expression

If 0 items are pending, all triggers are skipped (no-op). If pending > `max_batch_size`, the oldest N items are processed and the remainder stays pending for the next run.

---

## Batch Discussion Format

### Context injected into discussion

```
## Pending Items for Editorial Review
Triage scope: {triage_scope}
Item count: 5

--- ITEM 1 ---
Title: Apple releases iOS 18.5 with new AI features
Source: 9to5mac.com
Summary: {first 300 chars of body}

--- ITEM 2 ---
...
```

Body is truncated to `body_preview_chars` (default 300) per item to keep context manageable.

### Verdict format (moderator final message)

```
ITEM 1: PUBLISH
NOTES: Focus on the on-device inference angle for HK enterprise users.

ITEM 2: SKIP
NOTES: Acquisition too US-centric, no HK/Asia angle.

ITEM 3: PUBLISH
NOTES: Lead with privacy implications for Cantonese readers.
```

Parsed by `_parse_batch_verdicts(text, item_count)` → list of `(verdict, notes)` tuples. Fail-open: any unparseable item defaults to PUBLISH.

### Future: Score mode

The verdict format and parser are designed for extension. When score mode is ready:
- Verdict line becomes: `ITEM 1: SCORE 7`
- Config: `verdict.mode: score`, `verdict.score_threshold: 6`
- Items scoring ≥ threshold → PUBLISH; below → SKIP
- No structural changes to `intake_triage.py` or the discussion preset needed

---

## Config Schema

```yaml
# config.yaml
intake_triage:
  enabled: false              # opt-in; false = zero impact on existing pipelines
  tracker: github             # or: jira (future)

  labels:
    pending:  triage-pending
    approved: triage-approved
    skipped:  triage-skipped
    trigger:  press            # label that the watcher watches for (added on approve)

  trigger:
    min_count: 5              # fire when ≥ N items pending
    max_age_hours: 6          # fire when oldest item ≥ N hours old
    schedule: "0 9 * * *"    # also fire at 9am daily (null = off)
    # manual: run `python intake_triage.py --run`

  batch:
    max_size: 10              # max items per triage session
    body_preview_chars: 300   # chars of body shown to editors per item

  discussion:
    preset: discussions/intake-triage.yaml

  verdict:
    mode: binary              # binary (now) | score (future)
    # score_threshold: 6      # future only
```

### `IntakeTriageConfig` (Pydantic)

```python
class IntakeTriggerConfig(BaseModel):
    min_count: Optional[int] = 5
    max_age_hours: Optional[float] = 6
    schedule: Optional[str] = None

class IntakeBatchConfig(BaseModel):
    max_size: int = 10
    body_preview_chars: int = 300

class IntakeVerdictConfig(BaseModel):
    mode: str = "binary"          # "binary" | "score"
    score_threshold: Optional[int] = None

class IntakeTriageConfig(BaseModel):
    enabled: bool = False
    tracker: str = "github"
    labels: dict = {"pending": "triage-pending", "approved": "triage-approved", "skipped": "triage-skipped", "trigger": "press"}
    trigger: IntakeTriggerConfig = IntakeTriggerConfig()
    batch: IntakeBatchConfig = IntakeBatchConfig()
    verdict: IntakeVerdictConfig = IntakeVerdictConfig()
    discussion: dict = {"preset": "discussions/intake-triage.yaml"}
    model_extra = "allow"
```

---

## Integration with Existing Pipeline

### Fast-pass in `_stage_news_triage()`

```python
def _stage_news_triage(self, result: PipelineResult) -> None:
    # Fast-pass if already batch-triaged
    if self._intake_triage_approved(result):
        log.info("news_triage: batch-approved, fast-pass")
        return  # editorial_verdict/notes already set

    # Original per-story triage (unchanged)
    ...

def _intake_triage_approved(self, result: PipelineResult) -> bool:
    adapter = self._get_tracker_adapter()   # None if intake_triage disabled
    if not adapter:
        return False
    approved, notes = adapter.is_approved(str(result.issue_number))
    if approved:
        result.editorial_verdict = "PUBLISH"
        result.editorial_notes   = notes
    return approved
```

### Behaviour by configuration

| State | Behaviour |
|---|---|
| `intake_triage.enabled: false` (default) | `_get_tracker_adapter()` returns None. Fast-pass never fires. Existing per-story triage runs identically to today. |
| `intake_triage.enabled: true`, item has `triage-approved` | Fast-pass. `editorial_verdict = PUBLISH`, notes from batch triage comment. |
| `intake_triage.enabled: true`, item not yet labelled | Falls through to per-story triage (safety net). |
| Human manually adds `triage-approved` | Same as batch-approved — fast-pass. |

`triage-skipped` items are closed by `intake_triage.py` before the watcher sees them and never enter the pipeline.

---

## CLI

```bash
# Normal cron run (respects trigger conditions)
python intake_triage.py

# Manual trigger — fires regardless of count/age/schedule
python intake_triage.py --run

# Dry run — shows what would happen, no write/state-changing API calls
python intake_triage.py --dry-run

# Custom config file
python intake_triage.py --config config.yaml
```

---

## Future Domains

The same module serves:

| Domain | Inbox | Triage team | Execute |
|---|---|---|---|
| ai-it-press (now) | RSS/news issues | Editorial director, audience specialist, news editor | Write + translate pipeline |
| ai-software-house (future) | Client project requests | Partner team roles | Build pipeline |

Each domain configures its own `discussions/intake-triage.yaml` preset, roles, trigger thresholds, and tracker labels. The `intake_triage.py` script and `TrackerAdapter` interface are shared unchanged.

---

## Out of Scope (this iteration)

- Score-based verdict mode (foundation laid in config schema; not implemented)
- JiraTrackerAdapter (interface defined; implementation deferred)
- UI/dashboard for pending items (GitHub Issues UI serves this role for now)
- Automatic `triage-pending` labelling from RSS watcher (currently manual or via RSS-to-issue scripts; not changed here)
