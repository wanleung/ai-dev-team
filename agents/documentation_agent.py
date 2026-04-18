"""DocumentationAgent: reads repo files via GitHub API tools and writes documentation."""
from __future__ import annotations

import json
import re
from typing import Optional

from agents.base_agent import BaseAgent
from github_client import GitHubClient
from tools.registry import LocalToolRegistry


_SYSTEM_PROMPT = """\
You are a technical documentation writer for a software project.

You have three tools to read files from the target repository:
- list_files(path): list files and directories at a path (use "" for root)
- read_file(path): read the full content of a file
- search_files(pattern): find files matching a glob (e.g. "**/*.md", "**/*.py")

Your task:
1. Read the issue title and body carefully.
2. If the body contains "**Docs:** file1, file2", read those files first.
3. Otherwise, discover relevant documentation files by listing/searching the repo.
4. Read related source files when you need to document APIs, classes, or functions.
5. Produce updated or new documentation that fully addresses the issue.

When you are done reading and are ready to write, return ONLY a JSON array (no markdown
fences, no explanation) of file write objects:

[
  {"path": "README.md", "content": "# Full updated content here\\n", "action": "update"},
  {"path": "docs/new-guide.md", "content": "# New Guide\\n...", "action": "create"}
]

Rules:
- "action" must be "create" or "update"
- "content" must be the COMPLETE file content (not a diff)
- Do not include files you did not change
- Return an empty array [] ONLY if nothing needs changing (but try hard to be useful)
"""


class DocumentationAgent(BaseAgent):
    role_name = None  # We set system_prompt directly, not from a file

    def __init__(self, **kwargs) -> None:
        roles_dir = kwargs.pop("roles_dir", None)
        super().__init__(roles_dir=roles_dir, **kwargs)
        self.system_prompt = _SYSTEM_PROMPT

    def _parse_doc_targets(self, body: str) -> list[str]:
        """Extract file targets from '**Docs:** file1, file2' in issue body."""
        m = re.search(r"\*\*Docs:\*\*\s*(.+)", body)
        if not m:
            return []
        return [p.strip() for p in m.group(1).split(",") if p.strip()]

    def run(
        self,
        issue_title: str,
        issue_body: str,
        target_repo: str,
        github_token: Optional[str] = None,
        ref: str = "main",
    ) -> list[dict]:
        """Run the documentation agent.

        Returns a list of {"path", "content", "action"} dicts to commit.
        Raises ValueError if the agent produces no file writes.
        """
        gh = GitHubClient(target_repo, token=github_token)

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

        user_message = (
            f"## Issue: {issue_title}\n\n{issue_body}\n\n"
            "Please read the relevant files and produce the documentation updates."
        )

        raw = self.call_with_tools(user_message=user_message, tools=registry)

        # Parse JSON array from response
        try:
            file_writes = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\[.*\]", raw, re.DOTALL)
            if m:
                file_writes = json.loads(m.group(0))
            else:
                raise ValueError(f"Agent returned non-JSON response: {raw[:200]}")

        if not isinstance(file_writes, list) or len(file_writes) == 0:
            raise ValueError(
                f"DocumentationAgent produced no file writes for issue: {issue_title!r}"
            )

        return file_writes
