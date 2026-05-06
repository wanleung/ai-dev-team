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
import glob
import json
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
import requests

# ── Labels used to track pipeline state ─────────────────────────────────────
LABEL_QUEUED   = "agent-queued"
LABEL_RUNNING  = "agent-running"
LABEL_COMPLETE = "agent-complete"
LABEL_FAILED   = "agent-failed"
LABEL_WAITING  = "agent-waiting"

SKIP_LABELS = {LABEL_QUEUED, LABEL_RUNNING, LABEL_COMPLETE, LABEL_FAILED, LABEL_WAITING}

LABEL_COLOURS = {
    LABEL_QUEUED:   "e4e669",
    LABEL_RUNNING:  "0075ca",
    LABEL_COMPLETE: "0e8a16",
    LABEL_FAILED:   "d73a4a",
    LABEL_WAITING:  "fbca04",
}

# ── Lock file prevents overlapping cron runs ─────────────────────────────────
LOCK_FILE = Path(__file__).parent / ".watcher.lock"
_log = logging.getLogger("watcher")


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


def get_open_prs(repo: str, skip_drafts: bool = True) -> list[dict]:
    """Return open pull requests for the repo, optionally excluding drafts."""
    url = f"https://api.github.com/repos/{repo}/pulls"
    params = {"state": "open", "per_page": 50}
    resp = requests.get(url, headers=_gh_headers(), params=params, timeout=10)
    if not resp.ok:
        raise RuntimeError(f"GitHub API error {resp.status_code}: {resp.text[:200]}")
    prs = resp.json()
    if skip_drafts:
        prs = [pr for pr in prs if not pr.get("draft", False)]
    return prs


def get_pr_comments(repo: str, pr_number: int) -> list[dict]:
    """Return all conversation comments on a pull request."""
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    resp = requests.get(url, headers=_gh_headers(), params={"per_page": 100}, timeout=10)
    if not resp.ok:
        raise RuntimeError(f"GitHub API error {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def _pr_attempt_count(pr_labels: list[dict]) -> int:
    """Return the highest N from any 'ai-pr-fix-N' label, or 0 if none."""
    highest = 0
    for lbl in pr_labels:
        m = re.match(r"^ai-pr-fix-(\d+)$", lbl.get("name", ""))
        if m:
            highest = max(highest, int(m.group(1)))
    return highest


def _should_fix_pr(
    pr: dict,
    comments: list[dict],
    pr_fix_label: str,
    pr_failure_pattern: str,
    max_pr_retries: int,
) -> bool:
    """Return True if this PR should receive an automated fix run.

    Skips if: agent-running/agent-failed label present, or attempt count
    has reached max_pr_retries, or neither trigger condition is met.
    """
    labels = pr.get("labels", [])
    pr_label_names = {lbl.get("name", "") for lbl in labels}

    # Skip if already being processed, gave up, or already complete
    if pr_label_names & {"agent-running", "agent-failed", "agent-complete"}:
        return False

    # Skip if retry cap reached
    if _pr_attempt_count(labels) >= max_pr_retries:
        return False

    # Trigger 1: explicit fix label on the PR
    if pr_fix_label in pr_label_names:
        return True

    # Trigger 2: comment matching failure pattern
    pattern = re.compile(pr_failure_pattern, re.IGNORECASE)
    for comment in comments:
        if pattern.search(comment.get("body", "")):
            return True

    return False


_PRIOR_CONTEXT_MARKER = "\n\n---\n\n## 📜 Prior Work Context\n\n"

# Comment body prefixes generated by the pipeline itself that carry no new
# information for a re-run (progress tracker, error banners, chain notices).
_PIPELINE_NOISE_PREFIXES = (
    "## 🤖 Pipeline Progress",
    "## ❌ Agent Pipeline",
    "## 🔁 Pipeline Chaining",
    "## ⏸️",
)


def _collect_issue_prior_context(tracker_gh: "GitHubClient", issue_number: int) -> str:
    """Return a formatted context block of prior issue comments for agent injection.

    Fetches all comments on ``issue_number``, strips pipeline noise (progress
    tracker, error banners, chaining notices), and concatenates the remaining
    content under a ``## 📜 Prior Work Context`` header.  Returns ``""`` when
    there is nothing useful.

    A hard cap of 12 000 characters prevents blowing out agent token budgets.
    """
    _MAX_CHARS = 12_000
    try:
        comments = tracker_gh.get_issue_comments(issue_number)
    except Exception:
        return ""

    parts: list[str] = []
    total = 0
    for c in comments:
        body = (c.get("body") or "").strip()
        if not body:
            continue
        if any(body.startswith(p) for p in _PIPELINE_NOISE_PREFIXES):
            continue
        login = (c.get("user") or {}).get("login", "unknown")
        entry = f"<!-- @{login} -->\n{body}"
        if total + len(entry) > _MAX_CHARS:
            break
        parts.append(entry)
        total += len(entry)

    if not parts:
        return ""
    return _PRIOR_CONTEXT_MARKER + "\n\n---\n\n".join(parts)


def post_comment(repo: str, issue_number: int, body: str) -> None:
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
    requests.post(url, headers=_gh_headers(), json={"body": body}, timeout=10)


# ── Pipeline dispatch ─────────────────────────────────────────────────────────

def run_pipeline(
    issue: dict,
    tracker_repo: str,
    default_target: str | None,
    label: str,
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
        "  → Issue #%d: %r | label=%s | target=%s",
        issue_number, issue_title, label, target_repo,
    )

    if dry_run:
        logger.info("    [dry-run] Would run pipeline for label=%s", label)
        return True

    # Mark as running
    add_label(tracker_repo, issue_number, LABEL_RUNNING)
    remove_label(tracker_repo, issue_number, LABEL_QUEUED)

    # Set up per-issue log file
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    issue_log = log_dir / f"issue-{issue_number}-{ts}.log"

    try:
        result = _dispatch(
            label=label,
            tracker_repo=tracker_repo,
            target_repo=target_repo,
            issue_number=issue_number,
            model=model,
            num_engineers=num_engineers,
            log_file=issue_log,
            logger=logger,
        )

        # ── Pipeline chaining ─────────────────────────────────────────────────
        # Check if the result warrants automatic re-triggering (e.g. tests failed,
        # code review requested changes). The next_label can be set explicitly by
        # an agent during the run, or resolved from config-level chaining rules.
        pipeline_cfg = _load_pipeline_config()
        chaining_cfg = (pipeline_cfg.get("pipeline") or {}).get("chaining") or {}
        next_label = _resolve_next_label(result, chaining_cfg)

        if next_label:
            # Chain: remove agent-complete, apply the follow-up trigger label so
            # the watcher picks up the issue again on the next cycle.
            remove_label(tracker_repo, issue_number, LABEL_RUNNING)
            # Remove any previous terminal labels so SKIP_LABELS won't block it
            for stale in (LABEL_COMPLETE, LABEL_FAILED):
                try:
                    remove_label(tracker_repo, issue_number, stale)
                except Exception:
                    pass
            ensure_label(tracker_repo, next_label, "c5def5")
            add_label(tracker_repo, issue_number, next_label)
            post_comment(
                tracker_repo,
                issue_number,
                f"## 🔁 Pipeline Chaining → `{next_label}`\n\n"
                f"The pipeline completed but follow-up work was detected "
                f"(verdict: `{result.verdict or 'n/a'}`, "
                f"tests_passed: `{result.tests_passed}`, "
                f"deploy_tests_passed: `{result.deploy_tests_passed}`).\n\n"
                f"Automatically re-queued with label `{next_label}`. "
                f"The watcher will pick this up on the next cycle.\n\n"
                f"To stop chaining, remove the `{next_label}` label.",
            )
            logger.info(
                "    🔁 Issue #%d chained → label=%s (verdict=%s, tests_passed=%s)",
                issue_number, next_label, result.verdict, result.tests_passed,
            )
        else:
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


def load_watcher_config(config_path: Path) -> dict:
    """Load and merge watcher config from repos.yaml + repos-enabled/*.yaml.

    Returns a config dict with a unified ``watchers`` list.  Per-watcher
    ``settings:`` blocks are stripped from the watcher entry and stored as
    ``_settings`` (for both legacy and repos-enabled entries) so callers can
    apply per-watcher overrides.
    """
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    legacy_watchers: list[dict] = list(config.get("watchers") or [])
    # Apply settings→_settings transformation for legacy watchers too
    for w in legacy_watchers:
        per_settings = w.pop("settings", None)
        if per_settings is not None:
            w["_settings"] = per_settings
    seen: dict[str, int] = {}  # tracker_repo → index in merged list

    for i, w in enumerate(legacy_watchers):
        repo = w.get("tracker_repo", "")
        if repo:
            seen[repo] = i

    repos_enabled = config_path.parent / "repos-enabled"
    if repos_enabled.is_dir():
        for entry in sorted(repos_enabled.iterdir()):
            if entry.suffix != ".yaml":
                continue
            if not entry.exists():  # broken symlink
                _log.warning("Broken symlink in repos-enabled/: %s — skipping", entry.name)
                continue
            with open(entry, encoding="utf-8") as f:
                watcher_dict = yaml.safe_load(f) or {}
            per_settings = watcher_dict.pop("settings", None)
            if per_settings is not None:
                watcher_dict["_settings"] = per_settings
            repo = watcher_dict.get("tracker_repo", "")
            if not repo:
                _log.warning("repos-enabled/%s has no tracker_repo — skipping", entry.name)
                continue
            if repo in seen:
                _log.warning(
                    "Duplicate tracker_repo '%s' in repos-enabled/%s — enabled-dir entry wins",
                    repo, entry.name,
                )
                legacy_watchers[seen[repo]] = watcher_dict
            else:
                seen[repo] = len(legacy_watchers)
                legacy_watchers.append(watcher_dict)

    config["watchers"] = legacy_watchers
    return config


def cmd_repo_enable(base_dir: Path, name: str) -> None:
    """Enable a watcher by creating a symlink in repos-enabled/."""
    if "/" in name or "\\" in name or name.startswith("."):
        print(f"Error: invalid repo name '{name}'", file=sys.stderr)
        sys.exit(1)
    avail = base_dir / "repos-available" / f"{name}.yaml"
    if not avail.exists():
        available = sorted(p.stem for p in (base_dir / "repos-available").glob("*.yaml")) \
            if (base_dir / "repos-available").is_dir() else []
        print(f"Error: repos-available/{name}.yaml not found.", file=sys.stderr)
        if available:
            print(f"Available: {', '.join(available)}", file=sys.stderr)
        sys.exit(1)

    enabled_dir = base_dir / "repos-enabled"
    enabled_dir.mkdir(exist_ok=True)
    link = enabled_dir / f"{name}.yaml"

    if link.exists() or link.is_symlink():
        print(f"Error: '{name}' is already enabled. Run 'repo disable {name}' first.", file=sys.stderr)
        sys.exit(1)

    os.symlink(avail.resolve(), link)
    print(f"Enabled: {name}")


def cmd_repo_disable(base_dir: Path, name: str) -> None:
    """Disable a watcher by removing its symlink from repos-enabled/."""
    if "/" in name or "\\" in name or name.startswith("."):
        print(f"Error: invalid repo name '{name}'", file=sys.stderr)
        sys.exit(1)
    link = base_dir / "repos-enabled" / f"{name}.yaml"
    if not link.exists() and not link.is_symlink():
        print(f"Error: '{name}' is not currently enabled.", file=sys.stderr)
        sys.exit(1)

    link.unlink()
    print(f"Disabled: {name}")


def cmd_repo_list(base_dir: Path) -> None:
    """List all repos in repos-available/ with enabled/disabled status."""
    avail_dir = base_dir / "repos-available"
    if not avail_dir.is_dir():
        print("No repos-available/ directory found.", file=sys.stderr)
        return

    files = sorted(avail_dir.glob("*.yaml"))
    if not files:
        print("No repos found in repos-available/", file=sys.stderr)
        return

    enabled_dir = base_dir / "repos-enabled"
    for f in files:
        link = enabled_dir / f.name
        if link.is_symlink() and not link.resolve().exists():
            status = "[broken]  "
        elif link.exists():
            status = "[enabled] "
        else:
            status = "[disabled]"
        print(f"  {status}  {f.stem}")


def install_llm_pool_from_config(pipeline_cfg: dict) -> None:
    """Install the global LLMPoolManager from ``pipeline_cfg['llm']['pools']``.

    Should be called once at watcher / CLI startup, before any agent runs.
    Missing sections are tolerated — defaults from llm_pool apply.
    """
    from llm_pool import LLMPoolManager, set_pool
    pools = (pipeline_cfg.get("llm") or {}).get("pools") or {}
    set_pool(LLMPoolManager(pools))


def _dispatch(
    label: str,
    tracker_repo: str,
    target_repo: str,
    issue_number: int,
    model: str,
    num_engineers: int,
    log_file: Path,
    logger: logging.Logger,
) -> "PipelineResult":
    """Run the unified Orchestrator with the pipeline file selected by ``label``.

    Returns the PipelineResult so the caller can inspect verdict, test results,
    and ``next_label`` for pipeline chaining.
    """
    token = os.environ.get("GITHUB_TOKEN")

    pipeline_cfg = _load_pipeline_config()
    llm_cfg = pipeline_cfg.get("llm", {})
    pipe_cfg = pipeline_cfg.get("pipeline", {})
    cfg_model = llm_cfg.get("model", "") or ""
    effective_model = cfg_model if cfg_model and cfg_model != "gpt-4.1" else model
    model_overrides = llm_cfg.get("overrides", {})
    ollama_url = llm_cfg.get("ollama_url", "http://localhost:11434")
    nvidia_nim_api_key = llm_cfg.get("nvidia_nim_api_key") or os.environ.get("NVIDIA_API_KEY")
    nvidia_nim_base_url = llm_cfg.get("nvidia_nim_base_url") or os.environ.get("NVIDIA_NIM_BASE_URL")
    retry_delay = pipe_cfg.get("retry_delay", 15)
    max_api_retries = pipe_cfg.get("max_api_retries", 5)
    inter_call_delay = pipe_cfg.get("inter_call_delay", 0)

    with open(log_file, "w", encoding="utf-8") as fh:
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = fh
        try:
            from orchestrator import Orchestrator
            from github_client import GitHubClient

            tracker_gh = GitHubClient(tracker_repo, token)
            issue = tracker_gh.get_issue(issue_number)
            issue_body = issue.get("body") or ""
            requirement = (issue_body or issue.get("title") or "").strip()

            # Collect prior issue comments and append to trigger_issue_body so
            # agents receive the prior PRD, architecture, reviews, and human
            # feedback as context when this issue is re-processed.
            prior_ctx = _collect_issue_prior_context(tracker_gh, issue_number)
            trigger_issue_body = issue_body + prior_ctx if prior_ctx else issue_body

            orch = Orchestrator(
                model=effective_model,
                model_overrides=model_overrides,
                github_token=token,
                github_repo=tracker_repo,
                target_repo=target_repo,
                num_engineers=num_engineers,
                use_github=True,
                ollama_url=ollama_url,
                nvidia_nim_api_key=nvidia_nim_api_key,
                nvidia_nim_base_url=nvidia_nim_base_url,
                retry_delay=retry_delay,
                max_api_retries=max_api_retries,
                inter_call_delay=inter_call_delay,
            )

            # Resolve pipeline stages for this label (project override → builtin)
            stages = orch.load_pipeline_for_label(label)
            if stages is not None:
                orch._pipeline_yaml_stages = stages
                logger.info("    Using pipelines/%s.yaml (%d stages)", label, len(stages))
            else:
                logger.info("    Using built-in default pipeline (no pipelines/%s.yaml)", label)

            result = orch.run(requirement, trigger_issue_body=trigger_issue_body, issue_number=issue_number)
            return result
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr


def _resolve_next_label(result: "PipelineResult", chaining_cfg: dict) -> Optional[str]:
    """Determine whether the pipeline result should chain to a follow-up label.

    Priority order:
    1. ``result.next_label`` — explicitly set by an agent/stage during the run.
    2. Config rules in ``pipeline.chaining`` — evaluated against result flags.

    Returns the label string to apply, or None if no chaining needed.
    """
    # 1. Explicit label set by an agent during the pipeline
    if result.next_label:
        return result.next_label

    if not chaining_cfg:
        return None

    # 2. Config-driven rules
    if result.tests_passed is False or result.deploy_tests_passed is False:
        label = chaining_cfg.get("on_test_failure")
        if label:
            return label

    if result.verdict and "CHANGES" in result.verdict.upper():
        label = chaining_cfg.get("on_review_issues")
        if label:
            return label

    return None


def _run_pr_revision(
    pr: dict,
    tracker_repo: str,
    target_repo: str,
    model: str,
    num_engineers: int,
    log_dir: Path,
    logger: logging.Logger,
    pr_fix_label: str = "ai-fix",
) -> None:
    """Instantiate an Orchestrator and run run_revision() for a failing PR.

    Manages agent-running / agent-complete / agent-failed labels on the PR
    in target_repo (where the PR actually lives).
    The attempt count label (ai-pr-fix-N) is added before calling run_revision().
    """
    pr_number = pr["number"]
    attempt = _pr_attempt_count(pr.get("labels", [])) + 1
    attempt_label = f"ai-pr-fix-{attempt}"

    token = os.environ.get("GITHUB_TOKEN", "")
    pipeline_cfg = _load_pipeline_config()
    llm_cfg = pipeline_cfg.get("llm", {})
    pipe_cfg = pipeline_cfg.get("pipeline", {})
    cfg_model = llm_cfg.get("model", "") or ""
    effective_model = cfg_model if cfg_model and cfg_model != "gpt-4.1" else model
    model_overrides = llm_cfg.get("overrides", {})
    ollama_url = llm_cfg.get("ollama_url", "http://localhost:11434")
    nvidia_nim_api_key = llm_cfg.get("nvidia_nim_api_key") or os.environ.get("NVIDIA_API_KEY")
    nvidia_nim_base_url = llm_cfg.get("nvidia_nim_base_url") or os.environ.get("NVIDIA_NIM_BASE_URL")
    retry_delay = pipe_cfg.get("retry_delay", 15)
    max_api_retries = pipe_cfg.get("max_api_retries", 5)
    inter_call_delay = pipe_cfg.get("inter_call_delay", 0)

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"pr-revision-{pr_number}-attempt{attempt}.log"

    logger.info("  🔄 PR #%d: starting fix attempt %d", pr_number, attempt)

    # Mark as running and record attempt number (labels go on the PR in target_repo)
    ensure_label(target_repo, LABEL_RUNNING, LABEL_COLOURS[LABEL_RUNNING])
    ensure_label(target_repo, attempt_label, "c5def5")
    add_label(target_repo, pr_number, LABEL_RUNNING)
    add_label(target_repo, pr_number, attempt_label)

    try:
        with open(log_file, "w", encoding="utf-8") as fh:
            old_stdout, old_stderr = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = fh
            try:
                from orchestrator import Orchestrator

                orch = Orchestrator(
                    model=effective_model,
                    model_overrides=model_overrides,
                    github_token=token,
                    github_repo=tracker_repo,
                    target_repo=target_repo,
                    num_engineers=num_engineers,
                    use_github=True,
                    ollama_url=ollama_url,
                    nvidia_nim_api_key=nvidia_nim_api_key,
                    nvidia_nim_base_url=nvidia_nim_base_url,
                    retry_delay=retry_delay,
                    max_api_retries=max_api_retries,
                    inter_call_delay=inter_call_delay,
                )

                result = orch.run_revision(pr_number)
                status = result.get("status", "ok")

                if status in ("max_revisions_reached", "error"):
                    add_label(target_repo, pr_number, LABEL_FAILED)
                    remove_label(target_repo, pr_number, LABEL_RUNNING)
                    post_comment(
                        target_repo, pr_number,
                        f"❌ PR fix attempt {attempt} could not complete "
                        f"(status: `{status}`). Log: `{log_file}`\n\n"
                        "Remove `agent-failed` to retry manually.",
                    )
                    logger.info("  ❌ PR #%d fix attempt %d: %s", pr_number, attempt, status)
                else:
                    add_label(target_repo, pr_number, LABEL_COMPLETE)
                    remove_label(target_repo, pr_number, LABEL_RUNNING)
                    # Remove trigger label so next cycle doesn't re-trigger
                    remove_label(target_repo, pr_number, pr_fix_label)
                    logger.info("  ✅ PR #%d fix attempt %d complete", pr_number, attempt)

            except Exception as exc:  # noqa: BLE001
                logger.error("  ❌ PR #%d fix attempt %d unhandled error: %s", pr_number, attempt, exc)
                add_label(target_repo, pr_number, LABEL_FAILED)
                remove_label(target_repo, pr_number, LABEL_RUNNING)
                post_comment(
                    target_repo, pr_number,
                    f"❌ PR fix attempt {attempt} failed with error: `{exc}`\n"
                    f"Log: `{log_file}`\n\nRemove `agent-failed` to retry.",
                )
            finally:
                sys.stdout, sys.stderr = old_stdout, old_stderr
    except OSError as exc:  # noqa: BLE001
        logger.error("  ❌ PR #%d: could not open log file %s: %s", pr_number, log_file, exc)
        add_label(target_repo, pr_number, LABEL_FAILED)
        remove_label(target_repo, pr_number, LABEL_RUNNING)
        post_comment(
            target_repo, pr_number,
            f"❌ PR fix attempt {attempt} failed: could not open log file.\n"
            f"`{exc}`\n\nRemove `agent-failed` to retry.",
        )


def _watch_prs(
    watchers: list[dict],
    global_settings: dict,
    log_dir: Path,
    dry_run: bool,
    logger: logging.Logger,
) -> None:
    """Scan open PRs across all enabled watchers and dispatch fix runs as needed.

    Only runs for watchers with watch_prs: true in their settings.
    Per-watcher settings override global_settings (same _settings merge as watch()).
    """
    for w in watchers:
        if not w.get("enabled", True):
            continue
        _w_settings = {**global_settings, **w.get("_settings", {})}
        if not _w_settings.get("watch_prs", False):
            continue

        tracker_repo = w["tracker_repo"]
        target_repo = w.get("default_target") or tracker_repo
        model = _w_settings.get("model", "gpt-4.1")
        num_engineers = _w_settings.get("num_engineers", 2)
        pr_fix_label = _w_settings.get("pr_fix_label", "ai-fix")
        pr_failure_pattern = _w_settings.get("pr_failure_pattern", r"❌|FAILED|tests? failed|test suite failed")
        try:
            max_pr_retries = int(_w_settings.get("max_pr_retries", 3))
        except (ValueError, TypeError):
            logger.warning("Invalid max_pr_retries for %s; defaulting to 3", tracker_repo)
            max_pr_retries = 3
        skip_drafts = not _w_settings.get("watch_draft_prs", False)

        logger.info("Checking PRs in %s (tracker: %s) …", target_repo, tracker_repo)
        try:
            prs = get_open_prs(target_repo, skip_drafts=skip_drafts)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to fetch PRs from %s: %s", target_repo, exc)
            continue

        for pr in prs:
            pr_number = pr["number"]
            try:
                comments = get_pr_comments(target_repo, pr_number)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not fetch comments for PR #%d: %s", pr_number, exc)
                comments = []

            if not _should_fix_pr(pr, comments, pr_fix_label, pr_failure_pattern, max_pr_retries):
                continue

            logger.info("  🔧 PR #%d needs fixing (%s)", pr_number, pr.get("title", ""))

            if dry_run:
                logger.info("    [dry-run] Would run PR fix for #%d", pr_number)
                continue

            _run_pr_revision(
                pr, tracker_repo, target_repo, model, num_engineers, log_dir, logger,
                pr_fix_label=pr_fix_label,
            )


def _parse_target_repo(body: str) -> str | None:
    """Extract '**Target repo:** owner/repo' from issue body."""
    m = re.search(r"\*\*Target repo:\*\*\s*([\w.\-]+/[\w.\-]+)", body)
    if m:
        return m.group(1)
    m = re.search(r"Target repo:\s*([\w.\-]+/[\w.\-]+)", body)
    return m.group(1) if m else None


# ── Q&A / Clarification helpers ──────────────────────────────────────────────

def extract_answers_from_comments(
    comments: list[dict],
    question_comment_id: int,
    bot_login: str,
) -> list[str]:
    """Return text of comments posted AFTER the question comment by non-bot users.

    These are the human answers to the Q&A questions.
    """
    answers = []
    found_question = False
    for c in comments:
        if c["id"] == question_comment_id:
            found_question = True
            continue
        if found_question and c.get("user", {}).get("login") != bot_login:
            answers.append(c["body"])
    return answers


def _find_checkpoint_for_issue(workspace_dir: str, issue_number: int) -> Optional[str]:
    """Scan workspace_dir for a checkpoint JSON containing the given issue_number."""
    pattern = os.path.join(workspace_dir, "**", "checkpoint_*.json")
    for path in glob.glob(pattern, recursive=True):
        try:
            with open(path) as f:
                data = json.load(f)
            if data.get("issue_number") == issue_number:
                return path
        except Exception:
            continue
    return None


def _utcnow_iso() -> str:
    """Return current UTC time in ISO 8601 format."""
    import datetime as _dt
    return _dt.datetime.utcnow().isoformat() + "Z"


def _trigger_resume(issue_number: int, issue_title: str, requirement: str, workspace_dir: str) -> None:
    """Write a resume trigger file so the main watch() loop picks up the issue next cycle."""
    trigger_dir = os.path.join(workspace_dir, "resume_queue")
    os.makedirs(trigger_dir, exist_ok=True)
    trigger_path = os.path.join(trigger_dir, f"resume_{issue_number}.json")
    with open(trigger_path, "w") as f:
        json.dump({
            "issue_number": issue_number,
            "issue_title": issue_title,
            "requirement": requirement,
        }, f, indent=2)
    logging.getLogger("watcher").info(f"[Watcher] Resume trigger written: {trigger_path}")


def check_waiting_issues(github_token: str, tracker_repos: list[str], workspace_dir: str, bot_login: str) -> None:
    """Check all issues labelled agent-waiting for human replies.

    For each waiting issue that has a checkpoint with pending_clarification:
    1. Fetch comments after the question comment
    2. If human has replied, inject answers into checkpoint and re-label
    3. Re-dispatch pipeline (by removing agent-waiting and calling dispatch logic)
    """
    from orchestrator import PipelineResult

    logger = logging.getLogger("watcher")

    for tracker_repo in tracker_repos:
        try:
            waiting_issues = _get_issues_by_label(tracker_repo, LABEL_WAITING, github_token)
        except Exception as exc:
            logger.warning(f"[Watcher] Could not list agent-waiting issues for {tracker_repo}: {exc}")
            continue

        for issue in waiting_issues:
            issue_number = issue["number"]
            issue_title = issue.get("title", "")

            # Find checkpoint for this issue
            checkpoint_path = _find_checkpoint_for_issue(workspace_dir, issue_number)
            if not checkpoint_path:
                logger.info(f"[Watcher] Issue #{issue_number}: no checkpoint found, skipping")
                continue

            try:
                with open(checkpoint_path) as f:
                    data = json.load(f)
                result = PipelineResult.from_dict(data)
            except Exception as exc:
                logger.warning(f"[Watcher] Issue #{issue_number}: could not load checkpoint: {exc}")
                continue

            if not result.pending_clarification:
                logger.info(f"[Watcher] Issue #{issue_number}: no pending_clarification in checkpoint")
                continue

            pending = result.pending_clarification
            question_comment_id = pending.get("question_comment_id")
            if not question_comment_id:
                logger.info(f"[Watcher] Issue #{issue_number}: no question_comment_id, skipping")
                continue

            # Fetch comments and check for answers
            try:
                comments = _get_issue_comments(tracker_repo, issue_number, github_token)
            except Exception as exc:
                logger.warning(f"[Watcher] Issue #{issue_number}: could not fetch comments: {exc}")
                continue

            answers = extract_answers_from_comments(comments, question_comment_id, bot_login)
            if not answers:
                logger.info(f"[Watcher] Issue #{issue_number}: no human reply yet")
                continue

            logger.info(f"[Watcher] Issue #{issue_number}: human replied ({len(answers)} answer(s)), resuming pipeline")

            # Inject answers into clarification_history
            stage = pending.get("stage", "unknown")
            qa_round = pending.get("qa_rounds", 1)
            result.clarification_history.append({
                "stage": stage,
                "round": qa_round,
                "questions": pending.get("questions", []),
                "answers": answers,
                "answered_at": _utcnow_iso(),
            })
            result.pending_clarification = None

            # Save updated checkpoint
            with open(checkpoint_path, "w") as f:
                json.dump(result.to_dict(), f, indent=2)

            # Switch labels: remove agent-waiting, add agent-running
            try:
                remove_label(tracker_repo, issue_number, LABEL_WAITING)
                add_label(tracker_repo, issue_number, LABEL_RUNNING)
            except Exception as exc:
                logger.warning(f"[Watcher] Issue #{issue_number}: could not update labels: {exc}")

            # Trigger re-dispatch by appending to a simple queue file (watcher picks it up next cycle)
            _trigger_resume(issue_number, issue_title, result.requirement, workspace_dir)


def _get_issues_by_label(repo: str, label: str, token: str) -> list[dict]:
    """Return all open issues with the given label."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"https://api.github.com/repos/{repo}/issues"
    params = {"labels": label, "state": "open"}
    resp = requests.get(url, headers=headers, params=params, timeout=10)
    if not resp.ok:
        raise RuntimeError(f"GitHub API error {resp.status_code}: {resp.text[:200]}")
    return [issue for issue in resp.json() if "pull_request" not in issue]


def _get_issue_comments(repo: str, issue_number: int, token: str) -> list[dict]:
    """Return all comments for an issue."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
    resp = requests.get(url, headers=headers, timeout=10)
    if not resp.ok:
        raise RuntimeError(f"GitHub API error {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def _process_resume_queue(workspace_dir: str, tracker_repos: list[str], default_targets: dict[str, str], model: str, num_engineers: int, log_dir: Path, dry_run: bool, logger: logging.Logger) -> list[dict]:
    """Process any resume triggers left by check_waiting_issues().
    
    Returns a list of task dicts to be dispatched.
    """
    trigger_dir = os.path.join(workspace_dir, "resume_queue")
    if not os.path.isdir(trigger_dir):
        return []

    tasks = []
    for trigger_path in glob.glob(os.path.join(trigger_dir, "resume_*.json")):
        try:
            with open(trigger_path) as f:
                trigger = json.load(f)
            issue_number = trigger["issue_number"]
            requirement = trigger.get("requirement", trigger.get("issue_title", ""))
            logger.info(f"[Watcher] Resuming pipeline for issue #{issue_number}")

            task_created = False
            for tracker_repo in tracker_repos:
                try:
                    token = os.environ.get("GITHUB_TOKEN", "")
                    headers = {
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    }
                    url = f"https://api.github.com/repos/{tracker_repo}/issues/{issue_number}"
                    resp = requests.get(url, headers=headers, timeout=10)
                    if resp.ok:
                        issue = resp.json()
                        tasks.append(dict(
                            issue=issue,
                            tracker_repo=tracker_repo,
                            default_target=default_targets.get(tracker_repo),
                            label="ai-feature",
                            model=model,
                            num_engineers=num_engineers,
                        ))
                        logger.info(f"  Queued resumed issue #{issue_number}: {issue.get('title', '')}")
                        task_created = True
                        break
                except Exception as exc:
                    logger.debug(f"Could not fetch issue #{issue_number} from {tracker_repo}: {exc}")
                    continue

            # Only delete trigger after task successfully created; keep for retry otherwise
            if task_created:
                os.remove(trigger_path)
            else:
                logger.warning(
                    f"[Watcher] Could not fetch issue #{issue_number} from any repo — "
                    f"keeping trigger for retry"
                )
        except Exception as exc:
            logger.warning(f"[Watcher] Could not process resume trigger {trigger_path}: {exc}")
    
    return tasks


# ── Watcher loop ──────────────────────────────────────────────────────────────

def watch(config_path: Path, dry_run: bool, logger: logging.Logger) -> None:
    config = load_watcher_config(config_path)

    global_settings = config.get("settings", {})
    max_parallel  = global_settings.get("max_parallel", 3)
    log_dir       = Path(config_path.parent / global_settings.get("log_dir", "logs/watcher"))

    watchers = config.get("watchers", [])
    logger.info("Loaded %d watcher(s) from %s", len(watchers), config_path)

    # Load pipeline config to get workspace_dir, bot_login, and PR watcher defaults
    pipeline_cfg = _load_pipeline_config()
    pipeline_section = pipeline_cfg.get("pipeline", {})
    workspace_dir = pipeline_section.get("workspace_dir", "./workspace")
    github_cfg = pipeline_cfg.get("github", {})
    bot_login = github_cfg.get("bot_login", "github-actions[bot]")
    github_token = os.environ.get("GITHUB_TOKEN", "")

    # Merge pipeline PR-watching defaults as lowest-priority base for global_settings
    _PR_WATCH_KEYS = ("watch_prs", "pr_fix_label", "pr_failure_pattern",
                      "max_pr_retries", "watch_draft_prs")
    pr_defaults = {k: pipeline_section[k] for k in _PR_WATCH_KEYS if k in pipeline_section}
    global_settings = {**pr_defaults, **global_settings}

    # Build list of tracker repos for checking waiting issues
    tracker_repos = [w["tracker_repo"] for w in watchers if w.get("enabled", True)]
    default_targets = {w["tracker_repo"]: w.get("default_target") for w in watchers if w.get("enabled", True)}

    # Check issues waiting for human clarification
    if not dry_run:
        check_waiting_issues(github_token, tracker_repos, workspace_dir, bot_login)

    # Watch PRs for failures and dispatch fix runs
    _watch_prs(watchers, global_settings, log_dir, dry_run, logger)

    # Collect all issues across all watchers
    tasks: list[dict] = []
    
    # Process any resume triggers (issues answered by human)
    if not dry_run:
        # resume queue tasks always run with global model/num_engineers; per-watcher
        # overrides don't apply to resumed tasks (trigger files don't record the watcher).
        global_model = global_settings.get("model", "gpt-4.1")
        global_num_engineers = global_settings.get("num_engineers", 2)
        resumed_tasks = _process_resume_queue(workspace_dir, tracker_repos, default_targets, global_model, global_num_engineers, log_dir, dry_run, logger)
        tasks.extend(resumed_tasks)
    
    for w in watchers:
        if not w.get("enabled", True):
            continue
        tracker_repo    = w["tracker_repo"]
        default_target  = w.get("default_target") or None

        # Apply per-watcher settings overrides on top of global settings
        _w_settings   = {**global_settings, **w.get("_settings", {})}
        model         = _w_settings.get("model", "gpt-4.1")
        num_engineers = _w_settings.get("num_engineers", 2)

        # Read label → pipeline mapping for this watcher entry. New format:
        #   labels:
        #     ai-feature: {}
        #     my-bug: {pipeline: ai-fix}
        # Backward-compat with old feature_label / bug_label / doc_label keys.
        labels_cfg = w.get("labels")
        if labels_cfg is None:
            labels_cfg = {}

            def _add_legacy(field: str, default: str | None, pipeline: str) -> None:
                val = w.get(field, default)
                if not val:
                    return
                names = val if isinstance(val, list) else [val]
                for name in names:
                    if name:
                        labels_cfg[name] = {"pipeline": pipeline}

            _add_legacy("feature_label", "feature-request", "ai-feature")
            _add_legacy("bug_label", "bug", "ai-fix")
            _add_legacy("doc_label", "documentation", "ai-docs")

        # Ensure state labels exist
        for name, colour in LABEL_COLOURS.items():
            ensure_label(tracker_repo, name, colour)

        logger.info("Checking %s …", tracker_repo)
        try:
            for label_name, label_cfg in labels_cfg.items():
                if isinstance(label_cfg, str):
                    pipeline_name = label_cfg
                else:
                    pipeline_name = (label_cfg or {}).get("pipeline", label_name)
                for issue in get_open_issues(tracker_repo, label_name):
                    add_label(tracker_repo, issue["number"], LABEL_QUEUED)
                    tasks.append(dict(
                        issue=issue,
                        tracker_repo=tracker_repo,
                        default_target=default_target,
                        label=pipeline_name,
                        parallel_issues=w.get("parallel_issues", 1),
                        model=model,
                        num_engineers=num_engineers,
                    ))
                    logger.info("  Queued %s issue #%d: %s", pipeline_name, issue["number"], issue["title"])
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to fetch issues from %s: %s", tracker_repo, exc)

    if not tasks:
        logger.info("Nothing to do.")
        return

    # Group tasks by tracker_repo so each gets its own thread pool
    by_repo: dict[str, list[dict]] = {}
    for t in tasks:
        by_repo.setdefault(t["tracker_repo"], []).append(t)

    logger.info("Dispatching %d pipeline(s) across %d repo(s)…", len(tasks), len(by_repo))

    # One executor per repo; each repo's parallel_issues bounds its concurrency.
    # A global semaphore enforces the overall max_parallel cap so the total
    # number of simultaneous pipelines never exceeds settings.max_parallel
    # regardless of how many repos are being watched.
    global_sem = threading.Semaphore(max(1, max_parallel))

    def _run_with_global_cap(*args, **kwargs):
        global_sem.acquire()
        try:
            run_pipeline(*args, **kwargs)
        finally:
            global_sem.release()

    repo_executors: list[ThreadPoolExecutor] = []
    futures_to_task: dict = {}
    try:
        for repo_name, repo_tasks in by_repo.items():
            par = max(1, repo_tasks[0].get("parallel_issues", 1))
            ex = ThreadPoolExecutor(max_workers=par, thread_name_prefix=f"watcher-{repo_name}")
            repo_executors.append(ex)
            for t in repo_tasks:
                fut = ex.submit(
                    _run_with_global_cap,
                    t["issue"], t["tracker_repo"], t["default_target"],
                    t["label"], t.get("model", "gpt-4.1"), t.get("num_engineers", 2), log_dir, dry_run, logger,
                )
                futures_to_task[fut] = t

        for fut in as_completed(futures_to_task):
            t = futures_to_task[fut]
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.error("Unhandled error for issue #%d: %s", t["issue"]["number"], exc)
    finally:
        for ex in repo_executors:
            ex.shutdown(wait=True)


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


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Software House — GitHub issue watcher")
    parser.add_argument("--config", default="repos.yaml", help="Path to repos.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run, make no changes")
    parser.add_argument("--once", action="store_true",
                        help="Process a single issue and exit (used by GitHub Actions)")
    parser.add_argument("--repo", help="(--once mode) tracker repo, e.g. owner/repo")
    parser.add_argument("--issue", type=int, help="(--once mode) issue number")
    parser.add_argument("--label", help="(--once mode) GitHub label that triggered the pipeline")

    sub = parser.add_subparsers(dest="command")
    repo_p = sub.add_parser("repo", help="Manage repos-available / repos-enabled")
    repo_sub = repo_p.add_subparsers(dest="repo_command")

    en = repo_sub.add_parser("enable", help="Enable a repo watcher")
    en.add_argument("name", help="Repo name stem (e.g. mcp-tfl)")

    dis = repo_sub.add_parser("disable", help="Disable a repo watcher")
    dis.add_argument("name", help="Repo name stem (e.g. mcp-tfl)")

    repo_sub.add_parser("list", help="List all available repos with enabled/disabled status")

    return parser


def run_once(repo: str, issue: int, label: str, logger: logging.Logger) -> int:
    """Process a single issue and exit. Used by GitHub Actions workflows.

    Returns exit code (0 = success, 1 = failure).
    """
    install_llm_pool_from_config(_load_pipeline_config())
    log_dir = Path(__file__).parent / "logs" / "watcher"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    issue_log = log_dir / f"issue-{issue}-{ts}.log"
    try:
        _dispatch(
            label=label,
            tracker_repo=repo,
            target_repo=repo,
            issue_number=issue,
            model="gpt-4.1",
            num_engineers=2,
            log_file=issue_log,
            logger=logger,
        )
        logger.info("✅ Issue #%d complete", issue)
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.error("❌ Issue #%d failed: %s", issue, exc)
        return 1


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    # ── repo sub-commands ────────────────────────────────────────────────
    if getattr(args, "command", None) == "repo":
        config_path = Path(args.config).resolve()
        base_dir = config_path.parent
        repo_command = getattr(args, "repo_command", None)
        if repo_command == "enable":
            cmd_repo_enable(base_dir, args.name)
        elif repo_command == "disable":
            cmd_repo_disable(base_dir, args.name)
        elif repo_command == "list":
            cmd_repo_list(base_dir)
        else:
            print("Usage: watcher.py repo enable|disable|list [name]", file=sys.stderr)
            sys.exit(2)
        return

    # --once mode short-circuits everything (no lock file, no polling)
    if args.once:
        if not (args.repo and args.issue is not None and args.label):
            print("--once requires --repo, --issue, and --label", file=sys.stderr)
            sys.exit(2)
        log_dir = Path(__file__).parent / "logs" / "watcher"
        logger = _setup_logging(log_dir)
        sys.exit(run_once(args.repo, args.issue, args.label, logger))

    # ── Polling mode (existing behaviour) ───────────────────────────────
    config_path = Path(args.config).resolve()
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        sys.exit(1)

    raw = load_watcher_config(config_path)
    log_dir = Path(config_path.parent / raw.get("settings", {}).get("log_dir", "logs/watcher"))
    logger = _setup_logging(log_dir)

    if LOCK_FILE.exists():
        age = time.time() - LOCK_FILE.stat().st_mtime
        if age < 3600:
            logger.warning("Lock file exists (age %.0fs) — previous run still in progress. Exiting.", age)
            sys.exit(0)
        else:
            logger.warning("Stale lock file (age %.0fs) — removing and continuing.", age)
            LOCK_FILE.unlink()

    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    install_llm_pool_from_config(_load_pipeline_config())
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
