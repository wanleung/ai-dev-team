"""Tests for Milestone 2: Detection — validation_gate stage."""
import importlib.util
import pytest
from pathlib import Path
from dataclasses import fields

_ruff_available = importlib.util.find_spec("ruff") is not None


def test_pipeline_result_has_validation_attempts():
    from orchestrator import PipelineResult
    field_names = {f.name for f in fields(PipelineResult)}
    assert "validation_attempts" in field_names


def test_pipeline_result_has_validation_errors():
    from orchestrator import PipelineResult
    field_names = {f.name for f in fields(PipelineResult)}
    assert "validation_errors" in field_names


def test_pipeline_result_has_pr_draft():
    from orchestrator import PipelineResult
    field_names = {f.name for f in fields(PipelineResult)}
    assert "pr_draft" in field_names


def test_pipeline_result_validation_defaults():
    from orchestrator import PipelineResult
    r = PipelineResult()
    assert r.validation_attempts == 0
    assert r.validation_errors == []
    assert r.pr_draft is False


def test_validation_gate_passes_clean_python():
    """Gate should pass when all .py files have valid syntax."""
    from orchestrator import Orchestrator, PipelineResult
    orch = Orchestrator.__new__(Orchestrator)

    result = PipelineResult()
    result.all_files = {
        "mymodule/hello.py": "def hello():\n    return 'world'\n"
    }
    orch._stage_validation_gate(result)

    assert result.validation_errors == []
    assert result.pr_draft is False


def test_validation_gate_catches_syntax_error():
    """Gate catches SyntaxError in generated .py files."""
    from orchestrator import Orchestrator, PipelineResult
    orch = Orchestrator.__new__(Orchestrator)

    result = PipelineResult()
    result.all_files = {
        "mymodule/broken.py": "def hello(\n    pass\n"
    }
    orch._stage_validation_gate(result)

    assert len(result.validation_errors) > 0
    assert any("syntax" in e.lower() or "SyntaxError" in e for e in result.validation_errors)


@pytest.mark.skipif(not _ruff_available, reason="ruff not installed")
def test_validation_gate_catches_undefined_name():
    """Gate catches F821 undefined name via ruff."""
    from orchestrator import Orchestrator, PipelineResult
    orch = Orchestrator.__new__(Orchestrator)

    result = PipelineResult()
    result.all_files = {
        "mymodule/bad.py": "def foo():\n    return undefined_variable\n"
    }
    orch._stage_validation_gate(result)

    assert len(result.validation_errors) > 0


def test_validation_gate_marks_draft_after_two_retries():
    """After validation_attempts >= 2, gate marks pr_draft=True."""
    from orchestrator import Orchestrator, PipelineResult
    orch = Orchestrator.__new__(Orchestrator)

    result = PipelineResult()
    result.validation_attempts = 2
    result.all_files = {
        "mymodule/broken.py": "def hello(\n    pass\n"
    }
    orch._stage_validation_gate(result)

    assert result.pr_draft is True


def test_validation_gate_registered_in_stage_registry():
    """validation_gate must be registered in _make_stage_registry."""
    src = Path("orchestrator.py").read_text()
    assert '"validation_gate"' in src or "'validation_gate'" in src


def test_ai_feature_pipeline_has_validation_gate():
    import yaml
    pipeline = yaml.safe_load(Path("pipelines/ai-feature.yaml").read_text())
    stages = pipeline["stages"]
    assert "validation_gate" in stages


def test_ai_fix_pipeline_has_validation_gate():
    import yaml
    pipeline = yaml.safe_load(Path("pipelines/ai-fix.yaml").read_text())
    stages = pipeline["stages"]
    assert "validation_gate" in stages
