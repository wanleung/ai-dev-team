# Pipeline Progress Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Post a live pipeline-progress comment to each GitHub issue, updated as stages complete/fail/skip, with a configurable `summary` (one evolving comment) or `verbose` (per-stage comments) mode.

**Architecture:** A new `ProgressTracker` class (inline in `orchestrator.py`) manages stage state and GitHub comment posting. The orchestrator creates one instance per `run()` call and calls `mark_*()` hooks at each stage boundary. `GitHubClient` gains a `delete_issue_comment()` method. Mode is set via `pipeline.progress_tracker` config key.

**Tech Stack:** Python 3.11+, existing `GitHubClient`, `orchestrator.py` dataclasses, pytest + unittest.mock

---

## File Map

| File | Change |
|---|---|
| `github_client.py` | Add `delete_issue_comment()` |
| `orchestrator.py` | Add `ProgressStage` dataclass; `ProgressTracker` class; `progress_comment_id` field on `PipelineResult`; `_expected_stages()` on `Orchestrator`; tracker hooks in `run()`, `_prd_revision_loop()`, `_design_revision_loop()`, mode-driven loop; `progress_tracker_mode` param in `__init__` + `from_config()` |
| `config.yaml` | Add `pipeline.progress_tracker: summary` |
| `config.local.yaml` | Same |
| `tests/test_progress_tracker.py` | New test file |
| `tests/test_github_client_pr.py` | Add `delete_issue_comment` test |

---

## Task 1: `GitHubClient.delete_issue_comment()`

**Files:**
- Modify: `github_client.py` (after `add_issue_comment`, ~line 115)
- Modify: `tests/test_github_client_pr.py` (append at end)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_github_client_pr.py`:

```python
# ── delete_issue_comment ──────────────────────────────────────────────────────

def test_delete_issue_comment_calls_correct_endpoint(client):
    _mock_request(client, {})
    client.delete_issue_comment(99)
    client._request.assert_called_once_with("DELETE", "/repos/owner/repo/issues/comments/99")


def test_delete_issue_comment_ignores_404(client):
    """A 404 (already deleted) must not raise."""
    client._request = MagicMock(
        side_effect=RuntimeError("GitHub API DELETE ... failed [404]: Not Found")
    )
    # Should not raise
    client.delete_issue_comment(99)
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_github_client_pr.py::test_delete_issue_comment_calls_correct_endpoint tests/test_github_client_pr.py::test_delete_issue_comment_ignores_404 -v
```

Expected: `FAILED` — `AttributeError: 'GitHubClient' object has no attribute 'delete_issue_comment'`

- [ ] **Step 3: Implement `delete_issue_comment()`**

In `github_client.py`, add after `add_issue_comment()`:

```python
def delete_issue_comment(self, comment_id: int) -> None:
    """Delete a GitHub issue comment. Silently ignores 404 (already deleted)."""
    try:
        self._request("DELETE", f"/repos/{self.repo}/issues/comments/{comment_id}")
    except RuntimeError as exc:
        if "[404]" in str(exc):
            return
        raise
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_github_client_pr.py::test_delete_issue_comment_calls_correct_endpoint tests/test_github_client_pr.py::test_delete_issue_comment_ignores_404 -v
```

Expected: both `PASSED`

- [ ] **Step 5: Commit**

```bash
git add github_client.py tests/test_github_client_pr.py
git commit -m "feat: add GitHubClient.delete_issue_comment() with 404 tolerance"
```

---

## Task 2: `ProgressStage` dataclass + `ProgressTracker` class

**Files:**
- Modify: `orchestrator.py` — insert new classes before `class PipelineResult` (~line 123)
- Create: `tests/test_progress_tracker.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_progress_tracker.py`:

```python
"""Tests for ProgressTracker."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, call
from orchestrator import ProgressStage, ProgressTracker


# ── ProgressStage ──────────────────────────────────────────────────────────────

def test_progress_stage_defaults():
    s = ProgressStage(key="pm", label="📋 Product Manager")
    assert s.status == "pending"


# ── ProgressTracker — off mode ────────────────────────────────────────────────

def test_tracker_off_mode_is_noop():
    gh = MagicMock()
    t = ProgressTracker(github=gh, issue_number=1, mode="off")
    t.set_stages([ProgressStage("pm", "📋 PM")])
    t.mark_in_progress("pm")
    t.mark_done("pm")
    t.mark_failed("pm", "some error")
    t.mark_skipped("pm")
    gh.add_issue_comment.assert_not_called()
    gh.delete_issue_comment.assert_not_called()


# ── ProgressTracker — no github ───────────────────────────────────────────────

def test_tracker_none_github_is_noop():
    t = ProgressTracker(github=None, issue_number=1, mode="summary")
    t.set_stages([ProgressStage("pm", "📋 PM")])
    t.mark_done("pm")   # must not raise


def test_tracker_none_issue_number_is_noop():
    gh = MagicMock()
    t = ProgressTracker(github=gh, issue_number=None, mode="summary")
    t.set_stages([ProgressStage("pm", "📋 PM")])
    t.mark_done("pm")
    gh.add_issue_comment.assert_not_called()


# ── ProgressTracker — summary mode ───────────────────────────────────────────

def _make_tracker(mode="summary"):
    gh = MagicMock()
    gh.add_issue_comment.return_value = {"id": 42}
    t = ProgressTracker(github=gh, issue_number=7, mode=mode)
    stages = [
        ProgressStage("pm", "📋 Product Manager"),
        ProgressStage("architect", "🏗️ Architect"),
    ]
    t.set_stages(stages)
    return t, gh


def test_summary_set_stages_posts_initial_comment():
    t, gh = _make_tracker()
    gh.add_issue_comment.assert_called_once()
    body = gh.add_issue_comment.call_args[0][1]
    assert "⬜ 📋 Product Manager" in body
    assert "⬜ 🏗️ Architect" in body
    assert t.comment_id == 42


def test_summary_mark_in_progress_updates_comment():
    t, gh = _make_tracker()
    gh.add_issue_comment.reset_mock()
    gh.add_issue_comment.return_value = {"id": 43}
    t.mark_in_progress("pm")
    body = gh.add_issue_comment.call_args[0][1]
    assert "🔄 📋 Product Manager" in body
    gh.delete_issue_comment.assert_called_once_with(42)
    assert t.comment_id == 43


def test_summary_mark_done_shows_checkmark():
    t, gh = _make_tracker()
    gh.add_issue_comment.return_value = {"id": 44}
    t.mark_done("pm")
    body = gh.add_issue_comment.call_args[0][1]
    assert "✅ 📋 Product Manager" in body


def test_summary_mark_failed_shows_error():
    t, gh = _make_tracker()
    gh.add_issue_comment.return_value = {"id": 45}
    t.mark_failed("architect", "LLM returned empty")
    body = gh.add_issue_comment.call_args[0][1]
    assert "❌ 🏗️ Architect" in body
    assert "LLM returned empty" in body


def test_summary_mark_skipped_shows_skip_icon():
    t, gh = _make_tracker()
    gh.add_issue_comment.return_value = {"id": 46}
    t.mark_skipped("pm")
    body = gh.add_issue_comment.call_args[0][1]
    assert "⏭️ 📋 Product Manager" in body


def test_summary_unknown_key_is_noop():
    """mark_* with an unknown stage key must not raise."""
    t, gh = _make_tracker()
    t.mark_done("nonexistent_key")   # should not raise or post


def test_summary_add_stage_appended_to_list():
    t, gh = _make_tracker()
    gh.add_issue_comment.return_value = {"id": 50}
    t.add_stage(ProgressStage("design_revision_1", "🔄 Design Revision 1"))
    body = gh.add_issue_comment.call_args[0][1]
    assert "⬜ 🔄 Design Revision 1" in body


def test_summary_restore_sets_comment_id_without_posting():
    t, gh = _make_tracker()
    gh.add_issue_comment.reset_mock()
    t.restore(99)
    assert t.comment_id == 99
    gh.add_issue_comment.assert_not_called()


# ── ProgressTracker — verbose mode ───────────────────────────────────────────

def test_verbose_mark_in_progress_posts_starting_comment():
    t, gh = _make_tracker(mode="verbose")
    gh.add_issue_comment.reset_mock()
    t.mark_in_progress("pm")
    body = gh.add_issue_comment.call_args[0][1]
    assert "🔄" in body
    assert "Product Manager" in body


def test_verbose_mark_done_posts_done_comment():
    t, gh = _make_tracker(mode="verbose")
    gh.add_issue_comment.reset_mock()
    t.mark_done("pm")
    body = gh.add_issue_comment.call_args[0][1]
    assert "✅" in body
    assert "Product Manager" in body


def test_verbose_mark_failed_posts_failed_comment():
    t, gh = _make_tracker(mode="verbose")
    gh.add_issue_comment.reset_mock()
    t.mark_failed("pm", "out of memory")
    body = gh.add_issue_comment.call_args[0][1]
    assert "❌" in body
    assert "out of memory" in body


def test_verbose_does_not_delete_comments():
    t, gh = _make_tracker(mode="verbose")
    t.mark_in_progress("pm")
    t.mark_done("pm")
    gh.delete_issue_comment.assert_not_called()


# ── Error resilience ──────────────────────────────────────────────────────────

def test_summary_github_error_does_not_raise():
    """A GitHub error during post must be silently swallowed."""
    gh = MagicMock()
    gh.add_issue_comment.side_effect = RuntimeError("502 Server Error")
    t = ProgressTracker(github=gh, issue_number=7, mode="summary")
    t.set_stages([ProgressStage("pm", "📋 PM")])   # must not raise
    t.mark_done("pm")                               # must not raise
```

- [ ] **Step 2: Run tests to confirm they all fail**

```bash
python -m pytest tests/test_progress_tracker.py -v 2>&1 | head -30
```

Expected: `ImportError` — `cannot import name 'ProgressStage' from 'orchestrator'`

- [ ] **Step 3: Implement `ProgressStage` and `ProgressTracker`**

In `orchestrator.py`, find the line `@dataclass` before `class PipelineResult` (~line 123) and insert the following **before** it:

```python
@dataclass
class ProgressStage:
    """One stage entry in the pipeline progress tracker."""
    key: str
    label: str
    status: str = "pending"   # pending | in_progress | done | failed | skipped


class ProgressTracker:
    """Posts and updates a pipeline-progress comment on a GitHub issue.

    Modes:
        summary  — one comment, deleted and re-posted on every state change.
        verbose  — individual comment per state transition (no deletes).
        off      — all methods are no-ops.
    """

    _ICONS = {
        "pending":     "⬜",
        "in_progress": "🔄",
        "done":        "✅",
        "failed":      "❌",
        "skipped":     "⏭️",
    }

    def __init__(self, github, issue_number: Optional[int], mode: str) -> None:
        self.github = github
        self.issue_number = issue_number
        self.mode = mode          # "summary" | "verbose" | "off"
        self.stages: list[ProgressStage] = []
        self.comment_id: Optional[int] = None

    # ── Public API ────────────────────────────────────────────────────────

    def set_stages(self, stages: list[ProgressStage]) -> None:
        """Set the full ordered list of expected stages and post the initial comment."""
        self.stages = list(stages)
        if self.mode == "summary":
            self._post_summary()

    def add_stage(self, stage: ProgressStage) -> None:
        """Append a dynamic stage (e.g. revision rounds) and refresh the comment."""
        self.stages.append(stage)
        if self.mode == "summary":
            self._post_summary()

    def restore(self, comment_id: Optional[int]) -> None:
        """On checkpoint resume — reuse the existing comment_id without re-posting."""
        if comment_id:
            self.comment_id = comment_id

    def mark_in_progress(self, key: str) -> None:
        self._set_status(key, "in_progress")
        if self.mode == "verbose":
            label = self._label(key)
            self._safe_post(f"🔄 **{label}** — starting…")

    def mark_done(self, key: str) -> None:
        self._set_status(key, "done")
        if self.mode == "verbose":
            label = self._label(key)
            self._safe_post(f"✅ **{label}** — complete")

    def mark_failed(self, key: str, error: str = "") -> None:
        self._set_status(key, "failed", error=error)
        if self.mode == "verbose":
            label = self._label(key)
            msg = f"❌ **{label}** — failed"
            if error:
                msg += f": {error}"
            self._safe_post(msg)

    def mark_skipped(self, key: str) -> None:
        self._set_status(key, "skipped")
        if self.mode == "verbose":
            label = self._label(key)
            self._safe_post(f"⏭️ **{label}** — skipped")

    # ── Internals ─────────────────────────────────────────────────────────

    def _set_status(self, key: str, status: str, error: str = "") -> None:
        for stage in self.stages:
            if stage.key == key:
                stage.status = status
                if error:
                    stage.error = error
                if self.mode == "summary":
                    self._post_summary()
                return
        # Unknown key — ignore silently

    def _label(self, key: str) -> str:
        for stage in self.stages:
            if stage.key == key:
                return stage.label
        return key

    def _render(self) -> str:
        lines = ["## 🤖 Pipeline Progress\n"]
        for stage in self.stages:
            icon = self._ICONS.get(stage.status, "⬜")
            line = f"- {icon} {stage.label}"
            if stage.status == "failed" and getattr(stage, "error", ""):
                line += f" — {stage.error}"
            lines.append(line)
        return "\n".join(lines)

    def _post_summary(self) -> None:
        if not self.github or not self.issue_number:
            return
        self._safe_delete()
        resp = self._safe_add(self._render())
        if resp:
            self.comment_id = resp.get("id")

    def _safe_delete(self) -> None:
        if self.comment_id and self.github:
            try:
                self.github.delete_issue_comment(self.comment_id)
            except Exception as exc:
                log.warning("ProgressTracker: failed to delete comment %s: %s", self.comment_id, exc)

    def _safe_add(self, body: str) -> Optional[dict]:
        try:
            return self.github.add_issue_comment(self.issue_number, body)
        except Exception as exc:
            log.warning("ProgressTracker: failed to post comment: %s", exc)
            return None

    def _safe_post(self, body: str) -> None:
        """Verbose-mode single comment post."""
        if not self.github or not self.issue_number:
            return
        self._safe_add(body)
```

Note: `log` is already imported in `orchestrator.py` (`import logging; log = logging.getLogger(__name__)`). Verify with `grep -n "^log = \|^import logging" orchestrator.py`.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_progress_tracker.py -v
```

Expected: all `PASSED`

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py tests/test_progress_tracker.py
git commit -m "feat: add ProgressStage dataclass and ProgressTracker class"
```

---

## Task 3: Add `progress_comment_id` to `PipelineResult`

**Files:**
- Modify: `orchestrator.py` — `PipelineResult` dataclass, `to_dict()`, `from_dict()`
- Modify: `tests/test_prd_design_loops.py` — append new test

- [ ] **Step 1: Write the failing test**

Append to `tests/test_prd_design_loops.py`:

```python
def test_pipeline_result_progress_comment_id_default():
    r = PipelineResult(requirement="x")
    assert r.progress_comment_id is None


def test_pipeline_result_progress_comment_id_round_trips():
    r = PipelineResult(requirement="x")
    r.progress_comment_id = 12345
    data = r.to_dict()
    r2 = PipelineResult.from_dict(data)
    assert r2.progress_comment_id == 12345
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_prd_design_loops.py::test_pipeline_result_progress_comment_id_default tests/test_prd_design_loops.py::test_pipeline_result_progress_comment_id_round_trips -v
```

Expected: `FAILED` — `AttributeError: 'PipelineResult' object has no attribute 'progress_comment_id'`

- [ ] **Step 3: Add field to `PipelineResult`**

In `orchestrator.py`, find the `PipelineResult` dataclass field block. Add after `next_label`:

```python
progress_comment_id: Optional[int] = None
```

In `to_dict()`, add inside the return dict (after `"next_label": self.next_label,`):

```python
"progress_comment_id": self.progress_comment_id,
```

In `from_dict()`, add `"progress_comment_id"` to the list of keys in the `for key in [...]` loop.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_prd_design_loops.py::test_pipeline_result_progress_comment_id_default tests/test_prd_design_loops.py::test_pipeline_result_progress_comment_id_round_trips -v
```

Expected: both `PASSED`

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py tests/test_prd_design_loops.py
git commit -m "feat: add progress_comment_id field to PipelineResult"
```

---

## Task 4: `progress_tracker_mode` config + `_expected_stages()`

**Files:**
- Modify: `orchestrator.py` — `__init__()`, `from_config()`, new `_expected_stages()` method
- Modify: `tests/test_prd_design_loops.py` — append tests

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_prd_design_loops.py`:

```python
def test_orchestrator_progress_tracker_mode_default():
    o = Orchestrator.__new__(Orchestrator)
    o.progress_tracker_mode = "summary"
    assert o.progress_tracker_mode == "summary"


def test_from_config_reads_progress_tracker_key(tmp_path, monkeypatch):
    import yaml
    cfg = {
        "llm": {"model": "gpt-4.1"},
        "github": {"repo": "", "use_github": False},
        "team": {},
        "pipeline": {"progress_tracker": "verbose"},
    }
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(cfg))
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    o = Orchestrator.from_config(str(cfg_file))
    assert o.progress_tracker_mode == "verbose"


def test_from_config_progress_tracker_defaults_to_summary(tmp_path, monkeypatch):
    import yaml
    cfg = {
        "llm": {"model": "gpt-4.1"},
        "github": {"repo": "", "use_github": False},
        "team": {},
        "pipeline": {},
    }
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(cfg))
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    o = Orchestrator.from_config(str(cfg_file))
    assert o.progress_tracker_mode == "summary"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_prd_design_loops.py::test_from_config_reads_progress_tracker_key tests/test_prd_design_loops.py::test_from_config_progress_tracker_defaults_to_summary -v
```

Expected: `FAILED` — `AttributeError: 'Orchestrator' object has no attribute 'progress_tracker_mode'`

- [ ] **Step 3: Add param to `__init__()` and `from_config()`**

In `Orchestrator.__init__()`, add parameter after `pipeline_yaml_stages`:

```python
progress_tracker_mode: str = "summary",
```

And in the body of `__init__()`, add:

```python
self.progress_tracker_mode = progress_tracker_mode
```

In `from_config()`, pass the value in the `Orchestrator(...)` constructor call (after `pipeline_yaml_stages=pipeline_yaml_stages,`):

```python
progress_tracker_mode=pipeline.get("progress_tracker", "summary"),
```

- [ ] **Step 4: Add `_expected_stages()` helper**

In `orchestrator.py`, add this method to `Orchestrator` (near the other helpers, e.g. after `_build_stage_list`):

```python
def _expected_stages(self) -> list[ProgressStage]:
    """Return the ordered list of stages expected for this pipeline run.

    Revision rounds (prd_revision_N, design_revision_N) are excluded here —
    they are added dynamically via tracker.add_stage() as they actually begin.
    """
    stages: list[ProgressStage] = []

    if getattr(self, '_pipeline_yaml_stages', None) is None:
        # Standard pipeline: fixed PM + Arch loops first
        stages += [
            ProgressStage("pm",                "📋 Product Manager"),
            ProgressStage("pm_reviewer",       "🔎 PM Reviewer"),
            ProgressStage("pm_review_loop",    "✔️  PRD Approved"),
            ProgressStage("architect",         "🏗️  Architect"),
            ProgressStage("architect_reviewer","🔎 Architect Reviewer"),
            ProgressStage("architect_review_loop", "✔️  Design Approved"),
        ]

    # Mode-driven stages (engineer, reviewer, QA, etc.)
    for stage in self._build_stage_list():
        stages.append(ProgressStage(stage.checkpoint_key, stage.label))

    return stages
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_prd_design_loops.py::test_from_config_reads_progress_tracker_key tests/test_prd_design_loops.py::test_from_config_progress_tracker_defaults_to_summary -v
```

Expected: both `PASSED`

- [ ] **Step 6: Smoke-test import**

```bash
python -c "from orchestrator import Orchestrator, ProgressTracker, ProgressStage; print('OK')"
```

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add orchestrator.py tests/test_prd_design_loops.py
git commit -m "feat: add progress_tracker_mode config + _expected_stages() helper"
```

---

## Task 5: Wire tracker into `run()` — init, resume, and mode-driven loop

**Files:**
- Modify: `orchestrator.py` — `run()` method

- [ ] **Step 1: Locate insertion points in `run()`**

```bash
grep -n "result = PipelineResult\|result = self._load_checkpoint\|for stage in self._build_stage_list\|result.completed_stages.append(stage\|self._run_stage(stage" /home/wanleung/Projects/ai-software-house/orchestrator.py | head -20
```

Note the exact line numbers before proceeding.

- [ ] **Step 2: Add tracker initialisation after checkpoint load**

Find this block in `run()` (around line 1671):
```python
        else:
            result = PipelineResult(requirement=requirement)
```

Replace it with:
```python
        else:
            result = PipelineResult(requirement=requirement)

        # ── Progress tracker ───────────────────────────────────────────────────
        self._tracker = ProgressTracker(
            github=self.github,
            issue_number=result.issue_number,
            mode=self.progress_tracker_mode,
        )
        self._tracker.set_stages(self._expected_stages())
        if result.progress_comment_id:
            # Resuming: reuse existing comment slot; replay completed stages as done
            self._tracker.restore(result.progress_comment_id)
            for key in result.completed_stages:
                self._tracker._set_status(key, "done")
        # Keep result in sync with tracker's comment_id
        result.progress_comment_id = self._tracker.comment_id
```

- [ ] **Step 3: Hook tracker into the mode-driven stage loop**

Find this block in `run()` (around line 1715):
```python
        for stage in self._build_stage_list():
            # Checkpoint resume: skip if already completed
            if stage.checkpoint_key in result.completed_stages or stage.name in result.completed_stages:
                console.print(f"  ⏭️  [dim]{stage.label} — skipped (checkpoint)[/dim]")
                continue

            # Conditional skip
            if stage.skip_if(result):
                console.print(f"  ⏭️  [dim]{stage.label} — skipped[/dim]")
                continue

            if stage.loop_stages:
                ok = self._run_loop_stage(stage, result)
                if not ok:
                    self._save_checkpoint(result)
                    return self._finish(result, start_time)
            else:
                self._run_stage(stage.label, stage.description, result, lambda s=stage: s.fn(result))

                if result.errors:
                    self._save_checkpoint(result)
                    return self._finish(result, start_time)

            if stage.name == "senior_engineer":
                result.completed_stages.append("engineer")

            result.completed_stages.append(stage.checkpoint_key)
            self._save_checkpoint(result)

            if stage.stop_if(result):
                if stage.stop_message:
                    console.print(f"[bold red]{stage.stop_message}[/bold red]")
                return self._finish(result, start_time)
```

Replace with:
```python
        for stage in self._build_stage_list():
            # Checkpoint resume: skip if already completed
            if stage.checkpoint_key in result.completed_stages or stage.name in result.completed_stages:
                console.print(f"  ⏭️  [dim]{stage.label} — skipped (checkpoint)[/dim]")
                self._tracker.mark_skipped(stage.checkpoint_key)
                continue

            # Conditional skip
            if stage.skip_if(result):
                console.print(f"  ⏭️  [dim]{stage.label} — skipped[/dim]")
                self._tracker.mark_skipped(stage.checkpoint_key)
                continue

            self._tracker.mark_in_progress(stage.checkpoint_key)

            if stage.loop_stages:
                ok = self._run_loop_stage(stage, result)
                if not ok:
                    self._tracker.mark_failed(stage.checkpoint_key)
                    result.progress_comment_id = self._tracker.comment_id
                    self._save_checkpoint(result)
                    return self._finish(result, start_time)
            else:
                self._run_stage(stage.label, stage.description, result, lambda s=stage: s.fn(result))

                if result.errors:
                    self._tracker.mark_failed(stage.checkpoint_key, result.errors[-1])
                    result.progress_comment_id = self._tracker.comment_id
                    self._save_checkpoint(result)
                    return self._finish(result, start_time)

            if stage.name == "senior_engineer":
                result.completed_stages.append("engineer")

            result.completed_stages.append(stage.checkpoint_key)
            self._tracker.mark_done(stage.checkpoint_key)
            result.progress_comment_id = self._tracker.comment_id
            self._save_checkpoint(result)

            if stage.stop_if(result):
                if stage.stop_message:
                    console.print(f"[bold red]{stage.stop_message}[/bold red]")
                return self._finish(result, start_time)
```

- [ ] **Step 4: Verify syntax**

```bash
python -c "import orchestrator; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Run existing tests to catch regressions**

```bash
python -m pytest tests/test_pipeline_modes.py tests/test_prd_design_loops.py tests/test_progress_tracker.py -v --tb=short 2>&1 | tail -20
```

Expected: all `PASSED`

- [ ] **Step 6: Commit**

```bash
git add orchestrator.py
git commit -m "feat: wire ProgressTracker into run() — init, resume, mode-driven loop"
```

---

## Task 6: Wire tracker into `_prd_revision_loop()`

**Files:**
- Modify: `orchestrator.py` — `_prd_revision_loop()`

- [ ] **Step 1: Add hooks**

Find `_prd_revision_loop()` (~line 1850). Apply the following changes:

**Before each `_run_stage` call for PM**, add `self._tracker.mark_in_progress("pm")`. After the `result.completed_stages.append("pm")` line, add:
```python
self._tracker.mark_done("pm")
result.progress_comment_id = self._tracker.comment_id
```

**Before the `_run_stage` call for PM Reviewer**, add `self._tracker.mark_in_progress("pm_reviewer")`. After `result.completed_stages.append("pm_reviewer")`:
```python
self._tracker.mark_done("pm_reviewer")
result.progress_comment_id = self._tracker.comment_id
```

**On the `if result.errors` blocks after pm and pm_reviewer**, add before `return False`:
```python
self._tracker.mark_failed("pm", result.errors[-1])   # or "pm_reviewer"
result.progress_comment_id = self._tracker.comment_id
```

**For each revision round**, before the architect `_run_stage`:
```python
self._tracker.add_stage(ProgressStage(key, f"🔄 PRD Revision {round_num}"))
self._tracker.mark_in_progress(key)
```
After `result.completed_stages.append(key)`:
```python
self._tracker.mark_done(key)
result.progress_comment_id = self._tracker.comment_id
```

**At the final approved block** (after `result.completed_stages.append("pm_review_loop")`):
```python
self._tracker.mark_done("pm_review_loop")
result.progress_comment_id = self._tracker.comment_id
```

- [ ] **Step 2: Verify syntax**

```bash
python -c "import orchestrator; print('OK')"
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_prd_design_loops.py tests/test_progress_tracker.py -v --tb=short 2>&1 | tail -20
```

Expected: all `PASSED`

- [ ] **Step 4: Commit**

```bash
git add orchestrator.py
git commit -m "feat: wire ProgressTracker hooks into _prd_revision_loop()"
```

---

## Task 7: Wire tracker into `_design_revision_loop()`

**Files:**
- Modify: `orchestrator.py` — `_design_revision_loop()`

- [ ] **Step 1: Add hooks** (same pattern as Task 6, for architect stages)

Find `_design_revision_loop()` (~line 1991). Apply the following changes:

**Before `_run_stage` for Architect**, add `self._tracker.mark_in_progress("architect")`. After `result.completed_stages.append("architect")`:
```python
self._tracker.mark_done("architect")
result.progress_comment_id = self._tracker.comment_id
```

**On error after architect**, before `return False`:
```python
self._tracker.mark_failed("architect", result.errors[-1])
result.progress_comment_id = self._tracker.comment_id
```

**Before `_run_stage` for Architect Reviewer**, add `self._tracker.mark_in_progress("architect_reviewer")`. After `result.completed_stages.append("architect_reviewer")`:
```python
self._tracker.mark_done("architect_reviewer")
result.progress_comment_id = self._tracker.comment_id
```

**On error after architect_reviewer**, before `return False`:
```python
self._tracker.mark_failed("architect_reviewer", result.errors[-1])
result.progress_comment_id = self._tracker.comment_id
```

**For each revision round**, before the first `_run_stage`:
```python
self._tracker.add_stage(ProgressStage(key, f"🔄 Design Revision {round_num}"))
self._tracker.mark_in_progress(key)
```
After `result.completed_stages.append(key)`:
```python
self._tracker.mark_done(key)
result.progress_comment_id = self._tracker.comment_id
```

**At the final `result.completed_stages.append("architect_review_loop")`** (all paths that reach it), add after:
```python
self._tracker.mark_done("architect_review_loop")
result.progress_comment_id = self._tracker.comment_id
```

- [ ] **Step 2: Verify syntax**

```bash
python -c "import orchestrator; print('OK')"
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_prd_design_loops.py tests/test_progress_tracker.py -v --tb=short 2>&1 | tail -20
```

Expected: all `PASSED`

- [ ] **Step 4: Commit**

```bash
git add orchestrator.py
git commit -m "feat: wire ProgressTracker hooks into _design_revision_loop()"
```

---

## Task 8: Update config files and run full test suite

**Files:**
- Modify: `config.yaml`
- Modify: `config.local.yaml`

- [ ] **Step 1: Add config key to `config.yaml`**

Find the `pipeline:` section in `config.yaml`. Add:
```yaml
  # Progress tracker mode: summary (one live comment), verbose (per-stage comments), off
  progress_tracker: summary
```

- [ ] **Step 2: Add config key to `config.local.yaml`**

Find the `pipeline:` section in `config.local.yaml`. Add:
```yaml
  progress_tracker: summary
```

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short -q 2>&1 | tail -30
```

Expected: all existing tests pass + new progress tracker tests pass. No regressions.

- [ ] **Step 4: Commit and push**

```bash
git add config.yaml config.local.yaml
git commit -m "config: add pipeline.progress_tracker setting (default: summary)"
git push origin master
git push public master
```
