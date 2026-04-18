"""DocumentationAgent: reads repo files via GitHub API tools and writes documentation."""
from __future__ import annotations

import json
import re
from typing import Optional

from agents.base_agent import BaseAgent
from github_client import GitHubClient


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

    def _detect_ref(self, gh: GitHubClient) -> str:
        """Return the repo's default branch (e.g. 'main' or 'master')."""
        try:
            info = gh._request("GET", f"/repos/{gh.repo}")
            return info.get("default_branch", "main")
        except Exception:
            return "main"

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
        ref: Optional[str] = None,
    ) -> list[dict]:
        """Run the documentation agent.

        Args:
            issue_title: Title of the GitHub issue.
            issue_body: Body text of the GitHub issue.
            github_client: Pre-built GitHubClient for the target repo.
            ref: Git ref to read files from. Auto-detected from repo if None.

        Returns a list of {"path", "content", "action"} dicts to commit.
        Raises ValueError if the agent produces no file writes.
        """
        gh = github_client

        # Auto-detect the default branch (handles repos using master, main, etc.)
        if ref is None:
            ref = self._detect_ref(gh)

        doc_targets = self._parse_doc_targets(issue_body)

        # Pre-fetch file content and inject directly into the prompt
        file_context = self._build_file_context(gh, doc_targets, ref)

        user_message = (
            f"## Issue: {issue_title}\n\n{issue_body}\n\n"
            f"{file_context}\n\n"
            "Now produce the documentation updates as a JSON array."
        )

        # Use plain call() — file content is already in the prompt, no tools needed
        raw = self.call(user_message=user_message)

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
