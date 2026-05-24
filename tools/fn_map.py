"""Function size reporter and interactive HTML map generator.

Usage:
    python tools/fn_map.py                   # uses fn_map.yaml in cwd
    python tools/fn_map.py --config <path>   # alternate config
    python tools/fn_map.py --limit 50        # override line limit
    python tools/fn_map.py --no-html         # terminal output only
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class FunctionInfo:
    name: str
    file: str        # path relative to repo root
    lineno: int      # first line of the function
    line_count: int  # total lines including body
    calls: set[str]  # function names called from AST body


@dataclass
class FnMapConfig:
    limit: int = 30
    include: list[str] = field(default_factory=lambda: [
        "orchestrator.py", "watcher.py", "rss_watcher.py",
        "intake_triage.py", "intake_scoring.py", "main.py",
        "tracker_adapter.py", "config_schema.py", "agents/", "tools/",
    ])
    exclude: list[str] = field(default_factory=lambda: [
        "workspace/", ".venv/", "venv/", "tests/", ".git/", "__pycache__/",
    ])
    html_output: Optional[str] = "fn_map.html"


def load_config(path: str) -> FnMapConfig:
    """Load fn_map.yaml; return defaults if file is missing or empty."""
    if not Path(path).exists():
        return FnMapConfig()
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    cfg = FnMapConfig()
    if "limit" in data:
        try:
            cfg.limit = int(data["limit"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"fn_map.yaml: 'limit' must be an integer, got {data['limit']!r}") from exc
    if "include" in data:
        if not isinstance(data["include"], list):
            raise ValueError(f"fn_map.yaml: 'include' must be a YAML list, got {type(data['include']).__name__!r}")
        cfg.include = list(data["include"])
    if "exclude" in data:
        if not isinstance(data["exclude"], list):
            raise ValueError(f"fn_map.yaml: 'exclude' must be a YAML list, got {type(data['exclude']).__name__!r}")
        cfg.exclude = list(data["exclude"])
    if isinstance(data.get("output"), dict):
        cfg.html_output = data["output"].get("html", cfg.html_output)
    return cfg


def resolve_paths(
    include: list[str],
    exclude: list[str],
    root: Path,
) -> list[Path]:
    """Expand include globs/dirs and filter out excluded prefixes.
    
    Items ending with '/' are treated as directories (recursed for *.py).
    Items without trailing '/' are treated as individual files.
    Missing paths are silently skipped.
    """
    collected: list[Path] = []
    for inc in include:
        p = root / inc
        if inc.endswith("/"):
            if p.is_dir():
                collected.extend(p.rglob("*.py"))
        else:
            if p.is_file():
                collected.append(p)
    result = []
    for p in collected:
        rel = str(p.relative_to(root))
        excluded = any(rel.startswith(ex.rstrip("/") + "/") for ex in exclude)
        if not excluded:
            result.append(p)
    return sorted(set(result))


def _extract_calls(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Return names of all functions/methods called inside this function's body."""
    calls: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name):
            calls.add(child.func.id)
        elif isinstance(child.func, ast.Attribute):
            calls.add(child.func.attr)
    return calls


def _parse_file(path: Path, root: Path) -> list[FunctionInfo]:
    """Parse one .py file and return a FunctionInfo for every function defined in it."""
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
    except SyntaxError:
        return []
    rel = str(path.relative_to(root))
    results = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            results.append(FunctionInfo(
                name=node.name,
                file=rel,
                lineno=node.lineno,
                line_count=node.end_lineno - node.lineno + 1,
                calls=_extract_calls(node),
            ))
    return results


def collect_functions(paths: list[Path], root: Path) -> list[FunctionInfo]:
    """Walk all paths and aggregate FunctionInfo from every .py file."""
    funcs: list[FunctionInfo] = []
    for p in paths:
        funcs.extend(_parse_file(p, root))
    return funcs


def detect_violations(funcs: list[FunctionInfo], limit: int) -> list[FunctionInfo]:
    """Return functions exceeding limit, sorted by line_count descending."""
    return sorted(
        [f for f in funcs if f.line_count > limit],
        key=lambda f: f.line_count,
        reverse=True,
    )


def build_distribution(
    funcs: list[FunctionInfo], buckets: list[int]
) -> list[tuple[str, int]]:
    """Return (label, count) pairs for each size bucket (exclusive per-range counts)."""
    result: list[tuple[str, int]] = []
    prev = 0
    for b in sorted(buckets):
        count = sum(1 for f in funcs if prev < f.line_count <= b)
        result.append((f"≤{b} lines", count))
        prev = b
    over = sum(1 for f in funcs if f.line_count > sorted(buckets)[-1])
    result.append((f">{sorted(buckets)[-1]} lines", over))
    return result


def build_call_index(funcs: list[FunctionInfo]) -> dict[str, FunctionInfo]:
    """Map function name → FunctionInfo (last wins on duplicates)."""
    return {f.name: f for f in funcs}


def build_calledby_index(funcs: list[FunctionInfo]) -> dict[str, list[str]]:
    """Map function name → list of caller names."""
    idx: dict[str, list[str]] = {}
    for fn in funcs:
        for called in fn.calls:
            idx.setdefault(called, []).append(fn.name)
    return idx
