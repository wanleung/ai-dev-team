"""Structured pipeline error type replacing bare list[str] on PipelineResult."""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Literal

ERROR_CODES = Literal[
    "AGENT_TIMEOUT",
    "AGENT_CRASH",
    "LLM_RATE_LIMIT",
    "LLM_TIMEOUT",
    "LLM_CIRCUIT_OPEN",
    "GITHUB_API_ERROR",
    "GITHUB_RATE_LIMIT",
    "STAGE_SKIPPED",
    "DLQ_ENQUEUE_FAILED",
    "DEGRADATION_APPLIED",
    "VALIDATION_FAILED",
    "UNKNOWN",
]

import typing as _typing
_VALID_CODES: frozenset[str] = frozenset(_typing.get_args(ERROR_CODES))
_VALID_SEVERITIES: frozenset[str] = frozenset({"warning", "error", "fatal"})


@dataclass
class PipelineError:
    """Structured error for pipeline stages.

    Attributes:
        code: Machine-readable error code from ERROR_CODES.
        stage: Pipeline stage name where the error occurred.
        message: Human-readable error description.
        severity: One of 'warning', 'error', or 'fatal'.
        timestamp: ISO 8601 UTC timestamp with trailing 'Z'.
        context: Optional arbitrary key-value context for debugging.
    """

    code: ERROR_CODES
    stage: str
    message: str
    severity: Literal["warning", "error", "fatal"]
    timestamp: str = field(
        default_factory=lambda: (
            datetime.datetime.now(datetime.timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    )
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.code not in _VALID_CODES:
            raise ValueError(f"Invalid error code: {self.code!r}. Valid codes: {sorted(_VALID_CODES)}")
        if self.severity not in _VALID_SEVERITIES:
            raise ValueError(f"Invalid severity: {self.severity!r}. Valid: {sorted(_VALID_SEVERITIES)}")

    def to_dict(self) -> dict[str, Any]:
        """Serialise the error to a plain dictionary."""
        return {
            "code": self.code,
            "stage": self.stage,
            "message": self.message,
            "severity": self.severity,
            "timestamp": self.timestamp,
            "context": self.context,
        }

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.code} @ {self.stage}: {self.message}"
