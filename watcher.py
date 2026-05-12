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
import contextvars
import fcntl
import glob
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from logging_setup import configure_logging, bind_run_id, clear_run_id
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)
from utils import sanitise as _sanitise
from config_schema import load_repo_entry, AppConfig as _AppConfig
from pydantic import ValidationError as _ValidationError
from watcher_types import GitHubComment, GitHubIssue, GitHubPR, WatcherTask

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

# ── Per-issue dedup lock ──────────────────────────────────────────────────────
# Prevents the same GitHub issue from being processed twice concurrently within
# this process (e.g. duplicate API results, overlapping watch() cycles).
# Keyed by (tracker_repo, issue_number) so that issue #42 in repo A does not
# block issue #42 in a different repo B.
_ACTIVE_ISSUES: set[tuple[str, int]] = set()
_ACTIVE_ISSUES_LOCK = threading.Lock()


def _run_with_issue_lock(fn, issue: dict, repo: str, *args, **kwargs) -> None:
    """Guard fn against concurrent calls for the same (repo, issue_number) pair.

    Checks whether ``(repo, issue["number"])`` is already in the active-issues
    sentinel set.  If it is, logs a debug message and returns immediately
    without calling fn.  Otherwise, adds the key to the set, calls
    ``fn(issue, repo, *args, **kwargs)``, and removes the key in a finally
    block — ensuring the slot is always freed even if fn raises.

    Args:
        fn: Callable to invoke when the issue is not already in-flight.
        issue: GitHub issue dict (must contain a ``"number"`` key).
        repo: The tracker repository slug (``owner/name``).  Combined with
            ``issue["number"]`` to form the dedup key so that the same issue
            number in two different repos never suppresses each other.
        *args: Extra positional arguments forwarded to fn after issue and repo.
        **kwargs: Extra keyword arguments forwarded to fn.
    """
    issue_number: int = issue["number"]
    key: tuple[str, int] = (repo, issue_number)

    with _ACTIVE_ISSUES_LOCK:
        if key in _ACTIVE_ISSUES:
            _log.debug(
                "[Watcher] Issue #%d in %s already being processed — skipping duplicate",
                issue_number,
                repo,
            )
            return
        _ACTIVE_ISSUES.add(key)

    try:
        fn(issue, repo, *args, **kwargs)
    finally:
        with _ACTIVE_ISSUES_LOCK:
            _ACTIVE_ISSUES.discard(key)


def _is_retryable_http_error(exc: BaseException) -> bool:
    """Return True if exc is a transient network or HTTP error worth retrying."""
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError):
        resp = getattr(exc, "response", None)
        return resp is not None and resp.status_code in {429, 500, 502, 503, 504}
    return False


_retry_github = retry(
    retry=retry_if_exception(_is_retryable_http_error),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(5),
    before_sleep=before_sleep_log(_log, logging.WARNING),
    reraise=True,
)


def _gh_headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


# ── GitHub helpers ────────────────────────────────────────────────────────────

@_retry_github
def ensure_label(repo: str, name: str, colour: str) -> None:
    """Create a label if it doesn't already exist (idempotent — tolerates 422)."""
    url = f"https://api.github.com/repos/{repo}/labels"
    existing = requests.get(url, headers=_gh_headers(), timeout=10)
    existing.raise_for_status()
    names = {lbl["name"] for lbl in existing.json()}
    if name not in names:
        resp = requests.post(
            url,
            headers=_gh_headers(),
            json={"name": name, "color": colour},
            timeout=10,
        )
        if resp.status_code == 422:
            # GitHub returns 422 for "already exists" (race) AND for validation errors.
            # Only treat it as an idempotent no-op when the error code indicates a duplicate.
            try:
                body = resp.json() if resp.content else {}
            except ValueError:
                body = {}
            errors = body.get("errors", [])
            if any(e.get("code") == "already_exists" for e in errors):
                _log.debug("ensure_label: %s already exists in %s (concurrent create)", name, repo)
                return
            resp.raise_for_status()  # real validation failure — propagate
        resp.raise_for_status()


@_retry_github
def add_label(repo: str, issue_number: int, label: str) -> None:
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/labels"
    resp = requests.post(url, headers=_gh_headers(), json={"labels": [label]}, timeout=10)
    resp.raise_for_status()


@_retry_github
def remove_label(repo: str, issue_number: int, label: str) -> None:
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/labels/{label}"
    resp = requests.delete(url, headers=_gh_headers(), timeout=10)
    if resp.status_code == 404:
        return  # label already absent — idempotent no-op
    resp.raise_for_status()


@_retry_github
def _get_open_issues_raw(repo: str, label: str | list[str]) -> list[GitHubIssue]:
    """Inner (retryable) implementation of get_open_issues.

    Uses raise_for_status() so that 429/5xx responses surface as HTTPError
    and are intercepted by @_retry_github for exponential-backoff retries.
    """
    labels = [label] if isinstance(label, str) else list(label)
    seen: set[int] = set()
    issues: list[dict] = []
    for lbl in labels:
        url = f"https://api.github.com/repos/{repo}/issues"
        params = {"state": "open", "labels": lbl, "per_page": 50}
        resp = requests.get(url, headers=_gh_headers(), params=params, timeout=10)
        resp.raise_for_status()
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


def get_open_issues(repo: str, label: str | list[str]) -> list[GitHubIssue]:
    """Return open issues with the given label(s) that haven't been processed.

    label may be a single string or a list; issues matching ANY label are returned
    (deduped by issue number).

    Retries transiently on 429/5xx via @_retry_github applied to the inner
    function.  On final failure converts HTTPError to RuntimeError so callers
    receive a consistent exception type.
    """
    try:
        return _get_open_issues_raw(repo, label)
    except requests.HTTPError as exc:
        resp = exc.response
        if resp is None:
            raise RuntimeError("GitHub API error: (no response)") from exc
        raise RuntimeError(
            f"GitHub API error {resp.status_code}: {resp.text[:200]}"
        ) from exc


@_retry_github
def _get_open_prs_raw(repo: str, skip_drafts: bool = True) -> list[GitHubPR]:
    """Inner (retryable) implementation of get_open_prs.

    Uses raise_for_status() so that 429/5xx responses surface as HTTPError
    and are intercepted by @_retry_github for exponential-backoff retries.
    """
    url = f"https://api.github.com/repos/{repo}/pulls"
    params = {"state": "open", "per_page": 50}
    resp = requests.get(url, headers=_gh_headers(), params=params, timeout=10)
    resp.raise_for_status()
    prs = resp.json()
    if skip_drafts:
        prs = [pr for pr in prs if not pr.get("draft", False)]
    return prs


def get_open_prs(repo: str, skip_drafts: bool = True) -> list[GitHubPR]:
    """Return open pull requests for the repo, optionally excluding drafts.

    Retries transiently on 429/5xx via @_retry_github applied to the inner
    function.  On final failure converts HTTPError to RuntimeError so callers
    receive a consistent exception type.
    """
    try:
        return _get_open_prs_raw(repo, skip_drafts)
    except requests.HTTPError as exc:
        resp = exc.response
        if resp is None:
            raise RuntimeError("GitHub API error: (no response)") from exc
        raise RuntimeError(
            f"GitHub API error {resp.status_code}: {resp.text[:200]}"
        ) from exc


@_retry_github
def _get_pr_comments_raw(repo: str, pr_number: int) -> list[GitHubComment]:
    """Inner (retryable) implementation of get_pr_comments.

    Uses raise_for_status() so that 429/5xx responses surface as HTTPError
    and are intercepted by @_retry_github for exponential-backoff retries.
    """
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    resp = requests.get(url, headers=_gh_headers(), params={"per_page": 100}, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_pr_comments(repo: str, pr_number: int) -> list[GitHubComment]:
    """Return all conversation comments on a pull request.

    Retries transiently on 429/5xx via @_retry_github applied to the inner
    function.  On final failure converts HTTPError to RuntimeError so callers
    receive a consistent exception type.
    """
    try:
        return _get_pr_comments_raw(repo, pr_number)
    except requests.HTTPError as exc:
        resp = exc.response
        if resp is None:
            raise RuntimeError("GitHub API error: (no response)") from exc
        raise RuntimeError(
            f"GitHub API error {resp.status_code}: {resp.text[:200]}"
        ) from exc


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
    except Exception:  # noqa: BLE001
        _log.debug("Could not fetch comments for #%d", issue_number, exc_info=True)
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
    resp = requests.post(url, headers=_gh_headers(), json={"body": body}, timeout=10)
    resp.raise_for_status()


# ── Pipeline dispatch ─────────────────────────────────────────────────────────

def run_pipeline(
    issue: dict | None = None,
    tracker_repo: str = "",
    default_target: str | None = None,
    label: str = "",
    model: str = "",
    num_engineers: int = 1,
    log_dir: Path | None = None,
    dry_run: bool = False,
    logger: logging.Logger | None = None,
    *,
    target_repo: str | None = None,
    issue_number: int | None = None,
    log_file: Path | None = None,
    dlq=None,          # DeadLetterQueue | None
) -> bool:
    """Run the appropriate orchestrator for a single issue. Returns True on success.

    Supports two calling conventions:

    *Old style* (used by ``watch()``):
        ``run_pipeline(issue, tracker_repo, default_target, label, model,
        num_engineers, log_dir, dry_run, logger)``

    *New style* (used by tests and direct callers):
        ``run_pipeline(label=..., tracker_repo=..., target_repo=...,
        issue_number=..., model=..., num_engineers=..., log_file=...,
        logger=..., dlq=...)``
    """
    # ── Resolve parameters from whichever calling convention is used ──────────
    if issue is not None:
        _issue_number: int = issue["number"]
        _issue_title: str = issue.get("title", "")
        _target_repo: str = (
            _parse_target_repo(issue.get("body") or "")
            or default_target
            or tracker_repo
        )
    else:
        if issue_number is None:
            raise ValueError("Either 'issue' dict or 'issue_number' must be provided")
        _issue_number = issue_number
        _issue_title = f"issue #{issue_number}"
        _target_repo = target_repo or tracker_repo

    if logger is None:
        # Ensure a non-None logger to forward downstream (e.g. to _dispatch).
        # Local log calls in this function use the module-level _log instead.
        logger = logging.getLogger("watcher")

    _log.info(
        "  → Issue #%d: %r | label=%s | target=%s",
        _issue_number, _issue_title, label, _target_repo,
    )

    if dry_run:
        _log.info("    [dry-run] Would run pipeline for label=%s", label)
        return True

    # ── Resolve log file path ─────────────────────────────────────────────────
    if log_file is not None:
        issue_log: Path = log_file
    elif log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        issue_log = log_dir / f"issue-{_issue_number}-{ts}.log"
    else:
        issue_log = Path(f"logs/issue-{_issue_number}.log")

    try:
        # Mark as running
        add_label(tracker_repo, _issue_number, LABEL_RUNNING)
        remove_label(tracker_repo, _issue_number, LABEL_QUEUED)

        result = _dispatch(
            label=label,
            tracker_repo=tracker_repo,
            target_repo=_target_repo,
            issue_number=_issue_number,
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
            remove_label(tracker_repo, _issue_number, LABEL_RUNNING)
            # Remove any previous terminal labels so SKIP_LABELS won't block it
            for stale in (LABEL_COMPLETE, LABEL_FAILED):
                try:
                    remove_label(tracker_repo, _issue_number, stale)
                except Exception:  # noqa: BLE001
                    _log.debug("Could not remove stale label %r from #%d", stale, _issue_number, exc_info=True)
            ensure_label(tracker_repo, next_label, "c5def5")
            add_label(tracker_repo, _issue_number, next_label)
            post_comment(
                tracker_repo,
                _issue_number,
                f"## 🔁 Pipeline Chaining → `{next_label}`\n\n"
                f"The pipeline completed but follow-up work was detected "
                f"(verdict: `{result.verdict or 'n/a'}`, "
                f"tests_passed: `{result.tests_passed}`, "
                f"deploy_tests_passed: `{result.deploy_tests_passed}`).\n\n"
                f"Automatically re-queued with label `{next_label}`. "
                f"The watcher will pick this up on the next cycle.\n\n"
                f"To stop chaining, remove the `{next_label}` label.",
            )
            _log.info(
                "    🔁 Issue #%d chained → label=%s (verdict=%s, tests_passed=%s)",
                _issue_number, next_label, result.verdict, result.tests_passed,
            )
        else:
            add_label(tracker_repo, _issue_number, LABEL_COMPLETE)
            remove_label(tracker_repo, _issue_number, LABEL_RUNNING)
            _log.info("    ✅ Issue #%d complete", _issue_number)

        return True

    except Exception as exc:  # noqa: BLE001
        _token = os.environ.get("GITHUB_TOKEN", "")
        _log.error("    ❌ Issue #%d failed: %s", _issue_number, _sanitise(str(exc), _token), exc_info=True)
        try:
            add_label(tracker_repo, _issue_number, LABEL_FAILED)
            remove_label(tracker_repo, _issue_number, LABEL_RUNNING)
            post_comment(
                tracker_repo,
                _issue_number,
                f"## ❌ Agent Pipeline Failed\n\n```\n{_sanitise(str(exc), _token)}\n```\n\n"
                f"Log: `{issue_log}`\n\nRemove the `{LABEL_FAILED}` label and re-label "
                f"the issue to retry.",
            )
        except Exception:  # noqa: BLE001
            _log.debug("Could not update labels/comment for #%d during failure cleanup", _issue_number, exc_info=True)
        # ── Enqueue to DLQ for later retry ────────────────────────────────────
        if dlq is not None:
            from core.dead_letter import DLQEntry
            from core.errors import PipelineError
            _dlq_entry = DLQEntry(
                id=str(uuid.uuid4()),
                issue_number=_issue_number,
                tracker_repo=tracker_repo,
                target_repo=_target_repo,
                label=label,
                model=model,
                num_engineers=num_engineers,
                failed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                error=PipelineError(
                    code="AGENT_CRASH",
                    stage="pipeline",
                    message=_sanitise(str(exc), os.environ.get("GITHUB_TOKEN", "")),
                    severity="fatal",
                ).to_dict(),
                stage_name=getattr(exc, "stage", None) or "pipeline",
            )
            try:
                dlq.enqueue(_dlq_entry)
            except Exception as _dlq_exc:  # noqa: BLE001
                _log.warning("Could not enqueue to DLQ: %s", _sanitise(str(_dlq_exc), os.environ.get("GITHUB_TOKEN", "")))
        return False


def _load_pipeline_config() -> dict:
    """Load config.yaml + config.local.yaml from the script directory.

    Returns the merged config dict with llm and pipeline sections.
    Raises ValueError if the merged result fails AppConfig schema validation.
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
    try:
        _AppConfig.model_validate(cfg)  # validate only; callers consume raw dict
    except _ValidationError as exc:
        # Use include_input=False to avoid leaking secret values (e.g. github.token)
        # that may appear in Pydantic's input_value snippets.
        errors = exc.errors(include_input=False, include_url=False)
        raise ValueError(
            f"Invalid config (merged config.yaml + config.local.yaml): {errors}"
        ) from exc
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
    logger: logging.Logger,  # noqa: ARG001 – forwarded by callers; body uses module _log
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
                _log.info("    Using pipelines/%s.yaml (%d stages)", label, len(stages))
            else:
                _log.info("    Using built-in default pipeline (no pipelines/%s.yaml)", label)

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
    logger: logging.Logger,  # noqa: ARG001 – accepted for API consistency; body uses module _log
    pr_fix_label: str = "ai-fix",
    update_branch_enabled: bool = False,
    conflict_resolver_model: Optional[str] = None,
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

    _log.info("  🔄 PR #%d: starting fix attempt %d", pr_number, attempt)

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
                    update_branch_enabled=update_branch_enabled,
                    conflict_resolver_model=conflict_resolver_model,
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
                    _log.info("  ❌ PR #%d fix attempt %d: %s", pr_number, attempt, status)
                else:
                    add_label(target_repo, pr_number, LABEL_COMPLETE)
                    remove_label(target_repo, pr_number, LABEL_RUNNING)
                    # Remove trigger label so next cycle doesn't re-trigger
                    remove_label(target_repo, pr_number, pr_fix_label)
                    _log.info("  ✅ PR #%d fix attempt %d complete", pr_number, attempt)

            except Exception as exc:  # noqa: BLE001
                _log.error("  ❌ PR #%d fix attempt %d unhandled error: %s", pr_number, attempt, _sanitise(str(exc), token))
                add_label(target_repo, pr_number, LABEL_FAILED)
                remove_label(target_repo, pr_number, LABEL_RUNNING)
                post_comment(
                    target_repo, pr_number,
                    f"❌ PR fix attempt {attempt} failed with error: `{_sanitise(str(exc), token)}`\n"
                    f"Log: `{log_file}`\n\nRemove `agent-failed` to retry.",
                )
            finally:
                sys.stdout, sys.stderr = old_stdout, old_stderr
    except OSError as exc:  # noqa: BLE001
        _log.error("  ❌ PR #%d: could not open log file %s: %s", pr_number, log_file, _sanitise(str(exc), token))
        add_label(target_repo, pr_number, LABEL_FAILED)
        remove_label(target_repo, pr_number, LABEL_RUNNING)
        post_comment(
            target_repo, pr_number,
            f"❌ PR fix attempt {attempt} failed: could not open log file.\n"
            f"`{_sanitise(str(exc), token)}`\n\nRemove `agent-failed` to retry.",
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
        update_branch_enabled = bool(_w_settings.get("update_branch", False))
        conflict_resolver_model = _w_settings.get("conflict_resolver_model")
        pr_failure_pattern = _w_settings.get("pr_failure_pattern", r"❌|FAILED|tests? failed|test suite failed")
        try:
            max_pr_retries = int(_w_settings.get("max_pr_retries", 3))
        except (ValueError, TypeError):
            _log.warning("Invalid max_pr_retries for %s; defaulting to 3", tracker_repo)
            max_pr_retries = 3
        skip_drafts = not _w_settings.get("watch_draft_prs", False)

        _log.info("Checking PRs in %s (tracker: %s) …", target_repo, tracker_repo)
        try:
            prs = get_open_prs(target_repo, skip_drafts=skip_drafts)
        except Exception as exc:  # noqa: BLE001
            _log.error("Failed to fetch PRs from %s: %s", target_repo, _sanitise(str(exc), os.environ.get("GITHUB_TOKEN", "")))
            continue

        for pr in prs:
            pr_number = pr["number"]
            try:
                comments = get_pr_comments(target_repo, pr_number)
            except Exception as exc:  # noqa: BLE001
                _log.warning("Could not fetch comments for PR #%d: %s", pr_number, _sanitise(str(exc), os.environ.get("GITHUB_TOKEN", "")))
                comments = []

            if not _should_fix_pr(pr, comments, pr_fix_label, pr_failure_pattern, max_pr_retries):
                continue

            _log.info("  🔧 PR #%d needs fixing (%s)", pr_number, pr.get("title", ""))

            if dry_run:
                _log.info("    [dry-run] Would run PR fix for #%d", pr_number)
                continue

            _run_pr_revision(
                pr, tracker_repo, target_repo, model, num_engineers, log_dir, logger,
                pr_fix_label=pr_fix_label,
                update_branch_enabled=update_branch_enabled,
                conflict_resolver_model=conflict_resolver_model,
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
    """Write a resume trigger file atomically so the main watch() loop picks up the issue next cycle."""
    trigger_dir = os.path.join(workspace_dir, "resume_queue")
    os.makedirs(trigger_dir, exist_ok=True)
    trigger_path = os.path.join(trigger_dir, f"resume_{issue_number}.json")
    tmp_path_str = trigger_path + ".tmp"
    payload = {
        "issue_number": issue_number,
        "issue_title": issue_title,
        "requirement": requirement,
    }
    with open(tmp_path_str, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp_path_str, trigger_path)  # atomic on POSIX
    logging.getLogger("watcher").info("[Watcher] Resume trigger written: %s", trigger_path)


def check_waiting_issues(github_token: str, tracker_repos: list[str], workspace_dir: str, bot_login: str) -> None:
    """Check all issues labelled agent-waiting for human replies.

    For each waiting issue that has a checkpoint with pending_clarification:
    1. Fetch comments after the question comment
    2. If human has replied, inject answers into checkpoint and re-label
    3. Re-dispatch pipeline (by removing agent-waiting and calling dispatch logic)
    """
    from orchestrator import PipelineResult

    for tracker_repo in tracker_repos:
        try:
            waiting_issues = _get_issues_by_label(tracker_repo, LABEL_WAITING, github_token)
        except Exception as exc:
            _log.warning("[Watcher] Could not list agent-waiting issues for %s: %s", tracker_repo, _sanitise(str(exc), github_token))
            continue

        for issue in waiting_issues:
            issue_number = issue["number"]
            issue_title = issue.get("title", "")

            # Find checkpoint for this issue
            checkpoint_path = _find_checkpoint_for_issue(workspace_dir, issue_number)
            if not checkpoint_path:
                _log.info(f"[Watcher] Issue #{issue_number}: no checkpoint found, skipping")
                continue

            try:
                with open(checkpoint_path) as f:
                    data = json.load(f)
                result = PipelineResult.from_dict(data)
            except Exception as exc:
                _log.warning(f"[Watcher] Issue #{issue_number}: could not load checkpoint: {_sanitise(str(exc), github_token)}")
                continue

            if not result.pending_clarification:
                _log.info(f"[Watcher] Issue #{issue_number}: no pending_clarification in checkpoint")
                continue

            pending = result.pending_clarification
            question_comment_id = pending.get("question_comment_id")
            if not question_comment_id:
                _log.info(f"[Watcher] Issue #{issue_number}: no question_comment_id, skipping")
                continue

            # Fetch comments and check for answers
            try:
                comments = _get_issue_comments(tracker_repo, issue_number, github_token)
            except Exception as exc:
                _log.warning(f"[Watcher] Issue #{issue_number}: could not fetch comments: {_sanitise(str(exc), github_token)}")
                continue

            answers = extract_answers_from_comments(comments, question_comment_id, bot_login)
            if not answers:
                _log.info(f"[Watcher] Issue #{issue_number}: no human reply yet")
                continue

            _log.info(f"[Watcher] Issue #{issue_number}: human replied ({len(answers)} answer(s)), resuming pipeline")

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
                _log.warning(f"[Watcher] Issue #{issue_number}: could not update labels: {_sanitise(str(exc), github_token)}")

            # Trigger re-dispatch by appending to a simple queue file (watcher picks it up next cycle)
            _trigger_resume(issue_number, issue_title, result.requirement, workspace_dir)


def _get_issues_by_label(repo: str, label: str, token: str) -> list[GitHubIssue]:
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


def _get_issue_comments(repo: str, issue_number: int, token: str) -> list[GitHubComment]:
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


def _process_resume_queue(workspace_dir: str, tracker_repos: list[str], default_targets: dict[str, str], model: str, num_engineers: int, log_dir: Path, dry_run: bool, logger: logging.Logger) -> list[WatcherTask]:  # noqa: ARG001 (logger) – body uses module _log
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
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    _log.debug("[Watcher] Skipping locked resume file %s (another process holds it)", os.path.basename(trigger_path))
                    continue
                try:
                    trigger = json.load(f)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
            issue_number = trigger["issue_number"]
            requirement = trigger.get("requirement", trigger.get("issue_title", ""))
            _log.info(f"[Watcher] Resuming pipeline for issue #{issue_number}")

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
                        _log.info(f"  Queued resumed issue #{issue_number}: {issue.get('title', '')}")
                        task_created = True
                        break
                except Exception as exc:
                    _log.debug("Could not fetch issue #%d from %s: %s", issue_number, tracker_repo, _sanitise(str(exc), token))
                    continue

            # Only delete trigger after task successfully created; keep for retry otherwise
            if task_created:
                os.remove(trigger_path)
            else:
                _log.warning(
                    f"[Watcher] Could not fetch issue #{issue_number} from any repo — "
                    f"keeping trigger for retry"
                )
        except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
            _token = os.environ.get("GITHUB_TOKEN", "")
            _log.warning(
                "Could not load watcher entry %s: %s",
                trigger_path, _sanitise(str(exc), _token),
                exc_info=True,
            )
    
    return tasks


# ── Watcher loop ──────────────────────────────────────────────────────────────

def watch(config_path: Path, dry_run: bool = False, logger: logging.Logger | None = None) -> None:  # noqa: ARG001 – logger kept for backward compat
    config = load_watcher_config(config_path)

    global_settings = config.get("settings", {})
    log_dir       = Path(config_path.parent / global_settings.get("log_dir", "logs/watcher"))

    run_id = uuid.uuid4().hex[:8]
    logger = _setup_logging(log_dir, run_id=run_id)
    bind_run_id(run_id)
    _log.info("Watcher starting", extra={"run_id": run_id})

    max_parallel  = global_settings.get("max_parallel", 3)

    watchers = config.get("watchers", [])
    _log.info("Loaded %d watcher(s) from %s", len(watchers), config_path)

    # Validate each watcher entry; skip invalid entries with a warning
    validated_watchers: list[dict] = []
    for entry in watchers:
        try:
            load_repo_entry(entry)   # validate; raises ValidationError on bad entry
            validated_watchers.append(entry)
        except _ValidationError as exc:
            name = entry.get("tracker_repo", "?") if isinstance(entry, dict) else repr(entry)
            _log.warning(
                "Skipping invalid watcher entry %r: %s",
                name,
                exc,
            )
    watchers = validated_watchers

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

    # Wire Prometheus metrics sink if configured
    _metrics_url = global_settings.get("metrics_url")
    if _metrics_url:
        from core.events import set_emit_callback
        from core.metrics_sink import build_callback
        set_emit_callback(build_callback(_metrics_url))
        _log.info("Metrics sink wired to %s", _metrics_url)

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

        _log.info("Checking %s …", tracker_repo)
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
                    _log.info("  Queued %s issue #%d: %s", pipeline_name, issue["number"], issue["title"])
        except Exception as exc:  # noqa: BLE001
            _log.error(
                "Failed to fetch issues from %s: %s",
                tracker_repo, _sanitise(str(exc), github_token),
                exc_info=True,
            )

    try:
        if not tasks:
            _log.info("Nothing to do.")
            return

        # Group tasks by tracker_repo so each gets its own thread pool
        by_repo: dict[str, list[dict]] = {}
        for t in tasks:
            by_repo.setdefault(t["tracker_repo"], []).append(t)

        _log.info("Dispatching %d pipeline(s) across %d repo(s)…", len(tasks), len(by_repo))

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
                    ctx = contextvars.copy_context()
                    fut = ex.submit(
                        ctx.run,
                        _run_with_issue_lock,
                        _run_with_global_cap,
                        t["issue"], t["tracker_repo"], t["default_target"],
                        t["label"], t.get("model", "gpt-4.1"), t.get("num_engineers", 2), log_dir, dry_run, logger,
                    )
                    futures_to_task[fut] = t

            pipeline_timeout_s = int(global_settings.get("pipeline_timeout_s") or 3600)

            try:
                for fut in as_completed(futures_to_task, timeout=pipeline_timeout_s):
                    t = futures_to_task[fut]
                    try:
                        fut.result()
                    except Exception as exc:  # noqa: BLE001
                        _log.error(
                            "Unhandled error for issue #%d: %s",
                            t["issue"]["number"],
                            _sanitise(str(exc), github_token),
                            exc_info=True,
                        )
            except FuturesTimeoutError:
                hung = [
                    f"#{futures_to_task[f]['issue']['number']}"
                    for f in futures_to_task
                    if not f.done()
                ]
                _log.warning(
                    "Pipeline timeout (%ds) exceeded — cancelling %d hung pipeline(s): %s",
                    pipeline_timeout_s, len(hung), ", ".join(hung),
                )
                for f in futures_to_task:
                    f.cancel()
                # Clean up labels for futures that were cancelled before they started running.
                # Futures that were already running have their own label lifecycle in run_pipeline().
                for f in futures_to_task:
                    if f.cancelled():
                        t = futures_to_task[f]
                        issue_number = t["issue"]["number"]
                        tracker_repo = t["tracker_repo"]
                        _log.warning(
                            "Issue #%d timed out before starting — marking as failed",
                            issue_number,
                        )
                        try:
                            remove_label(tracker_repo, issue_number, LABEL_QUEUED)
                        except Exception:  # noqa: BLE001
                            _log.warning(
                                "Could not remove %s for timed-out issue #%d",
                                LABEL_QUEUED, issue_number, exc_info=True,
                            )
                        try:
                            add_label(tracker_repo, issue_number, LABEL_FAILED)
                        except Exception:  # noqa: BLE001
                            _log.warning(
                                "Could not add %s for timed-out issue #%d",
                                LABEL_FAILED, issue_number, exc_info=True,
                            )
        finally:
            for ex in repo_executors:
                ex.shutdown(wait=False, cancel_futures=True)
    finally:
        clear_run_id()


# ── Entry point ───────────────────────────────────────────────────────────────

def _setup_logging(log_dir: Path, run_id: str | None = None) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    if run_id is not None:
        log_file = log_dir / f"run-{run_id}.jsonl"
    else:
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d")
        log_file = log_dir / f"watcher-{ts}.log"
    configure_logging(log_level="INFO", log_file=log_file)
    return logging.getLogger("watcher")


def _cmd_list_dlq(cfg: dict) -> None:
    """Print all current DLQ entries to stdout as a formatted table.

    Warning: for the SQS backend, this calls drain() which temporarily changes
    message visibility. Messages will reappear after the visibility timeout expires.
    """
    from core.dead_letter import build_dlq
    from config_schema import DLQConfig

    dlq_cfg_raw = (cfg.get("reliability") or {}).get("dead_letter", {})
    dlq_cfg = DLQConfig.model_validate(dlq_cfg_raw) if dlq_cfg_raw else DLQConfig()

    if dlq_cfg.backend == "sqs":
        print("Note: SQS backend — listing temporarily affects message visibility.\n")

    dlq = build_dlq(dlq_cfg, workspace_root=Path("."))

    entries = list(dlq.drain())
    if not entries:
        print("DLQ is empty — no failed entries.")
        return

    header = f"{'ID':<36}  {'Issue':>6}  {'Stage':<20}  {'Attempts':>8}  {'Failed At':<22}  Error"
    print(header)
    print("-" * len(header))
    for e in entries:
        error_msg = (e.error or {}).get("message", str(e.error))[:60]
        print(
            f"{e.id:<36}  {e.issue_number:>6}  {e.stage_name:<20}  {e.attempt_count:>8}  "
            f"{e.failed_at:<22}  {error_msg}"
        )
    print(f"\n{len(entries)} entr{'y' if len(entries) == 1 else 'ies'} in DLQ.")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Software House — GitHub issue watcher")
    parser.add_argument("--config", default="repos.yaml", help="Path to repos.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run, make no changes")
    parser.add_argument("--once", action="store_true",
                        help="Process a single issue and exit (used by GitHub Actions)")
    parser.add_argument("--repo", help="(--once mode) tracker repo, e.g. owner/repo")
    parser.add_argument("--issue", type=int, help="(--once mode) issue number")
    parser.add_argument("--label", help="(--once mode) GitHub label that triggered the pipeline")

    parser.add_argument(
        "--retry-dlq",
        action="store_true",
        default=False,
        help="Drain the dead-letter queue and retry failed pipeline tasks.",
    )
    parser.add_argument(
        "--list-dlq",
        action="store_true",
        default=False,
        help="List all entries currently in the dead-letter queue and exit. "
             "Note: for the SQS backend, listing temporarily affects message visibility.",
    )

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
        _log.info("✅ Issue #%d complete", issue)
        return 0
    except Exception as exc:  # noqa: BLE001
        _log.error("❌ Issue #%d failed: %s", issue, _sanitise(str(exc), os.environ.get("GITHUB_TOKEN", "")))
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

    # ── --list-dlq: display current DLQ entries and exit ─────────────────────
    if args.list_dlq:
        pipeline_cfg = _load_pipeline_config()
        _cmd_list_dlq(pipeline_cfg)
        sys.exit(0)

    # ── --retry-dlq: drain dead-letter queue and retry failed tasks ──────────
    if args.retry_dlq:
        from core.dead_letter import build_dlq
        pipeline_cfg = _load_pipeline_config()
        rel_cfg = pipeline_cfg.get("reliability") or {}
        dlq_cfg_raw = rel_cfg.get("dead_letter", {})
        from config_schema import DLQConfig
        dlq_cfg = DLQConfig.model_validate(dlq_cfg_raw) if dlq_cfg_raw else DLQConfig()
        dlq = build_dlq(dlq_cfg)
        retried = 0
        failed = 0
        for entry in dlq.drain():
            _log.info("Retrying DLQ entry: issue #%d (%s)", entry.issue_number, entry.tracker_repo)
            try:
                ok = run_pipeline(
                    label=entry.label,
                    tracker_repo=entry.tracker_repo,
                    target_repo=entry.target_repo or entry.tracker_repo,
                    issue_number=entry.issue_number,
                    model=entry.model,
                    num_engineers=entry.num_engineers,
                    log_file=log_dir / f"dlq_retry_{entry.issue_number}.log",
                    logger=logger,
                    # Intentionally no dlq= to prevent re-enqueue loops
                )
            except Exception as exc:  # noqa: BLE001
                _log.warning("DLQ retry failed for issue #%d: %s", entry.issue_number, _sanitise(str(exc), os.environ.get("GITHUB_TOKEN", "")))
                dlq.nack(entry.id)
                failed += 1
            else:
                if ok:
                    dlq.ack(entry.id)
                    retried += 1
                else:
                    _log.warning("DLQ retry returned failure for issue #%d", entry.issue_number)
                    dlq.nack(entry.id)
                    failed += 1
        _log.info("DLQ drain complete: %d retried, %d failed", retried, failed)
        sys.exit(0)

    if LOCK_FILE.exists():
        age = time.time() - LOCK_FILE.stat().st_mtime
        if age < 3600:
            _log.warning("Lock file exists (age %.0fs) — previous run still in progress. Exiting.", age)
            sys.exit(0)
        else:
            _log.warning("Stale lock file (age %.0fs) — removing and continuing.", age)
            LOCK_FILE.unlink()

    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    install_llm_pool_from_config(_load_pipeline_config())
    _log.info("═" * 60)
    _log.info("AI Software House Watcher — %s%s",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                " [DRY RUN]" if args.dry_run else "")
    _log.info("Config: %s", config_path)
    try:
        watch(config_path, dry_run=args.dry_run)
    finally:
        LOCK_FILE.unlink(missing_ok=True)
        _log.info("Done.")


if __name__ == "__main__":
    main()
