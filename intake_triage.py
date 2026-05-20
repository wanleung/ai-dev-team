"""intake_triage.py — Batch intake triage for ai-software-house.

Holds incoming items (GitHub issues with triage-pending label) until a trigger
condition fires, then convenes a batch AI editorial discussion and votes
PUBLISH or SKIP on each item.

Usage:
    python intake_triage.py              # normal cron run (respects trigger conditions)
    python intake_triage.py --run        # manual trigger, ignores min_count/max_age
    python intake_triage.py --dry-run    # preview only, no API calls
    python intake_triage.py --config config.yaml
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config_schema import load_config, IntakeTriageConfig
from tracker_adapter import TrackerAdapter, TriageItem, GitHubTrackerAdapter

log = logging.getLogger("intake_triage")

_ITEM_VERDICT_RE = re.compile(
    r"ITEM\s+(\d+):\s*(PUBLISH|SKIP)\s*\nNOTES:\s*(.+?)(?=\n\nITEM\s+\d+:|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_ITEM_VERDICT_NO_NOTES_RE = re.compile(
    r"ITEM\s+(\d+):\s*(PUBLISH|SKIP)",
    re.IGNORECASE,
)


def _parse_batch_verdicts(text: str, item_count: int) -> list[tuple[str, str]]:
    """Parse moderator synthesis into per-item (verdict, notes) tuples.

    Fail-open: any unparseable or missing item defaults to ("PUBLISH", "").
    """
    results: dict[int, tuple[str, str]] = {}

    # Try to extract NOTES lines first
    for m in _ITEM_VERDICT_RE.finditer(text):
        idx = int(m.group(1))
        verdict = m.group(2).upper()
        notes = m.group(3).strip().splitlines()[0].strip()
        results[idx] = (verdict, notes)

    # Fall back to verdict-only lines for items not yet parsed
    for m in _ITEM_VERDICT_NO_NOTES_RE.finditer(text):
        idx = int(m.group(1))
        if idx not in results:
            results[idx] = (m.group(2).upper(), "")

    return [(results.get(i, ("PUBLISH", ""))) for i in range(1, item_count + 1)]


def _build_batch_context(
    items: list[TriageItem],
    scope: str,
    preview_chars: int = 300,
) -> str:
    """Build the context string for the batch discussion.

    Args:
        items: List of pending triage items to include.
        scope: Editorial scope description for the AI moderator.
        preview_chars: Maximum characters of body text to include per item.

    Returns:
        Formatted multi-line string ready to pass as context to DiscussionAgent.
    """
    lines = [
        "## Pending Items for Editorial Review",
        f"Triage scope: {scope}",
        f"Item count: {len(items)}",
        "",
    ]
    for i, item in enumerate(items, 1):
        preview = item.body[:preview_chars]
        if len(item.body) > preview_chars:
            preview += "..."
        lines += [
            f"--- ITEM {i} ---",
            f"Title: {item.title}",
            f"URL: {item.url}",
            f"Summary: {preview}",
            "",
        ]
    return "\n".join(lines)


def _should_fire(
    cfg: IntakeTriageConfig,
    items: list[TriageItem],
    force: bool = False,
) -> bool:
    """Return True if the triage session should run now.

    Trigger conditions (any one is sufficient):
    - ``force=True``: manual override, always fires when items are present.
    - ``trigger.min_count``: fires when pending item count reaches the threshold.
    - ``trigger.max_age_hours``: fires when the oldest item exceeds the age limit.
    - ``trigger.schedule``: fires if the cron expression matched within the last
      65 minutes (covers a standard once-per-hour cron window).

    Args:
        cfg: Loaded ``IntakeTriageConfig`` with trigger settings.
        items: Current list of pending triage items.
        force: When True, skip condition evaluation and fire immediately.

    Returns:
        True if the triage batch should be processed now, False otherwise.
    """
    if not items:
        return False
    if force:
        return True
    trigger = cfg.trigger
    if trigger.min_count is not None and len(items) >= trigger.min_count:
        return True
    if trigger.max_age_hours is not None and items:
        oldest = min(items, key=lambda x: x.created_at)
        age = (datetime.now(timezone.utc) - oldest.created_at).total_seconds() / 3600
        if age >= trigger.max_age_hours:
            return True
    if trigger.schedule:
        try:
            from croniter import croniter
            from datetime import timedelta
            now = datetime.now(timezone.utc)
            # Ask: "did the schedule fire in the last 65 minutes?"
            # get_prev() is exclusive at `now` so it returns yesterday when run
            # exactly on-schedule. Instead, advance from (now - 65min) forward.
            cron = croniter(trigger.schedule, now - timedelta(minutes=65))
            if cron.get_next(datetime) <= now:
                return True
        except Exception:
            log.warning("intake_triage: could not evaluate schedule '%s'", trigger.schedule)
    return False


def _make_adapter(cfg: IntakeTriageConfig, repo: str) -> TrackerAdapter:
    """Instantiate the correct TrackerAdapter implementation for the config.

    Args:
        cfg: Loaded ``IntakeTriageConfig``.
        repo: GitHub repository in ``owner/name`` format.

    Returns:
        A concrete ``TrackerAdapter`` instance.

    Raises:
        NotImplementedError: If the configured tracker type is not supported.
    """
    if cfg.tracker != "github":
        raise NotImplementedError(f"Tracker '{cfg.tracker}' not yet implemented")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise EnvironmentError(
            "GITHUB_TOKEN environment variable is not set. "
            "Set it before running intake_triage."
        )
    if "/" not in repo:
        raise ValueError(f"repo must be in 'owner/name' format, got: {repo!r}")
    return GitHubTrackerAdapter(
        repo=repo,
        token=token,
        pending_label=cfg.labels.get("pending", "triage-pending"),
        approved_label=cfg.labels.get("approved", "triage-approved"),
        skipped_label=cfg.labels.get("skipped", "triage-skipped"),
        trigger_label=cfg.labels.get("trigger", "press"),
    )


def run(
    cfg: IntakeTriageConfig,
    repo: str,
    model: str = "gpt-4.1",
    force: bool = False,
    dry_run: bool = False,
    script_dir: Optional[Path] = None,
) -> dict:
    """Run one intake triage cycle.

    Fetches pending items from the tracker, evaluates trigger conditions,
    and — if triggered — runs a batch AI discussion to vote PUBLISH or SKIP
    on each item, then applies the verdicts back to the tracker.

    Args:
        cfg: Loaded ``IntakeTriageConfig``.
        repo: GitHub repository in ``owner/name`` format.
        model: LLM model identifier to pass to the DiscussionAgent.
        force: When True, bypass trigger conditions and process immediately.
        dry_run: When True, log the batch context but make no API calls.
        script_dir: Base directory for locating discussion preset files.
            Defaults to the directory containing this script.

    Returns:
        A summary dict with keys: ``fired``, and either
        ``{"approved": [...], "skipped": [...]}`` or
        ``{"dry_run": True, "batch_size": N}`` or
        ``{"pending": N}``.
    """
    if script_dir is None:
        script_dir = Path(__file__).parent

    adapter = _make_adapter(cfg, repo)
    items = adapter.list_pending()
    log.info("intake_triage: %d item(s) pending", len(items))

    if not _should_fire(cfg, items, force=force):
        log.info("intake_triage: trigger conditions not met, skipping")
        return {"fired": False, "pending": len(items)}

    # Slice to max_batch_size, oldest first
    max_size = cfg.batch.max_size
    items.sort(key=lambda x: x.created_at)
    batch = items[:max_size]
    log.info("intake_triage: processing batch of %d item(s)", len(batch))

    # Get triage scope from config
    scope = cfg.scope

    context = _build_batch_context(batch, scope=scope, preview_chars=cfg.batch.body_preview_chars)

    if dry_run:
        log.info("intake_triage: --dry-run, would process %d items:\n%s", len(batch), context)
        return {"fired": True, "dry_run": True, "batch_size": len(batch)}

    # Run discussion
    preset_path = script_dir / cfg.discussion.get("preset", "discussions/intake-triage.yaml")
    # Deferred to avoid loading the full agents package during config-only import paths.
    from agents.discussion_agent import DiscussionAgent
    agent = DiscussionAgent.from_file(
        config_path=str(preset_path),
        model=model,
        github_token=os.environ.get("GITHUB_TOKEN", ""),
    )
    disc_result = agent.run(context=context)
    synthesis = disc_result.synthesis or ""

    verdicts = _parse_batch_verdicts(synthesis, item_count=len(batch))

    approved, skipped = [], []
    for item, (verdict, notes) in zip(batch, verdicts):
        if verdict == "SKIP":
            log.info("intake_triage: SKIP item %s — %s", item.id, notes)
            try:
                adapter.skip(item, reason=notes)
            except Exception as exc:
                log.warning("intake_triage: failed to skip item %s: %s", item.id, exc)
            skipped.append(item.id)
        else:
            log.info("intake_triage: PUBLISH item %s — %s", item.id, notes)
            try:
                adapter.approve(item, notes=notes)
            except Exception as exc:
                log.warning("intake_triage: failed to approve item %s: %s", item.id, exc)
            approved.append(item.id)

    log.info("intake_triage: done. approved=%d skipped=%d", len(approved), len(skipped))
    return {"fired": True, "approved": approved, "skipped": skipped}


def main() -> None:
    """Entry point for the CLI runner.

    Parses arguments, loads configuration, and delegates to :func:`run`.
    """
    parser = argparse.ArgumentParser(description="Batch intake triage runner")
    parser.add_argument("--run", action="store_true", help="Force run ignoring trigger conditions")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no API calls")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--repo", default=None, help="GitHub repo (owner/name), overrides config")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    cfg_path = Path(args.config)
    if not cfg_path.is_file():
        print(f"ERROR: config file not found: {cfg_path}", file=sys.stderr)
        sys.exit(1)

    app_cfg = load_config(str(cfg_path))
    intake_cfg = app_cfg.intake_triage

    if not intake_cfg.enabled and not args.run:
        log.info("intake_triage: disabled in config (use --run to force)")
        return

    repo = args.repo or (app_cfg.github.repo if app_cfg.github else "")
    if not repo:
        print("ERROR: no repo configured (set github.repo in config.yaml or use --repo)", file=sys.stderr)
        sys.exit(1)

    model = app_cfg.llm.model
    run(intake_cfg, repo=repo, model=model, force=args.run, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
