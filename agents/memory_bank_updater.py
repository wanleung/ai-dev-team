"""MemoryBankUpdaterAgent — updates memory bank files after a pipeline run."""
from __future__ import annotations

import re

from .base_agent import BaseAgent

BANK_FILES = [
    "projectbrief.md",
    "productContext.md",
    "systemPatterns.md",
    "techContext.md",
    "activeContext.md",
    "progress.md",
]

FILE_HEADER = re.compile(r"### FILE: (memory-bank/[^\s]+\.md)")


class MemoryBankUpdaterAgent(BaseAgent):
    """Agent that updates memory bank files to reflect the latest pipeline run.

    After a pipeline run completes, call ``update()`` with the current bank
    contents and a plain-text run summary.  The agent returns a dict mapping
    filenames (e.g. ``"activeContext.md"``) to their new full content.

    Only files that genuinely changed are returned; callers should write these
    back to disk and leave unchanged files untouched.
    """

    role_name = "memory_bank_updater"

    def update(
        self,
        current_bank: dict[str, str],
        run_summary: str,
    ) -> dict[str, str]:
        """Return updated memory bank files based on the run summary.

        Args:
            current_bank: Mapping of filename → current file content for each
                          of the six standard memory bank files.
            run_summary:  Plain-text description of what was built / changed
                          in the pipeline run that just completed.

        Returns:
            Dict mapping filename → new full content for every file that needs
            updating.  Files not present in the return value are unchanged.
        """
        bank_section = self._build_bank_section(current_bank)
        prompt = self._build_update_prompt(bank_section, run_summary)
        raw = self.call(prompt)
        return self._parse_output(raw)

    def _build_bank_section(self, current_bank: dict[str, str]) -> str:
        """Build the bank section showing current files."""
        return "\n\n".join(
            f"### CURRENT: memory-bank/{filename}\n{content}"
            for filename, content in current_bank.items()
            if filename in BANK_FILES
        )

    def _build_update_prompt(self, bank_section: str, run_summary: str) -> str:
        """Build the prompt for updating memory bank files."""
        return f"""Below are the current memory bank files followed by a summary of the pipeline run that just completed.

Update the memory bank files according to your instructions.

---

{bank_section}

---

## Run Summary

{run_summary}
"""

    def _parse_output(self, raw: str) -> dict[str, str]:
        """Parse the agent's raw output into a filename → content mapping.

        The expected format uses ``### FILE: memory-bank/<name>.md`` headers to
        delimit each file's content.  Only filenames that belong to
        ``BANK_FILES`` are included in the result; any unexpected filenames are
        silently dropped.

        Args:
            raw: Raw text response from the LLM.

        Returns:
            Dict mapping valid bank filenames to their new content strings.
        """
        parts = FILE_HEADER.split(raw)
        result: dict[str, str] = {}

        # parts layout after split: [prefix, filepath1, content1, filepath2, content2, ...]
        for i in range(1, len(parts) - 1, 2):
            filepath = parts[i].strip()
            content = parts[i + 1].strip()
            filename = filepath.split("/")[-1]
            if filename in BANK_FILES:
                result[filename] = content

        return result
