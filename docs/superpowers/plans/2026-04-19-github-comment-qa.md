# GitHub Comment Q&A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow PM and Architect agents to pause the pipeline, post clarifying questions to the GitHub issue, and resume automatically when the repository owner replies.

**Architecture:** `ClarificationNeeded` exception propagates from agent → orchestrator, which posts a formatted GitHub comment, saves state to the checkpoint, and switches the issue to `agent-waiting`. The watcher polls waiting issues each cron run, detects human replies (or 24 h timeout), writes answers into the checkpoint, and re-dispatches the pipeline. On resume the orchestrator injects the Q&A history as extra context into the interrupted stage.

**Tech Stack:** Python 3.13, GitHub REST API (`github_client.py`), existing checkpoint JSON format (extended), `requests` (already a dep), `pytest` for tests.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `orchestrator.py` | Modify | Add `ClarificationNeeded`, extend `PipelineResult`, pause/resume/inject logic |
| `agents/base_agent.py` | Modify | Add `request_clarification()` method |
| `roles/product_manager.md` | Modify | Clarification instruction block |
| `roles/architect.md` | Modify | Clarification instruction block |
| `watcher.py` | Modify | `LABEL_WAITING`, `check_waiting_issues()`, `_update_checkpoint_with_answer()` |
| `tests/test_qa_clarification.py` | Create | All unit tests for the Q&A feature |

---

### Task 1: `ClarificationNeeded` exception + `PipelineResult` extensions

**Files:**
- Modify: `orchestrator.py` (near top, after imports, before `PipelineResult`)

- [ ] **Step 1.1: Write the failing tests**

Create `tests/test_qa_clarification.py`:

```python
"""Tests for GitHub Comment Q&A clarification feature."""
import json
from dataclasses import field
from unittest.mock import MagicMock, patch

import pytest

from orchestrator import ClarificationNeeded, PipelineResult


def test_clarification_needed_stores_questions():
    exc = ClarificationNeeded(["Q1: What DB?", "Q2: Async?"])
    assert exc.questions == ["Q1: What DB?", "Q2: Async?"]


def test_clarification_needed_is_exception():
    exc = ClarificationNeeded(["Q1"])
    assert isinstance(exc, Exception)


def test_pipeline_result_has_pending_clarification_default():
    r = PipelineResult(requirement="test")
    assert r.pending_clarification is None


def test_pipeline_result_has_clarification_history_default():
    r = PipelineResult(requirement="test")
    assert r.clarification_history == []


def test_pipeline_result_to_dict_includes_qa_fields():
    r = PipelineResult(requirement="test")
    r.pending_clarification = {"stage": "pm", "questions": ["Q1"], "question_comment_id": 1, "asked_at": "2026-01-01T00:00:00Z", "qa_rounds": 1}
    r.clarification_history = [{"stage": "pm", "round": 1, "questions": ["Q1"], "answers": ["A1"], "answered_at": "2026-01-01T01:00:00Z"}]
    d = r.to_dict()
    assert d["pending_clarification"]["stage"] == "pm"
    assert d["clarification_history"][0]["answers"] == ["A1"]


def test_pipeline_result_from_dict_restores_qa_fields():
    data = {
        "requirement": "test",
        "pending_clarification": {"stage": "architect", "questions": ["Q2"], "question_comment_id": 42, "asked_at": "2026-01-01T00:00:00Z", "qa_rounds": 2},
        "clarification_history": [{"stage": "pm", "round": 1, "questions": ["Q1"], "answers": ["A1"], "answered_at": "2026-01-01T01:00:00Z"}],
    }
    r = PipelineResult.from_dict(data)
    assert r.pending_clarification["stage"] == "architect"
    assert r.clarification_history[0]["answers"] == ["A1"]


def test_pipeline_result_from_dict_missing_qa_fields_defaults():
    data = {"requirement": "test"}
    r = PipelineResult.from_dict(data)
    assert r.pending_clarification is None
    assert r.clarification_history == []
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_qa_clarification.py -v 2>&1 | head -40
```

Expected: ImportError or AttributeError for `ClarificationNeeded` and the new fields.

- [ ] **Step 1.3: Add `ClarificationNeeded` to `orchestrator.py`**

Find the line `class PipelineResult:` (around line 71). Add BEFORE it:

```python
class ClarificationNeeded(Exception):
    """Raised by PM or Architect agents when requirements are ambiguous.

    The orchestrator catches this, posts a GitHub comment with the questions,
    saves a checkpoint, and pauses the pipeline (agent-waiting label).
    """

    def __init__(self, questions: list[str]) -> None:
        self.questions = questions
        super().__init__(f"Clarification needed: {len(questions)} question(s)")
```

- [ ] **Step 1.4: Extend `PipelineResult` dataclass**

In the `PipelineResult` dataclass, after the `completed_stages` field (around line 97), add:

```python
    # Q&A clarification fields
    pending_clarification: Optional[dict] = None  # set while waiting for human reply
    clarification_history: list[dict] = field(default_factory=list)  # completed Q&A rounds
```

- [ ] **Step 1.5: Update `to_dict()`**

In `PipelineResult.to_dict()`, add at the end of the returned dict (before the closing brace):

```python
            "pending_clarification": self.pending_clarification,
            "clarification_history": self.clarification_history,
```

- [ ] **Step 1.6: Update `from_dict()`**

In `PipelineResult.from_dict()`, add these two keys to the existing loop's key list:

```python
            "pending_clarification", "clarification_history",
```

(The loop already uses `setattr(r, key, data.get(key, getattr(r, key)))`, so adding the keys is sufficient.)

- [ ] **Step 1.7: Run tests to verify they pass**

```bash
python -m pytest tests/test_qa_clarification.py::test_clarification_needed_stores_questions tests/test_qa_clarification.py::test_clarification_needed_is_exception tests/test_qa_clarification.py::test_pipeline_result_has_pending_clarification_default tests/test_qa_clarification.py::test_pipeline_result_has_clarification_history_default tests/test_qa_clarification.py::test_pipeline_result_to_dict_includes_qa_fields tests/test_qa_clarification.py::test_pipeline_result_from_dict_restores_qa_fields tests/test_qa_clarification.py::test_pipeline_result_from_dict_missing_qa_fields_defaults -v
```

Expected: All 7 tests PASS.

- [ ] **Step 1.8: Commit**

```bash
git add orchestrator.py tests/test_qa_clarification.py
git commit -m "feat: add ClarificationNeeded exception and PipelineResult Q&A fields

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: `BaseAgent.request_clarification()` + role prompt updates

**Files:**
- Modify: `agents/base_agent.py`
- Modify: `roles/product_manager.md`
- Modify: `roles/architect.md`
- Test: `tests/test_qa_clarification.py`

- [ ] **Step 2.1: Write the failing test**

Append to `tests/test_qa_clarification.py`:

```python
def test_base_agent_request_clarification_raises():
    from agents.base_agent import BaseAgent
    from orchestrator import ClarificationNeeded

    class DummyAgent(BaseAgent):
        role_name = "engineer"
        def run(self): pass

    agent = DummyAgent(model="gpt-4.1")
    with pytest.raises(ClarificationNeeded) as exc_info:
        agent.request_clarification(["Q1: What DB?", "Q2: Sync or async?"])
    assert exc_info.value.questions == ["Q1: What DB?", "Q2: Sync or async?"]


def test_base_agent_request_clarification_single_question():
    from agents.base_agent import BaseAgent
    from orchestrator import ClarificationNeeded

    class DummyAgent(BaseAgent):
        role_name = "engineer"
        def run(self): pass

    agent = DummyAgent(model="gpt-4.1")
    with pytest.raises(ClarificationNeeded) as exc_info:
        agent.request_clarification(["Q1: only one question"])
    assert len(exc_info.value.questions) == 1
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
python -m pytest tests/test_qa_clarification.py::test_base_agent_request_clarification_raises tests/test_qa_clarification.py::test_base_agent_request_clarification_single_question -v
```

Expected: AttributeError — `BaseAgent` has no `request_clarification`.

- [ ] **Step 2.3: Add `request_clarification()` to `BaseAgent`**

In `agents/base_agent.py`, find `def reset_history(self):` (around line 235). Add AFTER it:

```python
    def request_clarification(self, questions: list[str]) -> None:
        """Pause the pipeline and ask the human clarifying questions.

        Raises ClarificationNeeded which the orchestrator catches at the stage
        boundary. The orchestrator posts the questions to the GitHub issue and
        sets the agent-waiting label.

        Args:
            questions: List of question strings, e.g. ["Q1: What DB?", "Q2: Async?"]
        """
        from orchestrator import ClarificationNeeded
        raise ClarificationNeeded(questions)
```

- [ ] **Step 2.4: Run tests to verify they pass**

```bash
python -m pytest tests/test_qa_clarification.py::test_base_agent_request_clarification_raises tests/test_qa_clarification.py::test_base_agent_request_clarification_single_question -v
```

Expected: Both PASS.

- [ ] **Step 2.5: Update `roles/product_manager.md` with clarification guidance**

At the END of the file (after all existing content), add:

```markdown

## Asking Clarifying Questions

If the requirements are genuinely ambiguous and you cannot make a reasonable assumption, call `self.request_clarification(questions)` with a list of specific questions.

**Only do this when:**
- A key architectural decision is blocked on missing information (e.g., "which database?", "which auth provider?")
- Making the wrong assumption would require a full re-implementation

**Do NOT ask about:**
- Style preferences, minor naming choices, or formatting
- Anything you can reasonably infer from context or industry norms

**Format each question as a clear, specific string:**
```python
self.request_clarification([
    "Q1: Which database should the API use? (PostgreSQL, MySQL, or SQLite)",
    "Q2: Should authentication be JWT-based or session-based?",
])
```

Maximum 3 questions per call. Maximum 3 Q&A rounds per pipeline run; after that, proceed with your best assumptions.
```

- [ ] **Step 2.6: Update `roles/architect.md` with clarification guidance**

At the END of the file (after all existing content), add the same block as above (identical content — both agents have the same guidance).

- [ ] **Step 2.7: Commit**

```bash
git add agents/base_agent.py roles/product_manager.md roles/architect.md tests/test_qa_clarification.py
git commit -m "feat: add request_clarification() to BaseAgent and update PM/Architect prompts

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Orchestrator pause + resume logic

**Files:**
- Modify: `orchestrator.py` (4 methods: `_run_stage`, `run`, `_stage_pm`, `_stage_architect`)
- New helpers: `_pause_for_clarification()`, `_build_clarification_context()` on `Orchestrator`
- Test: `tests/test_qa_clarification.py`

- [ ] **Step 3.1: Write the failing tests**

Append to `tests/test_qa_clarification.py`:

```python
def test_run_stage_reraises_clarification_needed():
    """_run_stage must re-raise ClarificationNeeded, not swallow it."""
    from orchestrator import ClarificationNeeded, Orchestrator, PipelineResult
    orch = Orchestrator(model="gpt-4.1")
    result = PipelineResult(requirement="test")

    def bad_stage():
        raise ClarificationNeeded(["Q1: colour?"])

    with pytest.raises(ClarificationNeeded):
        orch._run_stage("Test Stage", "doing stuff", result, bad_stage)


def test_build_clarification_context_empty_history():
    from orchestrator import Orchestrator
    orch = Orchestrator(model="gpt-4.1")
    ctx = orch._build_clarification_context([], stage="pm")
    assert ctx == ""


def test_build_clarification_context_with_history():
    from orchestrator import Orchestrator
    orch = Orchestrator(model="gpt-4.1")
    history = [
        {"stage": "pm", "round": 1, "questions": ["Q1: DB?"], "answers": ["A1: PostgreSQL"], "answered_at": "2026-01-01T01:00:00Z"},
    ]
    ctx = orch._build_clarification_context(history, stage="pm")
    assert "Q1: DB?" in ctx
    assert "A1: PostgreSQL" in ctx
    assert "Clarification Answers" in ctx


def test_build_clarification_context_filters_by_stage():
    from orchestrator import Orchestrator
    orch = Orchestrator(model="gpt-4.1")
    history = [
        {"stage": "pm", "round": 1, "questions": ["Q1: DB?"], "answers": ["A1: PG"], "answered_at": ""},
        {"stage": "architect", "round": 1, "questions": ["Q2: API?"], "answers": ["A2: REST"], "answered_at": ""},
    ]
    ctx = orch._build_clarification_context(history, stage="pm")
    assert "Q1: DB?" in ctx
    assert "Q2: API?" not in ctx
```

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
python -m pytest tests/test_qa_clarification.py::test_run_stage_reraises_clarification_needed tests/test_qa_clarification.py::test_build_clarification_context_empty_history tests/test_qa_clarification.py::test_build_clarification_context_with_history tests/test_qa_clarification.py::test_build_clarification_context_filters_by_stage -v
```

Expected: FAIL — `_run_stage` swallows the exception; `_build_clarification_context` doesn't exist.

- [ ] **Step 3.3: Modify `_run_stage()` to re-raise `ClarificationNeeded`**

Current `_run_stage` (around line 1014):
```python
    def _run_stage(self, name: str, description: str, result: PipelineResult, fn) -> None:
        """Run a pipeline stage with progress display and error handling."""
        with Progress(
            SpinnerColumn(),
            TextColumn(f"[bold blue]{name}[/bold blue] {description}"),
            transient=True,
            console=console,
        ) as progress:
            progress.add_task("running", total=None)
            try:
                fn()
                console.print(f"  ✅ [green]{name}[/green] complete")
            except Exception as exc:
                error_msg = f"{name} failed: {exc}"
                result.errors.append(error_msg)
                console.print(f"  ❌ [red]{error_msg}[/red]")
```

Replace the `except` block with:
```python
            except ClarificationNeeded:
                raise  # handled by run() — do not log as error
            except Exception as exc:
                error_msg = f"{name} failed: {exc}"
                result.errors.append(error_msg)
                console.print(f"  ❌ [red]{error_msg}[/red]")
```

- [ ] **Step 3.4: Add `_build_clarification_context()` helper to `Orchestrator`**

Add this method AFTER `_run_stage` (around line 1040):

```python
    def _build_clarification_context(self, history: list[dict], stage: str) -> str:
        """Build an answer-injection block for a specific stage from Q&A history.

        Returns an empty string if there are no completed rounds for this stage.
        The returned block is prepended to the agent's main input so the agent
        treats the answers as authoritative requirements.
        """
        rounds = [r for r in history if r.get("stage") == stage]
        if not rounds:
            return ""
        lines = ["## Clarification Answers (from repository owner)\n"]
        for r in rounds:
            lines.append(f"### Round {r['round']}")
            for q, a in zip(r["questions"], r["answers"]):
                lines.append(f"{q}")
                lines.append(f"→ {a}\n")
        return "\n".join(lines)
```

- [ ] **Step 3.5: Add `_pause_for_clarification()` to `Orchestrator`**

Add this method directly after `_build_clarification_context`:

```python
    def _pause_for_clarification(
        self,
        result: PipelineResult,
        stage_key: str,
        questions: list[str],
    ) -> None:
        """Post Q&A comment to GitHub, save checkpoint, switch to agent-waiting.

        Called from run() when ClarificationNeeded is caught at stage boundary.
        Does nothing if GitHub integration is not configured.
        """
        qa_rounds = sum(1 for r in result.clarification_history if r.get("stage") == stage_key) + 1
        console.print(f"  🤔 [yellow]Clarification needed (round {qa_rounds})[/yellow]")

        comment_id: Optional[int] = None
        if self.github and result.issue_number:
            q_lines = "\n".join(f"**{q}**" for q in questions)
            comment_body = (
                f"<!-- ai-question:{stage_key}:round-{qa_rounds} -->\n"
                f"🤖 **AI needs clarification before proceeding**\n\n"
                f"Please answer the following questions by replying to this comment:\n\n"
                f"{q_lines}\n\n"
                f"_Pipeline paused. It will resume automatically when you reply. "
                f"If no answer is received within 24 hours, the pipeline will proceed "
                f"with its best assumptions._"
            )
            try:
                resp = self.github.post_comment(result.issue_number, comment_body)
                comment_id = resp.get("id") if isinstance(resp, dict) else None
            except Exception as exc:
                console.print(f"  ⚠️  [yellow]Could not post comment: {exc}[/yellow]")

            # Switch labels: remove agent-running, add agent-waiting
            from watcher import LABEL_RUNNING, LABEL_WAITING
            try:
                self.github.remove_label(result.issue_number, LABEL_RUNNING)
            except Exception:
                pass
            try:
                self.github.add_label(result.issue_number, LABEL_WAITING)
            except Exception:
                pass

        import datetime as _dt
        result.pending_clarification = {
            "stage": stage_key,
            "questions": questions,
            "question_comment_id": comment_id,
            "asked_at": _dt.datetime.utcnow().isoformat() + "Z",
            "qa_rounds": qa_rounds,
        }
        self._save_checkpoint(result)
        console.print(f"  ⏸️  [yellow]Pipeline paused — waiting for human reply[/yellow]")
```

- [ ] **Step 3.6: Modify `run()` to catch `ClarificationNeeded` and pre-set issue_number**

In `run()`, find the beginning of the method (around line 550) where `result` is built. The method signature is:
```python
def run(self, requirement: str, trigger_issue_body: Optional[str] = None, resume: bool = True) -> PipelineResult:
```

Add an `issue_number: Optional[int] = None` parameter:
```python
def run(self, requirement: str, trigger_issue_body: Optional[str] = None, resume: bool = True, issue_number: Optional[int] = None) -> PipelineResult:
```

After the `result = self._load_checkpoint(requirement) ...` block (where result is set), add:
```python
        # Pre-set issue_number if provided by caller (allows pause before PM creates it)
        if issue_number is not None and not result.issue_number:
            result.issue_number = issue_number
```

Then wrap each stage call that can pause (PM and Architect) with `ClarificationNeeded` handling. Change the PM stage block from:

```python
        # ── Stage 1: Product Manager ─────────────────────────────────────────
        if "pm" not in result.completed_stages:
            self._run_stage("📋 Product Manager", "Analyzing requirements & writing PRD...", result, lambda: self._stage_pm(result, requirement))
            if result.errors:
                self._save_checkpoint(result)
                return self._finish(result, start_time)
            result.completed_stages.append("pm")
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]📋 Product Manager — skipped (checkpoint)[/dim]")
```

To:

```python
        # ── Stage 1: Product Manager ─────────────────────────────────────────
        if "pm" not in result.completed_stages:
            try:
                self._run_stage("📋 Product Manager", "Analyzing requirements & writing PRD...", result, lambda: self._stage_pm(result, requirement))
            except ClarificationNeeded as exc:
                self._pause_for_clarification(result, "pm", exc.questions)
                return self._finish(result, start_time)
            if result.errors:
                self._save_checkpoint(result)
                return self._finish(result, start_time)
            result.completed_stages.append("pm")
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]📋 Product Manager — skipped (checkpoint)[/dim]")
```

And similarly change the Architect stage block from:

```python
        # ── Stage 2: Architect ────────────────────────────────────────────────
        if "architect" not in result.completed_stages:
            self._run_stage("🏗️  Architect", "Designing system architecture...", result, lambda: self._stage_architect(result))
            if result.errors:
                self._save_checkpoint(result)
                return self._finish(result, start_time)
            result.completed_stages.append("architect")
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]🏗️  Architect — skipped (checkpoint)[/dim]")
```

To:

```python
        # ── Stage 2: Architect ────────────────────────────────────────────────
        if "architect" not in result.completed_stages:
            try:
                self._run_stage("🏗️  Architect", "Designing system architecture...", result, lambda: self._stage_architect(result))
            except ClarificationNeeded as exc:
                self._pause_for_clarification(result, "architect", exc.questions)
                return self._finish(result, start_time)
            if result.errors:
                self._save_checkpoint(result)
                return self._finish(result, start_time)
            result.completed_stages.append("architect")
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]🏗️  Architect — skipped (checkpoint)[/dim]")
```

- [ ] **Step 3.7: Inject clarification context in `_stage_pm()` and `_stage_architect()`**

Current `_stage_pm`:
```python
    def _stage_pm(self, result: PipelineResult, requirement: str) -> None:
        if self.github:
            pm_result = self.pm.run_with_github(requirement, self.github)
            result.issue_number = pm_result["issue_number"]
            result.issue_url = pm_result["issue_url"]
        else:
            pm_result = self.pm.run(requirement)
        result.prd = pm_result["prd"]
        result.project_name = pm_result["project_name"]
```

Replace with:
```python
    def _stage_pm(self, result: PipelineResult, requirement: str) -> None:
        ctx = self._build_clarification_context(result.clarification_history, stage="pm")
        effective_req = f"{ctx}\n\n---\n\n{requirement}" if ctx else requirement
        if self.github:
            pm_result = self.pm.run_with_github(effective_req, self.github)
            result.issue_number = pm_result["issue_number"]
            result.issue_url = pm_result["issue_url"]
        else:
            pm_result = self.pm.run(effective_req)
        result.prd = pm_result["prd"]
        result.project_name = pm_result["project_name"]
```

Current `_stage_architect`:
```python
    def _stage_architect(self, result: PipelineResult) -> None:
        if self.github and result.issue_number:
            arch_result = self.architect.run_with_github(
                result.prd, result.project_name, self.github, result.issue_number
            )
        else:
            arch_result = self.architect.run(result.prd, result.project_name)
        result.design = arch_result["design"]
        result.modules = arch_result["modules"]
```

Replace with:
```python
    def _stage_architect(self, result: PipelineResult) -> None:
        ctx = self._build_clarification_context(result.clarification_history, stage="architect")
        effective_prd = f"{ctx}\n\n---\n\n{result.prd}" if ctx else result.prd
        if self.github and result.issue_number:
            arch_result = self.architect.run_with_github(
                effective_prd, result.project_name, self.github, result.issue_number
            )
        else:
            arch_result = self.architect.run(effective_prd, result.project_name)
        result.design = arch_result["design"]
        result.modules = arch_result["modules"]
```

- [ ] **Step 3.8: Check `github_client.py` has `post_comment()` and `remove_label()` / `add_label()` methods**

```bash
grep -n "def post_comment\|def remove_label\|def add_label" github_client.py
```

If `post_comment` doesn't return the created comment dict (needed for comment ID), check its implementation and update if needed. If it returns the response dict with `"id"`, no change is needed. If it returns `None`, update to return the response:

```python
def post_comment(self, issue_number: int, body: str) -> dict:
    return self._request("POST", f"/repos/{self.repo}/issues/{issue_number}/comments", json={"body": body})
```

- [ ] **Step 3.9: Run all tests**

```bash
python -m pytest tests/test_qa_clarification.py -v
```

Expected: All tests PASS.

- [ ] **Step 3.10: Commit**

```bash
git add orchestrator.py
git commit -m "feat: orchestrator pause/resume logic for ClarificationNeeded

- _run_stage re-raises ClarificationNeeded (not swallowed)
- run() catches it for PM and Architect stages
- _pause_for_clarification() posts GitHub comment, saves checkpoint, sets agent-waiting
- _build_clarification_context() injects Q&A history into re-run stages
- _stage_pm() and _stage_architect() prepend clarification context when resuming

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Watcher `agent-waiting` polling

**Files:**
- Modify: `watcher.py`
- Test: `tests/test_qa_clarification.py`

- [ ] **Step 4.1: Write the failing tests**

Append to `tests/test_qa_clarification.py`:

```python
def test_watcher_has_label_waiting_constant():
    import watcher
    assert hasattr(watcher, "LABEL_WAITING")
    assert watcher.LABEL_WAITING == "agent-waiting"


def test_watcher_label_waiting_in_skip_labels():
    import watcher
    assert watcher.LABEL_WAITING in watcher.SKIP_LABELS


def test_find_human_answer_returns_none_when_no_comments():
    from watcher import _find_human_answer
    comments = []
    result = _find_human_answer(comments, question_comment_id=99)
    assert result is None


def test_find_human_answer_returns_none_for_bot_comment():
    from watcher import _find_human_answer
    comments = [
        {"id": 100, "user": {"login": "github-actions[bot]"}, "body": "answer", "created_at": "2026-01-01T02:00:00Z"},
    ]
    result = _find_human_answer(comments, question_comment_id=99)
    assert result is None


def test_find_human_answer_returns_body_for_human_comment():
    from watcher import _find_human_answer
    comments = [
        {"id": 100, "user": {"login": "wanleung"}, "body": "Use PostgreSQL", "created_at": "2026-01-01T02:00:00Z"},
    ]
    result = _find_human_answer(comments, question_comment_id=99)
    assert result == "Use PostgreSQL"


def test_find_human_answer_ignores_comments_before_question():
    from watcher import _find_human_answer
    comments = [
        {"id": 50, "user": {"login": "wanleung"}, "body": "Old comment", "created_at": "2026-01-01T00:00:00Z"},
        {"id": 100, "user": {"login": "wanleung"}, "body": "Real answer", "created_at": "2026-01-01T02:00:00Z"},
    ]
    # question_comment_id=99, so only id > 99 counts
    result = _find_human_answer(comments, question_comment_id=99)
    assert result == "Real answer"


def test_is_clarification_timeout_false_within_24h():
    from watcher import _is_clarification_timeout
    import datetime as dt
    asked_at = (dt.datetime.utcnow() - dt.timedelta(hours=10)).isoformat() + "Z"
    assert _is_clarification_timeout(asked_at) is False


def test_is_clarification_timeout_true_after_24h():
    from watcher import _is_clarification_timeout
    import datetime as dt
    asked_at = (dt.datetime.utcnow() - dt.timedelta(hours=25)).isoformat() + "Z"
    assert _is_clarification_timeout(asked_at) is True
```

- [ ] **Step 4.2: Run tests to verify they fail**

```bash
python -m pytest tests/test_qa_clarification.py::test_watcher_has_label_waiting_constant tests/test_qa_clarification.py::test_watcher_label_waiting_in_skip_labels tests/test_qa_clarification.py::test_find_human_answer_returns_none_when_no_comments tests/test_qa_clarification.py::test_find_human_answer_returns_body_for_human_comment tests/test_qa_clarification.py::test_is_clarification_timeout_false_within_24h tests/test_qa_clarification.py::test_is_clarification_timeout_true_after_24h -v
```

Expected: ImportError or AttributeError.

- [ ] **Step 4.3: Add `LABEL_WAITING` constant and update `SKIP_LABELS` in `watcher.py`**

Find the label constants block (around line 33):
```python
LABEL_QUEUED   = "agent-queued"
LABEL_RUNNING  = "agent-running"
LABEL_COMPLETE = "agent-complete"
LABEL_FAILED   = "agent-failed"

SKIP_LABELS = {LABEL_QUEUED, LABEL_RUNNING, LABEL_COMPLETE, LABEL_FAILED}
```

Replace with:
```python
LABEL_QUEUED   = "agent-queued"
LABEL_RUNNING  = "agent-running"
LABEL_WAITING  = "agent-waiting"   # paused: agent needs human clarification
LABEL_COMPLETE = "agent-complete"
LABEL_FAILED   = "agent-failed"

# Watcher skips issues with any of these labels during normal dispatch
# (agent-waiting is checked separately in check_waiting_issues)
SKIP_LABELS = {LABEL_QUEUED, LABEL_RUNNING, LABEL_WAITING, LABEL_COMPLETE, LABEL_FAILED}
```

Also add to `LABEL_COLOURS`:
```python
LABEL_COLOURS = {
    LABEL_QUEUED:   "e4e669",
    LABEL_RUNNING:  "0075ca",
    LABEL_WAITING:  "fbca04",   # yellow — paused for input
    LABEL_COMPLETE: "0e8a16",
    LABEL_FAILED:   "d73a4a",
}
```

- [ ] **Step 4.4: Add `_find_human_answer()` and `_is_clarification_timeout()` helpers to `watcher.py`**

Add these two functions after the `post_comment()` function (keep them near other GitHub helpers):

```python
def _find_human_answer(comments: list[dict], question_comment_id: int) -> str | None:
    """Return the body of the first human comment after question_comment_id.

    Skips bot accounts (names ending in '[bot]'). Returns None if no human
    reply exists after the question comment.
    """
    for comment in comments:
        if comment["id"] <= question_comment_id:
            continue
        login = comment.get("user", {}).get("login", "")
        if login.endswith("[bot]"):
            continue
        return comment["body"]
    return None


def _is_clarification_timeout(asked_at: str, timeout_hours: int = 24) -> bool:
    """Return True if the question was asked more than timeout_hours ago."""
    import datetime as _dt
    try:
        asked = _dt.datetime.fromisoformat(asked_at.rstrip("Z"))
        elapsed = (_dt.datetime.utcnow() - asked).total_seconds()
        return elapsed > timeout_hours * 3600
    except (ValueError, AttributeError):
        return False
```

- [ ] **Step 4.5: Add `_find_checkpoint_for_issue()` helper to `watcher.py`**

Add after the helpers above:

```python
def _find_checkpoint_for_issue(workspace_dir: Path, issue_number: int) -> tuple[Path, dict] | None:
    """Scan workspace for a checkpoint belonging to the given issue number.

    Returns (path, data) or None if not found.
    """
    for cp_file in workspace_dir.glob("*/checkpoint.json"):
        try:
            data = json.loads(cp_file.read_text(encoding="utf-8"))
            if data.get("issue_number") == issue_number:
                return cp_file, data
        except Exception:
            continue
    return None
```

Also add `import json` at the top of `watcher.py` if not already present:
```bash
grep "^import json" watcher.py
```
If missing, add after the other stdlib imports.

- [ ] **Step 4.6: Add `check_waiting_issues()` to `watcher.py`**

Add this function after `_find_checkpoint_for_issue()`:

```python
def check_waiting_issues(
    tracker_repo: str,
    workspace_dir: Path,
    log_dir: Path,
    model: str,
    num_engineers: int,
    logger: logging.Logger,
) -> None:
    """Check agent-waiting issues for human replies and resume if found.

    Called once per watcher loop iteration, after normal issue dispatch.
    For each waiting issue:
    - Loads its checkpoint to find the question comment ID and timestamp.
    - Fetches GitHub comments after the question comment.
    - If a human reply exists: injects answer into checkpoint, resumes pipeline.
    - If 24 h elapsed with no reply: injects timeout note, resumes pipeline.
    - Otherwise: does nothing (will check again next cron run).
    """
    url = f"https://api.github.com/repos/{tracker_repo}/issues"
    params = {"state": "open", "labels": LABEL_WAITING, "per_page": 50}
    resp = requests.get(url, headers=_gh_headers(), params=params, timeout=10)
    if not resp.ok:
        logger.warning("Could not fetch agent-waiting issues: %s", resp.status_code)
        return

    for issue in resp.json():
        if "pull_request" in issue:
            continue
        issue_number = issue["number"]
        logger.info("  ⏳ Checking waiting issue #%d", issue_number)

        found = _find_checkpoint_for_issue(workspace_dir, issue_number)
        if not found:
            logger.warning("    No checkpoint for waiting issue #%d — skipping", issue_number)
            continue

        cp_path, cp_data = found
        pending = cp_data.get("pending_clarification")
        if not pending:
            logger.warning("    No pending_clarification in checkpoint for #%d — resuming anyway", issue_number)
            _resume_waiting_issue(tracker_repo, issue, log_dir, model, num_engineers, logger)
            continue

        question_comment_id = pending.get("question_comment_id") or 0
        asked_at = pending.get("asked_at", "")
        stage = pending.get("stage", "unknown")
        questions = pending.get("questions", [])
        qa_rounds = pending.get("qa_rounds", 1)

        # Fetch comments
        comments_url = f"https://api.github.com/repos/{tracker_repo}/issues/{issue_number}/comments"
        comments_resp = requests.get(comments_url, headers=_gh_headers(), timeout=10)
        comments = comments_resp.json() if comments_resp.ok else []

        answer = _find_human_answer(comments, question_comment_id)
        timed_out = _is_clarification_timeout(asked_at)

        if answer:
            logger.info("    ✅ Human answered issue #%d — injecting answer", issue_number)
            _inject_clarification_answer(cp_path, cp_data, stage, questions, qa_rounds, answer)
            _resume_waiting_issue(tracker_repo, issue, log_dir, model, num_engineers, logger)
        elif timed_out:
            logger.info("    ⏰ Timeout on issue #%d — proceeding with assumptions", issue_number)
            post_comment(
                tracker_repo, issue_number,
                "⏰ No answer received within 24 hours. Proceeding with best assumptions."
            )
            _inject_clarification_answer(
                cp_path, cp_data, stage, questions, qa_rounds,
                answer="[No answer received — proceed with best assumptions]",
            )
            _resume_waiting_issue(tracker_repo, issue, log_dir, model, num_engineers, logger)
        else:
            logger.info("    ⏳ Still waiting for answer on issue #%d", issue_number)


def _inject_clarification_answer(
    cp_path: Path,
    cp_data: dict,
    stage: str,
    questions: list[str],
    qa_rounds: int,
    answer: str,
) -> None:
    """Update checkpoint: append to clarification_history, clear pending_clarification."""
    import datetime as _dt
    history = cp_data.get("clarification_history", [])
    history.append({
        "stage": stage,
        "round": qa_rounds,
        "questions": questions,
        "answers": [answer],  # single combined answer block from human reply
        "answered_at": _dt.datetime.utcnow().isoformat() + "Z",
    })
    cp_data["clarification_history"] = history
    cp_data["pending_clarification"] = None

    import tempfile, os as _os
    content = json.dumps(cp_data, indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=cp_path.parent, prefix=".ckpt_", suffix=".json")
    try:
        _os.write(fd, content.encode("utf-8"))
        _os.fsync(fd)
    finally:
        _os.close(fd)
    _os.replace(tmp, cp_path)


def _resume_waiting_issue(
    tracker_repo: str,
    issue: dict,
    log_dir: Path,
    model: str,
    num_engineers: int,
    logger: logging.Logger,
) -> None:
    """Switch labels and re-dispatch the pipeline for a waiting issue."""
    issue_number = issue["number"]
    remove_label(tracker_repo, issue_number, LABEL_WAITING)
    add_label(tracker_repo, issue_number, LABEL_RUNNING)

    # Re-dispatch inline (blocking) — waiting issues are processed one at a time
    issue_labels = {l["name"] for l in issue.get("labels", [])}
    pipeline_type = (
        "feature" if any(l.startswith("ai-feature") for l in issue_labels) else
        "bug"      if any(l.startswith("ai-bug") for l in issue_labels) else
        "documentation" if any(l.startswith("ai-doc") for l in issue_labels) else
        "feature"  # fallback
    )
    success = run_pipeline(
        issue=issue,
        tracker_repo=tracker_repo,
        default_target=None,
        pipeline_type=pipeline_type,
        model=model,
        num_engineers=num_engineers,
        log_dir=log_dir,
        dry_run=False,
        logger=logger,
    )
    if not success:
        logger.error("    ❌ Resume failed for issue #%d", issue_number)
```

- [ ] **Step 4.7: Call `check_waiting_issues()` in the `watch()` loop**

Find the `watch()` function. After the `with ThreadPoolExecutor...` block that dispatches normal issues, add a call to `check_waiting_issues()`. The function ends after the executor block — add before `logger.info("Loaded %d watcher(s)...")` changes. Specifically, after the loop that dispatches normal tasks, add:

```python
    # ── Check agent-waiting issues for replies ────────────────────────────────
    workspace_dir = Path(script_dir / pipeline_cfg.get("pipeline", {}).get("workspace_dir", "./workspace"))
    check_waiting_issues(
        tracker_repo=watchers[0]["tracker_repo"] if watchers else "",
        workspace_dir=workspace_dir,
        log_dir=log_dir,
        model=model,
        num_engineers=num_engineers,
        logger=logger,
    )
```

But there may be multiple `tracker_repo` values (one per watcher). Handle all of them by iterating:

```python
    # ── Check agent-waiting issues for replies ────────────────────────────────
    script_dir = Path(__file__).parent
    pipeline_cfg = _load_pipeline_config()
    workspace_dir = Path(script_dir / pipeline_cfg.get("pipeline", {}).get("workspace_dir", "./workspace"))
    for w in watchers:
        if not w.get("enabled", True):
            continue
        check_waiting_issues(
            tracker_repo=w["tracker_repo"],
            workspace_dir=workspace_dir,
            log_dir=log_dir,
            model=model,
            num_engineers=num_engineers,
            logger=logger,
        )
```

- [ ] **Step 4.8: Ensure `agent-waiting` label is created during `ensure_label()` calls**

In the watcher's main loop, labels are created for each watcher. Find where `ensure_label()` is called and add `LABEL_WAITING`:

```bash
grep -n "ensure_label\|LABEL_COLOURS" watcher.py | head -20
```

If `ensure_label` is called per watcher using `LABEL_COLOURS`, adding `LABEL_WAITING` to `LABEL_COLOURS` (done in Step 4.3) is sufficient — the loop will create it.

- [ ] **Step 4.9: Run all tests**

```bash
python -m pytest tests/test_qa_clarification.py -v
```

Expected: All tests PASS.

- [ ] **Step 4.10: Commit**

```bash
git add watcher.py tests/test_qa_clarification.py
git commit -m "feat: watcher polls agent-waiting issues and resumes on human reply

- LABEL_WAITING = 'agent-waiting' added to SKIP_LABELS (prevents re-dispatch)
- check_waiting_issues() scans waiting issues each cron run
- _find_human_answer() detects human reply after question comment
- _is_clarification_timeout() enforces 24h limit
- _inject_clarification_answer() updates checkpoint with Q&A round
- _resume_waiting_issue() switches labels and re-dispatches pipeline

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Wire `_dispatch()` to pass `issue_number` + full integration test

**Files:**
- Modify: `watcher.py` (`_dispatch()` and `run_pipeline()`)
- Test: manual verification steps

- [ ] **Step 5.1: Pass `issue_number` from `_dispatch()` to `orch.run()`**

In `_dispatch()`, find where `orch.run(requirement, trigger_issue_body=issue_body)` is called (feature pipeline). Update to:

```python
                orch.run(requirement, trigger_issue_body=issue_body, issue_number=issue_number)
```

- [ ] **Step 5.2: Run the full test suite**

```bash
python -m pytest tests/test_qa_clarification.py -v
```

Expected: All tests PASS.

Also do a quick sanity-check import:
```bash
python -c "from orchestrator import ClarificationNeeded, PipelineResult; from watcher import LABEL_WAITING, check_waiting_issues, _find_human_answer, _is_clarification_timeout; print('All imports OK')"
```

Expected: `All imports OK`

- [ ] **Step 5.3: Manual verification — create a test issue**

Create an issue in the tracker repo with label `ai-feature` and body containing an ambiguous requirement (e.g., "Build a user management system" without specifying the database). The PM agent's prompt now tells it to call `request_clarification()` when there's ambiguity. Watch the logs:

```bash
tail -f logs/watcher/cron.log
```

Expected sequence:
1. Watcher picks up the issue → `agent-running` label
2. PM stage raises `ClarificationNeeded` → `agent-waiting` label
3. GitHub issue gets a comment: "🤖 AI needs clarification before proceeding..."
4. Reply to the comment from your GitHub account
5. Next cron run: watcher detects reply → `agent-running` label
6. Pipeline resumes with PM stage injected with your answers
7. Pipeline completes → `agent-complete` label

- [ ] **Step 5.4: Final commit and push**

```bash
git add watcher.py
git commit -m "feat: pass issue_number to orch.run() for pre-stage pause support

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push
```

---

## Self-Review

**Spec coverage check:**
- ✅ `ClarificationNeeded` exception → Task 1
- ✅ `request_clarification()` on BaseAgent → Task 2
- ✅ Checkpoint `pending_clarification` + `clarification_history` → Task 1
- ✅ Orchestrator pause: post comment, save checkpoint, set label → Task 3
- ✅ Orchestrator resume: inject answers → Task 3 (Steps 3.7)
- ✅ Watcher: detect reply, inject, re-dispatch → Task 4
- ✅ 24h timeout → Task 4 (`_is_clarification_timeout`)
- ✅ Round limit (3) — not explicitly enforced in code (spec says "after max rounds, proceed"). The `qa_rounds` counter is stored. Enforcing this: the orchestrator checks `qa_rounds` in `_pause_for_clarification` — if `qa_rounds >= 3`, log warning and return without pausing. **Add this check in Step 3.5.**
- ✅ PM + Architect only (Architect Reviewer, Engineers, etc. cannot pause) → only `_stage_pm` and `_stage_architect` wrapped
- ✅ `agent-waiting` label colour → Task 4 Step 4.3
- ✅ Tests for all new behaviour → all tasks

**Round limit enforcement (gap fix):** In `_pause_for_clarification()` (Step 3.5), after calculating `qa_rounds`, add:

```python
        if qa_rounds > 3:
            console.print(f"  ⚠️  [yellow]Max Q&A rounds reached for stage '{stage_key}' — proceeding with assumptions[/yellow]")
            return  # do NOT pause; orchestrator will continue with best-guess
```

This must be added to the code in Step 3.5 (before the GitHub comment block).

**Type consistency check:** `_find_checkpoint_for_issue` returns `tuple[Path, dict] | None` — used correctly in `check_waiting_issues` with `cp_path, cp_data = found`.
