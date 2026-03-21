#!/usr/bin/env python3
"""
fix_issue.py — Entry point for the GitHub Actions bug-fix trigger.

Called by .github/workflows/bug-fix.yml with the issue number from the event.
Reads issue details from GitHub, runs BugFixOrchestrator, and reports back.

Usage (GitHub Actions):
    python fix_issue.py --issue-number 42

Usage (manual testing):
    GITHUB_TOKEN=ghp_xxx python fix_issue.py --issue-number 42 --repo owner/repo
"""
from __future__ import annotations

import argparse
import os
import sys

from rich.console import Console

console = Console()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fix-issue",
        description="🐛 AI Bug Fixer — runs the bug-fix agent pipeline on a GitHub Issue.",
    )
    parser.add_argument(
        "--issue-number",
        type=int,
        required=True,
        metavar="N",
        help="GitHub Issue number to fix (e.g. 42)",
    )
    parser.add_argument(
        "--repo",
        metavar="OWNER/REPO",
        help="GitHub repo (e.g. 'myuser/myproject'). Overrides config.yaml.",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        metavar="FILE",
        help="Path to config YAML file (default: config.yaml)",
    )
    parser.add_argument(
        "--model",
        metavar="MODEL",
        help="LLM model override (e.g. gpt-4.1)",
    )
    parser.add_argument(
        "--token",
        metavar="TOKEN",
        help="GitHub token (overrides GITHUB_TOKEN env var)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    github_token = args.token or os.environ.get("GITHUB_TOKEN")
    if not github_token:
        console.print(
            "[bold red]❌ GITHUB_TOKEN not set.[/bold red]\n"
            "Set it as a repository secret in: Settings → Secrets → Actions → New repository secret\n"
            "Name: GITHUB_TOKEN  (GitHub provides this automatically in Actions)\n\n"
            "For local testing:\n  export GITHUB_TOKEN=ghp_your_token"
        )
        return 1

    try:
        from bug_fix_orchestrator import BugFixOrchestrator

        if os.path.exists(args.config):
            orch = BugFixOrchestrator.from_config(args.config, github_token=github_token)
        else:
            orch = BugFixOrchestrator(github_token=github_token)

        # CLI overrides
        if args.repo:
            from github_client import GitHubClient
            orch.github = GitHubClient(repo=args.repo, github_token=github_token)
        if args.model:
            orch.model = args.model
            orch.architect.model = args.model
            orch.engineer.model = args.model
            orch.reviewer.model = args.model
            orch.qa.model = args.model

        if not orch.github:
            console.print(
                "[red]No GitHub repo configured. Set github.repo in config.yaml or use --repo.[/red]"
            )
            return 1

    except Exception as exc:
        console.print(f"[red]Setup error: {exc}[/red]")
        return 1

    try:
        result = orch.run(issue_number=args.issue_number)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        return 130

    if result.errors:
        console.print(f"\n[bold yellow]⚠️  Completed with {len(result.errors)} error(s).[/bold yellow]")
        return 1

    console.print("\n[bold green]🎉 Bug fix pipeline complete![/bold green]")
    if result.pr_url:
        console.print(f"   PR: {result.pr_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
