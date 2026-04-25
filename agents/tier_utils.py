"""
tier_utils: Applies config-based tier override rules to a module list.
"""
from __future__ import annotations

import fnmatch


def apply_tier_overrides(
    modules: list[dict],
    rules: list[dict],
) -> list[dict]:
    """Apply glob-pattern override rules to module tier assignments.

    Rules are evaluated in order; first matching rule wins.
    Modules missing a 'tier' field default to 'senior'.

    Args:
        modules: List of module dicts (each with 'name', 'description', optional 'tier').
        rules: List of override dicts: [{"pattern": "*/models*", "tier": "junior"}, ...]

    Returns:
        New list of module dicts with 'tier' set according to rules (or defaults).
    """
    result = []
    for module in modules:
        mod = dict(module)
        if "tier" not in mod:
            mod["tier"] = "senior"
        for rule in rules:
            if fnmatch.fnmatch(mod["name"], rule["pattern"]):
                mod["tier"] = rule["tier"]
                break
        result.append(mod)
    return result
