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
from github_client import GitHubClient, parse_target_repo
from test_fix_loop import TestFixLoopMixin

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
    # Test-fix retry tracking
    tests_passed: Optional[bool] = None
    test_results: str = ""
    test_retry_count: int = 0
    test_fix_history: list[str] = field(default_factory=list)


class BugFixOrchestrator(TestFixLoopMixin):
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
        max_test_retries: int = 5,
    ) -> None:
        self.model = model
        self.branch_prefix = branch_prefix
        self.workspace_dir = Path(workspace_dir)
        self._github_token = github_token  # stored for creating target GitHubClient at runtime
        self.max_test_retries = max_test_retries
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
            max_test_retries=pipeline.get("max_test_retries", 5),
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

        # ── Detect target project repo (multi-repo support) ───────────────────
        # If the issue body contains "Target repo: owner/project", code ops go there
        # while tracker comments/issue-close stay in self.github (the ai-software-house repo).
        target_repo_override = parse_target_repo(result.issue_body)
        if target_repo_override and target_repo_override != self.github.repo:
            self._target_gh = GitHubClient(repo=target_repo_override, github_token=self._github_token)
            console.print(f"  🎯 Targeting project repo: [bold]{target_repo_override}[/bold]")
        else:
            self._target_gh = self.github  # same repo for tracking and code

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

        # ── Stage 5: Test Runner + Fix Loop ──────────────────────────────────
        if result.test_files:
            self._run_stage(
                "🏃 Test Runner + Fix Loop",
                "Running regression tests (with auto-fix)…",
                result,
                lambda: self._stage_test_fix_loop(result),
            )

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
        """Engineer implements the fix and opens a PR in the target project repo."""
        import re
        safe_title = re.sub(r"[^a-z0-9-]", "-", result.issue_title.lower())[:50]
        branch_name = f"{self.branch_prefix}/issue-{result.issue_number}-{safe_title}"

        eng_result = self.engineer.run_with_github(
            design=result.diagnosis,
            modules=result.modules,
            project_name=f"Bug Fix: {result.issue_title}",
            github_client=self._target_gh,
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
        """Code Reviewer reviews the fix in the target project repo."""
        if result.pr_number:
            rev_result = self.reviewer.run_with_github(
                files=result.fixed_files,
                prd=f"Bug Report: {result.issue_title}\n\n{result.issue_body}",
                project_name=f"Bug Fix #{result.issue_number}",
                github_client=self._target_gh,
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
        """QA writes regression tests. Code goes to target project; summary goes to tracker issue."""
        cross_repo = self._target_gh is not self.github
        if result.branch and result.pr_number:
            qa_result = self.qa.run_with_github(
                files=result.fixed_files,
                prd=f"Regression tests for bug: {result.issue_title}\n\n{result.issue_body}",
                project_name=f"Bug Fix #{result.issue_number}",
                github_client=self._target_gh,
                branch=result.branch,
                pr_number=result.pr_number,
                # Don't close the tracker issue from inside the agent when cross-repo;
                # _finish() will post the final comment on the tracker issue instead.
                issue_number=None if cross_repo else result.issue_number,
                tracker_github_client=self.github if cross_repo else None,
            )
        else:
            qa_result = self.qa.run(
                files=result.fixed_files,
                prd=result.issue_body,
                project_name=f"Bug Fix #{result.issue_number}",
            )
        result.test_files = qa_result["test_files"]

    def _stage_test_runner(self, result: BugFixResult) -> None:
        """Run pytest on regression test files written to the local workspace."""
        import subprocess
        import sys

        project_dir = self.workspace_dir / f"fix-issue-{result.issue_number}"

        # Install test requirements if present
        req_file = project_dir / "requirements-test.txt"
        if not req_file.exists():
            # Fallback: write a minimal one
            project_dir.mkdir(parents=True, exist_ok=True)
            req_file.write_text("pytest\npytest-cov\npytest-timeout\nhttpx\n", encoding="utf-8")

        console.print("    📦 Installing test dependencies…")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q",
             "pytest-timeout"],  # always ensure timeout plugin is available
            check=False,
            timeout=120,
        )

        # Write test files to disk if not already present
        tests_dir = project_dir / "tests"
        if result.test_files:
            tests_dir.mkdir(parents=True, exist_ok=True)
            for filepath, content in result.test_files.items():
                full_path = project_dir / filepath
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content, encoding="utf-8")

        if not tests_dir.exists():
            console.print("    ⚠️  No tests/ directory found — skipping execution.")
            result.test_results = "No tests directory found."
            return

        console.print(f"    🏃 Running pytest in {tests_dir}…")
        try:
            import importlib.util as _ilu
            _timeout_flag = ["--timeout=30"] if _ilu.find_spec("pytest_timeout") else []
            proc = subprocess.run(
                [
                    sys.executable, "-m", "pytest", str(tests_dir), "-v", "--tb=short",
                    f"--rootdir={project_dir}", "-p", "no:cacheprovider",
                ] + _timeout_flag,  # --timeout=30 only if pytest-timeout is available
                capture_output=True,
                text=True,
                cwd=str(project_dir),
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            result.test_results = "Tests timed out after 5 minutes."
            result.tests_passed = False
            return

        output = proc.stdout + proc.stderr
        result.tests_passed = proc.returncode == 0
        result.test_results = output
        status = "✅ All tests passed" if result.tests_passed else "❌ Some tests failed"
        console.print(f"    {status}")

        lines = output.strip().splitlines()
        for line in lines[-20:]:
            console.print(f"    [dim]{line}[/dim]")

        if hasattr(self, "_target_gh") and self._target_gh and getattr(result, "pr_number", None):
            truncated = "\n".join(lines[-60:]) if len(lines) > 60 else output
            self._target_gh.add_pr_comment(
                result.pr_number,
                f"## 🏃 Regression Test Results\n\n"
                f"**Status:** {status}\n\n```\n{truncated}\n```",
            )

    def _stage_test_fix_loop(self, result: BugFixResult) -> None:
        """Run regression tests and retry engineer fixes on failure."""
        project_dir = self.workspace_dir / f"fix-issue-{result.issue_number}"
        skip = {".git", "__pycache__", "node_modules"}

        def get_all_files_fn() -> dict:
            # Merge fixed_files and test_files; re-read from disk to capture prior patches
            files: dict[str, str] = {}
            if project_dir.exists():
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
            return files or {**result.fixed_files, **result.test_files}

        def write_files_fn(patches: dict) -> None:
            for filepath, content in patches.items():
                full_path = project_dir / filepath
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content, encoding="utf-8")
            # Keep result.fixed_files in sync so _finish() reports correctly
            result.fixed_files.update(patches)

        def commit_fn(attempt: int, patches: dict) -> bool:
            if hasattr(self, "_target_gh") and self._target_gh and getattr(result, "branch", None):
                for filepath, content in patches.items():
                    self._target_gh.commit_file(
                        path=filepath,
                        content=content,
                        message=f"fix(auto): regression test retry {attempt}/{self.max_test_retries}",
                        branch=result.branch,
                    )
            return True  # GitHub API always commits; cannot detect "no diff" to short-circuit

        def post_comment_fn(message: str) -> None:
            # Post on the tracker issue (self.github), not the code PR
            if self.github:
                self.github.add_issue_comment(result.issue_number, message)

        def fix_fn(failure_output: str, all_files: dict) -> dict:
            return self.engineer.fix_failures(
                failure_output=failure_output,
                all_files=all_files,
                design=result.diagnosis,
                project_name=f"Bug Fix #{result.issue_number}",
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

        # When code went to a different repo, close the tracker issue with a summary link
        cross_repo = hasattr(self, "_target_gh") and self._target_gh is not self.github
        if cross_repo and not result.errors:
            target_repo = self._target_gh.repo
            body = (
                f"## ✅ Bug Fix Complete\n\n"
                f"Fix implemented in **[{target_repo}]"
                f"(https://github.com/{target_repo})**.\n\n"
            )
            if result.pr_url:
                body += f"- 🔧 PR: {result.pr_url}\n"
            body += (
                f"- 📁 Fixed files: {len(result.fixed_files)}\n"
                f"- 🧪 Test files: {len(result.test_files)}\n"
                f"- 🔍 Review verdict: {result.verdict or '—'}"
            )
            try:
                self.github.close_issue(result.issue_number, comment=body)
            except Exception:
                pass  # Non-critical

        table = Table(title="Bug Fix Summary", show_header=True, header_style="bold red")
        table.add_column("Stage", style="cyan")
        table.add_column("Output")

        table.add_row("Issue", f"#{result.issue_number}: {result.issue_title[:60]}")
        if cross_repo:
            table.add_row("Target repo", self._target_gh.repo)
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
