"""
EngineerAgent: implements code modules based on the system design.
Supports N parallel workers for independent modules.
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Optional

from .base_agent import BaseAgent
from .tool_capable import ToolCapableAgentMixin
if TYPE_CHECKING:
    from tools.registry import ToolRegistry

_log = logging.getLogger(__name__)


class EngineerAgent(ToolCapableAgentMixin, BaseAgent):
    """Engineer Agent — writes code for assigned modules.

    Input:  system design + specific module to implement
    Output: dict of {filepath: code_content} for all files in the module
    """

    role_name = "engineer"

    def __init__(self, *args, tool_registry: "ToolRegistry | None" = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._tool_registry = tool_registry

    def run_module(
        self,
        design: str,
        module: dict,
        project_name: str = "Project",
        framework_context: str = "",
        all_files: dict[str, str] | None = None,
        test_files: dict[str, str] | None = None,
    ) -> dict:
        """Implement a single module.

        Args:
            design: Full system design markdown.
            module: Module dict with 'name' and 'description' keys.
            project_name: Project name for context.
            framework_context: Optional framework documentation to inject into the prompt.
            all_files: Optional dict of already-implemented files (used by senior engineer).
            test_files: Optional dict of pre-written test files (TDD mode). When provided,
                        the engineer is instructed to make these tests pass.

        Returns:
            dict with keys:
                - module_name (str): The module name
                - files (dict): {filepath: file_content} for all generated files
                - raw_response (str): Full LLM response
        """
        framework_section = f"## Framework Documentation\n\n{framework_context}\n\n" if framework_context else ""
        scaffold_hint = "\n\n> Note: If you scaffold a new project, check for AGENTS.md afterwards for framework-specific guidance." if not framework_context else ""
        test_section = self._build_test_section(test_files)
        prompt = self._build_module_prompt(module, design, project_name, framework_section, test_section, scaffold_hint)
        response = self._call_llm_with_tools(prompt)
        files = self._parse_files(response)
        files = self._enforce_function_size_rule(prompt, files)
        return {"module_name": module["name"], "files": files, "raw_response": response}

    def run_all_modules(
        self,
        design: str,
        modules: list[dict],
        project_name: str = "Project",
        max_workers: int = 3,
        framework_context: str = "",
        test_files: dict[str, str] | None = None,
    ) -> dict:
        """Implement multiple modules in parallel using a thread pool.

        Args:
            design: Full system design markdown.
            modules: List of module dicts from the Architect.
            project_name: Project name for context.
            max_workers: Maximum parallel LLM calls.
            framework_context: Optional framework documentation to inject into each module's prompt.
            test_files: Optional dict of pre-written test files (TDD mode).

        Returns:
            dict with keys:
                - modules (list[dict]): Each module's run_module() result
                - all_files (dict): Merged {filepath: content} across all modules
        """
        results = self._submit_module_futures(modules, design, project_name, framework_context, test_files, max_workers)
        all_files = self._merge_module_files(results)
        return {"modules": results, "all_files": all_files}

    def run_with_github(
        self,
        design: str,
        modules: list[dict],
        project_name: str,
        github_client,
        branch_prefix: str = "feature/agent",
        issue_number: Optional[int] = None,
        max_workers: int = 3,
        framework_context: str = "",
        test_files: dict[str, str] | None = None,
    ) -> dict:
        """Run all modules and commit code to GitHub on a feature branch, then open a PR.

        Args:
            design: System design markdown.
            modules: List of modules from the Architect.
            project_name: Project name.
            github_client: GitHubClient instance.
            branch_prefix: Prefix for the feature branch name.
            issue_number: PRD issue number to reference in the PR.
            max_workers: Parallel engineer workers.
            framework_context: Optional framework documentation to inject into each module's prompt.
            test_files: Optional dict of pre-written test files (TDD mode).

        Returns:
            run_all_modules() result plus:
                - branch (str): Created branch name
                - pr_number (int): Pull request number
                - pr_url (str): Pull request URL
        """
        result = self.run_all_modules(design, modules, project_name, max_workers, framework_context=framework_context, test_files=test_files)
        safe_name = re.sub(r"[^a-z0-9-]", "-", project_name.lower())[:40].strip("-") or "auto"
        branch_name = f"{branch_prefix}/{safe_name}"
        github_client.create_branch(branch_name)
        self._commit_files_to_branch(github_client, result["all_files"], branch_name, project_name)
        pr = self._open_implementation_pr(github_client, project_name, modules, branch_name, issue_number, len(result["all_files"]))
        result["branch"] = branch_name
        result["pr_number"] = pr["number"]
        result["pr_url"] = pr["html_url"]
        return result

    def fix_failures(
        self,
        failure_output: str,
        all_files: dict[str, str],
        design: str,
        project_name: str = "Project",
        framework_context: str = "",
    ) -> dict[str, str]:
        """Produce targeted code fixes for failing tests.

        Args:
            failure_output: The test failure output (e.g. pytest stderr/stdout).
            all_files: {filepath: content} of all current project source files.
            design: Full system design markdown.
            project_name: Project name for context.
            framework_context: Optional framework documentation to prepend to the prompt.

        Returns:
            {filepath: content} of ONLY the files that need to change.
            Empty dict if the LLM returns no parseable file blocks.
        """
        prompt = self._build_fix_prompt(failure_output, all_files, design, project_name, framework_context)
        response = self.call(prompt)
        if not response or "### FILE:" not in response:
            return {}
        return self._parse_files(response)

    @staticmethod
    def _sanitize_path(path: str) -> str | None:
        """Validate and normalise a file path from LLM output.

        Returns the normalised path, or *None* if the path is unsafe
        (directory traversal, absolute path, or outside project root).
        """
        import posixpath
        # Reject absolute paths
        if path.startswith("/") or path.startswith("\\"):
            return None
        # Normalise to collapse ``..``, ``.``, double slashes
        normalised = posixpath.normpath(path)
        # Reject traversal — normpath resolves ``..`` at the start as ``..``
        if normalised.startswith("..") or "/../" in normalised:
            return None
        # Reject Windows-style traversal
        if "..\\" in path or normalised.startswith("..\\"):
            return None
        # Reject empty or current-dir-only
        if normalised in ("", "."):
            return None
        return normalised

    @staticmethod
    def _parse_files(response: str) -> dict[str, str]:
        """Parse '### FILE: path' sections from the LLM response into a dict."""
        files, current_path, current_lines = {}, None, []
        in_code_block = False
        saw_fence = False
        for line in response.splitlines():
            if line.strip().startswith("### FILE:"):
                if current_path and current_lines:
                    files[current_path] = "\n".join(current_lines).strip()
                raw_path = line.strip().removeprefix("### FILE:").strip()
                current_path = EngineerAgent._sanitize_path(raw_path)
                current_lines, in_code_block, saw_fence = [], False, False
                continue
            if current_path is not None:
                stripped = line.strip()
                if stripped.startswith("```"):
                    if not in_code_block:
                        saw_fence = True
                    in_code_block = not in_code_block
                    continue
                # Only collect lines inside a code fence (once a fence has been seen).
                # If no fence has been encountered yet, collect all lines (unfenced files).
                if not saw_fence or in_code_block:
                    current_lines.append(line)
        if current_path and current_lines:
            files[current_path] = "\n".join(current_lines).strip()
        if not files and response.strip():
            files["main.py"] = response.strip()
        return files

    def _build_test_section(self, test_files: dict[str, str] | None) -> str:
        """Build the test section for the prompt."""
        return self._build_test_section_static(test_files)

    @staticmethod
    def _build_test_section_static(test_files: dict[str, str] | None) -> str:
        """Build the test section for the prompt (static implementation)."""
        if not test_files:
            return ""
        MAX_FILE_CHARS, MAX_TOTAL_CHARS = 3000, 10000
        parts = [
            f"### FILE: {path}\n```python\n{content[:MAX_FILE_CHARS]}{f'... (truncated, {len(content)} chars total)' if len(content) > MAX_FILE_CHARS else ''}\n```"
            for path, content in test_files.items()
        ]
        test_section_body = "\n\n".join(parts)
        if len(test_section_body) > MAX_TOTAL_CHARS:
            test_section_body = test_section_body[:MAX_TOTAL_CHARS] + "\n... (additional test files truncated)"
        return (
            f"\n\n## Pre-written tests your implementation must pass\n\n"
            f"{test_section_body}\n\n"
            f"Implement the module so all of the above tests pass. "
            f"Do not modify the test files."
        )

    def _build_module_prompt(
        self, module: dict, design: str, project_name: str,
        framework_section: str, test_section: str, scaffold_hint: str
    ) -> str:
        """Build the complete module implementation prompt."""
        return (
            f"{framework_section}"
            f"You are implementing the '{module['name']}' module for the project '{project_name}'.\n\n"
            f"Module description: {module.get('description', '')}\n\n"
            f"Full System Design:\n---\n{design}\n---"
            f"{test_section}\n\n"
            f"Please implement ALL files for this module. "
            f"Output each file using the '### FILE: path/to/file.py' format as instructed."
            f"{scaffold_hint}"
        )

    @property
    def _file_parser(self) -> callable:
        """Parse ``### FILE: path`` sections from LLM output."""
        return self._parse_files

    def _submit_module_futures(
        self, modules: list[dict], design: str, project_name: str,
        framework_context: str, test_files: dict[str, str] | None, max_workers: int
    ) -> list[dict]:
        """Submit module implementation tasks to thread pool and collect results."""
        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for i, mod in enumerate(modules):
                if i > 0:
                    time.sleep(2)  # Avoid burst rate limits
                futures.append(
                    executor.submit(
                        self.run_module, design, mod, project_name, framework_context,
                        all_files=None, test_files=test_files
                    )
                )
            results = [future.result() for future in futures]
        return results

    @staticmethod
    def _merge_module_files(results: list[dict]) -> dict[str, str]:
        """Merge all files across module results."""
        all_files: dict[str, str] = {}
        for result in results:
            all_files.update(result["files"])
        return all_files

    @staticmethod
    def _commit_files_to_branch(
        github_client, files: dict[str, str], branch_name: str, project_name: str
    ) -> None:
        """Commit all generated files to the feature branch."""
        for filepath, content in files.items():
            github_client.commit_file(
                path=filepath,
                content=content,
                message=f"feat: implement {filepath} [{project_name}]",
                branch=branch_name,
            )

    @staticmethod
    def _open_implementation_pr(
        github_client, project_name: str, modules: list[dict],
        branch_name: str, issue_number: Optional[int], file_count: int
    ) -> dict:
        """Create and return the implementation PR."""
        issue_ref = f"\nCloses #{issue_number}" if issue_number else ""
        return github_client.create_pull_request(
            title=f"[Implementation] {project_name}",
            body=(
                f"## 🤖 AI-Generated Implementation\n\n"
                f"This PR was created by the **EngineerAgent** of the AI Software House.\n\n"
                f"**Project:** {project_name}\n"
                f"**Modules implemented:** {', '.join(m['name'] for m in modules)}\n"
                f"**Files:** {file_count}\n"
                f"{issue_ref}"
            ),
            head=branch_name,
            draft=False,
        )

    def _build_fix_prompt(
        self, failure_output: str, all_files: dict[str, str],
        design: str, project_name: str, framework_context: str
    ) -> str:
        """Build the fix failures prompt."""
        framework_section = (
            f"## Framework Documentation\n\n{framework_context}\n\n"
            if framework_context else ""
        )
        files_section = "\n\n".join(
            f"## File: {path}\n\n````\n{content}\n````"
            for path, content in all_files.items()
        )
        test_file_instruction = self._build_test_file_fix_instruction(failure_output)
        return (
            f"{framework_section}"
            f"You are fixing test failures in the project '{project_name}'.\n\n"
            f"## Test Failure Output\n\n````\n{failure_output}\n````\n\n"
            f"## Current Project Files\n\n{files_section}\n\n"
            f"## System Design\n\n{design}\n\n"
            f"Read the test failure output carefully. Identify the root cause.\n"
            f"{test_file_instruction}\n"
            f"Return ONLY the files that need to change, using the '### FILE: path/to/file.py' format.\n"
            f"Do not return files that do not need to change."
        )

    @staticmethod
    def _build_test_file_fix_instruction(failure_output: str) -> str:
        if _failure_is_invalid_generated_test(failure_output):
            return (
                "The failure is caused by invalid generated pytest files, not only app code. "
                "You MAY modify generated test files and test helpers to make pytest collect and run. "
                "Do not import from conftest.py; move helper classes/functions to tests/helpers.py. "
                "Request pytest fixtures as test function parameters and do not call fixture functions directly."
            )
        return "Fix ONLY the broken source files. Do NOT modify test files."


def _failure_is_invalid_generated_test(failure_output: str) -> bool:
    markers = (
        "ERROR collecting tests/",
        "ImportError while loading conftest",
        "ImportError while importing test module",
        "from tests.conftest import",
        "from conftest import",
        "Fixture \"",
        "Fixtures are not meant to be called directly",
        "SyntaxError: invalid syntax",
    )
    return any(marker in failure_output for marker in markers)
