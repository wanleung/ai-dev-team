"""Framework docs awareness — detects and loads framework documentation into agent context."""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Max chars to read from a single bundled doc file (avoid giant prompts)
_MAX_DOC_CHARS = 4000
# Max total chars for all bundled docs combined
_MAX_TOTAL_BUNDLED = 12000


class FrameworkDocsLoader:
    """Detects framework docs in a project workspace and returns context to inject into prompts.

    Priority order:
      1. AGENTS.md at project root
      2. CLAUDE.md at project root
      3. Config-defined framework bundled docs or RAG hints
    """

    def __init__(self, config: dict) -> None:
        self._cfg = (config or {}).get("framework_docs", {})

    def load(self, project_dir: Path) -> str:
        """Return a context string to prepend to engineer prompts, or empty string if nothing found.

        Args:
            project_dir: Absolute path to the project workspace directory.
        """
        if not self._cfg:
            return ""

        # Layer 1 — AGENTS.md / CLAUDE.md
        if self._cfg.get("check_agents_md", True):
            for filename in ("AGENTS.md", "CLAUDE.md"):
                candidate = project_dir / filename
                if candidate.is_file():
                    content = candidate.read_text(encoding="utf-8", errors="replace").strip()
                    if content:
                        log.info("Loaded framework context from %s", filename)
                        return (
                            f"## Framework Instructions ({filename})\n\n"
                            f"{content}\n\n"
                            "---\n\n"
                        )

        # Layer 2 — Config-driven framework detection
        frameworks = self._cfg.get("frameworks", {})
        if not frameworks:
            return ""

        collected: list[str] = []

        for fw_name, fw_cfg in frameworks.items():
            detect_file = fw_cfg.get("detect_file")
            detect_key = fw_cfg.get("detect_key", "")

            if not detect_file:
                continue

            target = project_dir / detect_file
            if not target.is_file():
                continue

            file_content = target.read_text(encoding="utf-8", errors="replace")
            if detect_key and detect_key not in file_content:
                continue

            log.info("Detected framework: %s", fw_name)

            # RAG hint (always included if detected)
            rag_hint = fw_cfg.get("rag_hint", "")

            # Bundled docs
            bundled_path = fw_cfg.get("bundled_docs")
            bundled_text = ""
            if bundled_path:
                docs_dir = project_dir / bundled_path
                if docs_dir.is_dir():
                    bundled_text = _read_bundled_docs(docs_dir)

            section_parts = [f"## {fw_name} Framework Docs\n"]
            if bundled_text:
                section_parts.append(bundled_text)
            elif rag_hint:
                section_parts.append(rag_hint)
            else:
                section_parts.append(
                    f"Framework '{fw_name}' detected. "
                    "Check the installed package for bundled documentation or use search_docs."
                )

            collected.append("\n".join(section_parts))

        if not collected:
            return ""

        return "\n\n---\n\n".join(collected) + "\n\n---\n\n"


def _read_bundled_docs(docs_dir: Path) -> str:
    """Read markdown/text files from a bundled docs directory up to _MAX_TOTAL_BUNDLED chars."""
    parts: list[str] = []
    total = 0

    for doc_file in sorted(docs_dir.rglob("*.md")):
        if total >= _MAX_TOTAL_BUNDLED:
            break
        try:
            text = doc_file.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if not text:
            continue
        chunk = text[:_MAX_DOC_CHARS]
        parts.append(f"### {doc_file.name}\n\n{chunk}")
        total += len(chunk)

    return "\n\n".join(parts)
