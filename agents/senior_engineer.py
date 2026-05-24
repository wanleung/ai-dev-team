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
        augmented_design = self._build_augmented_design(design, junior_files, test_files)
        return super().run_module(augmented_design, module, project_name, framework_context)

    @staticmethod
    def _build_augmented_design(
        design: str, junior_files: dict[str, str] | None, test_files: dict[str, str] | None
    ) -> str:
        """Build augmented design with junior code context and test sections."""
        augmented = design
        if junior_files:
            augmented = SeniorEngineerAgent._inject_junior_context(design, junior_files)
        if test_files:
            augmented += EngineerAgent._build_test_section_static(test_files)
        return augmented

    @staticmethod
    def _inject_junior_context(design: str, junior_files: dict[str, str]) -> str:
        """Inject junior code context into the design."""
        file_dump = "\n\n".join(
            f"### FILE: {path}\n```\n{content}\n```"
            for path, content in junior_files.items()
        )
        return (
            f"## Junior Code Context\n\n"
            f"The following utility/model files have already been implemented by junior engineers. "
            f"You MUST use these files as-is — do NOT reimplement them.\n\n"
            f"{file_dump}\n\n"
            f"---\n\n"
            f"{design}"
        )
