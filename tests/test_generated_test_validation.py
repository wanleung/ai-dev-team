"""Tests for deterministic validation of generated pytest files."""
from __future__ import annotations

from unittest.mock import MagicMock

from tools.test_validation import validate_generated_tests


def test_validate_generated_tests_rejects_tests_conftest_import():
    files = {
        "tests/test_guest_access.py": "from tests.conftest import _Obj\n\n"
                                      "def test_x():\n    assert _Obj()\n",
    }

    issues = validate_generated_tests(files)

    assert len(issues) == 1
    assert "tests.conftest" in issues[0]
    assert "tests/helpers.py" in issues[0]


def test_validate_generated_tests_rejects_root_conftest_import():
    files = {"tests/test_user.py": "from conftest import make_user\n"}

    issues = validate_generated_tests(files)

    assert len(issues) == 1
    assert "conftest" in issues[0]


def test_validate_generated_tests_allows_helpers_import():
    files = {"tests/test_user.py": "from tests.helpers import Obj\n"}

    assert validate_generated_tests(files) == []


def test_validate_generated_tests_rejects_direct_fixture_call():
    files = {
        "tests/conftest.py": "import pytest\n\n@pytest.fixture\ndef make_user():\n    return object()\n",
        "tests/test_user.py": "def test_profile(make_user):\n    other = make_user(id=50)\n",
    }

    issues = validate_generated_tests(files)

    assert len(issues) == 1
    assert "calls pytest fixture 'make_user' directly" in issues[0]


def test_qa_engineer_retries_generated_test_rule_violations():
    from agents.qa_engineer import QAEngineerAgent

    agent = QAEngineerAgent.__new__(QAEngineerAgent)
    agent._tool_registry = None
    agent.call = MagicMock(side_effect=[
        "### FILE: tests/test_bad.py\n```python\nfrom tests.conftest import _Obj\n```",
        "### FILE: tests/helpers.py\n```python\nclass _Obj: pass\n```\n"
        "### FILE: tests/test_bad.py\n```python\nfrom tests.helpers import _Obj\n```",
    ])

    result = agent.run({}, "PRD", project_name="Project", write_only=True)

    assert agent.call.call_count == 2
    assert "from tests.helpers import _Obj" in result["test_files"]["tests/test_bad.py"]


def test_tdd_reviewer_retries_generated_test_rule_violations():
    from agents.tdd_reviewer import TDDReviewerAgent

    agent = TDDReviewerAgent.__new__(TDDReviewerAgent)
    agent.call = MagicMock(side_effect=[
        "### FILE: tests/test_bad.py\n```python\nfrom tests.conftest import _Obj\n```\n"
        "### REVIEW SUMMARY:\n- Correctness fixes: none",
        "### FILE: tests/helpers.py\n```python\nclass _Obj: pass\n```\n"
        "### FILE: tests/test_bad.py\n```python\nfrom tests.helpers import _Obj\n```\n"
        "### REVIEW SUMMARY:\n- Correctness fixes: moved helper",
    ])

    files, summary = agent.run(
        {"tests/test_bad.py": "from tests.conftest import _Obj"},
        prd="PRD",
        project_name="Project",
    )

    assert agent.call.call_count == 2
    assert "from tests.helpers import _Obj" in files["tests/test_bad.py"]
    assert "moved helper" in summary
