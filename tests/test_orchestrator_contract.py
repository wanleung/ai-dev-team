"""Tests for contract_validate pipeline stage wiring."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from orchestrator import Orchestrator, PipelineResult


@pytest.fixture
def orchestrator():
    """Minimal orchestrator with mocked deps."""
    orc = Orchestrator.__new__(Orchestrator)
    orc.contract_validator = MagicMock()
    orc.github = None
    orc.target_github = None
    orc.tdd_commit_tests = False
    return orc


class TestContractValidateStage:
    def test_skips_when_no_test_files(self, orchestrator):
        result = PipelineResult(requirement="test")
        result.test_files = {}
        result.naming_contract = "version: 1"
        orchestrator._stage_contract_validate(result)
        orchestrator.contract_validator.validate.assert_not_called()

    def test_skips_when_no_contract(self, orchestrator):
        result = PipelineResult(requirement="test")
        result.test_files = {"tests/test_foo.py": "content"}
        result.naming_contract = ""
        orchestrator._stage_contract_validate(result)
        orchestrator.contract_validator.validate.assert_not_called()

    def test_sets_passed_when_validation_passes(self, orchestrator):
        result = PipelineResult(requirement="test")
        result.test_files = {"tests/test_foo.py": "content"}
        result.naming_contract = "version: 1\nendpoints: []"
        orchestrator.contract_validator.validate.return_value = {
            "passed": True, "skipped": False, "divergences": []
        }
        orchestrator._stage_contract_validate(result)
        assert result.contract_validation_passed is True
        assert result.contract_divergences == []

    def test_sets_divergences_when_validation_fails(self, orchestrator):
        result = PipelineResult(requirement="test")
        result.test_files = {"tests/test_foo.py": "content"}
        result.naming_contract = "version: 1\nendpoints: []"
        divergence = {"file": "tests/test_foo.py", "field": "user_name", "issue": "...", "suggestion": "..."}
        orchestrator.contract_validator.validate.return_value = {
            "passed": False, "skipped": False, "divergences": [divergence]
        }
        orchestrator._stage_contract_validate(result)
        assert result.contract_validation_passed is False
        assert len(result.contract_divergences) == 1


class TestPipelineResultContractFields:
    def test_naming_contract_default_empty(self):
        result = PipelineResult(requirement="test")
        assert result.naming_contract == ""

    def test_contract_validation_passed_default_none(self):
        result = PipelineResult(requirement="test")
        assert result.contract_validation_passed is None

    def test_contract_divergences_default_empty_list(self):
        result = PipelineResult(requirement="test")
        assert result.contract_divergences == []
