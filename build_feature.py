#!/usr/bin/env python3
"""
build_feature.py — Entry point for the GitHub Actions feature-build trigger.

Called by .github/workflows/feature-build.yml when an issue is labeled 'ai-feature'.
Fetches the issue from GitHub, runs the full Orchestrator pipeline, and reports back.

Usage (GitHub Actions):
    python build_feature.py --issue-number 42 --tracker-repo owner/ai-software-house

Usage (manual testing):
    GITHUB_TOKEN=ghp_xxx python build_feature.py --issue-number 7 --tracker-repo me/ai-software-house
"""
from __future__ import annotations

import argparse
import os
import sys

from rich.console import Console

console = Console()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="build-feature",
        description="✨ AI Feature Builder — runs the full agent pipeline on a GitHub Issue.",
    )
    parser.add_argument(
        "--issue-number",
        type=int,
        required=True,
        metavar="N",
        help="GitHub Issue number containing the feature requirement.",
    )
    parser.add_argument(
        "--tracker-repo",
        metavar="OWNER/REPO",
        help="The repo where the issue lives (the ai-software-house repo). "
             "Falls back to config.yaml github.repo.",
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
        "--engineers",
        type=int,
        metavar="N",
        help="Number of parallel engineer agents.",
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
        from github_client import GitHubClient
        from orchestrator import Orchestrator
        import os.path

        # ── Build orchestrator from config ────────────────────────────────────
        if os.path.exists(args.config):
            orch = Orchestrator.from_config(args.config, github_token=github_token)
        else:
            orch = Orchestrator(github_token=github_token)

        # ── Override tracker repo (the repo that owns the issue) ──────────────
        tracker_repo = args.tracker_repo
        if tracker_repo:
            orch.github = GitHubClient(repo=tracker_repo, github_token=github_token)
            orch.use_github = True
            if orch.target_github is None:
                orch.target_github = orch.github  # default: same repo

        if not orch.github:
            console.print(
                "[red]No tracker repo configured. "
                "Set github.repo in config.yaml or use --tracker-repo.[/red]"
            )
            return 1

        # ── Apply CLI overrides ───────────────────────────────────────────────
        if args.model:
            for agent in (orch.pm, orch.architect, orch.reviewer, orch.qa):
                agent.model = args.model
            orch.model = args.model
        if args.engineers:
            orch.num_engineers = args.engineers

        # ── Fetch the triggering issue ────────────────────────────────────────
        issue = orch.github._request(
            "GET", f"/repos/{orch.github.repo}/issues/{args.issue_number}"
        )
        issue_title = issue.get("title", "")
        issue_body = issue.get("body", "") or ""
        requirement = f"{issue_title}\n\n{issue_body}".strip()

        console.print(
            f"[bold cyan]🏢 Building feature from Issue #{args.issue_number}:[/bold cyan] "
            f"{issue_title[:80]}"
        )

    except Exception as exc:
        console.print(f"[red]Setup error: {exc}[/red]")
        return 1

    # ── Run the pipeline ──────────────────────────────────────────────────────
    try:
        result = orch.run(requirement, trigger_issue_body=issue_body)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        return 130

    if result.errors:
        console.print(f"\n[bold yellow]⚠️  Completed with {len(result.errors)} error(s).[/bold yellow]")
        return 1

    console.print("\n[bold green]🎉 Feature pipeline complete![/bold green]")
    if result.pr_url:
        console.print(f"   PR: {result.pr_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
