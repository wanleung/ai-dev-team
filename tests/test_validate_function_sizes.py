"""Tests for tools.fn_map.validate_function_sizes."""
from __future__ import annotations

import textwrap
from pathlib import Path

from tools.fn_map import validate_function_sizes


def _write_py(tmp_path: Path, filename: str, src: str) -> Path:
    p = tmp_path / filename
    p.write_text(textwrap.dedent(src))
    return p


def test_returns_empty_for_compliant_file(tmp_path):
    f = _write_py(tmp_path, "ok.py", """\
        def small():
            x = 1
            return x
    """)
    assert validate_function_sizes([f]) == []


def test_detects_oversized_function(tmp_path):
    body = "\n".join(f"    x{i} = {i}" for i in range(35))
    src = f"def big_fn():\n{body}\n    return x0\n"
    f = _write_py(tmp_path, "big.py", src)
    violations = validate_function_sizes([f])
    assert len(violations) == 1
    assert "big_fn" in violations[0]
    assert "37" in violations[0]


def test_violation_string_format(tmp_path):
    body = "\n".join(f"    x{i} = {i}" for i in range(35))
    src = f"def bad_fn():\n{body}\n    return x0\n"
    f = _write_py(tmp_path, "module.py", src)
    violations = validate_function_sizes([f])
    assert violations[0].startswith("module.py::bad_fn")


def test_custom_limit(tmp_path):
    body = "\n".join(f"    x{i} = {i}" for i in range(20))
    src = f"def medium_fn():\n{body}\n    return x0\n"
    f = _write_py(tmp_path, "m.py", src)
    assert validate_function_sizes([f], limit=30) == []
    assert validate_function_sizes([f], limit=15) != []


def test_syntax_error_returns_empty(tmp_path):
    f = _write_py(tmp_path, "bad_syntax.py", "def broken(\n")
    assert validate_function_sizes([f]) == []


def test_multiple_files(tmp_path):
    ok = _write_py(tmp_path, "ok.py", "def fine():\n    return 1\n")
    body = "\n".join(f"    x{i} = {i}" for i in range(35))
    bad = _write_py(tmp_path, "bad.py", f"def large():\n{body}\n    return x0\n")
    violations = validate_function_sizes([ok, bad])
    assert len(violations) == 1
    assert "bad.py" in violations[0]
