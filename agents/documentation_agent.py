"""DocumentationAgent: reads repo files via GitHub API tools and writes documentation."""
from __future__ import annotations

import json
import re

from agents.base_agent import BaseAgent
from github_client import GitHubClient
from tools.registry import LocalToolRegistry


class DocumentationAgent(BaseAgent):
    role_name = "documentation_agent"

    def __init__(self, **kwargs) -> None:
        roles_dir = kwargs.pop("roles_dir", None)
        super().__init__(roles_dir=roles_dir, **kwargs)

    def _parse_doc_targets(self, body: str) -> list[str]:
        """Extract file targets from 'Docs: file1, file2' or '**Docs:** file1, file2' in issue body."""
        m = re.search(r"(?<!\w)\*{0,2}Docs:\*{0,2}\s*(.+)", body)
        if not m:
            return []
        return [p.strip() for p in m.group(1).split(",") if p.strip()]

    def _build_file_context(
        self, gh: GitHubClient, doc_targets: list[str], ref: str
    ) -> str:
        """Pre-fetch file content and return as a formatted context block.

        If doc_targets are specified, read those files.
        Otherwise, discover .md files plus repo root listing and read up to 5 files.
        """
        sections: list[str] = []

        # Always include root listing
        try:
            entries = gh.list_files("", ref=ref)
            listing = "\n".join(f"[{e['type']}] {e['path']}" for e in entries)
            sections.append(f"## Repository root\n{listing}")
        except Exception:
            pass

        # Determine which files to read
        if doc_targets:
            paths_to_read = doc_targets
        else:
            # Auto-discover markdown files (cap at 5)
            try:
                paths_to_read = gh.search_files("**/*.md", ref=ref)[:5]
            except Exception:
                paths_to_read = []

        # Read each file and include content
        for path in paths_to_read:
            try:
                content = gh.get_file_content(path, ref=ref)
                if content is not None:
                    sections.append(f"## File: {path}\n```\n{content}\n```")
                else:
                    sections.append(f"## File: {path}\n(does not exist yet — create it)")
            except Exception:
                pass

        if not sections:
            return "No existing files found."
        return "\n\n".join(sections)

    def run(
        self,
        issue_title: str,
        issue_body: str,
        github_client: GitHubClient,
        ref: str = "main",
    ) -> list[dict]:
        """Run the documentation agent.

        Args:
            issue_title: Title of the GitHub issue.
            issue_body: Body text of the GitHub issue.
            github_client: Pre-built GitHubClient for the target repo.
            ref: Git ref (branch/tag/SHA) to read files from.

        Returns a list of {"path", "content", "action"} dicts to commit.
        Raises ValueError if the agent produces no file writes.
        """
        gh = github_client

        # Build LocalToolRegistry wiring the three tools to the GitHub client
        registry = LocalToolRegistry()

        @registry.tool(
            name="list_files",
            description="List files and directories at a path in the target repo.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (empty string for root)"}
                },
                "required": ["path"],
            },
        )
        def _list_files(path: str) -> str:
            entries = gh.list_files(path, ref=ref)
            lines = [f"[{e['type']}] {e['path']}" for e in entries]
            return "\n".join(lines) if lines else "(empty directory)"

        @registry.tool(
            name="read_file",
            description="Read the full text content of a file in the target repo.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to repo root"}
                },
                "required": ["path"],
            },
        )
        def _read_file(path: str) -> str:
            content = gh.get_file_content(path, ref=ref)
            return content if content is not None else f"(file not found: {path})"

        @registry.tool(
            name="search_files",
            description="Find file paths matching a glob pattern (e.g. '**/*.md', '**/*.py').",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern to match file paths"}
                },
                "required": ["pattern"],
            },
        )
        def _search_files(pattern: str) -> str:
            matches = gh.search_files(pattern, ref=ref)
            return "\n".join(matches) if matches else "(no matches)"

        doc_targets = self._parse_doc_targets(issue_body)

        # Pre-fetch file context so the LLM has content without needing read_file calls
        file_context = self._build_file_context(gh, doc_targets, ref)

        user_message = (
            f"## Issue: {issue_title}\n\n{issue_body}\n\n"
            f"{file_context}\n\n"
            "Now produce the documentation updates as a JSON array."
        )

        raw = self.call_with_tools(user_message=user_message, tools=registry)

        # Parse JSON array from response
        try:
            file_writes = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\[.*?\]", raw, re.DOTALL)
            if m:
                try:
                    file_writes = json.loads(m.group(0))
                except json.JSONDecodeError:
                    return []
            else:
                return []

        if not isinstance(file_writes, list) or len(file_writes) == 0:
            raise ValueError(
                f"DocumentationAgent produced no file writes for issue: {issue_title!r}"
            )

        return file_writes
