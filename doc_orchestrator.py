"""
DocOrchestrator: a focused pipeline triggered by GitHub Issue documentation requests.

Unlike the full software house pipeline (PM→Architect→Engineer→Reviewer→QA),
this pipeline is optimised for documentation:

  Issue (doc request) → DocumentationAgent → Commit files → PR

No multi-agent handoff — the DocumentationAgent reads the repo and writes docs.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from agents.documentation_agent import DocumentationAgent
from github_client import GitHubClient, parse_target_repo

console = Console()


@dataclass
class DocResult:
    """Holds all artifacts produced by the documentation pipeline."""

    issue_number: int
    issue_title: str
    issue_body: str
    file_writes: list[dict] = field(default_factory=list)  # from DocumentationAgent.run()
    committed_files: list[str] = field(default_factory=list)  # paths actually committed
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    branch: Optional[str] = None
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


class DocOrchestrator:
    """Runs the documentation pipeline triggered by a GitHub Issue.

    Usage:
        orch = DocOrchestrator.from_config("config.yaml")
        result = orch.run(issue_number=42)
    """

    def __init__(
        self,
        model: str = "gpt-4.1",
        github_repo: Optional[str] = None,
        github_token: Optional[str] = None,
        branch_prefix: str = "doc",
        model_overrides: Optional[dict] = None,
    ) -> None:
        self.model = model
        self.branch_prefix = branch_prefix
        self._github_token = github_token
        # model_overrides reserved for future use
        self._model_overrides = model_overrides or {}

        self.github: Optional[GitHubClient] = None
        if github_repo:
            self.github = GitHubClient(repo=github_repo, github_token=github_token)

    @classmethod
    def from_config(
        cls,
        config_path: str = "config.yaml",
        github_token: Optional[str] = None,
    ) -> "DocOrchestrator":
        """Create from a config.yaml file (same format as BugFixOrchestrator.from_config)."""
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        llm = cfg.get("llm", {})
        gh = cfg.get("github", {})
        repo = gh.get("repo", "")

        return cls(
            model=llm.get("model", "gpt-4.1"),
            github_repo=repo if repo and repo != "your-username/your-repo" else None,
            github_token=github_token,
            branch_prefix=gh.get("doc_branch_prefix", "doc"),
            model_overrides=llm.get("overrides", {}),
        )

    def run(self, issue_number: int) -> DocResult:
        """Run the documentation pipeline for a GitHub Issue.

        Args:
            issue_number: GitHub Issue number containing the documentation request.

        Returns:
            DocResult with all artifacts and any errors encountered.

        Raises:
            EnvironmentError: If GitHub integration is not configured.
        """
        if not self.github:
            raise EnvironmentError(
                "GitHub integration is required for DocOrchestrator. "
                "Set github.repo in config.yaml and provide GITHUB_TOKEN."
            )

        # ── Fetch issue ──────────────────────────────────────────────────────
        issue = self.github.get_issue(issue_number)
        result = DocResult(
            issue_number=issue_number,
            issue_title=issue.get("title", "Documentation Request"),
            issue_body=issue.get("body", ""),
        )
        start_time = time.time()

        console.print(Panel.fit(
            f"[bold blue]📚 Documentation Pipeline[/bold blue]\n"
            f"[dim]Issue #{issue_number}: {result.issue_title[:100]}[/dim]",
            border_style="blue",
        ))

        # ── Post acknowledgement ─────────────────────────────────────────────
        try:
            self.github.add_issue_comment(
                issue_number,
                "🤖 **AI Software House** — Documentation pipeline started...\n\n"
                "The documentation agent is reading the repository and will open a PR shortly.",
            )
        except Exception as exc:
            result.errors.append(f"Acknowledgement comment failed: {exc}")

        # ── Detect target repo ───────────────────────────────────────────────
        target_repo_override = parse_target_repo(result.issue_body)
        if target_repo_override and target_repo_override != self.github.repo:
            target_gh = GitHubClient(repo=target_repo_override, github_token=self._github_token)
            console.print(f"  🎯 Targeting project repo: [bold]{target_repo_override}[/bold]")
        else:
            target_gh = self.github

        # ── Create branch ────────────────────────────────────────────────────
        branch = None
        try:
            branch = self._make_branch_name(issue_number, result.issue_title)
            target_gh.create_branch(branch)
            result.branch = branch
        except Exception as exc:
            result.errors.append(f"Branch creation failed: {exc}")
            return self._finish(result, start_time)

        # ── Run DocumentationAgent ───────────────────────────────────────────
        self._run_stage(
            "📝 Documentation Agent",
            "Reading repo and generating documentation...",
            result,
            lambda: self._stage_generate(result, target_gh),
        )
        if not result.file_writes:
            if not result.errors:
                result.errors.append("DocumentationAgent returned no file writes")
            return self._finish(result, start_time)

        # ── Commit files ─────────────────────────────────────────────────────
        self._run_stage(
            "💾 Committing Files",
            "Writing documentation files to branch...",
            result,
            lambda: self._stage_commit(result, target_gh, branch),
        )
        if not result.committed_files:
            if not result.errors:
                result.errors.append("No files were successfully committed")
            return self._finish(result, start_time)

        # ── Create PR ────────────────────────────────────────────────────────
        self._run_stage(
            "🔀 Pull Request",
            "Opening pull request...",
            result,
            lambda: self._stage_pr(result, target_gh, branch),
        )

        # ── Close issue ──────────────────────────────────────────────────────
        try:
            cross_repo = target_gh is not self.github
            close_body = self._build_close_comment(result, target_gh if cross_repo else None)
            self.github.close_issue(issue_number, comment=close_body)
        except Exception as exc:
            result.errors.append(f"Close issue failed: {exc}")

        return self._finish(result, start_time)

    # ── Stage implementations ────────────────────────────────────────────────

    def _stage_generate(self, result: DocResult, target_gh: GitHubClient) -> None:
        """Run DocumentationAgent to produce file writes."""
        agent = DocumentationAgent(model=self.model, github_token=self._github_token)
        result.file_writes = agent.run(
            issue_title=result.issue_title,
            issue_body=result.issue_body,
            github_client=target_gh,
        )

    def _stage_commit(self, result: DocResult, target_gh: GitHubClient, branch: str) -> None:
        """Commit each file write to the branch."""
        for write in result.file_writes:
            path = write.get("path", "")
            content = write.get("content", "")
            action = write.get("action", "update")
            commit_msg = f"docs: {action} {path} (issue #{result.issue_number})"
            try:
                target_gh.commit_file(
                    path=path,
                    content=content,
                    message=commit_msg,
                    branch=branch,
                )
                result.committed_files.append(path)
                console.print(f"    [green]✓[/green] {action} {path}")
            except Exception as exc:
                error_msg = f"Failed to commit {path}: {exc}"
                result.errors.append(error_msg)
                console.print(f"    [red]✗[/red] {error_msg}")

    def _stage_pr(self, result: DocResult, target_gh: GitHubClient, branch: str) -> None:
        """Open a pull request for the committed documentation files."""
        files_list = "\n".join(f"- `{p}`" for p in result.committed_files)
        pr_body = (
            f"## 📚 Documentation Update\n\n"
            f"Resolves #{result.issue_number}: {result.issue_title}\n\n"
            f"### Files updated\n\n{files_list}\n\n"
            f"_Generated by AI Software House Documentation Pipeline._"
        )
        pr = target_gh.create_pull_request(
            title=f"docs: {result.issue_title}",
            body=pr_body,
            head=branch,
            base="main",
        )
        result.pr_number = pr.get("number")
        result.pr_url = pr.get("html_url")

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _make_branch_name(self, issue_number: int, issue_title: str) -> str:
        """Return branch name like 'doc/42-update-readme-installation' (max 60 chars).

        Args:
            issue_number: GitHub Issue number.
            issue_title: Title of the issue (used to generate a URL-safe slug).

        Returns:
            Branch name string, at most 60 characters.
        """
        slug = issue_title.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        slug = slug.strip("-")

        prefix = f"{self.branch_prefix}/{issue_number}-"
        max_slug_len = 60 - len(prefix)
        slug = slug[:max_slug_len].rstrip("-")

        return f"{prefix}{slug}"

    def _run_stage(self, name: str, description: str, result: DocResult, fn) -> None:
        """Run a pipeline stage with a spinner, catching and recording any errors."""
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

    def _build_close_comment(
        self,
        result: DocResult,
        target_gh: Optional[GitHubClient],
    ) -> str:
        """Build the comment body used when closing the tracker issue."""
        if target_gh:
            repo_link = f"**[{target_gh.repo}](https://github.com/{target_gh.repo})**"
            body = f"## ✅ Documentation Pipeline Complete\n\nDocs committed to {repo_link}.\n\n"
        else:
            body = "## ✅ Documentation Pipeline Complete\n\n"

        if result.pr_url:
            body += f"- 📄 PR: {result.pr_url}\n"
        body += f"- 📁 Files committed: {len(result.committed_files)}\n"
        if result.errors:
            body += f"\n⚠️ Errors: {'; '.join(result.errors)}"
        return body

    def _finish(self, result: DocResult, start_time: float) -> DocResult:
        """Compute duration and print the Rich summary table."""
        result.duration_seconds = time.time() - start_time

        table = Table(title="Documentation Pipeline Summary", show_header=True, header_style="bold blue")
        table.add_column("Stage", style="cyan")
        table.add_column("Output")

        table.add_row("Issue", f"#{result.issue_number}: {result.issue_title[:60]}")
        table.add_row("Branch", result.branch or "—")
        table.add_row("Files written", str(len(result.committed_files)))
        if result.pr_url:
            table.add_row("Pull Request", result.pr_url)
        table.add_row("Duration", f"{result.duration_seconds:.1f}s")
        if result.errors:
            table.add_row("[red]Errors[/red]", "\n".join(result.errors))

        console.print(table)
        return result
