"""Domain-specific exceptions for the AI software-house orchestrator.

These exceptions are raised for configuration and setup errors that should
surface immediately (at load time) rather than failing silently at runtime.
"""
from __future__ import annotations


class ConfigurationError(Exception):
    """Raised when a pipeline or orchestrator configuration is invalid.

    Examples:
        - A pipeline YAML references a stage name that is not in the registry.
        - A required configuration key is missing or has an invalid value.

    This replaces silent ``logging.warning`` calls so that misconfigured
    pipelines are caught early with a clear, actionable message.
    """
