"""DocumentationAgent: reads repo files via GitHub API tools and writes documentation."""
from __future__ import annotations

import json
import re
from typing import Optional

import structlog

from agents.base_agent import BaseAgent
from github_client import GitHubClient

logger = structlog.get_logger(__name__)


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
        except Exception as exc:
            logger.warning("Failed to detect default branch, using 'main'", error=str(exc))
            return "main"

    def _build_file_context(
        self, gh: GitHubClient, doc_targets: list[str], ref: str
    ) -> str:
        """Pre-fetch file content and return as a formatted context block."""
        sections: list[str] = []
        self._add_root_listing(gh, ref, sections)
        paths_to_read = doc_targets or self._discover_markdown_files(gh, ref)
        self._read_files(gh, ref, paths_to_read, sections)
        return "\n\n".join(sections) if sections else "No existing files found."

    def _add_root_listing(self, gh: GitHubClient, ref: str, sections: list[str]) -> None:
        """Append repository root listing to sections."""
        try:
            entries = gh.list_files("", ref=ref)
            listing = "\n".join(f"[{e['type']}] {e['path']}" for e in entries)
            sections.append(f"## Repository root\n{listing}")
        except Exception as exc:
            logger.warning("Failed to list repository root files", error=str(exc))

    def _discover_markdown_files(self, gh: GitHubClient, ref: str) -> list[str]:
        """Auto-discover up to 5 markdown files in the repo."""
        try:
            return gh.search_files("**/*.md", ref=ref)[:5]
        except Exception as exc:
            logger.warning("Failed to auto-discover markdown files", error=str(exc))
            return []

    def _read_files(
        self, gh: GitHubClient, ref: str, paths: list[str], sections: list[str]
    ) -> None:
        """Read each file and append to sections."""
        for path in paths:
            try:
                content = gh.get_file_content(path, ref=ref)
                if content is not None:
                    sections.append(f"## File: {path}\n```\n{content}\n```")
                else:
                    sections.append(f"## File: {path}\n(does not exist yet — create it)")
            except Exception as exc:
                logger.warning("Failed to read file", path=path, error=str(exc))

    def run(
        self,
        issue_title: str,
        issue_body: str,
        github_client: GitHubClient,
        ref: Optional[str] = None,
    ) -> list[dict]:
        """Run agent on issue. Returns list of {"path", "content", "action"} dicts."""
        gh = github_client
        ref = ref or self._detect_ref(gh)
        doc_targets = self._parse_doc_targets(issue_body)
        file_context = self._build_file_context(gh, doc_targets, ref)

        user_message = (
            f"## Issue: {issue_title}\n\n{issue_body}\n\n"
            f"{file_context}\n\n"
            "Now produce the documentation updates as a JSON array."
        )

        raw = self.call(user_message=user_message)
        file_writes = self._parse_json_response(raw)

        # ValueError is raised only if parsing succeeded but returned empty list
        if file_writes is None:
            return []  # Parsing failed - return empty list
        if len(file_writes) == 0:
            raise ValueError(
                f"DocumentationAgent produced no file writes for issue: {issue_title!r}"
            )

        return file_writes

    def _parse_json_response(self, raw: str) -> list | None:
        """Parse JSON array from LLM response, with fallback extraction.
        
        Returns:
            list on successful parse, None if unparseable.
        """
        try:
            result = json.loads(raw)
            return result if isinstance(result, list) else None
        except json.JSONDecodeError:
            m = re.search(r"\[.*?\]", raw, re.DOTALL)
            if m:
                try:
                    result = json.loads(m.group(0))
                    return result if isinstance(result, list) else None
                except json.JSONDecodeError:
                    return None
            return None
