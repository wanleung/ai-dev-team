"""
EngineerAgent: implements code modules based on the system design.
Supports N parallel workers for independent modules.
"""
from __future__ import annotations

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from .base_agent import BaseAgent


class EngineerAgent(BaseAgent):
    """Engineer Agent — writes code for assigned modules.

    Input:  system design + specific module to implement
    Output: dict of {filepath: code_content} for all files in the module
    """

    role_name = "engineer"

    def run_module(self, design: str, module: dict, project_name: str = "Project") -> dict:
        """Implement a single module.

        Args:
            design: Full system design markdown.
            module: Module dict with 'name' and 'description' keys.
            project_name: Project name for context.

        Returns:
            dict with keys:
                - module_name (str): The module name
                - files (dict): {filepath: file_content} for all generated files
                - raw_response (str): Full LLM response
        """
        prompt = (
            f"You are implementing the '{module['name']}' module for the project '{project_name}'.\n\n"
            f"Module description: {module.get('description', '')}\n\n"
            f"Full System Design:\n---\n{design}\n---\n\n"
            f"Please implement ALL files for this module. "
            f"Output each file using the '### FILE: path/to/file.py' format as instructed."
        )

        response = self.call(prompt)
        files = self._parse_files(response)

        return {
            "module_name": module["name"],
            "files": files,
            "raw_response": response,
        }

    def run_all_modules(
        self,
        design: str,
        modules: list[dict],
        project_name: str = "Project",
        max_workers: int = 3,
    ) -> dict:
        """Implement multiple modules in parallel using a thread pool.

        Args:
            design: Full system design markdown.
            modules: List of module dicts from the Architect.
            project_name: Project name for context.
            max_workers: Maximum parallel LLM calls.

        Returns:
            dict with keys:
                - modules (list[dict]): Each module's run_module() result
                - all_files (dict): Merged {filepath: content} across all modules
        """
        results = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.run_module, design, mod, project_name): mod
                for mod in modules
            }
            for future in futures:
                result = future.result()
                results.append(result)

        # Merge all files across modules
        all_files: dict[str, str] = {}
        for result in results:
            all_files.update(result["files"])

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

        Returns:
            run_all_modules() result plus:
                - branch (str): Created branch name
                - pr_number (int): Pull request number
                - pr_url (str): Pull request URL
        """
        result = self.run_all_modules(design, modules, project_name, max_workers)

        # Create feature branch
        safe_name = re.sub(r"[^a-z0-9-]", "-", project_name.lower())[:40]
        branch_name = f"{branch_prefix}/{safe_name}"
        github_client.create_branch(branch_name)

        # Commit all generated files
        for filepath, content in result["all_files"].items():
            github_client.commit_file(
                path=filepath,
                content=content,
                message=f"feat: implement {filepath} [{project_name}]",
                branch=branch_name,
            )

        # Open a PR
        issue_ref = f"\nCloses #{issue_number}" if issue_number else ""
        pr = github_client.create_pull_request(
            title=f"[Implementation] {project_name}",
            body=(
                f"## 🤖 AI-Generated Implementation\n\n"
                f"This PR was created by the **EngineerAgent** of the AI Software House.\n\n"
                f"**Project:** {project_name}\n"
                f"**Modules implemented:** {', '.join(m['name'] for m in modules)}\n"
                f"**Files:** {len(result['all_files'])}\n"
                f"{issue_ref}"
            ),
            head=branch_name,
            draft=False,
        )

        result["branch"] = branch_name
        result["pr_number"] = pr["number"]
        result["pr_url"] = pr["html_url"]
        return result

    @staticmethod
    def _parse_files(response: str) -> dict[str, str]:
        """Parse '### FILE: path' sections from the LLM response into a dict."""
        files: dict[str, str] = {}
        current_path: Optional[str] = None
        current_lines: list[str] = []
        in_code_block = False

        for line in response.splitlines():
            # Detect FILE header
            if line.strip().startswith("### FILE:"):
                # Save previous file
                if current_path and current_lines:
                    files[current_path] = "\n".join(current_lines).strip()
                current_path = line.strip().removeprefix("### FILE:").strip()
                current_lines = []
                in_code_block = False
                continue

            if current_path is not None:
                # Skip opening/closing code fence
                if line.strip().startswith("```"):
                    in_code_block = not in_code_block
                    continue
                current_lines.append(line)

        # Save last file
        if current_path and current_lines:
            files[current_path] = "\n".join(current_lines).strip()

        # Fallback: if no FILE markers, treat entire response as main.py
        if not files and response.strip():
            files["main.py"] = response.strip()

        return files
