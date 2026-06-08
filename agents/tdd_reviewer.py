"""TDDReviewerAgent: reviews TDD test files for correctness and PRD coverage.

Sits between qa_write (test generation) and test_fix (test execution) in the
TDD pipeline. Makes one LLM call to:
  1. Fix correctness issues (wrong conftest scope, bad imports, syntax errors).
  2. Improve quality (flag weak assertions, add missing PRD coverage).

Returns revised test files + a plain-text review summary.
Never raises — on any failure it returns the original files unchanged.
"""
from __future__ import annotations

import ast
import logging

from .base_agent import BaseAgent

_log = logging.getLogger(__name__)

_REVIEW_SUMMARY_HEADER = "### REVIEW SUMMARY:"
_FILE_HEADER_PREFIX = "### FILE:"


class TDDReviewerAgent(BaseAgent):
    """Reviews and auto-fixes generated TDD test files.

    Input:  test_files dict, PRD string, project name
    Output: (revised_files dict, review_summary str)
    """

    role_name = "tdd_reviewer"

    def run(
        self,
        test_files: dict[str, str],
        prd: str,
        project_name: str = "Project",
    ) -> tuple[dict[str, str], str]:
        """Review test files for correctness and PRD coverage; auto-fix issues.

        Args:
            test_files: dict of {filepath: content} from QAEngineerAgent.
            prd: PRD markdown — used to check coverage.
            project_name: project name for context.

        Returns:
            (revised_files, review_summary) — revised_files equals test_files
            if the LLM call fails or returns no file blocks.
        """
        if not test_files:
            return test_files, ""

        prompt = self._build_prompt(test_files, prd, project_name)
        try:
            response = self.call(prompt)
        except Exception as exc:  # noqa: BLE001
            _log.warning("TDDReviewer LLM call failed: %s — returning original files", exc)
            return test_files, ""

        revised, summary = self._parse_review_response(response)

        if not revised:
            _log.info("TDDReviewer returned no file blocks — keeping original files")
            return test_files, summary

        # Validate syntax; retry once if errors remain.
        errors = self._collect_syntax_errors(revised)
        if errors:
            _log.info("TDDReviewer: syntax errors after review, retrying: %s", errors)
            try:
                retry_result, retry_summary = self._retry_syntax_fix(prompt, revised, errors)
                if retry_result is not None:
                    revised, summary = retry_result, retry_summary
                else:
                    _log.warning("TDDReviewer syntax-fix retry returned no files — returning original files")
                    return test_files, ""
            except Exception as exc:  # noqa: BLE001
                _log.warning("TDDReviewer syntax-fix retry failed: %s — returning original files", exc)
                return test_files, ""

        return revised, summary

    # ── Prompt builder ──────────────────────────────────────────────────────

    def _build_prompt(
        self, test_files: dict[str, str], prd: str, project_name: str
    ) -> str:
        """Build the LLM prompt for reviewing test files.

        Args:
            test_files: dict of {filepath: content} to review.
            prd: PRD markdown string for coverage checking.
            project_name: project name for context.

        Returns:
            Fully formatted prompt string.
        """
        files_section = "\n\n".join(
            f"### FILE: {path}\n```python\n{content}\n```"
            for path, content in test_files.items()
        )
        return (
            f"You are a senior Python test engineer reviewing TDD test files "
            f"before implementation begins.\n\n"
            f"## Project: {project_name}\n\n"
            f"## PRD:\n{prd}\n\n"
            f"## Test Files to Review:\n{files_section}\n\n"
            f"## Your Task\n\n"
            f"Perform TWO passes:\n\n"
            f"### Pass 1 — Correctness\n"
            f"Fix any issues that would prevent pytest from collecting or running tests:\n"
            f"- `from conftest import X` patterns: if X is a plain class or helper "
            f"(not decorated with @pytest.fixture), it must live in the ROOT conftest.py "
            f"so `from conftest import X` resolves correctly when pytest runs from the "
            f"project root. Move such helpers to the root conftest.py (project root level).\n"
            f"- Import paths that assume an app structure not guaranteed by the PRD "
            f"(e.g. `from app.main import app` when the PRD does not specify that path).\n"
            f"- Any syntax errors.\n\n"
            f"### Pass 2 — Quality\n"
            f"Check coverage against the PRD:\n"
            f"- Every major feature/endpoint mentioned in the PRD should have at least "
            f"one test.\n"
            f"- Every test should have a meaningful assertion (not just `assert True` "
            f"or `assert response is not None`).\n"
            f"- Every tested feature should have at least one error/edge-case test.\n"
            f"- Add concise tests for any obvious gaps (keep each function ≤80 lines).\n\n"
            f"## Output Format\n\n"
            f"Output ALL test files (modified or unchanged) using the ### FILE: format:\n\n"
            f"### FILE: tests/conftest.py\n"
            f"```python\n"
            f"# ... file content ...\n"
            f"```\n\n"
            f"Then output:\n\n"
            f"### REVIEW SUMMARY:\n"
            f"- Correctness fixes: [list what was fixed, or 'none']\n"
            f"- Quality additions: [list what was added/improved, or 'none']\n"
            f"- Remaining concerns: [anything the engineer should know, or 'none']\n"
        )

    # ── Response parser ─────────────────────────────────────────────────────

    @staticmethod
    def _parse_review_response(response: str) -> tuple[dict[str, str], str]:
        """Parse ### FILE: blocks and ### REVIEW SUMMARY: from LLM response.

        Returns (files_dict, summary_str). Either may be empty.
        """
        files: dict[str, str] = {}
        summary = ""
        current_path: str | None = None
        current_lines: list[str] = []
        in_code_block = False
        saw_fence = False
        in_summary = False
        summary_lines: list[str] = []

        for line in response.splitlines():
            stripped = line.strip()

            # Summary section starts after ### REVIEW SUMMARY: and runs to end.
            if stripped.startswith(_REVIEW_SUMMARY_HEADER):
                if current_path and current_lines:
                    files[current_path] = "\n".join(current_lines).strip()
                    current_path, current_lines = None, []
                in_summary = True
                continue

            if in_summary:
                summary_lines.append(line)
                continue

            if stripped.startswith(_FILE_HEADER_PREFIX):
                if current_path and current_lines:
                    files[current_path] = "\n".join(current_lines).strip()
                current_path = stripped.removeprefix(_FILE_HEADER_PREFIX).strip()
                current_lines, in_code_block, saw_fence = [], False, False
                continue

            if current_path is not None:
                if stripped.startswith("```"):
                    if not in_code_block:
                        saw_fence = True
                    in_code_block = not in_code_block
                    continue
                if not saw_fence or in_code_block:
                    current_lines.append(line)

        if current_path and current_lines:
            files[current_path] = "\n".join(current_lines).strip()

        summary = "\n".join(summary_lines).strip()
        return files, summary

    # ── Syntax helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _collect_syntax_errors(files: dict[str, str]) -> list[str]:
        """Return list of 'filename: SyntaxError msg (line N)' for invalid .py files."""
        errors = []
        for filename, source in files.items():
            if not filename.endswith(".py"):
                continue
            try:
                ast.parse(source)
            except SyntaxError as exc:
                errors.append(f"{filename}: {exc.msg} (line {exc.lineno})")
        return errors

    def _retry_syntax_fix(
        self,
        original_prompt: str,
        files: dict[str, str],
        errors: list[str],
    ) -> tuple[dict[str, str] | None, str]:
        """Ask LLM to fix syntax errors; return (revised_files, summary).

        Args:
            original_prompt: The original review prompt sent to the LLM.
            files: The files dict returned by the first LLM call (with errors).
            errors: List of syntax error strings from _collect_syntax_errors.

        Returns:
            (revised_files, summary) from the retry response, or (None, summary)
            if the retry returns no file blocks (caller should fall back to
            original test_files).
        """
        error_list = "\n".join(f"  - {e}" for e in errors)
        retry_prompt = (
            f"{original_prompt}\n\n---\n"
            f"The previous output had Python syntax errors:\n{error_list}\n\n"
            f"Fix the syntax errors and output ALL files again in ### FILE: format."
        )
        response = self.call(retry_prompt)
        revised, summary = TDDReviewerAgent._parse_review_response(response)
        return revised if revised else None, summary
