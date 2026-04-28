"""Minimal HTTP server for the pipeline.yaml config builder GUI.

Usage (via main.py --config-builder):
    from pipeline_builder.server import run_builder
    run_builder(config_path="config.yaml")
"""
from __future__ import annotations

import json
import os
import pathlib
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

_STATIC_DIR = pathlib.Path(__file__).parent


def _get_stage_palette() -> list[dict]:
    """Return stage metadata for the GUI palette, derived from _make_stage_registry()."""
    try:
        from orchestrator import Orchestrator
        # Build a minimal stub orchestrator just to call _make_stage_registry()
        orch = Orchestrator.__new__(Orchestrator)
        orch._stage_skips = {}
        orch._pipeline_yaml_stages = None
        orch._mode = "standard"
        orch.stop_on_review_issues = False
        for attr in ("pm", "pm_reviewer", "architect", "architect_reviewer",
                     "engineer", "junior_engineer", "senior_engineer", "reviewer",
                     "qa", "qa_planner", "deployment_tester", "tier_reviewer"):
            setattr(orch, attr, None)
        registry = orch._make_stage_registry()
        return [
            {"name": name, "label": stage.label, "description": stage.description}
            for name, stage in registry.items()
        ]
    except Exception as exc:
        traceback.print_exc()
        return [{"name": "error", "label": f"Registry error: {exc}", "description": ""}]


def _load_existing_pipeline_yaml(config_path: str) -> Optional[str]:
    """Return raw pipeline.yaml text if it exists, else None."""
    p = pathlib.Path(config_path).parent / "pipeline.yaml"
    return p.read_text(encoding="utf-8") if p.exists() else None


def _save_pipeline_yaml(config_path: str, content: str) -> None:
    """Write content to pipeline.yaml alongside config_path."""
    p = pathlib.Path(config_path).parent / "pipeline.yaml"
    p.write_text(content, encoding="utf-8")


def run_builder(config_path: str = "config.yaml") -> None:
    """Start the pipeline config builder server and open the browser."""
    config_path = str(pathlib.Path(config_path).resolve())
    palette = _get_stage_palette()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # silence default access log
            pass

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                html_path = _STATIC_DIR / "index.html"
                body = html_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/palette":
                body = json.dumps(palette).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/current":
                current = _load_existing_pipeline_yaml(config_path)
                body = json.dumps({"yaml": current}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == "/save":
                MAX_BODY = 1 * 1024 * 1024
                try:
                    raw_len = int(self.headers.get("Content-Length", 0))
                except (TypeError, ValueError):
                    raw_len = 0
                if raw_len > MAX_BODY:
                    self.send_response(413)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": False, "error": "Payload too large (max 1 MB)"}).encode())
                    # Drain connection to avoid broken pipe
                    self.rfile.read(min(raw_len, MAX_BODY))
                    return
                body = self.rfile.read(raw_len)
                try:
                    data = json.loads(body)
                    _save_pipeline_yaml(config_path, data["yaml"])
                    resp = json.dumps({"ok": True}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(resp)
                except Exception as exc:
                    resp = json.dumps({"ok": False, "error": str(exc)}).encode()
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(resp)
            else:
                self.send_response(404)
                self.end_headers()

    server = HTTPServer(("127.0.0.1", 0), Handler)   # port=0 → OS assigns free port
    port = server.server_address[1]
    url = f"http://localhost:{port}"
    print(f"\n🧩 Pipeline Config Builder ready at {url}")
    print(f"   Editing: {pathlib.Path(config_path).parent / 'pipeline.yaml'}")
    print("   Press Ctrl+C to exit.\n")

    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n✅ Builder closed.")
