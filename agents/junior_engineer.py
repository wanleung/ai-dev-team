"""
JuniorEngineerAgent: implements simple, self-contained modules using a fast/cheap model.
Inherits all behaviour from EngineerAgent — only role_name differs for model routing.
"""
from __future__ import annotations

from .engineer import EngineerAgent


class JuniorEngineerAgent(EngineerAgent):
    """Junior Engineer — implements isolated modules (models, schemas, utils).

    Uses a fast/cheap model. Inherits run_module, run_all_modules, run_with_github
    from EngineerAgent unchanged.
    """

    role_name = "junior_engineer"
