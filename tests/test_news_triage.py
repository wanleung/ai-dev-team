"""Tests for editorial triage — verdict parsing and PipelineResult fields."""


# ── PipelineResult field tests ───────────────────────────────────────────────

def test_pipeline_result_has_triage_fields():
    """PipelineResult must expose editorial_verdict, editorial_notes, triage_scope."""
    from orchestrator import PipelineResult
    r = PipelineResult(requirement="test")
    assert r.editorial_verdict == ""
    assert r.editorial_notes == ""
    assert r.triage_scope == ""


def test_pipeline_result_triage_fields_serialise_publish():
    """PUBLISH verdict, notes, and scope round-trip through to_dict/from_dict."""
    from orchestrator import PipelineResult
    r = PipelineResult(requirement="test")
    r.editorial_verdict = "PUBLISH"
    r.editorial_notes = "Focus on the security implications"
    r.triage_scope = "AI, cybersecurity"
    d = r.to_dict()
    assert d["editorial_verdict"] == "PUBLISH"
    assert d["editorial_notes"] == "Focus on the security implications"
    assert d["triage_scope"] == "AI, cybersecurity"
    r2 = PipelineResult.from_dict(d)
    assert r2.editorial_verdict == "PUBLISH"
    assert r2.editorial_notes == "Focus on the security implications"
    assert r2.triage_scope == "AI, cybersecurity"


def test_pipeline_result_triage_fields_serialise_skip():
    """SKIP verdict round-trips through to_dict/from_dict."""
    from orchestrator import PipelineResult
    r = PipelineResult(requirement="test")
    r.editorial_verdict = "SKIP"
    r.editorial_notes = "Story is out of scope for HK tech audience"
    d = r.to_dict()
    r2 = PipelineResult.from_dict(d)
    assert r2.editorial_verdict == "SKIP"
    assert r2.editorial_notes == "Story is out of scope for HK tech audience"


def test_pipeline_result_triage_fields_missing_keys_fall_back_to_defaults():
    """from_dict must not crash on old checkpoints that lack the triage fields."""
    from orchestrator import PipelineResult
    old_data = {"requirement": "legacy"}  # no triage keys
    r = PipelineResult.from_dict(old_data)
    assert r.editorial_verdict == ""
    assert r.editorial_notes == ""
    assert r.triage_scope == ""

# ── _parse_triage_verdict() tests ────────────────────────────────────────────
# _parse_triage_verdict is a @staticmethod — call via Orchestrator directly.

def test_parse_verdict_publish():
    """Standard PUBLISH output returns verdict=PUBLISH and notes."""
    from orchestrator import Orchestrator
    text = (
        "This story is highly relevant to our HK tech audience.\n"
        "VERDICT: PUBLISH\n"
        "EDITORIAL_NOTES: Focus on the open-source tooling implications for local DevOps teams."
    )
    result = Orchestrator._parse_triage_verdict(text)
    assert result["verdict"] == "PUBLISH"
    assert "open-source" in result["notes"]


def test_parse_verdict_skip():
    """Standard SKIP output returns verdict=SKIP and notes."""
    from orchestrator import Orchestrator
    text = (
        "This story is off-topic for our readership.\n"
        "VERDICT: SKIP\n"
        "EDITORIAL_NOTES: Story covers US sports industry with no tech angle."
    )
    result = Orchestrator._parse_triage_verdict(text)
    assert result["verdict"] == "SKIP"
    assert "sports" in result["notes"]


def test_parse_verdict_case_insensitive():
    """Lowercase 'publish' is accepted (fail-open)."""
    from orchestrator import Orchestrator
    text = "verdict: publish\nEDITORIAL_NOTES: Good story."
    result = Orchestrator._parse_triage_verdict(text)
    assert result["verdict"] == "PUBLISH"


def test_parse_verdict_malformed_no_verdict_line():
    """Missing VERDICT line → fail-open: PUBLISH with empty notes."""
    from orchestrator import Orchestrator
    text = "The discussion was inconclusive. No clear consensus."
    result = Orchestrator._parse_triage_verdict(text)
    assert result["verdict"] == "PUBLISH"
    assert result["notes"] == ""


def test_parse_verdict_fail_open_on_exception():
    """Non-string input → fail-open: PUBLISH (never raises)."""
    from orchestrator import Orchestrator
    result = Orchestrator._parse_triage_verdict(None)  # type: ignore[arg-type]
    assert result["verdict"] == "PUBLISH"
    assert result["notes"] == ""


def test_parse_verdict_multiline_notes():
    """EDITORIAL_NOTES spanning multiple lines are captured fully."""
    from orchestrator import Orchestrator
    text = (
        "VERDICT: PUBLISH\n"
        "EDITORIAL_NOTES: Focus on the security implications.\n"
        "Also highlight the local regulatory context."
    )
    result = Orchestrator._parse_triage_verdict(text)
    assert result["verdict"] == "PUBLISH"
    assert "security" in result["notes"]
    assert "regulatory" in result["notes"]

# ── Discussion YAML validity test ────────────────────────────────────────────

def test_news_triage_yaml_valid():
    """discussions/news-triage.yaml must load cleanly and reference existing role files."""
    from pathlib import Path
    import yaml

    yaml_path = Path("discussions/news-triage.yaml")
    assert yaml_path.is_file(), "discussions/news-triage.yaml not found"
    data = yaml.safe_load(yaml_path.read_text())

    assert "participants" in data
    assert len(data["participants"]) >= 2
    assert "context_fields" in data
    assert "issue_body" in data["context_fields"]
    assert "triage_scope" in data["context_fields"]

    for participant in data["participants"]:
        persona_file = participant.get("persona_file", "")
        assert persona_file, f"participant {participant} missing persona_file"
        assert Path(persona_file).is_file(), f"Role file not found: {persona_file}"
