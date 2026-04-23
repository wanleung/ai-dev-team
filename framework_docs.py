"""Framework docs awareness — detects and loads framework documentation into agent context."""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Max chars to read from a single bundled doc file (avoid giant prompts)
_MAX_DOC_CHARS = 4000
# Max total chars for all bundled docs combined (used as default for _read_bundled_docs)
_MAX_TOTAL_BUNDLED = 12000

_SCAFFOLD_HINT = (
    "No framework-specific docs found. "
    "If you scaffold a new project, check for AGENTS.md afterwards."
)


class FrameworkDocsLoader:
    """Detects framework docs in a project workspace and returns context to inject into prompts.

    Priority order:
      1. AGENTS.md / CLAUDE.md — walked up from project_dir to filesystem root
      2. Config-defined framework bundled docs or summaries
      3. Scaffold hint (when framework_docs config is present but no layers matched)

    Config schema::

        {
          "framework_docs": {
            "check_agents_md": True,        # optional, default True
            "frameworks": [                 # list of dicts
              {
                "name": "nextjs",
                "detect": ["package.json"], # glob patterns; any match = detected
                "summary": "Next.js ...",   # included verbatim when detected
                "bundled_docs_path": "node_modules/next/dist/docs"  # optional
              }
            ]
          }
        }
    """

    def __init__(self, config: dict) -> None:
        self._raw = config or {}
        self._cfg: dict = self._raw.get("framework_docs") or {}

    def load(self, project_dir: Path) -> str:
        """Return a context string to prepend to engineer prompts, or empty string if nothing found.

        Collects ALL available context: AGENTS.md/CLAUDE.md (if present) AND any
        config-driven framework docs. Both are returned together so project-specific
        instructions and framework API docs are never mutually exclusive.

        Args:
            project_dir: Absolute path to the project workspace directory.

        Returns:
            Non-empty context string when anything is found, ``""`` when the
            ``framework_docs`` config key is absent entirely, or the scaffold hint
            when the config key is present but neither layer produced content.
        """
        if not self._raw.get("framework_docs"):
            return ""

        sections: list[str] = []

        # Layer 1 — walk up directory tree for AGENTS.md / CLAUDE.md
        if self._cfg.get("check_agents_md", True):
            current = project_dir
            found_agents = False
            while not found_agents:
                for filename in ("AGENTS.md", "CLAUDE.md"):
                    candidate = current / filename
                    if candidate.is_file():
                        content = candidate.read_text(encoding="utf-8", errors="replace").strip()
                        if content:
                            log.info("Loaded framework context from %s", candidate)
                            sections.append(
                                f"## Framework Instructions ({filename})\n\n{content}"
                            )
                            found_agents = True
                            break  # AGENTS.md takes priority — only include one per level
                if found_agents:
                    break
                parent = current.parent
                if parent == current:  # reached filesystem root
                    break
                current = parent

        # Layer 2 — Config-driven framework detection
        frameworks = self._cfg.get("frameworks", [])
        for fw in frameworks:
            name = fw.get("name", "")
            detect_patterns: list[str] = fw.get("detect", [])

            # Detect: any glob pattern under project_dir matches → framework present
            matched = any(
                True
                for pattern in detect_patterns
                for _ in project_dir.glob(pattern)
            )
            if not matched:
                continue

            log.info("Detected framework: %s", name)

            summary = fw.get("summary", "")
            bundled_path = fw.get("bundled_docs_path")
            bundled_text = ""
            if bundled_path:
                bundled_text = self._read_bundled_docs(
                    project_dir / bundled_path, _MAX_TOTAL_BUNDLED
                )

            section_parts = [f"## {name} Framework Docs\n"]
            if bundled_text:
                section_parts.append(bundled_text)
            elif summary:
                section_parts.append(summary)
            else:
                section_parts.append(
                    f"Framework '{name}' detected. "
                    "Check the installed package for bundled documentation or use search_docs."
                )

            sections.append("\n".join(section_parts))

        # Layer 3 — scaffold hint when config was present but nothing matched
        if not sections:
            return _SCAFFOLD_HINT

        return "\n\n---\n\n".join(sections) + "\n\n---\n\n"

    def _read_bundled_docs(self, path: Path, max_chars: int) -> str:
        """Read all ``*.md`` files recursively from *path*, capped at *max_chars* total.

        The header ``### filename\\n\\n`` counts toward the cap alongside content.

        Args:
            path: Directory to search for markdown files.
            max_chars: Maximum total characters to return across all files.

        Returns:
            Concatenated markdown content, or ``""`` if *path* does not exist.
        """
        if not path.exists():
            return ""

        parts: list[str] = []
        total = 0

        for doc_file in sorted(path.rglob("*.md")):
            if total >= max_chars:
                break
            try:
                text = doc_file.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            if not text:
                continue
            chunk = text[:_MAX_DOC_CHARS]
            entry = f"### {doc_file.name}\n\n{chunk}"
            parts.append(entry)
            total += len(entry)  # header + content count toward cap

        return "\n\n".join(parts)
