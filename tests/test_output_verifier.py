"""Tests for OutputVerifier — post-stage field validation gate."""
from __future__ import annotations

import pytest
from core.output_verifier import OutputVerifier, OutputVerificationError


def _make_result(**kwargs):
    """Return a minimal namespace object for testing."""
    class _R:
        pass
    r = _R()
    for k, v in kwargs.items():
        setattr(r, k, v)
    return r


def test_verify_passes_when_all_fields_present():
    """No exception when all required fields are non-empty."""
    result = _make_result(prd="A product doc", architecture="Arch diagram")
    verifier = OutputVerifier(required_fields=["prd", "architecture"])
    verifier.verify(result, stage_name="architect")  # should not raise


def test_verify_raises_on_none_field():
    """OutputVerificationError raised when a required field is None."""
    result = _make_result(prd=None)
    verifier = OutputVerifier(required_fields=["prd"])
    with pytest.raises(OutputVerificationError, match="prd"):
        verifier.verify(result, stage_name="product_manager")


def test_verify_raises_on_empty_string_field():
    """OutputVerificationError raised when a required field is an empty string."""
    result = _make_result(architecture="")
    verifier = OutputVerifier(required_fields=["architecture"])
    with pytest.raises(OutputVerificationError, match="architecture"):
        verifier.verify(result, stage_name="architect")


def test_verify_raises_on_empty_list_field():
    """OutputVerificationError raised when a required field is an empty list."""
    result = _make_result(modules=[])
    verifier = OutputVerifier(required_fields=["modules"])
    with pytest.raises(OutputVerificationError, match="modules"):
        verifier.verify(result, stage_name="tier_review")


def test_verify_skips_missing_attribute_with_warning():
    """If the result object lacks the field entirely, warn but do not raise."""
    import warnings
    result = _make_result()  # no attributes
    verifier = OutputVerifier(required_fields=["prd"])
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        verifier.verify(result, stage_name="product_manager")
    assert any("prd" in str(warning.message) for warning in w)


def test_empty_required_fields_always_passes():
    """OutputVerifier with no required_fields is a no-op."""
    result = _make_result()
    verifier = OutputVerifier(required_fields=[])
    verifier.verify(result, stage_name="any_stage")  # should not raise


def test_verify_raises_on_whitespace_only_string():
    """OutputVerificationError raised when a required field is whitespace only.

    Bug 4 fix: ``'\\n\\n'`` is truthy but represents an empty LLM output.
    OutputVerifier must strip strings before checking for emptiness.
    """
    result = _make_result(prd="\n\n")
    verifier = OutputVerifier(required_fields=["prd"])
    with pytest.raises(OutputVerificationError, match="prd"):
        verifier.verify(result, stage_name="product_manager")


def test_verify_raises_on_spaces_only_string():
    """OutputVerificationError raised when a required field is all spaces."""
    result = _make_result(design="   \t   ")
    verifier = OutputVerifier(required_fields=["design"])
    with pytest.raises(OutputVerificationError, match="design"):
        verifier.verify(result, stage_name="architect")


def test_verify_passes_for_string_with_content_and_surrounding_whitespace():
    """A string that has real content despite surrounding whitespace should pass."""
    result = _make_result(prd="  some real content  ")
    verifier = OutputVerifier(required_fields=["prd"])
    verifier.verify(result, stage_name="product_manager")  # should not raise
