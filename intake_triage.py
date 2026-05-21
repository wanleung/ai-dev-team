"""intake_triage.py — Batch intake triage for ai-software-house.

Holds incoming items (GitHub issues with triage-pending label) until a trigger
condition fires, then convenes a batch AI editorial discussion and votes
PUBLISH or SKIP on each item.

Usage:
    python intake_triage.py              # cron run: all repos in repos-enabled/
    python intake_triage.py --run        # manual trigger, ignores min_count/max_age
    python intake_triage.py --dry-run    # preview only, no write/state-changing API calls
    python intake_triage.py --config config.yaml
    python intake_triage.py --repo-config repos-available/ai-it-press.yaml  # single repo
    python intake_triage.py --repo owner/name                                # single repo
"""
from __future__ import annotations

import argparse
import copy
import logging
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from config_schema import load_config, IntakeTriageConfig
from intake_scoring import VerdictRouter, ScoredVerdict
from tracker_adapter import TrackerAdapter, TriageItem, GitHubTrackerAdapter

log = logging.getLogger("intake_triage")

_ITEM_VERDICT_RE = re.compile(
    r"ITEM\s+(\d+):\s*(PUBLISH|SKIP)[^\n]*\n(?:SCORES:[^\n]*\n)?NOTES:\s*(.+?)(?=\n\nITEM\s+\d+:|\Z)",
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
    _now: Optional[datetime] = None,
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
        now_ts = _now or datetime.now(timezone.utc)
        age = (now_ts - oldest.created_at).total_seconds() / 3600
        if age >= trigger.max_age_hours:
            return True
    if trigger.schedule:
        try:
            from croniter import croniter
            from datetime import timedelta
            now = _now or datetime.now(timezone.utc)
            # Ask: "did the schedule fire in the last 65 minutes?"
            # get_prev() is exclusive at `now` so it returns yesterday when run
            # exactly on-schedule. Instead, advance from (now - 65min) forward.
            cron = croniter(trigger.schedule, now - timedelta(minutes=65))
            if cron.get_next(datetime) <= now:
                return True
        except Exception as exc:
            log.warning("intake_triage: could not evaluate schedule '%s': %s", trigger.schedule, exc)
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
    ollama_url: str = "http://localhost:11434",
    force: bool = False,
    dry_run: bool = False,
    script_dir: Optional[Path] = None,
    dashscope_api_key: Optional[str] = None,
    dashscope_url: Optional[str] = None,
    dashscope_think: bool = False,
    dashscope_preserve_thinking: bool = False,
    dashscope_stream: bool = True,
    fallbacks: Optional[list] = None,
    mcp_servers: Optional[list] = None,
) -> dict:
    """Run one intake triage cycle.

    Fetches pending items from the tracker, evaluates trigger conditions,
    and — if triggered — runs a batch AI discussion to vote PUBLISH or SKIP
    on each item, then applies the verdicts back to the tracker.

    Args:
        cfg: Loaded ``IntakeTriageConfig``.
        repo: GitHub repository in ``owner/name`` format.
        model: LLM model identifier to pass to the DiscussionAgent.
        ollama_url: Ollama base URL (forwarded to DiscussionAgent).
        force: When True, bypass trigger conditions and process immediately.
        dry_run: When True, log the batch context but make no write/state-changing API calls.
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

    # Build search tool registry from MCP servers if available
    search_registry = None
    search_servers = [s for s in (mcp_servers or []) if s.get("name") == "google_search"]
    if search_servers:
        try:
            from tools.mcp_registry import MCPToolRegistry
            search_registry = MCPToolRegistry(search_servers)
        except Exception as exc:
            log.warning("intake_triage: Google Search MCP init failed: %s — homework search disabled", exc)

    agent = DiscussionAgent.from_file(
        config_path=str(preset_path),
        model=model,
        github_token=os.environ.get("GITHUB_TOKEN", ""),
        ollama_url=ollama_url,
        tool_registry=search_registry,
        dashscope_api_key=dashscope_api_key,
        dashscope_url=dashscope_url,
        dashscope_think=dashscope_think,
        dashscope_preserve_thinking=dashscope_preserve_thinking,
        dashscope_stream=dashscope_stream,
        fallbacks=fallbacks,
    )
    disc_result = agent.run(context=context)
    synthesis = disc_result.synthesis or ""

    verdicts = _parse_batch_verdicts(synthesis, item_count=len(batch))

    # --- Score mode: use VerdictRouter when verdict.mode == "score" ---
    verdict_config = cfg.verdict
    if verdict_config.mode == "score" and verdict_config.score_threshold is not None:
        router = VerdictRouter(
            formula=verdict_config.score_formula,
            threshold=verdict_config.score_threshold,
            score_scale=verdict_config.score_scale,
            dimensions=verdict_config.score_dimensions,
        )
        try:
            scored_verdicts: list[ScoredVerdict] = router.route(synthesis, item_count=len(batch))
        except Exception as exc:
            log.warning(
                "intake_triage: VerdictRouter.route() failed (%s); falling back to plain verdicts", exc
            )
            scored_verdicts = []

        if scored_verdicts:
            # Sort (item, scored) pairs by score descending so highest-scored items appear first
            pairs = sorted(
                zip(batch, scored_verdicts),
                key=lambda pair: pair[1].score,
                reverse=True,
            )

            approved, skipped = [], []
            for item, scored in pairs:
                if scored.verdict == "PUBLISH":
                    log.info(
                        "intake_triage: PUBLISH item %s (score=%.2f) — %s",
                        item.id, scored.score, scored.notes,
                    )
                    approved_ok = False
                    try:
                        adapter.approve(item, notes=scored.notes)
                        approved.append(item.id)
                        approved_ok = True
                    except Exception as exc:
                        log.warning("intake_triage: failed to approve item %s: %s", item.id, exc)

                    if approved_ok:
                        try:
                            adapter.add_score_label(item, scored.score)
                        except Exception as exc:
                            log.warning("intake_triage: failed to add score label to item %s: %s", item.id, exc)
                        try:
                            adapter.post_score_comment(
                                item,
                                scored.score,
                                scored.dimension_scores,
                                verdict_config.score_scale,
                            )
                        except Exception as exc:
                            log.warning("intake_triage: failed to post score comment on item %s: %s", item.id, exc)
                else:
                    log.info(
                        "intake_triage: SKIP item %s (score=%.2f) — %s",
                        item.id, scored.score, scored.notes,
                    )
                    try:
                        adapter.skip(item, reason=scored.notes)
                        skipped.append(item.id)
                    except Exception as exc:
                        log.warning("intake_triage: failed to skip item %s: %s", item.id, exc)

            log.info("intake_triage: done. approved=%d skipped=%d", len(approved), len(skipped))
            return {"fired": True, "approved": approved, "skipped": skipped}

    # --- Binary mode (or fallback when scored_verdicts is empty) ---
    approved, skipped = [], []
    for item, (verdict, notes) in zip(batch, verdicts):
        if verdict == "SKIP":
            log.info("intake_triage: SKIP item %s — %s", item.id, notes)
            try:
                adapter.skip(item, reason=notes)
                skipped.append(item.id)
            except Exception as exc:
                log.warning("intake_triage: failed to skip item %s: %s", item.id, exc)
        else:
            log.info("intake_triage: PUBLISH item %s — %s", item.id, notes)
            try:
                adapter.approve(item, notes=notes)
                approved.append(item.id)
            except Exception as exc:
                log.warning("intake_triage: failed to approve item %s: %s", item.id, exc)

    log.info("intake_triage: done. approved=%d skipped=%d", len(approved), len(skipped))
    return {"fired": True, "approved": approved, "skipped": skipped}


def _load_merged_config(config_path: Path) -> dict:
    """Load config.yaml then deep-merge config.local.yaml on top.

    Mirrors the behaviour of watcher._load_pipeline_config() so intake_triage
    respects local overrides (e.g. model, ollama_url, api keys).
    """
    cfg: dict = {}
    for name in (config_path.name, config_path.stem + ".local.yaml"):
        p = config_path.parent / name
        if p.exists():
            data = yaml.safe_load(p.read_text()) or {}
            for section, val in data.items():
                if isinstance(val, dict) and isinstance(cfg.get(section), dict):
                    cfg[section] = {**cfg.get(section, {}), **val}
                else:
                    cfg[section] = val
    return cfg


def _deep_merge_llm(global_llm: dict, repo_llm: dict) -> dict:
    """Deep-merge per-repo LLM config on top of global.  Repo values win.

    - ``model``, ``ollama_url``, and other scalars: repo replaces global if non-empty.
    - ``overrides``, ``pools``: key-by-key merge (repo agent/backend wins).
    - ``fallbacks``: repo list replaces global list entirely.
    """
    result = copy.deepcopy(global_llm)
    for key, repo_val in (repo_llm or {}).items():
        if key in ("overrides", "pools") and isinstance(repo_val, dict):
            merged = dict(result.get(key) or {})
            merged.update(repo_val)
            result[key] = merged
        else:
            if repo_val is not None and repo_val != "" and repo_val != []:
                result[key] = repo_val
    return result


def _merge_intake_cfg(base: "IntakeTriageConfig", override: dict) -> "IntakeTriageConfig":
    """Return a new IntakeTriageConfig with per-repo override dict merged in.

    Nested dicts (trigger, batch, verdict, discussion, labels) are merged
    key-by-key so partial overrides work (e.g. only changing scope or
    trigger.min_count without repeating the full block).
    """
    if not override:
        return base
    base_dict = base.model_dump()
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(base_dict.get(key), dict):
            base_dict[key] = {**base_dict[key], **val}
        elif val is not None:
            base_dict[key] = val
    return IntakeTriageConfig.model_validate(base_dict)


def _load_repos_enabled(config_path: Path) -> list[tuple[str, dict, dict]]:
    """Return ``(tracker_repo, repo_llm_cfg, repo_intake_cfg)`` triples from repos-enabled/*.yaml.

    Broken symlinks and entries without tracker_repo are logged and skipped.
    """
    repos_enabled = config_path.parent / "repos-enabled"
    repos: list[tuple[str, dict, dict]] = []
    if not repos_enabled.is_dir():
        return repos
    for entry in sorted(repos_enabled.iterdir()):
        if entry.suffix != ".yaml":
            continue
        if not entry.exists():  # broken symlink
            log.warning("Broken symlink in repos-enabled/: %s — skipping", entry.name)
            continue
        data = yaml.safe_load(entry.read_text()) or {}
        repo = data.get("tracker_repo", "")
        if not repo:
            log.warning("repos-enabled/%s has no tracker_repo — skipping", entry.name)
            continue
        if data.get("enabled") is False:
            log.debug("repos-enabled/%s is disabled — skipping", entry.name)
            continue
        repos.append((repo, data.get("llm") or {}, data.get("intake_triage") or {}))
    return repos


@contextmanager
def _pidfile_lock(lock_path: Path):
    """Exclusive process lock using a PID file.

    Raises SystemExit(0) immediately if another instance is already running.
    The lock file is removed on clean exit or exception.
    """
    if lock_path.exists():
        try:
            pid = int(lock_path.read_text().strip())
            # Check if that PID is still alive
            os.kill(pid, 0)
            log.warning("intake_triage: another instance is running (pid %d), exiting", pid)
            sys.exit(0)
        except (ValueError, ProcessLookupError, PermissionError):
            # Stale lock — remove it
            log.debug("intake_triage: removing stale lock file %s", lock_path)
            lock_path.unlink(missing_ok=True)

    lock_path.write_text(str(os.getpid()))
    log.debug("intake_triage: acquired lock %s (pid %d)", lock_path, os.getpid())
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)
        log.debug("intake_triage: released lock %s", lock_path)


def main() -> None:
    """Entry point for the CLI runner.

    Parses arguments, loads configuration, and delegates to :func:`run`.
    """
    parser = argparse.ArgumentParser(description="Batch intake triage runner")
    parser.add_argument("--run", action="store_true", help="Force run ignoring trigger conditions")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no write/state-changing API calls")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--repo", default=None, help="GitHub repo (owner/name), overrides config")
    parser.add_argument(
        "--repo-config",
        default=None,
        metavar="REPO_YAML",
        help="Path to a repos-available/*.yaml file; reads tracker_repo from it",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    cfg_path = Path(args.config)
    if not cfg_path.is_file():
        print(f"ERROR: config file not found: {cfg_path}", file=sys.stderr)
        sys.exit(1)

    lock_path = cfg_path.parent / ".intake_triage.lock"
    with _pidfile_lock(lock_path):
        _main_locked(args, cfg_path)


def _main_locked(args, cfg_path: Path) -> None:
    """Main logic — runs only when the process lock is held."""
    # Load config.yaml merged with config.local.yaml (local wins)
    merged_cfg = _load_merged_config(cfg_path)
    app_cfg = load_config(str(cfg_path))  # for typed access (intake_triage, github sections)
    intake_cfg = app_cfg.intake_triage

    if not intake_cfg.enabled and not args.run:
        log.info("intake_triage: disabled in config (use --run to force)")
        return

    # Install LLM pool from merged config (respects pools: section in config.local.yaml)
    try:
        from watcher import install_llm_pool_from_config
        install_llm_pool_from_config(merged_cfg)
    except Exception as exc:  # non-fatal — pool defaults apply
        log.debug("intake_triage: could not install LLM pool: %s", exc)

    global_llm = merged_cfg.get("llm") or {}

    # ── Resolve target repos ──────────────────────────────────────────────────
    # Each entry is (tracker_repo, repo_llm_override, repo_intake_override)
    repo_entries: list[tuple[str, dict, dict]] = []

    if args.repo:
        repo_entries = [(args.repo, {}, {})]
    elif args.repo_config:
        repo_cfg_path = Path(args.repo_config)
        if not repo_cfg_path.is_file():
            print(f"ERROR: repo config file not found: {repo_cfg_path}", file=sys.stderr)
            sys.exit(1)
        data = yaml.safe_load(repo_cfg_path.read_text()) or {}
        repo = data.get("tracker_repo", "")
        if not repo:
            print(f"ERROR: no tracker_repo key found in {repo_cfg_path}", file=sys.stderr)
            sys.exit(1)
        log.info("intake_triage: using tracker_repo=%s from %s", repo, repo_cfg_path)
        repo_entries = [(repo, data.get("llm") or {}, data.get("intake_triage") or {})]
    else:
        repo_entries = _load_repos_enabled(cfg_path)
        if not repo_entries:
            fallback = app_cfg.github.repo if app_cfg.github else ""
            if fallback:
                log.info("intake_triage: no repos-enabled entries, falling back to github.repo=%s", fallback)
                repo_entries = [(fallback, {}, {})]
            else:
                print(
                    "ERROR: no repos found — add repos to repos-enabled/, use --repo-config, or set github.repo in config.yaml",
                    file=sys.stderr,
                )
                sys.exit(1)

    # ── Run triage for each repo (parallel) ──────────────────────────────────
    errors: list[str] = []
    mcp_servers = (merged_cfg.get("mcp") or {}).get("servers") or []

    def _run_repo(entry: tuple) -> None:
        repo, repo_llm, repo_intake = entry
        effective_llm = _deep_merge_llm(global_llm, repo_llm)
        model = effective_llm.get("model") or "gpt-4.1"
        ollama_url = effective_llm.get("ollama_url") or "http://localhost:11434"
        effective_intake = _merge_intake_cfg(intake_cfg, repo_intake)
        log.info("intake_triage: processing repo %s (model=%s)", repo, model)
        run(
            effective_intake,
            repo=repo,
            model=model,
            ollama_url=ollama_url,
            force=args.run,
            dry_run=args.dry_run,
            dashscope_api_key=effective_llm.get("dashscope_api_key"),
            dashscope_url=effective_llm.get("dashscope_url"),
            dashscope_think=effective_llm.get("dashscope_think", False),
            dashscope_preserve_thinking=effective_llm.get("dashscope_preserve_thinking", False),
            dashscope_stream=effective_llm.get("dashscope_stream", True),
            fallbacks=effective_llm.get("fallbacks") or None,
            mcp_servers=mcp_servers,
        )

    if len(repo_entries) == 1:
        # Single repo — run directly to keep tracebacks clean
        repo, repo_llm, repo_intake = repo_entries[0]
        try:
            _run_repo(repo_entries[0])
        except Exception as exc:
            log.error("intake_triage: repo %s failed: %s", repo, exc)
            errors.append(repo)
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        max_workers = min(len(repo_entries), 4)  # cap at 4 parallel repos
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="intake") as pool:
            futures = {pool.submit(_run_repo, entry): entry[0] for entry in repo_entries}
            for fut in as_completed(futures):
                repo = futures[fut]
                try:
                    fut.result()
                except Exception as exc:
                    log.error("intake_triage: repo %s failed: %s", repo, exc)
                    errors.append(repo)

    if errors:
        print(f"ERROR: intake_triage failed for repo(s): {', '.join(errors)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
