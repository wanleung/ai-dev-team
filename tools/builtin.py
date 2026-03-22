"""
Built-in tools available to any agent.

Each tool is registered on a module-level LocalToolRegistry instance.
Import `builtin_tools` and pass it to agent.call_with_tools().

Or create your own LocalToolRegistry and register only what you need.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

from .registry import LocalToolRegistry

builtin_tools = LocalToolRegistry()


# ── Code quality tools ───────────────────────────────────────────────────────

@builtin_tools.tool(
    name="run_linter",
    description=(
        "Run the ruff linter on Python source code and return any lint errors. "
        "Use this to check code quality before writing a review."
    ),
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Full Python source code to lint",
            },
            "filename": {
                "type": "string",
                "description": "Filename for context (e.g. 'src/main.py')",
            },
        },
        "required": ["code"],
    },
)
def run_linter(code: str, filename: str = "code.py") -> str:
    """Run ruff on the given code and return the output."""
    suffix = Path(filename).suffix or ".py"
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
        f.write(code)
        tmp = f.name
    try:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", tmp, "--output-format=text"],
            capture_output=True,
            text=True,
        )
        output = result.stdout + result.stderr
        # Strip the temp path so output is readable
        output = output.replace(tmp, filename)
        return output.strip() or "✅ No lint errors found."
    finally:
        os.unlink(tmp)


@builtin_tools.tool(
    name="run_shell_command",
    description=(
        "Run a safe shell command and return stdout + stderr. "
        "Use for running tests, checking syntax, or inspecting files. "
        "Do NOT use for destructive operations."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Command as a list of strings, e.g. ['pytest', 'tests/', '-v']",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory (optional)",
            },
        },
        "required": ["command"],
    },
)
def run_shell_command(command: list[str], cwd: str | None = None) -> str:
    """Run a command and return combined stdout/stderr (max 4000 chars)."""
    # Safety: block obviously destructive commands
    blocked = {"rm", "rmdir", "dd", "mkfs", "shutdown", "reboot", "curl", "wget"}
    if command and command[0].lower() in blocked:
        return f"[Blocked] Command '{command[0]}' is not allowed."
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
        )
        output = (result.stdout + result.stderr).strip()
        if len(output) > 4000:
            output = output[:4000] + "\n… [truncated]"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "[Error] Command timed out after 30s."
    except FileNotFoundError:
        return f"[Error] Command not found: {command[0]!r}"


# ── GitHub tools ─────────────────────────────────────────────────────────────

def _gh_headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


@builtin_tools.tool(
    name="search_github_issues",
    description=(
        "Search GitHub issues in a repository. Returns a list of matching issues "
        "with title, number, state, and body snippet. Useful for finding duplicate "
        "features, related bugs, or existing acceptance criteria."
    ),
    parameters={
        "type": "object",
        "properties": {
            "repo": {
                "type": "string",
                "description": "Repository in 'owner/repo' format",
            },
            "query": {
                "type": "string",
                "description": "Search keywords",
            },
            "state": {
                "type": "string",
                "enum": ["open", "closed", "all"],
                "description": "Issue state filter (default: open)",
            },
        },
        "required": ["repo", "query"],
    },
)
def search_github_issues(repo: str, query: str, state: str = "open") -> str:
    """Search GitHub issues and return a JSON summary."""
    url = "https://api.github.com/search/issues"
    params = {"q": f"{query} repo:{repo} is:issue state:{state}", "per_page": 5}
    resp = requests.get(url, headers=_gh_headers(), params=params, timeout=10)
    if not resp.ok:
        return f"[Error] GitHub search failed: {resp.status_code} {resp.text[:200]}"
    items = resp.json().get("items", [])
    if not items:
        return "No matching issues found."
    results = [
        {
            "number": i["number"],
            "title": i["title"],
            "state": i["state"],
            "url": i["html_url"],
            "body_snippet": (i.get("body") or "")[:300],
        }
        for i in items
    ]
    return json.dumps(results, indent=2)


@builtin_tools.tool(
    name="get_github_file",
    description=(
        "Read the content of a file from a GitHub repository. "
        "Useful for checking existing code before implementing new modules."
    ),
    parameters={
        "type": "object",
        "properties": {
            "repo": {
                "type": "string",
                "description": "Repository in 'owner/repo' format",
            },
            "path": {
                "type": "string",
                "description": "File path within the repository",
            },
            "ref": {
                "type": "string",
                "description": "Branch, tag, or commit SHA (default: main)",
            },
        },
        "required": ["repo", "path"],
    },
)
def get_github_file(repo: str, path: str, ref: str = "main") -> str:
    """Fetch raw file content from GitHub."""
    url = f"https://raw.githubusercontent.com/{repo}/{ref}/{path}"
    resp = requests.get(url, headers=_gh_headers(), timeout=10)
    if not resp.ok:
        return f"[Error] Could not fetch {path}: {resp.status_code}"
    content = resp.text
    if len(content) > 6000:
        content = content[:6000] + "\n… [truncated]"
    return content
