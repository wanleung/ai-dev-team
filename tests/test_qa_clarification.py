"""Tests for GitHub Comment Q&A clarification feature."""
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


def test_base_agent_request_clarification_raises():
    from agents.base_agent import BaseAgent

    class DummyAgent(BaseAgent):
        role_name = "engineer"
        def run(self): pass

    agent = DummyAgent(model="gpt-4.1")
    with pytest.raises(ClarificationNeeded) as exc_info:
        agent.request_clarification(["Q1: What DB?", "Q2: Sync or async?"])
    assert exc_info.value.questions == ["Q1: What DB?", "Q2: Sync or async?"]


def test_base_agent_request_clarification_single_question():
    from agents.base_agent import BaseAgent

    class DummyAgent(BaseAgent):
        role_name = "engineer"
        def run(self): pass

    agent = DummyAgent(model="gpt-4.1")
    with pytest.raises(ClarificationNeeded) as exc_info:
        agent.request_clarification(["Q1: only one question"])
    assert len(exc_info.value.questions) == 1


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


# ── Task 4: Watcher agent-waiting polling ──────────────────────────────────

def test_extract_answers_from_comments():
    """extract_answers_from_comments returns answers after the question comment."""
    from watcher import extract_answers_from_comments
    comments = [
        {"id": 10, "body": "<!-- ai-question:pm:round-1 -->\n**Q1: colour?**", "user": {"login": "bot"}},
        {"id": 20, "body": "Blue please", "user": {"login": "owner"}},
        {"id": 30, "body": "Also dark mode", "user": {"login": "owner"}},
    ]
    answers = extract_answers_from_comments(comments, question_comment_id=10, bot_login="bot")
    assert "Blue please" in answers
    assert "Also dark mode" in answers


def test_extract_answers_empty_when_no_reply():
    """extract_answers_from_comments returns empty list when no human reply yet."""
    from watcher import extract_answers_from_comments
    comments = [
        {"id": 10, "body": "<!-- ai-question:pm:round-1 -->\n**Q1?**", "user": {"login": "bot"}},
    ]
    answers = extract_answers_from_comments(comments, question_comment_id=10, bot_login="bot")
    assert answers == []


def test_label_waiting_in_skip_labels():
    """LABEL_WAITING must be in SKIP_LABELS so the main dispatch loop ignores it."""
    from watcher import LABEL_WAITING, SKIP_LABELS
    assert LABEL_WAITING in SKIP_LABELS


def test_label_waiting_value():
    """LABEL_WAITING must equal 'agent-waiting'."""
    from watcher import LABEL_WAITING
    assert LABEL_WAITING == "agent-waiting"


# ── Task 5: Integration test ───────────────────────────────────────────────

def test_full_qa_round_trip():
    """End-to-end: PM raises ClarificationNeeded → orchestrator pauses →
    checkpoint saved with pending_clarification → answers injected →
    _stage_pm gets context prepended.
    """
    from orchestrator import ClarificationNeeded, Orchestrator, PipelineResult

    # Patch PM agent to raise ClarificationNeeded on first call, then succeed on second
    call_count = {"n": 0}

    def pm_run_first_raises(requirement):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ClarificationNeeded(["Q1: What colour scheme?"])
        # Second call succeeds - return PRD that includes the requirement
        return {
            "prd": f"PRD with context: {requirement}",
            "project_name": "test_proj",
        }

    # Create orchestrator without GitHub integration
    orch = Orchestrator(model="gpt-4.1", github_repo=None)
    orch.pm.run = pm_run_first_raises

    result = PipelineResult(requirement="Build a dashboard", issue_number=42)

    # Simulate first run: PM raises → pause
    with pytest.raises(ClarificationNeeded) as exc_info:
        orch._stage_pm(result, "Build a dashboard")
    
    assert exc_info.value.questions == ["Q1: What colour scheme?"]

    # Inject answers into clarification_history
    result.clarification_history.append({
        "stage": "pm",
        "round": 1,
        "questions": ["Q1: What colour scheme?"],
        "answers": ["Blue and white"],
        "answered_at": "2026-01-01T00:00:00Z",
    })

    # Second call: context should be prepended
    result2 = PipelineResult(requirement="Build a dashboard", issue_number=42)
    result2.clarification_history = result.clarification_history
    orch._stage_pm(result2, "Build a dashboard")

    # Verify that the context was built and injected
    assert "Q1: What colour scheme?" in result2.prd
    assert "Blue and white" in result2.prd
    assert call_count["n"] == 2
