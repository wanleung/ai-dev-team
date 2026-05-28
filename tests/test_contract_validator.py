"""Tests for ContractValidatorAgent."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from agents.contract_validator import ContractValidatorAgent


CONTRACT = """
version: 1
endpoints:
  - path: /api/users
    method: POST
    auth: required
    request_fields: [username, email, password]
    response_fields: [id, username, email, created_at]
enums:
  UserRole: [admin, member, guest]
service_signatures:
  - fn: user_service.create_user
    args: [CreateUserRequest]
"""

PASSING_TEST = """\
def test_create_user(client):
    resp = client.post("/api/users", json={"username": "alice", "email": "a@b.com", "password": "secret"})
    assert resp.status_code == 201
    assert resp.json()["username"] == "alice"
    assert "created_at" in resp.json()
"""

FAILING_TEST = """\
def test_create_user(client):
    resp = client.post("/api/users", json={"user_name": "alice", "mail": "a@b.com"})
    assert resp.status_code == 201
"""


@pytest.fixture
def mock_llm():
    return MagicMock()


@pytest.fixture
def validator(mock_llm):
    return ContractValidatorAgent(llm=mock_llm)


class TestContractValidatorSkip:
    def test_no_contract_returns_skipped(self, validator):
        result = validator.validate(contract_yaml=None, files={"test.py": "content"})
        assert result == {"passed": True, "skipped": True, "divergences": []}

    def test_empty_contract_returns_skipped(self, validator):
        result = validator.validate(contract_yaml="", files={"test.py": "content"})
        assert result == {"passed": True, "skipped": True, "divergences": []}

    def test_no_files_returns_skipped(self, validator):
        result = validator.validate(contract_yaml=CONTRACT, files={})
        assert result == {"passed": True, "skipped": True, "divergences": []}


class TestContractValidatorPassing:
    def test_passing_test_returns_passed(self, validator, mock_llm):
        mock_llm.call.return_value = '{"passed": true, "skipped": false, "divergences": []}'
        result = validator.validate(CONTRACT, {"tests/test_users.py": PASSING_TEST})
        assert result["passed"] is True
        assert result["skipped"] is False
        assert result["divergences"] == []

    def test_llm_called_with_contract_and_files(self, validator, mock_llm):
        mock_llm.call.return_value = '{"passed": true, "skipped": false, "divergences": []}'
        validator.validate(CONTRACT, {"tests/test_users.py": PASSING_TEST})
        call_kwargs = mock_llm.call.call_args
        assert call_kwargs is not None
        # Verify contract YAML is in the prompt
        prompt = call_kwargs[1]["user_message"]
        assert "naming_contract.yaml" in prompt
        assert "username" in prompt


class TestContractValidatorFailing:
    def test_failing_test_returns_divergences(self, validator, mock_llm):
        response = json.dumps({
            "passed": False,
            "skipped": False,
            "divergences": [
                {
                    "file": "tests/test_users.py",
                    "field": "user_name",
                    "issue": "Test uses 'user_name' but contract expects 'username'",
                    "suggestion": "Rename 'user_name' to 'username'"
                }
            ]
        })
        mock_llm.call.return_value = response
        result = validator.validate(CONTRACT, {"tests/test_users.py": FAILING_TEST})
        assert result["passed"] is False
        assert len(result["divergences"]) == 1
        assert result["divergences"][0]["field"] == "user_name"


class TestContractValidatorParsing:
    def test_json_parse_error_returns_skipped(self, validator, mock_llm):
        mock_llm.call.return_value = "This is not JSON at all"
        result = validator.validate(CONTRACT, {"tests/test_users.py": PASSING_TEST})
        assert result["passed"] is True
        assert result["skipped"] is True

    def test_markdown_fenced_json_is_parsed(self, validator, mock_llm):
        mock_llm.call.return_value = '```json\n{"passed": true, "skipped": false, "divergences": []}\n```'
        result = validator.validate(CONTRACT, {"tests/test_users.py": PASSING_TEST})
        assert result["passed"] is True
        assert result["skipped"] is False
