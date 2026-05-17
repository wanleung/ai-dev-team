"""FailureRecord — passed to LearningAgent when a validation failure or PR review rejection occurs."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class FailureRecord:
    """Describes a single agent failure event for the LearningAgent to process.

    Attributes:
        agent_role: The role_name of the agent that produced the failure (e.g. "engineer").
        error: The error message or review comment that identified the failure.
        fix: The corrected code snippet or human explanation of what should have been done.
        pipeline: Which pipeline triggered this failure (e.g. "ai-feature", "ai-fix").
        timestamp: ISO-8601 timestamp of when the failure occurred.
        target_repo: GitHub repo slug (owner/name) of the target repo if this failure
                     occurred while working on an external repo. None means the failure
                     was in ai-software-house itself.
    """
    agent_role: str
    error: str
    fix: str
    pipeline: str
    timestamp: str
    target_repo: Optional[str] = None
