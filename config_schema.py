"""Pydantic v2 schema for config.yaml and repos.yaml.

Usage:
    from config_schema import load_config, AppConfig, RepoWatcherEntry
    cfg = load_config("config.yaml")   # raises ValidationError on bad config
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator


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


# ── reliability models ────────────────────────────────────────────────────────

class CircuitBreakerScopeConfig(BaseModel):
    """Configuration for a single circuit-breaker scope (agent, repo, or backend)."""

    model_config = {"extra": "forbid"}

    threshold: int = 5
    recovery_timeout_s: int = 60


class CircuitBreakerConfig(BaseModel):
    """Top-level circuit-breaker configuration with per-scope overrides."""

    model_config = {"extra": "forbid"}

    enabled: bool = False
    per_agent: CircuitBreakerScopeConfig = Field(
        default_factory=CircuitBreakerScopeConfig
    )
    per_repo: CircuitBreakerScopeConfig = Field(
        default_factory=lambda: CircuitBreakerScopeConfig(threshold=3, recovery_timeout_s=120)
    )
    per_backend: CircuitBreakerScopeConfig = Field(
        default_factory=lambda: CircuitBreakerScopeConfig(threshold=10, recovery_timeout_s=300)
    )


class DLQFileConfig(BaseModel):
    """Configuration for the file-backed dead-letter queue."""

    model_config = {"extra": "forbid"}

    path: str = "workspace/dlq"


class DLQRedisConfig(BaseModel):
    """Configuration for the Redis-backed dead-letter queue."""

    model_config = {"extra": "forbid"}

    url: str = "redis://localhost:6379"
    key: str = "ai-swhouse:dlq"
    ttl_s: Optional[int] = 604800


class DLQSQSConfig(BaseModel):
    """Configuration for the AWS SQS-backed dead-letter queue."""

    model_config = {"extra": "forbid"}

    queue_url: str
    region: str = "eu-west-1"


class DLQConfig(BaseModel):
    """Dead-letter queue configuration — stores failed pipeline jobs for retry."""

    model_config = {"extra": "forbid"}

    enabled: bool = False
    backend: Literal["file", "redis", "sqs"] = "file"
    max_attempts: int = 3
    file: DLQFileConfig = Field(default_factory=DLQFileConfig)
    redis: Optional[DLQRedisConfig] = None
    sqs: Optional[DLQSQSConfig] = None

    @model_validator(mode="after")
    def _backend_config_present(self) -> "DLQConfig":
        if self.backend == "redis" and self.redis is None:
            raise ValueError("backend='redis' requires a 'redis:' config block")
        if self.backend == "sqs" and self.sqs is None:
            raise ValueError("backend='sqs' requires a 'sqs:' config block")
        return self


class DegradationConfig(BaseModel):
    """Graceful-degradation policy — controls how the pipeline behaves under pressure."""

    model_config = {"extra": "forbid"}

    enabled: bool = False
    reduce_engineers: bool = True
    fallback_model: bool = True
    skip_optional_stages: bool = True
    optional_stages: List[str] = Field(
        default_factory=lambda: ["deploy_test", "documentation"]
    )


class ReliabilityConfig(BaseModel):
    """Container for all reliability sub-configurations."""

    model_config = {"extra": "forbid"}

    circuit_breaker: CircuitBreakerConfig = Field(
        default_factory=CircuitBreakerConfig
    )
    dead_letter: DLQConfig = Field(default_factory=DLQConfig)
    degradation: DegradationConfig = Field(default_factory=DegradationConfig)


class TriageConfig(BaseModel):
    model_config = {"extra": "allow"}

    scope: str = (
        "Focus areas: AI, software development tools, cybersecurity, Hong Kong tech scene, "
        "enterprise software, open-source.\n"
        "Audience: HK Cantonese-speaking tech professionals."
    )


class PressConfig(BaseModel):
    model_config = {"extra": "allow"}

    triage: TriageConfig = Field(default_factory=TriageConfig)


# ── intake triage config ──────────────────────────────────────────────────────

class IntakeTriggerConfig(BaseModel):
    model_config = {"extra": "allow"}

    min_count: Optional[int] = 5
    max_age_hours: Optional[float] = 6.0
    schedule: Optional[str] = None


class IntakeBatchConfig(BaseModel):
    model_config = {"extra": "allow"}

    max_size: int = 10
    body_preview_chars: int = 300


class IntakeVerdictConfig(BaseModel):
    model_config = {"extra": "allow"}

    mode: str = "binary"
    score_threshold: Optional[int] = None


class IntakeTriageConfig(BaseModel):
    model_config = {"extra": "allow"}

    enabled: bool = False
    tracker: str = "github"
    scope: str = "Tech news relevant to HK Cantonese-speaking professionals."
    labels: Dict[str, str] = Field(
        default_factory=lambda: {
            "pending":  "triage-pending",
            "approved": "triage-approved",
            "skipped":  "triage-skipped",
            "trigger":  "press",
        }
    )
    trigger: IntakeTriggerConfig = Field(default_factory=IntakeTriggerConfig)
    batch: IntakeBatchConfig = Field(default_factory=IntakeBatchConfig)
    verdict: IntakeVerdictConfig = Field(default_factory=IntakeVerdictConfig)
    discussion: Dict[str, Any] = Field(
        default_factory=lambda: {"preset": "discussions/intake-triage.yaml"}
    )


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
    reliability: Optional[ReliabilityConfig] = None
    rss_watcher: Optional[Dict[str, Any]] = None
    press: Optional[PressConfig] = None
    intake_triage: IntakeTriageConfig = Field(default_factory=IntakeTriageConfig)


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
    llm: Optional[LLMConfig] = None


# ── loaders ──────────────────────────────────────────────────────────────────

def load_config(path: str) -> AppConfig:
    """Load and validate config.yaml. Raises pydantic.ValidationError on schema errors."""
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return AppConfig.model_validate(raw)


def load_repo_entry(data: dict) -> RepoWatcherEntry:
    """Validate a single repos.yaml watcher entry."""
    return RepoWatcherEntry.model_validate(data)
