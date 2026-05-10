"""Stage output verification gate.

Inspired by the superpowers verification-before-completion principle:
"NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE."

After a pipeline stage runs successfully, OutputVerifier checks that the
PipelineResult fields the stage is responsible for are non-falsy. If any
required field is absent or empty, it raises OutputVerificationError so the
stage is treated as failed rather than silently completing with missing data.
"""
from __future__ import annotations


class OutputVerificationError(ValueError):
    """Raised when a required PipelineResult field is missing or empty after a stage."""

    def __init__(self, stage_name: str, field: str, reason: str = "empty or None") -> None:
        super().__init__(
            f"Stage '{stage_name}': required field '{field}' is {reason}"
        )
        self.stage_name = stage_name
        self.field = field
        self.reason = reason


class OutputVerifier:
    """Checks that named PipelineResult fields are non-falsy after a stage completes.

    Args:
        required_fields: List of attribute names on PipelineResult that must be
            non-falsy (not None, not empty string, not empty list/dict).
    """

    def __init__(self, required_fields: list[str]) -> None:
        self._required = required_fields

    def verify(self, result: object, stage_name: str) -> None:
        """Assert that all required fields on *result* are non-falsy.

        Args:
            result: A PipelineResult (or any object) to inspect.
            stage_name: Human-readable stage identifier for error messages.

        Raises:
            OutputVerificationError: If any required field is absent from result,
                or is present but None, empty string, or empty collection.
        """
        for field in self._required:
            if not hasattr(result, field):
                raise OutputVerificationError(stage_name, field, reason="missing from result")
            value = getattr(result, field)
            if isinstance(value, str):
                is_empty = not value.strip()
            else:
                is_empty = not value
            if is_empty:
                raise OutputVerificationError(stage_name, field, reason="empty or None")
