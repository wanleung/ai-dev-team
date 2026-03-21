#!/usr/bin/env python3
"""
AI Software House — main CLI entry point.

Usage:
    python main.py "Build a task management REST API with user auth"
    python main.py "Build a chat app" --repo owner/repo --engineers 3
    python main.py "Build a todo app" --no-github --model gpt-4.1-mini
"""
from __future__ import annotations

import argparse
import os
import sys

from rich.console import Console
from rich.panel import Panel

console = Console()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ai-software-house",
        description="🏢 AI Software House — a team of AI agents that builds software from a requirement.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run locally (no GitHub integration)
  python main.py "Build a REST API for a bookmark manager"

  # Run with GitHub integration (creates Issues + PR)
  python main.py "Build a blog platform" --repo myuser/myrepo

  # Use a faster model and more engineers
  python main.py "Build a calculator app" --model gpt-4.1-mini --engineers 3

  # Use a config file
  python main.py "Build a weather app" --config config.yaml

Setup:
  export GITHUB_TOKEN=ghp_your_token_here
  # Token needs: Copilot Requests + repo (contents, issues, pull_requests) permissions
  # Create at: https://github.com/settings/personal-access-tokens/new
        """,
    )

    parser.add_argument(
        "requirement",
        nargs="?",
        help="The software requirement in plain English (e.g. 'Build a REST API for a task manager')",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        metavar="FILE",
        help="Path to config YAML file (default: config.yaml)",
    )
    parser.add_argument(
        "--repo",
        metavar="OWNER/REPO",
        help="GitHub repo for integration (e.g. 'myuser/myproject'). Overrides config.yaml.",
    )
    parser.add_argument(
        "--model",
        metavar="MODEL",
        help="LLM model name (e.g. gpt-4.1, gpt-4.1-mini). Overrides config.yaml.",
    )
    parser.add_argument(
        "--engineers",
        type=int,
        metavar="N",
        help="Number of parallel engineer agents (default: 2). Overrides config.yaml.",
    )
    parser.add_argument(
        "--no-github",
        action="store_true",
        help="Disable GitHub integration even if repo is configured.",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        metavar="DIR",
        help="Local directory to save generated files (default: ./workspace).",
    )
    parser.add_argument(
        "--token",
        metavar="TOKEN",
        help="GitHub token (overrides GITHUB_TOKEN env var).",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # ── Prompt for requirement if not provided ────────────────────────────────
    requirement = args.requirement
    if not requirement:
        console.print(Panel.fit(
            "[bold cyan]🏢 AI Software House[/bold cyan]\n"
            "[dim]A team of AI agents: PM → Architect → Engineers → Reviewer → QA[/dim]",
            border_style="cyan",
        ))
        requirement = console.input("[bold]Enter your software requirement:[/bold] ").strip()
        if not requirement:
            console.print("[red]No requirement provided. Exiting.[/red]")
            return 1

    # ── Token ────────────────────────────────────────────────────────────────
    github_token = args.token or os.environ.get("GITHUB_TOKEN")
    if not github_token:
        console.print(
            "[bold red]❌ GITHUB_TOKEN not set.[/bold red]\n"
            "Create a token at [link]https://github.com/settings/personal-access-tokens/new[/link]\n"
            "Permissions needed: [bold]Copilot Requests[/bold] + [bold]repo[/bold] (contents, issues, pull_requests)\n\n"
            "Then run:\n  [bold]export GITHUB_TOKEN=ghp_your_token[/bold]"
        )
        return 1

    # ── Build Orchestrator ────────────────────────────────────────────────────
    try:
        from orchestrator import Orchestrator
        import os.path

        if os.path.exists(args.config):
            orch = Orchestrator.from_config(args.config, github_token=github_token)
        else:
            orch = Orchestrator(github_token=github_token)

        # Apply CLI overrides
        if args.model:
            orch.model = args.model
            orch.pm.model = args.model
            orch.architect.model = args.model
            orch.reviewer.model = args.model
            orch.qa.model = args.model
        if args.engineers:
            orch.num_engineers = args.engineers
        if args.repo and not args.no_github:
            from github_client import GitHubClient
            orch.github = GitHubClient(repo=args.repo, github_token=github_token)
            orch.use_github = True
        if args.no_github:
            orch.github = None
            orch.use_github = False
        if args.workspace:
            from pathlib import Path
            orch.workspace_dir = Path(args.workspace)

    except FileNotFoundError as e:
        console.print(f"[red]Config error: {e}[/red]")
        return 1
    except EnvironmentError as e:
        console.print(f"[red]{e}[/red]")
        return 1

    # ── Run the pipeline ──────────────────────────────────────────────────────
    try:
        result = orch.run(requirement)
    except KeyboardInterrupt:
        console.print("\n[yellow]Pipeline interrupted.[/yellow]")
        return 130

    # ── Exit code based on pipeline success ───────────────────────────────────
    if result.errors:
        console.print(f"\n[bold yellow]⚠️  Pipeline completed with {len(result.errors)} error(s).[/bold yellow]")
        return 1

    console.print("\n[bold green]🎉 Pipeline complete![/bold green]")
    if result.pr_url:
        console.print(f"   PR: {result.pr_url}")
    if result.all_files:
        console.print(f"   Local files saved in: ./workspace/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
