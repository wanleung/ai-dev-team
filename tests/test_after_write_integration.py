"""Integration test: _after_write violations are injected into agent feedback."""
from __future__ import annotations

import textwrap
from unittest.mock import MagicMock

import pytest

from agents.base_agent import BaseAgent


def _make_agent() -> BaseAgent:
    llm = MagicMock()
    llm.model = "gpt-4.1"
    llm.supports_tools.return_value = False
    return BaseAgent(model="gpt-4.1", llm=llm)


def test_after_write_returns_violations_for_big_function(tmp_path):
    """_after_write returns non-empty list when a written file has a >30-line function."""
    body = "\n".join(f"    var_{i} = {i}" for i in range(35))
    code = f"def process():\n{body}\n    return var_0\n"
    f = tmp_path / "service.py"
    f.write_text(code)

    agent = _make_agent()
    violations = agent._after_write([f])

    assert len(violations) == 1
    assert "process" in violations[0]
    assert "service.py" in violations[0]


def test_after_write_returns_empty_for_compliant_file(tmp_path):
    """_after_write returns empty list when all functions are ≤30 lines."""
    code = textwrap.dedent("""\
        def helper_a():
            return 1

        def helper_b():
            return 2
    """)
    f = tmp_path / "clean.py"
    f.write_text(code)

    agent = _make_agent()
    assert agent._after_write([f]) == []


def test_after_write_ignores_non_python_files(tmp_path):
    """_after_write skips non-.py files silently."""
    f = tmp_path / "config.yaml"
    f.write_text("key: value\n")
    agent = _make_agent()
    assert agent._after_write([f]) == []


@pytest.mark.parametrize("line_count,expect_violation", [
    (30, False),   # exactly at limit — must pass
    (31, True),    # one over — must fail
])
def test_after_write_boundary(tmp_path, line_count, expect_violation):
    """_after_write respects the strict >30 line boundary."""
    body = "\n".join(f"    x_{i} = {i}" for i in range(line_count - 1))
    code = f"def fn():\n{body}\n"
    (tmp_path / "mod.py").write_text(code)
    agent = _make_agent()
    result = agent._after_write([tmp_path / "mod.py"])
    assert bool(result) == expect_violation


def test_after_write_multiple_violations(tmp_path):
    """_after_write reports every violating function across all passed files."""
    def _big(name):
        body = "\n".join(f"    v_{i} = {i}" for i in range(32))
        return f"def {name}():\n{body}\n"

    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text(_big("alpha"))
    f2.write_text(_big("beta"))

    violations = _make_agent()._after_write([f1, f2])
    names = " ".join(violations)
    assert len(violations) == 2
    assert "alpha" in names
    assert "beta" in names


def test_after_write_mixed_file_list(tmp_path):
    """Non-.py files in the list do not suppress violations from .py files."""
    body = "\n".join(f"    v_{i} = {i}" for i in range(32))
    py_file = tmp_path / "svc.py"
    py_file.write_text(f"def big():\n{body}\n")
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("key: value\n")

    violations = _make_agent()._after_write([py_file, yaml_file])
    assert len(violations) == 1
    assert "big" in violations[0]
