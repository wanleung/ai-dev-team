"""Tests for main.py CLI flags."""
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_list_pipelines_includes_builtins():
    """`python main.py --list-pipelines` lists ai-feature, ai-fix, ai-docs."""
    result = subprocess.run(
        [sys.executable, "main.py", "--list-pipelines"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "ai-feature" in result.stdout
    assert "ai-fix" in result.stdout
    assert "ai-docs" in result.stdout


def test_pipeline_flag_parses():
    """`--pipeline ai-fix` is a valid argument (will fail elsewhere — we just check parsing)."""
    from main import _build_arg_parser
    parser = _build_arg_parser()
    args = parser.parse_args(["something", "--pipeline", "ai-fix"])
    assert args.pipeline == "ai-fix"
