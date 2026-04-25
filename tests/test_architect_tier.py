# tests/test_architect_tier.py
from agents.architect import ArchitectAgent


def test_parse_modules_extracts_tier_junior():
    design = """
## Implementation Modules
1. **`app/models/user`** [tier:junior]: User model and schema
2. **`app/services/auth`** [tier:senior]: Authentication service
"""
    modules = ArchitectAgent._parse_modules(design)
    assert len(modules) == 2
    assert modules[0]["name"] == "`app/models/user`"
    assert modules[0]["tier"] == "junior"
    assert modules[1]["name"] == "`app/services/auth`"
    assert modules[1]["tier"] == "senior"


def test_parse_modules_defaults_to_senior_when_no_tier():
    design = """
## Implementation Modules
1. **`app/models/user`**: User model and schema
"""
    modules = ArchitectAgent._parse_modules(design)
    assert modules[0]["tier"] == "senior"


def test_parse_modules_preserves_description():
    design = """
## Implementation Modules
1. **`app/core`** [tier:senior]: Core config and startup logic
"""
    modules = ArchitectAgent._parse_modules(design)
    assert "Core config and startup logic" in modules[0]["description"]


def test_parse_modules_fallback_returns_senior_tier():
    design = "No modules section here."
    modules = ArchitectAgent._parse_modules(design)
    assert modules[0]["name"] == "main"
    assert modules[0]["tier"] == "senior"
