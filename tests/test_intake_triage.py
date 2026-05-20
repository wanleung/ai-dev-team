"""Tests for intake triage config schema, tracker adapter, verdict parser, and main script."""
from __future__ import annotations
import pytest
from config_schema import AppConfig, IntakeTriageConfig, load_config
import yaml, tempfile, os


# ── Task 1: Config schema ──────────────────────────────────────────────────

def test_intake_triage_config_defaults():
    cfg = IntakeTriageConfig()
    assert cfg.enabled is False
    assert cfg.tracker == "github"
    assert cfg.labels["pending"] == "triage-pending"
    assert cfg.labels["approved"] == "triage-approved"
    assert cfg.labels["skipped"] == "triage-skipped"
    assert cfg.labels["trigger"] == "press"
    assert cfg.trigger.min_count == 5
    assert cfg.trigger.max_age_hours == 6
    assert cfg.trigger.schedule is None
    assert cfg.batch.max_size == 10
    assert cfg.batch.body_preview_chars == 300
    assert cfg.verdict.mode == "binary"
    assert cfg.verdict.score_threshold is None


def test_app_config_accepts_intake_triage():
    raw = {"llm": {"model": "gpt-4.1"}, "intake_triage": {"enabled": True, "trigger": {"min_count": 3}}}
    cfg = AppConfig(**raw)
    assert cfg.intake_triage.enabled is True
    assert cfg.intake_triage.trigger.min_count == 3


def test_app_config_intake_triage_disabled_by_default():
    cfg = AppConfig(**{"llm": {"model": "gpt-4.1"}})
    assert cfg.intake_triage is not None
    assert cfg.intake_triage.enabled is False


def test_intake_triage_config_from_yaml():
    content = """
llm:
  model: gpt-4.1
intake_triage:
  enabled: true
  labels:
    pending: triage-pending
    approved: triage-approved
    skipped: triage-skipped
    trigger: ai-press
  trigger:
    min_count: 3
    max_age_hours: 12
    schedule: "0 8 * * *"
  batch:
    max_size: 5
    body_preview_chars: 200
  verdict:
    mode: binary
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(content)
        f.flush()
        cfg = load_config(f.name)
    os.unlink(f.name)
    assert cfg.intake_triage.enabled is True
    assert cfg.intake_triage.labels["trigger"] == "ai-press"
    assert cfg.intake_triage.trigger.min_count == 3
    assert cfg.intake_triage.batch.max_size == 5
