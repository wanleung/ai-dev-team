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
        prog="ai-dev-team",
        description="🏢 AI Software House — a team of AI agents that builds software from a requirement.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run locally (no GitHub integration)
  python main.py "Build a REST API for a bookmark manager"

  # Load requirement from a text file
  python main.py --file requirements.txt
  python main.py --file requirements.txt --repo myuser/myrepo

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
        help="Default LLM model for all agents (e.g. gpt-4.1). Overrides config.yaml.",
    )
    parser.add_argument(
        "--model-override",
        metavar="AGENT=MODEL",
        action="append",
        dest="model_overrides",
        help=(
            "Per-agent model override. Can be repeated. "
            "e.g. --model-override engineer=gpt-4.1-mini --model-override architect=claude-3.5-sonnet"
        ),
    )
    parser.add_argument(
        "--engineers",
        type=int,
        metavar="N",
        help="Number of parallel engineer agents (default: 2). Overrides config.yaml.",
    )
    parser.add_argument(
        "--junior-engineers",
        type=int,
        default=None,
        metavar="N",
        help="Number of parallel junior engineer agents. Overrides config.yaml num_junior_engineers.",
    )
    parser.add_argument(
        "--senior-engineers",
        type=int,
        default=None,
        metavar="N",
        help="Number of parallel senior engineer agents. Overrides config.yaml num_senior_engineers.",
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
    parser.add_argument(
        "--refactor",
        action="store_true",
        help="Run in dream/refactor mode: analyse workspace code and open a cleanup PR instead of building new features.",
    )
    parser.add_argument(
        "--mode",
        choices=["build", "revise"],
        default="build",
        help="Pipeline mode: 'build' (default) builds new software; 'revise' processes PR feedback.",
    )
    parser.add_argument(
        "--pr",
        type=int,
        metavar="PR_NUMBER",
        help="Pull request number to revise (required when --mode=revise).",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore any saved checkpoint and start the pipeline from scratch.",
    )
    parser.add_argument(
        "--file",
        metavar="PATH",
        help="Read the requirement from a text file instead of the command line "
             "(e.g. --file requirements.txt). Overrides the positional argument.",
    )
    parser.add_argument(
        "--update-skills",
        action="store_true",
        help="Re-fetch marketplace skill index and refresh all cached skills, then exit.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # ── Prompt for requirement if not provided ────────────────────────────────
    requirement = args.requirement

    # --file takes priority over the positional argument
    if args.file:
        try:
            requirement = open(args.file, encoding="utf-8").read().strip()
            if not requirement:
                console.print(f"[red]File '{args.file}' is empty.[/red]")
                return 1
            console.print(f"[dim]📄 Loaded requirement from {args.file} ({len(requirement)} chars)[/dim]")
        except OSError as e:
            console.print(f"[red]Cannot read file '{args.file}': {e}[/red]")
            return 1

    if not requirement and args.mode != "revise":
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

        if os.path.exists(args.config):
            orch = Orchestrator.from_config(args.config, github_token=github_token)
        else:
            orch = Orchestrator(github_token=github_token)

        # Apply CLI overrides
        agent_map = {
            "product_manager": orch.pm,
            "pm_reviewer": orch.pm_reviewer,
            "architect": orch.architect,
            "architect_reviewer": orch.architect_reviewer,
            "engineer": orch.engineer,
            "code_reviewer": orch.reviewer,
            "qa_planner": orch.qa_planner,
            "qa_engineer": orch.qa,
            "deployment_tester": orch.deployment_tester,
        }
        if args.model:
            for agent in agent_map.values():
                agent.model = args.model
            orch.model = args.model
        if args.model_overrides:
            for spec in args.model_overrides:
                if "=" not in spec:
                    console.print(f"[yellow]⚠️  Ignoring invalid --model-override '{spec}' (expected AGENT=MODEL)[/yellow]")
                    continue
                agent_name, model_name = spec.split("=", 1)
                if agent_name not in agent_map:
                    console.print(f"[yellow]⚠️  Unknown agent '{agent_name}'. Valid: {', '.join(agent_map)}[/yellow]")
                    continue
                agent_map[agent_name].model = model_name
                console.print(f"  🔧 {agent_name}: {model_name}")
        if args.engineers:
            orch.num_engineers = args.engineers
        if args.junior_engineers:
            orch.num_junior_engineers = args.junior_engineers
        elif args.engineers:
            # --engineers shorthand: junior gets 2× senior
            orch.num_junior_engineers = args.engineers * 2
            orch.num_senior_engineers = args.engineers
        if args.senior_engineers:
            orch.num_senior_engineers = args.senior_engineers
        if args.repo and not args.no_github:
            from github_client import GitHubClient
            orch.github = GitHubClient(repo=args.repo, github_token=github_token)
            orch.target_github = orch.github
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

    # ── Handle --update-skills ────────────────────────────────────────────────
    if args.update_skills:
        if orch.skill_loader:
            try:
                console.print("[bold cyan]🔄 Updating skills from marketplace...[/bold cyan]")
                orch.skill_loader.update_marketplace()
                console.print("[bold green]✅ Skills updated.[/bold green]")
            except Exception as e:
                console.print(f"[bold red]❌ Failed to update skills: {e}[/bold red]")
                return 1
        else:
            console.print("[yellow]No skill_loader configured.[/yellow]")
        return 0

    # ── Run the pipeline ──────────────────────────────────────────────────────
    try:
        if args.refactor:
            refactor_result = orch.refactor()
            if refactor_result.get("pr_url"):
                console.print(f"\n[bold green]🌙 Refactor complete![/bold green] PR: {refactor_result['pr_url']}")
            else:
                console.print("\n[bold green]🌙 Refactor analysis complete![/bold green] (No PR — GitHub not configured or no changes)")
            return 0
        if args.mode == "revise":
            if not args.pr:
                console.print("[red]--pr PR_NUMBER is required when --mode=revise[/red]")
                return 1
            revision_result = orch.run_revision(args.pr)
            status = revision_result.get("status")
            if status == "max_revisions_reached":
                console.print("\n[yellow]⏹ Max revisions reached — no changes made.[/yellow]")
            elif status == "no_feedback":
                console.print("\n[dim]No human feedback found — no changes made.[/dim]")
            elif status == "error":
                console.print(f"\n[red]⚠️ Revision failed: {revision_result.get('reason', 'unknown')}[/red]")
                return 1
            elif status == "ok":
                rev_num = revision_result.get("revision", "?")
                files = revision_result.get("files_updated", 0)
                console.print(f"\n[bold green]✅ Revision {rev_num} complete![/bold green] {files} file(s) updated.")
            else:
                console.print(f"[red]⚠️ Unexpected revision status: {status}[/red]")
                return 1
            return 0
        result = orch.run(requirement, resume=not args.no_resume)
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
