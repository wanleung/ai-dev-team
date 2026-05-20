# Batch Intake Triage — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone `intake_triage.py` script that holds incoming GitHub issues in a `triage-pending` state, convenes a batch AI editorial discussion across all pending items, and approves or skips each one before the main pipeline runs — with zero impact on repos that don't enable it.

**Architecture:** A new `intake_triage.py` script (cron + manual) uses a `TrackerAdapter` interface (GitHub first) to list, approve, and skip items. It calls `DiscussionAgent` in standalone context mode to run a single discussion for the whole batch. The only change to existing code is a ~10-line fast-pass guard in `_stage_news_triage()` and new Pydantic config models.

**Tech Stack:** Python 3.11+, Pydantic v2, `requests`, existing `DiscussionAgent` (standalone `context=` mode), `croniter` (schedule trigger), pytest.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `config_schema.py` | Modify | Add `IntakeTriggerConfig`, `IntakeBatchConfig`, `IntakeVerdictConfig`, `IntakeTriageConfig`; add `intake_triage` field to `AppConfig` |
| `config.yaml` | Modify | Add `intake_triage:` section (disabled by default) |
| `tracker_adapter.py` | Create | `TriageItem` dataclass, `TrackerAdapter` ABC, `GitHubTrackerAdapter` |
| `discussions/intake-triage.yaml` | Create | Batch discussion preset (roles, rounds, verdict format) |
| `intake_triage.py` | Create | Main script: trigger evaluation, batch build, run discussion, parse verdicts, apply via adapter, CLI |
| `orchestrator.py` | Modify | Add `_intake_triage_approved()` + `_get_tracker_adapter()` fast-pass in `_stage_news_triage()` |
| `tests/test_intake_triage.py` | Create | All unit tests for Tasks 1–5 |
| `tests/test_news_stages.py` | Modify | Add fast-pass tests for Task 6 |

---

### Task 1: Config Schema

**Files:**
- Modify: `config_schema.py` (after line ~170, before `AppConfig`)
- Modify: `config.yaml` (add `intake_triage:` section at end)
- Modify: `tests/test_intake_triage.py` (create file)

- [ ] **Step 1: Write failing tests**

Create `tests/test_intake_triage.py`:

```python
"""Tests for intake triage config schema, tracker adapter, verdict parser, and main script."""
from __future__ import annotations
import pytest
from config_schema import AppConfig, IntakeTriageConfig, load_config
import yaml, tempfile, os


# ── Task 1: Config schema ──────────────────────────────────────────────────

def test_intake_triage_config_defaults():
    cfg = IntakeTriageConfig()
    assert cfg.enabled is False
    assert cfg.tracker == "github"
    assert cfg.labels["pending"] == "triage-pending"
    assert cfg.labels["approved"] == "triage-approved"
    assert cfg.labels["skipped"] == "triage-skipped"
    assert cfg.labels["trigger"] == "press"
    assert cfg.trigger.min_count == 5
    assert cfg.trigger.max_age_hours == 6
    assert cfg.trigger.schedule is None
    assert cfg.batch.max_size == 10
    assert cfg.batch.body_preview_chars == 300
    assert cfg.verdict.mode == "binary"
    assert cfg.verdict.score_threshold is None


def test_app_config_accepts_intake_triage():
    raw = {"llm": {"model": "gpt-4.1"}, "intake_triage": {"enabled": True, "trigger": {"min_count": 3}}}
    cfg = AppConfig(**raw)
    assert cfg.intake_triage.enabled is True
    assert cfg.intake_triage.trigger.min_count == 3


def test_app_config_intake_triage_disabled_by_default():
    cfg = AppConfig(**{"llm": {"model": "gpt-4.1"}})
    assert cfg.intake_triage is not None
    assert cfg.intake_triage.enabled is False


def test_intake_triage_config_from_yaml():
    content = """
llm:
  model: gpt-4.1
intake_triage:
  enabled: true
  labels:
    pending: triage-pending
    approved: triage-approved
    skipped: triage-skipped
    trigger: ai-press
  trigger:
    min_count: 3
    max_age_hours: 12
    schedule: "0 8 * * *"
  batch:
    max_size: 5
    body_preview_chars: 200
  verdict:
    mode: binary
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(content)
        f.flush()
        cfg = load_config(f.name)
    os.unlink(f.name)
    assert cfg.intake_triage.enabled is True
    assert cfg.intake_triage.labels["trigger"] == "ai-press"
    assert cfg.intake_triage.trigger.min_count == 3
    assert cfg.intake_triage.batch.max_size == 5
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /path/to/ai-software-house && python -m pytest tests/test_intake_triage.py::test_intake_triage_config_defaults -v
```
Expected: FAIL with `ImportError: cannot import name 'IntakeTriageConfig'`

- [ ] **Step 3: Add config models to `config_schema.py`**

Add after the `PressConfig` class (around line 173, before `AppConfig`):

```python
# ── intake triage config ──────────────────────────────────────────────────────

class IntakeTriggerConfig(BaseModel):
    model_config = {"extra": "allow"}

    min_count: Optional[int] = 5
    max_age_hours: Optional[float] = 6.0
    schedule: Optional[str] = None


class IntakeBatchConfig(BaseModel):
    model_config = {"extra": "allow"}

    max_size: int = 10
    body_preview_chars: int = 300


class IntakeVerdictConfig(BaseModel):
    model_config = {"extra": "allow"}

    mode: str = "binary"
    score_threshold: Optional[int] = None


class IntakeTriageConfig(BaseModel):
    model_config = {"extra": "allow"}

    enabled: bool = False
    tracker: str = "github"
    labels: Dict[str, str] = Field(
        default_factory=lambda: {
            "pending":  "triage-pending",
            "approved": "triage-approved",
            "skipped":  "triage-skipped",
            "trigger":  "press",
        }
    )
    trigger: IntakeTriggerConfig = Field(default_factory=IntakeTriggerConfig)
    batch: IntakeBatchConfig = Field(default_factory=IntakeBatchConfig)
    verdict: IntakeVerdictConfig = Field(default_factory=IntakeVerdictConfig)
    discussion: Dict[str, Any] = Field(
        default_factory=lambda: {"preset": "discussions/intake-triage.yaml"}
    )
```

Then add `intake_triage` to `AppConfig`:

```python
class AppConfig(BaseModel):
    model_config = {"extra": "forbid"}
    # ... existing fields ...
    press: Optional[PressConfig] = None
    intake_triage: IntakeTriageConfig = Field(default_factory=IntakeTriageConfig)  # add this line
```

- [ ] **Step 4: Add `intake_triage:` to `config.yaml`**

Add at the end of `config.yaml`:

```yaml
# ── Batch Intake Triage ───────────────────────────────────────────────────────
# Pre-pipeline batch triage: holds items in triage-pending until editors
# vote on the whole batch. Disabled by default; zero impact when off.
intake_triage:
  enabled: false              # flip to true to activate

  tracker: github             # github | jira (future)

  labels:
    pending:  triage-pending
    approved: triage-approved
    skipped:  triage-skipped
    trigger:  press            # label the watcher watches for (added on approve)

  trigger:
    min_count: 5              # fire when >= N items have triage-pending label
    max_age_hours: 6          # fire when oldest triage-pending item >= N hours old
    schedule: null            # cron expression e.g. "0 9 * * *", null = off

  batch:
    max_size: 10              # max items per session (overflow stays pending)
    body_preview_chars: 300   # chars of body shown to editors per item

  discussion:
    preset: discussions/intake-triage.yaml

  verdict:
    mode: binary              # binary (PUBLISH/SKIP) | score (future)
    # score_threshold: 6      # future: items scoring >= this -> PUBLISH
```

- [ ] **Step 5: Run tests to verify passing**

```bash
python -m pytest tests/test_intake_triage.py -k "config" -v
```
Expected: 4 tests PASS

- [ ] **Step 6: Run full suite for regressions**

```bash
python -m pytest --tb=short -q 2>&1 | tail -5
```
Expected: same pass count as before (1604), 0 new failures

- [ ] **Step 7: Commit**

```bash
git add config_schema.py config.yaml tests/test_intake_triage.py
git commit -m "feat(intake-triage): add IntakeTriageConfig schema and config.yaml section"
```

---

### Task 2: TrackerAdapter + GitHubTrackerAdapter

**Files:**
- Create: `tracker_adapter.py`
- Modify: `tests/test_intake_triage.py` (append tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_intake_triage.py`:

```python
# ── Task 2: TrackerAdapter ─────────────────────────────────────────────────

from tracker_adapter import TriageItem, TrackerAdapter, GitHubTrackerAdapter
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock


def _make_item(n: int = 1) -> TriageItem:
    return TriageItem(
        id=str(n),
        title=f"Story {n}",
        body="Body content here",
        url=f"https://github.com/org/repo/issues/{n}",
        created_at=datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc),
        metadata={"number": n, "labels": ["triage-pending"]},
    )


def test_triage_item_fields():
    item = _make_item(42)
    assert item.id == "42"
    assert item.title == "Story 42"
    assert item.created_at.tzinfo is not None


def test_tracker_adapter_is_abstract():
    """TrackerAdapter cannot be instantiated directly."""
    with pytest.raises(TypeError):
        TrackerAdapter()


def test_github_adapter_list_pending_empty():
    mock_resp = MagicMock()
    mock_resp.json.return_value = []
    mock_resp.raise_for_status = MagicMock()
    with patch("tracker_adapter.requests.get", return_value=mock_resp):
        adapter = GitHubTrackerAdapter(
            repo="org/repo",
            token="test-token",
            pending_label="triage-pending",
            approved_label="triage-approved",
            skipped_label="triage-skipped",
            trigger_label="press",
        )
        result = adapter.list_pending()
    assert result == []


def test_github_adapter_list_pending_returns_items():
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {
            "number": 5,
            "title": "Big story",
            "body": "Some body text",
            "html_url": "https://github.com/org/repo/issues/5",
            "created_at": "2026-05-20T08:00:00Z",
            "labels": [{"name": "triage-pending"}],
        }
    ]
    mock_resp.raise_for_status = MagicMock()
    with patch("tracker_adapter.requests.get", return_value=mock_resp):
        adapter = GitHubTrackerAdapter(
            repo="org/repo", token="t", pending_label="triage-pending",
            approved_label="triage-approved", skipped_label="triage-skipped",
            trigger_label="press",
        )
        items = adapter.list_pending()
    assert len(items) == 1
    assert items[0].id == "5"
    assert items[0].title == "Big story"


def test_github_adapter_is_approved_false_when_label_absent():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"labels": [{"name": "triage-pending"}], "body": "x"}
    mock_resp.raise_for_status = MagicMock()
    with patch("tracker_adapter.requests.get", return_value=mock_resp):
        adapter = GitHubTrackerAdapter(
            repo="org/repo", token="t", pending_label="triage-pending",
            approved_label="triage-approved", skipped_label="triage-skipped",
            trigger_label="press",
        )
        approved, notes = adapter.is_approved("5")
    assert approved is False
    assert notes == ""


def test_github_adapter_is_approved_true_when_label_present():
    issue_resp = MagicMock()
    issue_resp.json.return_value = {"labels": [{"name": "triage-approved"}]}
    issue_resp.raise_for_status = MagicMock()
    comments_resp = MagicMock()
    comments_resp.json.return_value = [
        {"body": "[INTAKE TRIAGE]\nVERDICT: PUBLISH\nNOTES: Focus on HK angle."}
    ]
    comments_resp.raise_for_status = MagicMock()
    with patch("tracker_adapter.requests.get", side_effect=[issue_resp, comments_resp]):
        adapter = GitHubTrackerAdapter(
            repo="org/repo", token="t", pending_label="triage-pending",
            approved_label="triage-approved", skipped_label="triage-skipped",
            trigger_label="press",
        )
        approved, notes = adapter.is_approved("5")
    assert approved is True
    assert "HK angle" in notes
```

- [ ] **Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_intake_triage.py -k "tracker or triage_item or adapter" -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'tracker_adapter'`

- [ ] **Step 3: Create `tracker_adapter.py`**

```python
"""tracker_adapter.py — Abstract tracker interface and GitHub implementation.

Defines TriageItem, TrackerAdapter ABC, and GitHubTrackerAdapter.
Future: JiraTrackerAdapter follows the same interface.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests


TRIAGE_COMMENT_MARKER = "[INTAKE TRIAGE]"
_NOTES_RE = re.compile(r"NOTES:\s*(.+)", re.DOTALL)


@dataclass
class TriageItem:
    id: str
    title: str
    body: str
    url: str
    created_at: datetime
    metadata: dict = field(default_factory=dict)


class TrackerAdapter(ABC):
    @abstractmethod
    def list_pending(self) -> list[TriageItem]:
        """Return all items currently in triage-pending state."""

    @abstractmethod
    def approve(self, item: TriageItem, notes: str) -> None:
        """Mark approved: post comment, add approved + trigger labels, remove pending label."""

    @abstractmethod
    def skip(self, item: TriageItem, reason: str) -> None:
        """Mark skipped: post comment, add skipped label, close item."""

    @abstractmethod
    def is_approved(self, item_id: str) -> tuple[bool, str]:
        """Return (approved, editorial_notes). Used by orchestrator fast-pass."""


class GitHubTrackerAdapter(TrackerAdapter):
    """GitHub Issues implementation of TrackerAdapter."""

    def __init__(
        self,
        repo: str,
        token: str,
        pending_label: str = "triage-pending",
        approved_label: str = "triage-approved",
        skipped_label: str = "triage-skipped",
        trigger_label: str = "press",
    ) -> None:
        self.repo = repo
        self._token = token
        self.pending_label = pending_label
        self.approved_label = approved_label
        self.skipped_label = skipped_label
        self.trigger_label = trigger_label

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _api(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"https://api.github.com{path}"
        resp = requests.request(method, url, headers=self._headers(), timeout=15, **kwargs)
        resp.raise_for_status()
        return resp

    def list_pending(self) -> list[TriageItem]:
        resp = requests.get(
            f"https://api.github.com/repos/{self.repo}/issues",
            headers=self._headers(),
            params={"state": "open", "labels": self.pending_label, "per_page": 100},
            timeout=15,
        )
        resp.raise_for_status()
        items = []
        for issue in resp.json():
            if "pull_request" in issue:
                continue
            created_at = datetime.fromisoformat(
                issue["created_at"].replace("Z", "+00:00")
            )
            items.append(TriageItem(
                id=str(issue["number"]),
                title=issue.get("title", ""),
                body=issue.get("body") or "",
                url=issue.get("html_url", ""),
                created_at=created_at,
                metadata={
                    "number": issue["number"],
                    "labels": [l["name"] for l in issue.get("labels", [])],
                },
            ))
        return items

    def approve(self, item: TriageItem, notes: str) -> None:
        number = item.id
        comment = (
            f"{TRIAGE_COMMENT_MARKER}\n"
            f"VERDICT: PUBLISH\n"
            f"NOTES: {notes}\n\n"
            "_Batch intake triage approved this story for the pipeline._"
        )
        try:
            self._api("POST", f"/repos/{self.repo}/issues/{number}/comments",
                      json={"body": comment})
        except Exception:
            pass  # comment failure must not block label transition
        self._api("POST", f"/repos/{self.repo}/issues/{number}/labels",
                  json={"labels": [self.approved_label, self.trigger_label]})
        try:
            self._api("DELETE",
                      f"/repos/{self.repo}/issues/{number}/labels/{self.pending_label}")
        except Exception:
            pass  # label may already be absent

    def skip(self, item: TriageItem, reason: str) -> None:
        number = item.id
        comment = (
            f"{TRIAGE_COMMENT_MARKER}\n"
            f"VERDICT: SKIP\n"
            f"NOTES: {reason}\n\n"
            "_Batch intake triage skipped this story. Issue closed._"
        )
        try:
            self._api("POST", f"/repos/{self.repo}/issues/{number}/comments",
                      json={"body": comment})
        except Exception:
            pass
        self._api("POST", f"/repos/{self.repo}/issues/{number}/labels",
                  json={"labels": [self.skipped_label]})
        try:
            self._api("PATCH", f"/repos/{self.repo}/issues/{number}",
                      json={"state": "closed", "state_reason": "not_planned"})
        except Exception:
            pass
        try:
            self._api("DELETE",
                      f"/repos/{self.repo}/issues/{number}/labels/{self.pending_label}")
        except Exception:
            pass

    def is_approved(self, item_id: str) -> tuple[bool, str]:
        resp = requests.get(
            f"https://api.github.com/repos/{self.repo}/issues/{item_id}",
            headers=self._headers(),
            timeout=15,
        )
        resp.raise_for_status()
        issue = resp.json()
        label_names = {l["name"] for l in issue.get("labels", [])}
        if self.approved_label not in label_names:
            return False, ""
        # fetch notes from most recent INTAKE TRIAGE comment
        try:
            cr = requests.get(
                f"https://api.github.com/repos/{self.repo}/issues/{item_id}/comments",
                headers=self._headers(),
                params={"per_page": 100},
                timeout=15,
            )
            cr.raise_for_status()
            for comment in reversed(cr.json()):
                body = comment.get("body", "")
                if TRIAGE_COMMENT_MARKER in body:
                    m = _NOTES_RE.search(body)
                    if m:
                        return True, m.group(1).strip().splitlines()[0]
        except Exception:
            pass
        return True, ""
```

- [ ] **Step 4: Run tests to verify passing**

```bash
python -m pytest tests/test_intake_triage.py -k "tracker or triage_item or adapter" -v
```
Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tracker_adapter.py tests/test_intake_triage.py
git commit -m "feat(intake-triage): add TriageItem, TrackerAdapter ABC, GitHubTrackerAdapter"
```

---

### Task 3: Batch Verdict Parser + Discussion Preset

**Files:**
- Create: `discussions/intake-triage.yaml`
- Modify: `tests/test_intake_triage.py` (append tests)
- Note: `_parse_batch_verdicts` will live in `intake_triage.py` (created in Task 4); tests are written now, implementation lands in Task 4 Step 3.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_intake_triage.py`:

```python
# ── Task 3: Batch verdict parser ───────────────────────────────────────────

from intake_triage import _parse_batch_verdicts


def test_parse_batch_verdicts_all_publish():
    text = (
        "ITEM 1: PUBLISH\nNOTES: Focus on HK angle.\n\n"
        "ITEM 2: PUBLISH\nNOTES: Strong security story.\n"
    )
    results = _parse_batch_verdicts(text, item_count=2)
    assert results == [("PUBLISH", "Focus on HK angle."), ("PUBLISH", "Strong security story.")]


def test_parse_batch_verdicts_mixed():
    text = (
        "ITEM 1: PUBLISH\nNOTES: Lead with Cantonese angle.\n\n"
        "ITEM 2: SKIP\nNOTES: No HK relevance.\n\n"
        "ITEM 3: PUBLISH\nNOTES: Strong enterprise angle.\n"
    )
    results = _parse_batch_verdicts(text, item_count=3)
    assert results[0] == ("PUBLISH", "Lead with Cantonese angle.")
    assert results[1] == ("SKIP", "No HK relevance.")
    assert results[2] == ("PUBLISH", "Strong enterprise angle.")


def test_parse_batch_verdicts_fail_open_on_missing():
    """Missing items default to PUBLISH (fail-open)."""
    text = "ITEM 1: PUBLISH\nNOTES: Good.\n"
    results = _parse_batch_verdicts(text, item_count=3)
    assert results[0] == ("PUBLISH", "Good.")
    assert results[1] == ("PUBLISH", "")   # missing → fail-open
    assert results[2] == ("PUBLISH", "")   # missing → fail-open


def test_parse_batch_verdicts_skip_all():
    text = "ITEM 1: SKIP\nNOTES: Not relevant.\n\nITEM 2: SKIP\nNOTES: Old news.\n"
    results = _parse_batch_verdicts(text, item_count=2)
    assert results == [("SKIP", "Not relevant."), ("SKIP", "Old news.")]


def test_parse_batch_verdicts_case_insensitive_verdict():
    text = "ITEM 1: publish\nNOTES: ok\n"
    results = _parse_batch_verdicts(text, item_count=1)
    assert results[0][0] == "PUBLISH"


def test_parse_batch_verdicts_notes_optional():
    """NOTES line is optional — verdict still parsed."""
    text = "ITEM 1: PUBLISH\n\nITEM 2: SKIP\n"
    results = _parse_batch_verdicts(text, item_count=2)
    assert results[0] == ("PUBLISH", "")
    assert results[1] == ("SKIP", "")


def test_parse_batch_verdicts_empty_text():
    results = _parse_batch_verdicts("", item_count=2)
    assert results == [("PUBLISH", ""), ("PUBLISH", "")]
```

- [ ] **Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_intake_triage.py -k "parse_batch_verdicts" -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'intake_triage'`

- [ ] **Step 3: Create `discussions/intake-triage.yaml`**

```yaml
# discussions/intake-triage.yaml
# Batch intake triage discussion — editors vote on a batch of pending items.
#
# Called by intake_triage.py with standalone context= mode.
# Context is a pre-formatted list of all pending items (see _build_batch_context).

topic: >
  Batch editorial triage: review the pending items below and vote PUBLISH or SKIP
  for each one. Consider relative importance, audience fit, and news value.
  An item that might pass in isolation may still be SKIP if better items are present.

max_rounds: 2
early_exit: CONSENSUS_REACHED

participants:
  - role: editorial_director
    persona_file: roles/editorial_director.md
    homework_llm: "ollama/thinker"

  - role: audience_specialist
    persona_file: roles/audience_specialist.md
    homework_llm: "ollama/thinker"

  - role: news_editor
    persona_file: roles/news_editor.md

homework_round: true

moderator:
  persona_file: roles/moderator.md

output_mode: synthesis

verdict_format: |
  At the end of your final synthesis, include a verdict block for EVERY item,
  using exactly this format (one block per item, in order):

  ITEM 1: PUBLISH
  NOTES: <one sentence: the angle or focus the writer should take>

  ITEM 2: SKIP
  NOTES: <one sentence: why this story was skipped>

  Only PUBLISH and SKIP are valid verdicts. Every item must have a verdict.
```

- [ ] **Step 4: Note — `_parse_batch_verdicts` will be implemented in Task 4 Step 2. Proceed to Task 4.**

---

### Task 4: `intake_triage.py` — Core Script

**Files:**
- Create: `intake_triage.py`
- Modify: `tests/test_intake_triage.py` (append tests)

Install `croniter` if not present:
```bash
pip install croniter && pip freeze | grep croniter >> requirements.txt
```

- [ ] **Step 1: Write failing tests for trigger logic and batch builder**

Append to `tests/test_intake_triage.py`:

```python
# ── Task 4: intake_triage.py ───────────────────────────────────────────────

from intake_triage import (
    _parse_batch_verdicts,
    _build_batch_context,
    _should_fire,
)
from datetime import datetime, timezone, timedelta


def _make_items(n: int, age_hours: float = 1.0) -> list:
    now = datetime.now(timezone.utc)
    return [
        TriageItem(
            id=str(i),
            title=f"Story {i}",
            body=f"Body for story {i} " * 20,
            url=f"https://github.com/org/repo/issues/{i}",
            created_at=now - timedelta(hours=age_hours),
            metadata={},
        )
        for i in range(1, n + 1)
    ]


def test_should_fire_manual_flag():
    from config_schema import IntakeTriageConfig
    cfg = IntakeTriageConfig(trigger={"min_count": 10, "max_age_hours": 24})
    items = _make_items(1, age_hours=0.5)
    assert _should_fire(cfg, items, force=True) is True


def test_should_fire_min_count_reached():
    from config_schema import IntakeTriageConfig
    cfg = IntakeTriageConfig(trigger={"min_count": 3, "max_age_hours": 24})
    items = _make_items(3, age_hours=1)
    assert _should_fire(cfg, items, force=False) is True


def test_should_fire_min_count_not_reached():
    from config_schema import IntakeTriageConfig
    cfg = IntakeTriageConfig(trigger={"min_count": 5, "max_age_hours": 24})
    items = _make_items(2, age_hours=1)
    assert _should_fire(cfg, items, force=False) is False


def test_should_fire_max_age_exceeded():
    from config_schema import IntakeTriageConfig
    cfg = IntakeTriageConfig(trigger={"min_count": 10, "max_age_hours": 6})
    items = _make_items(1, age_hours=7)  # 7 > 6 → fire
    assert _should_fire(cfg, items, force=False) is True


def test_should_fire_no_items():
    from config_schema import IntakeTriageConfig
    cfg = IntakeTriageConfig(trigger={"min_count": 1, "max_age_hours": 1})
    assert _should_fire(cfg, [], force=False) is False


def test_build_batch_context_format():
    items = _make_items(2, age_hours=1)
    items[0].title = "Apple releases iOS 19"
    items[0].body = "A" * 400  # will be truncated to 300
    items[1].title = "Google acquires startup"
    items[1].body = "B" * 100
    ctx = _build_batch_context(items, scope="AI and HK tech", preview_chars=300)
    assert "ITEM 1" in ctx
    assert "Apple releases iOS 19" in ctx
    assert "ITEM 2" in ctx
    assert "Google acquires startup" in ctx
    assert "A" * 301 not in ctx   # truncated
    assert "AI and HK tech" in ctx


def test_build_batch_context_item_count():
    items = _make_items(3)
    ctx = _build_batch_context(items, scope="tech", preview_chars=300)
    assert "Item count: 3" in ctx
```

- [ ] **Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_intake_triage.py -k "should_fire or build_batch_context" -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'intake_triage'`

- [ ] **Step 3: Create `intake_triage.py`**

```python
"""intake_triage.py — Batch intake triage for ai-software-house.

Holds incoming items (GitHub issues with triage-pending label) until a trigger
condition fires, then convenes a batch AI editorial discussion and votes
PUBLISH or SKIP on each item.

Usage:
    python intake_triage.py              # normal cron run (respects trigger conditions)
    python intake_triage.py --run        # manual trigger, ignores min_count/max_age
    python intake_triage.py --dry-run    # preview only, no API calls
    python intake_triage.py --config repos.yaml
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config_schema import load_config, IntakeTriageConfig
from tracker_adapter import TrackerAdapter, TriageItem, GitHubTrackerAdapter

log = logging.getLogger("intake_triage")

_ITEM_VERDICT_RE = re.compile(
    r"ITEM\s+(\d+):\s*(PUBLISH|SKIP)\s*\nNOTES:\s*(.+?)(?=\n\nITEM\s+\d+:|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_ITEM_VERDICT_NO_NOTES_RE = re.compile(
    r"ITEM\s+(\d+):\s*(PUBLISH|SKIP)",
    re.IGNORECASE,
)


def _parse_batch_verdicts(text: str, item_count: int) -> list[tuple[str, str]]:
    """Parse moderator synthesis into per-item (verdict, notes) tuples.

    Fail-open: any unparseable or missing item defaults to ("PUBLISH", "").
    """
    results: dict[int, tuple[str, str]] = {}

    # Try to extract NOTES lines first
    for m in _ITEM_VERDICT_RE.finditer(text):
        idx = int(m.group(1))
        verdict = m.group(2).upper()
        notes = m.group(3).strip().splitlines()[0].strip()
        results[idx] = (verdict, notes)

    # Fall back to verdict-only lines for items not yet parsed
    for m in _ITEM_VERDICT_NO_NOTES_RE.finditer(text):
        idx = int(m.group(1))
        if idx not in results:
            results[idx] = (m.group(2).upper(), "")

    return [(results.get(i, ("PUBLISH", ""))) for i in range(1, item_count + 1)]


def _build_batch_context(
    items: list[TriageItem],
    scope: str,
    preview_chars: int = 300,
) -> str:
    """Build the context string for the batch discussion."""
    lines = [
        "## Pending Items for Editorial Review",
        f"Triage scope: {scope}",
        f"Item count: {len(items)}",
        "",
    ]
    for i, item in enumerate(items, 1):
        preview = item.body[:preview_chars]
        if len(item.body) > preview_chars:
            preview += "..."
        lines += [
            f"--- ITEM {i} ---",
            f"Title: {item.title}",
            f"URL: {item.url}",
            f"Summary: {preview}",
            "",
        ]
    return "\n".join(lines)


def _should_fire(
    cfg: IntakeTriageConfig,
    items: list[TriageItem],
    force: bool = False,
) -> bool:
    """Return True if the triage session should run now."""
    if not items:
        return False
    if force:
        return True
    trigger = cfg.trigger
    if trigger.min_count is not None and len(items) >= trigger.min_count:
        return True
    if trigger.max_age_hours is not None and items:
        oldest = min(items, key=lambda x: x.created_at)
        age = (datetime.now(timezone.utc) - oldest.created_at).total_seconds() / 3600
        if age >= trigger.max_age_hours:
            return True
    if trigger.schedule:
        try:
            from croniter import croniter
            now = datetime.now(timezone.utc)
            # Fire if the schedule matched within the last 65 minutes (cron run window)
            cron = croniter(trigger.schedule, now)
            prev = cron.get_prev(datetime)
            if (now - prev).total_seconds() <= 65 * 60:
                return True
        except Exception:
            log.warning("intake_triage: could not evaluate schedule '%s'", trigger.schedule)
    return False


def _make_adapter(cfg: IntakeTriageConfig, repo: str) -> TrackerAdapter:
    if cfg.tracker != "github":
        raise NotImplementedError(f"Tracker '{cfg.tracker}' not yet implemented")
    token = os.environ.get("GITHUB_TOKEN", "")
    return GitHubTrackerAdapter(
        repo=repo,
        token=token,
        pending_label=cfg.labels.get("pending", "triage-pending"),
        approved_label=cfg.labels.get("approved", "triage-approved"),
        skipped_label=cfg.labels.get("skipped", "triage-skipped"),
        trigger_label=cfg.labels.get("trigger", "press"),
    )


def run(
    cfg: IntakeTriageConfig,
    repo: str,
    model: str = "gpt-4.1",
    force: bool = False,
    dry_run: bool = False,
    script_dir: Optional[Path] = None,
) -> dict:
    """Run one intake triage cycle. Returns summary dict."""
    if script_dir is None:
        script_dir = Path(__file__).parent

    adapter = _make_adapter(cfg, repo)
    items = adapter.list_pending()
    log.info("intake_triage: %d item(s) pending", len(items))

    if not _should_fire(cfg, items, force=force):
        log.info("intake_triage: trigger conditions not met, skipping")
        return {"fired": False, "pending": len(items)}

    # Slice to max_batch_size, oldest first
    max_size = cfg.batch.max_size
    items.sort(key=lambda x: x.created_at)
    batch = items[:max_size]
    log.info("intake_triage: processing batch of %d item(s)", len(batch))

    # Get triage scope from config
    scope = getattr(cfg, "scope", None)
    if not scope:
        # fall back to press triage scope if present in config
        scope = "Tech news relevant to HK Cantonese-speaking professionals."

    context = _build_batch_context(batch, scope=scope, preview_chars=cfg.batch.body_preview_chars)

    if dry_run:
        log.info("intake_triage: --dry-run, would process %d items:\n%s", len(batch), context)
        return {"fired": True, "dry_run": True, "batch_size": len(batch)}

    # Run discussion
    preset_path = script_dir / cfg.discussion.get("preset", "discussions/intake-triage.yaml")
    from agents.discussion_agent import DiscussionAgent
    agent = DiscussionAgent.from_file(
        config_path=str(preset_path),
        model=model,
        github_token=os.environ.get("GITHUB_TOKEN", ""),
    )
    disc_result = agent.run(context=context)
    synthesis = disc_result.synthesis or disc_result.transcript or ""

    verdicts = _parse_batch_verdicts(synthesis, item_count=len(batch))

    approved, skipped = [], []
    for item, (verdict, notes) in zip(batch, verdicts):
        if verdict == "SKIP":
            log.info("intake_triage: SKIP item %s — %s", item.id, notes)
            try:
                adapter.skip(item, reason=notes)
            except Exception as exc:
                log.warning("intake_triage: failed to skip item %s: %s", item.id, exc)
            skipped.append(item.id)
        else:
            log.info("intake_triage: PUBLISH item %s — %s", item.id, notes)
            try:
                adapter.approve(item, notes=notes)
            except Exception as exc:
                log.warning("intake_triage: failed to approve item %s: %s", item.id, exc)
            approved.append(item.id)

    log.info("intake_triage: done. approved=%d skipped=%d", len(approved), len(skipped))
    return {"fired": True, "approved": approved, "skipped": skipped}


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch intake triage runner")
    parser.add_argument("--run", action="store_true", help="Force run ignoring trigger conditions")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no API calls")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--repo", default=None, help="GitHub repo (owner/name), overrides config")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    cfg_path = Path(args.config)
    if not cfg_path.is_file():
        print(f"ERROR: config file not found: {cfg_path}", file=sys.stderr)
        sys.exit(1)

    app_cfg = load_config(str(cfg_path))
    intake_cfg = app_cfg.intake_triage

    if not intake_cfg.enabled and not args.run:
        log.info("intake_triage: disabled in config (use --run to force)")
        return

    repo = args.repo or (app_cfg.github.repo if app_cfg.github else "")
    if not repo:
        print("ERROR: no repo configured (set github.repo in config.yaml or use --repo)", file=sys.stderr)
        sys.exit(1)

    model = app_cfg.llm.model
    run(intake_cfg, repo=repo, model=model, force=args.run, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all Task 3+4 tests**

```bash
python -m pytest tests/test_intake_triage.py -k "parse_batch_verdicts or should_fire or build_batch_context" -v
```
Expected: 15 tests PASS

- [ ] **Step 5: Run full suite for regressions**

```bash
python -m pytest --tb=short -q 2>&1 | tail -5
```
Expected: same pass count as before, 0 new failures

- [ ] **Step 6: Commit**

```bash
git add intake_triage.py discussions/intake-triage.yaml tests/test_intake_triage.py
git commit -m "feat(intake-triage): add intake_triage.py, batch verdict parser, discussion preset"
```

---

### Task 5: Orchestrator Fast-Pass

**Files:**
- Modify: `orchestrator.py` (inside `_stage_news_triage()` and add two helper methods)
- Modify: `tests/test_news_stages.py` (append 3 tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_news_stages.py`:

```python
# ── intake triage fast-pass tests ─────────────────────────────────────────

def _make_triage_orch_with_intake(approved: bool, notes: str = ""):
    """Orchestrator with intake_triage enabled and mocked adapter."""
    from unittest.mock import MagicMock, patch
    from orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.model = "gpt-4.1"
    orch.model_overrides = {}
    orch._stage_timeouts = {}
    orch._discussions_dir = None
    orch._cfg = {"intake_triage": {"enabled": True}}
    orch.github = MagicMock()
    orch.target_github = MagicMock()

    mock_adapter = MagicMock()
    mock_adapter.is_approved.return_value = (approved, notes)
    orch._cached_tracker_adapter = mock_adapter
    return orch


def test_news_triage_fast_pass_when_batch_approved():
    """If triage-approved label present, news_triage sets PUBLISH and returns early."""
    orch = _make_triage_orch_with_intake(approved=True, notes="Focus on HK angle.")
    result = MagicMock()
    result.issue_number = 42
    result.editorial_verdict = None
    result.editorial_notes = ""

    with patch.object(orch, "_stage_discuss") as mock_discuss:
        orch._stage_news_triage(result)

    mock_discuss.assert_not_called()
    assert result.editorial_verdict == "PUBLISH"
    assert result.editorial_notes == "Focus on HK angle."


def test_news_triage_no_fast_pass_when_not_approved():
    """If triage-approved absent, falls through to per-story triage."""
    orch = _make_triage_orch_with_intake(approved=False)
    result = MagicMock()
    result.issue_number = 43
    result.editorial_verdict = None
    result.editorial_notes = ""
    result.errors = []

    with patch.object(orch, "_stage_discuss") as mock_discuss:
        with patch.object(orch, "_parse_triage_verdict", return_value={"verdict": "PUBLISH", "notes": ""}):
            orch._stage_news_triage(result)

    mock_discuss.assert_called_once()


def test_news_triage_fast_pass_disabled_when_no_adapter():
    """When intake_triage is disabled (no adapter), per-story triage always runs."""
    from orchestrator import Orchestrator
    from unittest.mock import MagicMock, patch
    orch = Orchestrator.__new__(Orchestrator)
    orch.model = "gpt-4.1"
    orch.model_overrides = {}
    orch._stage_timeouts = {}
    orch._discussions_dir = None
    orch._cfg = {}   # no intake_triage key
    orch.github = MagicMock()
    orch.target_github = MagicMock()
    orch._cached_tracker_adapter = None

    result = MagicMock()
    result.issue_number = 44
    result.editorial_verdict = None
    result.editorial_notes = ""
    result.errors = []

    with patch.object(orch, "_stage_discuss") as mock_discuss:
        with patch.object(orch, "_parse_triage_verdict", return_value={"verdict": "PUBLISH", "notes": ""}):
            orch._stage_news_triage(result)

    mock_discuss.assert_called_once()
```

- [ ] **Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_news_stages.py -k "fast_pass" -v
```
Expected: FAIL (attribute errors on `_cached_tracker_adapter`)

- [ ] **Step 3: Add fast-pass methods to `orchestrator.py`**

Find `_stage_news_triage` (around line 4254). Add two helper methods just before it:

```python
def _get_tracker_adapter(self):
    """Return a TrackerAdapter if intake_triage is enabled, else None.

    Result is cached on self._cached_tracker_adapter to avoid repeated
    config lookups within a pipeline run.
    """
    if hasattr(self, "_cached_tracker_adapter"):
        return self._cached_tracker_adapter
    cfg_dict = getattr(self, "_cfg", {})
    it_cfg = cfg_dict.get("intake_triage", {}) if isinstance(cfg_dict, dict) else {}
    if not it_cfg.get("enabled", False):
        self._cached_tracker_adapter = None
        return None
    try:
        from config_schema import IntakeTriageConfig
        from tracker_adapter import GitHubTrackerAdapter
        import os
        it = IntakeTriageConfig(**it_cfg)
        gh = getattr(self, "github", None) or getattr(self, "target_github", None)
        repo = str(getattr(gh, "repo", "")) if gh else ""
        token = os.environ.get("GITHUB_TOKEN", "")
        adapter = GitHubTrackerAdapter(
            repo=repo,
            token=token,
            pending_label=it.labels.get("pending", "triage-pending"),
            approved_label=it.labels.get("approved", "triage-approved"),
            skipped_label=it.labels.get("skipped", "triage-skipped"),
            trigger_label=it.labels.get("trigger", "press"),
        )
        self._cached_tracker_adapter = adapter
    except Exception as exc:
        log.warning("_get_tracker_adapter: failed to build adapter: %s", exc)
        self._cached_tracker_adapter = None
    return self._cached_tracker_adapter

def _intake_triage_approved(self, result: "PipelineResult") -> bool:
    """Check if item was already approved by batch intake triage.

    Sets result.editorial_verdict and result.editorial_notes if approved.
    Returns True if fast-pass should apply.
    """
    adapter = self._get_tracker_adapter()
    if adapter is None:
        return False
    try:
        approved, notes = adapter.is_approved(str(result.issue_number))
    except Exception as exc:
        log.warning("_intake_triage_approved: adapter error (%s) — proceeding with per-story triage", exc)
        return False
    if approved:
        result.editorial_verdict = "PUBLISH"
        result.editorial_notes = notes
    return approved
```

Then at the top of `_stage_news_triage`, add the fast-pass guard:

```python
def _stage_news_triage(self, result: "PipelineResult") -> None:
    # ── Fast-pass if already approved by batch intake triage ─────────────
    if self._intake_triage_approved(result):
        log.info("news_triage: batch intake triage already approved this item — fast-pass")
        return

    # ── Original per-story triage (unchanged below) ───────────────────────
    ... (rest of existing method unchanged)
```

- [ ] **Step 4: Run fast-pass tests**

```bash
python -m pytest tests/test_news_stages.py -k "fast_pass" -v
```
Expected: 3 tests PASS

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest --tb=short -q 2>&1 | tail -5
```
Expected: existing 1604 + 3 new = 1607 passing, 0 new failures

- [ ] **Step 6: Commit**

```bash
git add orchestrator.py tests/test_news_stages.py
git commit -m "feat(intake-triage): add fast-pass in _stage_news_triage via _intake_triage_approved"
```

---

### Task 6: Full Test Suite + PR

**Files:**
- Review all test files

- [ ] **Step 1: Run complete test suite**

```bash
python -m pytest --tb=short -q 2>&1 | tail -10
```
Expected: ≥1607 passing. Note the pre-existing failure `test_full_qa_round_trip` — this is known and unrelated.

- [ ] **Step 2: Verify intake_triage.py help and dry-run**

```bash
python intake_triage.py --help
python intake_triage.py --dry-run --config config.yaml 2>&1 | head -5
```
Expected: help text printed; dry-run exits cleanly (may log "disabled in config").

- [ ] **Step 3: Check config.yaml loads cleanly**

```bash
python -c "from config_schema import load_config; c = load_config('config.yaml'); print('intake_triage.enabled =', c.intake_triage.enabled)"
```
Expected: `intake_triage.enabled = False`

- [ ] **Step 4: Push branch and open PR**

```bash
git push -u origin HEAD

gh pr create \
  --title "feat: batch intake triage module" \
  --body "$(cat <<'EOF'
## Summary

- New standalone \`intake_triage.py\` script: holds issues in \`triage-pending\` state, runs a batch AI editorial discussion (all items in one context), then approves or skips each via GitHub labels
- New \`tracker_adapter.py\`: \`TrackerAdapter\` ABC + \`GitHubTrackerAdapter\` (JIRA-ready interface)
- New \`discussions/intake-triage.yaml\`: batch triage discussion preset (3 editors, 2 rounds, per-item PUBLISH/SKIP verdicts)
- 4 configurable triggers: min item count, max item age, cron schedule, manual \`--run\` flag
- Opt-in via \`intake_triage.enabled: true\` in config.yaml — **zero impact on existing pipelines when disabled**
- Fast-pass in \`_stage_news_triage()\`: skips per-story triage if batch already approved the item

## Test Plan
- [ ] All new tests pass (\`tests/test_intake_triage.py\`, fast-pass in \`tests/test_news_stages.py\`)
- [ ] Full suite: no regressions (pre-existing \`test_full_qa_round_trip\` failure is unrelated)
- [ ] \`python intake_triage.py --dry-run\` exits cleanly
- [ ] \`config.yaml\` loads with \`intake_triage.enabled = False\` by default

## Spec
\`docs/superpowers/specs/2026-05-20-batch-intake-triage-design.md\`
EOF
)"
```

---

## Cron Setup (after merge)

Add to crontab to run every 30 minutes:
```bash
*/30 * * * * cd /path/to/ai-software-house && source venv/bin/activate && python intake_triage.py >> logs/intake_triage/cron.log 2>&1
```
