"""RefactorAgent — analyses existing code and produces a cleanup plan + PR."""
from pathlib import Path
from .base_agent import BaseAgent

ROLE_FILE = Path(__file__).parent.parent / "roles" / "refactor_agent.md"


class RefactorAgent(BaseAgent):
    role_name = "refactor_agent"

    def analyse(self, code_snapshot: str, memory_context: str = "", design: str = "") -> str:
        """Analyse existing code and propose a refactor plan."""
        memory_section = f"\n## Memory from previous runs:\n{memory_context}\n" if memory_context else ""
        design_section = f"\n## Original Design:\n{design[:1000]}\n" if design else ""

        prompt = f"""You are reviewing an existing codebase for a cleanup/refactor pass.
{memory_section}{design_section}
## Existing Code:
{code_snapshot}

---

Produce a detailed refactor plan covering:
1. **Code smells** — duplication, long functions, unclear naming
2. **Architecture issues** — violations of the original design, missing abstractions
3. **Tech debt** — incomplete implementations, TODOs, hardcoded values
4. **Security/reliability** — missing error handling, no input validation, etc.
5. **Specific changes** — list each file and what to change

Format each change as:
### File: `<path>`
**Issue:** <what's wrong>
**Fix:** <what to do>
"""
        return self.call(prompt)

    def rewrite(self, file_path: str, current_code: str, fix_instructions: str) -> str:
        """Rewrite a single file based on refactor instructions."""
        prompt = f"""Rewrite the following file applying these specific improvements.

## File: {file_path}
## Instructions:
{fix_instructions}

## Current code:
```
{current_code}
```

Output ONLY the complete rewritten file content. No explanation, no markdown fences."""
        return self.call(prompt)
