"""
Orchestrator: runs the full PM → Architect → Engineer×N → Reviewer → QA pipeline.
Manages artifact passing, logging, and optional GitHub integration.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from agents import (
    ArchitectAgent,
    CodeReviewerAgent,
    EngineerAgent,
    ProductManagerAgent,
    QAEngineerAgent,
)
from github_client import GitHubClient, parse_target_repo

console = Console()


@dataclass
class PipelineResult:
    """Holds the full output of a completed pipeline run."""

    requirement: str
    project_name: str = ""
    prd: str = ""
    design: str = ""
    modules: list[dict] = field(default_factory=list)
    all_files: dict[str, str] = field(default_factory=dict)
    test_files: dict[str, str] = field(default_factory=dict)
    review: str = ""
    verdict: str = ""
    test_plan: str = ""
    issue_number: Optional[int] = None
    issue_url: Optional[str] = None
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    branch: Optional[str] = None
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)
    completed_stages: list[str] = field(default_factory=list)  # stages that finished OK

    def to_dict(self) -> dict:
        return {
            "requirement": self.requirement,
            "project_name": self.project_name,
            "prd": self.prd,
            "design": self.design,
            "modules": self.modules,
            "all_files": self.all_files,
            "test_files": self.test_files,
            "review": self.review,
            "verdict": self.verdict,
            "test_plan": self.test_plan,
            "issue_number": self.issue_number,
            "issue_url": self.issue_url,
            "pr_number": self.pr_number,
            "pr_url": self.pr_url,
            "branch": self.branch,
            "completed_stages": self.completed_stages,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PipelineResult":
        r = cls(requirement=data["requirement"])
        for key in ["project_name", "prd", "design", "modules", "all_files", "test_files",
                    "review", "verdict", "test_plan", "issue_number", "issue_url",
                    "pr_number", "pr_url", "branch", "completed_stages"]:
            setattr(r, key, data.get(key, getattr(r, key)))
        return r


class Orchestrator:
    """Runs the AI software house pipeline end-to-end.

    Usage:
        orch = Orchestrator.from_config("config.yaml")
        result = orch.run("Build a task management REST API")
    """

    def __init__(
        self,
        model: str = "gpt-4.1",
        github_repo: Optional[str] = None,
        github_token: Optional[str] = None,
        num_engineers: int = 2,
        branch_prefix: str = "feature/agent",
        workspace_dir: str = "./workspace",
        stop_on_review_issues: bool = False,
        model_overrides: Optional[dict] = None,
        use_github: bool = False,
        target_repo: Optional[str] = None,
    ) -> None:
        self.model = model
        self.num_engineers = num_engineers
        self.branch_prefix = branch_prefix
        self.workspace_dir = Path(workspace_dir)
        self.stop_on_review_issues = stop_on_review_issues
        self.model_overrides = model_overrides or {}
        self.use_github = use_github and bool(github_repo)
        self._github_token = github_token

        # Shared kwargs for all agents
        agent_kwargs = {"github_token": github_token}

        self.pm = ProductManagerAgent(model=model, **agent_kwargs)
        self.architect = ArchitectAgent(model=model, **agent_kwargs)
        self.engineer = EngineerAgent(
            model=self.model_overrides.get("engineer", model), **agent_kwargs
        )
        self.reviewer = CodeReviewerAgent(model=model, **agent_kwargs)
        self.qa = QAEngineerAgent(model=model, **agent_kwargs)

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

    @classmethod
    def from_config(cls, config_path: str = "config.yaml", github_token: Optional[str] = None) -> "Orchestrator":
        """Create an Orchestrator from a YAML config file."""
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        llm = cfg.get("llm", {})
        gh = cfg.get("github", {})
        team = cfg.get("team", {})
        pipeline = cfg.get("pipeline", {})

        repo = gh.get("repo", "")
        use_github = bool(repo) and repo != "your-username/your-repo"

        return cls(
            model=llm.get("model", "gpt-4.1"),
            github_repo=repo if use_github else None,
            github_token=github_token,
            num_engineers=team.get("num_engineers", 2),
            branch_prefix=gh.get("branch_prefix", "feature/agent"),
            workspace_dir=pipeline.get("workspace_dir", "./workspace"),
            stop_on_review_issues=pipeline.get("stop_on_review_issues", False),
            model_overrides=llm.get("overrides", {}),
            use_github=use_github,
        )

    def run(self, requirement: str, trigger_issue_body: Optional[str] = None, resume: bool = True) -> PipelineResult:
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

        # ── Load checkpoint if resuming ───────────────────────────────────────
        result = self._load_checkpoint(requirement) if resume else None
        if result:
            console.print(
                f"[bold yellow]⏭️  Resuming from checkpoint[/bold yellow] "
                f"(completed: {', '.join(result.completed_stages)})"
            )
        else:
            result = PipelineResult(requirement=requirement)

        console.print(Panel.fit(
            f"[bold cyan]🏢 AI Software House Pipeline[/bold cyan]\n"
            f"[dim]{requirement[:120]}{'...' if len(requirement) > 120 else ''}[/dim]",
            border_style="cyan",
        ))

        # ── Stage 1: Product Manager ─────────────────────────────────────────
        if "pm" not in result.completed_stages:
            self._run_stage("📋 Product Manager", "Analyzing requirements & writing PRD...", result, lambda: self._stage_pm(result, requirement))
            if result.errors:
                self._save_checkpoint(result)
                return self._finish(result, start_time)
            result.completed_stages.append("pm")
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]📋 Product Manager — skipped (checkpoint)[/dim]")

        # ── Stage 2: Architect ────────────────────────────────────────────────
        if "architect" not in result.completed_stages:
            self._run_stage("🏗️  Architect", "Designing system architecture...", result, lambda: self._stage_architect(result))
            if result.errors:
                self._save_checkpoint(result)
                return self._finish(result, start_time)
            result.completed_stages.append("architect")
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]🏗️  Architect — skipped (checkpoint)[/dim]")

        # ── Stage 3: Engineers ────────────────────────────────────────────────
        if "engineer" not in result.completed_stages:
            self._run_stage(
                f"💻 Engineers (×{self.num_engineers})",
                f"Implementing {len(result.modules)} module(s) in parallel...",
                result,
                lambda: self._stage_engineer(result),
            )
            if result.errors:
                self._save_checkpoint(result)
                return self._finish(result, start_time)
            result.completed_stages.append("engineer")
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]💻 Engineers — skipped (checkpoint)[/dim]")

        # ── Stage 4: Code Reviewer ────────────────────────────────────────────
        if "reviewer" not in result.completed_stages:
            self._run_stage("🔍 Code Reviewer", "Reviewing generated code...", result, lambda: self._stage_reviewer(result))
            if self.stop_on_review_issues and result.verdict == "CHANGES REQUESTED":
                console.print("[bold red]⛔ Pipeline stopped: code reviewer requested changes.[/bold red]")
                self._save_checkpoint(result)
                return self._finish(result, start_time)
            result.completed_stages.append("reviewer")
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]🔍 Code Reviewer — skipped (checkpoint)[/dim]")

        # ── Stage 5: QA Engineer ──────────────────────────────────────────────
        if "qa" not in result.completed_stages:
            self._run_stage("🧪 QA Engineer", "Writing tests & producing test plan...", result, lambda: self._stage_qa(result))
            result.completed_stages.append("qa")
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]🧪 QA Engineer — skipped (checkpoint)[/dim]")

        # Pipeline complete — remove checkpoint
        self._clear_checkpoint(result)
        return self._finish(result, start_time)

    # ── Stage implementations ────────────────────────────────────────────────

    def _stage_pm(self, result: PipelineResult, requirement: str) -> None:
        if self.github:
            pm_result = self.pm.run_with_github(requirement, self.github)
            result.issue_number = pm_result["issue_number"]
            result.issue_url = pm_result["issue_url"]
        else:
            pm_result = self.pm.run(requirement)
        result.prd = pm_result["prd"]
        result.project_name = pm_result["project_name"]

    def _stage_architect(self, result: PipelineResult) -> None:
        if self.github and result.issue_number:
            arch_result = self.architect.run_with_github(
                result.prd, result.project_name, self.github, result.issue_number
            )
        else:
            arch_result = self.architect.run(result.prd, result.project_name)
        result.design = arch_result["design"]
        result.modules = arch_result["modules"]

    def _stage_engineer(self, result: PipelineResult) -> None:
        # Limit to num_engineers modules for parallel dispatch
        modules = result.modules[: max(self.num_engineers, len(result.modules))]
        if self.target_github:
            eng_result = self.engineer.run_with_github(
                result.design,
                modules,
                result.project_name,
                self.target_github,
                branch_prefix=self.branch_prefix,
                issue_number=result.issue_number,
                max_workers=self.num_engineers,
            )
            result.branch = eng_result.get("branch")
            result.pr_number = eng_result.get("pr_number")
            result.pr_url = eng_result.get("pr_url")
        else:
            eng_result = self.engineer.run_all_modules(
                result.design, modules, result.project_name, max_workers=self.num_engineers
            )
        result.all_files = eng_result["all_files"]
        self._save_files_locally(result.all_files, result.project_name)

    def _stage_reviewer(self, result: PipelineResult) -> None:
        if self.target_github and result.pr_number:
            rev_result = self.reviewer.run_with_github(
                result.all_files, result.prd, result.project_name, self.target_github, result.pr_number
            )
        else:
            rev_result = self.reviewer.run(result.all_files, result.prd, result.project_name)
        result.review = rev_result["review"]
        result.verdict = rev_result["verdict"]

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
            )
        else:
            qa_result = self.qa.run(result.all_files, result.prd, result.project_name)
        result.test_files = qa_result["test_files"]
        result.test_plan = qa_result["test_plan"]
        self._save_files_locally(result.test_files, result.project_name)

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
            except Exception as exc:
                error_msg = f"{name} failed: {exc}"
                result.errors.append(error_msg)
                console.print(f"  ❌ [red]{error_msg}[/red]")

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
        """Persist the current pipeline state to disk."""
        path = self._checkpoint_path(result)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def _load_checkpoint(self, requirement: str) -> Optional[PipelineResult]:
        """Load a checkpoint matching this requirement, if one exists."""
        # Search all subdirs of workspace for a checkpoint with matching requirement
        if not self.workspace_dir.exists():
            return None
        for checkpoint_file in self.workspace_dir.glob("*/checkpoint.json"):
            try:
                data = json.loads(checkpoint_file.read_text(encoding="utf-8"))
                if data.get("requirement") == requirement and data.get("completed_stages"):
                    return PipelineResult.from_dict(data)
            except Exception:
                continue
        return None

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
        """Print summary and return the final result."""
        result.duration_seconds = time.time() - start_time

        # Summary table
        table = Table(title="Pipeline Summary", show_header=True, header_style="bold magenta")
        table.add_column("Stage", style="cyan")
        table.add_column("Output")

        table.add_row("Project", result.project_name or "—")
        table.add_row("PRD", f"{len(result.prd)} chars" if result.prd else "—")
        table.add_row("Modules", str(len(result.modules)))
        table.add_row("Code files", str(len(result.all_files)))
        table.add_row("Test files", str(len(result.test_files)))
        table.add_row("Review verdict", result.verdict or "—")
        if result.issue_url:
            table.add_row("GitHub Issue", result.issue_url)
        if result.pr_url:
            table.add_row("Pull Request", result.pr_url)
        table.add_row("Duration", f"{result.duration_seconds:.1f}s")
        if result.errors:
            table.add_row("[red]Errors[/red]", "\n".join(result.errors))

        console.print(table)
        return result
