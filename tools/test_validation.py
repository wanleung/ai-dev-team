"""Validation helpers for generated pytest files."""
from __future__ import annotations

import ast


_BLOCKED_CONFTEST_MODULES = {"conftest", "tests.conftest"}


def validate_generated_tests(files: dict[str, str]) -> list[str]:
    """Return deterministic issues in generated pytest files.

    This catches patterns that routinely break collection before pytest reaches
    the actual app behavior.  Keep these checks narrow and actionable; broader
    test-quality judgment still belongs to the reviewer agent.
    """
    issues: list[str] = []
    fixture_names = _collect_fixture_names(files)
    for filename, source in files.items():
        if not _is_test_python_file(filename):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        issues.extend(_find_conftest_imports(filename, tree))
        if fixture_names and _is_test_module(filename):
            issues.extend(_find_direct_fixture_calls(filename, tree, fixture_names))
    return issues


def _is_test_python_file(filename: str) -> bool:
    return filename.endswith(".py") and (
        filename.startswith("tests/") or filename == "conftest.py"
    )


def _is_test_module(filename: str) -> bool:
    return filename.startswith("tests/test_") and filename.endswith(".py")


def _collect_fixture_names(files: dict[str, str]) -> set[str]:
    names: set[str] = set()
    for filename, source in files.items():
        if filename not in {"conftest.py", "tests/conftest.py"}:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _has_pytest_fixture_decorator(node):
                names.add(node.name)
    return names


def _has_pytest_fixture_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr == "fixture":
            return isinstance(target.value, ast.Name) and target.value.id == "pytest"
        if isinstance(target, ast.Name) and target.id == "fixture":
            return True
    return False


def _find_conftest_imports(filename: str, tree: ast.AST) -> list[str]:
    issues: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        if module not in _BLOCKED_CONFTEST_MODULES:
            continue
        names = ", ".join(alias.name for alias in node.names)
        issues.append(
            f"{filename}: imports {names or '*'} from {module}; "
            "do not import from conftest.py. Move shared helpers to tests/helpers.py "
            "or request fixtures as test parameters."
        )
    return issues


def _find_direct_fixture_calls(filename: str, tree: ast.AST, fixture_names: set[str]) -> list[str]:
    issues: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name):
            continue
        if node.func.id not in fixture_names:
            continue
        issues.append(
            f"{filename}: calls pytest fixture '{node.func.id}' directly; "
            "fixtures must be requested as test parameters and must not be called like helper functions. "
            "Move factory helpers to tests/helpers.py when direct calls are needed."
        )
    return issues
