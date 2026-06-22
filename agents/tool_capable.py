"""ToolCapableAgentMixin — shared tool-calling and 80-line enforcement logic.

Mixed into EngineerAgent and QAEngineerAgent to eliminate ~180 lines of
duplicated code.  Subclasses override ``_rag_hint`` and ``_file_parser`` to
customise behaviour.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

_log = logging.getLogger(__name__)


class ToolCapableAgentMixin:
    """Mixin for agents that call LLMs with optional RAG tool support.

    Requires the host class to:
    - inherit from ``BaseAgent`` (provides ``call``, ``call_with_tools``,
      ``_validate_code_strings``)
    - set ``self._tool_registry`` in ``__init__``
    """

    _tool_registry: ToolRegistry | None

    # ── Override points ──────────────────────────────────────────────────────

    @property
    def _rag_hint(self) -> str:
        """RAG tool hint appended to prompts when tools are available."""
        return (
            "\n\nYou have access to RAG search tools: `search_codebase` and `search_docs`. "
            "Use them to find relevant existing code patterns and documentation before implementing."
        )

    @property
    def _file_parser(self) -> Callable[[str], dict[str, str]]:
        """Return the static ``_parse_files`` / ``_parse_test_files`` method."""
        raise NotImplementedError("Subclass must set _file_parser")

    @property
    def _size_fix_label(self) -> str:
        """Label used in the 80-line violation prompt (e.g. 'functions', 'test helper functions')."""
        return "functions"

    # ── Shared implementations ───────────────────────────────────────────────

    def _call_llm_with_tools(self, prompt: str, *, write_only: bool = False) -> str:
        """Call LLM with optional RAG tool registry support.

        When *write_only* is True, tools are skipped (used by QA for TDD
        write-first passes where searching existing code is not useful).
        """
        if self._tool_registry is not None and not write_only:
            try:
                return self.call_with_tools(prompt + self._rag_hint, tools=self._tool_registry)
            except NotImplementedError:
                return self.call(prompt)
        return self.call(prompt)

    def _enforce_function_size_rule(
        self, original_prompt: str, files: dict[str, str]
    ) -> dict[str, str]:
        """Validate generated files against the 80-line rule and retry once.

        Returns the (possibly revised) files dict.  Never raises — if
        validation or the retry itself fails, returns the original files.
        """
        violations = self._validate_code_strings(files)
        if not violations:
            return files
        _log.info("80-line violations found, requesting fix: %s", violations)
        try:
            revised = self._request_function_size_fix(original_prompt, files, violations)
        except Exception as exc:  # noqa: BLE001
            _log.warning("80-line retry failed: %s — keeping original output", exc)
    def _request_function_size_fix(
        self, original_prompt: str, files: dict[str, str], violations: list[str]
    ) -> dict[str, str]:
        """Ask the LLM to split oversized functions and return revised files."""
        self._cap_history(max_exchanges=3)  # Prevent context blow-up in fix loops
        violation_list = "\n".join(f"  - {v}" for v in violations)
        fix_prompt = (
            f"{original_prompt}\n\n"
            f"---\n"
            f"The following {self._size_fix_label} in your output exceed the 80-line rule:\n"
            f"{violation_list}\n\n"
            f"Please rewrite ONLY these {self._size_fix_label}, splitting each into smaller helpers "
            f"(≤80 lines each) with clear, descriptive names. "
            f"Output ALL files again using the '### FILE: path' format, including the revised {self._size_fix_label}."
        )
        revised_response = self._call_llm_with_tools(fix_prompt)
        return self._file_parser(revised_response) or files
