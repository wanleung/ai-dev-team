"""Tests for OutputVerifier raising on missing attribute (T5-B Task 3).

Verifies that:
- verify() raises OutputVerificationError when a required field is absent
- No warnings are emitted (raises instead)
- Empty present fields still raise (existing behaviour preserved)
- All fields present and non-empty: no exception
"""
import pytest
from unittest.mock import MagicMock
from core.output_verifier import OutputVerifier, OutputVerificationError


def _result(**kwargs):
    """Create a mock PipelineResult with given attributes."""
    mock = MagicMock(spec=[])
    for k, v in kwargs.items():
        setattr(mock, k, v)
    return mock


def test_raises_on_missing_attribute():
    """verify() must raise OutputVerificationError when required field is absent."""
    result = _result(prd="A valid PRD")  # no 'design' attribute
    verifier = OutputVerifier(["prd", "design"])

    with pytest.raises(OutputVerificationError) as exc_info:
        verifier.verify(result, "architect")

    assert "design" in str(exc_info.value)
    assert "architect" in str(exc_info.value)


def test_no_warning_emitted_on_missing_attribute(recwarn):
    """warnings.warn must NOT be called for missing attributes (raises instead)."""
    result = _result(prd="ok")  # no 'design'
    verifier = OutputVerifier(["prd", "design"])

    with pytest.raises(OutputVerificationError):
        verifier.verify(result, "stage-x")

    assert len(recwarn) == 0, "No warnings should be emitted"


def test_still_raises_on_empty_present_field():
    """Empty field still raises (existing behaviour preserved)."""
    result = _result(prd="", design="valid design")
    verifier = OutputVerifier(["prd", "design"])

    with pytest.raises(OutputVerificationError) as exc_info:
        verifier.verify(result, "pm")

    assert "prd" in str(exc_info.value)


def test_passes_when_all_fields_present_and_nonempty():
    """No exception when all required fields are present and non-empty."""
    result = _result(prd="A product spec", design="An architecture doc")
    verifier = OutputVerifier(["prd", "design"])
    verifier.verify(result, "architect")  # must not raise
