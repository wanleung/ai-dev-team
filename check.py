#!/usr/bin/env python3
"""
AI Software House — setup validation CLI.

Usage:
    python check.py validate-config [--config config.yaml] [--repos repos.yaml]
    python check.py test-github [--repo owner/repo] [--token TOKEN]
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

import requests
from rich.console import Console

console = Console()


# ── validate-config ──────────────────────────────────────────────────────────

def cmd_validate_config(config: str, repos: str) -> int:
    """Validate config.yaml and repos.yaml. Returns exit code."""
    from config_schema import load_config, load_repo_entry
    import yaml
    from pydantic import ValidationError

    errors = 0

    # Validate config.yaml
    console.print(f"\n[bold]Validating {config}...[/bold]")
    if not os.path.exists(config):
        console.print(f"  [red]❌ File not found: {config}[/red]")
        errors += 1
    else:
        try:
            cfg = load_config(config)
            console.print(f"  [green]✅ llm.model:[/green] {cfg.llm.model}")
            if cfg.github:
                console.print(f"  [green]✅ github.repo:[/green] {cfg.github.repo or '(not set)'}")
            if cfg.pipeline:
                console.print(f"  [green]✅ pipeline.num_engineers:[/green] {cfg.pipeline.num_engineers}")
            console.print(f"  [green]✅ config.yaml is valid[/green]")
        except ValidationError as exc:
            for err in exc.errors():
                loc = " → ".join(str(x) for x in err["loc"])
                console.print(f"  [red]❌ {loc}:[/red] {err['msg']}")
            errors += len(exc.errors())
        except Exception as exc:
            console.print(f"  [red]❌ Failed to load: {exc}[/red]")
            errors += 1

    # Validate repos.yaml
    console.print(f"\n[bold]Validating {repos}...[/bold]")
    if not os.path.exists(repos):
        console.print(f"  [yellow]⚠️  File not found: {repos} (optional)[/yellow]")
    else:
        try:
            with open(repos, encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            watchers = raw.get("watchers", [])
            if not watchers:
                console.print("  [yellow]⚠️  No watchers defined[/yellow]")
            for entry in watchers:
                try:
                    r = load_repo_entry(entry)
                    status = "enabled" if r.enabled else "disabled"
                    console.print(f"  [green]✅[/green] {r.tracker_repo} ({status}, {r.parallel_issues} parallel)")
                except ValidationError as exc:
                    name = entry.get("tracker_repo", "?") if isinstance(entry, dict) else repr(entry)
                    for err in exc.errors():
                        loc = " → ".join(str(x) for x in err["loc"])
                        console.print(f"  [red]❌ {name} {loc}:[/red] {err['msg']}")
                        errors += 1
        except Exception as exc:
            console.print(f"  [red]❌ Failed to load: {exc}[/red]")
            errors += 1

    if errors:
        console.print(f"\n[red]{errors} error(s) found. Fix before running the pipeline.[/red]")
    else:
        console.print("\n[green]All configuration is valid.[/green]")

    return 1 if errors else 0


# ── test-github ───────────────────────────────────────────────────────────────

def cmd_test_github(repo: str, token: str | None) -> int:
    """Test GitHub credentials. Returns exit code."""
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        console.print("[red]❌ No token provided. Set GITHUB_TOKEN or pass --token.[/red]")
        return 1

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    errors = 0

    console.print("\n[bold]Testing GitHub credentials...[/bold]")

    # Check token identity
    try:
        resp = requests.get("https://api.github.com/user", headers=headers, timeout=10)
    except requests.exceptions.RequestException as exc:
        console.print(f"  [red]❌ Network error reaching GitHub: {exc}[/red]")
        return 1
    if resp.ok:
        user = resp.json().get("login", "unknown")
        scopes = resp.headers.get("X-OAuth-Scopes", "(none)")
        remaining = resp.headers.get("X-RateLimit-Remaining", "?")
        reset_ts = resp.headers.get("X-RateLimit-Reset")
        reset_str = ""
        if reset_ts:
            reset_dt = datetime.fromtimestamp(int(reset_ts), tz=timezone.utc)
            mins = max(0, int((reset_dt - datetime.now(tz=timezone.utc)).total_seconds() / 60))
            reset_str = f" (resets in {mins} min)"
        console.print(f"  [green]✅ Token valid[/green] — authenticated as: [bold]{user}[/bold]")
        console.print(f"  [green]✅ Token scopes:[/green] {scopes}")
        console.print(f"  [green]✅ Rate limit:[/green] {remaining}/5000 remaining{reset_str}")
    else:
        try:
            msg = resp.json().get("message", "")
        except ValueError:
            msg = resp.text[:120]
        console.print(f"  [red]❌ Token invalid — HTTP {resp.status_code}: {msg}[/red]")
        errors += 1

    # Check repo access
    if repo:
        console.print(f"\n[bold]Testing repo access: {repo}[/bold]")
        try:
            resp2 = requests.get(f"https://api.github.com/repos/{repo}", headers=headers, timeout=10)
        except requests.exceptions.RequestException as exc:
            console.print(f"  [red]❌ Network error reaching GitHub: {exc}[/red]")
            return 1
        if resp2.ok:
            data = resp2.json()
            perms = data.get("permissions", {})
            push = "✅" if perms.get("push") else "❌"
            default_branch = data.get("default_branch", "?")
            console.print(f"  [green]✅ Repo {repo}[/green] — read access ✓, push access {push}")
            console.print(f"  [green]✅ Default branch:[/green] {default_branch}")
            if not perms.get("push"):
                console.print("  [yellow]⚠️  No push access — pipeline will fail when committing code[/yellow]")
                errors += 1
        else:
            console.print(f"  [red]❌ Cannot access repo {repo} — HTTP {resp2.status_code}[/red]")
            errors += 1

    if errors == 0:
        console.print("\n[green]All checks passed.[/green]")
    else:
        console.print(f"\n[red]{errors} check(s) failed.[/red]")

    return 1 if errors else 0


# ── CLI entry point ───────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check",
        description="AI Software House — setup validation",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # validate-config
    vc = sub.add_parser("validate-config", help="Validate config.yaml and repos.yaml")
    vc.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    vc.add_argument("--repos", default="repos.yaml", help="Path to repos.yaml")

    # test-github
    tg = sub.add_parser("test-github", help="Test GitHub token and repo access")
    tg.add_argument("--repo", default=os.environ.get("GITHUB_REPO", ""), help="owner/repo to test")
    tg.add_argument("--token", default=None, help="GitHub token (default: GITHUB_TOKEN env)")

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "validate-config":
        return cmd_validate_config(config=args.config, repos=args.repos)
    elif args.command == "test-github":
        return cmd_test_github(repo=args.repo, token=args.token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
