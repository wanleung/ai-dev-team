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
