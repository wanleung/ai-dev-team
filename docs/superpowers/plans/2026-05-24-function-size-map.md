# Function Size Report & Map — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `tools/fn_map.py` — an advisory tool that reports function size violations and generates an interactive HTML function map for the ai-software-house core codebase.

**Architecture:** A standalone Python script with small internal functions (≤30 lines each, practising what it preaches). It uses Python's `ast` module for static analysis, `pyyaml` for config, and generates a self-contained HTML file with inline CSS/JS for the interactive map.

**Tech Stack:** Python stdlib (`ast`, `argparse`, `dataclasses`, `pathlib`, `json`), PyYAML (already in requirements.txt), pytest for tests.

---

### Task 1: Scaffold + data model + config loader

**Files:**
- Create: `tools/fn_map.py`
- Create: `tests/test_fn_map.py`

- [ ] **Step 1.1: Write the failing tests**

```python
# tests/test_fn_map.py
"""Tests for tools/fn_map.py — function size reporter and map generator."""
from __future__ import annotations

import textwrap
from pathlib import Path
import pytest
from tools.fn_map import FunctionInfo, FnMapConfig, load_config

# ── Task 1: Data model + config loader ──────────────────────────────────────

def test_function_info_defaults():
    fn = FunctionInfo(name="my_fn", file="foo.py", lineno=10, line_count=5, calls=set())
    assert fn.name == "my_fn"
    assert fn.calls == set()

def test_config_defaults():
    cfg = FnMapConfig()
    assert cfg.limit == 30
    assert "orchestrator.py" in cfg.include
    assert "workspace/" in cfg.exclude
    assert cfg.html_output == "fn_map.html"

def test_load_config_missing_file(tmp_path):
    cfg = load_config(str(tmp_path / "nonexistent.yaml"))
    assert cfg.limit == 30  # falls back to defaults

def test_load_config_overrides_limit(tmp_path):
    yaml_file = tmp_path / "fn_map.yaml"
    yaml_file.write_text("limit: 50\n")
    cfg = load_config(str(yaml_file))
    assert cfg.limit == 50

def test_load_config_overrides_html_output(tmp_path):
    yaml_file = tmp_path / "fn_map.yaml"
    yaml_file.write_text("output:\n  html: custom_map.html\n")
    cfg = load_config(str(yaml_file))
    assert cfg.html_output == "custom_map.html"

def test_load_config_null_html_disables_output(tmp_path):
    yaml_file = tmp_path / "fn_map.yaml"
    yaml_file.write_text("output:\n  html: null\n")
    cfg = load_config(str(yaml_file))
    assert cfg.html_output is None

def test_load_config_overrides_include(tmp_path):
    yaml_file = tmp_path / "fn_map.yaml"
    yaml_file.write_text("include:\n  - foo.py\n  - bar/\n")
    cfg = load_config(str(yaml_file))
    assert cfg.include == ["foo.py", "bar/"]
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/test_fn_map.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'tools.fn_map'`

- [ ] **Step 1.3: Create `tools/fn_map.py` with data model and config loader**

```python
# tools/fn_map.py
"""Function size reporter and interactive HTML map generator.

Usage:
    python tools/fn_map.py                   # uses fn_map.yaml in cwd
    python tools/fn_map.py --config <path>   # alternate config
    python tools/fn_map.py --limit 50        # override line limit
    python tools/fn_map.py --no-html         # terminal output only
"""
from __future__ import annotations

import ast
import argparse
import json
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
    include: list = field(default_factory=lambda: [
        "orchestrator.py", "watcher.py", "rss_watcher.py",
        "intake_triage.py", "intake_scoring.py", "main.py",
        "tracker_adapter.py", "config_schema.py", "agents/", "tools/",
    ])
    exclude: list = field(default_factory=lambda: [
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
        cfg.limit = int(data["limit"])
    if "include" in data:
        cfg.include = list(data["include"])
    if "exclude" in data:
        cfg.exclude = list(data["exclude"])
    if isinstance(data.get("output"), dict):
        cfg.html_output = data["output"].get("html", cfg.html_output)
    return cfg
```

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_fn_map.py -v -k "task1 or test_function_info or test_config or test_load_config"
```

Expected: 7 tests PASS

- [ ] **Step 1.5: Commit**

```bash
git add tools/fn_map.py tests/test_fn_map.py
GIT_EDITOR=true git commit -m "feat(fn_map): data model + config loader"
```

---

### Task 2: Path resolution

**Files:**
- Modify: `tools/fn_map.py` — add `resolve_paths()`
- Modify: `tests/test_fn_map.py` — add path resolution tests

- [ ] **Step 2.1: Write the failing tests**

Add to `tests/test_fn_map.py`:

```python
# ── Task 2: Path resolution ──────────────────────────────────────────────────
from tools.fn_map import resolve_paths

def test_resolve_paths_includes_py_file(tmp_path):
    f = tmp_path / "foo.py"
    f.write_text("x = 1")
    result = resolve_paths(["foo.py"], [], root=tmp_path)
    assert f in result

def test_resolve_paths_excludes_match(tmp_path):
    (tmp_path / "workspace").mkdir()
    f = tmp_path / "workspace" / "bar.py"
    f.write_text("x = 1")
    result = resolve_paths(["workspace/"], ["workspace/"], root=tmp_path)
    assert f not in result

def test_resolve_paths_recurses_directory(tmp_path):
    sub = tmp_path / "agents"
    sub.mkdir()
    f1 = sub / "one.py"
    f2 = sub / "two.py"
    f1.write_text("x = 1")
    f2.write_text("x = 2")
    result = resolve_paths(["agents/"], [], root=tmp_path)
    assert f1 in result
    assert f2 in result

def test_resolve_paths_ignores_missing_include(tmp_path):
    result = resolve_paths(["nonexistent.py"], [], root=tmp_path)
    assert result == []
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_fn_map.py -v -k "resolve_paths"
```

Expected: `ImportError` or `AttributeError` — `resolve_paths` not defined

- [ ] **Step 2.3: Add `resolve_paths` to `tools/fn_map.py`**

Add after `load_config`:

```python
def resolve_paths(
    include: list[str],
    exclude: list[str],
    root: Path,
) -> list[Path]:
    """Expand include globs/dirs and filter out excluded prefixes."""
    collected: list[Path] = []
    for inc in include:
        p = root / inc
        if p.is_dir():
            collected.extend(p.rglob("*.py"))
        elif p.is_file():
            collected.append(p)
    result = []
    for p in collected:
        rel = str(p.relative_to(root))
        excluded = any(rel.startswith(ex.rstrip("/")) for ex in exclude)
        if not excluded:
            result.append(p)
    return sorted(set(result))
```

- [ ] **Step 2.4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_fn_map.py -v -k "resolve_paths"
```

Expected: 4 tests PASS

- [ ] **Step 2.5: Commit**

```bash
git add tools/fn_map.py tests/test_fn_map.py
GIT_EDITOR=true git commit -m "feat(fn_map): path resolution"
```

---

### Task 3: AST analysis

**Files:**
- Modify: `tools/fn_map.py` — add `_extract_calls`, `_parse_file`, `collect_functions`
- Modify: `tests/test_fn_map.py` — add AST analysis tests

- [ ] **Step 3.1: Write the failing tests**

Add to `tests/test_fn_map.py`:

```python
# ── Task 3: AST analysis ────────────────────────────────────────────────────
from tools.fn_map import _extract_calls, _parse_file, collect_functions
import ast

def _make_py(tmp_path, name, code):
    f = tmp_path / name
    f.write_text(code)
    return f

def test_extract_calls_finds_direct_call():
    src = "def foo():\n    bar()\n    baz()\n"
    tree = ast.parse(src)
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    calls = _extract_calls(node)
    assert "bar" in calls
    assert "baz" in calls

def test_extract_calls_finds_method_call():
    src = "def foo(self):\n    self.helper()\n"
    tree = ast.parse(src)
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    calls = _extract_calls(node)
    assert "helper" in calls

def test_parse_file_basic(tmp_path):
    f = _make_py(tmp_path, "sample.py", "def short():\n    pass\n")
    results = _parse_file(f, tmp_path)
    assert len(results) == 1
    assert results[0].name == "short"
    assert results[0].line_count == 2
    assert results[0].lineno == 1
    assert results[0].file == "sample.py"

def test_parse_file_multi_function(tmp_path):
    code = "def a():\n    pass\n\ndef b():\n    a()\n"
    f = _make_py(tmp_path, "multi.py", code)
    results = _parse_file(f, tmp_path)
    names = {r.name for r in results}
    assert names == {"a", "b"}
    b_fn = next(r for r in results if r.name == "b")
    assert "a" in b_fn.calls

def test_parse_file_syntax_error_returns_empty(tmp_path):
    f = _make_py(tmp_path, "bad.py", "def (broken")
    results = _parse_file(f, tmp_path)
    assert results == []

def test_collect_functions_aggregates(tmp_path):
    _make_py(tmp_path, "a.py", "def f1():\n    pass\n")
    _make_py(tmp_path, "b.py", "def f2():\n    pass\n\ndef f3():\n    pass\n")
    paths = [tmp_path / "a.py", tmp_path / "b.py"]
    funcs = collect_functions(paths, tmp_path)
    assert len(funcs) == 3
    assert {f.name for f in funcs} == {"f1", "f2", "f3"}
```

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_fn_map.py -v -k "extract_calls or parse_file or collect_functions"
```

Expected: `ImportError` — functions not defined

- [ ] **Step 3.3: Add AST functions to `tools/fn_map.py`**

Add after `resolve_paths`:

```python
def _extract_calls(node: ast.FunctionDef) -> set[str]:
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
```

- [ ] **Step 3.4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_fn_map.py -v -k "extract_calls or parse_file or collect_functions"
```

Expected: 7 tests PASS

- [ ] **Step 3.5: Commit**

```bash
git add tools/fn_map.py tests/test_fn_map.py
GIT_EDITOR=true git commit -m "feat(fn_map): AST analysis — extract calls + parse files"
```

---

### Task 4: Analysis logic

**Files:**
- Modify: `tools/fn_map.py` — add `detect_violations`, `build_distribution`, `build_call_index`, `build_calledby_index`
- Modify: `tests/test_fn_map.py` — add analysis logic tests

- [ ] **Step 4.1: Write the failing tests**

Add to `tests/test_fn_map.py`:

```python
# ── Task 4: Analysis logic ───────────────────────────────────────────────────
from tools.fn_map import (
    detect_violations, build_distribution, build_call_index, build_calledby_index,
)

def _make_fn(name, line_count, file="a.py", calls=None):
    return FunctionInfo(name=name, file=file, lineno=1,
                        line_count=line_count, calls=calls or set())

def test_detect_violations_filters_over_limit():
    funcs = [_make_fn("short", 10), _make_fn("long", 40), _make_fn("huge", 100)]
    violations = detect_violations(funcs, limit=30)
    assert len(violations) == 2
    assert violations[0].line_count == 100   # sorted descending
    assert violations[1].line_count == 40

def test_detect_violations_none_over_limit():
    funcs = [_make_fn("a", 5), _make_fn("b", 30)]
    assert detect_violations(funcs, limit=30) == []

def test_build_distribution_buckets():
    funcs = [_make_fn("a", 5), _make_fn("b", 15), _make_fn("c", 25), _make_fn("d", 60)]
    dist = build_distribution(funcs, [10, 20, 30, 50, 100])
    labels = [label for label, _ in dist]
    counts = {label: count for label, count in dist}
    assert counts["≤10 lines"] == 1   # a
    assert counts["≤20 lines"] == 1   # b
    assert counts["≤30 lines"] == 1   # c
    assert counts["≤50 lines"] == 0
    assert counts["≤100 lines"] == 1  # d
    assert counts[">100 lines"] == 0

def test_build_call_index():
    fn_a = _make_fn("alpha", 10)
    fn_b = _make_fn("beta", 20)
    idx = build_call_index([fn_a, fn_b])
    assert "alpha" in idx
    assert idx["beta"] is fn_b

def test_build_calledby_index():
    fn_a = _make_fn("caller", 10, calls={"helper", "util"})
    fn_b = _make_fn("helper", 5)
    idx = build_calledby_index([fn_a, fn_b])
    assert "helper" in idx
    assert "caller" in idx["helper"]
    assert "util" in idx
```

- [ ] **Step 4.2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_fn_map.py -v -k "violations or distribution or call_index or calledby"
```

Expected: `ImportError` — functions not defined

- [ ] **Step 4.3: Add analysis logic to `tools/fn_map.py`**

Add after `collect_functions`:

```python
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
        result.append((f"≤{b:>3} lines", count))
        prev = b
    over = sum(1 for f in funcs if f.line_count > sorted(buckets)[-1])
    result.append((f">{sorted(buckets)[-1]:>3} lines", over))
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
```

- [ ] **Step 4.4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_fn_map.py -v -k "violations or distribution or call_index or calledby"
```

Expected: 5 tests PASS

- [ ] **Step 4.5: Commit**

```bash
git add tools/fn_map.py tests/test_fn_map.py
GIT_EDITOR=true git commit -m "feat(fn_map): analysis logic — violations, distribution, call index"
```

---

### Task 5: Terminal report

**Files:**
- Modify: `tools/fn_map.py` — add `_colour`, `_fn_colour_code`, `_print_violations_table`, `_print_summary`, `_print_distribution`, `print_terminal_report`
- Modify: `tests/test_fn_map.py` — add terminal report tests

- [ ] **Step 5.1: Write the failing tests**

Add to `tests/test_fn_map.py`:

```python
# ── Task 5: Terminal report ──────────────────────────────────────────────────
from tools.fn_map import print_terminal_report

def test_print_terminal_report_shows_violations(capsys):
    funcs = [_make_fn("big_fn", 50, "mymodule.py"), _make_fn("small_fn", 5)]
    print_terminal_report(funcs, limit=30)
    captured = capsys.readouterr().out
    assert "big_fn" in captured
    assert "50" in captured
    assert "mymodule.py" in captured

def test_print_terminal_report_shows_summary(capsys):
    funcs = [_make_fn("a", 40), _make_fn("b", 10), _make_fn("c", 20)]
    print_terminal_report(funcs, limit=30)
    captured = capsys.readouterr().out
    assert "1 violation" in captured or "violations" in captured
    assert "2 compliant" in captured or "compliant" in captured

def test_print_terminal_report_shows_distribution(capsys):
    funcs = [_make_fn("a", 5), _make_fn("b", 15), _make_fn("c", 35)]
    print_terminal_report(funcs, limit=30)
    captured = capsys.readouterr().out
    assert "Distribution" in captured

def test_print_terminal_report_no_violations(capsys):
    funcs = [_make_fn("a", 10), _make_fn("b", 20)]
    print_terminal_report(funcs, limit=30)
    captured = capsys.readouterr().out
    assert "0 violation" in captured or "violations" in captured
```

- [ ] **Step 5.2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_fn_map.py -v -k "terminal_report"
```

Expected: `ImportError` — `print_terminal_report` not defined

- [ ] **Step 5.3: Add terminal report functions to `tools/fn_map.py`**

Add after `build_calledby_index`:

```python
def _colour(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def _fn_colour_code(line_count: int, limit: int) -> str:
    if line_count <= limit:
        return "32"   # green
    if line_count <= 50:
        return "33"   # orange/yellow
    return "31"       # red


def _print_violations_table(violations: list[FunctionInfo], limit: int) -> None:
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
    total = len(funcs)
    compliant = total - len(violations)
    pct = compliant / total * 100 if total else 0
    v_str = _colour(f"{len(violations)} violation{'s' if len(violations) != 1 else ''}", "31")
    c_str = _colour(f"{compliant} compliant ({pct:.0f}%)", "32")
    print(f"\n{v_str}  |  {c_str}  |  {total} total\n")


def _print_distribution(funcs: list[FunctionInfo]) -> None:
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
```

- [ ] **Step 5.4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_fn_map.py -v -k "terminal_report"
```

Expected: 4 tests PASS

- [ ] **Step 5.5: Commit**

```bash
git add tools/fn_map.py tests/test_fn_map.py
GIT_EDITOR=true git commit -m "feat(fn_map): terminal report with colour coding"
```

---

### Task 6: HTML generation

**Files:**
- Modify: `tools/fn_map.py` — add `_fn_css_class`, `_render_function_card`, `_render_module_group`, `_build_fn_data_json`, `_html_head`, `_html_sidebar`, `_html_script`, `generate_html`
- Modify: `tests/test_fn_map.py` — add HTML generation tests

- [ ] **Step 6.1: Write the failing tests**

Add to `tests/test_fn_map.py`:

```python
# ── Task 6: HTML generation ──────────────────────────────────────────────────
from tools.fn_map import generate_html, _render_function_card, _fn_css_class

def test_fn_css_class_ok():
    fn = _make_fn("ok", 20)
    assert _fn_css_class(fn, 30) == "fn-ok"

def test_fn_css_class_warn():
    fn = _make_fn("warn", 40)
    assert _fn_css_class(fn, 30) == "fn-warn"

def test_fn_css_class_bad():
    fn = _make_fn("bad", 80)
    assert _fn_css_class(fn, 30) == "fn-bad"

def test_render_function_card_contains_name():
    fn = _make_fn("my_function", 25, calls={"other"})
    html = _render_function_card(fn, 30)
    assert "my_function" in html
    assert "25" in html

def test_generate_html_creates_file(tmp_path):
    funcs = [
        _make_fn("alpha", 10, "mod.py", calls={"beta"}),
        _make_fn("beta", 45, "mod.py"),
    ]
    out = str(tmp_path / "map.html")
    generate_html(funcs, limit=30, output_path=out)
    content = Path(out).read_text()
    assert "alpha" in content
    assert "beta" in content
    assert "<!DOCTYPE html>" in content

def test_generate_html_embeds_call_data(tmp_path):
    funcs = [_make_fn("caller_fn", 10, "a.py", calls={"callee_fn"}),
             _make_fn("callee_fn", 5, "a.py")]
    out = str(tmp_path / "map.html")
    generate_html(funcs, limit=30, output_path=out)
    content = Path(out).read_text()
    assert "caller_fn" in content
    assert "callee_fn" in content

def test_generate_html_has_filter_buttons(tmp_path):
    funcs = [_make_fn("f", 10, "x.py")]
    out = str(tmp_path / "map.html")
    generate_html(funcs, limit=30, output_path=out)
    content = Path(out).read_text()
    assert "Violations only" in content
    assert "All" in content
```

- [ ] **Step 6.2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_fn_map.py -v -k "html or fn_css_class or render_function"
```

Expected: `ImportError` — functions not defined

- [ ] **Step 6.3: Add HTML rendering helpers to `tools/fn_map.py`**

Add after `print_terminal_report`:

```python
def _fn_css_class(fn: FunctionInfo, limit: int) -> str:
    if fn.line_count <= limit:
        return "fn-ok"
    if fn.line_count <= 50:
        return "fn-warn"
    return "fn-bad"


def _render_function_card(fn: FunctionInfo, limit: int) -> str:
    css = _fn_css_class(fn, limit)
    key = f"{fn.file}::{fn.name}::{fn.lineno}"
    key_safe = key.replace("'", "\\'")
    calls_n = len(fn.calls)
    return (
        f'<div class="fn-card {css}" '
        f'onclick="showDetail(\'{key_safe}\')" '
        f'data-violation="{1 if fn.line_count > limit else 0}" '
        f'data-big="{1 if fn.line_count > 50 else 0}">'
        f'<div class="fn-name">{fn.name}</div>'
        f'<div class="fn-meta">{fn.line_count} lines · :{fn.lineno}</div>'
        f'<div class="fn-calls">{calls_n} call{"s" if calls_n != 1 else ""}</div>'
        f'</div>'
    )


def _render_module_group(file: str, funcs: list[FunctionInfo], limit: int) -> str:
    violations = sum(1 for f in funcs if f.line_count > limit)
    cards = "\n".join(_render_function_card(f, limit) for f in funcs)
    badge_class = "badge-bad" if violations > 0 else "badge-ok"
    return (
        f'<div class="module-box" data-file="{file}">'
        f'<div class="module-header">'
        f'<span class="module-name">{file}</span>'
        f'<span class="{badge_class}">{violations} violation{"s" if violations != 1 else ""}'
        f' / {len(funcs)} fn</span>'
        f'</div>'
        f'<div class="fn-cards">{cards}</div>'
        f'</div>'
    )
```

- [ ] **Step 6.4: Add `_build_fn_data_json` and HTML page builders to `tools/fn_map.py`**

Add after `_render_module_group`:

```python
def _build_fn_data_json(funcs: list[FunctionInfo], calledby: dict[str, list[str]]) -> str:
    """Build a JSON object mapping key → {name, file, lineno, lines, calls, calledBy}."""
    data: dict[str, dict] = {}
    for fn in funcs:
        key = f"{fn.file}::{fn.name}::{fn.lineno}"
        data[key] = {
            "name": fn.name, "file": fn.file, "lineno": fn.lineno,
            "lines": fn.line_count, "calls": sorted(fn.calls),
            "calledBy": sorted(calledby.get(fn.name, [])),
        }
    return json.dumps(data)


def _html_head() -> str:
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Function Map</title>
<style>
body{font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3;margin:0}
#toolbar{background:#161b22;padding:.5em 1em;display:flex;gap:.6em;align-items:center;border-bottom:1px solid #30363d}
#toolbar h1{font-size:1em;margin:0;color:#79c0ff}
.filter-btn{background:#30363d;border:none;color:#e6edf3;padding:.25em .7em;border-radius:4px;cursor:pointer}
.filter-btn.active{background:#238636}
#layout{display:flex;height:calc(100vh - 41px)}
#sidebar{width:220px;border-right:1px solid #30363d;overflow-y:auto;padding:.5em}
#sidebar .s-file{padding:.3em .5em;border-radius:4px;cursor:pointer;display:flex;justify-content:space-between;font-size:.85em;margin-bottom:.2em}
.badge-bad{background:#da3633;color:#fff;padding:0 .4em;border-radius:3px;font-size:.8em}
.badge-ok{background:#1a7f37;color:#fff;padding:0 .4em;border-radius:3px;font-size:.8em}
#main{flex:1;overflow-y:auto;padding:1em}
.module-box{background:#161b22;border:1px solid #30363d;border-radius:8px;margin-bottom:1em}
.module-header{padding:.5em 1em;border-bottom:1px solid #30363d;display:flex;gap:.6em;align-items:center}
.module-name{font-weight:bold}
.fn-cards{padding:.7em 1em;display:flex;flex-wrap:wrap;gap:.5em}
.fn-card{border-radius:6px;padding:.4em .7em;cursor:pointer;min-width:140px;border:1px solid}
.fn-ok{background:#0a1a0a;border-color:#238636}
.fn-warn{background:#1a1200;border-color:#d29922}
.fn-bad{background:#1a0a0a;border-color:#da3633}
.fn-name{font-weight:bold;font-size:.9em}
.fn-meta,.fn-calls{color:#8b949e;font-size:.75em}
#detail{border-top:1px solid #30363d;padding:1em;background:#161b22;min-height:80px;display:none}
#detail h3{margin:0 0 .5em;color:#79c0ff}
.detail-cols{display:flex;gap:2em}
.detail-col h4{color:#8b949e;font-size:.75em;text-transform:uppercase;margin:0 0 .3em}
.detail-col a{color:#3fb950;text-decoration:none;display:block;font-size:.85em}
.detail-col a:hover{text-decoration:underline}
.detail-col span{color:#8b949e;font-size:.85em;display:block}
</style></head><body>"""


def _html_sidebar(by_file: dict[str, list[FunctionInfo]], limit: int) -> str:
    items = []
    for file, funcs in sorted(by_file.items()):
        v = sum(1 for f in funcs if f.line_count > limit)
        badge = f'<span class="badge-{"bad" if v else "ok"}">{v}</span>'
        items.append(
            f'<div class="s-file" onclick="scrollToFile(\'{file}\')">'
            f'{file}{badge}</div>'
        )
    return f'<div id="sidebar">{"".join(items)}</div>'


def _html_script(fn_data_json: str) -> str:
    return f"""<script>
const FN_DATA = {fn_data_json};
function showDetail(key) {{
  const d = FN_DATA[key]; if (!d) return;
  document.getElementById('detail').style.display = 'block';
  const calls = d.calls.map(n => `<a href="#" onclick="findAndShow('${{n}}');return false">${{n}}</a>`).join('') || '<span>none</span>';
  const calledBy = d.calledBy.map(n => `<a href="#" onclick="findAndShow('${{n}}');return false">${{n}}</a>`).join('') || '<span>none</span>';
  document.getElementById('detail').innerHTML = `<h3>${{d.name}} <small style="color:#8b949e">${{d.file}}:${{d.lineno}} · ${{d.lines}} lines</small></h3><div class="detail-cols"><div class="detail-col"><h4>Calls</h4>${{calls}}</div><div class="detail-col"><h4>Called by</h4>${{calledBy}}</div></div>`;
}}
function findAndShow(name) {{
  const key = Object.keys(FN_DATA).find(k => FN_DATA[k].name === name);
  if (key) showDetail(key);
}}
function scrollToFile(file) {{
  const el = document.querySelector(`[data-file="${{file}}"]`);
  if (el) el.scrollIntoView({{behavior:'smooth'}});
}}
function applyFilter(mode, btn) {{
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.fn-card').forEach(c => {{
    const v = c.dataset.violation === '1', big = c.dataset.big === '1';
    c.style.display = (mode==='all' || (mode==='violations' && v) || (mode==='big' && big)) ? '' : 'none';
  }});
}}
document.addEventListener('DOMContentLoaded', () => {{
  document.querySelector('.filter-btn').classList.add('active');
}});
</script>"""


def generate_html(funcs: list[FunctionInfo], limit: int, output_path: str) -> None:
    """Write a self-contained interactive HTML function map to output_path."""
    calledby = build_calledby_index(funcs)
    by_file: dict[str, list[FunctionInfo]] = {}
    for fn in funcs:
        by_file.setdefault(fn.file, []).append(fn)
    groups = "\n".join(
        _render_module_group(file, fns, limit)
        for file, fns in sorted(by_file.items())
    )
    toolbar = (
        '<div id="toolbar"><h1>fn_map</h1>'
        '<button class="filter-btn" onclick="applyFilter(\'all\',this)">All</button>'
        '<button class="filter-btn" onclick="applyFilter(\'violations\',this)">Violations only</button>'
        '<button class="filter-btn" onclick="applyFilter(\'big\',this)">&gt;50 lines</button>'
        '</div>'
    )
    sidebar = _html_sidebar(by_file, limit)
    main = f'<div id="main">{groups}</div>'
    detail = '<div id="detail"></div>'
    script = _html_script(_build_fn_data_json(funcs, calledby))
    html = (
        _html_head() + toolbar
        + f'<div id="layout">{sidebar}{main}</div>'
        + detail + script + "</body></html>"
    )
    Path(output_path).write_text(html, encoding="utf-8")
```

- [ ] **Step 6.5: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_fn_map.py -v -k "html or fn_css_class or render_function"
```

Expected: 8 tests PASS

- [ ] **Step 6.6: Commit**

```bash
git add tools/fn_map.py tests/test_fn_map.py
GIT_EDITOR=true git commit -m "feat(fn_map): HTML map generation with sidebar, cards, and detail panel"
```

---

### Task 7: CLI entry point + config file + gitignore

**Files:**
- Modify: `tools/fn_map.py` — add `main()`
- Create: `fn_map.yaml`
- Modify: `.gitignore` — add `fn_map.html`

- [ ] **Step 7.1: Write the failing integration test**

Add to `tests/test_fn_map.py`:

```python
# ── Task 7: CLI integration ───────────────────────────────────────────────────
import subprocess, sys

def test_cli_runs_without_error(tmp_path):
    """Run fn_map.py --no-html against a tiny sample dir and check exit code 0."""
    sample = tmp_path / "sample.py"
    sample.write_text("def alpha():\n    pass\n\ndef beta():\n    alpha()\n")
    cfg = tmp_path / "fn_map.yaml"
    cfg.write_text(f"include:\n  - sample.py\nlimit: 30\noutput:\n  html: null\n")
    result = subprocess.run(
        [sys.executable, "tools/fn_map.py", "--config", str(cfg), "--root", str(tmp_path)],
        capture_output=True, text=True,
        cwd="/home/wanleung/Projects/ai-software-house",
    )
    assert result.returncode == 0, result.stderr
    assert "Function Size Report" in result.stdout

def test_cli_writes_html(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text("def alpha():\n    pass\n")
    cfg = tmp_path / "fn_map.yaml"
    out_html = tmp_path / "out.html"
    cfg.write_text(f"include:\n  - sample.py\nlimit: 30\noutput:\n  html: {out_html}\n")
    result = subprocess.run(
        [sys.executable, "tools/fn_map.py", "--config", str(cfg), "--root", str(tmp_path)],
        capture_output=True, text=True,
        cwd="/home/wanleung/Projects/ai-software-house",
    )
    assert result.returncode == 0, result.stderr
    assert out_html.exists()
    assert "<!DOCTYPE html>" in out_html.read_text()
```

- [ ] **Step 7.2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_fn_map.py -v -k "cli"
```

Expected: `AssertionError` or non-zero exit (no `main()` yet)

- [ ] **Step 7.3: Add `main()` to `tools/fn_map.py`**

Add at the end of `tools/fn_map.py`:

```python
def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Function size reporter and HTML map generator")
    p.add_argument("--config", default="fn_map.yaml", help="Path to fn_map.yaml (default: fn_map.yaml)")
    p.add_argument("--limit", type=int, default=None, help="Override function line limit")
    p.add_argument("--no-html", action="store_true", help="Skip HTML output")
    p.add_argument("--root", default=".", help="Repo root directory (default: cwd)")
    return p


def main() -> None:
    args = _build_arg_parser().parse_args()
    cfg = load_config(args.config)
    if args.limit is not None:
        cfg.limit = args.limit
    if args.no_html:
        cfg.html_output = None
    root = Path(args.root).resolve()
    paths = resolve_paths(cfg.include, cfg.exclude, root)
    funcs = collect_functions(paths, root)
    print_terminal_report(funcs, cfg.limit)
    if cfg.html_output:
        html_path = str(Path(args.root) / cfg.html_output)
        generate_html(funcs, cfg.limit, html_path)
        print(f"\nHTML map written → {html_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7.4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_fn_map.py -v -k "cli"
```

Expected: 2 tests PASS

- [ ] **Step 7.5: Run the full test suite to confirm no regressions**

```bash
python3 -m pytest tests/test_fn_map.py -v
```

Expected: all tests PASS (should be ~30+ tests)

- [ ] **Step 7.6: Create `fn_map.yaml` in repo root**

```yaml
# fn_map.yaml — function size report configuration
# Run: python tools/fn_map.py

limit: 30

include:
  - orchestrator.py
  - watcher.py
  - rss_watcher.py
  - intake_triage.py
  - intake_scoring.py
  - main.py
  - tracker_adapter.py
  - config_schema.py
  - agents/
  - tools/

exclude:
  - workspace/
  - .venv/
  - venv/
  - tests/
  - .git/
  - __pycache__/
  - tools/fn_map.py   # exclude self-analysis

output:
  html: fn_map.html
```

- [ ] **Step 7.7: Add `fn_map.html` to `.gitignore`**

Add to `.gitignore` (after the existing `test_deployment.db` line):

```
fn_map.html
```

- [ ] **Step 7.8: Run the tool against the real codebase to verify it works**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 tools/fn_map.py
```

Expected output: Function Size Report showing orchestrator.py violations, then `HTML map written → fn_map.html`. Open `fn_map.html` in a browser to verify the interactive map renders.

- [ ] **Step 7.9: Commit**

```bash
git add tools/fn_map.py fn_map.yaml .gitignore tests/test_fn_map.py
GIT_EDITOR=true git commit -m "feat(fn_map): CLI entry point, fn_map.yaml config, gitignore

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by |
|---|---|
| `FunctionInfo` dataclass | Task 1 |
| `FnMapConfig` + `load_config` | Task 1 |
| `resolve_paths` with include/exclude | Task 2 |
| `_extract_calls` / `_parse_file` / `collect_functions` | Task 3 |
| `detect_violations` / `build_distribution` / `build_call_index` | Task 4 |
| `build_calledby_index` | Task 4 |
| `print_terminal_report` with colour coding | Task 5 |
| HTML: sidebar + module boxes + function cards | Task 6 |
| HTML: filter buttons (All/Violations/50+) | Task 6 |
| HTML: detail panel with calls + called-by | Task 6 |
| Self-contained static HTML (no external deps) | Task 6 |
| `main()` with `--config`, `--limit`, `--no-html`, `--root` | Task 7 |
| `fn_map.yaml` committed to repo | Task 7 |
| `fn_map.html` gitignored | Task 7 |
| Every internal function ≤ 30 lines | All tasks (enforced by design) |

**Placeholder scan:** No TBDs, TODOs, or "implement later" — all code is complete. ✓

**Type consistency:**
- `FunctionInfo` defined in Task 1, used consistently throughout
- `build_calledby_index` defined in Task 4, called in Task 6 `generate_html` ✓
- `detect_violations` defined in Task 4, called in Task 5 `_print_violations_table` ✓
- `build_distribution` defined in Task 4, called in Task 5 `_print_distribution` ✓
- `resolve_paths` signature `(include, exclude, root)` in Task 2, called in Task 7 `main()` with `(cfg.include, cfg.exclude, root)` ✓
- `collect_functions(paths, root)` in Task 3, called in Task 7 with `(paths, root)` ✓
- `_fn_css_class` defined in Task 6, called in `_render_function_card` ✓

All good. ✓
