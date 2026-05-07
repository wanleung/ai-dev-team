"""Pydantic v2 schema for config.yaml and repos.yaml.

Usage:
    from config_schema import load_config, AppConfig, RepoWatcherEntry
    cfg = load_config("config.yaml")   # raises ValidationError on bad config
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


# ── config.yaml models ──────────────────────────────────────────────────────

class LLMConfig(BaseModel):
    model_config = {"extra": "allow"}   # allow unknown agent override keys

    model: str = "gpt-4.1"
    fallback: Optional[List[str]] = None
    overrides: Optional[Dict[str, Any]] = None


class GithubConfig(BaseModel):
    model_config = {"extra": "allow"}

    repo: str = ""
    token: Optional[str] = None


class PipelineChainingConfig(BaseModel):
    model_config = {"extra": "allow"}

    on_test_failure: Optional[str] = None
    on_review_issues: Optional[str] = None


class PipelineConfig(BaseModel):
    model_config = {"extra": "allow"}

    num_engineers: int = 2
    max_revisions: int = 3
    chaining: Optional[PipelineChainingConfig] = None
    mode: str = "standard"


class OllamaConfig(BaseModel):
    model_config = {"extra": "allow"}

    url: str = "http://localhost:11434"
    api_key: Optional[str] = None
    think: bool = False
    preserve_thinking: bool = False
    stream: bool = True


class AppConfig(BaseModel):
    model_config = {"extra": "forbid"}   # unknown top-level keys are errors

    llm: LLMConfig = Field(default_factory=LLMConfig)
    github: Optional[GithubConfig] = None
    pipeline: Optional[PipelineConfig] = None
    ollama: Optional[OllamaConfig] = None
    team: Optional[Dict[str, Any]] = None
    mcp: Optional[Dict[str, Any]] = None
    repo_context: Optional[Dict[str, Any]] = None
    memory: Optional[Dict[str, Any]] = None
    skills: Optional[Dict[str, Any]] = None
    token_tracking: Optional[Dict[str, Any]] = None
    cost_tracking: Optional[Dict[str, Any]] = None
    framework_docs: Optional[Dict[str, Any]] = None
    rag: Optional[Dict[str, Any]] = None
    project: Optional[Dict[str, Any]] = None


# ── repos.yaml models ────────────────────────────────────────────────────────

class RepoWatcherEntry(BaseModel):
    model_config = {"extra": "allow"}   # allow custom keys for future expansion

    tracker_repo: str
    default_target: Optional[str] = None
    parallel_issues: int = 1
    labels: Dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    senior_model: Optional[str] = None
    conflict_resolver_model: Optional[str] = None


# ── loaders ──────────────────────────────────────────────────────────────────

def load_config(path: str) -> AppConfig:
    """Load and validate config.yaml. Raises pydantic.ValidationError on schema errors."""
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return AppConfig.model_validate(raw)


def load_repo_entry(data: dict) -> RepoWatcherEntry:
    """Validate a single repos.yaml watcher entry."""
    return RepoWatcherEntry.model_validate(data)
