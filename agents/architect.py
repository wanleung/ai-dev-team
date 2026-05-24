"""
ArchitectAgent: transforms a PRD into a system design document.
"""
from __future__ import annotations

import re

from .base_agent import BaseAgent


class ArchitectAgent(BaseAgent):
    """Architect Agent — produces a system design from a PRD.

    Input:  PRD markdown (from ProductManagerAgent)
    Output: system design markdown + list of implementation modules
    """

    role_name = "architect"

    def __init__(self, *args, tool_registry: "ToolRegistry | None" = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._tool_registry = tool_registry

    def run(self, prd: str, project_name: str = "Project") -> dict:
        """Produce a system design document from a PRD.

        Args:
            prd: PRD markdown from the PM agent
            project_name: Human-readable project name for context

        Returns:
            dict with 'design' (str) and 'modules' (list[dict])
            Each module: {name: str, description: str, tier: str}
        """
        prompt = (
            f"You have received the following PRD for the project '{project_name}':\n\n"
            f"---\n{prd}\n---\n\n"
            f"Please produce a complete System Design document following your role instructions. "
            f"Make sure to include an 'Implementation Modules' section that clearly lists each "
            f"module/file that needs to be implemented."
        )

        design = self._call_with_tools_or_fallback(prompt)
        modules = self._parse_modules(design)

        return {
            "design": design,
            "modules": modules,
        }

    def run_with_github(self, prd: str, project_name: str, github_client, issue_number: int) -> dict:
        """Run and post the system design as a GitHub Issue comment.

        Args:
            prd: PRD markdown.
            project_name: Project name.
            github_client: A GitHubClient instance.
            issue_number: The PRD issue number to comment on.

        Returns:
            Same as run() result.
        """
        result = self.run(prd, project_name)

        github_client.add_issue_comment(
            issue_number,
            f"## 🏗️ System Design (Architect)\n\n{result['design']}",
        )
        return result

    def run_revision(
        self,
        original_design: str,
        review: str,
        draft_revision: str,
        prd: str,
        project_name: str,
    ) -> dict:
        """Rewrite the system design incorporating reviewer feedback and the reviewer's draft.

        Args:
            original_design, review, draft_revision, prd, project_name

        Returns:
            dict with 'design' (str) and 'modules' (list[dict])
        """
        prompt = self._build_revision_prompt(
            project_name, prd, original_design, review, draft_revision
        )
        design = self._call_with_tools_or_fallback(prompt)
        modules = self._parse_modules(design)
        return {"design": design, "modules": modules}

    def _build_revision_prompt(
        self,
        project_name: str,
        prd: str,
        original_design: str,
        review: str,
        draft_revision: str,
    ) -> str:
        """Build the revision prompt from all input sections."""
        return (
            f"You previously wrote a System Design for the project '{project_name}' that was "
            f"reviewed and needs improvement.\n\n"
            f"## PRD (unchanged)\n---\n{prd}\n---\n\n"
            f"## Your Original System Design\n---\n{original_design}\n---\n\n"
            f"## Reviewer Feedback\n---\n{review}\n---\n\n"
            f"## Reviewer's Suggested Draft (use as direction, not copy-paste)\n"
            f"---\n{draft_revision}\n---\n\n"
            f"Rewrite the System Design addressing the reviewer's concerns. Preserve correct "
            f"decisions. Output a complete, improved System Design following your role instructions. "
            f"Make sure to include an 'Implementation Modules' section."
        )

    def _call_with_tools_or_fallback(self, prompt: str) -> str:
        """Call LLM with optional RAG tool registry support, falling back to plain call.

        Args:
            prompt: The prompt to send to the LLM.

        Returns:
            str: The LLM's response text.
        """
        if self._tool_registry is not None:
            rag_hint = (
                "\n\nYou have access to RAG search tools: `search_memory` and `search_docs`. "
                "Use them to find relevant past designs and documentation before producing the system design."
            )
            try:
                return self.call_with_tools(prompt + rag_hint, tools=self._tool_registry)
            except NotImplementedError:
                return self.call(prompt)
        return self.call(prompt)

    @staticmethod
    def _parse_modules(design: str) -> list[dict]:
        """Extract the list of modules from the system design document."""
        modules = []
        in_modules_section = False

        for line in design.splitlines():
            stripped = line.strip()

            if "implementation modules" in stripped.lower() or "## modules" in stripped.lower():
                in_modules_section = True
                continue

            # Stop at next major section heading
            if in_modules_section and stripped.startswith("## ") and "module" not in stripped.lower():
                break

            # Parse numbered list items
            if in_modules_section and stripped and stripped[0].isdigit():
                module = ArchitectAgent._parse_module_line(stripped)
                if module:
                    modules.append(module)

        # Fallback: return a generic single module if parsing fails
        if not modules:
            modules = [{"name": "main", "description": "Main application module", "tier": "senior"}]

        return modules

    @staticmethod
    def _parse_module_line(stripped: str) -> dict | None:
        """Parse a single numbered module line into a dict."""
        content = stripped.split(". ", 1)[-1] if ". " in stripped else stripped
        if ":" not in content:
            name = content.strip("* ").strip()
            return {"name": name, "description": "", "tier": "senior"} if name else None

        last_colon_idx = content.rfind(":")
        name_part = content[:last_colon_idx].strip()
        desc = content[last_colon_idx + 1:].strip()

        # Extract tier tag
        tier = "senior"
        tier_match = re.search(r'\[tier:(junior|senior)\]', name_part + " " + desc)
        if tier_match:
            tier = tier_match.group(1)

        # Extract name from **name** if present
        bold_match = re.search(r'\*\*(.*?)\*\*', name_part)
        name = bold_match.group(1) if bold_match else name_part.strip("* ").strip()

        # Remove tier tag from both name and desc
        name = re.sub(r'\s*\[tier:(?:junior|senior)\]', '', name).strip()
        desc = re.sub(r'\s*\[tier:(?:junior|senior)\]', '', desc).strip()

        return {"name": name, "description": desc, "tier": tier} if name else None
