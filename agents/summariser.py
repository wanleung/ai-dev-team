"""SummaryAgent — writes a concise memory entry after each pipeline run."""
from pathlib import Path
from .base_agent import BaseAgent

ROLE_FILE = Path(__file__).parent.parent / "roles" / "summariser.md"


class SummaryAgent(BaseAgent):
    role_name = "summariser"

    def summarise(
        self,
        repo: str,
        requirement: str,
        prd: str,
        design: str,
        review: str,
        mode: str = "feature",
    ) -> str:
        """Produce a compact memory entry for storage in the memory store."""
        prompt = f"""You are summarising a completed AI software house pipeline run for future reference.

## Repo: {repo}
## Mode: {mode}
## Requirement:
{requirement[:500]}

## PRD (excerpt):
{prd[:1000]}

## Architecture Design (excerpt):
{design[:1000]}

## Code Review Notes:
{review[:800]}

---

Write a concise memory entry (max 400 words) covering:
1. **What was built** — key components, modules, tech stack
2. **Design decisions** — important architectural choices made
3. **Issues & feedback** — what the reviewer flagged, what to watch out for
4. **Tech debt** — anything left incomplete or marked for future improvement

Be specific and factual. This will be read by future AI agents to avoid repeating mistakes.
Output plain text only, no JSON."""

        return self.call(prompt)
