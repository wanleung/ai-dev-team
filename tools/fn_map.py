"""Function size reporter and interactive HTML map generator.

Usage:
    python tools/fn_map.py                   # uses fn_map.yaml in cwd
    python tools/fn_map.py --config <path>   # alternate config
    python tools/fn_map.py --limit 50        # override line limit
    python tools/fn_map.py --no-html         # terminal output only
"""
from __future__ import annotations

import argparse
import ast
import html
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


def _fn_css_class(fn: FunctionInfo, limit: int) -> str:
    if fn.line_count <= limit:
        return "fn-ok"
    if fn.line_count <= 50:
        return "fn-warn"
    return "fn-bad"


def _render_function_card(fn: FunctionInfo, limit: int) -> str:
    css = _fn_css_class(fn, limit)
    file_safe = html.escape(fn.file)
    name_safe = html.escape(fn.name)
    key = f"{file_safe}::{name_safe}::{fn.lineno}"
    key_safe = key.replace("'", "\\'")
    calls_n = len(fn.calls)
    return (
        f'<div class="fn-card {css}" '
        f'onclick="showDetail(\'{key_safe}\')" '
        f'data-violation="{1 if fn.line_count > limit else 0}" '
        f'data-big="{1 if fn.line_count > 50 else 0}">'
        f'<div class="fn-name">{name_safe}</div>'
        f'<div class="fn-meta">{fn.line_count} lines · :{fn.lineno}</div>'
        f'<div class="fn-calls">{calls_n} call{"s" if calls_n != 1 else ""}</div>'
        f'</div>'
    )


def _render_module_group(file: str, funcs: list[FunctionInfo], limit: int) -> str:
    violations = sum(1 for f in funcs if f.line_count > limit)
    cards = "\n".join(_render_function_card(f, limit) for f in funcs)
    badge_class = "badge-bad" if violations > 0 else "badge-ok"
    file_safe = html.escape(file)
    return (
        f'<div class="module-box" data-file="{file_safe}">'
        f'<div class="module-header">'
        f'<span class="module-name">{file_safe}</span>'
        f'<span class="{badge_class}">{violations} violation{"s" if violations != 1 else ""}'
        f' / {len(funcs)} fn</span>'
        f'</div>'
        f'<div class="fn-cards">{cards}</div>'
        f'</div>'
    )


def _build_fn_data_json(funcs: list[FunctionInfo], calledby: dict[str, list[str]]) -> str:
    """Build a JSON object mapping key → {name, file, lineno, lines, calls, calledBy}."""
    data: dict[str, dict] = {}
    for fn in funcs:
        file_safe = html.escape(fn.file)
        name_safe = html.escape(fn.name)
        key = f"{file_safe}::{name_safe}::{fn.lineno}"
        data[key] = {
            "name": fn.name, "file": fn.file, "lineno": fn.lineno,
            "lines": fn.line_count, "calls": sorted(fn.calls),
            "calledBy": sorted(calledby.get(fn.name, [])),
        }
    return json.dumps(data)


def _html_css() -> str:
    """Return inline CSS for the HTML map."""
    return (
        "body{font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3;margin:0}"
        "#toolbar{background:#161b22;padding:.5em 1em;display:flex;gap:.6em;align-items:center;border-bottom:1px solid #30363d}"
        "#toolbar h1{font-size:1em;margin:0;color:#79c0ff}"
        ".filter-btn{background:#30363d;border:none;color:#e6edf3;padding:.25em .7em;border-radius:4px;cursor:pointer}"
        ".filter-btn.active{background:#238636}"
        "#layout{display:flex;height:calc(100vh - 41px)}"
        "#sidebar{width:220px;border-right:1px solid #30363d;overflow-y:auto;padding:.5em}"
        "#sidebar .s-file{padding:.3em .5em;border-radius:4px;cursor:pointer;display:flex;justify-content:space-between;font-size:.85em;margin-bottom:.2em}"
        ".badge-bad{background:#da3633;color:#fff;padding:0 .4em;border-radius:3px;font-size:.8em}"
        ".badge-ok{background:#1a7f37;color:#fff;padding:0 .4em;border-radius:3px;font-size:.8em}"
        "#main{flex:1;overflow-y:auto;padding:1em}"
        ".module-box{background:#161b22;border:1px solid #30363d;border-radius:8px;margin-bottom:1em}"
        ".module-header{padding:.5em 1em;border-bottom:1px solid #30363d;display:flex;gap:.6em;align-items:center}"
        ".module-name{font-weight:bold}"
        ".fn-cards{padding:.7em 1em;display:flex;flex-wrap:wrap;gap:.5em}"
        ".fn-card{border-radius:6px;padding:.4em .7em;cursor:pointer;min-width:140px;border:1px solid}"
        ".fn-ok{background:#0a1a0a;border-color:#238636}"
        ".fn-warn{background:#1a1200;border-color:#d29922}"
        ".fn-bad{background:#1a0a0a;border-color:#da3633}"
        ".fn-name{font-weight:bold;font-size:.9em}"
        ".fn-meta,.fn-calls{color:#8b949e;font-size:.75em}"
        "#detail{border-top:1px solid #30363d;padding:1em;background:#161b22;min-height:80px;display:none}"
        "#detail h3{margin:0 0 .5em;color:#79c0ff}"
        ".detail-cols{display:flex;gap:2em}"
        ".detail-col h4{color:#8b949e;font-size:.75em;text-transform:uppercase;margin:0 0 .3em}"
        ".detail-col a{color:#3fb950;text-decoration:none;display:block;font-size:.85em}"
        ".detail-col a:hover{text-decoration:underline}"
        ".detail-col span{color:#8b949e;font-size:.85em;display:block}"
    )


def _html_head() -> str:
    """Return HTML document head with inline CSS."""
    return (
        '<!DOCTYPE html>\n<html lang="en"><head><meta charset="UTF-8">\n'
        '<title>Function Map</title>\n'
        f'<style>{_html_css()}</style></head><body>'
    )


def _html_sidebar(by_file: dict[str, list[FunctionInfo]], limit: int) -> str:
    items = []
    for file, funcs in sorted(by_file.items()):
        v = sum(1 for f in funcs if f.line_count > limit)
        badge = f'<span class="badge-{"bad" if v else "ok"}">{v}</span>'
        file_safe = html.escape(file)
        items.append(
            f'<div class="s-file" onclick="scrollToFile(\'{file_safe}\')">'
            f'{file_safe}{badge}</div>'
        )
    return f'<div id="sidebar">{"".join(items)}</div>'


def _html_script(fn_data_json: str) -> str:
    safe_json = fn_data_json.replace("</", "<\\/")
    return f"""<script>
const FN_DATA = {safe_json};
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
