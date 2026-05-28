"""
Orchestrator: runs the full PM → Architect → Engineer×N → Reviewer → QA pipeline.
Manages artifact passing, logging, and optional GitHub integration.
"""
from __future__ import annotations

import collections
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    ContractValidatorAgent,
    DeploymentTesterAgent,
    EngineerAgent,
    PMReviewerAgent,
    ProductManagerAgent,
    QAEngineerAgent,
    QAPlannerAgent,
    TDDReviewerAgent,
)
from agents.junior_engineer import JuniorEngineerAgent
from agents.senior_engineer import SeniorEngineerAgent
from agents.tier_reviewer import TierReviewerAgent
from agents.tier_utils import apply_tier_overrides
from agents.summariser import SummaryAgent
from agents.memory_bank_updater import MemoryBankUpdaterAgent
from agents.refactor_agent import RefactorAgent
from agents.memory_consolidator import MemoryConsolidatorAgent
from agents.conflict_resolver import ConflictResolverAgent, PRContext
from agents.deploy_backends import build_deploy_backend
from agents.news_writer import NewsWriterAgent
from agents.news_editor import NewsEditorAgent
from agents.news_reviewer import NewsReviewerAgent
from agents.translator import TranslatorAgent
from framework_docs import FrameworkDocsLoader
from github_client import GitHubClient, parse_target_repo
from config_schema import AppConfig as _AppConfig
from pydantic import ValidationError as _PydanticValidationError
from repo_context import RepoContext, RepoContextLoader, RepoAutoIndexer
from memory_store import MemoryStore
from skills_loader import SkillContext, SkillLoader
from test_fix_loop import TestFixLoopMixin
from tools import builtin_tools, CombinedToolRegistry, MCPToolRegistry
from agents.token_ledger import TokenLedger, BudgetExceededError, current_stage, get_ledger, set_ledger
from utils import sanitise as _sanitise, deep_merge as _deep_merge
from core.errors import PipelineError as _PipelineError
from core.exceptions import ConfigurationError

try:
    from agents.learning_agent import LearningAgent as LearningAgent  # noqa: F401
except ImportError:
    LearningAgent = None  # type: ignore

log = logging.getLogger(__name__)

console = Console()

# ── Zombie thread tracking (T5-A) ────────────────────────────────────────────
import time as _time  # alias to avoid name collision with user-code 'time'

_leaked_thread_lock: threading.Lock = threading.Lock()
_leaked_thread_labels: collections.deque = collections.deque(maxlen=1000)
_leaked_thread_total: int = 0  # cumulative count; never saturates at deque's maxlen


def _record_leaked_thread(stage_name: str) -> None:
    """Track a zombie thread spawned by a timed-out stage."""
    global _leaked_thread_total
    label = f"{stage_name}@{_time.monotonic():.0f}"
    with _leaked_thread_lock:
        _leaked_thread_labels.append(label)
        _leaked_thread_total += 1
        window_count = len(_leaked_thread_labels)
        total_count = _leaked_thread_total
    log.warning(
        "Stage %r timed out — leaked background thread still running. "
        "Zombie threads this window (last 1000): %d, total (cumulative): %d",
        stage_name,
        window_count,
        total_count,
    )


def get_leaked_thread_count() -> int:
    """Return the cumulative number of zombie threads created by timed-out stages.

    Unlike ``len(_leaked_thread_labels)`` (which saturates at the deque's
    ``maxlen`` of 1000), this counter keeps growing so callers can detect
    ongoing leakage beyond the rolling window.
    """
    with _leaked_thread_lock:
        return _leaked_thread_total


# ─────────────────────────────────────────────────────────────────────────────

# Parallel stage concurrency cap (T5-A)
try:
    MAX_PARALLEL_STAGES: int = max(1, int(os.getenv("AI_MAX_PARALLEL_STAGES", "8")))
except (ValueError, TypeError):
    MAX_PARALLEL_STAGES = 8

# Marker embedded in bot comments to acknowledge processed update-branch directives
_UPDATE_BRANCH_MARKER = "<!-- auto-update-branch -->"

# Valid values for a loop block's 'until' verdict field.
# Typos at load time raise ValueError rather than silently looping forever.
VALID_LOOP_VERDICTS: frozenset[str] = frozenset({"APPROVED", "NEEDS_REVISION"})


def _parse_explicit_skills(text: str) -> list[str]:
    """Parse 'skills: name1, name2' directive from issue body."""
    m = re.search(r"^skills\s*:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    if not m:
        return []
    return [s.strip() for s in m.group(1).split(",") if s.strip()]


# Regex for detecting merge directives in PR feedback.
_MERGE_DIRECTIVE_RE = re.compile(
    r"merge-branch:\s*(\S+)"              # explicit: merge-branch: <branch>
    r"|merge\s+branch\s+`([^`]+)`"        # backtick: merge branch `<branch>`
    r"|incorporate.*?branch\s+`([^`]+)`"  # incorporate: from branch `<branch>`
    r"|merge\s+from\s+PR\s+#(\d+)",       # PR number: merge from PR #N
    re.IGNORECASE,
)


# Diagnosis system prompt overlay used by the bug-fix pipeline.
_DIAGNOSIS_PREFIX = """
You are performing a **bug diagnosis**, not a new system design.

Given:
- A bug report (title + description from a GitHub Issue)
- The existing codebase files provided

Your job is to:
1. Identify the most likely root cause
2. Pinpoint the exact file(s) and function(s) that need changing
3. Describe the minimal fix required — do NOT redesign the whole system
4. List only the module(s) that need to be touched

Output format:
```markdown
# Bug Diagnosis: [Bug Title]

## Root Cause
[Concise explanation of why the bug occurs]

## Affected Files
- `path/to/file.py` — [what needs to change]

## Fix Strategy
[Step-by-step description of the minimal fix]

## Implementation Modules
1. **[module_name]**: [file to fix] — [what to change]
```
"""


class ClarificationNeeded(Exception):
    """Raised by PM or Architect agents when requirements are ambiguous.

    The orchestrator catches this, posts a GitHub comment with the questions,
    saves a checkpoint, and pauses the pipeline (agent-waiting label).
    """

    def __init__(self, questions: list[str]) -> None:
        self.questions = questions
        super().__init__(f"Clarification needed: {len(questions)} question(s)")


class _ShutdownRequested(BaseException):
    """Raised internally when a graceful shutdown is requested during a pipeline run.

    Inherits from BaseException (not Exception) so it propagates through broad
    ``except Exception`` handlers in stage loops without being accidentally swallowed.
    The orchestrator's ``run()`` method catches this at the top level and returns
    the current (partial) PipelineResult without marking the interrupted stage as
    completed.
    """


@dataclass
class ProgressStage:
    """One stage entry in the pipeline progress tracker."""
    key: str
    label: str
    status: str = "pending"   # pending | in_progress | done | failed | skipped
    error: str = ""           # populated by mark_failed()


class ProgressTracker:
    """Posts and updates a pipeline-progress comment on a GitHub issue.

    Modes:
        summary  — one comment, deleted and re-posted on every state change.
        verbose  — individual comment per state transition (no deletes).
        off      — all methods are no-ops.
    """

    _VALID_MODES: frozenset = frozenset({"summary", "verbose", "off"})

    _ICONS = {
        "pending":     "⬜",
        "in_progress": "🔄",
        "done":        "✅",
        "failed":      "❌",
        "skipped":     "⏭️",
    }

    def __init__(self, github, issue_number: Optional[int], mode: str) -> None:
        if mode not in self._VALID_MODES:
            raise ValueError(f"ProgressTracker: invalid mode {mode!r}; expected one of {sorted(self._VALID_MODES)}")
        self.github = github
        self.issue_number = issue_number
        self.mode = mode          # "summary" | "verbose" | "off"
        self.stages: list[ProgressStage] = []
        self.comment_id: Optional[int] = None

    # ── Public API ────────────────────────────────────────────────────────

    def set_stages(self, stages: list[ProgressStage]) -> None:
        """Set the full ordered list of expected stages and post the initial comment."""
        self.stages = list(stages)
        if self.mode == "summary":
            self._post_summary()

    def add_stage(self, stage: ProgressStage) -> None:
        """Append a dynamic stage (e.g. revision rounds) and refresh the comment."""
        self.stages.append(stage)
        if self.mode == "summary":
            self._post_summary()

    def restore(self, comment_id: Optional[int]) -> None:
        """On checkpoint resume — reuse the existing comment_id without re-posting."""
        if comment_id:
            self.comment_id = comment_id

    def restore_stages(self, completed_keys: list) -> None:
        """Replay completed stages from a checkpoint in-memory without posting N times."""
        for stage in self.stages:
            if stage.key in completed_keys:
                stage.status = "done"
        if self.mode == "summary":
            self._post_summary()

    def mark_in_progress(self, key: str) -> None:
        """Mark a stage as in-progress."""
        self._set_status(key, "in_progress")
        if self.mode == "verbose":
            label = self._label(key)
            self._safe_post(f"🔄 **{label}** — starting…")

    def mark_done(self, key: str) -> None:
        """Mark a stage as done."""
        self._set_status(key, "done")
        if self.mode == "verbose":
            label = self._label(key)
            self._safe_post(f"✅ **{label}** — complete")

    def mark_failed(self, key: str, error: str = "") -> None:
        """Mark a stage as failed, with an optional error message."""
        self._set_status(key, "failed", error=error)
        if self.mode == "verbose":
            label = self._label(key)
            msg = f"❌ **{label}** — failed"
            if error:
                msg += f": {error}"
            self._safe_post(msg)

    def mark_skipped(self, key: str) -> None:
        """Mark a stage as skipped."""
        self._set_status(key, "skipped")
        if self.mode == "verbose":
            label = self._label(key)
            self._safe_post(f"⏭️ **{label}** — skipped")

    # ── Internals ─────────────────────────────────────────────────────────

    def _set_status(self, key: str, status: str, error: str = "") -> None:
        for stage in self.stages:
            if stage.key == key:
                stage.status = status
                if error:
                    stage.error = error
                if self.mode == "summary":
                    self._post_summary()
                return
        # Unknown key — ignore silently

    def _label(self, key: str) -> str:
        for stage in self.stages:
            if stage.key == key:
                return stage.label
        return key

    def _render(self) -> str:
        lines = ["## 🤖 Pipeline Progress\n"]
        for stage in self.stages:
            icon = self._ICONS.get(stage.status, "⬜")
            line = f"- {icon} {stage.label}"
            if stage.status == "failed" and stage.error:
                line += f" — {stage.error}"
            lines.append(line)
        return "\n".join(lines)

    def _post_summary(self) -> None:
        if not self.github or not self.issue_number:
            return
        self._safe_delete()
        resp = self._safe_add(self._render())
        if resp:
            self.comment_id = resp.get("id")

    def _safe_delete(self) -> None:
        if self.comment_id and self.github:
            try:
                self.github.delete_issue_comment(self.comment_id)
            except Exception as exc:
                log.warning("ProgressTracker: failed to delete comment %s: %s", self.comment_id, exc)

    def _safe_add(self, body: str) -> Optional[dict]:
        """Post a new comment, returning the response dict or None on error."""
        try:
            return self.github.add_issue_comment(self.issue_number, body)
        except Exception as exc:
            log.warning("ProgressTracker: failed to post comment: %s", exc)
            return None

    def _safe_post(self, body: str) -> None:
        """Verbose-mode single comment post."""
        if not self.github or not self.issue_number:
            return
        self._safe_add(body)


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
    errors: list["_PipelineError"] = field(default_factory=list)
    completed_stages: list[str] = field(default_factory=list)  # stages that finished OK
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )
    # Q&A clarification fields
    pending_clarification: Optional[dict] = None  # set while waiting for human reply
    clarification_history: list[dict] = field(default_factory=list)  # completed Q&A rounds
    # Test-fix retry tracking
    test_retry_count: int = 0
    test_fix_history: list[str] = field(default_factory=list)
    deploy_retry_count: int = 0
    deploy_fix_history: list[str] = field(default_factory=list)
    tdd_review_summary: str = ""
    # Validation gate fields (Accuracy M2)
    pipeline_label: str = "unknown"
    validation_attempts: int = 0
    validation_errors: list[str] = field(default_factory=list)
    pr_draft: bool = False
    # Bootstrap fields (Accuracy M4)
    bootstrap_agents_md: Optional[str] = None
    # Discussion stage outputs
    discussion_transcript: str = ""
    discussion_synthesis: str = ""
    # News article stage outputs
    article_draft: str = ""
    article: str = ""
    article_zh_hk: str = ""  # Written Cantonese translation
    article_zh_tw: str = ""  # Formal Traditional Chinese translation
    # News reviewer stage outputs
    article_reviewer_notes: str = ""   # last reviewer issue list (injected on retry)
    article_review_retry_count: int = 0  # total reviewer retries across all loops
    # Editorial triage stage outputs
    editorial_verdict: str = ""   # "PUBLISH" or "SKIP"
    editorial_notes: str = ""     # angle/focus for writer, or reason for skip
    triage_scope: str = ""        # injected from config; passed to discussion as context
    # PRD/Design revision loop tracking
    prd_revision_count: int = 0
    design_revision_count: int = 0
    prd_reviewer_draft: str = ""      # reviewer's suggested PRD (for PM.run_revision)
    design_reviewer_draft: str = ""   # reviewer's suggested design (for Architect.run_revision)
    last_verdict: str = ""
    """Set by reviewer stages inside a loop block; checked against loop_until."""
    next_label: Optional[str] = None
    """If set, the watcher will apply this label after completion to chain the next pipeline.
    Can be set explicitly by any stage (e.g. code_reviewer sets 'ai-fix' when changes requested).
    Also computed automatically by the watcher from chaining rules in config.yaml."""
    progress_comment_id: Optional[int] = None
    """GitHub comment ID of the progress tracker comment, for resuming from checkpoints."""
    run_id: str = ""
    total_cost_usd: float = 0.0
    token_usage: dict = field(default_factory=dict)
    # Contract validation fields
    naming_contract: str = ""
    contract_validation_passed: Optional[bool] = None
    contract_divergences: list[dict] = field(default_factory=list)

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
            "errors": [e.to_dict() for e in self.errors],
            "pending_clarification": self.pending_clarification,
            "clarification_history": self.clarification_history,
            "test_retry_count": self.test_retry_count,
            "test_fix_history": self.test_fix_history,
            "deploy_retry_count": self.deploy_retry_count,
            "deploy_fix_history": self.deploy_fix_history,
            "tdd_review_summary": self.tdd_review_summary,
            "prd_revision_count": self.prd_revision_count,
            "design_revision_count": self.design_revision_count,
            "prd_reviewer_draft": self.prd_reviewer_draft,
            "design_reviewer_draft": self.design_reviewer_draft,
            "design_output": self.design_output,
            "last_verdict": self.last_verdict,
            "next_label": self.next_label,
            "pipeline_label": self.pipeline_label,
            "validation_attempts": self.validation_attempts,
            "validation_errors": self.validation_errors,
            "pr_draft": self.pr_draft,
            "bootstrap_agents_md": self.bootstrap_agents_md,
            "discussion_transcript": self.discussion_transcript,
            "discussion_synthesis": self.discussion_synthesis,
            "article_draft": self.article_draft,
            "article": self.article,
            "article_zh_hk": self.article_zh_hk,
            "article_zh_tw": self.article_zh_tw,
            "article_reviewer_notes": self.article_reviewer_notes,
            "article_review_retry_count": self.article_review_retry_count,
            "editorial_verdict": self.editorial_verdict,
            "editorial_notes": self.editorial_notes,
            "triage_scope": self.triage_scope,
            "progress_comment_id": self.progress_comment_id,
            "run_id": self.run_id,
            "total_cost_usd": self.total_cost_usd,
            "token_usage": self.token_usage,
        }

    def add_error(self, error: "str | _PipelineError") -> None:
        """Add an error. Accepts a bare string (backwards compat) or a PipelineError."""
        if isinstance(error, str):
            error = _PipelineError(code="UNKNOWN", stage="unknown", message=error, severity="error")
        with self._lock:
            self.errors.append(error)

    def add_completed_stage(self, key: str) -> None:
        """Thread-safe append to completed_stages."""
        with self._lock:
            self.completed_stages.append(key)

    def has_fatal(self) -> bool:
        """Return True if any error has severity='fatal'."""
        return any(e.severity == "fatal" for e in self.errors)

    @classmethod
    def from_dict(cls, data: dict) -> "PipelineResult":
        r = cls(requirement=data.get("requirement", ""))
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
                    "tdd_review_summary",
                    "prd_revision_count", "design_revision_count",
                    "prd_reviewer_draft", "design_reviewer_draft",
                    "design_output", "last_verdict", "next_label",
                    "pipeline_label", "validation_attempts", "pr_draft",
                    "bootstrap_agents_md",
                    "discussion_transcript", "discussion_synthesis",
                    "article_draft", "article",
                    "article_zh_hk", "article_zh_tw",
                    "article_reviewer_notes", "article_review_retry_count",
                    "editorial_verdict", "editorial_notes", "triage_scope",
                    "progress_comment_id",
                    "run_id", "total_cost_usd", "token_usage"]:
            setattr(r, key, data.get(key, getattr(r, key)))
        # Deserialize errors from list of dicts to list of PipelineError instances.
        # Handle backward compat: old checkpoints may store errors as plain strings.
        def _to_pipeline_error(item) -> "_PipelineError":
            if isinstance(item, _PipelineError):
                return item
            if isinstance(item, dict):
                return _PipelineError(**item)
            return _PipelineError(code="UNKNOWN", stage="unknown", message=str(item), severity="error")

        r.errors = [_to_pipeline_error(item) for item in data.get("errors", [])]
        r.validation_errors = data.get("validation_errors", [])
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

    timeout_s: float | None = None
    """Per-stage timeout in seconds. None = no timeout (wait forever)."""

    loop_stages: list[str] = field(default_factory=list)
    """Stage names to run repeatedly. Non-empty = this is a loop block."""

    loop_max: int = 1
    """Maximum iterations for a loop block."""

    loop_until: str = ""
    """Verdict string that exits a loop block early (e.g. 'APPROVED')."""

    parallel_group: str | None = None
    """When non-None, consecutive stages sharing this group name run concurrently."""

    required_output_fields: list[str] = field(default_factory=list)
    """Fields that must be non-empty on PipelineResult after this stage completes.
    Empty list = no verification (default, backward-compatible)."""

    is_critical: bool = False
    """When True, this stage's circuit breaker state is checked by downstream stages.
    Downstream non-critical stages are skipped if any critical CB is open."""


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
        "contract_validate",
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
    # Class-level default so __new__-based stubs don't raise AttributeError
    # when __init__ is bypassed; __init__ overwrites this with an instance dict.
    _stage_timeouts: dict[str, float] | None = None

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
        ollama_api_key: Optional[str] = None,
        ollama_think: bool = False,
        ollama_preserve_thinking: bool = False,
        ollama_stream: bool = True,
        opencode_stream: bool = True,
        github_models_stream: bool = True,
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
        reviewer_max_retries: int = 2,
        framework_docs_loader: Optional["FrameworkDocsLoader"] = None,
        repo_context_loader: Optional["RepoContextLoader"] = None,
        llm_cfg: Optional[dict] = None,
        llm_fallbacks: Optional[list] = None,
        pipeline_mode: str = "standard",
        stage_skips: dict[str, bool] | None = None,
        pipeline_yaml_stages: "list | None" = None,
        progress_tracker_mode: str = "summary",
        tdd_commit_tests: bool = False,
        cost_tracking: dict | None = None,
        update_branch_enabled: bool = False,
        conflict_resolver_model: Optional[str] = None,
        deploy_cfg: dict | None = None,
        press_cfg: dict | None = None,
        raw_cfg: dict | None = None,
    ) -> None:
        self._init_core_attrs(
            model=model, num_engineers=num_engineers,
            num_junior_engineers=num_junior_engineers,
            num_senior_engineers=num_senior_engineers,
            junior_model=junior_model, senior_model=senior_model,
            tier_reviewer_model=tier_reviewer_model,
            junior_quality_gate=junior_quality_gate,
            junior_test_retries=junior_test_retries,
            tier_override_rules=tier_override_rules,
            senior_engineer_use_mcp=senior_engineer_use_mcp,
            junior_engineer_use_mcp=junior_engineer_use_mcp,
            branch_prefix=branch_prefix, workspace_dir=workspace_dir,
            stop_on_review_issues=stop_on_review_issues,
            model_overrides=model_overrides, use_github=use_github,
            github_repo=github_repo, github_token=github_token,
            ollama_url=ollama_url, ollama_api_key=ollama_api_key,
            ollama_think=ollama_think,
            ollama_preserve_thinking=ollama_preserve_thinking,
            ollama_stream=ollama_stream, opencode_stream=opencode_stream,
            github_models_stream=github_models_stream,
            max_revisions=max_revisions, max_prd_revisions=max_prd_revisions,
            max_design_revisions=max_design_revisions,
            stop_on_prd_issues=stop_on_prd_issues,
            stop_on_design_issues=stop_on_design_issues,
            max_test_retries=max_test_retries,
            max_deploy_retries=max_deploy_retries,
            reviewer_max_retries=reviewer_max_retries,
            skill_loader=skill_loader,
            framework_docs_loader=framework_docs_loader,
            repo_context_loader=repo_context_loader,
            press_cfg=press_cfg, raw_cfg=raw_cfg,
        )
        self._checkpoint_lock: threading.Lock = threading.Lock()

        self._init_tool_registries(mcp_servers)

        # Shared kwargs for all agents (kept for backward compat; tests check agent_kwargs)
        agent_kwargs: dict = {"github_token": github_token, "ollama_url": ollama_url,
                              "ollama_api_key": ollama_api_key,
                              "ollama_think": ollama_think, "ollama_preserve_thinking": ollama_preserve_thinking,
                              "ollama_stream": ollama_stream,
                              "opencode_stream": opencode_stream,
                              "github_models_stream": github_models_stream,
                              "nvidia_nim_api_key": nvidia_nim_api_key,
                              "nvidia_nim_base_url": nvidia_nim_base_url,
                              "retry_delay": retry_delay, "max_api_retries": max_api_retries,
                              "inter_call_delay": inter_call_delay}
        self.agent_kwargs = agent_kwargs

        # ── Global LLM config dict (used by _make_backend) ────────────────────
        self._init_llm_cfg(
            model=model, ollama_url=ollama_url,
            ollama_api_key=ollama_api_key, ollama_think=ollama_think,
            ollama_preserve_thinking=ollama_preserve_thinking,
            ollama_stream=ollama_stream, opencode_stream=opencode_stream,
            github_models_stream=github_models_stream,
            nvidia_nim_api_key=nvidia_nim_api_key,
            nvidia_nim_base_url=nvidia_nim_base_url,
            llm_fallbacks=llm_fallbacks, llm_cfg=llm_cfg,
        )

        self._init_standard_agents(agent_kwargs, deploy_cfg)
        self._init_tier_agents(agent_kwargs)
        self._init_support_agents(agent_kwargs)

        self._init_github(
            github_repo=github_repo,
            github_token=github_token,
            target_repo=target_repo,
        )
        self._init_pipeline_config(
            pipeline_mode=pipeline_mode,
            stage_skips=stage_skips,
            pipeline_yaml_stages=pipeline_yaml_stages,
            progress_tracker_mode=progress_tracker_mode,
            tdd_commit_tests=tdd_commit_tests,
            cost_tracking=cost_tracking,
            update_branch_enabled=update_branch_enabled,
            conflict_resolver_model=conflict_resolver_model,
        )
        self._init_health_and_signals()

    # ── Core attribute initialiser ────────────────────────────────────────────

    def _init_core_attrs(
        self,
        model: str,
        num_engineers: int,
        num_junior_engineers: int,
        num_senior_engineers: int,
        junior_model: Optional[str],
        senior_model: Optional[str],
        tier_reviewer_model: Optional[str],
        junior_quality_gate: bool,
        junior_test_retries: int,
        tier_override_rules: "list[dict] | None",
        senior_engineer_use_mcp: bool,
        junior_engineer_use_mcp: bool,
        branch_prefix: str,
        workspace_dir: str,
        stop_on_review_issues: bool,
        model_overrides: Optional[dict],
        use_github: bool,
        github_repo: Optional[str],
        github_token: Optional[str],
        ollama_url: str,
        ollama_api_key: Optional[str],
        ollama_think: bool,
        ollama_preserve_thinking: bool,
        ollama_stream: bool,
        opencode_stream: bool,
        github_models_stream: bool,
        max_revisions: int,
        max_prd_revisions: int,
        max_design_revisions: int,
        stop_on_prd_issues: bool,
        stop_on_design_issues: bool,
        max_test_retries: int,
        max_deploy_retries: int,
        reviewer_max_retries: int,
        skill_loader: Optional["SkillLoader"],
        framework_docs_loader: Optional["FrameworkDocsLoader"],
        repo_context_loader: Optional["RepoContextLoader"],
        press_cfg: Optional[dict],
        raw_cfg: Optional[dict],
    ) -> None:
        """Assign primary configuration attributes; normalise types and apply defaults."""
        self._press_cfg: dict = press_cfg or {}
        self._raw_cfg: dict = raw_cfg or {}
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
        self.ollama_api_key = ollama_api_key
        self.ollama_think = ollama_think
        self.ollama_preserve_thinking = ollama_preserve_thinking
        self.ollama_stream = ollama_stream
        self.opencode_stream = opencode_stream
        self.github_models_stream = github_models_stream
        self.max_revisions = max_revisions
        self.max_prd_revisions = max_prd_revisions
        self.max_design_revisions = max_design_revisions
        self.stop_on_prd_issues = stop_on_prd_issues
        self.stop_on_design_issues = stop_on_design_issues
        self.max_test_retries = max_test_retries
        self.max_deploy_retries = max_deploy_retries
        self._reviewer_max_retries = reviewer_max_retries
        self.skill_loader: Optional[SkillLoader] = skill_loader
        self.framework_docs_loader: FrameworkDocsLoader = framework_docs_loader or FrameworkDocsLoader(config={})
        self.repo_context_loader: Optional[RepoContextLoader] = repo_context_loader

    def _init_tool_registries(self, mcp_servers: "list[dict] | None") -> None:
        """Build MCP, RAG and Google Search tool registries; also initialises repo_auto_indexer."""
        # Combined tool registry (builtin + optional MCP)
        if mcp_servers:
            try:
                mcp_registry = MCPToolRegistry(mcp_servers)
                tool_registry = CombinedToolRegistry(builtin_tools, mcp_registry)
            except Exception as exc:
                log.warning("[orchestrator] MCP init failed: %s — continuing with builtin tools only", exc)
                tool_registry = builtin_tools
        else:
            tool_registry = builtin_tools
        self._tool_registry = tool_registry
        # RAG server (isolated from builtin tools for RAG-capable agents)
        rag_servers = [s for s in (mcp_servers or []) if s.get("name") == "rag"]
        try:
            rag_registry = MCPToolRegistry(rag_servers) if rag_servers else None
        except Exception as exc:
            log.warning("[orchestrator] RAG MCP init failed: %s — RAG disabled", exc)
            rag_registry = None
        self._rag_registry = rag_registry
        self.repo_auto_indexer = RepoAutoIndexer() if rag_registry else None

        # Google Search MCP (for news_reviewer etc.)
        search_servers = [s for s in (mcp_servers or []) if s.get("name") == "google_search"]
        try:
            search_registry = MCPToolRegistry(search_servers) if search_servers else None
        except Exception as exc:
            log.warning("[orchestrator] Google Search MCP init failed: %s — web search disabled", exc)
            search_registry = None
        self._search_registry = search_registry

    # ── LLM config + agent kwargs helpers ────────────────────────────────────

    def _init_llm_cfg(
        self,
        model: str,
        ollama_url: str,
        ollama_api_key: Optional[str],
        ollama_think: bool,
        ollama_preserve_thinking: bool,
        ollama_stream: bool,
        opencode_stream: bool,
        github_models_stream: bool,
        nvidia_nim_api_key: Optional[str],
        nvidia_nim_base_url: Optional[str],
        llm_fallbacks: Optional[list],
        llm_cfg: Optional[dict],
    ) -> None:
        """Build self._llm_cfg from params; deep-merge caller-supplied cfg."""
        self._llm_cfg: dict = {
            "model": model,
            "ollama_url": ollama_url,
            "ollama_api_key": ollama_api_key,
            "ollama_think": ollama_think,
            "ollama_preserve_thinking": ollama_preserve_thinking,
            "ollama_stream": ollama_stream,
            "opencode_stream": opencode_stream,
            "github_models_stream": github_models_stream,
        }
        if nvidia_nim_api_key is not None:
            self._llm_cfg["nvidia_nim_api_key"] = nvidia_nim_api_key
        if nvidia_nim_base_url is not None:
            self._llm_cfg["nvidia_nim_base_url"] = nvidia_nim_base_url
        if llm_fallbacks:
            self._llm_cfg["fallbacks"] = llm_fallbacks
        if llm_cfg:
            self._llm_cfg = _deep_merge(self._llm_cfg, llm_cfg)

    def _make_agent_kwargs(
        self, agent_name: str, model_fallback: Optional[str] = None
    ) -> dict:
        """Return ``{"llm": backend}`` for a named agent.

        Routes to :meth:`_make_backend_from_model` when *model_fallback* is given
        (tier agents whose model is resolved via team config), or to
        :meth:`_make_backend` for all other agents.
        """
        if model_fallback:
            backend = self._make_backend_from_model(model_fallback)
        else:
            backend = self._make_backend(agent_name)
        return {"llm": backend}

    def _init_standard_agents(
        self, agent_kwargs: dict, deploy_cfg: "dict | None"
    ) -> None:
        """Instantiate PM, news, architect, engineer, QA and deployment agents."""
        mk = self._make_agent_kwargs
        rag = self._rag_registry
        search = self._search_registry
        tools = self._tool_registry
        self.pm = ProductManagerAgent(**{**agent_kwargs, **mk("product_manager")})
        self.news_writer = NewsWriterAgent(tool_registry=search, **{**agent_kwargs, **mk("news_writer")})
        self.news_editor = NewsEditorAgent(**{**agent_kwargs, **mk("news_editor")})
        self.news_reviewer = NewsReviewerAgent(tool_registry=search, **{**agent_kwargs, **mk("news_reviewer")})
        self.translator = TranslatorAgent(**{**agent_kwargs, **mk("translator")})
        self.pm_reviewer = PMReviewerAgent(**{**agent_kwargs, **mk("pm_reviewer")})
        self.architect = ArchitectAgent(tool_registry=rag, **{**agent_kwargs, **mk("architect")})
        self.architect_reviewer = ArchitectReviewerAgent(**{**agent_kwargs, **mk("architect_reviewer")})
        self.engineer = EngineerAgent(tool_registry=rag, **{**agent_kwargs, **mk("engineer")})
        self.reviewer = CodeReviewerAgent(tool_registry=tools, **{**agent_kwargs, **mk("code_reviewer")})
        self.qa_planner = QAPlannerAgent(tool_registry=tools, **{**agent_kwargs, **mk("qa_planner")})
        self.qa = QAEngineerAgent(tool_registry=rag, **{**agent_kwargs, **mk("qa_engineer")})
        self.tdd_reviewer = TDDReviewerAgent(**{**agent_kwargs, **mk("tdd_reviewer")})
        self.contract_validator = ContractValidatorAgent(**{**agent_kwargs, **mk("contract_validator")})
        _deploy_cfg = deploy_cfg or {"mode": "docker"}
        self._deploy_cfg = _deploy_cfg
        _deploy_backend = build_deploy_backend(_deploy_cfg)
        self.deployment_tester = DeploymentTesterAgent(
            deploy_backend=_deploy_backend,
            deploy_config=_deploy_cfg,
            **{**agent_kwargs, **mk("deployment_tester")},
        )

    def _init_tier_agents(self, agent_kwargs: dict) -> None:
        """Instantiate junior/senior/tier-reviewer agents."""
        mk = self._make_agent_kwargs
        rag = self._rag_registry
        _junior_fallback = (
            None if "junior_engineer" in self.model_overrides
            else (self.junior_model or self.model)
        )
        _senior_fallback = (
            None if "senior_engineer" in self.model_overrides
            else (self.senior_model or self.model)
        )
        _tier_rev_fallback = (
            None if "tier_reviewer" in self.model_overrides
            else (self.tier_reviewer_model or self.junior_model or self.model)
        )
        self.junior_engineer = JuniorEngineerAgent(
            tool_registry=rag if self.junior_engineer_use_mcp else None,
            **{**agent_kwargs, **mk("junior_engineer", model_fallback=_junior_fallback)},
        )
        self.senior_engineer = SeniorEngineerAgent(
            tool_registry=rag if self.senior_engineer_use_mcp else None,
            **{**agent_kwargs, **mk("senior_engineer", model_fallback=_senior_fallback)},
        )
        self.tier_reviewer = TierReviewerAgent(
            **{**agent_kwargs, **mk("tier_reviewer", model_fallback=_tier_rev_fallback)},
        )

    def _init_support_agents(self, agent_kwargs: dict) -> None:
        """Instantiate summariser, refactor agent, memory store; snapshot original system prompts."""
        mk = self._make_agent_kwargs
        self.summariser = SummaryAgent(**{**agent_kwargs, **mk("summariser")})
        self.refactor_agent = RefactorAgent(**{**agent_kwargs, **mk("refactor_agent")})
        self.memory = MemoryStore(self.workspace_dir / "memory.db")
        self._original_system_prompts: dict = {
            agent: agent.system_prompt
            for agent in (
                self.pm, self.news_writer, self.news_editor, self.news_reviewer,
                self.pm_reviewer, self.architect, self.architect_reviewer,
                self.engineer, self.junior_engineer, self.senior_engineer,
                self.tier_reviewer,
                self.reviewer, self.qa_planner, self.qa, self.tdd_reviewer, self.deployment_tester,
            )
            if agent is not None
        }

    def _init_github(
        self,
        github_repo: Optional[str],
        github_token: Optional[str],
        target_repo: Optional[str],
    ) -> None:
        """Create tracker and target GitHubClient instances."""
        self.github: Optional[GitHubClient] = None
        if self.use_github and github_repo:
            self.github = GitHubClient(repo=github_repo, github_token=github_token)
            self._ensure_github_labels()
        self.target_github: Optional[GitHubClient] = None
        if target_repo and target_repo != github_repo:
            self.target_github = GitHubClient(repo=target_repo, github_token=github_token)
        else:
            self.target_github = self.github

    def _init_pipeline_config(
        self,
        pipeline_mode: str,
        stage_skips: "dict[str, bool] | None",
        pipeline_yaml_stages: "list | None",
        progress_tracker_mode: str,
        tdd_commit_tests: bool,
        cost_tracking: "dict | None",
        update_branch_enabled: bool,
        conflict_resolver_model: Optional[str],
    ) -> None:
        """Assign pipeline-mode flags, cost tracking and stage-timeout config."""
        self._mode: str = pipeline_mode
        self._stage_skips: dict[str, bool] = stage_skips or {}
        self._pipeline_yaml_stages: "list | None" = pipeline_yaml_stages
        self._discussions_dir: Path = Path(__file__).parent / "discussions"
        self.progress_tracker_mode: str = progress_tracker_mode
        self.tdd_commit_tests: bool = tdd_commit_tests
        self._cost_tracking: dict = cost_tracking or {}
        self._update_branch_enabled: bool = update_branch_enabled
        self.conflict_resolver_model: Optional[str] = conflict_resolver_model
        ct = self._cost_tracking
        if ct.get("enabled", False):
            max_cost = None
            if ct.get("max_cost_usd") is not None:
                try:
                    max_cost = float(ct["max_cost_usd"])
                except (TypeError, ValueError):
                    pass
            ledger = TokenLedger(pricing=ct.get("pricing", {}), max_cost_usd=max_cost)
            set_ledger(ledger)
        self._stage_timeouts: dict[str, float] = {}
        _pipeline_cfg: dict = {}
        if hasattr(self, "_cfg"):
            _pipeline_cfg = self._cfg.get("pipeline", {}) or {}
        for _stage_name, _secs in (_pipeline_cfg.get("stage_timeouts") or {}).items():
            try:
                self._stage_timeouts[_stage_name] = float(_secs)
            except (TypeError, ValueError):
                pass

    def _init_health_and_signals(self) -> None:
        """Set up AgentHealthMonitor and graceful shutdown signal handlers."""
        from core.agent_health import AgentHealthMonitor
        self._agent_health = AgentHealthMonitor(failure_threshold=3)
        self._shutdown_event = threading.Event()

        def _handle_shutdown(signum, frame) -> None:
            self._shutdown_event.set()

        if threading.current_thread() is threading.main_thread():
            import signal as _signal
            _signal.signal(_signal.SIGTERM, _handle_shutdown)
            _signal.signal(_signal.SIGINT, _handle_shutdown)

    def _resolve_agent_model(self, agent_name: str) -> str:
        """Return the model string for *agent_name*, falling back to ``self.model``.

        Handles both string overrides (model name) and dict overrides
        (full per-agent settings with a ``"model"`` key).
        """
        _default_model = getattr(self, "model", "gpt-4.1")
        override = getattr(self, "model_overrides", {}).get(agent_name, _default_model)
        if isinstance(override, dict):
            return override.get("model", _default_model)
        return override

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
            "claude-", "dashscope/", "mimo/",
        )
        # Route to GitHub Models for bare names OR unknown-prefix names
        # (e.g. "openai/gpt-4.1", "meta/llama-3.1-405b-instruct").
        use_factory = ("/" not in model) or any(
            model.startswith(p) for p in _FACTORY_PREFIXES
        )

        if not use_factory:
            from agents.backends.github_models import GitHubModelsBackend
            primary = GitHubModelsBackend(
                model=model,
                github_token=self._github_token,
                stream=cfg.get("github_models_stream", True),
            )
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
            if cfg.get("ollama_api_key"):
                factory_cfg["api_key"] = cfg["ollama_api_key"]
        elif model.startswith("nvidia-nim/"):
            if cfg.get("nvidia_nim_api_key"):
                factory_cfg["nvidia_nim_api_key"] = cfg["nvidia_nim_api_key"]
            if cfg.get("nvidia_nim_base_url"):
                factory_cfg["nvidia_nim_base_url"] = cfg["nvidia_nim_base_url"]
        elif model.startswith("dashscope/"):
            if cfg.get("dashscope_api_key"):
                factory_cfg["dashscope_api_key"] = cfg["dashscope_api_key"]
            if cfg.get("dashscope_url"):
                factory_cfg["dashscope_url"] = cfg["dashscope_url"]
            factory_cfg["think"] = cfg.get("dashscope_think", False)
            factory_cfg["preserve_thinking"] = cfg.get("dashscope_preserve_thinking", False)
            factory_cfg["stream"] = cfg.get("dashscope_stream", True)
        elif model.startswith("mimo/"):
            if cfg.get("mimo_api_key"):
                factory_cfg["mimo_api_key"] = cfg["mimo_api_key"]
            if cfg.get("mimo_url"):
                factory_cfg["mimo_url"] = cfg["mimo_url"]
            factory_cfg["stream"] = cfg.get("mimo_stream", True)
            if "mimo_think" in cfg:
                factory_cfg["mimo_think"] = cfg["mimo_think"]
        elif model.startswith("opencode-go/") or model.startswith("opencode-zen/"):
            factory_cfg["stream"] = cfg.get("opencode_stream", True)
        # opencode/ (bare prefix) is a subprocess CLI backend that has no stream parameter; no translation needed.
        # All other backends (anthropic, copilot) use env-var auth and need no extra config keys.

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
        # Validate schema — raises pydantic.ValidationError with field-level detail on bad config
        # Validate AFTER merging local override so the effective config is checked
        local_path = Path(config_path).parent / "config.local.yaml"
        if local_path.exists():
            with open(local_path, encoding="utf-8") as lf:
                local_cfg = yaml.safe_load(lf) or {}
            cfg = _deep_merge(cfg, local_cfg)
        try:
            _AppConfig.model_validate(cfg)
        except _PydanticValidationError as exc:
            raise ValueError(f"Invalid config ({config_path}): {exc}") from exc

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
            ollama_api_key=llm.get("ollama_api_key"),
            ollama_think=llm.get("ollama_think", False),
            ollama_preserve_thinking=llm.get("ollama_preserve_thinking", False),
            ollama_stream=llm.get("ollama_stream", True),
            opencode_stream=llm.get("opencode_stream", True),
            github_models_stream=llm.get("github_models_stream", True),
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
            reviewer_max_retries=pipeline.get("reviewer_max_retries", 2),
            framework_docs_loader=framework_docs_loader,
            repo_context_loader=repo_context_loader,
            llm_fallbacks=llm.get("fallbacks") or None,
            pipeline_mode=pipeline_mode,
            stage_skips=stage_skips,
            pipeline_yaml_stages=pipeline_yaml_stages,
            progress_tracker_mode=pipeline.get("progress_tracker", "summary"),
            tdd_commit_tests=pipeline.get("tdd_commit_tests", False),
            cost_tracking=cfg.get("cost_tracking", {}),
            deploy_cfg=cfg.get("deploy", {"mode": "docker"}),
            press_cfg=cfg.get("press", {}),
            raw_cfg=cfg,
        )

    # ── Revision helpers ──────────────────────────────────────────────────────

    # ── Bug-fix stages (absorbed from bug_fix_orchestrator) ────────────────

    def _stage_diagnose(self, result: "PipelineResult") -> None:
        """Diagnose a bug from the trigger issue body and existing repo files.

        Sets ``result.design`` to the diagnosis Markdown so downstream
        stages (engineer/test_fix) see the fix plan as their design doc.
        """
        from agents import ArchitectAgent

        body = (result.requirement or "").strip()
        existing_files = getattr(result, "existing_files", {}) or {}
        files_section = ""
        if existing_files:
            files_section = "\n\n## Existing Files\n" + "\n".join(
                f"### `{p}`\n```\n{c[:6000]}\n```" for p, c in existing_files.items()
            )

        # Reuse the orchestrator's already-constructed architect agent if available;
        # otherwise build a fresh one. Either way overlay the diagnosis prefix.
        arch = getattr(self, "architect", None)
        if arch is None:
            arch = ArchitectAgent(
                model=self.model,
                github_token=self._github_token,
                ollama_url=self.ollama_url,
            )
        original_prompt = arch.system_prompt
        try:
            arch.system_prompt = _DIAGNOSIS_PREFIX + "\n\n" + original_prompt
            arch_result = arch.run(
                prd=body + files_section,
                project_name=f"Bug Fix: {result.project_name or 'issue'}",
            )
        finally:
            arch.system_prompt = original_prompt

        result.design = arch_result.get("design", "")
        result.modules = arch_result.get("modules", []) or []

    def _stage_bug_fix(self, result: "PipelineResult") -> None:
        """Apply the bug fix using the engineer agent against existing files.

        By this point ``result.design`` holds the diagnosis and the engineer
        will produce patches against the existing files.
        """
        return self._stage_engineer(result)

    # ── Documentation stages (absorbed from doc_orchestrator) ──────────────

    def _stage_doc_generate(self, result: "PipelineResult") -> None:
        """Generate documentation files using the documentation agent."""
        from agents import DocumentationAgent

        gh = self.target_github or self.github
        if gh is None:
            result.add_error(
                "doc_generate requires a GitHub connection but none is available "
                "(hint: do not use --no-github with the ai-docs pipeline)"
            )
            return
        body = (result.requirement or "").strip()
        agent = DocumentationAgent(
            model=self.model,
            github_token=self._github_token,
            ollama_url=self.ollama_url,
        )
        file_writes = agent.run(
            issue_title=result.project_name or f"docs-{result.issue_number or ''}",
            issue_body=body,
            github_client=gh,
        ) or []
        # Store as files dict so the standard commit/PR helpers can pick them up
        for write in file_writes:
            path = write.get("path") or ""
            content = write.get("content") or ""
            if path:
                result.all_files[path] = content

    def _stage_doc_commit_pr(self, result: "PipelineResult") -> None:
        """Commit doc files and open a PR — uses the same path as feature pipeline."""
        if not getattr(result, "all_files", None):
            return
        self._commit_and_open_pr(
            result,
            branch_prefix="docs/agent",
            title_prefix="docs",
            body_header="## 📚 Documentation Update",
            commit_msg_prefix="docs",
        )

    # ── PR/Marketing Campaign pipeline stages ─────────────────────────────

    def _stage_pr_analyst(self, result: "PipelineResult") -> None:
        """Run the PR Analyst agent to produce structured research from the campaign brief."""
        from agents.pr_analyst import PRAnalystAgent

        agent = PRAnalystAgent(
            model=self._resolve_agent_model("pr_analyst"),
            github_token=self._github_token,
            ollama_url=self.ollama_url,
            tool_registry=getattr(self, "_search_registry", None) or self._rag_registry,
        )
        context = {
            "issue_body": result.requirement or "",
            "issue_number": result.issue_number,
        }
        updated = agent.run(context)
        setattr(result, "pr_analyst_output", updated.get("pr_analyst"))

    def _stage_pr_creative(self, result: "PipelineResult") -> None:
        """Run the PR Creative agent to generate campaign concepts from analyst research."""
        from agents.pr_creative import PRCreativeAgent

        analyst_output = getattr(result, "pr_analyst_output", None)
        if not analyst_output:
            result.add_error("pr_creative stage: missing pr_analyst_output from previous stage")
            return

        agent = PRCreativeAgent(
            model=self._resolve_agent_model("pr_creative"),
            github_token=self._github_token,
            ollama_url=self.ollama_url,
            tool_registry=self._rag_registry,
        )
        context = {
            "pr_analyst": analyst_output,
        }
        updated = agent.run(context)
        setattr(result, "pr_creative_output", updated.get("pr_creative"))

    def _stage_pr_proposal(self, result: "PipelineResult") -> None:
        """Run the PR Proposal agent to assemble and submit the campaign proposal PR."""
        from agents.pr_proposal import PRProposalAgent

        analyst_output = getattr(result, "pr_analyst_output", None)
        creative_output = getattr(result, "pr_creative_output", None)

        if not analyst_output or not creative_output:
            result.add_error(
                "pr_proposal stage: missing analyst or creative output from previous stages"
            )
            return

        gh = self.target_github or self.github
        agent = PRProposalAgent(
            model=self._resolve_agent_model("pr_proposal"),
            github_token=self._github_token,
            ollama_url=self.ollama_url,
            tool_registry=self._rag_registry,
        )
        context = {
            "pr_analyst": analyst_output,
            "pr_creative": creative_output,
            "issue_number": result.issue_number,
            "github_client": gh,
        }
        updated = agent.run(context)
        proposal = updated.get("pr_proposal", {})
        setattr(result, "pr_proposal_output", proposal)
        if proposal.get("pr_url"):
            logger.info("Campaign proposal PR opened: %s", proposal["pr_url"])
        if proposal.get("pr_url"):
            result.pr_url = proposal["pr_url"]
        if proposal.get("pr_number"):
            result.pr_number = proposal["pr_number"]
        if proposal.get("branch_name"):
            result.branch = proposal["branch_name"]

    def _stage_validation_gate(self, result: "PipelineResult") -> None:
        """Validate generated files before opening a PR.

        Runs syntax check (py_compile) then lint (ruff F,E errors only) on all
        .py files in result.all_files. On failure, if validation_attempts < 2,
        appends errors to result.validation_errors for the re-prompt loop.
        If validation_attempts >= 2, marks result.pr_draft = True so the PR
        is opened as a draft with the needs-human-fix label.
        """
        import py_compile
        import subprocess
        import sys
        import tempfile
        import os

        errors: list[str] = []
        py_files = {p: c for p, c in (result.all_files or {}).items() if p.endswith(".py")}

        if not py_files:
            return  # nothing to validate

        with tempfile.TemporaryDirectory(prefix="validation_gate_") as tmpdir:
            # Write files to temp dir
            for rel_path, content in py_files.items():
                safe_rel = os.path.normpath(rel_path)
                if safe_rel.startswith("..") or os.path.isabs(safe_rel):
                    log.warning("validation_gate: skipping unsafe path %r", rel_path)
                    continue
                dest = os.path.join(tmpdir, safe_rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "w") as f:
                    f.write(content)

            # Step 1: syntax check
            for rel_path in py_files:
                abs_path = os.path.join(tmpdir, rel_path)
                try:
                    py_compile.compile(abs_path, doraise=True)
                except py_compile.PyCompileError as e:
                    errors.append(f"SyntaxError in {rel_path}: {e}")

            # Step 2: lint (ruff F + E codes — errors and undefined names only)
            if not errors:
                try:
                    proc = subprocess.run(
                        [sys.executable, "-m", "ruff", "check", "--select", "F,E", "--output-format", "concise", tmpdir],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if proc.returncode != 0:
                        lint_output = proc.stdout.replace(tmpdir + "/", "").replace(tmpdir + os.sep, "")
                        errors.extend([
                            line for line in lint_output.splitlines()
                            if line.strip() and not line.startswith("Found")
                        ])
                except FileNotFoundError:
                    log.warning("ruff not found — skipping lint check in validation_gate")
                except subprocess.TimeoutExpired:
                    log.warning("ruff timed out in validation_gate — skipping lint")

        if not errors:
            return  # all good

        result.validation_errors = errors

        result.add_error(_PipelineError(
            code="VALIDATION_FAILED",
            stage="validation_gate",
            message=f"Validation failed with {len(errors)} error(s): {'; '.join(errors[:3])}",
            severity="warning",
        ))

        if result.validation_attempts >= 2:
            result.pr_draft = True
            # Convert existing PR to draft if already open
            if result.pr_number and getattr(self, "target_github", None):
                try:
                    self.target_github.convert_pull_request_to_draft(result.pr_number)
                    log.info("validation_gate: converted PR #%d to draft", result.pr_number)
                except Exception as e:
                    log.warning("validation_gate: failed to convert PR to draft: %s", e)
            log.warning(
                "validation_gate: %d errors after %d attempts — marking as draft PR",
                len(errors), result.validation_attempts,
            )
            # Trigger LearningAgent to write anti-patterns from these errors
            try:
                from agents.failure_record import FailureRecord
                from datetime import datetime
                target_repo = getattr(self.target_github, "repo", None) if getattr(self, "target_github", None) else None
                failure = FailureRecord(
                    agent_role="engineer",
                    error="\n".join(errors[:5]),
                    fix="Human review required — see PR draft",
                    pipeline=result.pipeline_label,
                    timestamp=datetime.utcnow().isoformat(),
                    target_repo=target_repo,
                )
                if LearningAgent is not None:
                    learning_agent = LearningAgent(
                        model=self.model,
                        github_token=self._github_token,
                        ollama_url=getattr(self, "ollama_url", None),
                    )
                    learning_agent.run(failure)
            except Exception as e:
                log.warning("LearningAgent failed to run: %s", e)
        else:
            result.validation_attempts += 1
            log.warning(
                "validation_gate: %d errors on attempt %d — errors stored for re-prompt",
                len(errors), result.validation_attempts,
            )

    # ── Shared commit + PR helper (extracted from doc_orchestrator) ────────

    def _stage_bootstrap_patterns(self, result: "PipelineResult") -> None:
        """Generate .github/copilot-instructions.md for the target repo.

        Uses self.target_github (set when 'Target repo: owner/repo' appears in trigger issue).
        Commits the generated file directly to the target repo's default branch.
        """
        if not self.target_github:
            result.add_error(_PipelineError(
                code="BOOTSTRAP_NO_TARGET",
                stage="bootstrap_patterns",
                message="bootstrap_patterns: no target repo set — add 'Target repo: owner/repo' to trigger issue",
                severity="fatal",
            ))
            return

        from agents.bootstrap_patterns_agent import BootstrapPatternsAgent
        agent = BootstrapPatternsAgent(
            model=self.model,
            github_token=self._github_token,
            ollama_url=self.ollama_url,
            tool_registry=getattr(self, "_rag_registry", None),
        )
        agents_md = agent.run(self.target_github, commit=True)
        result.bootstrap_agents_md = agents_md
        result.add_completed_stage("bootstrap_patterns")

    def _stage_discuss(self, result: "PipelineResult", config_path: str) -> None:
        """Run a discussion stage from a preset config file."""
        if not Path(config_path).is_file():
            result.add_error(_PipelineError(
                code="DISCUSS_CONFIG_MISSING",
                stage="discuss",
                message=f"_stage_discuss: preset config not found: {config_path}",
                severity="fatal",
            ))
            return
        from agents.discussion_agent import DiscussionAgent
        _overrides = getattr(self, "model_overrides", {})
        _disc_model = self._resolve_agent_model("discussion")
        _llm_cfg = getattr(self, "_llm_cfg", {})
        agent = DiscussionAgent.from_file(
            config_path=config_path,
            model=_disc_model,
            github_token=self._github_token,
            ollama_url=self.ollama_url,
            tool_registry=getattr(self, "_search_registry", None) or getattr(self, "_rag_registry", None),
            dashscope_api_key=_llm_cfg.get("dashscope_api_key"),
            dashscope_url=_llm_cfg.get("dashscope_url"),
            dashscope_think=_llm_cfg.get("dashscope_think", False),
            dashscope_preserve_thinking=_llm_cfg.get("dashscope_preserve_thinking", False),
            dashscope_stream=_llm_cfg.get("dashscope_stream", True),
            fallbacks=_llm_cfg.get("fallbacks") or None,
        )
        active_repo = str(getattr(self.target_github, "repo", None) or "local") if getattr(self, "target_github", None) else "local"
        agent.run(result, memory_store=getattr(self, "memory", None), repo=active_repo)

    def _stage_discuss_inline(self, result: "PipelineResult", config: dict) -> None:
        """Run a discussion stage from an inline config dict (from pipeline.yaml).

        Writes the config to a temporary YAML file inside the discussions/
        directory (next to the orchestrator) so that DiscussionConfig.from_yaml
        resolves persona_file paths relative to the repo root (parent.parent of
        the config file), not from the system temp directory.
        """
        import os
        import tempfile
        from pathlib import Path
        try:
            import yaml as _yaml
        except ImportError:
            result.add_error(_PipelineError(
                code="DISCUSS_INLINE_ERROR",
                stage="discuss",
                message="_stage_discuss_inline: PyYAML not installed",
                severity="fatal",
            ))
            return
        # Write inside discussions/ so .parent.parent == repo root.
        discussions_dir = Path(__file__).parent / "discussions"
        discussions_dir.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, prefix="discuss_inline_",
            dir=str(discussions_dir),
        ) as f:
            _yaml.safe_dump(config, f)
            tmp_path = f.name
        try:
            self._stage_discuss(result, tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _commit_and_open_pr(
        self,
        result: "PipelineResult",
        branch_prefix: str = "feature/agent",
        title_prefix: str = "feat",
        body_header: str = "## 🤖 Automated change",
        commit_msg_prefix: str = "chore",
        files: "dict[str, str] | None" = None,
    ) -> None:
        """Commit files to a new branch and open a PR.

        ``files`` defaults to ``result.all_files`` when not provided.

        Extracted from ``doc_orchestrator._stage_commit`` / ``_stage_pr`` so
        that doc + bug-fix flows can share a single commit/PR path on the
        unified Orchestrator. Existing feature-pipeline commit logic still
        lives inside ``EngineerAgent.run_with_github`` and is unaffected.
        """
        files_to_commit = files if files is not None else result.all_files
        gh = self.target_github or self.github
        if gh is None or not files_to_commit:
            return

        try:
            repo_info = gh._request("GET", f"/repos/{gh.repo}")
            base_branch = repo_info.get("default_branch", "main")
        except Exception:
            base_branch = "main"

        import re as _re
        slug_source = result.project_name or f"issue-{result.issue_number or 'auto'}"
        slug = _re.sub(r"[^a-z0-9-]", "-", slug_source.lower())[:40].strip("-") or "auto"
        issue_part = f"{result.issue_number}-" if result.issue_number else ""
        branch = f"{branch_prefix}/{issue_part}{slug}"

        try:
            gh.create_branch(branch)
        except Exception as exc:
            result.add_error(f"Branch creation failed: {exc}")
            return
        result.branch = branch

        committed: list[str] = []
        for path, content in files_to_commit.items():
            commit_msg = f"{commit_msg_prefix}: update {path}"
            if result.issue_number:
                commit_msg += f" (issue #{result.issue_number})"
            try:
                gh.commit_file(path=path, content=content, message=commit_msg, branch=branch)
                committed.append(path)
            except Exception as exc:
                result.add_error(f"Failed to commit {path}: {exc}")

        if not committed:
            return

        files_list = "\n".join(f"- `{p}`" for p in committed)
        title = f"{title_prefix}: {result.project_name or 'automated update'}"
        pr_body = (
            f"{body_header}\n\n"
            + (f"Resolves #{result.issue_number}\n\n" if result.issue_number else "")
            + f"### Files\n\n{files_list}\n\n"
            "_Generated by AI Software House unified pipeline._"
        )
        try:
            pr = gh.create_pull_request(title=title, body=pr_body, head=branch, base=base_branch)
            result.pr_number = pr.get("number")
            result.pr_url = pr.get("html_url")
        except Exception as exc:
            result.add_error(f"PR creation failed: {exc}")

    def _get_repo_patterns_dir(self) -> Path:
        """Return the path to repo-patterns/ directory. Patchable in tests."""
        return Path(__file__).parent / "repo-patterns"

    def _build_engineer_context(
        self,
        task: str,
        target_gh: Optional["GitHubClient"] = None,
    ) -> str:
        """Inject relevant codebase context into an engineer task prompt.

        Two tiers:
        - Tier A (local, keyword-triggered): ai-software-house internal patterns —
          base_agent.py signatures, repos.yaml content, _make_stage_registry pattern.
          Only activated for tasks that are modifying ai-software-house itself.
        - Tier B (remote+fallback, always checked when target_gh is set): repo-specific
          patterns from the target repo. Checks in priority order (first match wins):
            1. .github/copilot-instructions.md  (GitHub Copilot standard)
            2. CLAUDE.md                        (Claude Code standard)
            3. .github/AGENTS.md                (our convention)
            4. repo-patterns/{slug}.md          (local fallback)

        Args:
            task: The task description / design string.
            target_gh: GitHubClient pointed at the target repo, or None when working
                       on ai-software-house itself.

        Returns:
            Concatenated context string, or empty string if nothing found.
        """
        task_lower = task.lower()
        parts: list[str] = []

        # ── Tier A: ai-software-house meta-patterns ─────────────────────────────
        # Only fires when working on ai-software-house itself (no external target repo).
        if target_gh is None:
            if "baseagent" in task_lower or "base_agent" in task_lower or (
                "agent" in task_lower and "subclass" in task_lower
            ):
                try:
                    lines = (Path(__file__).parent / "agents/base_agent.py").read_text().splitlines()
                    snippet = "\n".join(lines[:140])
                    parts.append(
                        "## Reference: agents/base_agent.py (first 140 lines)\n"
                        "```python\n" + snippet + "\n```"
                    )
                except FileNotFoundError:
                    pass

            if "repos.yaml" in task_lower or "watcher" in task_lower:
                try:
                    contents = (Path(__file__).parent / "repos.yaml").read_text()
                    parts.append(
                        "## Reference: current repos.yaml (read before modifying — add entries, never rewrite)\n"
                        "```yaml\n" + contents + "\n```"
                    )
                except FileNotFoundError:
                    pass

            if "_make_stage_registry" in task_lower or "pipeline stage" in task_lower or (
                "orchestrator" in task_lower and "stage" in task_lower
            ):
                try:
                    src = (Path(__file__).parent / "orchestrator.py").read_text()
                    start = src.find("    def _make_stage_registry(")
                    end = src.find("\n    def ", start + 1)
                    if start != -1:
                        snippet = src[start:end] if end != -1 else src[start:start + 3000]
                        parts.append(
                            "## Reference: _make_stage_registry() pattern in orchestrator.py\n"
                            "```python\n" + snippet + "\n```"
                        )
                except FileNotFoundError:
                    pass

        # ── Tier B: repo-specific patterns ───────────────────────────────────────
        if target_gh is not None:
            repo_slug = target_gh.repo.replace("/", "-")
            agents_md: Optional[str] = None
            source_label: str = ""

            remote_candidates = [
                (".github/copilot-instructions.md", "`.github/copilot-instructions.md`"),
                ("CLAUDE.md", "`CLAUDE.md`"),
                (".github/AGENTS.md", "`.github/AGENTS.md`"),
            ]

            for remote_path, label in remote_candidates:
                try:
                    content = target_gh.get_file_content(remote_path)
                except Exception:
                    continue
                if content is not None:
                    agents_md = content
                    source_label = label
                    break

            if agents_md is None:
                local_path = self._get_repo_patterns_dir() / f"{repo_slug}.md"
                if local_path.exists():
                    try:
                        agents_md = local_path.read_text(encoding="utf-8")
                        source_label = f"`repo-patterns/{repo_slug}.md` (local fallback)"
                    except OSError:
                        pass

            if agents_md:
                parts.append(
                    f"## Codebase Patterns for {target_gh.repo} (from {source_label})\n\n"
                    + agents_md
                )

        return "\n\n".join(parts)

    def _make_stage_registry(self) -> dict[str, "PipelineStage"]:
        """Build and return the complete stage registry by composing sub-group builders."""
        stages: dict[str, "PipelineStage"] = {}
        stages.update(self._build_product_stages())
        stages.update(self._build_engineering_stages())
        stages.update(self._build_content_stages())
        stages.update(self._build_utility_stages())
        stages.update(self._build_discussion_stages())
        # Wire per-stage timeouts from config
        for _name, _stage in stages.items():
            if _name in (self._stage_timeouts or {}):
                _stage.timeout_s = self._stage_timeouts[_name]  # type: ignore[index]
        return stages

    # ------------------------------------------------------------------
    # Stage sub-builders
    # ------------------------------------------------------------------

    def _build_product_stages(self) -> dict[str, "PipelineStage"]:
        """Build product pipeline stages (PM, PM reviewer, and PR campaign stages)."""
        stages: dict[str, "PipelineStage"] = {}
        stages.update(self._build_product_stages_pm())
        stages.update(self._build_product_stages_pr())
        return stages

    def _build_product_stages_pm(self) -> dict[str, "PipelineStage"]:
        """Build product manager and PM reviewer stages."""
        stages: dict[str, "PipelineStage"] = {}
        stages["pm"] = PipelineStage(
            name="pm",
            label="📋 Product Manager",
            description="Analyzing requirements & writing PRD...",
            checkpoint_key="pm",
            fn=lambda r: self._stage_pm(r, r.requirement),
            required_output_fields=["prd"],
            is_critical=True,
        )
        stages["pm_reviewer"] = PipelineStage(
            name="pm_reviewer",
            label="📝 PM Reviewer",
            description="Reviewing PRD for completeness...",
            checkpoint_key="pm_reviewer",
            fn=lambda r: self._stage_pm_reviewer(r, r.requirement),
        )
        return stages

    def _build_product_stages_pr(self) -> dict[str, "PipelineStage"]:
        """Build PR (marketing campaign) pipeline stages."""
        stages: dict[str, "PipelineStage"] = {}
        stages["pr_analyst"] = PipelineStage(
            name="pr_analyst",
            label="🔍 PR Analyst",
            description="Analysing campaign brief...",
            checkpoint_key="pr_analyst",
            fn=lambda r: self._stage_pr_analyst(r),
        )
        stages["pr_creative"] = PipelineStage(
            name="pr_creative",
            label="🎨 PR Creative",
            description="Generating campaign concepts...",
            checkpoint_key="pr_creative",
            fn=lambda r: self._stage_pr_creative(r),
        )
        stages["pr_proposal"] = PipelineStage(
            name="pr_proposal",
            label="📋 PR Proposal",
            description="Assembling proposal and opening PR...",
            checkpoint_key="pr_proposal",
            fn=lambda r: self._stage_pr_proposal(r),
        )
        return stages

    def _build_engineering_stages(self) -> dict[str, "PipelineStage"]:
        """Build all engineering pipeline stages across design, impl, QA, and debug groups."""
        stages: dict[str, "PipelineStage"] = {}
        stages.update(self._build_engineering_stages_design())
        stages.update(self._build_engineering_stages_impl())
        stages.update(self._build_engineering_stages_qa())
        stages.update(self._build_engineering_stages_test())
        stages.update(self._build_engineering_stages_fix())
        stages.update(self._build_engineering_stages_debug())
        return stages

    def _build_engineering_stages_design(self) -> dict[str, "PipelineStage"]:
        """Build architecture design and tier-review stages."""
        stages: dict[str, "PipelineStage"] = {}
        stages["architect"] = PipelineStage(
            name="architect",
            label="🏗️  Architect",
            description="Designing system architecture...",
            checkpoint_key="architect",
            fn=lambda r: self._stage_architect(r),
            required_output_fields=["design"],
            is_critical=True,
        )
        stages["architect_reviewer"] = PipelineStage(
            name="architect_reviewer",
            label="🔎 Architect Reviewer",
            description="Reviewing system design...",
            checkpoint_key="architect_reviewer",
            fn=lambda r: self._stage_architect_reviewer(r),
        )
        stages["tier_review"] = PipelineStage(
            name="tier_review",
            label="🏷️  Tier Review",
            description="Classifying modules into junior/senior tiers...",
            checkpoint_key="tier_review",
            fn=lambda r: self._stage_tier_review(r),
            # parallel_group can be set here for custom pipeline.yaml arrangements
            # where tier_review and qa_planner appear consecutively.
            # They are not consecutive in the built-in MODES, so no group is set by default.
        )
        return stages

    def _build_engineering_stages_impl(self) -> dict[str, "PipelineStage"]:
        """Build engineer implementation stages (junior, senior, single-tier)."""
        stages: dict[str, "PipelineStage"] = {}
        stages["junior_engineer"] = PipelineStage(
            name="junior_engineer",
            label="🟢 Junior Engineers",
            description="Implementing junior module(s)...",
            checkpoint_key="junior_engineer",
            fn=lambda r: self._stage_junior_engineer(r),
            skip_if=lambda r: "engineer" in r.completed_stages,
        )
        stages["senior_engineer"] = PipelineStage(
            name="senior_engineer",
            label="🔵 Senior Engineers",
            description="Implementing senior module(s)...",
            checkpoint_key="senior_engineer",
            fn=lambda r: self._stage_senior_engineer(r),
            skip_if=lambda r: "engineer" in r.completed_stages,
        )
        stages["engineer"] = PipelineStage(
            name="engineer",
            label="👷 Engineer",
            description="Implementing modules (single-tier)...",
            checkpoint_key="engineer",
            fn=lambda r: self._stage_engineer(r),
        )
        return stages

    def _build_engineering_stages_qa(self) -> dict[str, "PipelineStage"]:
        """Build code review and QA planning/engineering stages."""
        stages: dict[str, "PipelineStage"] = {}
        stages["reviewer"] = PipelineStage(
            name="reviewer",
            label="🔍 Code Reviewer",
            description="Reviewing generated code...",
            checkpoint_key="reviewer",
            fn=lambda r: self._stage_reviewer(r),
            stop_if=lambda r: self.stop_on_review_issues and r.verdict == "CHANGES REQUESTED",
            stop_message="⛔ Pipeline stopped: code reviewer requested changes.",
        )
        stages["qa_planner"] = PipelineStage(
            name="qa_planner",
            label="📋 QA Planner",
            description="Creating test plan & acceptance criteria...",
            checkpoint_key="qa_planner",
            fn=lambda r: self._stage_qa_planner(r),
            # parallel_group can be set in custom pipeline.yaml configurations.
        )
        stages["qa_engineer"] = PipelineStage(
            name="qa_engineer",
            label="🧪 QA Engineer",
            description="Writing tests & producing test plan...",
            checkpoint_key="qa",
            fn=lambda r: self._stage_qa(r),
        )
        return stages

    def _build_engineering_stages_test(self) -> dict[str, "PipelineStage"]:
        """Build TDD write, test-runner loop, and validation-gate stages."""
        stages: dict[str, "PipelineStage"] = {}
        stages["qa_write"] = PipelineStage(
            name="qa_write",
            label="✍️  QA Write (TDD)",
            description="Writing tests before implementation...",
            checkpoint_key="qa_write",
            fn=lambda r: self._stage_qa_write(r),
        )
        stages["tdd_review"] = PipelineStage(
            name="tdd_review",
            label="🔎 TDD Review",
            description="Reviewing and auto-fixing TDD test files...",
            checkpoint_key="tdd_review",
            fn=lambda r: self._stage_tdd_review(r),
            skip_if=lambda r: not r.test_files,
        )
        stages["contract_validate"] = PipelineStage(
            name="contract_validate",
            label="📋 Contract Validation",
            description="Validating test files against naming contract...",
            checkpoint_key="contract_validate",
            fn=lambda r: self._stage_contract_validate(r),
            skip_if=lambda r: not r.test_files or not r.naming_contract,
        )
        stages["test_fix"] = PipelineStage(
            name="test_fix",
            label="🏃 Test Runner + Fix Loop",
            description="Executing tests (with auto-fix)…",
            checkpoint_key="test_runner",
            fn=lambda r: self._stage_test_fix_loop(r),
            skip_if=lambda r: not r.test_files,
        )
        stages["validation_gate"] = PipelineStage(
            name="validation_gate",
            label="🔍 Validation Gate",
            description="Syntax-checking and linting generated code...",
            checkpoint_key="validation_gate",
            fn=lambda r: self._stage_validation_gate(r),
        )
        return stages

    def _build_engineering_stages_fix(self) -> dict[str, "PipelineStage"]:
        """Build deployment tester and deploy-fix-loop stages."""
        stages: dict[str, "PipelineStage"] = {}
        stages["deploy_tester"] = PipelineStage(
            name="deploy_tester",
            label="🚀 Deployment Tester",
            description="Generating deployment smoke tests...",
            checkpoint_key="deployment_tester",
            fn=lambda r: self._stage_deployment_tester(r),
        )
        stages["deploy_fix"] = PipelineStage(
            name="deploy_fix",
            label="🐳 Deploy Test Runner + Fix Loop",
            description="Running deployment tests (with auto-fix)…",
            checkpoint_key="deploy_test_runner",
            fn=lambda r: self._stage_deploy_fix_loop(r),
            skip_if=lambda r: not r.deploy_files,
        )
        return stages

    def _build_engineering_stages_debug(self) -> dict[str, "PipelineStage"]:
        """Build bug diagnose and bug-fix stages."""
        stages: dict[str, "PipelineStage"] = {}
        stages["diagnose"] = PipelineStage(
            name="diagnose",
            label="🔬 Diagnoser",
            description="Diagnosing bug from issue body and existing files...",
            checkpoint_key="diagnose",
            fn=lambda r: self._stage_diagnose(r),
        )
        stages["bug_fix"] = PipelineStage(
            name="bug_fix",
            label="🛠️  Bug Fix",
            description="Applying bug fix patches...",
            checkpoint_key="bug_fix",
            fn=lambda r: self._stage_bug_fix(r),
        )
        return stages

    def _build_content_stages(self) -> dict[str, "PipelineStage"]:
        """Build all content/news pipeline stages (writing, translation, review)."""
        stages: dict[str, "PipelineStage"] = {}
        stages.update(self._build_content_stages_writing())
        stages.update(self._build_content_stages_translate())
        stages.update(self._build_content_stages_review())
        return stages

    def _build_content_stages_writing(self) -> dict[str, "PipelineStage"]:
        """Build news triage, writer, and editor stages."""
        stages: dict[str, "PipelineStage"] = {}
        stages["news_triage"] = PipelineStage(
            name="news_triage",
            label="🗞️  Editorial Triage",
            description="Editorial team voting: publish or skip?",
            checkpoint_key="news_triage",
            fn=lambda r: self._stage_news_triage(r),
            stop_if=lambda r: r.editorial_verdict == "SKIP",
            stop_message="🚫 Editorial triage: story skipped — pipeline aborted.",
        )
        stages["news_writer"] = PipelineStage(
            name="news_writer",
            label="✍️  News Writer",
            description="Writing news article draft...",
            checkpoint_key="news_writer",
            fn=lambda r: self._stage_news_writer(r),
        )
        stages["news_editor"] = PipelineStage(
            name="news_editor",
            label="📝 News Editor",
            description="Editing and finalising article...",
            checkpoint_key="news_editor",
            fn=lambda r: self._stage_news_editor(r),
        )
        return stages

    def _build_content_stages_translate(self) -> dict[str, "PipelineStage"]:
        """Build translation stages (Cantonese and Traditional Chinese)."""
        stages: dict[str, "PipelineStage"] = {}
        stages["translate_cantonese"] = PipelineStage(
            name="translate_cantonese",
            label="🀄 Translate (Cantonese)",
            description="Translating article to Written Cantonese...",
            checkpoint_key="translate_cantonese",
            fn=lambda r: self._stage_translate(r, "cantonese", "article_zh_hk"),
        )
        stages["translate_zh_traditional"] = PipelineStage(
            name="translate_zh_traditional",
            label="🀄 Translate (Traditional Chinese)",
            description="Translating article to Traditional Chinese...",
            checkpoint_key="translate_zh_traditional",
            fn=lambda r: self._stage_translate(r, "traditional_chinese", "article_zh_tw"),
        )
        return stages

    def _build_content_stages_review(self) -> dict[str, "PipelineStage"]:
        """Build news article reviewer and PR-open stages."""
        stages: dict[str, "PipelineStage"] = {}
        stages["news_reviewer"] = PipelineStage(
            name="news_reviewer",
            label="🔍 News Reviewer",
            description="Reviewing article quality and translation correctness...",
            checkpoint_key="news_reviewer",
            fn=lambda r: self._stage_news_reviewer(r),
        )
        stages["news_article_pr"] = PipelineStage(
            name="news_article_pr",
            label="📨 News Article PR",
            description="Opening PR with article...",
            checkpoint_key="news_article_pr",
            fn=lambda r: self._stage_news_article_pr(r),
        )
        return stages

    def _build_utility_stages(self) -> dict[str, "PipelineStage"]:
        """Build utility stages: doc generation, doc PR, and bootstrap patterns."""
        stages: dict[str, "PipelineStage"] = {}
        stages["doc_generate"] = PipelineStage(
            name="doc_generate",
            label="📚 Doc Generator",
            description="Generating documentation files...",
            checkpoint_key="doc_generate",
            fn=lambda r: self._stage_doc_generate(r),
        )
        stages["doc_commit_pr"] = PipelineStage(
            name="doc_commit_pr",
            label="📤 Doc Commit + PR",
            description="Committing docs and opening PR...",
            checkpoint_key="doc_commit_pr",
            fn=lambda r: self._stage_doc_commit_pr(r),
        )
        stages["bootstrap_patterns"] = PipelineStage(
            name="bootstrap_patterns",
            label="🌱 Bootstrap Patterns",
            description="Scanning repo and generating .github/AGENTS.md...",
            checkpoint_key="bootstrap_patterns",
            fn=lambda r: self._stage_bootstrap_patterns(r),
        )
        return stages

    def _build_discussion_stages(self) -> dict[str, "PipelineStage"]:
        """Auto-discover discussions/*.yaml presets and register as discuss_<name> stages.

        Registered dynamically at runtime — no fixed sub-builders possible.
        """
        stages: dict[str, "PipelineStage"] = {}
        # Auto-discover discussions/*.yaml and register as discuss_<name> stages
        discussions_dir = getattr(self, "_discussions_dir", Path(__file__).parent / "discussions")
        if discussions_dir.is_dir():
            all_presets = sorted(
                list(discussions_dir.glob("*.yaml")) + list(discussions_dir.glob("*.yml"))
            )
            for preset_path in all_presets:
                stage_key = f"discuss_{preset_path.stem.replace('-', '_')}"
                if stage_key in stages:
                    log.warning(
                        "discuss stage key collision: '%s' from '%s' already registered; skipping.",
                        stage_key, preset_path.name,
                    )
                    continue
                label_name = preset_path.stem.replace("-", " ").replace("_", " ").title()
                stages[stage_key] = PipelineStage(
                    name=stage_key,
                    label=f"💬 Discuss: {label_name}",
                    description=f"Multi-agent round-table discussion ({preset_path.name})",
                    checkpoint_key=stage_key,
                    fn=lambda r, p=str(preset_path): self._stage_discuss(r, p),
                )
        return stages

    def _load_pipeline_yaml(self, config_path: str) -> "list | None":
        """Parse and validate pipeline.yaml from the same directory as config_path.

        Returns a raw ordered list of stage entries (strings for simple stages,
        dicts with a 'loop' key for loop blocks), or None if the file does not
        exist.  Raises ValueError on any schema violation.

        Returning raw entries (instead of PipelineStage objects) ensures that
        when the real orchestrator later resolves them via _build_stage_list(),
        all fn lambdas close over the correct ``self`` — not over a temporary
        stub created during from_config().
        """
        pipeline_yaml_path = Path(config_path).parent / "pipeline.yaml"
        if not pipeline_yaml_path.exists():
            return None

        try:
            with open(pipeline_yaml_path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise yaml.YAMLError(f"Error parsing {pipeline_yaml_path}: {exc}") from exc

        if not data or not isinstance(data, dict):
            raise ValueError(
                f"pipeline.yaml root must be a mapping with a 'stages' list. "
                f"Found: {'empty file' if not data else type(data).__name__}"
            )
        if not isinstance(data.get("stages"), list):
            raise ValueError(
                f"pipeline.yaml must define a 'stages' list. "
                f"Found: {type(data.get('stages')).__name__}"
            )

        registry = self._make_stage_registry()
        valid_names = set(registry.keys())
        result_entries: list = []

        for i, entry in enumerate(data["stages"]):
            if isinstance(entry, str):
                if entry not in valid_names:
                    raise ValueError(
                        f"Unknown stage {entry!r} at index {i} in pipeline.yaml. "
                        f"Valid names: {sorted(valid_names)}"
                    )
                result_entries.append(entry)  # store the name string only

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
                # Whitelist check: reject typos immediately rather than looping forever
                until_val = str(loop["until"]).strip().upper()
                if until_val not in VALID_LOOP_VERDICTS:
                    raise ValueError(
                        f"Loop block at index {i} 'until' must be one of "
                        f"{sorted(VALID_LOOP_VERDICTS)}. Got: {loop['until']!r}"
                    )
                loop["until"] = until_val  # normalise to uppercase
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
                result_entries.append(entry)  # store the raw dict

            elif isinstance(entry, dict) and "discuss" in entry:
                discuss = entry["discuss"]
                if not isinstance(discuss, dict):
                    raise ValueError(f"Discuss block at index {i} must be a mapping.")
                participants = discuss.get("participants")
                preset = discuss.get("preset")
                if not participants and not preset:
                    raise ValueError(
                        f"Discuss block at index {i} must have 'participants' list or 'preset' path."
                    )
                result_entries.append(entry)  # store the raw dict

            else:
                raise ValueError(
                    f"Invalid stage entry at index {i}: {entry!r}. "
                    f"Expected a stage name (string) or a loop block (dict with 'loop' key)."
                )

        return result_entries

    def load_pipeline_for_label(
        self,
        label: str,
        project_dir: "str | None" = None,
    ) -> "list | None":
        """Resolve the pipeline stage list for a given GitHub label.

        Priority (highest to lowest):
        1. ``project_dir/pipeline.yaml`` if it exists (project override)
        2. ``pipelines/<label>.yaml`` next to this orchestrator module
        3. ``None`` (caller falls back to built-in default)
        """
        from pathlib import Path
        if project_dir:
            project_yaml = Path(project_dir) / "pipeline.yaml"
            if project_yaml.exists():
                import yaml
                with open(project_yaml, encoding="utf-8") as fh:
                    raw = yaml.safe_load(fh) or {}
                stages = raw.get("stages")
                if stages is not None:
                    self._validate_pipeline_stages(str(project_yaml), stages)
                return stages

        builtin = Path(__file__).parent / "pipelines" / f"{label}.yaml"
        if builtin.exists():
            import yaml
            with open(builtin, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            stages = raw.get("stages")
            if stages is not None:
                self._validate_pipeline_stages(label, stages)
            return stages

        return None

    def _validate_pipeline_stages(self, source: str, stages: list) -> None:
        """Validate all stage names exist in the registry (collects all errors).

        Walks top-level string entries and inner stages inside loop blocks.
        Raises ConfigurationError listing all unknown stages at once.

        Raises:
            ConfigurationError: If ``stages`` is not a list, if any stage name
                (including those nested inside loop blocks) does not exist in
                the stage registry, or if a loop block is structurally invalid.
                All unknown names are collected before raising so the caller
                sees every problem in a single error.
        """
        if not isinstance(stages, list):
            raise ConfigurationError(
                f"Pipeline 'stages' must be a list, got {type(stages).__name__!r} in {source!r}"
            )
        registry = self._make_stage_registry()
        unknown = []
        for entry in stages:
            if isinstance(entry, str):
                if entry not in registry:
                    unknown.append(entry)
            elif isinstance(entry, dict) and "loop" in entry:
                loop = entry["loop"]
                if not isinstance(loop, dict):
                    raise ConfigurationError(
                        f"Loop block must be a mapping in {source!r}, got {type(loop).__name__!r}"
                    )
                inner_stages = loop.get("stages")
                if inner_stages is not None and not isinstance(inner_stages, list):
                    raise ConfigurationError(
                        f"Loop 'stages' must be a list in {source!r}, got {type(inner_stages).__name__!r}"
                    )
                for inner in (inner_stages or []):
                    if isinstance(inner, str) and inner not in registry:
                        unknown.append(f"(loop){inner}")
            elif isinstance(entry, dict) and "discuss" in entry:
                discuss = entry["discuss"]
                if not isinstance(discuss, dict):
                    raise ConfigurationError(
                        f"Discuss block must be a mapping in {source!r}, got {type(discuss).__name__!r}"
                    )
                participants = discuss.get("participants")
                preset = discuss.get("preset")
                if not participants and not preset:
                    raise ConfigurationError(
                        f"Discuss block in {source!r} must have 'participants' list or 'preset' path."
                    )
                # inline discuss blocks are validated above; no registry lookup needed
        if unknown:
            raise ConfigurationError(
                f"Unknown pipeline stage(s) {unknown!r} in {source!r}. "
                f"Valid stages: {sorted(registry.keys())}"
            )

    def _build_stage_list(self) -> list[PipelineStage]:
        """Return the ordered stage list, applying skip overrides.

        When _pipeline_yaml_stages is set (pipeline.yaml was present at load
        time), resolve the raw entries to real PipelineStage objects using the
        current orchestrator's registry so that all fn lambdas close over the
        correct ``self``.  Otherwise falls back to MODES[_mode].
        """
        import copy

        raw = getattr(self, '_pipeline_yaml_stages', None)
        if raw is not None:
            registry = self._make_stage_registry()
            stages: list[PipelineStage] = []
            for i, entry in enumerate(raw):
                if isinstance(entry, str):
                    # Assign a unique checkpoint_key per occurrence so repeated
                    # stage names don't collide on pipeline resume (Fix 1).
                    stage = copy.copy(registry[entry])
                    stage.checkpoint_key = f"{entry}_{i}"
                    if not self._stage_skips.get(entry, False):
                        stages.append(stage)
                elif isinstance(entry, dict) and "loop" in entry:
                    loop = entry["loop"]
                    loop_name = f"loop_{i}"
                    if not self._stage_skips.get(loop_name, False):
                        inner_label = ", ".join(loop["stages"])
                        stages.append(PipelineStage(
                            name=loop_name,
                            label=f"🔁 Loop ({inner_label})",
                            description=f"Running loop: {inner_label}...",
                            checkpoint_key=loop_name,
                            fn=lambda r: None,  # execution handled by _run_loop_stage()
                            loop_stages=list(loop["stages"]),
                            loop_max=loop["max"],
                            loop_until=str(loop["until"]),
                        ))
                elif isinstance(entry, dict) and "discuss" in entry:
                    discuss_cfg = entry["discuss"]
                    stage_name = f"discuss_inline_{i}"
                    if not self._stage_skips.get(stage_name, False):
                        if "preset" in discuss_cfg and "participants" not in discuss_cfg:
                            # Preset-only: delegate directly to _stage_discuss with the preset path.
                            preset_path = discuss_cfg["preset"]
                            stages.append(PipelineStage(
                                name=stage_name,
                                label=f"💬 Discuss ({discuss_cfg['preset']})",
                                description=f"Multi-agent round-table discussion ({discuss_cfg['preset']})",
                                checkpoint_key=stage_name,
                                fn=lambda r, p=preset_path: self._stage_discuss(r, p),
                            ))
                        else:
                            stages.append(PipelineStage(
                                name=stage_name,
                                label="💬 Discuss (inline)",
                                description="Multi-agent round-table discussion (inline participants)",
                                checkpoint_key=stage_name,
                                fn=lambda r, d=discuss_cfg: self._stage_discuss_inline(r, d),
                            ))
            return stages

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

    def _expected_stages(self) -> list[ProgressStage]:
        """Return the ordered list of stages expected for this pipeline run.

        Revision rounds (prd_revision_N, design_revision_N) are excluded here —
        they are added dynamically via tracker.add_stage() as they actually begin.
        """
        stages: list[ProgressStage] = []

        if getattr(self, '_pipeline_yaml_stages', None) is None:
            # Standard pipeline: fixed PM + Arch loops first
            stages += [
                ProgressStage("pm",                "📋 Product Manager"),
                ProgressStage("pm_reviewer",       "📝 PM Reviewer"),
                ProgressStage("pm_review_loop",    "✔️  PRD Approved"),
                ProgressStage("architect",         "🏗️  Architect"),
                ProgressStage("architect_reviewer","🔎 Architect Reviewer"),
                ProgressStage("architect_review_loop", "✔️  Design Approved"),
            ]

        # Mode-driven stages (engineer, reviewer, QA, etc.)
        for stage in self._build_stage_list():
            stages.append(ProgressStage(stage.checkpoint_key, stage.label))

        return stages

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
                _inner_token = current_stage.set(inner_name)
                try:
                    self._run_stage(
                        inner.label, inner.description, result,
                        lambda s=inner: s.fn(result),
                        timeout_s=inner.timeout_s,
                        required_output_fields=inner.required_output_fields,
                    )
                finally:
                    current_stage.reset(_inner_token)
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
        """Return non-bot PR review comments, review bodies, and regular PR comments as a flat list.

        Each item: {"author": str, "body": str, "location": str}

        Sources:
          - Inline diff review comments  (/pulls/{n}/comments)
          - PR review submissions         (/pulls/{n}/reviews)
          - Regular PR issue comments     (/issues/{n}/comments)  ← test results, human notes
        """
        # github-actions[bot] posts CI noise; copilot[bot] is a legacy app name (not the PR reviewer).
        # copilot-pull-request-reviewer posts useful suggestions and is intentionally included.
        bot_logins = {"github-actions[bot]", "copilot[bot]"}

        inline = self.target_github.get_pr_review_comments(pr_number)
        reviews = self.target_github.get_pr_reviews(pr_number)
        issue_comments = self.target_github.get_issue_comments(pr_number)

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

        for c in issue_comments:
            login = c.get("user", {}).get("login", "")
            if login in bot_logins:
                continue
            body = (c.get("body") or "").strip()
            if not body:
                continue
            feedback.append({"author": login, "body": body, "location": "comment"})

        return feedback

    def _format_feedback(self, feedback: list[dict]) -> str:
        """Format a list of feedback dicts as a markdown bullet list."""
        lines = ["### PR Feedback to Address\n"]
        for item in feedback:
            loc = item["location"]
            if loc in ("review", "comment"):
                location = f" _(in PR {loc})_"
            else:
                location = f" _(at {loc})_"
            lines.append(f"- **{item['author']}**{location}: {item['body']}")
        return "\n".join(lines)

    def _parse_merge_directives(self, feedback: list[dict]) -> list[str]:
        """Scan PR feedback for merge directives and return deduplicated branch names.

        Supports:
          - ``merge-branch: <branch>``
          - ``merge branch `<branch>```
          - ``incorporate ... from branch `<branch>```
          - ``merge from PR #N``  (resolved to head branch via GitHub API)
        """
        seen: list[str] = []
        for item in feedback:
            body = item.get("body", "")
            for m in _MERGE_DIRECTIVE_RE.finditer(body):
                branch = m.group(1) or m.group(2) or m.group(3)
                pr_num_str = m.group(4)
                if pr_num_str and self.target_github:
                    try:
                        pr = self.target_github.get_pr(int(pr_num_str))
                        branch = pr["head"]["ref"]
                    except Exception:
                        continue
                if branch and branch not in seen:
                    seen.append(branch)
        return seen

    def _fetch_branch_files(self, branch: str) -> dict[str, str]:
        """Fetch all file contents from *branch* using the GitHub tree API.

        Returns a mapping of ``file_path -> file_content`` (UTF-8 strings).
        Binary files that cannot be decoded are silently skipped.
        Files larger than 200 KB (``size > 204_800``) are also skipped to
        avoid blowing up the context window.
        """
        MAX_FILE_BYTES = 204_800  # 200 KB
        tree = self.target_github.get_full_tree(ref=branch)
        result: dict[str, str] = {}
        for entry in tree:
            if entry.get("type") != "blob":
                continue
            if entry.get("size", 0) > MAX_FILE_BYTES:
                continue
            path = entry["path"]
            content = self.target_github.get_file_content(path, ref=branch)
            if content is not None:
                result[path] = content
        return result

    def _parse_update_directive(self, feedback: list[dict]) -> bool:
        """Return True if there is a pending (unprocessed) 'update-branch' directive.

        Scans comments in reverse chronological order (newest first).
        A directive is considered already processed if a bot acknowledgment comment
        (containing _UPDATE_BRANCH_MARKER) appears after the most recent user
        update-branch comment.

        Supported user directive formats (case-insensitive):
            update-branch
            update-branch: true
        """
        directive_pattern = re.compile(r"update-branch(?::\s*true)?", re.IGNORECASE)
        for item in reversed(feedback):
            body = item.get("body", "")
            if _UPDATE_BRANCH_MARKER in body:
                return False  # Bot already acknowledged this directive — not pending
            if directive_pattern.search(body):
                return True  # Unprocessed user directive found
        return False  # No directive

    def _update_branch_from_base(
        self,
        head_branch: str,
        base_branch: str = "master",
        pr_number: int | None = None,
        pr_context: "PRContext | None" = None,
    ) -> dict:
        """Merge *base_branch* into *head_branch*.

        Returns a status dict:
            {"status": "up_to_date"}  — 204, nothing to do
            {"status": "merged"}      — 201, clean or AI-resolved merge
            {"status": "conflict", "conflicting_files": [...]}
                                      — could not resolve, PR comment posted
        """
        code = self.target_github.merge_base_into_branch(base_branch, head_branch)

        if code == 204:
            console.print(f"  ✅ Branch [cyan]{head_branch}[/cyan] is already up to date with [cyan]{base_branch}[/cyan]")
            if pr_number is not None:
                self.target_github.add_pr_comment(
                    pr_number,
                    f"ℹ️ Branch `{head_branch}` is already up to date with `{base_branch}`. {_UPDATE_BRANCH_MARKER}",
                )
            return {"status": "up_to_date"}

        if code == 201:
            console.print(f"  ✅ Merged [cyan]{base_branch}[/cyan] into [cyan]{head_branch}[/cyan] cleanly")
            if pr_number is not None:
                self.target_github.add_pr_comment(
                    pr_number,
                    f"✅ Merged `{base_branch}` into `{head_branch}` successfully. {_UPDATE_BRANCH_MARKER}",
                )
            return {"status": "merged"}

        # ── 409: conflict path ────────────────────────────────────────────────
        console.print(f"  ⚠️  Merge conflict detected — attempting AI resolution …")

        if not pr_context:
            console.print("  ⚠️  conflict detected but no pr_context — cannot resolve")
            if pr_number is not None:
                self.target_github.add_pr_comment(
                    pr_number,
                    "⚠️ Could not automatically resolve merge conflicts.\n\n"
                    "- (unknown)\n\n"
                    f"Please resolve these conflicts manually and re-trigger ai-fix.\n\n"
                    f"{_UPDATE_BRANCH_MARKER}",
                )
            return {"status": "conflict", "conflicting_files": []}

        model = self.conflict_resolver_model or self.senior_model or self.model
        resolver = ConflictResolverAgent(model=model, **self.agent_kwargs)

        # Build authenticated HTTPS clone URL from the target GitHub client
        token = self.target_github.token
        repo = self.target_github.repo
        repo_url = f"https://{token}@github.com/{repo}.git"

        result = resolver.resolve(
            repo_url=repo_url,
            head_branch=head_branch,
            base_branch=base_branch,
            pr_context=pr_context,
        )

        if result.status == "resolved":
            console.print(f"  ✅ Conflict resolved: {result.resolved_files}")
            # Retry merge after conflict resolution
            retry_code = self.target_github.merge_base_into_branch(base_branch, head_branch)
            if retry_code in (201, 204):
                console.print(f"  ✅ Merge succeeded after AI conflict resolution")
                if pr_number is not None:
                    self.target_github.add_pr_comment(
                        pr_number,
                        f"✅ Merged `{base_branch}` into `{head_branch}` after resolving conflicts. {_UPDATE_BRANCH_MARKER}",
                    )
                return {"status": "merged"}
            # Merge still conflicted after resolution — we don't know which files
            # GitHub considers conflicting anymore (the previously resolved files
            # are already fixed), so report an empty list and ask for manual merge.
            conflicting_files = []
            retry_failed_after_resolution = True
        else:
            console.print(f"  ❌ Conflict resolution failed: {_sanitise(result.reason or '', getattr(self.target_github, 'token', ''))}")
            conflicting_files = result.failed_files or []
            retry_failed_after_resolution = False

        if pr_number is not None:
            if retry_failed_after_resolution:
                self.target_github.add_pr_comment(
                    pr_number,
                    "⚠️ Conflicts were resolved locally but the merge still could not complete. "
                    "Please merge manually.\n\n"
                    f"{_UPDATE_BRANCH_MARKER}",
                )
            else:
                files_list = "\n".join(f"- `{p}`" for p in conflicting_files) if conflicting_files else "- (unknown)"
                self.target_github.add_pr_comment(
                    pr_number,
                    "⚠️ Could not automatically resolve merge conflicts.\n\n"
                    f"Conflicting files:\n{files_list}\n\n"
                    f"Please resolve these conflicts manually and re-trigger ai-fix.\n\n"
                    f"{_UPDATE_BRANCH_MARKER}",
                )
        return {"status": "conflict", "conflicting_files": conflicting_files}

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

        ctx = self._revision_fetch_pr_context(pr_number)
        self._revision_inject_skills(ctx["pr_body"])

        cap_result = self._revision_check_cap(pr_number, ctx["current_rev"])
        if cap_result:
            return cap_result

        update_result = self._revision_maybe_update_branch(pr_number, ctx["pr"], ctx["head_branch"])
        if update_result:
            return update_result

        fb_ctx = self._revision_collect_feedback(pr_number)
        if "status" in fb_ctx:
            return fb_ctx

        files_ctx = self._revision_collect_files(
            pr_number, ctx["head_branch"], ctx["issue_number"], fb_ctx["merge_branches"]
        )
        augmented_design = self._revision_build_augmented_design(
            files_ctx["design"], ctx["head_branch"], files_ctx["current_files"],
            files_ctx["merge_branch_files"], fb_ctx["feedback_md"],
        )

        new_revision = ctx["current_rev"] + 1
        console.print(f"\n[bold cyan]🔄 Revision {new_revision}/{self.max_revisions}[/bold cyan]")
        return self._revision_execute(
            pr_number, ctx["head_branch"], augmented_design, files_ctx, fb_ctx, ctx, new_revision
        )

    # ── run_revision() helpers ────────────────────────────────────────────────

    def _revision_fetch_pr_context(self, pr_number: int) -> dict:
        """Fetch PR metadata needed for revision: pr object, head branch, body, issue number, and current revision count."""
        pr = self.target_github.get_pr(pr_number)
        head_branch = pr["head"]["ref"]
        pr_body = pr.get("body") or ""
        issue_number = self._extract_issue_number(pr_body)
        labels = [lbl["name"] for lbl in pr.get("labels", [])]
        current_rev = self._get_revision_number(labels)
        return {
            "pr": pr,
            "head_branch": head_branch,
            "pr_body": pr_body,
            "issue_number": issue_number,
            "labels": labels,
            "current_rev": current_rev,
        }

    def _revision_inject_skills(self, pr_body: str) -> None:
        """Inject skills relevant to the PR into engineer, reviewer, and QA agents."""
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

    def _revision_check_cap(self, pr_number: int, current_rev: int) -> Optional[dict]:
        """Return an early-exit dict if the revision cap has been reached, else None."""
        if current_rev >= self.max_revisions:
            self.target_github.add_pr_comment(
                pr_number,
                f"⏹ Max revisions reached ({current_rev}/{self.max_revisions}). "
                "No further automated revisions will be made.",
            )
            return {"status": "max_revisions_reached"}
        return None

    def _revision_maybe_update_branch(self, pr_number: int, pr: dict, head_branch: str) -> Optional[dict]:
        """If auto-update is configured and a directive is present, sync branch with its base. Returns conflict dict or None."""
        if not self._update_branch_enabled:
            return None
        pr_base_branch = pr["base"]["ref"]
        pr_issue_comments = self.target_github.get_issue_comments(pr_number)
        update_directive_feedback = [
            {"body": c.get("body", ""), "author": c.get("user", {}).get("login", "")}
            for c in pr_issue_comments
        ]
        if self._parse_update_directive(update_directive_feedback):
            pr_ctx = PRContext(
                pr_title=pr.get("title", ""),
                pr_body=pr.get("body", "") or "",
                design_doc="",
                skills="",
            )
            update_result = self._update_branch_from_base(
                head_branch, base_branch=pr_base_branch, pr_number=pr_number,
                pr_context=pr_ctx,
            )
            if update_result["status"] == "conflict":
                return update_result
        return None

    def _revision_collect_feedback(self, pr_number: int) -> dict:
        """Collect human feedback from PR. Returns dict with feedback/feedback_md/merge_branches, or {"status": "no_feedback"}."""
        feedback = self._collect_pr_feedback(pr_number)
        if not feedback:
            return {"status": "no_feedback"}
        feedback_md = self._format_feedback(feedback)
        console.print(f"  💬 Collected [bold]{len(feedback)}[/bold] feedback item(s) from PR #{pr_number}")
        # ── 3b. Detect merge directives ───────────────────────────────────────
        merge_branches = self._parse_merge_directives(feedback)
        if merge_branches:
            console.print(
                f"  🔀 Merge directives found: {', '.join(f'[cyan]{b}[/cyan]' for b in merge_branches)}"
            )
        return {"feedback": feedback, "feedback_md": feedback_md, "merge_branches": merge_branches}

    def _revision_collect_files(
        self, pr_number: int, head_branch: str, issue_number: Optional[int], merge_branches: list
    ) -> dict:
        """Fetch design doc, current branch files, and merge-branch files. Returns dict with design/current_files/merge_branch_files."""
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
        # ── 5b. Fetch files from merge branches ───────────────────────────────
        merge_branch_files: dict[str, dict[str, str]] = {}
        for mb in merge_branches:
            mb_files = self._fetch_branch_files(mb)
            if mb_files:
                merge_branch_files[mb] = mb_files
                console.print(
                    f"  📂 Fetched [bold]{len(mb_files)}[/bold] file(s) from merge branch [cyan]{mb}[/cyan]"
                )
        return {"design": design, "current_files": current_files, "merge_branch_files": merge_branch_files}

    def _revision_build_augmented_design(
        self,
        design: str,
        head_branch: str,
        current_files: dict,
        merge_branch_files: dict,
        feedback_md: str,
    ) -> str:
        """Compose the full design document string augmented with current code, merge-branch files, and PR feedback."""
        current_files_block = "\n\n".join(
            f"### `{path}`\n```\n{self._safe_fence(content)}\n```"
            for path, content in current_files.items()
        )
        merge_branch_blocks = ""
        for mb, mb_files in merge_branch_files.items():
            mb_block = "\n\n".join(
                f"### `{path}`\n```\n{self._safe_fence(content)}\n```"
                for path, content in mb_files.items()
            )
            merge_branch_blocks += (
                f"\n\n---\n\n"
                f"## Files from Branch `{mb}` (incorporate these — make the implementation pass these tests)\n\n"
                f"{mb_block}"
            )
        return (
            f"{design}\n\n"
            f"---\n\n"
            f"## Current Code on Branch `{head_branch}`\n\n"
            f"{current_files_block}"
            f"{merge_branch_blocks}\n\n"
            f"---\n\n"
            f"{feedback_md}"
        )

    def _revision_build_modules(self, current_files: dict, merge_branch_files: dict) -> list:
        """Build the revision_modules list for the engineer agent."""
        merge_hint = ""
        if merge_branch_files:
            branch_names = ", ".join(f"`{b}`" for b in merge_branch_files)
            merge_hint = (
                f"\n\nFiles from merge branch(es) {branch_names} are included above. "
                f"Make your revised implementation pass those tests."
            )
        revision_modules = [
            {
                "name": "Revision",
                "description": (
                    f"Revise the existing code to address all PR feedback listed above. "
                    f"Return updated versions of these files: {', '.join(current_files.keys())}. "
                    f"Only change what is necessary to address the feedback."
                    f"{merge_hint}"
                ),
            }
        ]
        return revision_modules

    def _revision_run_engineer(
        self,
        pr_number: int,
        augmented_design: str,
        current_files: dict,
        merge_branch_files: dict,
        pr: dict,
        new_revision: int,
    ) -> tuple:
        """Run the engineer agent to produce revised files. Returns (error_dict, None) on failure or (None, revised_files)."""
        revision_modules = self._revision_build_modules(current_files, merge_branch_files)
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
            return {"status": "error", "reason": "engineer_returned_no_files"}, None
        return None, revised_files

    def _revision_commit_revised_files(
        self, pr_number: int, head_branch: str, new_revision: int, revised_files: dict
    ) -> Optional[dict]:
        """Commit all revised files to the branch. Returns an error dict on failure, None on success."""
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
        return None

    def _revision_commit_merge_files(
        self,
        pr_number: int,
        head_branch: str,
        revised_files: dict,
        current_files: dict,
        merge_branch_files: dict,
    ) -> None:
        """Commit any merge-branch files not already revised by the engineer or present on the branch."""
        merge_commit_errors: list[str] = []
        for mb, mb_files in merge_branch_files.items():
            for filepath, content in mb_files.items():
                if filepath in revised_files or filepath in current_files:
                    continue  # skip if engineer revised it OR if it already exists in the PR branch
                try:
                    self.target_github.commit_file(
                        path=filepath,
                        content=content,
                        message=f"feat: incorporate {filepath} from branch {mb}",
                        branch=head_branch,
                    )
                except RuntimeError as exc:
                    merge_commit_errors.append(f"{filepath}: {exc}")
                    console.print(f"  [yellow]⚠️  Could not commit merge file {filepath}: {exc}[/yellow]")
        if merge_commit_errors:
            self.target_github.add_pr_comment(
                pr_number,
                f"⚠️ Could not commit {len(merge_commit_errors)} merge-branch file(s):\n"
                + "\n".join(f"- `{e}`" for e in merge_commit_errors),
            )

    def _revision_run_reviewer_and_qa(
        self,
        revised_files: dict,
        design: str,
        project_name: str,
        head_branch: str,
        new_revision: int,
    ) -> tuple:
        """Run code review and QA passes, committing any new test files. Returns (rev_result, test_files)."""
        # Code Reviewer
        rev_result = self.reviewer.run(revised_files, design or "N/A", project_name)
        console.print(f"  🔍 Code review verdict: [bold]{rev_result.get('verdict', '?')}[/bold]")
        # QA Engineer
        qa_result = self.qa.run(revised_files, design or "N/A", project_name)
        test_files: dict[str, str] = qa_result.get("test_files", {})
        # TDD Reviewer — catches broken conftest patterns, bad imports, syntax errors
        if test_files:
            revised_tests, tdd_summary = self.tdd_reviewer.run(
                test_files, prd=design or "N/A", project_name=project_name
            )
            if revised_tests:
                test_files = revised_tests
            if tdd_summary:
                console.print(f"  🔎 TDD review: {tdd_summary[:120]}")
        for filepath, content in test_files.items():
            self.target_github.commit_file(
                path=filepath,
                content=content,
                message=f"test: revision {new_revision} — update tests [{filepath}]",
                branch=head_branch,
            )
        return rev_result, test_files

    def _revision_post_summary(
        self,
        pr_number: int,
        new_revision: int,
        feedback: list,
        revised_files: dict,
        rev_result: dict,
        test_files: dict,
        merge_branch_files: dict,
        current_rev: int,
    ) -> None:
        """Update the revision label and post a summary comment to the PR."""
        # ── 8. Update label and post summary comment ──────────────────────────
        old_label = f"ai-revision-{current_rev}" if current_rev > 0 else None
        new_label = f"ai-revision-{new_revision}"
        self.target_github.ensure_labels([
            {"name": new_label, "color": "0075ca", "description": f"AI revision round {new_revision}"}
        ])
        if old_label:
            self.target_github.remove_pr_label(pr_number, old_label)
        self.target_github.add_pr_label(pr_number, new_label)
        merge_branch_note = ""
        if merge_branch_files:
            names = ", ".join(f"`{b}`" for b in merge_branch_files)
            total_files = sum(len(v) for v in merge_branch_files.values())
            merge_branch_note = f"\n**Incorporated branches:** {names} ({total_files} file(s))\n"
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
            + merge_branch_note
        )
        self.target_github.add_pr_comment(pr_number, summary)

    def _revision_execute(
        self,
        pr_number: int,
        head_branch: str,
        augmented_design: str,
        files_ctx: dict,
        fb_ctx: dict,
        ctx: dict,
        new_revision: int,
    ) -> dict:
        """Orchestrate engineer run, commits, review, QA, and summary posting for a revision round."""
        eng_err, revised_files = self._revision_run_engineer(
            pr_number, augmented_design, files_ctx["current_files"],
            files_ctx["merge_branch_files"], ctx["pr"], new_revision,
        )
        if eng_err:
            return eng_err
        commit_err = self._revision_commit_revised_files(
            pr_number, head_branch, new_revision, revised_files
        )
        if commit_err:
            return commit_err
        self._revision_commit_merge_files(
            pr_number, head_branch, revised_files,
            files_ctx["current_files"], files_ctx["merge_branch_files"],
        )
        project_name = ctx["pr"].get("title", f"PR #{pr_number}").replace("[Implementation] ", "")
        rev_result, test_files = self._revision_run_reviewer_and_qa(
            revised_files, files_ctx["design"], project_name, head_branch, new_revision,
        )
        self._revision_post_summary(
            pr_number, new_revision, fb_ctx["feedback"], revised_files,
            rev_result, test_files, files_ctx["merge_branch_files"], ctx["current_rev"],
        )
        return {"status": "ok", "revision": new_revision, "files_updated": len(revised_files)}

    # ── Context-setup helpers (extracted from run()) ──────────────────────────

    def _resolve_target_repo(self, trigger_issue_body: Optional[str]) -> None:
        """Detect target project repo from trigger_issue_body and set self.target_github.

        If trigger_issue_body contains a 'Target repo:' directive pointing to a
        different repo than the tracker repo, a new GitHubClient is created for
        that repo.  Falls back to self.github when no override is present.
        """
        target_repo_override = parse_target_repo(trigger_issue_body or "")
        if target_repo_override and self.github and target_repo_override != self.github.repo:
            self.target_github = GitHubClient(repo=target_repo_override, github_token=self._github_token)
            console.print(f"  🎯 Targeting project repo: [bold]{target_repo_override}[/bold]")
        elif not self.target_github:
            self.target_github = self.github

    def _inject_repo_context(self) -> None:
        """Fetch the target repo file tree and prepend it to planning agents' system prompts."""
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

    def _inject_memory(self, active_repo: str) -> None:
        """Load recent memories for active_repo and prepend to agent system prompts."""
        memory_context = self.memory.recall(active_repo)
        if memory_context:
            console.print(f"  🧠 [dim]Loaded memory from {active_repo}[/dim]")
            for agent in (self.pm, self.architect, self.engineer,
                          self.junior_engineer, self.senior_engineer,
                          self.reviewer, self.qa, self.qa_planner):
                if agent.system_prompt is not None:
                    original = self._original_system_prompts.get(agent, agent.system_prompt)
                    agent.system_prompt = memory_context + "\n\n---\n\n" + original

    def _apply_skills_to_agents(self, matched_skills: list) -> None:
        """Inject matched skill blocks into each role agent's system prompt."""
        if not self.skill_loader:
            return
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

    def _inject_skills(self, trigger_issue_body: Optional[str], requirement: str, active_repo: str) -> None:
        """Detect skills relevant to this run and inject them into agent system prompts."""
        if not self.skill_loader:
            return
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
        # Inject skill blocks on top of memory-enriched prompts (reads _original_system_prompts to avoid stacking)
        self._apply_skills_to_agents(matched_skills)

    def _load_or_init_result(self, requirement: str, resume: bool) -> "PipelineResult":
        """Load a prior checkpoint for resumption, or return a fresh PipelineResult."""
        result = self._load_checkpoint(requirement) if resume else None
        if result:
            console.print(
                f"[bold yellow]⏭️  Resuming from checkpoint[/bold yellow] "
                f"(completed: {', '.join(result.completed_stages)})"
            )
        else:
            result = PipelineResult(requirement=requirement)
        return result

    def _extract_prior_context(self, trigger_issue_body: Optional[str]) -> None:
        """Extract 'Prior Work Context' block from trigger_issue_body into self._issue_prior_context."""
        _prior_marker = "\n\n---\n\n## 📜 Prior Work Context\n\n"
        if trigger_issue_body and _prior_marker in trigger_issue_body:
            self._issue_prior_context: str = trigger_issue_body[
                trigger_issue_body.index(_prior_marker) + len("\n\n---\n\n"):
            ]
        else:
            self._issue_prior_context = ""

    def _setup_progress_tracker(self, result: "PipelineResult") -> None:
        """Initialise self._tracker for this run, restoring state if resuming."""
        self._tracker = ProgressTracker(
            github=self.github,
            issue_number=result.issue_number,
            mode=self.progress_tracker_mode,
        )
        if result.progress_comment_id:
            # Resuming: restore comment slot and replay done stages before set_stages
            # so set_stages() deletes the old comment when re-posting
            self._tracker.restore(result.progress_comment_id)
            self._tracker.restore_stages(result.completed_stages)
        self._tracker.set_stages(self._expected_stages())
        # Keep result in sync with tracker's comment_id
        result.progress_comment_id = self._tracker.comment_id

    # ── Stage-loop helpers ────────────────────────────────────────────────────

    def _initialize_run(
        self,
        requirement: str,
        trigger_issue_body: Optional[str],
        resume: bool,
        issue_number: Optional[int],
        run_id: str,
        start_time: float,
    ) -> "PipelineResult":
        """Set up ledger, inject context, load checkpoint, configure tracker; return result."""
        ct = self._cost_tracking
        if ct.get("enabled", False):
            active_repo = str(
                self.target_github.repo if self.target_github else
                (self.github.repo if self.github else "local")
            )
            get_ledger().start_run(run_id, "", active_repo)  # project_name updated in _finish

        self._resolve_target_repo(trigger_issue_body)
        self._inject_repo_context()
        active_repo = str(self.target_github.repo if self.target_github else
                          (self.github.repo if self.github else "local"))
        self._inject_memory(active_repo)
        self._inject_skills(trigger_issue_body, requirement, active_repo)

        result = self._load_or_init_result(requirement, resume)
        self._extract_prior_context(trigger_issue_body)

        # Set run_id on result (new run or restored checkpoint)
        if not result.run_id:
            result.run_id = run_id

        # Pre-set issue_number if provided by caller (allows pause before PM creates it)
        if issue_number is not None and not result.issue_number:
            result.issue_number = issue_number

        self._setup_progress_tracker(result)
        return result

    def _run_standard_revision_loops(
        self,
        result: "PipelineResult",
        requirement: str,
        start_time: float,
    ) -> Optional["PipelineResult"]:
        """Run PM and Architect review loops for the standard (non-YAML) pipeline.

        Returns an early-exit PipelineResult if a loop fails, otherwise None.
        """
        if "pm_review_loop" not in result.completed_stages:
            ok = self._prd_revision_loop(result, requirement)
            if not ok:
                return self._finish(result, start_time)
        else:
            console.print("  ⏭️  [dim]PRD revision loop — skipped (checkpoint)[/dim]")

        if "architect_review_loop" not in result.completed_stages:
            ok = self._design_revision_loop(result)
            if not ok:
                return self._finish(result, start_time)
        else:
            console.print("  ⏭️  [dim]Design revision loop — skipped (checkpoint)[/dim]")

        return None

    def _run_preamble_stages(
        self,
        result: "PipelineResult",
        requirement: str,
        start_time: float,
    ) -> Optional["PipelineResult"]:
        """Run pre-loop stages: standard revision loops (if applicable) and RAG index.

        Returns an early-exit PipelineResult if a stage fails, otherwise None.
        """
        # ── Stage 1 + 2: hardcoded PM / Arch revision loops (standard pipeline only) ──
        if getattr(self, '_pipeline_yaml_stages', None) is None:
            early_exit = self._run_standard_revision_loops(result, requirement, start_time)
            if early_exit is not None:
                return early_exit

        # ── RAG index (always before engineer, not mode-dependent) ─────────────
        # Sync issue_number into tracker — PM may have just created the GitHub issue
        self._tracker.issue_number = result.issue_number
        if self.repo_auto_indexer and self.target_github and "rag_index" not in result.completed_stages:
            self._run_stage(
                "📦 RAG Index",
                "Indexing repo codebase into RAG...",
                result,
                lambda: self._stage_repo_index(result),
            )
            result.add_completed_stage("rag_index")

        return None

    def _collect_stage_batch(
        self,
        stage_list: list,
        i: int,
    ) -> "tuple[list, int]":
        """Collect a parallel batch starting at index *i*.

        Returns ``(batch, new_i)`` where *batch* is the list of stages to run
        together and *new_i* is the updated index for the outer loop.
        """
        stage = stage_list[i]
        if stage.parallel_group is not None:
            batch = [stage]
            j = i + 1
            while j < len(stage_list) and stage_list[j].parallel_group == stage.parallel_group:
                batch.append(stage_list[j])
                j += 1
            return batch, j
        return [stage], i + 1

    def _filter_runnable_stages(
        self,
        batch: list,
        result: "PipelineResult",
    ) -> list:
        """Filter *batch* to stages whose preconditions are met.

        Already-completed and skip_if-matching stages are logged and excluded.
        Returns the list of runnable stages.
        """
        runnable = []
        for s in batch:
            if s.checkpoint_key in result.completed_stages or s.name in result.completed_stages:
                console.print(f"  ⏭️  [dim]{s.label} — skipped (checkpoint)[/dim]")
                self._tracker.mark_skipped(s.checkpoint_key)
            elif s.skip_if(result):
                console.print(f"  ⏭️  [dim]{s.label} — skipped[/dim]")
                self._tracker.mark_skipped(s.checkpoint_key)
            else:
                runnable.append(s)
        return runnable

    def _execute_sequential_stage(
        self,
        s: "StageSpec",
        result: "PipelineResult",
        start_time: float,
    ) -> Optional["PipelineResult"]:
        """Execute a single sequential stage (loop block or regular).

        Returns an early-exit PipelineResult if the stage fails, otherwise None.
        """
        _stage_token = current_stage.set(s.checkpoint_key)
        try:
            if s.loop_stages:
                # Loop block from pipeline.yaml
                ok = self._run_loop_stage(s, result)
                if not ok:
                    # Can't use _abort_pipeline here — mark_failed must precede checkpoint save
                    self._tracker.mark_failed(s.checkpoint_key)
                    result.progress_comment_id = self._tracker.comment_id
                    self._save_checkpoint(result)
                    return self._finish(result, start_time)
            else:
                self._run_stage(
                    s.label, s.description, result,
                    lambda ss=s: ss.fn(result),
                    required_output_fields=s.required_output_fields,
                )
        finally:
            current_stage.reset(_stage_token)
        return None

    def _mark_batch_outcomes(
        self,
        runnable: list,
        result: "PipelineResult",
        stage_results: "dict[str, bool]",
        errors_before: int,
    ) -> bool:
        """Mark each stage in the batch as done or failed.

        For parallel batches uses *stage_results*; for sequential batches
        compares the error count.  Returns True if any stage failed.
        Sequential done-marking is delegated to _finalize_stage_batch → _mark_sequential_stage_done.
        """
        any_failed = False
        if len(runnable) > 1:
            for s in runnable:
                if not stage_results.get(s.checkpoint_key, True):
                    self._tracker.mark_failed(
                        s.checkpoint_key,
                        str(result.errors[-1]) if result.errors else "",
                    )
                    any_failed = True
                else:
                    if s.name == "senior_engineer":
                        result.add_completed_stage("engineer")
                    result.add_completed_stage(s.checkpoint_key)
                    self._tracker.mark_done(s.checkpoint_key)
        elif len(result.errors) > errors_before:
            any_failed = True
            self._tracker.mark_failed(runnable[0].checkpoint_key, str(result.errors[-1]))
        return any_failed

    def _finalize_stage_batch(
        self,
        runnable: list,
        result: "PipelineResult",
        stage_results: "dict[str, bool]",
        errors_before: int,
        start_time: float,
    ) -> Optional["PipelineResult"]:
        """Mark outcomes, save checkpoint, check stop_if; return early exit or None."""
        any_failed = self._mark_batch_outcomes(runnable, result, stage_results, errors_before)

        if any_failed:
            return self._abort_pipeline(result, start_time)

        # Mark sequential stage done (parallel stages handled in _mark_batch_outcomes)
        if len(runnable) == 1:
            self._mark_sequential_stage_done(runnable[0], result)

        result.progress_comment_id = self._tracker.comment_id
        self._save_checkpoint(result)

        # Early pipeline stop — only for sequential stages.
        # NOTE: checkpoint saved before stop_if check (intentional): on resume,
        # the completed stage is skipped and the pipeline continues from the next.
        if len(runnable) == 1:
            s = runnable[0]
            if s.stop_if(result):
                console.print(
                    f"\n  🛑 [bold yellow]{s.stop_message or 'Pipeline stopped early.'}[/bold yellow]"
                )
                return self._finish(result, start_time)

        return None

    def _mark_sequential_stage_done(
        self,
        s: "StageSpec",
        result: "PipelineResult",
    ) -> None:
        """Mark a sequential stage complete, including the backward-compat ``engineer`` alias."""
        if s.name == "senior_engineer":
            result.add_completed_stage("engineer")
        result.add_completed_stage(s.checkpoint_key)
        self._tracker.mark_done(s.checkpoint_key)

    def _execute_stage_batch(
        self,
        runnable: list,
        result: "PipelineResult",
        start_time: float,
    ) -> "tuple[Optional[PipelineResult], dict[str, bool]]":
        """Dispatch a batch to parallel or sequential execution.

        Returns ``(early_exit, stage_results)`` where *early_exit* is a
        PipelineResult when the batch failed (else None) and *stage_results*
        maps checkpoint keys to success booleans (parallel batches only).
        """
        if len(runnable) > 1:
            stage_results: dict[str, bool] = {}  # checkpoint_key → succeeded
            early_exit = self._run_parallel_batch(runnable, result, start_time, stage_results)
            return early_exit, stage_results
        stage_results = {}
        early_exit = self._execute_sequential_stage(runnable[0], result, start_time)
        return early_exit, stage_results

    def _abort_pipeline(
        self,
        result: "PipelineResult",
        start_time: float,
    ) -> "PipelineResult":
        """Save checkpoint and return partial result when the pipeline is aborted."""
        result.progress_comment_id = self._tracker.comment_id
        self._save_checkpoint(result)
        return self._finish(result, start_time)

    def _run_stage_loop(
        self,
        result: "PipelineResult",
        start_time: float,
    ) -> "PipelineResult":
        """Iterate the mode-determined stage list until all stages complete or one fails."""
        stage_list = self._build_stage_list()
        i = 0
        while i < len(stage_list):
            batch, i = self._collect_stage_batch(stage_list, i)
            runnable = self._filter_runnable_stages(batch, result)

            if not runnable:
                continue

            for s in runnable:
                self._tracker.mark_in_progress(s.checkpoint_key)

            errors_before = len(result.errors)
            early_exit, stage_results = self._execute_stage_batch(runnable, result, start_time)
            if early_exit is not None:
                return early_exit

            early_exit = self._finalize_stage_batch(
                runnable, result, stage_results, errors_before, start_time
            )
            if early_exit is not None:
                return early_exit

        # Pipeline complete — remove checkpoint
        self._clear_checkpoint(result)
        return self._finish(result, start_time)

    def run(self, requirement: str, trigger_issue_body: Optional[str] = None, resume: bool = True, issue_number: Optional[int] = None) -> PipelineResult:
        """Execute the full pipeline for *requirement* and return a PipelineResult."""
        start_time = time.time()
        run_id = str(uuid.uuid4())
        result = self._initialize_run(
            requirement, trigger_issue_body, resume, issue_number, run_id, start_time
        )

        console.print(Panel.fit(
            f"[bold cyan]🏢 AI Software House Pipeline[/bold cyan]\n"
            f"[dim]{requirement[:120]}{'...' if len(requirement) > 120 else ''}[/dim]",
            border_style="cyan",
        ))

        try:
            early_exit = self._run_preamble_stages(result, requirement, start_time)
            if early_exit is not None:
                return early_exit
            return self._run_stage_loop(result, start_time)

        except _ShutdownRequested:
            # Graceful shutdown (SIGTERM/SIGINT): save checkpoint so resume=True picks up
            # from the last *completed* stage, not the interrupted one.
            logging.info("Graceful shutdown: pipeline interrupted before completion")
            return self._abort_pipeline(result, start_time)
        except BudgetExceededError:
            # Token budget exhausted: save checkpoint so partial progress is not lost.
            logging.warning("Token budget exceeded — saving checkpoint and aborting pipeline")
            result.add_error("Pipeline aborted: token budget exceeded")
            return self._abort_pipeline(result, start_time)


    # ── Stage implementations ────────────────────────────────────────────────

    def _stage_pm(self, result: PipelineResult, requirement: str) -> None:
        ctx = self._build_clarification_context(result.clarification_history, stage="pm")
        prior_ctx = getattr(self, "_issue_prior_context", "")
        extra = "\n\n".join(filter(None, [ctx, prior_ctx]))
        effective_req = f"{extra}\n\n---\n\n{requirement}" if extra else requirement
        synthesis = result.discussion_synthesis or ""
        if self.github:
            pm_result = self.pm.run_with_github(effective_req, self.github, discussion_synthesis=synthesis)
            result.issue_number = pm_result["issue_number"]
            result.issue_url = pm_result["issue_url"]
        else:
            pm_result = self.pm.run(effective_req, discussion_synthesis=synthesis)
        if not pm_result.get("prd", "").strip():
            raise RuntimeError("Product Manager produced an empty PRD — LLM may have returned no content.")
        result.prd = pm_result["prd"]
        result.project_name = pm_result["project_name"]

    def _stage_architect(self, result: PipelineResult) -> None:
        ctx = self._build_clarification_context(result.clarification_history, stage="architect")
        effective_prd = f"{ctx}\n\n---\n\n{result.prd}" if ctx else result.prd
        # Always run LLM first so result.design is set even if GitHub post fails.
        arch_result = self.architect.run(effective_prd, result.project_name)
        if not arch_result.get("design", "").strip():
            raise RuntimeError("Architect produced an empty design — LLM may have returned no content.")
        result.design = arch_result["design"]
        result.modules = arch_result["modules"]
        # Extract naming_contract if the architect included it
        result.naming_contract = arch_result.get("naming_contract", "")
        if self.github and result.issue_number:
            self.github.add_issue_comment(
                result.issue_number,
                f"## 🏗️ System Design (Architect)\n\n{result.design}",
            )

    def _stage_pm_reviewer(self, result: PipelineResult, requirement: str) -> None:
        """Review the PM's PRD. If revision needed, update prd + project_name."""
        if not result.prd or not result.prd.strip():
            raise RuntimeError(
                "Cannot review PRD: result.prd is empty. "
                "The PM stage may have failed to produce output."
            )
        # Run LLM first; post to GitHub separately so a transient 502 doesn't
        # lose the review result and cause a duplicate comment on the next retry.
        rev_result = self.pm_reviewer.run(result.prd, requirement, result.project_name)

        if self.github and result.issue_number:
            verdict_emoji = {
                PMReviewerAgent.VERDICT_APPROVED: "✅",
                PMReviewerAgent.VERDICT_SUGGESTIONS: "💡",
                PMReviewerAgent.VERDICT_REVISION: "🔄",
            }.get(rev_result["verdict"], "🔍")
            self.github.add_issue_comment(
                result.issue_number,
                f"## {verdict_emoji} PRD Review (PMReviewer)\n\n{rev_result['review']}",
            )

        result.prd_review = rev_result["review"]
        result.prd_verdict = rev_result["verdict"]
        # Normalize for loop exit conditions (pipeline.yaml `until: APPROVED` / `until: NEEDS_REVISION`)
        result.last_verdict = "NEEDS_REVISION" if rev_result["needs_revision"] else "APPROVED"

        # Store reviewer's draft for use in run_revision() (new revision loop)
        result.prd_reviewer_draft = rev_result.get("revised_prd") or ""
        # Legacy single-pass behaviour preserved when loop is disabled (max_prd_revisions == 0)
        if getattr(self, "max_prd_revisions", 3) == 0 and rev_result["needs_revision"] and rev_result["revised_prd"]:
            result.prd = rev_result["revised_prd"]
            result.project_name = rev_result["revised_project_name"]

    def _stage_pm_revision(self, result: PipelineResult, requirement: str, round_num: int) -> None:
        """PM rewrites the PRD using reviewer feedback and reviewer's draft."""
        previous_prd = result.prd
        pm_result = self.pm.run_revision(
            original_prd=result.prd,
            review=result.prd_review,
            draft_revision=result.prd_reviewer_draft,
            requirement=requirement,
            project_name=result.project_name,
        )
        revised_prd = pm_result.get("prd", "").strip()
        if revised_prd:
            result.prd = pm_result["prd"]
            result.project_name = pm_result["project_name"]
        else:
            console.print("  ⚠️  [yellow]PM revision returned empty PRD — keeping previous version.[/yellow]")
            result.prd = previous_prd
        result.prd_revision_count = round_num
        # Post revised PRD to GitHub so the reviewer (and humans) can read it.
        if self.github and result.issue_number:
            self.github.add_issue_comment(
                result.issue_number,
                f"## 📋 Revised PRD (Product Manager — round {round_num})\n\n{result.prd}",
            )

    def _prd_revision_loop(self, result: PipelineResult, requirement: str) -> bool:
        """Run PM → PM Reviewer revision loop (up to max_prd_revisions rounds).

        Returns True if pipeline should continue, False if it should halt.
        """
        # Step 1: PM writes initial PRD
        if "pm" not in result.completed_stages:
            self._tracker.mark_in_progress("pm")
            try:
                self._run_stage(
                    "📋 Product Manager",
                    "Analyzing requirements & writing PRD...",
                    result,
                    lambda: self._stage_pm(result, requirement),
                    required_output_fields=["prd"],
                )
            except ClarificationNeeded as exc:
                self._tracker.mark_failed("pm", "Awaiting clarification")
                result.progress_comment_id = self._tracker.comment_id
                self._pause_for_clarification(result, "pm", exc.questions)
                return False
            if result.errors:
                self._tracker.mark_failed("pm", str(result.errors[-1]))
                result.progress_comment_id = self._tracker.comment_id
                self._save_checkpoint(result)
                return False
            result.add_completed_stage("pm")
            self._tracker.mark_done("pm")
            result.progress_comment_id = self._tracker.comment_id
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]📋 Product Manager — skipped (checkpoint)[/dim]")

        # Step 2: Initial PM Reviewer pass
        if "pm_reviewer" not in result.completed_stages:
            self._tracker.mark_in_progress("pm_reviewer")
            self._run_stage(
                "📝 PM Reviewer",
                "Reviewing PRD for completeness...",
                result,
                lambda: self._stage_pm_reviewer(result, requirement),
                required_output_fields=["prd_review", "prd_verdict"],
            )
            if result.errors:
                self._tracker.mark_failed("pm_reviewer", str(result.errors[-1]))
                result.progress_comment_id = self._tracker.comment_id
                self._save_checkpoint(result)
                return False
            result.add_completed_stage("pm_reviewer")
            self._tracker.mark_done("pm_reviewer")
            result.progress_comment_id = self._tracker.comment_id
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]📝 PM Reviewer — skipped (checkpoint)[/dim]")

        # Step 3: Revision loop (skip if disabled)
        if self.max_prd_revisions == 0:
            result.add_completed_stage("pm_review_loop")
            self._tracker.mark_done("pm_review_loop")
            result.progress_comment_id = self._tracker.comment_id
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
            self._tracker.add_stage(ProgressStage(key, f"🔄 PRD Revision {round_num}"))
            self._tracker.mark_in_progress(key)
            self._run_stage(
                "📋 Product Manager",
                f"Revising PRD based on reviewer feedback (round {round_num})...",
                result,
                lambda rn=round_num: self._stage_pm_revision(result, requirement, rn),
                required_output_fields=["prd"],
            )
            if result.errors:
                self._tracker.mark_failed(key, str(result.errors[-1]))
                result.progress_comment_id = self._tracker.comment_id
                self._save_checkpoint(result)
                return False

            # Reviewer re-checks
            self._run_stage(
                "📝 PM Reviewer",
                f"Re-reviewing revised PRD (round {round_num})...",
                result,
                lambda: self._stage_pm_reviewer(result, requirement),
                required_output_fields=["prd_review", "prd_verdict"],
            )
            if result.errors:
                self._tracker.mark_failed(key, str(result.errors[-1]))
                result.progress_comment_id = self._tracker.comment_id
                self._save_checkpoint(result)
                return False

            result.add_completed_stage(key)
            self._tracker.mark_done(key)
            result.progress_comment_id = self._tracker.comment_id
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
                    result.add_completed_stage("pm_review_loop")
                    self._tracker.mark_done("pm_review_loop")
                    result.progress_comment_id = self._tracker.comment_id
                    self._save_checkpoint(result)
                    return False

        if result.prd_verdict != PMReviewerAgent.VERDICT_REVISION:
            console.print(
                f"  ✅ [green]PRD APPROVED (round {result.prd_revision_count})[/green]"
            )

        result.add_completed_stage("pm_review_loop")
        self._tracker.mark_done("pm_review_loop")
        result.progress_comment_id = self._tracker.comment_id
        self._save_checkpoint(result)
        return True

    def _stage_arch_revision(self, result: PipelineResult, round_num: int) -> None:
        """Ask ArchitectAgent to revise the design based on reviewer feedback."""
        previous_design = result.design
        rev_result = self.architect.run_revision(
            original_design=result.design,
            prd=result.prd,
            review=result.design_review or "",
            draft_revision=result.design_reviewer_draft or "",
            project_name=result.project_name or "",
        )
        revised = rev_result.get("design", "").strip()
        if revised:
            result.design = rev_result["design"]
        else:
            console.print("  ⚠️  [yellow]Architect revision returned empty — keeping previous design.[/yellow]")
            result.design = previous_design
        if rev_result.get("modules"):
            result.modules = rev_result["modules"]
        result.design_revision_count = round_num
        # Post revised design to GitHub so the reviewer (and humans) can read it.
        if self.github and result.issue_number:
            self.github.add_issue_comment(
                result.issue_number,
                f"## 🏗️ Revised System Design (Architect — round {round_num})\n\n{result.design}",
            )

    def _design_revision_loop(self, result: PipelineResult) -> bool:
        """Run Architect + Architect Reviewer in a feedback loop, up to max_design_revisions rounds.

        Returns True if pipeline should continue, False if it should halt.
        """
        # Step 1: Architect
        if "architect" not in result.completed_stages:
            self._tracker.mark_in_progress("architect")
            try:
                self._run_stage(
                    "🏗️  Architect",
                    "Designing system architecture...",
                    result,
                    lambda: self._stage_architect(result),
                    required_output_fields=["design"],
                )
            except ClarificationNeeded as exc:
                self._tracker.mark_failed("architect", "Awaiting clarification")
                result.progress_comment_id = self._tracker.comment_id
                self._pause_for_clarification(result, "architect", exc.questions)
                return False
            if result.errors:
                self._tracker.mark_failed("architect", str(result.errors[-1]))
                result.progress_comment_id = self._tracker.comment_id
                self._save_checkpoint(result)
                return False
            result.add_completed_stage("architect")
            self._tracker.mark_done("architect")
            result.progress_comment_id = self._tracker.comment_id
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]🏗️  Architect — skipped (checkpoint)[/dim]")

        # Step 2: Initial Architect Reviewer pass
        if "architect_reviewer" not in result.completed_stages:
            self._tracker.mark_in_progress("architect_reviewer")
            self._run_stage(
                "🔎 Architect Reviewer",
                "Reviewing system design...",
                result,
                lambda: self._stage_architect_reviewer(result),
                required_output_fields=["design_review", "design_verdict"],
            )
            if result.errors:
                self._tracker.mark_failed("architect_reviewer", str(result.errors[-1]))
                result.progress_comment_id = self._tracker.comment_id
                self._save_checkpoint(result)
                return False
            result.add_completed_stage("architect_reviewer")
            self._tracker.mark_done("architect_reviewer")
            result.progress_comment_id = self._tracker.comment_id
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]🔎 Architect Reviewer — skipped (checkpoint)[/dim]")

        # Step 3: Revision loop (skip if disabled)
        if self.max_design_revisions == 0:
            result.add_completed_stage("architect_review_loop")
            self._tracker.mark_done("architect_review_loop")
            result.progress_comment_id = self._tracker.comment_id
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
            self._tracker.add_stage(ProgressStage(key, f"🔄 Design Revision {round_num}"))
            self._tracker.mark_in_progress(key)
            self._run_stage(
                "🏗️  Architect",
                f"Revising design based on reviewer feedback (round {round_num})...",
                result,
                lambda rn=round_num: self._stage_arch_revision(result, rn),
                required_output_fields=["design"],
            )
            if result.errors:
                self._tracker.mark_failed(key, str(result.errors[-1]))
                result.progress_comment_id = self._tracker.comment_id
                self._save_checkpoint(result)
                return False

            # Reviewer re-checks
            self._run_stage(
                "🔎 Architect Reviewer",
                f"Re-reviewing revised design (round {round_num})...",
                result,
                lambda: self._stage_architect_reviewer(result),
                required_output_fields=["design_review", "design_verdict"],
            )
            if result.errors:
                self._tracker.mark_failed(key, str(result.errors[-1]))
                result.progress_comment_id = self._tracker.comment_id
                self._save_checkpoint(result)
                return False

            result.add_completed_stage(key)
            self._tracker.mark_done(key)
            result.progress_comment_id = self._tracker.comment_id
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
                    result.add_completed_stage("architect_review_loop")
                    self._tracker.mark_done("architect_review_loop")
                    result.progress_comment_id = self._tracker.comment_id
                    self._save_checkpoint(result)
                    return False

        if result.design_verdict != ArchitectReviewerAgent.VERDICT_REVISION:
            console.print(
                f"  ✅ [green]DESIGN APPROVED (round {result.design_revision_count})[/green]"
            )

        result.add_completed_stage("architect_review_loop")
        self._tracker.mark_done("architect_review_loop")
        result.progress_comment_id = self._tracker.comment_id
        self._save_checkpoint(result)
        return True

    def _stage_architect_reviewer(self, result: PipelineResult) -> None:
        """Review the Architect's design. Store draft; only self-patch when max_design_revisions == 0."""
        if not result.design or not result.design.strip():
            raise RuntimeError(
                "Cannot review design: result.design is empty. "
                "The architect stage may have failed to produce output."
            )
        if self.github and result.issue_number:
            rev_result = self.architect_reviewer.run_with_github(
                result.design, result.prd, result.project_name, self.github, result.issue_number
            )
        else:
            rev_result = self.architect_reviewer.run(result.design, result.prd, result.project_name)

        result.design_review = rev_result["review"]
        result.design_verdict = rev_result["verdict"]
        # Normalize for loop exit conditions
        result.last_verdict = "NEEDS_REVISION" if rev_result["needs_revision"] else "APPROVED"
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
        engineer_context = ""
        try:
            engineer_context = self._build_engineer_context(result.design, self.target_github)
        except Exception as exc:
            logger.warning("_build_engineer_context failed (non-fatal): %s", exc)
        if engineer_context:
            framework_context = (framework_context + "\n\n" + engineer_context) if framework_context else engineer_context
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
        # Run LLM first; post to GitHub separately so a transient 502 doesn't
        # lose the review result and cause a duplicate comment on the next retry.
        rev_result = self.reviewer.run(result.all_files, result.prd, result.project_name)
        if self.target_github and result.pr_number:
            self.target_github.add_pr_review(
                result.pr_number,
                body=f"## 🔍 Code Review (CodeReviewerAgent)\n\n{rev_result['review']}",
                event="COMMENT",
            )
        result.review = rev_result["review"]
        result.verdict = rev_result["verdict"]

    def _stage_qa_planner(self, result: PipelineResult) -> None:
        """QA Planner produces a structured test plan before QA Engineer writes tests."""
        cross_repo = self.target_github is not self.github and self.target_github is not None
        github_client = self.github  # test plan posted to tracker issue

        repo = github_client.repo if github_client and hasattr(github_client, "repo") else ""
        # Run LLM first; post to GitHub separately so a transient 502 doesn't
        # lose the plan and cause a duplicate comment on the next retry.
        plan_result = self.qa_planner.run(
            result.prd, result.design, result.all_files, result.project_name, repo=repo
        )

        if github_client and result.issue_number:
            status = "✅" if plan_result["success"] else "⚠️"
            ac_count = len(plan_result["acceptance_criteria"])
            summary = f"{status} **{ac_count} acceptance criteria identified**" if ac_count else status
            comment_body = f"## 📋 Test Plan ({summary})\n\n{plan_result['test_plan']}"
            pr_number = result.pr_number if not cross_repo else None
            if pr_number:
                github_client.add_pr_comment(pr_number, comment_body)
            else:
                github_client.add_issue_comment(result.issue_number, comment_body)

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
            # Index test files into RAG so Engineer can search test expectations
            if getattr(self, "repo_auto_indexer", None):
                try:
                    safe = "".join(
                        c if c.isalnum() or c in "-_" else "_"
                        for c in project_name.lower()
                    )
                    project_dir = str((self.workspace_dir / safe).resolve())
                    self.repo_auto_indexer.index_local_dir(project_dir)
                    _log.info(
                        "[qa_write] indexed %d test file(s) into RAG",
                        len(result.test_files),
                    )
                except Exception as exc:
                    _log.warning("[qa_write] RAG test indexing failed (non-fatal): %s", exc)
        else:
            console.print("[yellow]⚠️  No test files generated[/yellow]")
            return

        # Optionally commit test files to a new branch immediately (tdd_commit_tests: true).
        # This lets engineers see the tests in GitHub before writing implementation code.
        if not self.tdd_commit_tests:
            return
        gh = self.target_github or (self.github if self.use_github else None)
        if not gh:
            return

        console.print("[cyan]📤 Committing test files to branch (tdd_commit_tests=true)…[/cyan]")
        self._commit_and_open_pr(
            result=result,
            files=result.test_files,
            branch_prefix=self.branch_prefix,
            commit_msg_prefix="test(tdd): add generated test files",
            title_prefix="TDD: tests for",
            body_header="## 🧪 TDD — Tests written before implementation\n\nTest files generated by QA Engineer. Implementation to follow.",
        )
        if result.pr_url:
            console.print(f"[green]✅ Tests committed — PR: {result.pr_url}[/green]")
        elif result.branch:
            console.print(f"[green]✅ Tests committed to branch: {result.branch}[/green]")

    def _stage_tdd_review(self, result: PipelineResult) -> None:
        """Review and auto-fix TDD test files before execution."""
        test_files = result.test_files
        if not test_files:
            _log.info("TDD review: no test files to review, skipping")
            return
        prd = getattr(result, "prd", "") or ""
        project_name = result.project_name or "Project"
        _log.info("TDD review: reviewing %d test files", len(test_files))
        console.print(f"\n[bold cyan]🔎 TDD Reviewer[/bold cyan]")
        revised, summary = self.tdd_reviewer.run(
            test_files, prd=prd, project_name=project_name
        )
        result.tdd_review_summary = summary
        result.test_files = revised
        if summary:
            _log.info("TDD review summary: %s", summary[:200])
            console.print(f"[green]✅ TDD review complete ({len(revised)} file(s))[/green]")

    def _stage_contract_validate(self, result: PipelineResult) -> None:
        """Validate test files against naming_contract.yaml (if present)."""
        if not result.test_files or not result.naming_contract:
            log.info("contract_validate: no test files or no naming contract — skipping")
            return
        console.print("\n[bold cyan]📋 Contract Validator[/bold cyan]")
        validation = self.contract_validator.validate(
            contract_yaml=result.naming_contract,
            files=result.test_files,
        )
        result.contract_validation_passed = validation["passed"]
        result.contract_divergences = validation.get("divergences", [])
        if validation.get("skipped"):
            console.print("[yellow]⚠️  Contract validation skipped (no contract)[/yellow]")
            return
        if not validation["passed"]:
            n = len(result.contract_divergences)
            console.print(f"[yellow]⚠️  Contract validation found {n} divergence(s)[/yellow]")
            for d in result.contract_divergences[:5]:
                console.print(f"  • {d.get('file', '?')}: {d.get('issue', '?')}")
            log.warning("Contract divergences: %s", result.contract_divergences)
        else:
            console.print("[green]✅ Contract validation passed[/green]")

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

        # Sanitise requirements-test.txt — strip blank lines, comments, markdown
        # table rows (|...|), and any line that doesn't look like a valid pip
        # specifier.  The QA Planner sometimes writes its test-plan table into
        # this file; leaving those lines causes `pip install` to fail immediately
        # on every fix attempt before pytest even runs.
        raw_lines = req_file.read_text(encoding="utf-8").splitlines()
        clean_lines = []
        for line in raw_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # Skip markdown table rows and headers (|...|, ----, ====)
            if stripped.startswith("|") or set(stripped) <= set("-="):
                continue
            # Skip lines that contain spaces but don't look like pip extras/URLs
            # (e.g. prose sentences, backtick code, etc.)
            if " " in stripped and not any(
                stripped.startswith(p) for p in ("git+", "http://", "https://", "-r ", "-c ", "-e ")
            ):
                continue
            clean_lines.append(stripped)
        if not clean_lines:
            clean_lines = ["pytest", "pytest-cov", "pytest-timeout", "httpx"]
        req_file.write_text("\n".join(clean_lines) + "\n", encoding="utf-8")

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
        """Run deployment smoke tests via the configured backend."""
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in result.project_name.lower())
        project_dir = self.workspace_dir / safe

        deploy_result = self.deployment_tester.run_smoke_tests(
            project_dir, issue_number=result.issue_number
        )

        if deploy_result.skipped:
            result.deploy_tests_passed = None
            result.deploy_test_results = ""
            return

        passed = deploy_result.passed
        output = deploy_result.output
        vm_name = deploy_result.vm_name
        vm_ip = deploy_result.vm_ip
        duration = deploy_result.duration_s

        status_emoji = "✅" if passed else "❌"
        status_text = "Passed" if passed else "Failed"

        if vm_name is not None:
            icon = "🚀"
            backend_label = "libvirt"
        else:
            icon = "🐳"
            backend_label = "docker"

        console.print(f"    {icon} Deployment tests [{backend_label}]: {status_emoji} {status_text}")

        lines = output.strip().splitlines()
        for line in lines[-20:]:
            console.print(f"    [dim]{line}[/dim]")

        result.deploy_test_results = output
        result.deploy_tests_passed = passed

        if self.target_github and result.pr_number:
            truncated = "\n".join(lines[-60:]) if len(lines) > 60 else output
            duration_str = f"{int(duration // 60)}m {int(duration % 60)}s" if duration >= 60 else f"{int(duration)}s"

            if vm_name and vm_ip:
                virt_host = self._deploy_cfg.get("virt_host", "virt_host")
                vm_user = self._deploy_cfg.get("vm_user", "ubuntu")
                extra = (
                    f"\n**VM:** `{vm_name}` @ `{vm_ip}`\n"
                    f"**Access:** `ssh {virt_host}` then `ssh {vm_user}@{vm_ip}`\n"
                )
            elif vm_name:
                extra = f"\n**VM:** `{vm_name}`  |  **Duration:** {duration_str}\n"
            else:
                extra = f"\n**Duration:** {duration_str}\n"

            comment = (
                f"## {icon} Deployment Test Results [{backend_label}]\n\n"
                f"**Status:** {status_emoji} {status_text}{extra}\n"
                f"```\n{truncated}\n```"
            )
            self.target_github.add_pr_comment(result.pr_number, comment)

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

    @staticmethod
    def _parse_triage_verdict(text) -> dict:
        """Parse VERDICT and EDITORIAL_NOTES from triage discussion synthesis.

        Returns {"verdict": "PUBLISH"|"SKIP", "notes": str}.
        Always returns PUBLISH on any parse failure (fail-open — never silently drops a story).
        """
        try:
            if not isinstance(text, str):
                return {"verdict": "PUBLISH", "notes": ""}
            verdict_match = re.search(r"VERDICT\s*:\s*(PUBLISH|SKIP)", text, re.IGNORECASE)
            if not verdict_match:
                return {"verdict": "PUBLISH", "notes": ""}
            verdict = verdict_match.group(1).upper()
            notes_match = re.search(r"EDITORIAL_NOTES\s*:\s*(.+(?:\n.+)*)", text, re.IGNORECASE)
            notes = notes_match.group(1).strip() if notes_match else ""
            return {"verdict": verdict, "notes": notes}
        except Exception:
            return {"verdict": "PUBLISH", "notes": ""}

    def _get_tracker_adapter(self):
        """Return a TrackerAdapter if intake_triage is enabled, else None.

        Result is cached on self._cached_tracker_adapter to avoid repeated
        config lookups within a pipeline run.
        """
        if hasattr(self, "_cached_tracker_adapter"):
            return self._cached_tracker_adapter
        cfg_dict = self._raw_cfg
        it_cfg_raw = cfg_dict.get("intake_triage", {}) if isinstance(cfg_dict, dict) else {}
        if not it_cfg_raw.get("enabled", False):
            self._cached_tracker_adapter = None
            return None
        try:
            from config_schema import IntakeTriageConfig
            from intake_triage import _make_adapter
            it = IntakeTriageConfig(**it_cfg_raw)
            gh = getattr(self, "github", None) or getattr(self, "target_github", None)
            repo = str(getattr(gh, "repo", "")) if gh else ""
            self._cached_tracker_adapter = _make_adapter(it, repo)
        except Exception as exc:
            log.warning("_get_tracker_adapter: failed to build adapter: %s", exc)
            self._cached_tracker_adapter = None
        return self._cached_tracker_adapter

    def _intake_triage_approved(self, result) -> bool:
        """Check if item was already approved by batch intake triage.

        Sets result.editorial_verdict and result.editorial_notes if approved.
        Returns True if fast-pass should apply.
        """
        adapter = self._get_tracker_adapter()
        if adapter is None:
            return False
        try:
            approved, notes = adapter.is_approved(str(result.issue_number))
        except Exception as exc:
            log.warning("_intake_triage_approved: adapter error (%s) — proceeding with per-story triage", exc)
            return False
        if approved:
            result.editorial_verdict = "PUBLISH"
            result.editorial_notes = notes
        return approved

    def _issue_has_trigger_label(self, result) -> bool:
        """Return True if the GitHub issue already carries the intake triage trigger label (e.g. 'press').

        Falls back to False on any error so that triage still runs rather than silently skipping.
        """
        if not result.issue_number:
            return False
        cfg_dict = self._raw_cfg
        it_cfg_raw = cfg_dict.get("intake_triage", {}) if isinstance(cfg_dict, dict) else {}
        trigger_label = (it_cfg_raw.get("labels") or {}).get("trigger", "press")
        gh = getattr(self, "target_github", None) or getattr(self, "github", None)
        if gh is None:
            return False
        try:
            issue = gh.get_issue(int(result.issue_number))
            label_names = {lb["name"] for lb in issue.get("labels", [])}
            return trigger_label in label_names
        except Exception as exc:
            log.warning("_issue_has_trigger_label: could not fetch labels for #%s (%s) — proceeding with triage", result.issue_number, exc)
            return False

    def _stage_news_triage(self, result: "PipelineResult") -> None:
        """Run the editorial triage discussion and act on the verdict.

        PUBLISH: stores editorial_verdict + editorial_notes on result; pipeline continues.
        SKIP:    posts a comment to the GitHub issue, closes it, sets editorial_verdict=SKIP.
                 The stage registry's stop_if=lambda r: r.editorial_verdict=="SKIP" halts the pipeline.
        Fail-open: any exception → PUBLISH; story is never silently dropped.
        """
        # ── Fast-pass if already approved by batch intake triage ─────────────
        if self._intake_triage_approved(result):
            log.info("news_triage: batch intake triage already approved this item — fast-pass")
            return

        # Inject triage scope from config (DiscussionAgent reads it via context_fields)
        press_cfg = self._press_cfg
        triage_cfg = press_cfg.get("triage", {}) or {}
        result.triage_scope = str(triage_cfg.get("scope", "")).strip()

        # ── Fast-pass if trigger label already present and config allows it ──
        if triage_cfg.get("skip_if_trigger_label", False):
            if self._issue_has_trigger_label(result):
                log.info("news_triage: trigger label already present — skip_if_trigger_label fast-pass")
                result.editorial_verdict = "PUBLISH"
                result.editorial_notes = "Pre-approved: trigger label already applied."
                return

        discussions_dir = getattr(self, "_discussions_dir", None) or Path(__file__).parent / "discussions"
        config_path = str(discussions_dir / "news-triage.yaml")
        try:
            self._stage_discuss(result, config_path=config_path)
        except Exception as exc:
            log.warning("_stage_news_triage: discussion failed (%s) — defaulting to PUBLISH (fail-open)", exc)
            result.editorial_verdict = "PUBLISH"
            result.editorial_notes = ""
            return

        synthesis = result.discussion_synthesis or ""
        parsed = self._parse_triage_verdict(synthesis)
        result.editorial_verdict = parsed["verdict"]
        result.editorial_notes = parsed["notes"]

        if parsed["verdict"] == "SKIP":
            log.info("Editorial triage SKIP: %s", parsed["notes"])
            console.print(f"  🚫 [bold yellow]Editorial triage: SKIP[/bold yellow] — {parsed['notes']}")
            gh = self.target_github or self.github
            if gh and result.issue_number:
                comment = (
                    f"## 🚫 Editorial Triage: SKIP\n\n"
                    f"**Reason:** {parsed['notes']}\n\n"
                    f"<details><summary>Discussion summary</summary>\n\n{synthesis}\n\n</details>\n\n"
                    f"_This story was reviewed by the editorial team and will not be published._"
                )
                try:
                    gh.add_issue_comment(result.issue_number, comment)
                except Exception as exc:
                    log.warning("_stage_news_triage: failed to post skip comment: %s", exc)
                try:
                    gh.close_issue(result.issue_number)
                except Exception as exc:
                    log.warning("_stage_news_triage: failed to close issue: %s", exc)
        else:
            console.print(f"  ✅ [green]Editorial triage: PUBLISH[/green] — {parsed['notes']}")

    @staticmethod
    def _validate_article_frontmatter(
        text: str,
        label: str = "article",
        *,
        require_date: bool = True,
    ) -> str | None:
        """Validate that *text* contains a complete YAML frontmatter block.

        Returns an error string describing the problem, or ``None`` if the
        frontmatter is valid.  Checks:

        - Two ``---`` delimiters enclosing a YAML block (not just a bare opening)
        - ``title`` field present and non-empty
        - ``date`` field present and non-empty (when *require_date* is True)

        Args:
            text: Full article markdown text.
            label: Human-readable label used in error messages (e.g. "NewsEditor").
            require_date: When True, also checks that ``date`` is present. Set to
                False for translated sidecars that inherit the date from the EN article.
        """
        import re as _re
        import yaml as _yaml

        stripped = text.strip()
        m = _re.match(r"^---\s*\n(.*?)\n---", stripped, _re.DOTALL)
        if not m:
            return (
                f"{label}: YAML frontmatter block not found "
                f"(opening '---' exists but closing '---' is missing). "
                f"Preview: {stripped[:120]!r}"
            )
        try:
            fm = _yaml.safe_load(m.group(1)) or {}
        except Exception as exc:  # noqa: BLE001
            return f"{label}: YAML frontmatter parse error: {exc}"
        if not str(fm.get("title") or "").strip():
            return f"{label}: frontmatter missing required field 'title'"
        if require_date and not str(fm.get("date") or "").strip():
            return f"{label}: frontmatter missing required field 'date'"
        return None

    @staticmethod
    def _strip_article_code_fence(text: str) -> str:
        """Strip code fences and thinking preamble from LLM article output.

        Handles:
          - Code fences: ```yaml\\n---\\n...\\n```
          - Thinking preamble: reasoning text before the first ``---`` line
            (produced by reasoning models like qwen3 that output chain-of-thought
            before the article when thinking is not suppressed via a separate channel)
        Returns the article starting from its YAML frontmatter ``---``.
        """
        import re as _re
        stripped = text.strip()
        m = _re.match(r"^```(?:yaml|markdown|md)?\s*\n(.*?)(?:\n```\s*)?$", stripped, _re.DOTALL)
        if m:
            stripped = m.group(1).strip()
        if not stripped.startswith("---"):
            fm = _re.search(r"(?:^|\n)(---\n)", stripped)
            if fm:
                stripped = stripped[fm.start(1):]
        return stripped

    def _stage_news_writer(self, result: PipelineResult) -> None:
        """Write a first-draft news article from the issue brief."""
        from datetime import datetime as _datetime
        issue_body = getattr(result, "issue_body", "") or result.requirement
        synthesis = result.discussion_synthesis or ""
        # Prepend editorial triage notes so the writer knows the agreed angle
        if result.editorial_notes:
            issue_body = f"[EDITORIAL NOTES]\n{result.editorial_notes}\n\n" + issue_body
        # Inject today's publication date so the writer uses it in frontmatter,
        # not the source article's original publication date.
        pub_date = _datetime.utcnow().strftime("%Y-%m-%dT%H:%M:00")
        issue_body = f"[PUBLICATION DATE: {pub_date}]\n\n" + issue_body
        wr = self.news_writer.run(issue_body, discussion_synthesis=synthesis)
        draft = self._strip_article_code_fence(wr.get("article_draft", "") or "")
        if not draft:
            raise RuntimeError("NewsWriter produced an empty draft — LLM may have returned no content.")
        fm_err = self._validate_article_frontmatter(draft, "NewsWriter")
        if fm_err:
            raise RuntimeError(fm_err)
        result.article_draft = draft
        # Do NOT clear discussion_synthesis here — if discuss_news_draft runs next it
        # will overwrite it; if it doesn't run the editor should still see the
        # pre-write analysis synthesis from discuss_news_analysis.

    def _stage_news_editor(self, result: PipelineResult, reviewer_notes: str = "") -> None:
        """Edit the article draft to publication standard."""
        issue_body = getattr(result, "issue_body", "") or result.requirement
        synthesis = result.discussion_synthesis or ""
        # On reviewer retry, use the current article as the draft to preserve prior edits
        draft = result.article if reviewer_notes and result.article else result.article_draft
        ed = self.news_editor.run(
            draft,
            issue_body=issue_body,
            discussion_synthesis=synthesis,
            reviewer_notes=reviewer_notes,
        )
        if not ed.get("article", "").strip():
            raise RuntimeError("NewsEditor produced an empty article — LLM may have returned no content.")
        edited = self._strip_article_code_fence(ed["article"] or "")
        fm_err = self._validate_article_frontmatter(edited, "NewsEditor")
        if fm_err:
            raise RuntimeError(fm_err)
        result.article = edited

    _TRANSLATE_VALID_LANGUAGES = frozenset({"cantonese", "traditional_chinese"})
    _TRANSLATE_VALID_FIELDS = frozenset({"article_zh_hk", "article_zh_tw"})

    def _stage_translate(self, result: "PipelineResult", target_language: str, result_field: str, reviewer_notes: str = "") -> None:
        """Translate the final article into a target language."""
        if target_language not in self._TRANSLATE_VALID_LANGUAGES:
            raise ValueError(
                f"translate: unknown target_language {target_language!r}. "
                f"Expected one of: {sorted(self._TRANSLATE_VALID_LANGUAGES)}"
            )
        if result_field not in self._TRANSLATE_VALID_FIELDS:
            raise ValueError(
                f"translate: unknown result_field {result_field!r}. "
                f"Expected one of: {sorted(self._TRANSLATE_VALID_FIELDS)}"
            )
        source = result.article or result.article_draft
        if not source.strip():
            raise RuntimeError(
                f"translate ({target_language}): no source article found — "
                "run news_writer or news_editor before translation stages"
            )
        out = self.translator.run(source, target_language=target_language, reviewer_notes=reviewer_notes)
        translated = self._strip_article_code_fence(out.get("translated_article", "") or "")
        if not translated:
            raise RuntimeError(f"translate ({target_language}): empty output from translator")
        fm_err = self._validate_article_frontmatter(translated, f"translate ({target_language})", require_date=False)
        if fm_err:
            raise RuntimeError(fm_err)
        setattr(result, result_field, translated)

    def _stage_news_reviewer(self, result: PipelineResult) -> None:
        """Review article quality and translation correctness; retry on issues."""
        import re as _re

        max_retries: int = getattr(self, "_reviewer_max_retries", 2)

        # Extract source_url from YAML frontmatter
        source_url = ""
        fm_match = _re.match(r"^---\s*\n(.*?)\n---", result.article or "", _re.DOTALL)
        if fm_match:
            try:
                import yaml as _yaml
                fm = _yaml.safe_load(fm_match.group(1)) or {}
                source_url = str(fm.get("source_url", ""))
            except Exception:
                pass

        for attempt in range(max_retries + 1):
            out = self.news_reviewer.run(
                result.article or result.article_draft,
                result.article_zh_tw,
                source_url=source_url,
            )
            verdict = out.get("verdict", "PASS")
            issues = out.get("issues", [])

            if verdict == "PASS":
                if attempt > 0:
                    console.print(f"  ✅ [green]Reviewer passed after {attempt} retry(s)[/green]")
                else:
                    console.print("  ✅ [dim]Reviewer: PASS[/dim]")
                return

            if attempt >= max_retries:
                console.print(
                    f"  [yellow]⚠️  Reviewer still has issues after {max_retries} retries — accepting article[/yellow]"
                )
                return

            # Classify issues
            has_english = any(
                i.startswith("[FACT]") or i.startswith("[WORDING]") for i in issues
            )
            has_zh_tw = any("[ZH_TW]" in i for i in issues)
            notes = "\n".join(issues)
            result.article_reviewer_notes = notes
            result.article_review_retry_count += 1

            console.print(
                f"  [yellow]📝 Reviewer: NEEDS_REVISION (attempt {attempt + 1}/{max_retries})[/yellow]"
            )
            for issue in issues:
                console.print(f"     {issue}")

            if has_english:
                console.print("  🔄 [dim]Retrying editor + translation…[/dim]")
                self._stage_news_editor(result, reviewer_notes=notes)
                self._stage_translate(result, "traditional_chinese", "article_zh_tw", reviewer_notes=notes)
            elif has_zh_tw:
                console.print("  🔄 [dim]Retrying Traditional Chinese translation…[/dim]")
                self._stage_translate(
                    result, "traditional_chinese", "article_zh_tw", reviewer_notes=notes
                )

    def _stage_news_article_pr(self, result: PipelineResult) -> None:
        """Commit the final article as a file and open a PR in the tracker repo."""
        import re
        import yaml as _yaml

        article = result.article or result.article_draft
        if not article.strip():
            result.add_error("news_article_pr: no article content to commit.")
            return
        fm_err = self._validate_article_frontmatter(article, "news_article_pr")
        if fm_err:
            result.add_error(fm_err)
            return

        # Validate sidecar translations before committing (catches agent commentary leaking in)
        if result.article_zh_hk.strip():
            sidecar_err = self._validate_article_frontmatter(
                result.article_zh_hk, "news_article_pr: zh_hk sidecar", require_date=False
            )
            if sidecar_err:
                result.add_error(sidecar_err)
                return
        if result.article_zh_tw.strip():
            sidecar_err = self._validate_article_frontmatter(
                result.article_zh_tw, "news_article_pr: zh_tw sidecar", require_date=False
            )
            if sidecar_err:
                result.add_error(sidecar_err)
                return

        # Parse frontmatter for date and title
        date_str = ""
        title_slug = ""
        source_url = ""
        fm_match = re.match(r"^---\s*\n(.*?)\n---", article, re.DOTALL)
        if fm_match:
            try:
                fm = _yaml.safe_load(fm_match.group(1)) or {}
                raw_date = str(fm.get("date", ""))
                date_str = raw_date[:10].replace("-", "") if raw_date else ""
                title = str(fm.get("title", ""))
                source_url = str(fm.get("source_url", ""))
                title_slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:40].strip("-")
            except Exception:  # noqa: BLE001
                pass

        if not date_str:
            from datetime import datetime
            date_str = datetime.utcnow().strftime("%Y%m%d")

        # Fall back to source URL hostname + path slug when title is empty (e.g. all-Chinese title)
        if not title_slug and source_url:
            try:
                from urllib.parse import urlparse as _urlparse
                parsed = _urlparse(source_url)
                host_slug = re.sub(r"[^a-z0-9]+", "-", parsed.hostname.lower()).strip("-")[:20] if parsed.hostname else ""
                path_slug = re.sub(r"[^a-z0-9]+", "-", parsed.path.lower()).strip("-")[:20] if parsed.path else ""
                title_slug = f"{host_slug}-{path_slug}".strip("-")[:40]
            except Exception:  # noqa: BLE001
                pass

        issue_part = f"{result.issue_number}-" if result.issue_number else ""
        filename = f"articles/{date_str}-{issue_part}{title_slug or 'article'}.md"
        # Derive zh filenames from the English base so all three files share the same stem.
        # e.g. 20260519-42-the-future-of-ai.md + .zh-hk.md + .zh-tw.md
        extra_files: dict[str, str] = {}
        if result.article_zh_hk.strip():
            extra_files[filename.replace(".md", ".zh-hk.md")] = result.article_zh_hk
        if result.article_zh_tw.strip():
            extra_files[filename.replace(".md", ".zh-tw.md")] = result.article_zh_tw
        result.all_files = {filename: article, **extra_files}

        self._commit_and_open_pr(
            result,
            branch_prefix="article",
            title_prefix="article",
            body_header="## 📰 AI-Generated News Article",
            commit_msg_prefix="article",
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _critical_cb_open(self) -> str | None:
        """Return the name of the first critical stage whose circuit breaker is open, or None.

        Checks the well-known critical stage checkpoint keys ('pm', 'architect'). Used by
        _run_stage() to cascade-skip downstream stages when an upstream critical
        stage has tripped its circuit breaker open.
        """
        from core.circuit_breaker_registry import get_registry
        registry = get_registry()
        for name in ("pm", "architect"):
            try:
                cb = registry.get_or_create("agent", name)
                if cb.state == "open":
                    return name
            except Exception as exc:
                _log.warning("_critical_cb_open: error checking breaker %r: %s", name, exc)
        return None

    def _run_stage_safe(self, stage: "PipelineStage", result: "PipelineResult") -> bool:
        """Thread-safe wrapper for _run_stage used in parallel group execution.

        Sets the current_stage ContextVar within this thread's context copy so
        that token tracking is correct per-thread.  Errors are recorded on
        *result*; returns True if the stage succeeded, False if it errored.
        """
        errors_before = len(result.errors)
        _token = current_stage.set(stage.checkpoint_key)
        try:
            self._run_stage(
                stage.label,
                stage.description,
                result,
                lambda s=stage: s.fn(result),
                timeout_s=stage.timeout_s,
                required_output_fields=stage.required_output_fields,
                cb_key=stage.checkpoint_key,
                is_critical=stage.is_critical,
            )
        finally:
            current_stage.reset(_token)
        return len(result.errors) == errors_before

    def _run_parallel_batch(
        self,
        runnable: list,
        result: "PipelineResult",
        start_time: float,
        stage_results: dict,
    ) -> "PipelineResult | None":
        """Execute a parallel batch of stages using a ThreadPoolExecutor.

        Submits all *runnable* stages concurrently and collects results via
        ``as_completed``.  On ``BudgetExceededError`` the in-flight futures are
        cancelled, the triggering stage is marked failed, a checkpoint is saved,
        and a finished ``PipelineResult`` is returned so the caller can propagate
        the early exit.

        Args:
            runnable:      List of ``PipelineStage`` objects to run in parallel.
            result:        Shared ``PipelineResult`` accumulator (thread-safe via locks).
            start_time:    Wall-clock start time used by ``_finish``.
            stage_results: Mutable dict populated with ``checkpoint_key → succeeded``
                           entries.  Modified in-place so the caller can inspect
                           per-stage outcomes after a normal (non-early-exit) return.

        Returns:
            A finished ``PipelineResult`` if the batch was aborted early (e.g. budget
            exceeded), or ``None`` if all futures completed normally.
        """
        early_exit = False
        with ThreadPoolExecutor(max_workers=min(len(runnable), MAX_PARALLEL_STAGES)) as executor:
            futures = {
                executor.submit(self._run_stage_safe, s, result): s
                for s in runnable
            }
            try:
                for future in as_completed(futures):
                    s = futures[future]
                    try:
                        stage_results[s.checkpoint_key] = future.result()  # re-raises unexpected exceptions
                    except BudgetExceededError:
                        for pending in futures:
                            pending.cancel()
                        self._tracker.mark_failed(s.checkpoint_key, "budget exceeded")
                        result.progress_comment_id = self._tracker.comment_id
                        self._save_checkpoint(result)
                        # Capture early-exit condition and break out of the loop.
                        # Do NOT call _finish() here — the executor's __exit__ must
                        # run first (shutdown/wait) so that any still-running futures
                        # finish mutating `result` before _finish() is called below.
                        early_exit = True
                        break
            except _ShutdownRequested:
                # Cancel any futures that haven't started yet so we don't
                # wait for them inside the ThreadPoolExecutor __exit__.
                for f in futures:
                    f.cancel()
                raise
        # Executor has fully shut down at this point; safe to call _finish().
        if early_exit:
            return self._finish(result, start_time)
        return None

    def _run_stage(self, name: str, description: str, result: PipelineResult, fn, timeout_s: float | None = None, required_output_fields: list[str] | None = None, cb_key: str | None = None, is_critical: bool = False) -> None:
        """Run a pipeline stage with progress display, error handling, and optional timeout.

        If *timeout_s* is set and the stage exceeds it, a timeout error is recorded
        on *result*. The background thread continues until the LLM call returns —
        Python cannot forcibly kill threads.

        Args:
            name:                  Stage display label (used in progress output).
            description:           Short description shown in progress spinner.
            result:                PipelineResult to record errors on.
            fn:                    Callable to execute the stage logic.
            timeout_s:             Optional wall-clock timeout in seconds.
            required_output_fields: Fields verified on result after stage completes.
            cb_key:                Circuit breaker key for this stage (defaults to name).
                                   Should be the stage's checkpoint_key for consistency.
            is_critical:           When True, this stage is exempt from cascade-skip;
                                   critical stages always run regardless of upstream CB state.
        """
        # Graceful shutdown: abort immediately if a SIGTERM/SIGINT was received.
        # Raise _ShutdownRequested (BaseException) instead of returning None so
        # that callers cannot mistakenly infer "stage succeeded" from "no new errors".
        if getattr(self, "_shutdown_event", None) and self._shutdown_event.is_set():
            raise _ShutdownRequested()

        # CB cascade: skip non-critical stages when a critical upstream CB is open.
        # Critical stages (pm, architect) always run so they can recover.
        if not is_critical:
            open_stage = self._critical_cb_open()
            if open_stage:
                result.add_error(_PipelineError(
                    code="STAGE_SKIPPED",
                    stage=cb_key or name,
                    message=f"Skipped: critical stage {open_stage!r} circuit breaker is open",
                    severity="warning",
                    context={"upstream_stage": open_stage, "reason": "CB_CASCADE"},
                ))
                return

        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
        with Progress(
            SpinnerColumn(),
            TextColumn(f"[bold blue]{name}[/bold blue] {description}"),
            transient=True,
            console=console,
        ) as progress:
            progress.add_task("running", total=None)
            try:
                if timeout_s is not None:
                    import threading as _threading
                    exc_box: list[BaseException] = []

                    def _run_fn() -> None:
                        try:
                            fn()
                        except BaseException as _e:
                            exc_box.append(_e)

                    t = _threading.Thread(target=_run_fn, daemon=True)
                    t.start()
                    t.join(timeout=timeout_s)
                    if t.is_alive():
                        # Thread leaked — it runs until LLM returns, but as a daemon
                        # thread it will not block interpreter shutdown.
                        _record_leaked_thread(name)
                        error_msg = (
                            f"{name} timed out after {timeout_s}s "
                            f"(background thread still running)"
                        )
                        result.add_error(error_msg)
                        console.print(f"  ⏱️  [yellow]{error_msg}[/yellow]")
                        return
                    if exc_box:
                        raise exc_box[0]
                else:
                    fn()
                if required_output_fields:
                    from core.output_verifier import OutputVerifier, OutputVerificationError
                    try:
                        OutputVerifier(required_output_fields).verify(result, name)
                    except OutputVerificationError as ove:
                        result.add_error(str(ove))
                        console.print(f"  ❌ [red]{ove}[/red]")
                        return
                console.print(f"  ✅ [green]{name}[/green] complete")
                if hasattr(self, "_agent_health"):
                    self._agent_health.record_success(name)
            except ClarificationNeeded:
                raise  # handled by run() — do not log as error
            except BudgetExceededError:
                raise  # propagate so the stage loop can halt the pipeline
            except Exception as exc:
                error_msg = f"{name} failed: {exc}"
                result.add_error(error_msg)
                console.print(f"  ❌ [red]{error_msg}[/red]")
                if hasattr(self, "_agent_health"):
                    self._agent_health.record_failure(name)
                    if self._agent_health.is_unhealthy(name):
                        effective_cb_key = cb_key or name
                        console.print(
                            f"  ⚠️  [yellow]{name} has failed "
                            f"{self._agent_health.failure_count(name)} consecutive times — "
                            f"tripping circuit breaker for '{effective_cb_key}'[/yellow]"
                        )
                        from core.circuit_breaker_registry import get_registry
                        get_registry().get_or_create("agent", effective_cb_key).force_open()

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
        with self._checkpoint_lock:
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
        with self._checkpoint_lock:
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
                mb_model = self._resolve_agent_model("memory_bank_updater")
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
        ct = self._cost_tracking
        if ct.get("enabled", False) and result.run_id:
            ledger = get_ledger()
            # Update project name now that it's known
            if result.run_id in ledger._runs:
                ledger._runs[result.run_id]["project_name"] = result.project_name or ""
            ledger.finish_run(result.run_id)
            # Flush to SQLite
            db_path = ct.get("db_path", "./token_usage.db")
            try:
                ledger.flush_to_db(db_path)
            except Exception as exc:
                console.print(f"  [yellow]⚠️  Token DB flush failed: {exc}[/yellow]")
            # Store results
            s = ledger.summary(result.run_id)
            result.total_cost_usd = s["total_cost_usd"]
            result.token_usage = s
            # Post to GitHub issue if configured
            if ct.get("post_to_github", False) and self.github and result.issue_number:
                try:
                    comment = ledger.format_github_comment(result.run_id)
                    self.github.add_issue_comment(result.issue_number, comment)
                except Exception as exc:
                    console.print(f"  [yellow]⚠️  Token comment failed: {exc}[/yellow]")

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
        if result.total_cost_usd > 0:
            table.add_row("Est. cost", f"${result.total_cost_usd:.4f} USD")
        if result.errors:
            table.add_row("[red]Errors[/red]", "\n".join(str(e) for e in result.errors))

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
        """Commit updated memory bank files directly to the default branch.

        Writing to the default branch (not the article PR branch) avoids
        merge conflicts when multiple article branches run concurrently.
        """
        if not updated_bank:
            return
        try:
            target_branch = gh.get_default_branch()
        except Exception:
            target_branch = "main"
        for name, content in updated_bank.items():
            try:
                gh.commit_file(
                    f"memory-bank/{name}",
                    content,
                    f"memory: update {name} after pipeline run",
                    target_branch,
                    max_retries=1,  # Non-critical write — don't hang on transient 5xx errors
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
