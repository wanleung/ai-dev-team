"""Tests for tools/fn_map.py — function size reporter and map generator."""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path
import pytest
from tools.fn_map import FunctionInfo, FnMapConfig, load_config, resolve_paths, _extract_calls, _parse_file, collect_functions, detect_violations, build_distribution, build_call_index, build_calledby_index, print_terminal_report

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

def test_load_config_overrides_exclude(tmp_path):
    yaml_file = tmp_path / "fn_map.yaml"
    yaml_file.write_text("exclude:\n  - custom_exclude/\n")
    cfg = load_config(str(yaml_file))
    assert cfg.exclude == ["custom_exclude/"]

# ── Task 2: Path resolution ──────────────────────────────────────────────────

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
    result = resolve_paths(["agents/"], [], root=tmp_path)  # trailing slash required
    assert f1 in result
    assert f2 in result

def test_resolve_paths_exclude_does_not_match_prefix(tmp_path):
    (tmp_path / "workspace_extra").mkdir()
    f = tmp_path / "workspace_extra" / "file.py"
    f.write_text("x = 1")
    result = resolve_paths(["workspace_extra/"], ["workspace/"], root=tmp_path)
    assert f in result  # should NOT be excluded — "workspace/" exclude must not match "workspace_extra/"

def test_resolve_paths_ignores_missing_include(tmp_path):
    result = resolve_paths(["nonexistent.py"], [], root=tmp_path)
    assert result == []

# ── Task 3: AST analysis ────────────────────────────────────────────────────

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

# ── Task 4: Analysis logic ───────────────────────────────────────────────────

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


# ── Task 5: Terminal report ──────────────────────────────────────────────────

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

# ── Task 6: HTML generation ──────────────────────────────────────────────────
from tools.fn_map import generate_html, _render_function_card, _fn_css_class

def test_render_function_card_escapes_html():
    fn = FunctionInfo(
        name='evil<script>alert(1)</script>',
        file="test.py", lineno=1, line_count=10, calls=set()
    )
    card = _render_function_card(fn, 30)
    assert "<script>" not in card
    assert "&lt;script&gt;" in card

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
