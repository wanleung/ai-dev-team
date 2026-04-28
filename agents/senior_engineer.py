"""
SeniorEngineerAgent: implements complex integration modules using an expensive model.
Injects all junior-tier code as context so seniors can reference utility code directly.
"""
from __future__ import annotations

from .engineer import EngineerAgent


class SeniorEngineerAgent(EngineerAgent):
    """Senior Engineer — implements integration/orchestration modules.

    Uses an expensive model. Extends run_module to inject junior code as context.
    """

    role_name = "senior_engineer"

    def run_module(
        self,
        design: str,
        module: dict,
        project_name: str = "Project",
        framework_context: str = "",
        junior_files: dict[str, str] | None = None,
        test_files: dict[str, str] | None = None,
    ) -> dict:
        """Implement a single senior module.

        Identical to EngineerAgent.run_module but prepends a 'Junior Code Context'
        section when junior_files are available.  When test_files are provided
        (TDD mode) they are forwarded to the parent implementation so the engineer
        is instructed to make the pre-written tests pass.

        Args:
            design: Full system design markdown.
            module: Module dict with 'name', 'description', 'tier' keys.
            project_name: Project name for context.
            framework_context: Optional framework documentation.
            junior_files: Dict of {filepath: content} produced by the junior batch.
            test_files: Optional dict of pre-written test files (TDD mode). When
                        provided, the engineer is instructed to make these tests pass.

        Returns:
            Same as EngineerAgent.run_module.
        """
        augmented_design = design
        if junior_files:
            file_dump = "\n\n".join(
                f"### FILE: {path}\n```\n{content}\n```"
                for path, content in junior_files.items()
            )
            augmented_design = (
                f"## Junior Code Context\n\n"
                f"The following utility/model files have already been implemented by junior engineers. "
                f"You MUST use these files as-is — do NOT reimplement them.\n\n"
                f"{file_dump}\n\n"
                f"---\n\n"
                f"{design}"
            )

        # Build truncated test section (mirrors EngineerAgent logic) and inject it
        # directly into augmented_design so the parent receives test_files=None and
        # does not double-inject the section.
        if test_files:
            MAX_FILE_CHARS = 3000
            MAX_TOTAL_CHARS = 10000
            parts = []
            for path, content in test_files.items():
                if len(content) > MAX_FILE_CHARS:
                    content = content[:MAX_FILE_CHARS] + f"\n... (truncated, {len(content)} chars total)"
                parts.append(f"### FILE: {path}\n```python\n{content}\n```")
            test_section_body = "\n\n".join(parts)
            if len(test_section_body) > MAX_TOTAL_CHARS:
                test_section_body = test_section_body[:MAX_TOTAL_CHARS] + "\n... (additional test files truncated)"
            augmented_design += (
                f"\n\n## Pre-written tests your implementation must pass\n\n"
                f"{test_section_body}\n\n"
                f"Implement the module so all of the above tests pass. "
                f"Do not modify the test files."
            )

        return super().run_module(augmented_design, module, project_name, framework_context)
