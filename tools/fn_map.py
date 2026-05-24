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
    sorted_buckets = sorted(buckets)
    result: list[tuple[str, int]] = []
    prev = 0
    for b in sorted_buckets:
        count = sum(1 for f in funcs if prev < f.line_count <= b)
        result.append((f"≤{b} lines", count))
        prev = b
    over = sum(1 for f in funcs if f.line_count > sorted_buckets[-1])
    result.append((f">{sorted_buckets[-1]} lines", over))
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


def _colour(text: str, code: str) -> str:
    """Return text wrapped in ANSI colour code."""
    return f"\033[{code}m{text}\033[0m"


def _fn_colour_code(line_count: int, limit: int) -> str:
    """Return ANSI colour code based on line_count vs limit."""
    if line_count <= limit:
        return "32"   # green
    if line_count <= 50:
        return "33"   # orange/yellow
    return "31"       # red


def _print_violations_table(violations: list[FunctionInfo], limit: int) -> None:
    """Print table of functions exceeding the limit, colour-coded."""
    print(_colour(f"\nFunction Size Report  (limit: {limit} lines)", "1;34"))
    print("─" * 62)
    print(f"  {'Lines':>6}  {'Function':<32}  File")
    print("─" * 62)
    for fn in violations[:50]:
        code = _fn_colour_code(fn.line_count, limit)
        loc = f"{fn.file}:{fn.lineno}"
        print(f"  {_colour(f'{fn.line_count:>6}', code)}  {fn.name:<32}  {loc}")
    if len(violations) > 50:
        print(f"  ... ({len(violations) - 50} more violations)")
    print("─" * 62)


def _print_summary(funcs: list[FunctionInfo], violations: list[FunctionInfo]) -> None:
    """Print compliance summary line."""
    total = len(funcs)
    compliant = total - len(violations)
    pct = compliant / total * 100 if total else 0
    v_str = _colour(f"{len(violations)} violation{'s' if len(violations) != 1 else ''}", "31")
    c_str = _colour(f"{compliant} compliant ({pct:.0f}%)", "32")
    print(f"\n{v_str}  |  {c_str}  |  {total} total\n")


def _print_distribution(funcs: list[FunctionInfo]) -> None:
    """Print histogram of function size distribution."""
    buckets = [10, 20, 30, 50, 100]
    dist = build_distribution(funcs, buckets)
    total = len(funcs)
    max_count = max((c for _, c in dist), default=1)
    bar_width = 24
    print(_colour("Distribution:", "1"))
    for label, count in dist:
        pct = count / total * 100 if total else 0
        bar_len = int(count / max_count * bar_width) if max_count else 0
        bar = "█" * bar_len + " " * (bar_width - bar_len)
        print(f"  {label}   {bar}  {count:>5}  {pct:.0f}%")


def print_terminal_report(funcs: list[FunctionInfo], limit: int) -> None:
    """Print violation table, summary, and distribution histogram to stdout."""
    violations = detect_violations(funcs, limit)
    _print_violations_table(violations, limit)
    _print_summary(funcs, violations)
    _print_distribution(funcs)
