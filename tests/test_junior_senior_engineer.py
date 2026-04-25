# tests/test_junior_senior_engineer.py
from unittest.mock import MagicMock
from agents.junior_engineer import JuniorEngineerAgent
from agents.senior_engineer import SeniorEngineerAgent


def _make_junior() -> JuniorEngineerAgent:
    agent = JuniorEngineerAgent.__new__(JuniorEngineerAgent)
    agent._tool_registry = None
    return agent


def _make_senior() -> SeniorEngineerAgent:
    agent = SeniorEngineerAgent.__new__(SeniorEngineerAgent)
    agent._tool_registry = None
    return agent


# ── JuniorEngineerAgent ───────────────────────────────────────────────────────

def test_junior_role_name():
    assert JuniorEngineerAgent.role_name == "junior_engineer"


def test_junior_run_module_returns_files():
    agent = _make_junior()
    agent.call = MagicMock(return_value=(
        "### FILE: app/models/user.py\n"
        "class User:\n    pass\n"
    ))
    result = agent.run_module("design", {"name": "app/models/user", "description": "User model"})
    assert "app/models/user.py" in result["files"]


def test_junior_prompt_does_not_contain_junior_code_context():
    agent = _make_junior()
    captured = []
    agent.call = MagicMock(side_effect=lambda p: captured.append(p) or "### FILE: x.py\npass")
    agent.run_module("design", {"name": "app/models/user", "description": "User model"})
    assert "Junior Code Context" not in captured[0]


# ── SeniorEngineerAgent ───────────────────────────────────────────────────────

def test_senior_role_name():
    assert SeniorEngineerAgent.role_name == "senior_engineer"


def test_senior_run_module_injects_junior_context():
    agent = _make_senior()
    captured = []
    agent.call = MagicMock(side_effect=lambda p: captured.append(p) or "### FILE: x.py\npass")
    junior_files = {"app/models/user.py": "class User:\n    pass\n"}
    agent.run_module(
        "design",
        {"name": "app/services/auth", "description": "Auth service"},
        junior_files=junior_files,
    )
    assert "Junior Code Context" in captured[0]
    assert "app/models/user.py" in captured[0]
    assert "class User" in captured[0]


def test_senior_run_module_no_junior_files_skips_context():
    agent = _make_senior()
    captured = []
    agent.call = MagicMock(side_effect=lambda p: captured.append(p) or "### FILE: x.py\npass")
    agent.run_module(
        "design",
        {"name": "app/services/auth", "description": "Auth service"},
        junior_files={},
    )
    assert "Junior Code Context" not in captured[0]


def test_senior_run_module_returns_files():
    agent = _make_senior()
    agent.call = MagicMock(return_value=(
        "### FILE: app/services/auth.py\n"
        "def login(): pass\n"
    ))
    result = agent.run_module(
        "design",
        {"name": "app/services/auth", "description": "Auth"},
        junior_files={},
    )
    assert "app/services/auth.py" in result["files"]
