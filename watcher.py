#!/usr/bin/env python3
"""
watcher.py — Hourly GitHub issue poller and pipeline dispatcher.

Reads repos.yaml, finds open unprocessed issues, and runs the agent
pipeline for each one in parallel.

Usage:
    python watcher.py                       # uses repos.yaml in same directory
    python watcher.py --config my-repos.yaml
    python watcher.py --dry-run             # show what would run, no API calls
    python watcher.py --once                # run once and exit (same as cron mode)

Cron setup (hourly):
    crontab -e
    0 * * * * cd /home/you/ai-software-house && source venv/bin/activate && python watcher.py >> logs/watcher/cron.log 2>&1
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import yaml
import requests

# ── Labels used to track pipeline state ─────────────────────────────────────
LABEL_QUEUED   = "agent-queued"
LABEL_RUNNING  = "agent-running"
LABEL_COMPLETE = "agent-complete"
LABEL_FAILED   = "agent-failed"

SKIP_LABELS = {LABEL_QUEUED, LABEL_RUNNING, LABEL_COMPLETE, LABEL_FAILED}

LABEL_COLOURS = {
    LABEL_QUEUED:   "e4e669",
    LABEL_RUNNING:  "0075ca",
    LABEL_COMPLETE: "0e8a16",
    LABEL_FAILED:   "d73a4a",
}

# ── Lock file prevents overlapping cron runs ─────────────────────────────────
LOCK_FILE = Path(__file__).parent / ".watcher.lock"


def _gh_headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


# ── GitHub helpers ────────────────────────────────────────────────────────────

def ensure_label(repo: str, name: str, colour: str) -> None:
    """Create a label if it doesn't already exist."""
    url = f"https://api.github.com/repos/{repo}/labels"
    existing = requests.get(url, headers=_gh_headers(), timeout=10)
    names = {l["name"] for l in existing.json()} if existing.ok else set()
    if name not in names:
        requests.post(url, headers=_gh_headers(), json={"name": name, "color": colour}, timeout=10)


def add_label(repo: str, issue_number: int, label: str) -> None:
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/labels"
    requests.post(url, headers=_gh_headers(), json={"labels": [label]}, timeout=10)


def remove_label(repo: str, issue_number: int, label: str) -> None:
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/labels/{label}"
    requests.delete(url, headers=_gh_headers(), timeout=10)


def get_open_issues(repo: str, label: str | list[str]) -> list[dict]:
    """Return open issues with the given label(s) that haven't been processed.

    label may be a single string or a list; issues matching ANY label are returned
    (deduped by issue number).
    """
    labels = [label] if isinstance(label, str) else list(label)
    seen: set[int] = set()
    issues: list[dict] = []
    for lbl in labels:
        url = f"https://api.github.com/repos/{repo}/issues"
        params = {"state": "open", "labels": lbl, "per_page": 50}
        resp = requests.get(url, headers=_gh_headers(), params=params, timeout=10)
        if not resp.ok:
            raise RuntimeError(f"GitHub API error {resp.status_code}: {resp.text[:200]}")
        for issue in resp.json():
            if "pull_request" in issue:
                continue  # skip PRs
            if issue["number"] in seen:
                continue  # already added via another label
            issue_labels = {l["name"] for l in issue.get("labels", [])}
            if issue_labels & SKIP_LABELS:
                continue  # already processed or in progress
            seen.add(issue["number"])
            issues.append(issue)
    return issues


def post_comment(repo: str, issue_number: int, body: str) -> None:
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
    requests.post(url, headers=_gh_headers(), json={"body": body}, timeout=10)


# ── Pipeline dispatch ─────────────────────────────────────────────────────────

def run_pipeline(
    issue: dict,
    tracker_repo: str,
    default_target: str | None,
    pipeline_type: str,  # "feature" or "bug"
    model: str,
    num_engineers: int,
    log_dir: Path,
    dry_run: bool,
    logger: logging.Logger,
) -> bool:
    """Run the appropriate orchestrator for a single issue. Returns True on success."""
    issue_number = issue["number"]
    issue_title = issue["title"]

    # Resolve target repo from issue body or fall back to default
    target_repo = _parse_target_repo(issue.get("body") or "") or default_target or tracker_repo

    logger.info(
        "  → Issue #%d: %r | type=%s | target=%s",
        issue_number, issue_title, pipeline_type, target_repo,
    )

    if dry_run:
        logger.info("    [dry-run] Would run %s pipeline", pipeline_type)
        return True

    # Mark as running
    add_label(tracker_repo, issue_number, LABEL_RUNNING)
    remove_label(tracker_repo, issue_number, LABEL_QUEUED)

    # Set up per-issue log file
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    issue_log = log_dir / f"issue-{issue_number}-{ts}.log"

    try:
        _dispatch(
            pipeline_type=pipeline_type,
            tracker_repo=tracker_repo,
            target_repo=target_repo,
            issue_number=issue_number,
            model=model,
            num_engineers=num_engineers,
            log_file=issue_log,
            logger=logger,
        )
        add_label(tracker_repo, issue_number, LABEL_COMPLETE)
        remove_label(tracker_repo, issue_number, LABEL_RUNNING)
        logger.info("    ✅ Issue #%d complete", issue_number)
        return True

    except Exception as exc:  # noqa: BLE001
        logger.error("    ❌ Issue #%d failed: %s", issue_number, exc)
        add_label(tracker_repo, issue_number, LABEL_FAILED)
        remove_label(tracker_repo, issue_number, LABEL_RUNNING)
        post_comment(
            tracker_repo,
            issue_number,
            f"## ❌ Agent Pipeline Failed\n\n```\n{exc}\n```\n\n"
            f"Log: `{issue_log}`\n\nRemove the `{LABEL_FAILED}` label and re-label "
            f"the issue to retry.",
        )
        return False


def _load_pipeline_config() -> dict:
    """Load config.yaml + config.local.yaml from the script directory.

    Returns the merged config dict with llm and pipeline sections.
    """
    script_dir = Path(__file__).parent
    cfg: dict = {}
    for name in ("config.yaml", "config.local.yaml"):
        p = script_dir / name
        if p.exists():
            with open(p, encoding="utf-8") as f:
                local = yaml.safe_load(f) or {}
            # Deep merge: local overrides base
            for section, val in local.items():
                if isinstance(val, dict) and isinstance(cfg.get(section), dict):
                    cfg[section] = {**cfg.get(section, {}), **val}
                else:
                    cfg[section] = val
    return cfg


def _dispatch(
    pipeline_type: str,
    tracker_repo: str,
    target_repo: str,
    issue_number: int,
    model: str,
    num_engineers: int,
    log_file: Path,
    logger: logging.Logger,
) -> None:
    """Import and run the correct orchestrator."""
    token = os.environ.get("GITHUB_TOKEN")

    # Load config.yaml (+ config.local.yaml) to pick up model overrides and
    # pipeline tuning — these are NOT in repos.yaml.
    pipeline_cfg = _load_pipeline_config()
    llm_cfg = pipeline_cfg.get("llm", {})
    pipe_cfg = pipeline_cfg.get("pipeline", {})
    # Use config model if set (and not the placeholder default); else fall back
    # to the model passed from repos.yaml settings.
    cfg_model = llm_cfg.get("model", "") or ""
    effective_model = cfg_model if cfg_model and cfg_model != "gpt-4.1" else model
    model_overrides = llm_cfg.get("overrides", {})
    ollama_url = llm_cfg.get("ollama_url", "http://localhost:11434")
    retry_delay = pipe_cfg.get("retry_delay", 15)
    max_api_retries = pipe_cfg.get("max_api_retries", 5)
    inter_call_delay = pipe_cfg.get("inter_call_delay", 0)

    # Redirect stdout/stderr to the issue log file for this run
    with open(log_file, "w", encoding="utf-8") as fh:
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = fh
        try:
            if pipeline_type == "feature":
                from orchestrator import Orchestrator
                from github_client import GitHubClient

                tracker_gh = GitHubClient(tracker_repo, token)
                issue = tracker_gh.get_issue(issue_number)
                issue_body = issue.get("body") or ""
                requirement = (issue_body or issue.get("title") or "").strip()

                orch = Orchestrator(
                    model=effective_model,
                    model_overrides=model_overrides,
                    github_token=token,
                    github_repo=tracker_repo,
                    target_repo=target_repo,
                    num_engineers=num_engineers,
                    use_github=True,
                    ollama_url=ollama_url,
                    retry_delay=retry_delay,
                    max_api_retries=max_api_retries,
                    inter_call_delay=inter_call_delay,
                )
                orch.run(requirement, trigger_issue_body=issue_body)

            elif pipeline_type == "bug":
                from bug_fix_orchestrator import BugFixOrchestrator

                orch = BugFixOrchestrator(
                    model=effective_model,
                    github_token=token,
                    github_repo=tracker_repo,
                )
                orch.run(issue_number=issue_number)

            elif pipeline_type == "documentation":
                from doc_orchestrator import DocOrchestrator

                orch = DocOrchestrator(
                    model=effective_model,
                    github_token=token,
                    github_repo=tracker_repo,
                )
                orch.run(issue_number=issue_number)
            else:
                logger.error(
                    "Unknown pipeline_type=%r — skipping issue #%d",
                    pipeline_type,
                    issue_number,
                )
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr


def _parse_target_repo(body: str) -> str | None:
    """Extract '**Target repo:** owner/repo' from issue body."""
    import re
    m = re.search(r"\*\*Target repo:\*\*\s*([\w.\-]+/[\w.\-]+)", body)
    if m:
        return m.group(1)
    m = re.search(r"Target repo:\s*([\w.\-]+/[\w.\-]+)", body)
    return m.group(1) if m else None


# ── Watcher loop ──────────────────────────────────────────────────────────────

def watch(config_path: Path, dry_run: bool, logger: logging.Logger) -> None:
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    settings   = config.get("settings", {})
    max_parallel = settings.get("max_parallel", 3)
    log_dir    = Path(config_path.parent / settings.get("log_dir", "logs/watcher"))
    model      = settings.get("model", "gpt-4.1")
    num_engineers = settings.get("num_engineers", 2)

    watchers = config.get("watchers", [])
    logger.info("Loaded %d watcher(s) from %s", len(watchers), config_path)

    # Collect all issues across all watchers
    tasks: list[dict] = []
    for w in watchers:
        if not w.get("enabled", True):
            continue
        tracker_repo    = w["tracker_repo"]
        default_target  = w.get("default_target") or None
        feature_label   = w.get("feature_label", "feature-request")
        bug_label       = w.get("bug_label", "bug")
        doc_label       = w.get("doc_label", "documentation")

        # Ensure state labels exist
        for name, colour in LABEL_COLOURS.items():
            ensure_label(tracker_repo, name, colour)

        logger.info("Checking %s …", tracker_repo)
        try:
            for issue in get_open_issues(tracker_repo, feature_label):
                add_label(tracker_repo, issue["number"], LABEL_QUEUED)
                tasks.append(dict(
                    issue=issue, tracker_repo=tracker_repo,
                    default_target=default_target, pipeline_type="feature",
                ))
                logger.info("  Queued feature issue #%d: %s", issue["number"], issue["title"])

            for issue in get_open_issues(tracker_repo, bug_label):
                add_label(tracker_repo, issue["number"], LABEL_QUEUED)
                tasks.append(dict(
                    issue=issue, tracker_repo=tracker_repo,
                    default_target=default_target, pipeline_type="bug",
                ))
                logger.info("  Queued bug issue #%d: %s", issue["number"], issue["title"])

            for issue in get_open_issues(tracker_repo, doc_label):
                add_label(tracker_repo, issue["number"], LABEL_QUEUED)
                tasks.append(dict(
                    issue=issue, tracker_repo=tracker_repo,
                    default_target=default_target, pipeline_type="documentation",
                ))
                logger.info("  Queued documentation issue #%d: %s", issue["number"], issue["title"])

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to fetch issues from %s: %s", tracker_repo, exc)

    if not tasks:
        logger.info("Nothing to do.")
        return

    logger.info("Dispatching %d pipeline(s) (max_parallel=%d) …", len(tasks), max_parallel)

    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        futures = {
            pool.submit(
                run_pipeline,
                t["issue"], t["tracker_repo"], t["default_target"],
                t["pipeline_type"], model, num_engineers, log_dir, dry_run, logger,
            ): t
            for t in tasks
        }
        for future in as_completed(futures):
            t = futures[future]
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001
                logger.error("Unhandled error for issue #%d: %s", t["issue"]["number"], exc)


# ── Entry point ───────────────────────────────────────────────────────────────

def _setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d")
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", "%H:%M:%S")

    logger = logging.getLogger("watcher")
    logger.setLevel(logging.INFO)

    # Console
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # Daily rotating file
    fh = logging.FileHandler(log_dir / f"watcher-{ts}.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Software House — GitHub issue watcher")
    parser.add_argument("--config", default="repos.yaml", help="Path to repos.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run, make no changes")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        sys.exit(1)

    # Load log_dir early for the logger
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    log_dir = Path(config_path.parent / raw.get("settings", {}).get("log_dir", "logs/watcher"))
    logger = _setup_logging(log_dir)

    # Lock file — prevent overlapping cron runs
    if LOCK_FILE.exists():
        age = time.time() - LOCK_FILE.stat().st_mtime
        if age < 3600:
            logger.warning("Lock file exists (age %.0fs) — previous run still in progress. Exiting.", age)
            sys.exit(0)
        else:
            logger.warning("Stale lock file (age %.0fs) — removing and continuing.", age)
            LOCK_FILE.unlink()

    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    logger.info("═" * 60)
    logger.info("AI Software House Watcher — %s%s",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                " [DRY RUN]" if args.dry_run else "")
    logger.info("Config: %s", config_path)

    try:
        watch(config_path, dry_run=args.dry_run, logger=logger)
    finally:
        LOCK_FILE.unlink(missing_ok=True)
        logger.info("Done.")


if __name__ == "__main__":
    main()
