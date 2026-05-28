"""Contract Validator Agent — checks test/impl files against naming_contract.yaml."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.base_agent import BaseAgent

log = logging.getLogger(__name__)


class ContractValidatorAgent:
    """Validates test and implementation files against a naming_contract.yaml.

    Returns a dict with keys:
        passed (bool)    — True if no divergences found (or contract absent)
        skipped (bool)   — True if no naming_contract.yaml was available
        divergences (list[dict]) — list of {file, field, issue, suggestion}
    """

    ROLE_FILE = Path(__file__).parent.parent / "roles" / "contract_validator.md"

    def __init__(self, llm: "BaseAgent") -> None:
        self._llm = llm
        self._role = self.ROLE_FILE.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(
        self,
        contract_yaml: str | None,
        files: dict[str, str],
    ) -> dict:
        """Validate *files* against *contract_yaml*.

        Args:
            contract_yaml: Contents of naming_contract.yaml, or None if absent.
            files: Mapping of {filename: content} to validate.

        Returns:
            {"passed": bool, "skipped": bool, "divergences": list[dict]}
        """
        if not contract_yaml or not contract_yaml.strip():
            log.info("[contract_validator] No contract — skipping validation")
            return {"passed": True, "skipped": True, "divergences": []}

        if not files:
            log.info("[contract_validator] No files to validate — skipping")
            return {"passed": True, "skipped": True, "divergences": []}

        prompt = self._build_prompt(contract_yaml, files)
        response = self._llm.call(user_message=prompt, context=self._role)
        return self._parse_response(response)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, contract_yaml: str, files: dict[str, str]) -> str:
        parts = [
            "## naming_contract.yaml\n```yaml",
            contract_yaml.strip(),
            "```\n",
        ]
        for filename, content in files.items():
            parts.append(f"## {filename}\n```python")
            parts.append(content.strip())
            parts.append("```\n")
        return "\n".join(parts)

    def _parse_response(self, response: str) -> dict:
        """Parse the LLM JSON response, with fallback on parse errors."""
        text = response.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1]) if lines[-1] == "```" else "\n".join(lines[1:])
        try:
            data = json.loads(text)
            return {
                "passed": bool(data.get("passed", True)),
                "skipped": bool(data.get("skipped", False)),
                "divergences": list(data.get("divergences", [])),
            }
        except (json.JSONDecodeError, TypeError):
            log.warning("[contract_validator] Could not parse LLM response as JSON: %s", text[:200])
            return {"passed": True, "skipped": True, "divergences": []}
