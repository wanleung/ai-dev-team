#!/usr/bin/env python3
"""press_maintenance.py — Automated maintenance for the ai-it-press pipeline.

Runs three jobs:
  1. auto-merge  — Approve and squash-merge open press PRs that are ready.
  2. stuck-running — Issues stuck in agent-running for too long → re-queue.
  3. stuck-complete — Issues marked agent-complete but with a failed/incomplete
                      pipeline comment → re-queue.

Designed to run every 15 minutes via cron:
  */15 * * * * cd /home/wanleung/Projects/ai-software-house && \
    venv/bin/python scripts/press_maintenance.py >> logs/press_maintenance.log 2>&1

Environment:
  GITHUB_TOKEN  — required (same token used by the orchestrator)
  PRESS_TRACKER — optional, defaults to wanleung/ai-it-press
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TRACKER_REPO = os.environ.get("PRESS_TRACKER", "wanleung/ai-it-press")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
API_BASE = "https://api.github.com"

# How long an issue may stay in agent-running before we consider it stuck.
# config.local.yaml sets pipeline_timeout_s: 7200 (2h), so 3h gives one hour
# of grace before we intervene.
STUCK_RUNNING_HOURS = 3

# Trigger label that re-queues an issue through the news-article pipeline.
PRESS_LABEL = "press"

# Agent state labels (mirror watcher.py constants)
LABEL_RUNNING  = "agent-running"
LABEL_COMPLETE = "agent-complete"
LABEL_FAILED   = "agent-failed"
LABEL_QUEUED   = "agent-queued"

# The orchestrator posts a "## 🤖 Pipeline Progress" comment on the issue
# with per-stage ✅/❌/⬜ markers.  A completed pipeline has:
#   - ✅ 📨 News Article PR   (last mandatory stage)
# A failed pipeline has one or more ❌ stage lines and ⬜ for subsequent ones.
PROGRESS_HEADER   = "## 🤖 Pipeline Progress"
SUCCESS_STAGE     = "✅ 📨 News Article PR"   # last required stage checked
STAGE_FAIL_MARKER = "❌"                        # any stage failure

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("press_maintenance")


# ---------------------------------------------------------------------------
# GitHub helpers (thin layer — no dependency on github_client.py)
# ---------------------------------------------------------------------------

def _headers() -> dict:
    if not GITHUB_TOKEN:
        log.error("GITHUB_TOKEN is not set — cannot call GitHub API")
        sys.exit(1)
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get(path: str, params: dict | None = None) -> list | dict:
    url = f"{API_BASE}{path}"
    resp = requests.get(url, headers=_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, json: dict) -> dict:
    resp = requests.post(f"{API_BASE}{path}", headers=_headers(), json=json, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _put(path: str, json: dict) -> dict:
    resp = requests.put(f"{API_BASE}{path}", headers=_headers(), json=json, timeout=15)
    resp.raise_for_status()
    return resp.json() if resp.text else {}


def _delete(path: str) -> None:
    resp = requests.delete(f"{API_BASE}{path}", headers=_headers(), timeout=15)
    if resp.status_code == 404:
        return  # already absent
    resp.raise_for_status()


def add_label(issue_number: int, label: str) -> None:
    _post(f"/repos/{TRACKER_REPO}/issues/{issue_number}/labels", {"labels": [label]})


def remove_label(issue_number: int, label: str) -> None:
    try:
        _delete(f"/repos/{TRACKER_REPO}/issues/{issue_number}/labels/{label}")
    except requests.HTTPError:
        pass  # 404 = already absent, ignore other errors too for idempotency


def get_issue_comments(issue_number: int) -> list[dict]:
    return _get(f"/repos/{TRACKER_REPO}/issues/{issue_number}/comments",
                params={"per_page": 100})


def list_open_issues(label: str) -> list[dict]:
    """Return all open issues with the given label (handles pagination)."""
    issues: list[dict] = []
    page = 1
    while True:
        batch = _get(f"/repos/{TRACKER_REPO}/issues",
                     params={"state": "open", "labels": label,
                             "per_page": 100, "page": page})
        if not batch:
            break
        issues.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return issues


def list_open_prs() -> list[dict]:
    """Return all open PRs in the tracker repo."""
    prs: list[dict] = []
    page = 1
    while True:
        batch = _get(f"/repos/{TRACKER_REPO}/pulls",
                     params={"state": "open", "per_page": 100, "page": page})
        if not batch:
            break
        prs.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return prs


def merge_pr(pr_number: int, title: str) -> bool:
    """Squash-merge a PR. Returns True on success, False if not mergeable."""
    resp = requests.put(
        f"{API_BASE}/repos/{TRACKER_REPO}/pulls/{pr_number}/merge",
        headers=_headers(),
        json={"merge_method": "squash",
              "commit_title": title,
              "commit_message": "Auto-merged by press_maintenance."},
        timeout=15,
    )
    if resp.status_code == 200:
        return True
    if resp.status_code in (405, 409):
        # 405 = not mergeable yet; 409 = merge conflict
        log.warning("PR #%d not mergeable (%d): %s", pr_number, resp.status_code,
                    resp.json().get("message", ""))
        return False
    resp.raise_for_status()
    return False


# ---------------------------------------------------------------------------
# Job 1: Auto-merge ready press PRs
# ---------------------------------------------------------------------------

def _is_press_pr(pr: dict) -> bool:
    """Heuristic: branch created by the news_article_pr or image_pr stage."""
    ref: str = pr.get("head", {}).get("ref", "")
    # news_article_pr uses branch_prefix="article" → "article/<slug>"
    # image_pr standalone mode uses "image/<slug>"
    return ref.startswith("article/") or ref.startswith("image/")


def _fetch_pr(pr_number: int) -> dict:
    """Fetch a single PR — triggers GitHub to compute mergeable_state if unknown."""
    return _get(f"/repos/{TRACKER_REPO}/pulls/{pr_number}")


def job_auto_merge(dry_run: bool = False) -> None:
    log.info("=== job: auto-merge ===")
    prs = list_open_prs()
    press_prs = [p for p in prs if _is_press_pr(p)]
    log.info("Found %d open PR(s), %d look like press articles", len(prs), len(press_prs))

    for pr in press_prs:
        num = pr["number"]
        draft = pr.get("draft", False)
        if draft:
            continue

        # The list endpoint returns mergeable_state=unknown for PRs GitHub hasn't
        # recently computed mergeability for.  A single individual GET wakes the
        # computation and returns the real state immediately.
        pr = _fetch_pr(num)
        title = pr.get("title", f"PR #{num}")
        state = pr.get("mergeable_state", "unknown")
        merged = pr.get("merged", False)

        if merged:
            continue

        log.info("PR #%d %r — mergeable_state=%s", num, title, state)

        if state in ("unknown", "blocked", "behind", "dirty"):
            log.info("  → skipping (state=%s)", state)
            continue

        # state == "clean" or "has_hooks" — safe to merge directly.
        # Approval is skipped: GitHub does not allow approving your own PR,
        # and as repo owner you can merge without a review.
        if dry_run:
            log.info("  [dry-run] would merge PR #%d", num)
        else:
            ok = merge_pr(num, title)
            if ok:
                log.info("  ✓ merged PR #%d %r", num, title)
            else:
                log.info("  → merge deferred for PR #%d (not ready)", num)


# ---------------------------------------------------------------------------
# Job 2: Recover stuck agent-running issues
# ---------------------------------------------------------------------------

def _issue_label_names(issue: dict) -> set[str]:
    return {lbl["name"] for lbl in issue.get("labels", [])}


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def job_recover_stuck_running(dry_run: bool = False) -> None:
    log.info("=== job: recover stuck agent-running ===")
    issues = list_open_issues(LABEL_RUNNING)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STUCK_RUNNING_HOURS)
    log.info("Found %d issue(s) with agent-running label", len(issues))

    for issue in issues:
        num = issue["number"]
        updated_at = _parse_iso(issue["updated_at"])
        age_h = (datetime.now(timezone.utc) - updated_at).total_seconds() / 3600

        if updated_at > cutoff:
            log.info("  Issue #%d last updated %.1fh ago — still within grace period", num, age_h)
            continue

        title = issue.get("title", "")
        log.warning("  Issue #%d %r stuck in agent-running for %.1fh — re-queuing",
                    num, title, age_h)

        if dry_run:
            log.info("  [dry-run] would remove agent-running, add press")
            continue

        remove_label(num, LABEL_RUNNING)
        add_label(num, PRESS_LABEL)
        log.info("  ✓ re-queued issue #%d", num)


# ---------------------------------------------------------------------------
# Job 3: Recover agent-complete issues with failed/incomplete pipeline
# ---------------------------------------------------------------------------

def _pipeline_comment_status(issue_number: int) -> str:
    """Scan the issue's comments and return 'failed', 'success', or 'unknown'.

    The orchestrator posts a single '## 🤖 Pipeline Progress' comment that it
    updates in-place.  Each stage line uses ✅ (done), ❌ (failed), or ⬜ (skipped).
    We look at that comment to determine outcome:
      - success : contains '✅ 📨 News Article PR' (last required stage)
      - failed  : contains a ❌ stage line but not the success marker
      - unknown : no pipeline progress comment found (issue may not be a press article)
    """
    try:
        comments = get_issue_comments(issue_number)
    except Exception as exc:
        log.warning("  Could not fetch comments for #%d: %s", issue_number, exc)
        return "unknown"

    for comment in comments:
        body: str = comment.get("body", "")
        if PROGRESS_HEADER not in body:
            continue
        # Found the pipeline progress comment
        if SUCCESS_STAGE in body:
            return "success"
        if STAGE_FAIL_MARKER in body:
            return "failed"
        # Progress comment exists but no ✅ final stage and no ❌ — pipeline
        # was likely killed mid-run (no stage had a chance to fail explicitly).
        return "failed"

    return "unknown"  # no pipeline progress comment — not a press pipeline issue


def job_recover_stuck_complete(dry_run: bool = False) -> None:
    log.info("=== job: recover stuck agent-complete (incomplete pipeline) ===")
    issues = list_open_issues(LABEL_COMPLETE)
    log.info("Found %d issue(s) with agent-complete label", len(issues))

    for issue in issues:
        num = issue["number"]
        title = issue.get("title", "")
        labels = _issue_label_names(issue)

        # Only care about press-related issues (have had the press label at some point).
        # We infer this by checking if any press-pipeline labels are present.
        # The press label itself is removed by the watcher when agent-running is added,
        # but the issue should still have been triaged through it.
        # We limit to issues that were open (not closed) and have agent-complete.
        # Safeguard: don't touch anything that has agent-failed (already marked).
        if LABEL_FAILED in labels:
            continue

        status = _pipeline_comment_status(num)
        log.info("  Issue #%d %r — pipeline comment status: %s", num, title, status)

        if status != "failed":
            continue

        log.warning("  Issue #%d has agent-complete but pipeline failed — re-queuing", num)

        if dry_run:
            log.info("  [dry-run] would remove agent-complete, add press")
            continue

        remove_label(num, LABEL_COMPLETE)
        add_label(num, PRESS_LABEL)
        log.info("  ✓ re-queued issue #%d", num)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="ai-it-press pipeline maintenance")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would happen without making any changes")
    parser.add_argument("--job", choices=["merge", "stuck-running", "stuck-complete", "all"],
                        default="all", help="Which job(s) to run (default: all)")
    args = parser.parse_args()

    if args.dry_run:
        log.info("*** DRY RUN — no changes will be made ***")

    try:
        if args.job in ("merge", "all"):
            job_auto_merge(dry_run=args.dry_run)
        if args.job in ("stuck-running", "all"):
            job_recover_stuck_running(dry_run=args.dry_run)
        if args.job in ("stuck-complete", "all"):
            job_recover_stuck_complete(dry_run=args.dry_run)
    except Exception as exc:
        log.error("Unhandled error: %s", exc, exc_info=True)
        sys.exit(1)

    log.info("Done.")


if __name__ == "__main__":
    main()
