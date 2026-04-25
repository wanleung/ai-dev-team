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
    ) -> dict:
        """Implement a single senior module.

        Identical to EngineerAgent.run_module but prepends a 'Junior Code Context'
        section when junior_files are available.

        Args:
            design: Full system design markdown.
            module: Module dict with 'name', 'description', 'tier' keys.
            project_name: Project name for context.
            framework_context: Optional framework documentation.
            junior_files: Dict of {filepath: content} produced by the junior batch.

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
        return super().run_module(augmented_design, module, project_name, framework_context)
