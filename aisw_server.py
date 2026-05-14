#!/usr/bin/env python3
"""
AI Software House Integration Server

Exposes a REST API + MCP server for triggering and monitoring pipelines.

Usage:
    python aisw_server.py                # uses aisw_server.yaml
    python aisw_server.py --port 9000
    AISW_API_KEY=secret python aisw_server.py
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import uvicorn
import yaml


def _load_config(path: str = "aisw_server.yaml") -> dict:
    if not Path(path).exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main() -> None:
    parser = argparse.ArgumentParser(description="AISW Integration Server")
    parser.add_argument("--config", default="aisw_server.yaml")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    cfg = _load_config(args.config)
    srv = cfg.get("server", {})
    defaults = cfg.get("defaults", {})

    host = args.host if args.host is not None else srv.get("host", "0.0.0.0")
    port = args.port if args.port is not None else srv.get("port", 8765)
    api_key = os.environ.get("AISW_API_KEY") or srv.get("api_key", "change-me")

    import warnings as _warnings
    if api_key == "change-me":
        _warnings.warn(
            "api_key is still the default 'change-me' placeholder — "
            "set AISW_API_KEY before deploying",
            UserWarning,
            stacklevel=1,
        )
    from server import auth as auth_mod
    auth_mod.set_api_key(api_key)

    from server.job_store import JobStore
    from server.job_runner import JobRunner
    from server.app import create_app

    store = JobStore(db_path="jobs.db")
    store.init_db()

    runner = JobRunner(
        store=store,
        log_dir=Path("logs/jobs"),
        config_yaml=defaults.get("config_yaml", "config.yaml"),
        default_repo=defaults.get("repo", ""),
        default_pipeline=defaults.get("pipeline", "ai-feature"),
        default_engineers=defaults.get("engineers", 2),
    )
    # Save original stdout/stderr before runner.start() installs its proxy writer
    _stdout = sys.stdout
    _stderr = sys.stderr

    runner.start()

    app = create_app(runner=runner)

    # Mount MCP server (auto-generates tools from FastAPI routes)
    try:
        from fastapi_mcp import FastApiMCP
        mcp = FastApiMCP(app)
        mcp.mount()
        print(f"MCP server mounted at http://{host}:{port}/mcp", file=_stdout, flush=True)
    except ImportError:
        print("Warning: fastapi-mcp not installed — MCP endpoint not available", file=_stderr, flush=True)

    print(f"AISW server starting on http://{host}:{port}", file=_stdout, flush=True)
    try:
        uvicorn.run(app, host=host, port=port)
    finally:
        runner.shutdown()


if __name__ == "__main__":
    main()
