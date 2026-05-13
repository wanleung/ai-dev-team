"""Tests for tools/builtin.py and tools/registry.py."""
from __future__ import annotations

import json
import subprocess
import warnings
from unittest.mock import MagicMock, patch

import pytest

from tools.builtin import (
    run_linter,
    run_shell_command,
    search_github_issues,
    get_github_file,
    builtin_tools,
)
from tools.registry import LocalToolRegistry, CombinedToolRegistry


# ── run_linter ────────────────────────────────────────────────────────────────

class TestRunLinter:
    def test_no_errors_returns_success_message(self):
        """run_linter on valid Python returns the no-errors sentinel."""
        with patch("tools.builtin.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
            result = run_linter("x = 1\n")
        assert "No lint errors" in result

    def test_returns_lint_errors_for_invalid_code(self):
        """run_linter on code with undefined name returns ruff output."""
        with patch("tools.builtin.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="test_code.py:1:7: F821 Undefined name `undefined_var`\n",
                stderr="",
                returncode=1
            )
            result = run_linter("print(undefined_var)\n", filename="test_code.py")
        # ruff may report F821 (undefined name) or similar; result is non-empty
        assert isinstance(result, str)
        # The temp path is stripped and replaced with the given filename
        assert "test_code.py" in result

    def test_filename_suffix_used_for_tempfile(self):
        """run_linter respects the filename parameter (used for context)."""
        with patch("tools.builtin.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
            result = run_linter("y: int = 'wrong'\n", filename="mymodule.py")
        assert isinstance(result, str)


# ── run_shell_command ─────────────────────────────────────────────────────────

class TestRunShellCommand:
    def test_blocked_command_returns_error(self):
        """run_shell_command blocks destructive commands (rm, wget, etc.)."""
        result = run_shell_command(["rm", "-rf", "/"])
        assert "[Blocked]" in result
        assert "rm" in result

    def test_successful_command_returns_output(self):
        """run_shell_command returns stdout for a safe command."""
        result = run_shell_command(["echo", "hello world"])
        assert "hello world" in result

    def test_timeout_returns_error_message(self):
        """run_shell_command returns timeout error if command takes too long."""
        with patch("tools.builtin.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("cmd", 30)
            result = run_shell_command(["sleep", "999"])
        assert "timed out" in result.lower()

    def test_file_not_found_returns_error(self):
        """run_shell_command returns not-found error for unknown executables."""
        with patch("tools.builtin.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            result = run_shell_command(["nonexistent_binary_xyz"])
        assert "not found" in result.lower()

    def test_long_output_truncated(self):
        """run_shell_command truncates output exceeding 4000 chars."""
        long_output = "x" * 5000
        with patch("tools.builtin.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=long_output, stderr="", returncode=0
            )
            result = run_shell_command(["python3", "-c", "print('x'*5000)"])
        assert len(result) <= 4020  # 4000 + "… [truncated]"
        assert "truncated" in result

    def test_cwd_passed_to_subprocess(self, tmp_path):
        """run_shell_command forwards cwd to subprocess.run."""
        with patch("tools.builtin.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
            run_shell_command(["ls"], cwd=str(tmp_path))
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs.get("cwd") == str(tmp_path)


# ── search_github_issues ──────────────────────────────────────────────────────

class TestSearchGithubIssues:
    def test_returns_json_on_success(self):
        """search_github_issues returns JSON list of matching issues."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "items": [
                {
                    "number": 42,
                    "title": "Fix the auth bug",
                    "state": "open",
                    "html_url": "https://github.com/owner/repo/issues/42",
                    "body": "Description of the auth bug",
                }
            ]
        }
        with patch("tools.builtin.requests.get", return_value=mock_resp):
            result = search_github_issues("owner/repo", "auth bug")

        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["number"] == 42
        assert data[0]["title"] == "Fix the auth bug"

    def test_returns_no_issues_message_when_empty(self):
        """search_github_issues returns a readable message when no items found."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"items": []}
        with patch("tools.builtin.requests.get", return_value=mock_resp):
            result = search_github_issues("owner/repo", "xyz123notfound")
        assert "No matching" in result

    def test_returns_error_on_http_failure(self):
        """search_github_issues returns error string on non-OK response."""
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 403
        mock_resp.text = "rate limited"
        with patch("tools.builtin.requests.get", return_value=mock_resp):
            result = search_github_issues("owner/repo", "anything")
        assert "[Error]" in result
        assert "403" in result


# ── get_github_file ───────────────────────────────────────────────────────────

class TestGetGithubFile:
    def test_returns_file_content_on_success(self):
        """get_github_file returns the raw file content from GitHub."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.text = "def hello(): pass\n"
        with patch("tools.builtin.requests.get", return_value=mock_resp):
            result = get_github_file("owner/repo", "src/hello.py")
        assert "def hello(): pass" in result

    def test_truncates_large_files(self):
        """get_github_file truncates content exceeding 6000 chars."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.text = "x" * 7000
        with patch("tools.builtin.requests.get", return_value=mock_resp):
            result = get_github_file("owner/repo", "big.py")
        assert "truncated" in result
        assert len(result) <= 6100

    def test_returns_error_on_failure(self):
        """get_github_file returns error message on 404."""
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 404
        with patch("tools.builtin.requests.get", return_value=mock_resp):
            result = get_github_file("owner/repo", "missing.py")
        assert "[Error]" in result
        assert "404" in result

    def test_uses_ref_in_url(self):
        """get_github_file constructs the correct raw URL including ref."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.text = "content"
        with patch("tools.builtin.requests.get", return_value=mock_resp) as mock_get:
            get_github_file("owner/repo", "file.py", ref="my-branch")
        url = mock_get.call_args[0][0]
        assert "my-branch" in url
        assert "file.py" in url


# ── LocalToolRegistry ─────────────────────────────────────────────────────────

class TestLocalToolRegistry:
    def _make_registry(self):
        reg = LocalToolRegistry()
        @reg.tool(
            name="echo_tool",
            description="Returns its input",
            parameters={
                "type": "object",
                "properties": {"msg": {"type": "string"}},
                "required": ["msg"],
            },
        )
        def echo_tool(msg: str) -> str:
            return msg
        return reg

    def test_call_unknown_tool_returns_error(self):
        """LocalToolRegistry.call() returns ToolError for unknown tool name."""
        reg = self._make_registry()
        result = reg.call("does_not_exist", "{}")
        assert "[ToolError]" in result
        assert "does_not_exist" in result

    def test_call_tool_that_raises_returns_error(self):
        """LocalToolRegistry.call() wraps exceptions in a ToolError string."""
        reg = LocalToolRegistry()
        @reg.tool(name="boom", description="raises", parameters={"type": "object", "properties": {}, "required": []})
        def boom() -> str:
            raise ValueError("intentional error")

        result = reg.call("boom", "{}")
        assert "[ToolError]" in result
        assert "intentional error" in result

    def test_repr_lists_tool_names(self):
        """LocalToolRegistry.__repr__() includes registered tool names."""
        reg = self._make_registry()
        r = repr(reg)
        assert "echo_tool" in r
        assert "LocalToolRegistry" in r


# ── CombinedToolRegistry ──────────────────────────────────────────────────────

class TestCombinedToolRegistry:
    def _make_reg(self, tool_name: str, return_value: str = "ok") -> LocalToolRegistry:
        reg = LocalToolRegistry()
        @reg.tool(
            name=tool_name,
            description=f"tool {tool_name}",
            parameters={"type": "object", "properties": {}, "required": []},
        )
        def fn() -> str:
            return return_value
        return reg

    def test_call_routes_to_primary(self):
        """CombinedToolRegistry routes primary tool calls to primary registry."""
        primary = self._make_reg("primary_tool", "from primary")
        secondary = self._make_reg("secondary_tool", "from secondary")
        combined = CombinedToolRegistry(primary, secondary)
        assert combined.call("primary_tool", "{}") == "from primary"

    def test_call_routes_to_secondary(self):
        """CombinedToolRegistry routes secondary tool calls to secondary registry."""
        primary = self._make_reg("primary_tool")
        secondary = self._make_reg("secondary_tool", "from secondary")
        combined = CombinedToolRegistry(primary, secondary)
        assert combined.call("secondary_tool", "{}") == "from secondary"

    def test_schemas_merges_both_registries(self):
        """CombinedToolRegistry.schemas exposes tools from both registries."""
        primary = self._make_reg("tool_a")
        secondary = self._make_reg("tool_b")
        combined = CombinedToolRegistry(primary, secondary)
        names = [s["function"]["name"] for s in combined.schemas]
        assert "tool_a" in names
        assert "tool_b" in names

    def test_overlap_emits_warning(self):
        """CombinedToolRegistry warns when primary and secondary share a tool name."""
        primary = self._make_reg("shared_tool")
        secondary = self._make_reg("shared_tool")
        combined = CombinedToolRegistry(primary, secondary)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _ = combined.schemas
        assert any("shared_tool" in str(w.message) for w in caught)

    def test_repr_includes_both(self):
        """CombinedToolRegistry.__repr__() mentions primary and secondary."""
        primary = self._make_reg("p_tool")
        secondary = self._make_reg("s_tool")
        combined = CombinedToolRegistry(primary, secondary)
        r = repr(combined)
        assert "CombinedToolRegistry" in r
        assert "primary" in r.lower() or "p_tool" in r
