"""Tests for TDDReviewerAgent."""
from unittest.mock import MagicMock


def _make_agent(response: str = ""):
    """Helper: create TDDReviewerAgent with a mocked call() method."""
    from agents.tdd_reviewer import TDDReviewerAgent
    agent = TDDReviewerAgent.__new__(TDDReviewerAgent)
    agent.model = "gpt-4.1"
    agent._history = []
    agent.call = MagicMock(return_value=response)
    return agent


class TestParseReviewResponse:
    """Test _parse_review_response static method."""

    def test_parses_file_blocks_and_summary(self):
        from agents.tdd_reviewer import TDDReviewerAgent
        response = """
### FILE: tests/conftest.py
```python
import pytest

class MockModel:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
```

### REVIEW SUMMARY:
- Correctness fixes: moved MockModel to root conftest
- Quality additions: none
- Remaining concerns: none
"""
        files, summary = TDDReviewerAgent._parse_review_response(response)
        assert "tests/conftest.py" in files
        assert "MockModel" in files["tests/conftest.py"]
        assert "Correctness fixes" in summary

    def test_returns_empty_files_when_no_file_blocks(self):
        from agents.tdd_reviewer import TDDReviewerAgent
        response = "### REVIEW SUMMARY:\n- Nothing to fix"
        files, summary = TDDReviewerAgent._parse_review_response(response)
        assert files == {}
        assert "Nothing to fix" in summary

    def test_summary_empty_string_when_missing(self):
        from agents.tdd_reviewer import TDDReviewerAgent
        response = "### FILE: tests/test_foo.py\n```python\nassert True\n```"
        files, summary = TDDReviewerAgent._parse_review_response(response)
        assert "tests/test_foo.py" in files
        assert summary == ""


class TestCollectSyntaxErrors:
    """Test _collect_syntax_errors static method."""

    def test_no_errors_on_valid_python(self):
        from agents.tdd_reviewer import TDDReviewerAgent
        files = {"tests/test_foo.py": "def test_x():\n    assert 1 == 1\n"}
        assert TDDReviewerAgent._collect_syntax_errors(files) == []

    def test_detects_syntax_error(self):
        from agents.tdd_reviewer import TDDReviewerAgent
        files = {"tests/test_foo.py": "def test_x(\n    assert 1 == 1\n"}
        errors = TDDReviewerAgent._collect_syntax_errors(files)
        assert len(errors) == 1
        assert "test_foo.py" in errors[0]

    def test_skips_non_python_files(self):
        from agents.tdd_reviewer import TDDReviewerAgent
        files = {"requirements-test.txt": "pytest\n---\nbad"}
        assert TDDReviewerAgent._collect_syntax_errors(files) == []


class TestRun:
    """Test TDDReviewerAgent.run() end-to-end."""

    def test_run_returns_revised_files_and_summary(self):
        llm_response = """
### FILE: tests/conftest.py
```python
import pytest

class MockModel:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

@pytest.fixture
def mock_db():
    return MockModel()
```

### REVIEW SUMMARY:
- Correctness fixes: added MockModel to conftest
- Quality additions: none
- Remaining concerns: none
"""
        agent = _make_agent(llm_response)
        original = {"tests/conftest.py": "import pytest\n"}
        revised, summary = agent.run(original, prd="Build a REST API", project_name="myapp")
        assert "MockModel" in revised.get("tests/conftest.py", "")
        assert "Correctness fixes" in summary

    def test_run_returns_original_on_llm_failure(self):
        agent = _make_agent()
        agent.call.side_effect = RuntimeError("LLM unavailable")
        original = {"tests/test_foo.py": "def test_x():\n    assert True\n"}
        revised, summary = agent.run(original, prd="Build something", project_name="proj")
        assert revised == original
        assert summary == ""

    def test_run_returns_original_when_no_file_blocks_returned(self):
        agent = _make_agent("### REVIEW SUMMARY:\n- All good")
        original = {"tests/test_foo.py": "def test_x():\n    assert 1 == 1\n"}
        revised, summary = agent.run(original, prd="PRD", project_name="proj")
        assert revised == original
        assert "All good" in summary

    def test_run_retries_on_syntax_error_and_returns_fixed_files(self):
        syntax_broken = "### FILE: tests/test_foo.py\n```python\ndef test_x(\n    assert 1\n```"
        fixed = (
            "### FILE: tests/test_foo.py\n```python\ndef test_x():\n    assert 1 == 1\n```\n"
            "### REVIEW SUMMARY:\n- Correctness fixes: fixed syntax error\n"
        )
        agent = _make_agent()
        agent.call.side_effect = [syntax_broken, fixed]
        original = {"tests/test_foo.py": "def test_x():\n    assert 1 == 1\n"}
        revised, summary = agent.run(original, prd="PRD", project_name="proj")
        assert "assert 1 == 1" in revised.get("tests/test_foo.py", "")

    def test_run_returns_original_when_retry_raises(self):
        syntax_broken = "### FILE: tests/test_foo.py\n```python\ndef test_x(\n    assert 1\n```"
        agent = _make_agent()
        agent.call.side_effect = [syntax_broken, RuntimeError("retry failed")]
        original = {"tests/test_foo.py": "def test_x():\n    assert 1 == 1\n"}
        revised, summary = agent.run(original, prd="PRD", project_name="proj")
        assert revised == original
        assert summary == ""
