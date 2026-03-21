"""
BugFixOrchestrator: a focused pipeline triggered by GitHub Issue bug reports.

Unlike the full software house pipeline (PM→Architect→Engineer→Reviewer→QA),
this pipeline is optimised for bug fixes:

  Issue (bug report) → Diagnosis → Fix → Code Review → Regression Test

No Product Manager stage — the GitHub Issue IS the requirement.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from agents import ArchitectAgent, CodeReviewerAgent, EngineerAgent, QAEngineerAgent
from github_client import GitHubClient

console = Console()

# System-prompt overlay for diagnosis mode (prepended to Architect role)
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


@dataclass
class BugFixResult:
    """Holds all artifacts produced by the bug-fix pipeline."""

    issue_number: int
    issue_title: str
    issue_body: str
    diagnosis: str = ""
    modules: list[dict] = field(default_factory=list)
    fixed_files: dict[str, str] = field(default_factory=dict)
    review: str = ""
    verdict: str = ""
    test_files: dict[str, str] = field(default_factory=dict)
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    branch: Optional[str] = None
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


class BugFixOrchestrator:
    """Runs the bug-fix pipeline triggered by a GitHub Issue.

    Usage:
        orch = BugFixOrchestrator.from_config("config.yaml")
        result = orch.run(issue_number=42)
    """

    def __init__(
        self,
        model: str = "gpt-4.1",
        github_repo: Optional[str] = None,
        github_token: Optional[str] = None,
        branch_prefix: str = "fix/agent",
        workspace_dir: str = "./workspace",
        model_overrides: Optional[dict] = None,
    ) -> None:
        self.model = model
        self.branch_prefix = branch_prefix
        self.workspace_dir = Path(workspace_dir)
        overrides = model_overrides or {}

        agent_kwargs = {"github_token": github_token}
        self.architect = ArchitectAgent(model=model, **agent_kwargs)
        self.engineer = EngineerAgent(model=overrides.get("engineer", model), **agent_kwargs)
        self.reviewer = CodeReviewerAgent(model=model, **agent_kwargs)
        self.qa = QAEngineerAgent(model=model, **agent_kwargs)

        # Override architect system prompt for diagnosis mode
        self.architect.system_prompt = _DIAGNOSIS_PREFIX + "\n\n" + self.architect.system_prompt

        self.github: Optional[GitHubClient] = None
        if github_repo:
            self.github = GitHubClient(repo=github_repo, github_token=github_token)

    @classmethod
    def from_config(cls, config_path: str = "config.yaml", github_token: Optional[str] = None) -> "BugFixOrchestrator":
        """Create from a config.yaml file."""
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        llm = cfg.get("llm", {})
        gh = cfg.get("github", {})
        pipeline = cfg.get("pipeline", {})
        repo = gh.get("repo", "")

        return cls(
            model=llm.get("model", "gpt-4.1"),
            github_repo=repo if repo and repo != "your-username/your-repo" else None,
            github_token=github_token,
            branch_prefix=gh.get("bug_branch_prefix", "fix/agent"),
            workspace_dir=pipeline.get("workspace_dir", "./workspace"),
            model_overrides=llm.get("overrides", {}),
        )

    def run(
        self,
        issue_number: int,
        existing_files: Optional[dict[str, str]] = None,
    ) -> BugFixResult:
        """Run the bug-fix pipeline for a GitHub Issue.

        Args:
            issue_number: GitHub Issue number containing the bug report.
            existing_files: Optional dict of {filepath: content} for the codebase.
                            If omitted and GitHub is configured, fetches from repo.

        Returns:
            BugFixResult with all artifacts.
        """
        if not self.github:
            raise EnvironmentError(
                "GitHub integration is required for BugFixOrchestrator. "
                "Set github.repo in config.yaml and provide GITHUB_TOKEN."
            )

        # Fetch the issue
        issue = self.github._request("GET", f"/repos/{self.github.repo}/issues/{issue_number}")
        result = BugFixResult(
            issue_number=issue_number,
            issue_title=issue.get("title", "Bug Report"),
            issue_body=issue.get("body", ""),
        )
        start_time = time.time()

        console.print(Panel.fit(
            f"[bold red]🐛 Bug Fix Pipeline[/bold red]\n"
            f"[dim]Issue #{issue_number}: {result.issue_title[:100]}[/dim]",
            border_style="red",
        ))

        # Post initial acknowledgement comment
        self.github.add_issue_comment(
            issue_number,
            "🤖 **AI Software House** — Bug fix pipeline started.\n\n"
            "Agents are diagnosing the issue. A fix PR will be opened shortly.",
        )

        # ── Stage 1: Diagnosis (Architect in bug mode) ───────────────────────
        self._run_stage("🔬 Diagnosis", "Analysing root cause...", result, lambda: self._stage_diagnose(result, existing_files))
        if result.errors:
            return self._finish(result, start_time)

        # ── Stage 2: Fix (Engineer) ──────────────────────────────────────────
        self._run_stage("🔧 Engineer", "Implementing fix...", result, lambda: self._stage_fix(result))
        if result.errors:
            return self._finish(result, start_time)

        # ── Stage 3: Code Review ─────────────────────────────────────────────
        self._run_stage("🔍 Code Reviewer", "Reviewing the fix...", result, lambda: self._stage_review(result))

        # ── Stage 4: Regression Tests ────────────────────────────────────────
        self._run_stage("🧪 QA Engineer", "Writing regression tests...", result, lambda: self._stage_qa(result))

        return self._finish(result, start_time)

    # ── Stage implementations ────────────────────────────────────────────────

    def _stage_diagnose(self, result: BugFixResult, existing_files: Optional[dict]) -> None:
        """Use Architect (in diagnosis mode) to find root cause."""
        bug_context = (
            f"**Bug Report (GitHub Issue #{result.issue_number})**\n"
            f"**Title:** {result.issue_title}\n\n"
            f"**Description:**\n{result.issue_body}"
        )

        if existing_files:
            code_context = "\n\n".join(
                f"### FILE: {path}\n```\n{content}\n```"
                for path, content in list(existing_files.items())[:20]  # cap at 20 files
            )
            bug_context += f"\n\n**Existing codebase:**\n{code_context}"

        arch_result = self.architect.run(prd=bug_context, project_name=f"Bug Fix: {result.issue_title}")
        result.diagnosis = arch_result["design"]
        result.modules = arch_result["modules"]

        # Post diagnosis as issue comment
        self.github.add_issue_comment(
            result.issue_number,
            f"## 🔬 Bug Diagnosis\n\n{result.diagnosis}",
        )

    def _stage_fix(self, result: BugFixResult) -> None:
        """Engineer implements the fix and opens a PR."""
        import re
        safe_title = re.sub(r"[^a-z0-9-]", "-", result.issue_title.lower())[:50]
        branch_name = f"{self.branch_prefix}/issue-{result.issue_number}-{safe_title}"

        eng_result = self.engineer.run_with_github(
            design=result.diagnosis,
            modules=result.modules,
            project_name=f"Bug Fix: {result.issue_title}",
            github_client=self.github,
            branch_prefix=self.branch_prefix,
            issue_number=result.issue_number,
        )
        # Override branch name to include issue number
        result.fixed_files = eng_result["all_files"]
        result.branch = eng_result.get("branch")
        result.pr_number = eng_result.get("pr_number")
        result.pr_url = eng_result.get("pr_url")

        self._save_files_locally(result.fixed_files, f"fix-issue-{result.issue_number}")

    def _stage_review(self, result: BugFixResult) -> None:
        """Code Reviewer reviews the fix."""
        if result.pr_number:
            rev_result = self.reviewer.run_with_github(
                files=result.fixed_files,
                prd=f"Bug Report: {result.issue_title}\n\n{result.issue_body}",
                project_name=f"Bug Fix #{result.issue_number}",
                github_client=self.github,
                pr_number=result.pr_number,
            )
        else:
            rev_result = self.reviewer.run(
                files=result.fixed_files,
                prd=result.issue_body,
                project_name=f"Bug Fix #{result.issue_number}",
            )
        result.review = rev_result["review"]
        result.verdict = rev_result["verdict"]

    def _stage_qa(self, result: BugFixResult) -> None:
        """QA writes regression tests and posts results."""
        if result.branch and result.pr_number:
            qa_result = self.qa.run_with_github(
                files=result.fixed_files,
                prd=f"Regression tests for bug: {result.issue_title}\n\n{result.issue_body}",
                project_name=f"Bug Fix #{result.issue_number}",
                github_client=self.github,
                branch=result.branch,
                pr_number=result.pr_number,
                issue_number=result.issue_number,
            )
        else:
            qa_result = self.qa.run(
                files=result.fixed_files,
                prd=result.issue_body,
                project_name=f"Bug Fix #{result.issue_number}",
            )
        result.test_files = qa_result["test_files"]

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _run_stage(self, name: str, description: str, result: BugFixResult, fn) -> None:
        with Progress(
            SpinnerColumn(),
            TextColumn(f"[bold red]{name}[/bold red] {description}"),
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

    def _save_files_locally(self, files: dict[str, str], dir_name: str) -> None:
        out_dir = self.workspace_dir / dir_name
        out_dir.mkdir(parents=True, exist_ok=True)
        for filepath, content in files.items():
            full_path = out_dir / filepath
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")

    def _finish(self, result: BugFixResult, start_time: float) -> BugFixResult:
        result.duration_seconds = time.time() - start_time

        table = Table(title="Bug Fix Summary", show_header=True, header_style="bold red")
        table.add_column("Stage", style="cyan")
        table.add_column("Output")

        table.add_row("Issue", f"#{result.issue_number}: {result.issue_title[:60]}")
        table.add_row("Fixed files", str(len(result.fixed_files)))
        table.add_row("Test files", str(len(result.test_files)))
        table.add_row("Review verdict", result.verdict or "—")
        if result.pr_url:
            table.add_row("Pull Request", result.pr_url)
        table.add_row("Duration", f"{result.duration_seconds:.1f}s")
        if result.errors:
            table.add_row("[red]Errors[/red]", "\n".join(result.errors))

        console.print(table)
        return result
