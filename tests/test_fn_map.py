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
