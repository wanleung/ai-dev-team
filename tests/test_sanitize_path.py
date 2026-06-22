"""Tests for path sanitization in EngineerAgent and QAEngineerAgent."""
from __future__ import annotations

from agents.engineer import EngineerAgent
from agents.qa_engineer import QAEngineerAgent


# ── _sanitize_path ──────────────────────────────────────────────────────────

class TestSanitizePath:
    """Shared tests for both EngineerAgent._sanitize_path and QAEngineerAgent._sanitize_path."""

    def _sanitize(self, path: str) -> str | None:
        """Test via EngineerAgent (both implementations are identical)."""
        return EngineerAgent._sanitize_path(path)

    def test_valid_relative_path(self):
        assert self._sanitize("src/main.py") == "src/main.py"

    def test_valid_nested_path(self):
        assert self._sanitize("app/models/user.py") == "app/models/user.py"

    def test_valid_test_path(self):
        assert self._sanitize("tests/test_main.py") == "tests/test_main.py"

    def test_valid_conftest(self):
        assert self._sanitize("conftest.py") == "conftest.py"

    def test_rejects_absolute_path(self):
        assert self._sanitize("/etc/passwd") is None

    def test_rejects_absolute_windows_path(self):
        assert self._sanitize("\\Windows\\System32") is None

    def test_rejects_dot_dot_traversal(self):
        assert self._sanitize("../../../etc/passwd") is None

    def test_rejects_dot_dot_in_middle(self):
        assert self._sanitize("src/../../../etc/passwd") is None

    def test_rejects_dot_dot_at_start(self):
        assert self._sanitize("../../sensitive.txt") is None

    def test_rejects_empty_string(self):
        assert self._sanitize("") is None

    def test_rejects_dot_only(self):
        assert self._sanitize(".") is None

    def test_collapses_double_slashes(self):
        assert self._sanitize("src//main.py") == "src/main.py"

    def test_collapses_dot_slash(self):
        assert self._sanitize("./src/main.py") == "src/main.py"

    def test_windows_dot_dot_rejected(self):
        assert self._sanitize("..\\..\\etc\\passwd") is None

    def test_valid_dockerfile(self):
        assert self._sanitize("Dockerfile") == "Dockerfile"

    def test_valid_deeply_nested(self):
        assert self._sanitize("a/b/c/d/e.py") == "a/b/c/d/e.py"


# ── _parse_files with sanitization ──────────────────────────────────────────

class TestParseFilesSanitization:
    """Verify _parse_files drops unsafe paths."""

    def test_safe_paths_parsed(self):
        response = (
            "### FILE: src/main.py\n"
            "```python\nprint('hello')\n```\n"
            "### FILE: tests/test_main.py\n"
            "```python\ndef test_main(): pass\n```\n"
        )
        files = EngineerAgent._parse_files(response)
        assert "src/main.py" in files
        assert "tests/test_main.py" in files

    def test_unsafe_path_dropped(self):
        response = (
            "### FILE: src/main.py\n"
            "```python\nprint('hello')\n```\n"
            "### FILE: ../../../etc/passwd\n"
            "```python\nmalicious\n```\n"
        )
        files = EngineerAgent._parse_files(response)
        assert "src/main.py" in files
        assert "../../../etc/passwd" not in files
        assert "/etc/passwd" not in files

    def test_absolute_path_falls_back_to_main(self):
        """Absolute paths are dropped; if no safe paths remain, falls back to main.py."""
        response = (
            "### FILE: /tmp/evil.py\n"
            "```python\nevil code\n```\n"
        )
        files = EngineerAgent._parse_files(response)
        # Unsafe path dropped → no files parsed → fallback to main.py
        assert "/tmp/evil.py" not in files
        assert "main.py" in files
        response = (
            "### FILE: tests/test_ok.py\n"
            "```python\ndef test_ok(): pass\n```\n"
            "### FILE: ../../evil.py\n"
            "```python\ndef test_evil(): pass\n```\n"
        )
        files = QAEngineerAgent._parse_test_files(response)
        # Only the safe path should survive (after _normalize_test_paths)
        assert any("test_ok.py" in k for k in files)
        assert not any("evil" in k for k in files)


# ── _parse_files basic parsing ──────────────────────────────────────────────

class TestParseFilesBasic:
    """Verify basic FILE: parsing still works correctly."""

    def test_single_file(self):
        response = "### FILE: main.py\n```\nprint('hi')\n```"
        files = EngineerAgent._parse_files(response)
        assert files == {"main.py": "print('hi')"}

    def test_fallback_to_main_py(self):
        """When no FILE: markers found, entire response goes to main.py."""
        response = "print('hello world')"
        files = EngineerAgent._parse_files(response)
        assert files == {"main.py": "print('hello world')"}

    def test_empty_response(self):
        files = EngineerAgent._parse_files("")
        assert files == {}
