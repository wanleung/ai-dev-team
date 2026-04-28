"""
Orchestrator: runs the full PM → Architect → Engineer×N → Reviewer → QA pipeline.
Manages artifact passing, logging, and optional GitHub integration.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from agents import (
    ArchitectAgent,
    ArchitectReviewerAgent,
    CodeReviewerAgent,
    DeploymentTesterAgent,
    EngineerAgent,
    PMReviewerAgent,
    ProductManagerAgent,
    QAEngineerAgent,
    QAPlannerAgent,
)
from agents.junior_engineer import JuniorEngineerAgent
from agents.senior_engineer import SeniorEngineerAgent
from agents.tier_reviewer import TierReviewerAgent
from agents.tier_utils import apply_tier_overrides
from agents.summariser import SummaryAgent
from agents.memory_bank_updater import MemoryBankUpdaterAgent
from agents.refactor_agent import RefactorAgent
from agents.memory_consolidator import MemoryConsolidatorAgent
from framework_docs import FrameworkDocsLoader
from github_client import GitHubClient, parse_target_repo
from repo_context import RepoContext, RepoContextLoader, RepoAutoIndexer
from memory_store import MemoryStore
from skills_loader import SkillContext, SkillLoader
from test_fix_loop import TestFixLoopMixin
from tools import builtin_tools, CombinedToolRegistry, MCPToolRegistry

console = Console()


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict.

    Nested dicts are merged at the leaf level; scalars are overwritten.
    Neither input dict is mutated.
    """
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _parse_explicit_skills(text: str) -> list[str]:
    """Parse 'skills: name1, name2' directive from issue body."""
    m = re.search(r"^skills\s*:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    if not m:
        return []
    return [s.strip() for s in m.group(1).split(",") if s.strip()]


class ClarificationNeeded(Exception):
    """Raised by PM or Architect agents when requirements are ambiguous.

    The orchestrator catches this, posts a GitHub comment with the questions,
    saves a checkpoint, and pauses the pipeline (agent-waiting label).
    """

    def __init__(self, questions: list[str]) -> None:
        self.questions = questions
        super().__init__(f"Clarification needed: {len(questions)} question(s)")


@dataclass
class PipelineResult:
    """Holds the full output of a completed pipeline run."""

    requirement: str = ""
    project_name: str = ""
    prd: str = ""
    prd_review: str = ""
    prd_verdict: str = ""
    design: str = ""
    design_review: str = ""
    design_verdict: str = ""
    modules: list[dict] = field(default_factory=list)
    all_files: dict[str, str] = field(default_factory=dict)
    junior_files: dict[str, str] = field(default_factory=dict)
    tier_classifications: list[dict] = field(default_factory=list)
    test_files: dict[str, str] = field(default_factory=dict)
    deploy_files: dict[str, str] = field(default_factory=dict)
    design_output: dict = field(default_factory=dict)  # raw architect output; used as module fallback
    review: str = ""
    verdict: str = ""
    qa_plan: str = ""          # structured test plan from QAPlanner
    qa_acceptance_criteria: list[str] = field(default_factory=list)
    test_plan: str = ""
    deploy_plan: str = ""
    test_results: str = ""
    deploy_test_results: str = ""
    tests_passed: Optional[bool] = None
    deploy_tests_passed: Optional[bool] = None
    issue_number: Optional[int] = None
    issue_url: Optional[str] = None
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    branch: Optional[str] = None
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)
    completed_stages: list[str] = field(default_factory=list)  # stages that finished OK
    # Q&A clarification fields
    pending_clarification: Optional[dict] = None  # set while waiting for human reply
    clarification_history: list[dict] = field(default_factory=list)  # completed Q&A rounds
    # Test-fix retry tracking
    test_retry_count: int = 0
    test_fix_history: list[str] = field(default_factory=list)
    deploy_retry_count: int = 0
    deploy_fix_history: list[str] = field(default_factory=list)
    # PRD/Design revision loop tracking
    prd_revision_count: int = 0
    design_revision_count: int = 0
    prd_reviewer_draft: str = ""      # reviewer's suggested PRD (for PM.run_revision)
    design_reviewer_draft: str = ""   # reviewer's suggested design (for Architect.run_revision)
    last_verdict: str = ""
    """Set by reviewer stages inside a loop block; checked against loop_until."""

    def to_dict(self) -> dict:
        return {
            "requirement": self.requirement,
            "project_name": self.project_name,
            "prd": self.prd,
            "prd_review": self.prd_review,
            "prd_verdict": self.prd_verdict,
            "design": self.design,
            "design_review": self.design_review,
            "design_verdict": self.design_verdict,
            "modules": self.modules,
            "all_files": self.all_files,
            "junior_files": self.junior_files,
            "tier_classifications": self.tier_classifications,
            "test_files": self.test_files,
            "deploy_files": self.deploy_files,
            "review": self.review,
            "verdict": self.verdict,
            "qa_plan": self.qa_plan,
            "qa_acceptance_criteria": self.qa_acceptance_criteria,
            "test_plan": self.test_plan,
            "deploy_plan": self.deploy_plan,
            "test_results": self.test_results,
            "deploy_test_results": self.deploy_test_results,
            "tests_passed": self.tests_passed,
            "deploy_tests_passed": self.deploy_tests_passed,
            "issue_number": self.issue_number,
            "issue_url": self.issue_url,
            "pr_number": self.pr_number,
            "pr_url": self.pr_url,
            "branch": self.branch,
            "completed_stages": self.completed_stages,
            "pending_clarification": self.pending_clarification,
            "clarification_history": self.clarification_history,
            "test_retry_count": self.test_retry_count,
            "test_fix_history": self.test_fix_history,
            "deploy_retry_count": self.deploy_retry_count,
            "deploy_fix_history": self.deploy_fix_history,
            "prd_revision_count": self.prd_revision_count,
            "design_revision_count": self.design_revision_count,
            "prd_reviewer_draft": self.prd_reviewer_draft,
            "design_reviewer_draft": self.design_reviewer_draft,
            "design_output": self.design_output,
            "last_verdict": self.last_verdict,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PipelineResult":
        r = cls(requirement=data["requirement"])
        for key in ["project_name", "prd", "prd_review", "prd_verdict", "design", "design_review", "design_verdict",
                    "modules", "all_files", "junior_files", "tier_classifications", "test_files",
                    "deploy_files", "review", "verdict", "qa_plan", "qa_acceptance_criteria",
                    "test_plan", "deploy_plan",
                    "test_results", "deploy_test_results", "tests_passed", "deploy_tests_passed",
                    "issue_number", "issue_url",
                    "pr_number", "pr_url", "branch", "completed_stages",
                    "pending_clarification", "clarification_history",
                    "test_retry_count", "test_fix_history",
                    "deploy_retry_count", "deploy_fix_history",
                    "prd_revision_count", "design_revision_count",
                    "prd_reviewer_draft", "design_reviewer_draft",
                    "design_output", "last_verdict"]:
            setattr(r, key, data.get(key, getattr(r, key)))
        return r


@dataclass
class PipelineStage:
    """Describes a single executable stage in the pipeline."""

    name: str
    """Identifier — used in MODES lists and per-stage config."""

    label: str
    """Display label shown in the Rich console (with emoji)."""

    description: str
    """Progress message shown while the stage runs."""

    checkpoint_key: str
    """Key written to PipelineResult.completed_stages when the stage finishes."""

    fn: Callable[[PipelineResult], None]
    """The stage callable. Receives the current PipelineResult."""

    skip_if: Callable[[PipelineResult], bool] = field(
        default_factory=lambda: lambda r: False
    )
    """Return True to skip this stage conditionally (e.g. no test_files yet)."""

    stop_if: Callable[[PipelineResult], bool] = field(
        default_factory=lambda: lambda r: False
    )
    """Return True after the stage runs to halt the pipeline early."""

    stop_message: str = ""
    """Optional message printed when stop_if triggers."""

    loop_stages: list[str] = field(default_factory=list)
    """Stage names to run repeatedly. Non-empty = this is a loop block."""

    loop_max: int = 1
    """Maximum iterations for a loop block."""

    loop_until: str = ""
    """Verdict string that exits a loop block early (e.g. 'APPROVED')."""


MODES: dict[str, list[str]] = {
    # Standard waterfall: engineers then QA
    "standard": [
        "tier_review",
        "junior_engineer",
        "senior_engineer",
        "reviewer",
        "qa_planner",
        "qa_engineer",
        "test_fix",
        "deploy_tester",
        "deploy_fix",
    ],
    # TDD: QA writes tests first, engineers implement against them
    "tdd": [
        "qa_planner",
        "qa_write",
        "tier_review",
        "junior_engineer",
        "senior_engineer",
        "test_fix",
        "reviewer",
        "deploy_tester",
        "deploy_fix",
    ],
}


class Orchestrator(TestFixLoopMixin):
    """Runs the AI software house pipeline end-to-end.

    Usage:
        orch = Orchestrator.from_config("config.yaml")
        result = orch.run("Build a task management REST API")
    """

    # Class-level default so __new__-constructed instances have the attribute
    skill_loader: Optional["SkillLoader"] = None

    def __init__(
        self,
        model: str = "gpt-4.1",
        github_repo: Optional[str] = None,
        github_token: Optional[str] = None,
        num_engineers: int = 2,
        num_junior_engineers: int = 5,
        num_senior_engineers: int = 2,
        junior_model: Optional[str] = None,
        senior_model: Optional[str] = None,
        tier_reviewer_model: Optional[str] = None,
        junior_quality_gate: bool = True,
        junior_test_retries: int = 3,
        tier_override_rules: list[dict] | None = None,
        senior_engineer_use_mcp: bool = True,
        junior_engineer_use_mcp: bool = True,
        branch_prefix: str = "feature/agent",
        workspace_dir: str = "./workspace",
        stop_on_review_issues: bool = False,
        model_overrides: Optional[dict] = None,
        use_github: bool = False,
        target_repo: Optional[str] = None,
        ollama_url: str = "http://localhost:11434",
        ollama_think: bool = False,
        ollama_preserve_thinking: bool = False,
        ollama_stream: bool = True,
        nvidia_nim_api_key: Optional[str] = None,
        nvidia_nim_base_url: Optional[str] = None,
        max_revisions: int = 3,
        max_prd_revisions: int = 3,
        max_design_revisions: int = 3,
        stop_on_prd_issues: bool = False,
        stop_on_design_issues: bool = False,
        skill_loader: Optional["SkillLoader"] = None,
        mcp_servers: list[dict] | None = None,
        retry_delay: int = 15,
        max_api_retries: int = 5,
        inter_call_delay: int = 0,
        max_test_retries: int = 5,
        max_deploy_retries: int = 5,
        framework_docs_loader: Optional["FrameworkDocsLoader"] = None,
        repo_context_loader: Optional["RepoContextLoader"] = None,
        llm_cfg: Optional[dict] = None,
        llm_fallbacks: Optional[list] = None,
        pipeline_mode: str = "standard",
        stage_skips: dict[str, bool] | None = None,
        pipeline_yaml_stages: "list[PipelineStage] | None" = None,
    ) -> None:
        self.model = model
        self.num_engineers = num_engineers
        self.num_junior_engineers = num_junior_engineers
        self.num_senior_engineers = num_senior_engineers
        self.junior_model = junior_model
        self.senior_model = senior_model
        self.tier_reviewer_model = tier_reviewer_model
        self.junior_quality_gate = junior_quality_gate
        self.junior_test_retries = junior_test_retries
        self.tier_override_rules = tier_override_rules or []
        self.senior_engineer_use_mcp = senior_engineer_use_mcp
        self.junior_engineer_use_mcp = junior_engineer_use_mcp
        self.branch_prefix = branch_prefix
        self.workspace_dir = Path(workspace_dir)
        self.stop_on_review_issues = stop_on_review_issues
        self.model_overrides = model_overrides or {}
        self.use_github = use_github and bool(github_repo)
        self._github_token = github_token
        self.ollama_url = ollama_url
        self.ollama_think = ollama_think
        self.ollama_preserve_thinking = ollama_preserve_thinking
        self.ollama_stream = ollama_stream
        self.max_revisions = max_revisions
        self.max_prd_revisions = max_prd_revisions
        self.max_design_revisions = max_design_revisions
        self.stop_on_prd_issues = stop_on_prd_issues
        self.stop_on_design_issues = stop_on_design_issues
        self.max_test_retries = max_test_retries
        self.max_deploy_retries = max_deploy_retries
        self.skill_loader: Optional[SkillLoader] = skill_loader
        self.framework_docs_loader: FrameworkDocsLoader = framework_docs_loader or FrameworkDocsLoader(config={})
        self.repo_context_loader: Optional[RepoContextLoader] = repo_context_loader

        # RAG registry and auto-indexer: only active when RAG MCP is configured
        # (rag_registry is built below from mcp_servers; store a forward ref here)
        self._rag_registry = None  # will be set after rag_registry is built below
        self.repo_auto_indexer: Optional[RepoAutoIndexer] = None  # set after rag check

        # Build combined tool registry (builtin + optional MCP servers)
        if mcp_servers:
            mcp_registry = MCPToolRegistry(mcp_servers)
            tool_registry = CombinedToolRegistry(builtin_tools, mcp_registry)
        else:
            tool_registry = builtin_tools
        self._tool_registry = tool_registry

        # Extract RAG server for retrieval-augmented agents (isolated from builtin tools)
        rag_servers = [s for s in (mcp_servers or []) if s.get("name") == "rag"]
        rag_registry = MCPToolRegistry(rag_servers) if rag_servers else None
        self._rag_registry = rag_registry
        self.repo_auto_indexer = RepoAutoIndexer() if rag_registry else None

        # Shared kwargs for all agents (kept for backward compat; tests check agent_kwargs)
        agent_kwargs: dict = {"github_token": github_token, "ollama_url": ollama_url,
                              "ollama_think": ollama_think, "ollama_preserve_thinking": ollama_preserve_thinking,
                              "ollama_stream": ollama_stream,
                              "nvidia_nim_api_key": nvidia_nim_api_key,
                              "nvidia_nim_base_url": nvidia_nim_base_url,
                              "retry_delay": retry_delay, "max_api_retries": max_api_retries,
                              "inter_call_delay": inter_call_delay}
        self.agent_kwargs = agent_kwargs

        # ── Global LLM config dict (used by _make_backend) ────────────────────
        self._llm_cfg: dict = {
            "model": model,
            "ollama_url": ollama_url,
            "ollama_think": ollama_think,
            "ollama_preserve_thinking": ollama_preserve_thinking,
            "ollama_stream": ollama_stream,
        }
        if nvidia_nim_api_key is not None:
            self._llm_cfg["nvidia_nim_api_key"] = nvidia_nim_api_key
        if nvidia_nim_base_url is not None:
            self._llm_cfg["nvidia_nim_base_url"] = nvidia_nim_base_url
        if llm_fallbacks:
            self._llm_cfg["fallbacks"] = llm_fallbacks
        if llm_cfg:
            # Caller supplied a full llm config dict — deep-merge over constructed defaults
            self._llm_cfg = _deep_merge(self._llm_cfg, llm_cfg)

        def _model(agent_name: str) -> str:
            """Return the model string for a given agent, falling back to the global default."""
            override = self.model_overrides.get(agent_name, model)
            if isinstance(override, dict):
                return override.get("model", model)
            return override

        def _mk(agent_name: str, model_fallback: Optional[str] = None) -> dict:
            """Build per-agent constructor kwargs: llm backend only.

            Delegates to :meth:`_make_backend_from_model` when *model_fallback* is
            given (tier agents whose model is resolved via team config), or to
            :meth:`_make_backend` for all other agents.  The ollama compat attrs
            (``ollama_think`` etc.) are already present in ``agent_kwargs`` and do
            not need to be duplicated here.
            """
            if model_fallback:
                backend = self._make_backend_from_model(model_fallback)
            else:
                backend = self._make_backend(agent_name)
            return {"llm": backend}

        self.pm = ProductManagerAgent(**{**agent_kwargs, **_mk("product_manager")})
        self.pm_reviewer = PMReviewerAgent(**{**agent_kwargs, **_mk("pm_reviewer")})
        self.architect = ArchitectAgent(tool_registry=rag_registry, **{**agent_kwargs, **_mk("architect")})
        self.architect_reviewer = ArchitectReviewerAgent(**{**agent_kwargs, **_mk("architect_reviewer")})
        self.engineer = EngineerAgent(tool_registry=rag_registry, **{**agent_kwargs, **_mk("engineer")})
        self.reviewer = CodeReviewerAgent(tool_registry=tool_registry, **{**agent_kwargs, **_mk("code_reviewer")})
        self.qa_planner = QAPlannerAgent(tool_registry=tool_registry, **{**agent_kwargs, **_mk("qa_planner")})
        self.qa = QAEngineerAgent(tool_registry=rag_registry, **{**agent_kwargs, **_mk("qa_engineer")})
        self.deployment_tester = DeploymentTesterAgent(**{**agent_kwargs, **_mk("deployment_tester")})

        # Junior/Senior tier agents — model priority: llm.overrides > team.junior/senior_model > global
        # When an agent has a dict override entry, pass model_fallback=None so _mk routes to
        # _make_backend() which deep-merges the full dict (preserving extra keys like ollama_think).
        # When there is no dict override, pass the resolved model string as model_fallback so
        # _mk routes to _make_backend_from_model() with the correct team/global model.
        _junior_fallback = (
            None if "junior_engineer" in self.model_overrides
            else (self.junior_model or self.model)
        )
        _senior_fallback = (
            None if "senior_engineer" in self.model_overrides
            else (self.senior_model or self.model)
        )
        # tier_reviewer fallback must not reference _junior_model (removed); replicate logic inline.
        _tier_rev_fallback = (
            None if "tier_reviewer" in self.model_overrides
            else (self.tier_reviewer_model or self.junior_model or self.model)
        )

        self.junior_engineer = JuniorEngineerAgent(
            tool_registry=rag_registry if self.junior_engineer_use_mcp else None,
            **{**agent_kwargs, **_mk("junior_engineer", model_fallback=_junior_fallback)},
        )
        self.senior_engineer = SeniorEngineerAgent(
            tool_registry=rag_registry if self.senior_engineer_use_mcp else None,
            **{**agent_kwargs, **_mk("senior_engineer", model_fallback=_senior_fallback)},
        )
        self.tier_reviewer = TierReviewerAgent(
            **{**agent_kwargs, **_mk("tier_reviewer", model_fallback=_tier_rev_fallback)},
        )


        # Snapshot original system prompts to prevent stacking on repeated run() calls
        self._original_system_prompts: dict = {
            agent: agent.system_prompt
            for agent in (
                self.pm, self.pm_reviewer, self.architect, self.architect_reviewer,
                self.engineer, self.junior_engineer, self.senior_engineer,
                self.reviewer, self.qa_planner, self.qa,
                self.deployment_tester,
            )
            if agent is not None
        }

        self.summariser = SummaryAgent(**{**agent_kwargs, **_mk("summariser")})
        self.refactor_agent = RefactorAgent(**{**agent_kwargs, **_mk("refactor_agent")})

        # Long-term SQLite memory store
        self.memory = MemoryStore(self.workspace_dir / "memory.db")

        # Tracker GitHub (ai-software-house): PM issues, progress comments
        self.github: Optional[GitHubClient] = None
        if self.use_github and github_repo:
            self.github = GitHubClient(repo=github_repo, github_token=github_token)
            self._ensure_github_labels()

        # Target GitHub: where code branches / commits / PRs go.
        # Defaults to tracker github; overridden at run-time when issue body has "Target repo:".
        self.target_github: Optional[GitHubClient] = None
        if target_repo and target_repo != github_repo:
            self.target_github = GitHubClient(repo=target_repo, github_token=github_token)
        else:
            self.target_github = self.github

        # ── Pipeline mode + per-stage skip config ─────────────────────────────
        self._mode: str = pipeline_mode
        self._stage_skips: dict[str, bool] = stage_skips or {}
        self._pipeline_yaml_stages: "list[PipelineStage] | None" = pipeline_yaml_stages

    # ── Backend factory helpers ───────────────────────────────────────────────

    def _make_backend(self, agent_name: str) -> "LLMBackend":
        """Build an :class:`~agents.backends.base.LLMBackend` for *agent_name*.

        Reads the global ``_llm_cfg`` config, merges any per-agent override from
        ``model_overrides``, translates orchestrator-level keys to the backend
        constructor's expected keys, and calls :func:`~agents.backends.factory.create_backend`.

        Supports both string overrides (model name only) and dict overrides
        (full per-agent settings).
        """
        from agents.backends.factory import create_backend
        from agents.backends.base import LLMBackend as _LLMBackend  # noqa: F401

        # Merge global cfg with per-agent override
        cfg: dict = dict(self._llm_cfg)
        override = self.model_overrides.get(agent_name)
        if isinstance(override, str):
            cfg["model"] = override
        elif isinstance(override, dict):
            cfg = _deep_merge(cfg, override)

        return self._build_factory_cfg_and_create(cfg)

    def _make_backend_from_model(self, model: str) -> "LLMBackend":
        """Build a backend for an explicit model string, inheriting global llm settings.

        Used for tier agents (junior/senior/tier_reviewer) whose model is resolved
        via ``team.junior_model`` / ``team.senior_model`` rather than a named
        ``model_overrides`` entry.
        """
        cfg: dict = dict(self._llm_cfg)
        cfg["model"] = model
        return self._build_factory_cfg_and_create(cfg)

    def _build_factory_cfg_and_create(self, cfg: dict) -> "LLMBackend":
        """Translate orchestrator-level config keys → factory keys and call create_backend.

        Handles key-name differences between the YAML/orchestrator config
        (``ollama_think``, ``ollama_stream``, …) and the backend constructors
        (``think``, ``stream``, …).

        Models with a provider prefix that is *not* a recognised backend prefix
        (e.g. ``openai/gpt-4.1``, ``meta/llama-3.1-405b-instruct``) are treated
        as GitHub Models API calls — matching the legacy ``BaseAgent._build_backend``
        default fallback.  These are routed directly to
        :class:`~agents.backends.github_models.GitHubModelsBackend` rather than
        through :func:`~agents.backends.factory.create_backend`, which raises
        ``ValueError`` for unknown prefixes.
        """
        model: str = cfg["model"]

        # Prefixes that create_backend understands natively
        _FACTORY_PREFIXES = (
            "ollama/", "copilot/", "nvidia-nim/",
            "opencode/", "opencode-zen/", "opencode-go/",
            "claude-",
        )
        # Route to GitHub Models for bare names OR unknown-prefix names
        # (e.g. "openai/gpt-4.1", "meta/llama-3.1-405b-instruct").
        use_factory = ("/" not in model) or any(
            model.startswith(p) for p in _FACTORY_PREFIXES
        )

        if not use_factory:
            from agents.backends.github_models import GitHubModelsBackend
            primary = GitHubModelsBackend(model=model, github_token=self._github_token)
            fallback_cfgs: list[dict] = cfg.get("fallbacks") or []
            if not fallback_cfgs:
                return primary
            from agents.backends.fallback import FallbackLLMBackend
            # Each fallback inherits parent settings; its own keys take priority
            parent_base = {k: v for k, v in cfg.items() if k != "fallbacks"}
            backends = [primary] + [
                self._build_factory_cfg_and_create(_deep_merge(parent_base, fb))
                for fb in fallback_cfgs
            ]
            return FallbackLLMBackend(backends)

        # Build translated factory cfg for the primary backend
        factory_cfg: dict = {"model": model}

        if model.startswith("ollama/"):
            factory_cfg["ollama_url"] = cfg.get("ollama_url", "http://localhost:11434")
            factory_cfg["think"] = cfg.get("ollama_think", False)
            factory_cfg["preserve_thinking"] = cfg.get("ollama_preserve_thinking", False)
            factory_cfg["stream"] = cfg.get("ollama_stream", True)
        elif model.startswith("nvidia-nim/"):
            if cfg.get("nvidia_nim_api_key"):
                factory_cfg["nvidia_nim_api_key"] = cfg["nvidia_nim_api_key"]
            if cfg.get("nvidia_nim_base_url"):
                factory_cfg["nvidia_nim_base_url"] = cfg["nvidia_nim_base_url"]
        # All other backends (anthropic, copilot, opencode, opencode-zen,
        # opencode-go) use env-var auth and need no extra config keys.

        from agents.backends.factory import _make_single_backend
        primary = _make_single_backend(factory_cfg, github_token=self._github_token)

        # Recursively translate and build each fallback through this same method
        # so that ollama_think/ollama_stream etc. are properly translated for each entry.
        # Each fallback inherits parent settings (e.g. ollama_url, ollama_stream) by
        # default; its own keys take priority via _deep_merge.
        fallback_cfgs: list[dict] = cfg.get("fallbacks") or []
        if not fallback_cfgs:
            return primary

        parent_base = {k: v for k, v in cfg.items() if k != "fallbacks"}
        from agents.backends.fallback import FallbackLLMBackend
        backends = [primary] + [
            self._build_factory_cfg_and_create(_deep_merge(parent_base, fb))
            for fb in fallback_cfgs
        ]
        return FallbackLLMBackend(backends)

    @classmethod
    def from_config(cls, config_path: str = "config.yaml", github_token: Optional[str] = None) -> "Orchestrator":
        """Create an Orchestrator from a YAML config file."""
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        # Load optional local override config (never committed)
        local_path = Path(config_path).parent / "config.local.yaml"
        if local_path.exists():
            with open(local_path, encoding="utf-8") as lf:
                local_cfg = yaml.safe_load(lf) or {}
            cfg = _deep_merge(cfg, local_cfg)

        llm = cfg.get("llm", {})
        gh = cfg.get("github", {})
        team = cfg.get("team", {})
        pipeline = cfg.get("pipeline", {})
        mcp_cfg = cfg.get("mcp", {})
        mcp_servers = mcp_cfg.get("servers") or []

        pipeline_mode = pipeline.get("mode", "standard")
        stage_skips = {}
        raw_stages = pipeline.get("stages") or {}
        if not isinstance(raw_stages, dict):
            raise ValueError(
                f"pipeline.stages must be a mapping, got {type(raw_stages).__name__}"
            )
        for name, opts in raw_stages.items():
            if not isinstance(opts, dict):
                raise ValueError(
                    f"pipeline.stages.{name} must be a mapping (e.g. {{skip: true}}), got {type(opts).__name__}"
                )
            stage_skips[name] = bool(opts.get("skip", False))

        skill_loader = SkillLoader(config=cfg)
        skill_loader.init()

        framework_docs_loader = FrameworkDocsLoader(config=cfg)

        repo_ctx_cfg = cfg.get("repo_context", {})
        repo_context_loader = RepoContextLoader(
            threshold=repo_ctx_cfg.get("large_repo_threshold", 50)
        )

        repo = gh.get("repo", "")
        use_github = bool(repo) and repo != "your-username/your-repo"

        # Load pipeline.yaml from same directory as config file (overrides pipeline.mode)
        _temp_orch_for_load = cls.__new__(cls)
        _temp_orch_for_load._stage_skips = {}
        _temp_orch_for_load._pipeline_yaml_stages = None
        _temp_orch_for_load._mode = pipeline_mode
        # Stub agent attributes so _make_stage_registry() can build fn lambdas
        for _attr in ("pm", "pm_reviewer", "architect", "architect_reviewer",
                      "engineer", "junior_engineer", "senior_engineer", "reviewer",
                      "qa", "qa_planner", "deployment_tester", "tier_reviewer"):
            setattr(_temp_orch_for_load, _attr, None)
        pipeline_yaml_stages = _temp_orch_for_load._load_pipeline_yaml(config_path)
        if pipeline_yaml_stages is not None:
            logging.debug("pipeline.yaml found — pipeline.mode in config.yaml is ignored.")

        return cls(
            model=llm.get("model", "gpt-4.1"),
            github_repo=repo if use_github else None,
            github_token=github_token,
            num_engineers=team.get("num_engineers", 2),
            num_junior_engineers=team.get("num_junior_engineers", 5),
            num_senior_engineers=team.get("num_senior_engineers", 2),
            junior_model=team.get("junior_model"),
            senior_model=team.get("senior_model"),
            tier_reviewer_model=team.get("tier_reviewer_model"),
            junior_quality_gate=team.get("junior_quality_gate", True),
            junior_test_retries=team.get("junior_test_retries", 3),
            tier_override_rules=team.get("tier_override_rules", []),
            senior_engineer_use_mcp=team.get("senior_engineer_use_mcp", True),
            junior_engineer_use_mcp=team.get("junior_engineer_use_mcp", True),
            branch_prefix=gh.get("branch_prefix", "feature/agent"),
            workspace_dir=pipeline.get("workspace_dir", "./workspace"),
            stop_on_review_issues=pipeline.get("stop_on_review_issues", False),
            model_overrides=llm.get("overrides", {}),
            use_github=use_github,
            ollama_url=llm.get("ollama_url", "http://localhost:11434"),
            ollama_think=llm.get("ollama_think", False),
            ollama_preserve_thinking=llm.get("ollama_preserve_thinking", False),
            ollama_stream=llm.get("ollama_stream", True),
            max_revisions=pipeline.get("max_revisions", 3),
            max_prd_revisions=pipeline.get("max_prd_revisions", 3),
            max_design_revisions=pipeline.get("max_design_revisions", 3),
            stop_on_prd_issues=pipeline.get("stop_on_prd_issues", False),
            stop_on_design_issues=pipeline.get("stop_on_design_issues", False),
            skill_loader=skill_loader,
            mcp_servers=mcp_servers,
            retry_delay=pipeline.get("retry_delay", 15),
            max_api_retries=pipeline.get("max_api_retries", 5),
            inter_call_delay=pipeline.get("inter_call_delay", 0),
            max_test_retries=pipeline.get("max_test_retries", 5),
            max_deploy_retries=pipeline.get("max_deploy_retries", 5),
            framework_docs_loader=framework_docs_loader,
            repo_context_loader=repo_context_loader,
            llm_fallbacks=llm.get("fallbacks") or None,
            pipeline_mode=pipeline_mode,
            stage_skips=stage_skips,
            pipeline_yaml_stages=pipeline_yaml_stages,
        )

    # ── Revision helpers ──────────────────────────────────────────────────────

    def _make_stage_registry(self) -> dict[str, "PipelineStage"]:
        """Build the full registry of all known pipeline stages."""
        return {
            "pm": PipelineStage(
                name="pm",
                label="📋 Product Manager",
                description="Analyzing requirements & writing PRD...",
                checkpoint_key="pm",
                fn=lambda r: self._stage_pm(r, r.requirement),
            ),
            "pm_reviewer": PipelineStage(
                name="pm_reviewer",
                label="📝 PM Reviewer",
                description="Reviewing PRD for completeness...",
                checkpoint_key="pm_reviewer",
                fn=lambda r: self._stage_pm_reviewer(r, r.requirement),
            ),
            "architect": PipelineStage(
                name="architect",
                label="🏗️  Architect",
                description="Designing system architecture...",
                checkpoint_key="architect",
                fn=lambda r: self._stage_architect(r),
            ),
            "architect_reviewer": PipelineStage(
                name="architect_reviewer",
                label="🔎 Architect Reviewer",
                description="Reviewing system design...",
                checkpoint_key="architect_reviewer",
                fn=lambda r: self._stage_architect_reviewer(r),
            ),
            "tier_review": PipelineStage(
                name="tier_review",
                label="🏷️  Tier Review",
                description="Classifying modules into junior/senior tiers...",
                checkpoint_key="tier_review",
                fn=lambda r: self._stage_tier_review(r),
            ),
            "junior_engineer": PipelineStage(
                name="junior_engineer",
                label="🟢 Junior Engineers",
                description="Implementing junior module(s)...",
                checkpoint_key="junior_engineer",
                fn=lambda r: self._stage_junior_engineer(r),
                skip_if=lambda r: "engineer" in r.completed_stages,
            ),
            "senior_engineer": PipelineStage(
                name="senior_engineer",
                label="🔵 Senior Engineers",
                description="Implementing senior module(s)...",
                checkpoint_key="senior_engineer",
                fn=lambda r: self._stage_senior_engineer(r),
                skip_if=lambda r: "engineer" in r.completed_stages,
            ),
            "reviewer": PipelineStage(
                name="reviewer",
                label="🔍 Code Reviewer",
                description="Reviewing generated code...",
                checkpoint_key="reviewer",
                fn=lambda r: self._stage_reviewer(r),
                stop_if=lambda r: self.stop_on_review_issues and r.verdict == "CHANGES REQUESTED",
                stop_message="⛔ Pipeline stopped: code reviewer requested changes.",
            ),
            "qa_planner": PipelineStage(
                name="qa_planner",
                label="📋 QA Planner",
                description="Creating test plan & acceptance criteria...",
                checkpoint_key="qa_planner",
                fn=lambda r: self._stage_qa_planner(r),
            ),
            "qa_engineer": PipelineStage(
                name="qa_engineer",
                label="🧪 QA Engineer",
                description="Writing tests & producing test plan...",
                checkpoint_key="qa",
                fn=lambda r: self._stage_qa(r),
            ),
            "qa_write": PipelineStage(
                name="qa_write",
                label="✍️  QA Write (TDD)",
                description="Writing tests before implementation...",
                checkpoint_key="qa_write",
                fn=lambda r: self._stage_qa_write(r),
            ),
            "test_fix": PipelineStage(
                name="test_fix",
                label="🏃 Test Runner + Fix Loop",
                description="Executing tests (with auto-fix)…",
                checkpoint_key="test_runner",
                fn=lambda r: self._stage_test_fix_loop(r),
                skip_if=lambda r: not r.test_files,
            ),
            "deploy_tester": PipelineStage(
                name="deploy_tester",
                label="🚀 Deployment Tester",
                description="Generating deployment smoke tests...",
                checkpoint_key="deployment_tester",
                fn=lambda r: self._stage_deployment_tester(r),
            ),
            "deploy_fix": PipelineStage(
                name="deploy_fix",
                label="🐳 Deploy Test Runner + Fix Loop",
                description="Running deployment tests (with auto-fix)…",
                checkpoint_key="deploy_test_runner",
                fn=lambda r: self._stage_deploy_fix_loop(r),
                skip_if=lambda r: not r.deploy_files,
            ),
        }

    def _load_pipeline_yaml(self, config_path: str) -> "list[PipelineStage] | None":
        """Parse and validate pipeline.yaml from the same directory as config_path.

        Returns an ordered list of PipelineStage objects, or None if the file
        does not exist. Raises ValueError on any schema violation.
        """
        pipeline_yaml_path = Path(config_path).parent / "pipeline.yaml"
        if not pipeline_yaml_path.exists():
            return None

        try:
            with open(pipeline_yaml_path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise yaml.YAMLError(f"Error parsing {pipeline_yaml_path}: {exc}") from exc

        if not data or not isinstance(data.get("stages"), list):
            raise ValueError(
                f"pipeline.yaml must define a 'stages' list. "
                f"Found: {type(data.get('stages')).__name__ if data else 'empty file'}"
            )

        registry = self._make_stage_registry()
        valid_names = set(registry.keys())
        stages: list[PipelineStage] = []

        for i, entry in enumerate(data["stages"]):
            if isinstance(entry, str):
                if entry not in valid_names:
                    raise ValueError(
                        f"Unknown stage {entry!r} at index {i} in pipeline.yaml. "
                        f"Valid names: {sorted(valid_names)}"
                    )
                stages.append(registry[entry])

            elif isinstance(entry, dict) and "loop" in entry:
                loop = entry["loop"]
                if not isinstance(loop, dict):
                    raise ValueError(f"Loop block at index {i} must be a mapping.")
                for required_key in ("max", "until", "stages"):
                    if required_key not in loop:
                        raise ValueError(
                            f"Loop block at index {i} missing required field '{required_key}'."
                        )
                if not loop["until"]:
                    raise ValueError(
                        f"Loop block at index {i} 'until' must be a non-empty string "
                        f"(e.g. 'APPROVED'). Got: {loop['until']!r}"
                    )
                if not isinstance(loop["stages"], list) or len(loop["stages"]) == 0:
                    raise ValueError(
                        f"Loop block at index {i} 'stages' must be a non-empty list."
                    )
                if not isinstance(loop["max"], int) or loop["max"] <= 0:
                    raise ValueError(
                        f"Loop block at index {i} 'max' must be a positive integer."
                    )
                for inner_name in loop["stages"]:
                    if inner_name not in valid_names:
                        raise ValueError(
                            f"Unknown stage {inner_name!r} inside loop block at index {i}. "
                            f"Valid names: {sorted(valid_names)}"
                        )
                inner_label = ", ".join(loop["stages"])
                stages.append(PipelineStage(
                    name=f"loop_{i}",
                    label=f"🔁 Loop ({inner_label})",
                    description=f"Running loop: {inner_label}...",
                    checkpoint_key=f"loop_{i}",
                    fn=lambda r: None,  # execution handled by _run_loop_stage()
                    loop_stages=list(loop["stages"]),
                    loop_max=loop["max"],
                    loop_until=str(loop["until"]),
                ))

            else:
                raise ValueError(
                    f"Invalid stage entry at index {i}: {entry!r}. "
                    f"Expected a stage name (string) or a loop block (dict with 'loop' key)."
                )

        return stages

    def _build_stage_list(self) -> list[PipelineStage]:
        """Return the ordered stage list, applying skip overrides.

        When _pipeline_yaml_stages is set (pipeline.yaml present), that list
        takes full precedence. Otherwise falls back to MODES[_mode].
        """
        if getattr(self, '_pipeline_yaml_stages', None) is not None:
            return [
                s for s in self._pipeline_yaml_stages
                if not self._stage_skips.get(s.name, False)
            ]

        registry = self._make_stage_registry()
        if self._mode not in MODES:
            raise ValueError(
                f"Unknown pipeline.mode {self._mode!r}. Valid modes: {list(MODES)}"
            )
        stage_names = MODES[self._mode]
        return [
            registry[name]
            for name in stage_names
            if name in registry and not self._stage_skips.get(name, False)
        ]

    def _run_loop_stage(self, loop_stage: "PipelineStage", result: "PipelineResult") -> bool:
        """Execute a loop block from pipeline.yaml.

        Runs inner stages repeatedly until loop_until verdict is seen or loop_max
        iterations are exhausted. Returns True to continue pipeline, False on error.

        Note: Checkpointing is at the loop-block level (the outer loop_N stage). If
        the pipeline is interrupted mid-loop, the entire loop will restart on resume.
        Individual inner stages are not checkpointed.
        """
        registry = self._make_stage_registry()
        console.print(f"\n  {loop_stage.label}")

        for iteration in range(loop_stage.loop_max):
            result.last_verdict = ""
            for inner_name in loop_stage.loop_stages:
                inner = registry[inner_name]
                self._run_stage(
                    inner.label, inner.description, result,
                    lambda s=inner: s.fn(result)
                )
                if result.errors:
                    return False

            if result.last_verdict == loop_stage.loop_until:
                console.print(
                    f"  ✅ [green]Loop condition met: {loop_stage.loop_until} "
                    f"(round {iteration + 1})[/green]"
                )
                break

            if iteration < loop_stage.loop_max - 1:
                console.print(
                    f"  🔄 [yellow]Round {iteration + 1}/{loop_stage.loop_max} — "
                    f"verdict: {result.last_verdict or 'none'}, retrying...[/yellow]"
                )

        if result.last_verdict != loop_stage.loop_until:
            console.print(
                f"  ⚠️  [yellow]Loop exhausted after {loop_stage.loop_max} rounds "
                f"without reaching '{loop_stage.loop_until}' "
                f"(last verdict: {result.last_verdict or 'none'})[/yellow]"
            )

        return True

    def _get_revision_number(self, labels: list[str]) -> int:
        """Return the highest ai-revision-N number found in labels, or 0."""
        nums = [int(m.group(1)) for lbl in labels if (m := re.fullmatch(r"ai-revision-(\d+)", lbl))]
        return max(nums, default=0)

    def _extract_issue_number(self, body: str) -> Optional[int]:
        """Extract a GitHub issue number from phrases like 'Closes #42' or 'Related to #7'."""
        m = re.search(r"(?:Closes|Related to|Fixes|Resolves)\s+#(\d+)", body, re.IGNORECASE)
        return int(m.group(1)) if m else None

    def _safe_fence(self, content: str) -> str:
        """Escape triple backticks to prevent prompt injection via file content."""
        return content.replace("```", "` ` `")

    def _collect_pr_feedback(self, pr_number: int) -> list[dict]:
        """Return non-bot PR review comments and review bodies as a flat list.

        Each item: {"author": str, "body": str, "location": str}
        """
        bot_logins = {"github-actions[bot]", "copilot[bot]"}

        inline = self.target_github.get_pr_review_comments(pr_number)
        reviews = self.target_github.get_pr_reviews(pr_number)

        feedback = []
        for c in inline:
            login = c.get("user", {}).get("login", "")
            if login in bot_logins:
                continue
            body = (c.get("body") or "").strip()
            if not body:
                continue
            line_no = c.get('line')
            location = f"{c.get('path', '?')} line {line_no if line_no is not None else c.get('original_line', '?')}"
            feedback.append({"author": login, "body": body, "location": location})

        for r in reviews:
            login = r.get("user", {}).get("login", "")
            if login in bot_logins:
                continue
            body = (r.get("body") or "").strip()
            if not body:
                continue
            feedback.append({"author": login, "body": body, "location": "review"})

        return feedback

    def _format_feedback(self, feedback: list[dict]) -> str:
        """Format a list of feedback dicts as a markdown bullet list."""
        lines = ["### PR Feedback to Address\n"]
        for item in feedback:
            location = f" _(at {item['location']})_" if item["location"] != "review" else ""
            lines.append(f"- **{item['author']}**{location}: {item['body']}")
        return "\n".join(lines)

    def _fetch_design_from_issue(self, issue_number: int) -> str:
        """Read issue comments to find the architect's system design post.

        Returns the body of the first comment containing '🏗️ System Design',
        or an empty string if not found.
        """
        comments = self.github.get_issue_comments(issue_number)
        for c in comments:
            body = c.get("body", "")
            if "System Design" in body and "🏗️" in body:
                return body
        return ""

    def run_revision(self, pr_number: int) -> dict:
        """Re-run engineer→reviewer→QA for a PR based on human review comments.

        Reads all non-bot review comments from the PR, re-generates the code
        incorporating the feedback, pushes commits to the same branch, posts a
        summary comment, and updates the ai-revision-N label.

        Returns a dict with a "status" key:
          - "max_revisions_reached" — revision cap hit, nothing done
          - "no_feedback"           — no human comments found, nothing done
          - "ok"                    — revision committed, "revision" key has round number
        """
        if self.target_github is None:
            raise RuntimeError("target_github is required for run_revision()")

        # ── 1. PR metadata ────────────────────────────────────────────────────
        pr = self.target_github.get_pr(pr_number)
        head_branch = pr["head"]["ref"]
        pr_body = pr.get("body") or ""
        issue_number = self._extract_issue_number(pr_body)
        labels = [lbl["name"] for lbl in pr.get("labels", [])]

        # ── Inject skills ─────────────────────────────────────────────────────
        if self.skill_loader:
            active_repo = self.target_github.repo
            repo_languages = self.target_github.get_repo_languages(active_repo)
            skill_ctx = SkillContext(
                issue_body=pr_body,
                explicit_skills=_parse_explicit_skills(pr_body),
                repo_languages=repo_languages,
            )
            matched_skills = self.skill_loader.detect(skill_ctx)
            for role, agent in [("engineer", self.engineer), ("code_reviewer", self.reviewer), ("qa_engineer", self.qa)]:
                blocks = self.skill_loader.for_role(role, matched_skills)
                block_text = self.skill_loader.render_prompt_block(blocks)
                if block_text:
                    original = getattr(self, '_original_system_prompts', {}).get(agent, agent.system_prompt or "")
                    if original:
                        agent.system_prompt = block_text + "\n\n---\n\n" + original

        # ── 2. Check revision cap ─────────────────────────────────────────────
        current_rev = self._get_revision_number(labels)
        if current_rev >= self.max_revisions:
            self.target_github.add_pr_comment(
                pr_number,
                f"⏹ Max revisions reached ({current_rev}/{self.max_revisions}). "
                "No further automated revisions will be made.",
            )
            return {"status": "max_revisions_reached"}

        # ── 3. Collect human feedback ─────────────────────────────────────────
        feedback = self._collect_pr_feedback(pr_number)
        if not feedback:
            return {"status": "no_feedback"}

        feedback_md = self._format_feedback(feedback)
        console.print(f"  💬 Collected [bold]{len(feedback)}[/bold] feedback item(s) from PR #{pr_number}")

        # ── 4. Fetch design from linked issue ─────────────────────────────────
        design = self._fetch_design_from_issue(issue_number) if issue_number else ""
        if not design:
            console.print("  [yellow]⚠️  No system design found in linked issue — engineer will use feedback only[/yellow]")

        # ── 5. Read current files from branch ─────────────────────────────────
        pr_files = self.target_github.get_pr_files(pr_number)
        current_files: dict[str, str] = {}
        for f in pr_files:
            path = f["filename"]
            content = self.target_github.get_file_content(path, ref=head_branch)
            if content is not None:
                current_files[path] = content

        console.print(f"  📂 Read [bold]{len(current_files)}[/bold] current file(s) from branch [cyan]{head_branch}[/cyan]")

        # ── 6. Build augmented design for engineer ────────────────────────────
        current_files_block = "\n\n".join(
            f"### `{path}`\n```\n{self._safe_fence(content)}\n```"
            for path, content in current_files.items()
        )
        augmented_design = (
            f"{design}\n\n"
            f"---\n\n"
            f"## Current Code on Branch `{head_branch}`\n\n"
            f"{current_files_block}\n\n"
            f"---\n\n"
            f"{feedback_md}"
        )

        # ── 7. Re-run engineer → reviewer → QA ───────────────────────────────
        new_revision = current_rev + 1
        console.print(f"\n[bold cyan]🔄 Revision {new_revision}/{self.max_revisions}[/bold cyan]")

        revision_modules = [
            {
                "name": "Revision",
                "description": (
                    f"Revise the existing code to address all PR feedback listed above. "
                    f"Return updated versions of these files: {', '.join(current_files.keys())}. "
                    f"Only change what is necessary to address the feedback."
                ),
            }
        ]

        project_name = pr.get("title", f"PR #{pr_number}").replace("[Implementation] ", "")

        # Engineer: generate revised files
        console.print("  👷 [cyan]Engineer[/cyan] — revising code based on PR feedback...")
        eng_result = self.engineer.run_all_modules(augmented_design, revision_modules, project_name)
        revised_files: dict[str, str] = eng_result.get("all_files", {})
        if not revised_files:
            console.print("  [red]⚠️  Engineer returned no files — aborting revision[/red]")
            self.target_github.add_pr_comment(
                pr_number,
                "⚠️ Revision aborted: the engineer agent produced no updated files. "
                "Please retry or check the model logs.",
            )
            return {"status": "error", "reason": "engineer_returned_no_files"}

        # Commit revised files to the existing branch
        commit_errors: list[str] = []
        for filepath, content in revised_files.items():
            try:
                self.target_github.commit_file(
                    path=filepath,
                    content=content,
                    message=f"fix: revision {new_revision} — address PR feedback [{filepath}]",
                    branch=head_branch,
                )
            except RuntimeError as exc:
                commit_errors.append(f"{filepath}: {exc}")
                console.print(f"  [red]⚠️  Failed to commit {filepath}: {exc}[/red]")

        if commit_errors:
            self.target_github.add_pr_comment(
                pr_number,
                f"⚠️ Revision {new_revision} partially failed. "
                f"Could not commit:\n" + "\n".join(f"- `{e}`" for e in commit_errors),
            )
            return {"status": "error", "reason": "commit_failed", "errors": commit_errors}

        console.print(f"  ✅ Committed [bold]{len(revised_files)}[/bold] revised file(s) to [cyan]{head_branch}[/cyan]")

        # Code Reviewer
        rev_result = self.reviewer.run(revised_files, design or "N/A", project_name)
        console.print(f"  🔍 Code review verdict: [bold]{rev_result.get('verdict', '?')}[/bold]")

        # QA Engineer
        qa_result = self.qa.run(revised_files, design or "N/A", project_name)
        test_files: dict[str, str] = qa_result.get("test_files", {})
        for filepath, content in test_files.items():
            self.target_github.commit_file(
                path=filepath,
                content=content,
                message=f"test: revision {new_revision} — update tests [{filepath}]",
                branch=head_branch,
            )

        # ── 8. Update label and post summary comment ──────────────────────────
        old_label = f"ai-revision-{current_rev}" if current_rev > 0 else None
        new_label = f"ai-revision-{new_revision}"

        self.target_github.ensure_labels([
            {"name": new_label, "color": "0075ca", "description": f"AI revision round {new_revision}"}
        ])
        if old_label:
            self.target_github.remove_pr_label(pr_number, old_label)
        self.target_github.add_pr_label(pr_number, new_label)

        summary = (
            f"## ✅ Revision {new_revision} Complete\n\n"
            f"The AI agents have addressed **{len(feedback)} feedback item(s)**:\n\n"
            + "\n".join(
                f"- {item['body'][:120]}{'…' if len(item['body']) > 120 else ''}"
                for item in feedback
            )
            + f"\n\n**Files updated:** {', '.join(f'`{p}`' for p in revised_files)}\n"
            f"**Code review verdict:** {rev_result.get('verdict', 'N/A')}\n"
            f"**Test files updated:** {len(test_files)}"
        )
        self.target_github.add_pr_comment(pr_number, summary)

        return {"status": "ok", "revision": new_revision, "files_updated": len(revised_files)}

    def run(self, requirement: str, trigger_issue_body: Optional[str] = None, resume: bool = True, issue_number: Optional[int] = None) -> PipelineResult:
        """Execute the full pipeline for a given requirement.

        Args:
            requirement: The user's software requirement in plain English.
            trigger_issue_body: Optional raw body of the GitHub Issue that triggered this run.
                If it contains a "Target repo:" directive, code goes to that repo instead of
                the tracker repo.
            resume: If True (default), load a saved checkpoint and skip already-completed stages.

        Returns:
            A PipelineResult with all artifacts.
        """
        start_time = time.time()

        # ── Detect target project repo (multi-repo support) ───────────────────
        target_repo_override = parse_target_repo(trigger_issue_body or "")
        if target_repo_override and self.github and target_repo_override != self.github.repo:
            self.target_github = GitHubClient(repo=target_repo_override, github_token=self._github_token)
            console.print(f"  🎯 Targeting project repo: [bold]{target_repo_override}[/bold]")
        elif not self.target_github:
            self.target_github = self.github

        # ── Fetch repo context (file tree) ────────────────────────────────────
        repo_context: Optional[RepoContext] = None
        if self.repo_context_loader and self.target_github:
            repo_context = self.repo_context_loader.build(self.target_github)
            if repo_context.tree_text:
                size_label = "large" if repo_context.is_large else "small"
                console.print(
                    f"  🗂️  [dim]Repo tree loaded ({repo_context.file_count} files, {size_label})[/dim]"
                )
                tree_block = repo_context.tree_text + "\n\n---\n\n"
                for agent in (self.pm, self.architect, self.pm_reviewer, self.architect_reviewer):
                    if agent.system_prompt is not None:
                        if not agent.system_prompt.startswith(tree_block):
                            agent.system_prompt = tree_block + agent.system_prompt

        # ── Inject long-term memory into agents ───────────────────────────────
        active_repo = str(self.target_github.repo if self.target_github else
                          (self.github.repo if self.github else "local"))
        memory_context = self.memory.recall(active_repo)
        if memory_context:
            console.print(f"  🧠 [dim]Loaded memory from {active_repo}[/dim]")
            # Prepend past-work context to each agent's system prompt
            for agent in (self.pm, self.architect, self.engineer,
                          self.junior_engineer, self.senior_engineer,
                          self.reviewer, self.qa, self.qa_planner):
                if agent.system_prompt:
                    agent.system_prompt = memory_context + "\n\n---\n\n" + agent.system_prompt

        # ── Inject skills into agents ─────────────────────────────────────────
        if self.skill_loader:
            repo_languages: list[str] = []
            if self.target_github:
                repo_languages = self.target_github.get_repo_languages(active_repo)
            explicit_skills = _parse_explicit_skills(trigger_issue_body or "")
            skill_ctx = SkillContext(
                issue_body=trigger_issue_body or requirement,
                explicit_skills=explicit_skills,
                repo_languages=repo_languages,
            )
            matched_skills = self.skill_loader.detect(skill_ctx)
            if matched_skills:
                skill_names = ", ".join(s.name for s in matched_skills)
                console.print(f"  🎯 [dim]Skills loaded: {skill_names}[/dim]")
            # Save original prompts before any injection (memory + skills)
            # This prevents prompt stacking if run() is called multiple times on the same instance
            _role_agents = {
                "product_manager": self.pm,
                "pm_reviewer": self.pm_reviewer,
                "architect": self.architect,
                "architect_reviewer": self.architect_reviewer,
                "engineer": self.engineer,
                "junior_engineer": self.junior_engineer,
                "senior_engineer": self.senior_engineer,
                "tier_reviewer": self.tier_reviewer,
                "code_reviewer": self.reviewer,
                "qa_planner": self.qa_planner,
                "qa_engineer": self.qa,
                "deployment_tester": self.deployment_tester,
            }
            for role, agent in _role_agents.items():
                blocks = self.skill_loader.for_role(role, matched_skills)
                block_text = self.skill_loader.render_prompt_block(blocks)
                if block_text:
                    original = getattr(self, '_original_system_prompts', {}).get(agent, agent.system_prompt or "")
                    if original:
                        agent.system_prompt = block_text + "\n\n---\n\n" + original

        # ── Load checkpoint if resuming ───────────────────────────────────────
        result = self._load_checkpoint(requirement) if resume else None
        if result:
            console.print(
                f"[bold yellow]⏭️  Resuming from checkpoint[/bold yellow] "
                f"(completed: {', '.join(result.completed_stages)})"
            )
        else:
            result = PipelineResult(requirement=requirement)

        # Pre-set issue_number if provided by caller (allows pause before PM creates it)
        if issue_number is not None and not result.issue_number:
            result.issue_number = issue_number

        console.print(Panel.fit(
            f"[bold cyan]🏢 AI Software House Pipeline[/bold cyan]\n"
            f"[dim]{requirement[:120]}{'...' if len(requirement) > 120 else ''}[/dim]",
            border_style="cyan",
        ))

        # ── Stage 1 + 2: hardcoded PM / Arch revision loops (standard pipeline only) ──
        if getattr(self, '_pipeline_yaml_stages', None) is None:
            # ── Stage 1: PM + PM Reviewer revision loop ───────────────────────
            if "pm_review_loop" not in result.completed_stages:
                ok = self._prd_revision_loop(result, requirement)
                if not ok:
                    return self._finish(result, start_time)
            else:
                console.print("  ⏭️  [dim]PRD revision loop — skipped (checkpoint)[/dim]")

            # ── Stage 2: Architect + Architect Reviewer revision loop ─────────
            if "architect_review_loop" not in result.completed_stages:
                ok = self._design_revision_loop(result)
                if not ok:
                    return self._finish(result, start_time)
            else:
                console.print("  ⏭️  [dim]Design revision loop — skipped (checkpoint)[/dim]")

        # ── RAG index (always before engineer, not mode-dependent) ─────────────
        if self.repo_auto_indexer and self.target_github and "rag_index" not in result.completed_stages:
            self._run_stage(
                "📦 RAG Index",
                "Indexing repo codebase into RAG...",
                result,
                lambda: self._stage_repo_index(result),
            )
            result.completed_stages.append("rag_index")

        # ── Mode-driven stage loop ────────────────────────────────────────────
        for stage in self._build_stage_list():
            # Checkpoint resume: skip if already completed
            if stage.checkpoint_key in result.completed_stages or stage.name in result.completed_stages:
                console.print(f"  ⏭️  [dim]{stage.label} — skipped (checkpoint)[/dim]")
                continue

            # Conditional skip (e.g. test_fix skipped when no test_files)
            if stage.skip_if(result):
                console.print(f"  ⏭️  [dim]{stage.label} — skipped[/dim]")
                continue

            if stage.loop_stages:
                # Loop block from pipeline.yaml
                ok = self._run_loop_stage(stage, result)
                if not ok:
                    self._save_checkpoint(result)
                    return self._finish(result, start_time)
            else:
                self._run_stage(stage.label, stage.description, result, lambda s=stage: s.fn(result))

                if result.errors:
                    self._save_checkpoint(result)
                    return self._finish(result, start_time)

            # Backward-compat: senior_engineer stage also marks old "engineer" key
            if stage.name == "senior_engineer":
                result.completed_stages.append("engineer")

            result.completed_stages.append(stage.checkpoint_key)
            self._save_checkpoint(result)

            # Early pipeline stop (e.g. code review: CHANGES REQUESTED)
            # NOTE: checkpoint_key is saved before stop_if check (intentional).
            # On resume, completed stages (incl. reviewer) are skipped, so
            # the pipeline continues from the next stage rather than re-running
            # the stage that triggered the stop.
            if stage.stop_if(result):
                if stage.stop_message:
                    console.print(f"[bold red]{stage.stop_message}[/bold red]")
                return self._finish(result, start_time)

        # Pipeline complete — remove checkpoint
        self._clear_checkpoint(result)
        return self._finish(result, start_time)

    # ── Stage implementations ────────────────────────────────────────────────

    def _stage_pm(self, result: PipelineResult, requirement: str) -> None:
        ctx = self._build_clarification_context(result.clarification_history, stage="pm")
        effective_req = f"{ctx}\n\n---\n\n{requirement}" if ctx else requirement
        if self.github:
            pm_result = self.pm.run_with_github(effective_req, self.github)
            result.issue_number = pm_result["issue_number"]
            result.issue_url = pm_result["issue_url"]
        else:
            pm_result = self.pm.run(effective_req)
        result.prd = pm_result["prd"]
        result.project_name = pm_result["project_name"]

    def _stage_architect(self, result: PipelineResult) -> None:
        ctx = self._build_clarification_context(result.clarification_history, stage="architect")
        effective_prd = f"{ctx}\n\n---\n\n{result.prd}" if ctx else result.prd
        if self.github and result.issue_number:
            arch_result = self.architect.run_with_github(
                effective_prd, result.project_name, self.github, result.issue_number
            )
        else:
            arch_result = self.architect.run(effective_prd, result.project_name)
        result.design = arch_result["design"]
        result.modules = arch_result["modules"]

    def _stage_pm_reviewer(self, result: PipelineResult, requirement: str) -> None:
        """Review the PM's PRD. If revision needed, update prd + project_name."""
        if self.github and result.issue_number:
            rev_result = self.pm_reviewer.run_with_github(
                result.prd, requirement, result.project_name, self.github, result.issue_number
            )
        else:
            rev_result = self.pm_reviewer.run(result.prd, requirement, result.project_name)

        result.prd_review = rev_result["review"]
        result.prd_verdict = rev_result["verdict"]
        result.last_verdict = result.prd_verdict

        # Store reviewer's draft for use in run_revision() (new revision loop)
        result.prd_reviewer_draft = rev_result.get("revised_prd") or ""
        # Legacy single-pass behaviour preserved when loop is disabled (max_prd_revisions == 0)
        if getattr(self, "max_prd_revisions", 3) == 0 and rev_result["needs_revision"] and rev_result["revised_prd"]:
            result.prd = rev_result["revised_prd"]
            result.project_name = rev_result["revised_project_name"]

    def _stage_pm_revision(self, result: PipelineResult, requirement: str, round_num: int) -> None:
        """PM rewrites the PRD using reviewer feedback and reviewer's draft."""
        pm_result = self.pm.run_revision(
            original_prd=result.prd,
            review=result.prd_review,
            draft_revision=result.prd_reviewer_draft,
            requirement=requirement,
            project_name=result.project_name,
        )
        result.prd = pm_result["prd"]
        result.project_name = pm_result["project_name"]
        result.prd_revision_count = round_num

    def _prd_revision_loop(self, result: PipelineResult, requirement: str) -> bool:
        """Run PM → PM Reviewer revision loop (up to max_prd_revisions rounds).

        Returns True if pipeline should continue, False if it should halt.
        """
        # Step 1: PM writes initial PRD
        if "pm" not in result.completed_stages:
            try:
                self._run_stage(
                    "📋 Product Manager",
                    "Analyzing requirements & writing PRD...",
                    result,
                    lambda: self._stage_pm(result, requirement),
                )
            except ClarificationNeeded as exc:
                self._pause_for_clarification(result, "pm", exc.questions)
                return False
            if result.errors:
                self._save_checkpoint(result)
                return False
            result.completed_stages.append("pm")
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]📋 Product Manager — skipped (checkpoint)[/dim]")

        # Step 2: Initial PM Reviewer pass
        if "pm_reviewer" not in result.completed_stages:
            self._run_stage(
                "📝 PM Reviewer",
                "Reviewing PRD for completeness...",
                result,
                lambda: self._stage_pm_reviewer(result, requirement),
            )
            if result.errors:
                self._save_checkpoint(result)
                return False
            result.completed_stages.append("pm_reviewer")
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]📝 PM Reviewer — skipped (checkpoint)[/dim]")

        # Step 3: Revision loop (skip if disabled)
        if self.max_prd_revisions == 0:
            result.completed_stages.append("pm_review_loop")
            self._save_checkpoint(result)
            return True

        any_round_ran = False
        for round_num in range(1, self.max_prd_revisions + 1):
            if result.prd_verdict != PMReviewerAgent.VERDICT_REVISION:
                break  # Already approved

            key = f"prd_revision_{round_num}"
            if key in result.completed_stages:
                console.print(f"  ⏭️  [dim]PRD revision round {round_num} — skipped (checkpoint)[/dim]")
                continue

            any_round_ran = True
            # PM rewrites PRD
            console.print(
                f"  🔄 [yellow]PRD NEEDS REVISION (round {round_num}/{self.max_prd_revisions})"
                f" — sending back to PM...[/yellow]"
            )
            self._run_stage(
                "📋 Product Manager",
                f"Revising PRD based on reviewer feedback (round {round_num})...",
                result,
                lambda rn=round_num: self._stage_pm_revision(result, requirement, rn),
            )
            if result.errors:
                self._save_checkpoint(result)
                return False

            # Reviewer re-checks
            self._run_stage(
                "📝 PM Reviewer",
                f"Re-reviewing revised PRD (round {round_num})...",
                result,
                lambda: self._stage_pm_reviewer(result, requirement),
            )
            if result.errors:
                self._save_checkpoint(result)
                return False

            result.completed_stages.append(key)
            self._save_checkpoint(result)
        else:
            # for-else: exited without break → max rounds hit, still NEEDS REVISION
            if any_round_ran:
                console.print(
                    f"  ⚠️  [yellow]Max PRD revisions reached ({self.max_prd_revisions}/"
                    f"{self.max_prd_revisions}). "
                    + ("Halting pipeline." if self.stop_on_prd_issues else "Continuing with current best.")
                    + "[/yellow]"
                )
                if self.stop_on_prd_issues:
                    if self.github and result.issue_number:
                        self.github.add_issue_comment(
                            result.issue_number,
                            f"⚠️ PRD revision limit reached after {self.max_prd_revisions} rounds. "
                            f"Human review required. Remove `agent-failed` label and re-trigger to retry.",
                        )
                    result.completed_stages.append("pm_review_loop")
                    self._save_checkpoint(result)
                    return False

        if result.prd_verdict != PMReviewerAgent.VERDICT_REVISION:
            console.print(
                f"  ✅ [green]PRD APPROVED (round {result.prd_revision_count})[/green]"
            )

        result.completed_stages.append("pm_review_loop")
        self._save_checkpoint(result)
        return True

    def _stage_arch_revision(self, result: PipelineResult, round_num: int) -> None:
        """Ask ArchitectAgent to revise the design based on reviewer feedback."""
        rev_result = self.architect.run_revision(
            original_design=result.design,
            prd=result.prd,
            review=result.design_review or "",
            draft_revision=result.design_reviewer_draft or "",
            project_name=result.project_name or "",
        )
        result.design = rev_result["design"]
        if rev_result.get("modules"):
            result.modules = rev_result["modules"]
        result.design_revision_count = round_num

    def _design_revision_loop(self, result: PipelineResult) -> bool:
        """Run Architect + Architect Reviewer in a feedback loop, up to max_design_revisions rounds.

        Returns True if pipeline should continue, False if it should halt.
        """
        # Step 1: Architect
        if "architect" not in result.completed_stages:
            try:
                self._run_stage("🏗️  Architect", "Designing system architecture...", result, lambda: self._stage_architect(result))
            except ClarificationNeeded as exc:
                self._pause_for_clarification(result, "architect", exc.questions)
                return False
            if result.errors:
                self._save_checkpoint(result)
                return False
            result.completed_stages.append("architect")
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]🏗️  Architect — skipped (checkpoint)[/dim]")

        # Step 2: Initial Architect Reviewer pass
        if "architect_reviewer" not in result.completed_stages:
            self._run_stage(
                "🔎 Architect Reviewer",
                "Reviewing system design...",
                result,
                lambda: self._stage_architect_reviewer(result),
            )
            if result.errors:
                self._save_checkpoint(result)
                return False
            result.completed_stages.append("architect_reviewer")
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]🔎 Architect Reviewer — skipped (checkpoint)[/dim]")

        # Step 3: Revision loop (skip if disabled)
        if self.max_design_revisions == 0:
            result.completed_stages.append("architect_review_loop")
            self._save_checkpoint(result)
            return True

        any_round_ran = False
        for round_num in range(1, self.max_design_revisions + 1):
            if result.design_verdict != ArchitectReviewerAgent.VERDICT_REVISION:
                break  # Already approved

            key = f"design_revision_{round_num}"
            if key in result.completed_stages:
                console.print(f"  ⏭️  [dim]Design revision round {round_num} — skipped (checkpoint)[/dim]")
                continue

            any_round_ran = True
            # Architect rewrites design
            console.print(
                f"  🔄 [yellow]DESIGN NEEDS REVISION (round {round_num}/{self.max_design_revisions})"
                f" — sending back to Architect...[/yellow]"
            )
            self._run_stage(
                "🏗️  Architect",
                f"Revising design based on reviewer feedback (round {round_num})...",
                result,
                lambda rn=round_num: self._stage_arch_revision(result, rn),
            )
            if result.errors:
                self._save_checkpoint(result)
                return False

            # Reviewer re-checks
            self._run_stage(
                "🔎 Architect Reviewer",
                f"Re-reviewing revised design (round {round_num})...",
                result,
                lambda: self._stage_architect_reviewer(result),
            )
            if result.errors:
                self._save_checkpoint(result)
                return False

            result.completed_stages.append(key)
            self._save_checkpoint(result)
        else:
            # for-else: exited without break → max rounds hit, still NEEDS REVISION
            if any_round_ran:
                console.print(
                    f"  ⚠️  [yellow]Max design revisions reached ({self.max_design_revisions}/"
                    f"{self.max_design_revisions}). "
                    + ("Halting pipeline." if self.stop_on_design_issues else "Continuing with current best.")
                    + "[/yellow]"
                )
                if self.stop_on_design_issues:
                    if self.github and result.issue_number:
                        self.github.add_issue_comment(
                            result.issue_number,
                            f"⚠️ Design revision limit reached after {self.max_design_revisions} rounds. "
                            f"Human review required. Remove `agent-failed` label and re-trigger to retry.",
                        )
                    result.completed_stages.append("architect_review_loop")
                    self._save_checkpoint(result)
                    return False

        if result.design_verdict != ArchitectReviewerAgent.VERDICT_REVISION:
            console.print(
                f"  ✅ [green]DESIGN APPROVED (round {result.design_revision_count})[/green]"
            )

        result.completed_stages.append("architect_review_loop")
        self._save_checkpoint(result)
        return True

    def _stage_architect_reviewer(self, result: PipelineResult) -> None:
        """Review the Architect's design. Store draft; only self-patch when max_design_revisions == 0."""
        if self.github and result.issue_number:
            rev_result = self.architect_reviewer.run_with_github(
                result.design, result.prd, result.project_name, self.github, result.issue_number
            )
        else:
            rev_result = self.architect_reviewer.run(result.design, result.prd, result.project_name)

        result.design_review = rev_result["review"]
        result.design_verdict = rev_result["verdict"]
        result.last_verdict = result.design_verdict
        result.design_reviewer_draft = rev_result.get("revised_design") or result.design

        if self.max_design_revisions == 0 and rev_result.get("revised_design"):
            # Legacy single-pass: apply reviewer's draft directly
            console.print(
                f"  🔄 [yellow]Design revised by reviewer "
                f"({rev_result['verdict']})[/yellow]"
            )
            result.design = rev_result["revised_design"]
            if rev_result.get("revised_modules"):
                result.modules = rev_result["revised_modules"]
        else:
            console.print(f"  🔎 Design verdict: [bold]{rev_result['verdict']}[/bold]")

    def _stage_repo_index(self, result: PipelineResult) -> None:
        """Auto-index the target repo into RAG codebase collection.

        Only runs when RAG MCP is configured and target_github is set.
        Runs before the Engineer stage so search_codebase returns real results.
        """
        if not self.repo_auto_indexer or not self.target_github:
            return
        console.print("  📦 [dim]Indexing repo into RAG codebase collection...[/dim]")
        self.repo_auto_indexer.index(
            repo=self.target_github.repo,
            github_token=self._github_token or "",
        )

    def _stage_engineer(self, result: PipelineResult) -> None:
        modules = result.modules[: max(self.num_engineers, len(result.modules))]
        # Determine project_dir for framework docs detection
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in result.project_name.lower())
        project_dir = (self.workspace_dir / safe).resolve()
        framework_context = self.framework_docs_loader.load(project_dir)
        if self.target_github:
            eng_result = self.engineer.run_with_github(
                result.design,
                modules,
                result.project_name,
                self.target_github,
                branch_prefix=self.branch_prefix,
                issue_number=result.issue_number,
                max_workers=self.num_engineers,
                framework_context=framework_context,
            )
            result.branch = eng_result.get("branch")
            result.pr_number = eng_result.get("pr_number")
            result.pr_url = eng_result.get("pr_url")
        else:
            eng_result = self.engineer.run_all_modules(
                result.design, modules, result.project_name, max_workers=self.num_engineers,
                framework_context=framework_context,
            )
        result.all_files = eng_result["all_files"]
        self._save_files_locally(result.all_files, result.project_name)

    def _stage_tier_review(self, result: PipelineResult) -> None:
        """Validate module tier assignments via TierReviewerAgent, then apply config overrides."""
        revised = self.tier_reviewer.run(result.modules)
        final = apply_tier_overrides(revised, self.tier_override_rules)
        result.modules = final
        result.tier_classifications = final

    def _run_junior_module_tests(self, files: dict[str, str], project_name: str) -> tuple[bool, str]:
        """Write module files to a temp directory and run pytest on them.

        Returns:
            (passed: bool, output: str)
        """
        test_files = {p: c for p, c in files.items() if "test" in p.lower()}
        if not test_files:
            return True, "No test files — skipping junior quality gate for this module"

        with tempfile.TemporaryDirectory(prefix=f"junior_gate_{project_name}_") as tmpdir:
            for filepath, content in files.items():
                dest = os.path.join(tmpdir, filepath)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "w") as f:
                    f.write(content)
            test_paths = [os.path.join(tmpdir, p) for p in test_files]
            proc = subprocess.run(
                [sys.executable, "-m", "pytest"] + test_paths + ["-v", "--tb=short", "-x"],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=tmpdir,
            )
            passed = proc.returncode == 0
            output = proc.stdout + proc.stderr
        return passed, output

    def _stage_junior_engineer(self, result: PipelineResult) -> None:
        """Implement junior-tier modules with fast model; run quality gate per module."""
        modules_with_tiers = result.modules  # from tier_review when available
        design_modules = result.design_output.get("modules", []) if result.design_output else []
        _all_modules = modules_with_tiers if modules_with_tiers else design_modules
        tiers_present = any(m.get("tier") for m in _all_modules)
        default_tier = None if tiers_present else "junior"
        junior_modules = [m for m in _all_modules if m.get("tier", default_tier) == "junior"]
        if not junior_modules:
            console.print("  [dim]No junior modules to implement.[/dim]")
            return

        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in result.project_name.lower())
        project_dir = (self.workspace_dir / safe).resolve()
        framework_context = self.framework_docs_loader.load(project_dir)

        if self.target_github:
            eng_result = self.junior_engineer.run_with_github(
                result.design,
                junior_modules,
                result.project_name,
                self.target_github,
                branch_prefix=self.branch_prefix,
                issue_number=result.issue_number,
                max_workers=self.num_junior_engineers,
                framework_context=framework_context,
                test_files=result.test_files if self._mode == "tdd" else None,
            )
            result.branch = eng_result.get("branch")
            result.pr_number = eng_result.get("pr_number")
            result.pr_url = eng_result.get("pr_url")
        else:
            eng_result = self.junior_engineer.run_all_modules(
                result.design,
                junior_modules,
                result.project_name,
                max_workers=self.num_junior_engineers,
                framework_context=framework_context,
                test_files=result.test_files if self._mode == "tdd" else None,
            )

        junior_files: dict[str, str] = eng_result.get("all_files", {})
        escalated: list[dict] = []

        if self.junior_quality_gate:
            for mod_result in eng_result.get("modules", []):
                mod_files = mod_result["files"]
                mod_name = mod_result["module_name"]
                passed, output = self._run_junior_module_tests(mod_files, result.project_name)

                retries = 0
                while not passed and retries < self.junior_test_retries:
                    retries += 1
                    console.print(
                        f"  🔄 [yellow]Junior gate retry {retries}/{self.junior_test_retries} "
                        f"for {mod_name}[/yellow]"
                    )
                    fixed = self.junior_engineer.fix_failures(
                        failure_output=output,
                        all_files=mod_files,
                        design=result.design,
                        project_name=result.project_name,
                    )
                    mod_files.update(fixed)
                    junior_files.update(fixed)
                    passed, output = self._run_junior_module_tests(mod_files, result.project_name)

                if not passed:
                    console.print(
                        f"  ⬆️  [yellow]Escalating {mod_name} to senior tier "
                        f"(failed after {self.junior_test_retries} retries)[/yellow]"
                    )
                    for m in result.modules:
                        if m["name"] == mod_name:
                            m["tier"] = "senior"
                            escalated.append(m)
                            break
                    for tc in result.tier_classifications:
                        if tc["name"] == mod_name:
                            tc["tier"] = "senior"
                            break
                    for path in list(mod_files.keys()):
                        junior_files.pop(path, None)

        result.junior_files = junior_files
        self._save_files_locally(junior_files, result.project_name)

        if escalated:
            console.print(
                f"  ⬆️  [dim]{len(escalated)} module(s) escalated to senior tier.[/dim]"
            )

    def _stage_senior_engineer(self, result: PipelineResult) -> None:
        """Implement senior-tier modules with expensive model; inject junior code as context."""
        design_modules = result.design_output.get("modules", []) if result.design_output else []
        _all_modules = result.modules if result.modules else design_modules
        tiers_present = any(m.get("tier") for m in _all_modules)
        default_tier = None if tiers_present else "junior"
        senior_modules = [m for m in _all_modules if m.get("tier", default_tier) == "senior"]
        if not senior_modules:
            console.print("  [dim]No senior modules to implement.[/dim]")
            result.all_files = dict(result.junior_files)
            return

        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in result.project_name.lower())
        project_dir = (self.workspace_dir / safe).resolve()
        framework_context = self.framework_docs_loader.load(project_dir)

        from concurrent.futures import ThreadPoolExecutor

        senior_results = []
        with ThreadPoolExecutor(max_workers=self.num_senior_engineers) as executor:
            futures = [
                executor.submit(
                    self.senior_engineer.run_module,
                    result.design,
                    mod,
                    result.project_name,
                    framework_context,
                    result.junior_files,
                    test_files=result.test_files if self._mode == "tdd" else None,
                )
                for mod in senior_modules
            ]
            for future in futures:
                senior_results.append(future.result())

        senior_files: dict[str, str] = {}
        for sr in senior_results:
            senior_files.update(sr["files"])

        result.all_files = {**result.junior_files, **senior_files}
        self._save_files_locally(result.all_files, result.project_name)

        if self.target_github and result.branch:
            for filepath, content in senior_files.items():
                self.target_github.commit_file(
                    filepath,
                    content,
                    branch=result.branch,
                    message=f"feat({result.project_name}): implement senior module files",
                )

    def _stage_reviewer(self, result: PipelineResult) -> None:
        if self.target_github and result.pr_number:
            rev_result = self.reviewer.run_with_github(
                result.all_files, result.prd, result.project_name, self.target_github, result.pr_number
            )
        else:
            rev_result = self.reviewer.run(result.all_files, result.prd, result.project_name)
        result.review = rev_result["review"]
        result.verdict = rev_result["verdict"]

    def _stage_qa_planner(self, result: PipelineResult) -> None:
        """QA Planner produces a structured test plan before QA Engineer writes tests."""
        cross_repo = self.target_github is not self.github and self.target_github is not None
        github_client = self.github  # test plan posted to tracker issue

        if github_client and result.issue_number:
            plan_result = self.qa_planner.run_with_github(
                result.prd,
                result.design,
                result.all_files,
                result.project_name,
                github_client,
                issue_number=result.issue_number,
                pr_number=result.pr_number if not cross_repo else None,
            )
        else:
            plan_result = self.qa_planner.run(
                result.prd, result.design, result.all_files, result.project_name
            )

        result.qa_plan = plan_result["test_plan"]
        result.qa_acceptance_criteria = plan_result["acceptance_criteria"]

    def _stage_qa_write(self, result: PipelineResult) -> None:
        prd = result.prd or ""
        project_name = result.project_name or "project"
        console.print(f"\n[bold cyan]🧪 QA Engineer (write-only)[/bold cyan]")
        qa_result = self.qa.run({}, prd, project_name, test_plan=result.qa_plan, write_only=True)
        result.test_files = qa_result.get("test_files", {})
        result.test_plan = qa_result.get("test_plan", result.qa_plan or "")
        if result.test_files:
            self._save_files_locally(result.test_files, project_name)
            console.print(f"[green]✅ {len(result.test_files)} test file(s) written locally[/green]")
        else:
            console.print("[yellow]⚠️  No test files generated[/yellow]")

    def _stage_qa(self, result: PipelineResult) -> None:
        cross_repo = self.target_github is not self.github and self.target_github is not None
        if self.target_github and result.branch and result.pr_number and result.issue_number:
            qa_result = self.qa.run_with_github(
                result.all_files,
                result.prd,
                result.project_name,
                self.target_github,
                branch=result.branch,
                pr_number=result.pr_number,
                issue_number=None if cross_repo else result.issue_number,
                tracker_github_client=self.github if cross_repo else None,
                test_plan=result.qa_plan,
            )
        else:
            qa_result = self.qa.run(result.all_files, result.prd, result.project_name, test_plan=result.qa_plan)
        result.test_files = qa_result["test_files"]
        result.test_plan = qa_result["test_plan"]
        self._save_files_locally(result.test_files, result.project_name)

    def _stage_test_runner(self, result: PipelineResult) -> None:
        """Run pytest on the locally saved test files and post results back to the PR."""
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in result.project_name.lower())
        project_dir = (self.workspace_dir / safe).resolve()  # absolute path — avoids doubled --rootdir when cwd changes

        # Install test requirements if present
        req_file = project_dir / "requirements-test.txt"
        if not req_file.exists():
            # Fallback: write a minimal one
            req_file.write_text("pytest\npytest-cov\npytest-timeout\nhttpx\n", encoding="utf-8")

        console.print("    📦 Installing test dependencies…")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q",
             "pytest-timeout"],  # always ensure timeout plugin is available
            check=False,
            timeout=120,
        )

        tests_dir = project_dir / "tests"
        if not tests_dir.exists():
            console.print("    ⚠️  No tests/ directory found — skipping execution.")
            result.test_results = "No tests directory found."
            return

        console.print(f"    🏃 Running pytest in {tests_dir}…")
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", str(tests_dir), "-v", "--tb=short",
                 f"--rootdir={project_dir}", "-p", "no:cacheprovider",
                 "--timeout=30"],  # 30s per test to prevent hanging integration tests
                capture_output=True,
                text=True,
                cwd=str(project_dir),
                timeout=300,  # 5 min total cap
            )
        except subprocess.TimeoutExpired:
            console.print("    ⚠️  Tests timed out after 5 minutes — skipping results.")
            result.test_results = "Tests timed out after 5 minutes."
            result.tests_passed = False
            return

        output = proc.stdout + proc.stderr
        passed = proc.returncode == 0
        status = "✅ All tests passed" if passed else "❌ Some tests failed"
        console.print(f"    {status}")

        # Show last 40 lines in console
        lines = output.strip().splitlines()
        summary_lines = lines[-40:] if len(lines) > 40 else lines
        for line in summary_lines:
            console.print(f"    [dim]{line}[/dim]")

        result.test_results = output
        result.tests_passed = passed

        # Post results as a PR comment
        if self.target_github and result.pr_number:
            truncated = "\n".join(lines[-80:]) if len(lines) > 80 else output
            self.target_github.add_pr_comment(
                result.pr_number,
                f"## 🏃 Test Run Results\n\n"
                f"**Status:** {status}\n\n"
                f"```\n{truncated}\n```",
            )

    def _make_project_file_helpers(
        self, project_dir
    ) -> tuple:
        """Return (get_all_files_fn, write_files_fn) closures for a project directory."""
        skip = {".git", "__pycache__", "node_modules"}

        def get_all_files_fn() -> dict:
            files = {}
            for path in sorted(project_dir.rglob("*")):
                if any(part in skip for part in path.parts):
                    continue
                if path.is_file() and path.suffix not in {".pyc", ".pyo"}:
                    try:
                        files[str(path.relative_to(project_dir))] = path.read_text(
                            encoding="utf-8", errors="replace"
                        )
                    except OSError:
                        pass
            return files

        def write_files_fn(patches: dict) -> None:
            for filepath, content in patches.items():
                full_path = project_dir / filepath
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content, encoding="utf-8")

        return get_all_files_fn, write_files_fn

    def _stage_test_fix_loop(self, result: PipelineResult) -> None:
        """Run tests and automatically retry engineer fixes on failure."""
        safe = "".join(
            c if c.isalnum() or c in "-_" else "_"
            for c in result.project_name.lower()
        )
        project_dir = (self.workspace_dir / safe).resolve()

        get_all_files_fn, write_files_fn = self._make_project_file_helpers(project_dir)

        def commit_fn(attempt: int, patches: dict) -> bool:
            if self.target_github and result.branch:
                for filepath, content in patches.items():
                    self.target_github.commit_file(
                        path=filepath,
                        content=content,
                        message=f"fix(auto): test retry {attempt}/{self.max_test_retries}",
                        branch=result.branch,
                    )
            return True  # GitHub API always commits; cannot detect "no diff" to short-circuit

        def post_comment_fn(message: str) -> None:
            if self.target_github and result.pr_number:
                self.target_github.add_pr_comment(result.pr_number, message)

        def fix_fn(failure_output: str, all_files: dict) -> dict:
            return self.engineer.fix_failures(
                failure_output=failure_output,
                all_files=all_files,
                design=result.design,
                project_name=result.project_name,
            )

        self.run_test_fix_loop(
            result=result,
            run_tests_fn=lambda r: self._stage_test_runner(r),
            get_all_files_fn=get_all_files_fn,
            write_files_fn=write_files_fn,
            commit_fn=commit_fn,
            post_comment_fn=post_comment_fn,
            fix_fn=fix_fn,
            max_retries=self.max_test_retries,
        )

    def _stage_deployment_tester(self, result: PipelineResult) -> None:
        """Generate deployment smoke tests and commit them to the PR branch."""
        deploy_result = self.deployment_tester.run(result.all_files, result.prd, result.project_name)
        result.deploy_files = deploy_result["deploy_files"]
        result.deploy_plan = deploy_result["deploy_plan"]
        self._save_files_locally(result.deploy_files, result.project_name)

        if self.target_github and result.branch and result.pr_number:
            self.deployment_tester.run_with_github(
                result.all_files, result.prd, result.project_name,
                self.target_github, result.branch, result.pr_number,
            )

    def _stage_deploy_test_runner(self, result: PipelineResult) -> None:
        """Run docker-compose deployment smoke tests locally."""
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in result.project_name.lower())
        project_dir = self.workspace_dir / safe

        # Check if docker is available
        docker_check = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        if docker_check.returncode != 0:
            console.print("    ⚠️  Docker not available — skipping deployment tests.")
            result.deploy_test_results = "Docker not available in this environment."
            result.deploy_tests_passed = None
            return

        console.print("    🐳 Running docker deployment smoke tests…")
        deploy_result = self.deployment_tester.run_docker_smoke_tests(project_dir)

        if deploy_result.get("skipped"):
            console.print(f"    ⏭️  {deploy_result['output']}")
            result.deploy_tests_passed = None
            return

        output = deploy_result["output"]
        passed = deploy_result["passed"]
        status = "✅ Deployment tests passed" if passed else "❌ Deployment tests failed"
        console.print(f"    {status}")

        lines = output.strip().splitlines()
        for line in lines[-20:]:
            console.print(f"    [dim]{line}[/dim]")

        result.deploy_test_results = output
        result.deploy_tests_passed = passed

        if self.target_github and result.pr_number:
            truncated = "\n".join(lines[-60:]) if len(lines) > 60 else output
            self.target_github.add_pr_comment(
                result.pr_number,
                f"## 🐳 Deployment Smoke Test Results\n\n"
                f"**Status:** {status}\n\n"
                f"```\n{truncated}\n```",
            )

    def _stage_deploy_fix_loop(self, result: PipelineResult) -> None:
        """Run deployment tests and retry engineer fixes on failure.

        Only called when unit tests have passed (result.tests_passed is True).
        Uses result.deploy_retry_count and result.deploy_fix_history.
        """
        if result.tests_passed is not True:
            console.print("    ⏭️  Skipping deploy fix loop — unit tests did not pass.")
            return

        safe = "".join(
            c if c.isalnum() or c in "-_" else "_"
            for c in result.project_name.lower()
        )
        project_dir = (self.workspace_dir / safe).resolve()

        get_all_files_fn, write_files_fn = self._make_project_file_helpers(project_dir)

        def commit_fn(attempt: int, patches: dict) -> bool:
            if self.target_github and result.branch:
                for filepath, content in patches.items():
                    self.target_github.commit_file(
                        path=filepath,
                        content=content,
                        message=f"fix(auto): deploy retry {attempt}/{self.max_deploy_retries}",
                        branch=result.branch,
                    )
            return True  # GitHub API always commits; cannot detect "no diff" to short-circuit

        def post_comment_fn(message: str) -> None:
            if self.target_github and result.pr_number:
                self.target_github.add_pr_comment(result.pr_number, message)

        def fix_fn(failure_output: str, all_files: dict) -> dict:
            return self.engineer.fix_failures(
                failure_output=failure_output,
                all_files=all_files,
                design=result.design,
                project_name=result.project_name,
            )

        # Temporarily alias deploy fields to the standard names the mixin expects,
        # then restore. This lets us reuse run_test_fix_loop without modification.
        _orig_passed = result.tests_passed
        _orig_results = result.test_results
        _orig_count = result.test_retry_count
        _orig_history = result.test_fix_history
        result.tests_passed = result.deploy_tests_passed
        result.test_results = result.deploy_test_results
        result.test_retry_count = result.deploy_retry_count
        result.test_fix_history = result.deploy_fix_history

        def run_deploy_tests(r):
            self._stage_deploy_test_runner(r)
            # Treat None (skipped/unavailable) as a non-failure so the fix loop doesn't trigger
            r.tests_passed = r.deploy_tests_passed if r.deploy_tests_passed is not None else True
            r.test_results = r.deploy_test_results

        try:
            self.run_test_fix_loop(
                result=result,
                run_tests_fn=run_deploy_tests,
                get_all_files_fn=get_all_files_fn,
                write_files_fn=write_files_fn,
                commit_fn=commit_fn,
                post_comment_fn=post_comment_fn,
                fix_fn=fix_fn,
                max_retries=self.max_deploy_retries,
            )
        finally:
            # Restore and sync deploy fields
            result.deploy_retry_count = result.test_retry_count
            result.deploy_fix_history = result.test_fix_history
            result.tests_passed    = _orig_passed
            result.test_results    = _orig_results
            result.test_retry_count = _orig_count
            result.test_fix_history = _orig_history

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _run_stage(self, name: str, description: str, result: PipelineResult, fn) -> None:
        """Run a pipeline stage with progress display and error handling."""
        with Progress(
            SpinnerColumn(),
            TextColumn(f"[bold blue]{name}[/bold blue] {description}"),
            transient=True,
            console=console,
        ) as progress:
            progress.add_task("running", total=None)
            try:
                fn()
                console.print(f"  ✅ [green]{name}[/green] complete")
            except ClarificationNeeded:
                raise  # handled by run() — do not log as error
            except Exception as exc:
                error_msg = f"{name} failed: {exc}"
                result.errors.append(error_msg)
                console.print(f"  ❌ [red]{error_msg}[/red]")

    def _build_clarification_context(self, history: list[dict], stage: str) -> str:
        """Build an answer-injection block for a specific stage from Q&A history.

        Returns an empty string if there are no completed rounds for this stage.
        The returned block is prepended to the agent's main input so the agent
        treats the answers as authoritative requirements.
        """
        rounds = [r for r in history if r.get("stage") == stage]
        if not rounds:
            return ""
        lines = ["## Clarification Answers (from repository owner)\n"]
        for r in rounds:
            lines.append(f"### Round {r['round']}")
            for q, a in zip(r["questions"], r["answers"]):
                lines.append(f"{q}")
                lines.append(f"→ {a}\n")
        return "\n".join(lines)

    def _pause_for_clarification(
        self,
        result: PipelineResult,
        stage_key: str,
        questions: list[str],
    ) -> None:
        """Post Q&A comment to GitHub, save checkpoint, switch to agent-waiting.

        Called from run() when ClarificationNeeded is caught at stage boundary.
        Does nothing if GitHub integration is not configured.
        If qa_rounds >= 3, logs a warning and returns WITHOUT pausing (proceed
        with assumptions on next run).
        """
        qa_rounds = sum(1 for r in result.clarification_history if r.get("stage") == stage_key) + 1

        # Enforce max 3 Q&A rounds
        if qa_rounds > 3:
            console.print(
                f"  ⚠️  [yellow]Max Q&A rounds reached for stage '{stage_key}' "
                f"— proceeding with assumptions[/yellow]"
            )
            return

        console.print(f"  🤔 [yellow]Clarification needed (round {qa_rounds})[/yellow]")

        comment_id: Optional[int] = None
        if self.github and result.issue_number:
            q_lines = "\n".join(f"**{q}**" for q in questions)
            comment_body = (
                f"<!-- ai-question:{stage_key}:round-{qa_rounds} -->\n"
                f"🤖 **AI needs clarification before proceeding**\n\n"
                f"Please answer the following questions by replying to this comment:\n\n"
                f"{q_lines}\n\n"
                f"_Pipeline paused. It will resume automatically when you reply. "
                f"If no answer is received within 24 hours, the pipeline will proceed "
                f"with its best assumptions._"
            )
            try:
                resp = self.github.add_issue_comment(result.issue_number, comment_body)
                comment_id = resp.get("id") if isinstance(resp, dict) else None
            except Exception as exc:
                console.print(f"  ⚠️  [yellow]Could not post comment: {exc}[/yellow]")

            # Switch labels: remove agent-running, add agent-waiting
            try:
                from watcher import LABEL_RUNNING, LABEL_WAITING
                self.github.remove_pr_label(result.issue_number, LABEL_RUNNING)
                self.github.add_pr_label(result.issue_number, LABEL_WAITING)
            except Exception as exc:
                console.print(f"  ⚠️  [yellow]Could not update labels: {exc}[/yellow]")

        import datetime as _dt
        result.pending_clarification = {
            "stage": stage_key,
            "questions": questions,
            "question_comment_id": comment_id,
            "asked_at": _dt.datetime.utcnow().isoformat() + "Z",
            "qa_rounds": qa_rounds,
        }
        self._save_checkpoint(result)
        console.print(f"  ⏸️  [yellow]Pipeline paused — waiting for human reply[/yellow]")

    def _save_files_locally(self, files: dict[str, str], project_name: str) -> None:
        """Save generated files to the local workspace directory."""
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in project_name.lower())
        project_dir = self.workspace_dir / safe
        project_dir.mkdir(parents=True, exist_ok=True)
        for filepath, content in files.items():
            full_path = project_dir / filepath
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")

    def _checkpoint_path(self, result: PipelineResult) -> Path:
        """Return the checkpoint file path for a given pipeline result."""
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (result.project_name or result.requirement[:40]).lower())
        return self.workspace_dir / safe / "checkpoint.json"

    def _save_checkpoint(self, result: PipelineResult) -> None:
        """Persist the current pipeline state to disk.

        Write is atomic (temp file → rename) to prevent a corrupted checkpoint
        if the process is interrupted mid-write. We also skip saving when
        completed_stages is empty — there is nothing useful to preserve and an
        empty checkpoint would shadow any existing good checkpoint at the same path.
        """
        if not result.completed_stages:
            return  # Nothing worth preserving; don't clobber an existing checkpoint.

        path = self._checkpoint_path(result)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(result.to_dict(), indent=2, ensure_ascii=False)

        # Write atomically: write to a sibling tmp file, then rename.
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".ckpt_", suffix=".json")
        try:
            os.write(fd, content.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp_path, path)  # atomic on POSIX

    def _load_checkpoint(self, requirement: str) -> Optional[PipelineResult]:
        """Load the best checkpoint matching this requirement.

        Searches all workspace subdirectories and picks the checkpoint with the
        most completed stages (so a partial bad run can never cause a rollback).
        Silently skips files that are missing, unreadable, or contain invalid JSON.
        """
        if not self.workspace_dir.exists():
            return None
        best: Optional[PipelineResult] = None
        for checkpoint_file in self.workspace_dir.glob("*/checkpoint.json"):
            try:
                data = json.loads(checkpoint_file.read_text(encoding="utf-8"))
                if data.get("requirement") != requirement:
                    continue
                stages = data.get("completed_stages") or []
                if not stages:
                    continue
                candidate = PipelineResult.from_dict(data)
                if best is None or len(candidate.completed_stages) > len(best.completed_stages):
                    best = candidate
            except Exception:
                continue
        return best

    def _clear_checkpoint(self, result: PipelineResult) -> None:
        """Delete the checkpoint file after a successful pipeline run."""
        path = self._checkpoint_path(result)
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass

    def _ensure_github_labels(self) -> None:
        """Create standard labels in the repo if they don't exist."""
        if not self.github:
            return
        labels = [
            {"name": "prd", "color": "0075ca", "description": "Product Requirements Document"},
            {"name": "requirements", "color": "e4e669", "description": "Requirements tracking"},
            {"name": "ai-generated", "color": "d93f0b", "description": "AI-generated content"},
        ]
        try:
            self.github.ensure_labels(labels)
        except Exception:
            pass  # Label setup is non-critical

    def _finish(self, result: PipelineResult, start_time: float) -> PipelineResult:
        """Print summary, save memory, and return the final result."""
        result.duration_seconds = time.time() - start_time

        # ── Save run summary to long-term memory ──────────────────────────────
        active_repo = (self.target_github.repo if self.target_github else
                       (self.github.repo if self.github else "local"))
        try:
            summary_text = self.summariser.summarise(
                repo=active_repo,
                requirement=result.requirement,
                prd=result.prd,
                design=result.design,
                review=result.review,
            )
            self.memory.save(repo=active_repo, summary=summary_text, mode="feature")
            # Save markdown copy to workspace
            mem_file = self.workspace_dir / "memory.md"
            with open(mem_file, "a", encoding="utf-8") as f:
                import datetime
                f.write(f"\n\n---\n## {datetime.date.today()} — {result.project_name or 'run'}\n")
                f.write(summary_text)
            console.print("  🧠 [dim]Memory saved[/dim]")

            # Auto-consolidate if enough run-tier entries have accumulated
            self._maybe_consolidate(active_repo)
        except Exception as exc:
            console.print(f"  [yellow]⚠️  Memory save failed: {exc}[/yellow]")

        # ── Update memory bank in target repo ─────────────────────────────────
        if self.target_github and getattr(result, "branch", None):
            try:
                current_bank = self._read_memory_bank(self.target_github)
                # Resolve model for memory_bank_updater from model_overrides
                mb_model = self.model_overrides.get("memory_bank_updater", self.model)
                updater = MemoryBankUpdaterAgent(
                    model=mb_model,
                    github_token=self._github_token,
                )
                summary_for_bank = locals().get("summary_text", getattr(result, "requirement", "")[:200])
                updated_bank = updater.update(current_bank, summary_for_bank)
                self._write_memory_bank(updated_bank, self.target_github, result.branch)
            except Exception as exc:
                console.print(f"  [yellow]⚠️  Memory bank update failed: {exc}[/yellow]")

        # Summary table
        table = Table(title="Pipeline Summary", show_header=True, header_style="bold magenta")
        table.add_column("Stage", style="cyan")
        table.add_column("Output")

        table.add_row("Project", result.project_name or "—")
        table.add_row("PRD", f"{len(result.prd)} chars" if result.prd else "—")
        if result.prd_verdict:
            table.add_row("PRD verdict", result.prd_verdict)
        table.add_row("Modules", str(len(result.modules)))
        if result.design_verdict:
            table.add_row("Design verdict", result.design_verdict)
        table.add_row("Code files", str(len(result.all_files)))
        table.add_row("Test files", str(len(result.test_files)))
        if result.qa_acceptance_criteria:
            table.add_row("Acceptance criteria", str(len(result.qa_acceptance_criteria)))
        table.add_row("Review verdict", result.verdict or "—")
        if result.tests_passed is True:
            table.add_row("Tests", "✅ Passed")
        elif result.tests_passed is False:
            table.add_row("Tests", "❌ Failed (see PR comment for details)")
        else:
            table.add_row("Tests", "—")
        if result.deploy_tests_passed is True:
            table.add_row("Deploy tests", "✅ Passed")
        elif result.deploy_tests_passed is False:
            table.add_row("Deploy tests", "❌ Failed (see PR comment for details)")
        elif result.deploy_files:
            table.add_row("Deploy tests", "⏭️  Skipped (no Docker)")
        if result.issue_url:
            table.add_row("GitHub Issue", result.issue_url)
        if result.pr_url:
            table.add_row("Pull Request", result.pr_url)
        table.add_row("Duration", f"{result.duration_seconds:.1f}s")
        if result.errors:
            table.add_row("[red]Errors[/red]", "\n".join(result.errors))

        console.print(table)
        return result

    def _read_memory_bank(self, gh: "GitHubClient") -> dict[str, str]:
        """Read current memory bank files via GitHub API.

        Returns filename -> content for all 6 bank files.
        Files that don't exist yet return empty string (first run).
        """
        import base64

        bank_names = [
            "projectbrief.md", "productContext.md", "systemPatterns.md",
            "techContext.md", "activeContext.md", "progress.md",
        ]
        bank: dict[str, str] = {}
        for name in bank_names:
            try:
                file_data = gh._request("GET", f"/repos/{gh.repo}/contents/memory-bank/{name}")
                bank[name] = base64.b64decode(file_data["content"]).decode("utf-8")
            except Exception:
                bank[name] = ""
        return bank

    def _write_memory_bank(
        self,
        updated_bank: dict[str, str],
        gh: "GitHubClient",
        branch: str,
    ) -> None:
        """Commit updated memory bank files to the feature branch."""
        if not updated_bank or not branch:
            return
        for name, content in updated_bank.items():
            try:
                gh.commit_file(
                    f"memory-bank/{name}",
                    content,
                    f"memory: update {name} after pipeline run",
                    branch,
                )
                console.print(f"  🧠 [dim]Memory bank updated: {name}[/dim]")
            except Exception as exc:
                console.print(f"  [yellow]⚠️  Failed to update memory-bank/{name}: {exc}[/yellow]")

    # ──────────────────────────────────────────────────────────────────────────
    # TIERED MEMORY CONSOLIDATION
    # ──────────────────────────────────────────────────────────────────────────

    def _maybe_consolidate(self, repo: str) -> None:
        """Check thresholds and trigger monthly / quarterly consolidation if needed."""
        consolidator = MemoryConsolidatorAgent(model=self.model)

        if self.memory.needs_consolidation(repo):
            console.print("  🧠 [dim]Auto-consolidating monthly memory…[/dim]")
            try:
                self.memory.consolidate_monthly(
                    repo=repo,
                    llm_fn=consolidator.consolidate,
                )
                console.print("  🧠 [dim]Monthly snapshot saved[/dim]")
            except Exception as exc:
                console.print(f"  [yellow]⚠️  Monthly consolidation failed: {exc}[/yellow]")

        if self.memory.needs_quarterly(repo):
            console.print("  🧠 [dim]Auto-consolidating quarterly memory…[/dim]")
            try:
                self.memory.consolidate_quarterly(
                    repo=repo,
                    llm_fn=consolidator.consolidate,
                )
                console.print("  🧠 [dim]Quarterly snapshot saved[/dim]")
            except Exception as exc:
                console.print(f"  [yellow]⚠️  Quarterly consolidation failed: {exc}[/yellow]")

    # ──────────────────────────────────────────────────────────────────────────
    # REFACTOR / DREAM MODE
    # ──────────────────────────────────────────────────────────────────────────

    def refactor(self, repo: Optional[str] = None) -> dict:
        """Analyse the most recently generated code and open a cleanup PR.

        Reads workspace files, runs the RefactorAgent, re-writes changed files,
        and pushes a new refactor branch + PR to GitHub if configured.

        Args:
            repo: Optional target repo override (owner/name). Defaults to target_github.

        Returns:
            dict with keys: plan, changes, pr_url (or None if no GH).
        """
        import datetime

        active_repo = repo or (self.target_github.repo if self.target_github else
                               (self.github.repo if self.github else "local"))
        memory_context = self.memory.recall(active_repo)

        # ── Collect workspace code snapshot ───────────────────────────────────
        ws_files: dict[str, str] = {}
        for fp in self.workspace_dir.rglob("*"):
            if fp.is_file() and fp.suffix in {".py", ".js", ".ts", ".go", ".java", ".rb", ".cs"}:
                rel = str(fp.relative_to(self.workspace_dir))
                try:
                    ws_files[rel] = fp.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    pass

        if not ws_files:
            console.print("[yellow]⚠️  No code files found in workspace — nothing to refactor[/yellow]")
            return {"plan": "", "changes": {}, "pr_url": None}

        from agents.base_agent import BaseAgent
        code_snapshot = BaseAgent.truncate_files(ws_files, max_chars=20_000)
        snapshot_str = "\n\n".join(f"### {path}\n```\n{content}\n```" for path, content in code_snapshot.items())

        console.print(Panel.fit(
            f"[bold yellow]🌙 Dream / Refactor Mode[/bold yellow]\n"
            f"[dim]Analysing {len(code_snapshot)} files in {active_repo}[/dim]",
            border_style="yellow",
        ))

        # ── Analyse & plan ────────────────────────────────────────────────────
        plan = self.refactor_agent.analyse(
            code_snapshot=snapshot_str,
            memory_context=memory_context,
        )
        console.print("  ✅ Refactor plan complete")

        # ── Apply rewrites for files explicitly called out ────────────────────
        changed: dict[str, str] = {}
        for match in re.finditer(r"### File: `([^`]+)`.*?(?=### File:|$)", plan, re.DOTALL):
            file_path = match.group(1).strip()
            # Find matching workspace file (partial path ok)
            ws_match = next((k for k in ws_files if k.endswith(file_path) or file_path.endswith(k)), None)
            if ws_match:
                instructions = match.group(0)
                rewritten = self.refactor_agent.rewrite(
                    file_path=ws_match,
                    current_code=ws_files[ws_match],
                    fix_instructions=instructions,
                )
                changed[ws_match] = rewritten
                # Write back to workspace
                full_path = self.workspace_dir / ws_match
                full_path.write_text(rewritten, encoding="utf-8")

        console.print(f"  ✅ Rewrote {len(changed)} files")

        # ── Save memory entry for this refactor run ───────────────────────────
        self.memory.save(
            repo=active_repo,
            summary=f"[Refactor] {len(changed)} files cleaned up.\n\n{plan[:600]}",
            mode="refactor",
        )

        # ── Push refactor branch + PR ─────────────────────────────────────────
        pr_url = None
        gh = self.target_github or self.github
        if gh and changed:
            branch = f"refactor/agent-{datetime.date.today()}"
            try:
                default_sha = gh.get_default_branch_sha()
                gh.create_branch(branch, default_sha)
                for path, content in changed.items():
                    gh.commit_file(
                        branch=branch,
                        path=path,
                        content=content,
                        message=f"refactor: agent cleanup — {path}",
                    )
                pr = gh.create_pull_request(
                    title=f"🌙 Agent Refactor: {datetime.date.today()}",
                    body=f"## AI Refactor Pass\n\nFiles changed: {len(changed)}\n\n{plan[:3000]}",
                    head=branch,
                    base="main",
                )
                pr_url = pr.get("html_url", "")
                console.print(f"  🔀 Refactor PR: [link]{pr_url}[/link]")
            except Exception as exc:
                console.print(f"  [yellow]⚠️  PR creation failed: {exc}[/yellow]")

        return {"plan": plan, "changes": changed, "pr_url": pr_url}

