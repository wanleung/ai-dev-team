"""
TierReviewerAgent: validates and corrects module tier assignments (junior/senior).
Single LLM call — not a loop.
"""
from __future__ import annotations

import re

from .base_agent import BaseAgent


class TierReviewerAgent(BaseAgent):
    """Reviews the architect's module tier assignments and corrects any misclassifications.

    Input:  list of modules with tier assignments from the architect
    Output: revised list of modules with corrected tier assignments
    """

    role_name = "tier_reviewer"

    def run(self, modules: list[dict]) -> list[dict]:
        """Review and correct tier assignments for a list of modules.

        Args:
            modules: List of module dicts with 'name', 'description', 'tier' keys.

        Returns:
            Revised list of module dicts with corrected 'tier' values.
            Falls back to original modules if the LLM response cannot be parsed.
        """
        module_lines = "\n".join(
            f"{i+1}. **{m['name']}** [tier:{m.get('tier', 'senior')}]: {m.get('description', '')}"
            for i, m in enumerate(modules)
        )
        prompt = (
            "You are reviewing module tier assignments for a software project.\n\n"
            "Tier definitions:\n"
            "- **junior**: Self-contained modules with NO dependency on other modules in this list "
            "(models, schemas, utils, constants, config loaders, migrations).\n"
            "- **senior**: Modules that integrate, orchestrate, or BUILD ON other modules in this list "
            "(service layers, API routes, controllers, authentication flows, background tasks).\n\n"
            "Review each module below and correct its tier if needed. "
            "Return the COMPLETE revised list in the SAME FORMAT. "
            "Output ONLY the numbered list — no explanations.\n\n"
            f"## Module List\n{module_lines}"
        )

        response = self.call(prompt)
        revised = self._parse_revised_modules(response, modules)
        return revised

    @staticmethod
    def _parse_revised_modules(response: str, original: list[dict]) -> list[dict]:
        """Parse revised tier assignments from LLM response.

        Falls back to original modules if parsing fails or count mismatches.
        """
        pattern = re.compile(
            r'\d+\.\s+\*\*(.+?)\*\*\s+\[tier:(junior|senior)\]',
            re.IGNORECASE,
        )
        matches = pattern.findall(response)

        if len(matches) != len(original):
            return original

        revised = []
        for (_, tier), orig in zip(matches, original):
            mod = dict(orig)
            mod["tier"] = tier.lower()
            revised.append(mod)
        return revised
