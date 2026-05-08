"""Tests for core.errors.PipelineError."""
from __future__ import annotations
import pytest
from core.errors import PipelineError


def test_pipeline_error_str():
    e = PipelineError(code="AGENT_TIMEOUT", stage="architect", message="timed out", severity="error")
    s = str(e)
    assert "AGENT_TIMEOUT" in s
    assert "architect" in s
    assert "timed out" in s
    assert "ERROR" in s


def test_pipeline_error_to_dict():
    e = PipelineError(code="LLM_RATE_LIMIT", stage="qa", message="429", severity="warning")
    d = e.to_dict()
    assert d["code"] == "LLM_RATE_LIMIT"
    assert d["stage"] == "qa"
    assert d["message"] == "429"
    assert d["severity"] == "warning"
    assert "timestamp" in d
    assert isinstance(d["context"], dict)


def test_pipeline_error_context():
    e = PipelineError(code="UNKNOWN", stage="s", message="m", severity="error",
                      context={"file": "main.py", "line": 42})
    assert e.context["file"] == "main.py"
    assert e.to_dict()["context"]["line"] == 42


def test_pipeline_error_default_timestamp():
    e = PipelineError(code="UNKNOWN", stage="s", message="m", severity="fatal")
    assert e.timestamp.endswith("Z")


def test_pipeline_error_rejects_invalid_code():
    with pytest.raises(ValueError, match="Invalid error code"):
        PipelineError(code="TOTALLY_BOGUS", stage="s", message="m", severity="error")


def test_pipeline_error_rejects_invalid_severity():
    with pytest.raises(ValueError, match="Invalid severity"):
        PipelineError(code="UNKNOWN", stage="s", message="m", severity="mega_fatal")


def test_pipeline_error_to_dict_is_json_serializable():
    import json
    e = PipelineError(code="AGENT_TIMEOUT", stage="s", message="m", severity="error",
                      context={"retries": 3})
    json.dumps(e.to_dict())  # must not raise


# Tests for PipelineResult integration with PipelineError
from orchestrator import PipelineResult


def test_pipeline_result_errors_are_pipeline_error_instances():
    r = PipelineResult()
    r.add_error("something went wrong")
    assert len(r.errors) == 1
    assert isinstance(r.errors[0], PipelineError)
    assert r.errors[0].code == "UNKNOWN"
    assert r.errors[0].severity == "error"
    assert "something went wrong" in r.errors[0].message


def test_pipeline_result_has_fatal():
    r = PipelineResult()
    r.errors.append(PipelineError(code="AGENT_CRASH", stage="qa", message="crash", severity="fatal"))
    assert r.has_fatal() is True


def test_pipeline_result_has_fatal_false_when_only_warnings():
    r = PipelineResult()
    r.errors.append(PipelineError(code="STAGE_SKIPPED", stage="doc", message="skipped", severity="warning"))
    assert r.has_fatal() is False


def test_pipeline_result_add_error_with_structured_error():
    r = PipelineResult()
    e = PipelineError(code="LLM_TIMEOUT", stage="architect", message="timeout", severity="error")
    r.add_error(e)
    assert r.errors[0].code == "LLM_TIMEOUT"


def test_pipeline_result_errors_str_backwards_compat():
    """Existing code that does str(result.errors[0]) still works."""
    r = PipelineResult()
    r.add_error("legacy string error")
    assert "legacy string error" in str(r.errors[0])


def test_pipeline_result_from_dict_errors_string_list():
    """from_dict() must handle old checkpoints that stored errors as plain strings."""
    data = {
        "requirement": "build a thing",
        "errors": ["something went wrong", "another failure"],
    }
    r = PipelineResult.from_dict(data)
    assert len(r.errors) == 2
    # Each string should be wrapped in a PipelineError with the message preserved.
    assert "something went wrong" in r.errors[0].message
    assert "another failure" in r.errors[1].message


def test_pipeline_result_from_dict_errors_mixed():
    """from_dict() tolerates a mix of dict and string items in the errors list."""
    data = {
        "requirement": "build a thing",
        "errors": [
            {"code": "LLM_TIMEOUT", "stage": "engineer", "message": "timed out", "severity": "error"},
            "plain string error",
        ],
    }
    r = PipelineResult.from_dict(data)
    assert len(r.errors) == 2
    assert r.errors[0].code == "LLM_TIMEOUT"
    assert "plain string error" in r.errors[1].message


def test_pipeline_result_has_fatal_empty():
    r = PipelineResult()
    assert r.has_fatal() is False
