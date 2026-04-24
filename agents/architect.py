"""
ArchitectAgent: transforms a PRD into a system design document.
"""
from __future__ import annotations

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
            prd: The PRD markdown from the PM agent.
            project_name: Human-readable project name for context.

        Returns:
            dict with keys:
                - design (str): Full system design markdown
                - modules (list[dict]): Parsed list of modules to implement
                  Each module: {name: str, description: str}
        """
        prompt = (
            f"You have received the following PRD for the project '{project_name}':\n\n"
            f"---\n{prd}\n---\n\n"
            f"Please produce a complete System Design document following your role instructions. "
            f"Make sure to include an 'Implementation Modules' section that clearly lists each "
            f"module/file that needs to be implemented."
        )

        if self._tool_registry is not None:
            rag_hint = (
                "\n\nYou have access to RAG search tools: `search_memory` and `search_docs`. "
                "Use them to find relevant past designs and documentation before producing the system design."
            )
            try:
                design = self.call_with_tools(prompt + rag_hint, tools=self._tool_registry)
            except NotImplementedError:
                design = self.call(prompt)
        else:
            design = self.call(prompt)
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
            original_design: The system design that was reviewed.
            review: Reviewer's feedback text.
            draft_revision: Reviewer's suggested rewrite (use as direction, not copy-paste).
            prd: Current PRD (for context).
            project_name: Current project name.

        Returns:
            dict with keys:
                - design (str): Improved system design markdown
                - modules (list[dict]): Re-parsed implementation modules
        """
        prompt = (
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

        if self._tool_registry is not None:
            try:
                design = self.call_with_tools(prompt, tools=self._tool_registry)
            except NotImplementedError:
                design = self.call(prompt)
        else:
            design = self.call(prompt)

        modules = self._parse_modules(design)
        return {
            "design": design,
            "modules": modules,
        }

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

            # Parse numbered list items: "1. **module_name**: description"
            if in_modules_section and stripped and stripped[0].isdigit():
                # Remove leading "1. " etc.
                content = stripped.split(". ", 1)[-1] if ". " in stripped else stripped
                # Split on ":" for name/description
                if "**" in content and "**:" in content:
                    parts = content.split("**:", 1)
                    name = parts[0].strip("* ").strip()
                    desc = parts[1].strip() if len(parts) > 1 else ""
                elif ":" in content:
                    name, _, desc = content.partition(":")
                    name = name.strip("* ").strip()
                    desc = desc.strip()
                else:
                    name = content.strip("* ").strip()
                    desc = ""

                if name:
                    modules.append({"name": name, "description": desc})

        # Fallback: return a generic single module if parsing fails
        if not modules:
            modules = [{"name": "main", "description": "Main application module"}]

        return modules
