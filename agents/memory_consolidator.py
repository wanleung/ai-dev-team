"""MemoryConsolidatorAgent — compresses N run summaries into a single snapshot.

This agent is the "dreaming" component: it runs after enough individual run
summaries accumulate and folds them into a compact monthly or quarterly entry.
The result is stored back in the MemoryStore so recall() stays fast and bounded.
"""
from pathlib import Path
from .base_agent import BaseAgent

ROLE_FILE = Path(__file__).parent.parent / "roles" / "memory_consolidator.md"


class MemoryConsolidatorAgent(BaseAgent):
    role_name = "memory_consolidator"

    def consolidate(self, prompt: str) -> str:
        """Run the consolidation prompt and return the compressed summary text."""
        return self.call(prompt)
