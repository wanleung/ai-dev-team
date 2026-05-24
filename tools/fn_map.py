"""Function size reporter and interactive HTML map generator.

Usage:
    python tools/fn_map.py                   # uses fn_map.yaml in cwd
    python tools/fn_map.py --config <path>   # alternate config
    python tools/fn_map.py --limit 50        # override line limit
    python tools/fn_map.py --no-html         # terminal output only
"""
from __future__ import annotations

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
