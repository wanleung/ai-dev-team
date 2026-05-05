# Repos Apache2-Style Config Split — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `repos.yaml` into individual per-repo files in `repos-available/`, enable/disable via symlinks in `repos-enabled/`, managed by `python watcher.py repo enable|disable|list`.

**Architecture:** A new `load_watcher_config(config_path)` helper in `watcher.py` replaces the two bare `yaml.safe_load` calls. It reads the root config, globs `repos-enabled/*.yaml`, merges watcher lists, and returns a unified config dict. Three new CLI sub-commands (`repo enable`, `repo disable`, `repo list`) are added as a new `repo` argparse sub-parser. All changes are backward-compatible — a `repos.yaml` with a `watchers:` list and no `repos-enabled/` directory works unchanged.

**Tech Stack:** Python 3.10+, PyYAML, pathlib, argparse, os.symlink

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `watcher.py` | Modify | Add `load_watcher_config()`, update `watch()` and `main()` to use it, add `repo` sub-commands |
| `tests/test_watcher_config.py` | Create | Tests for `load_watcher_config()` and `repo` sub-commands |
| `repos-available/` | Create dir | Example/migrated per-repo YAML files |

---

## Task 1: Extract `load_watcher_config()` helper

**Files:**
- Modify: `watcher.py` — add `load_watcher_config()` between `_load_pipeline_config()` (line ~227) and `install_llm_pool_from_config()` (line ~248)
- Create: `tests/test_watcher_config.py`

The new function replaces the two existing `yaml.safe_load` calls in `watch()` (line 606) and `main()` (line 822). It:
1. Loads root `repos.yaml` → `config`
2. Globs `{config_path.parent}/repos-enabled/*.yaml`
3. For each enabled file: loads YAML, pops `settings` key, appends the watcher dict to `config["watchers"]`
4. Warns (via `logging.getLogger`) on broken symlinks (target missing) — skips them
5. Warns and the enabled-dir entry wins on duplicate `tracker_repo`
6. Returns the merged `config` dict

- [ ] **Step 1: Write the failing tests**

Create `tests/test_watcher_config.py`:

```python
"""tests/test_watcher_config.py — Tests for load_watcher_config() and repo sub-commands."""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest
import yaml

import watcher
from watcher import load_watcher_config


# ── load_watcher_config ───────────────────────────────────────────────────────

def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


def test_legacy_only(tmp_path):
    """repos.yaml with watchers: list, no repos-enabled/ — unchanged behaviour."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, """
        watchers:
          - tracker_repo: owner/alpha
            enabled: true
        settings:
          max_parallel: 2
    """)
    result = load_watcher_config(cfg)
    assert len(result["watchers"]) == 1
    assert result["watchers"][0]["tracker_repo"] == "owner/alpha"
    assert result["settings"]["max_parallel"] == 2


def test_repos_enabled_only(tmp_path):
    """repos-enabled/ symlinks with no legacy watchers: list."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, "settings:\n  max_parallel: 1\n")

    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "my-repo.yaml", """
        tracker_repo: owner/my-repo
        feature_label: feature-request
        enabled: true
    """)

    enabled = tmp_path / "repos-enabled"
    enabled.mkdir()
    os.symlink(avail / "my-repo.yaml", enabled / "my-repo.yaml")

    result = load_watcher_config(cfg)
    assert len(result["watchers"]) == 1
    assert result["watchers"][0]["tracker_repo"] == "owner/my-repo"


def test_mixed_legacy_and_enabled(tmp_path):
    """Legacy watchers: entries merged with repos-enabled/ entries."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, """
        watchers:
          - tracker_repo: owner/legacy
            enabled: true
        settings:
          max_parallel: 3
    """)

    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "new-repo.yaml", """
        tracker_repo: owner/new-repo
        feature_label: feature-request
    """)
    enabled = tmp_path / "repos-enabled"
    enabled.mkdir()
    os.symlink(avail / "new-repo.yaml", enabled / "new-repo.yaml")

    result = load_watcher_config(cfg)
    repos = [w["tracker_repo"] for w in result["watchers"]]
    assert "owner/legacy" in repos
    assert "owner/new-repo" in repos
    assert len(repos) == 2


def test_per_watcher_settings_stored(tmp_path):
    """Per-watcher settings: block is stored on the watcher dict as _settings."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, "settings:\n  model: gpt-4.1\n")

    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "fast-repo.yaml", """
        tracker_repo: owner/fast-repo
        feature_label: feature-request
        settings:
          model: gpt-4.1-mini
          num_engineers: 1
    """)
    enabled = tmp_path / "repos-enabled"
    enabled.mkdir()
    os.symlink(avail / "fast-repo.yaml", enabled / "fast-repo.yaml")

    result = load_watcher_config(cfg)
    w = result["watchers"][0]
    assert w["_settings"]["model"] == "gpt-4.1-mini"
    assert w["_settings"]["num_engineers"] == 1
    # settings: key must be removed from the watcher dict itself
    assert "settings" not in w


def test_broken_symlink_skipped(tmp_path):
    """Broken symlinks in repos-enabled/ are skipped with a warning."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, "settings:\n  max_parallel: 1\n")

    enabled = tmp_path / "repos-enabled"
    enabled.mkdir()
    # Symlink pointing to a non-existent file
    os.symlink(tmp_path / "repos-available" / "ghost.yaml", enabled / "ghost.yaml")

    result = load_watcher_config(cfg)
    assert result["watchers"] == []


def test_duplicate_tracker_repo_enabled_wins(tmp_path):
    """If same tracker_repo appears in both legacy and repos-enabled/, enabled wins."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, """
        watchers:
          - tracker_repo: owner/shared
            feature_label: old-label
            enabled: true
        settings:
          max_parallel: 1
    """)

    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "shared.yaml", """
        tracker_repo: owner/shared
        feature_label: new-label
        enabled: true
    """)
    enabled = tmp_path / "repos-enabled"
    enabled.mkdir()
    os.symlink(avail / "shared.yaml", enabled / "shared.yaml")

    result = load_watcher_config(cfg)
    repos = [w["tracker_repo"] for w in result["watchers"]]
    assert repos.count("owner/shared") == 1
    w = next(w for w in result["watchers"] if w["tracker_repo"] == "owner/shared")
    assert w["feature_label"] == "new-label"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house && source venv/bin/activate
pytest tests/test_watcher_config.py -v 2>&1 | head -30
```

Expected: `ImportError: cannot import name 'load_watcher_config' from 'watcher'`

- [ ] **Step 3: Implement `load_watcher_config()`**

Insert this function in `watcher.py` after `_load_pipeline_config()` (around line 247):

```python
def load_watcher_config(config_path: Path) -> dict:
    """Load and merge watcher config from repos.yaml + repos-enabled/*.yaml.

    Returns a config dict with a unified ``watchers`` list.  Per-watcher
    ``settings:`` blocks are stripped from the watcher entry and stored as
    ``_settings`` so callers can apply per-watcher overrides.
    """
    _log = logging.getLogger(__name__)

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    legacy_watchers: list[dict] = list(config.get("watchers") or [])
    seen: dict[str, int] = {}  # tracker_repo → index in merged list

    for w in legacy_watchers:
        repo = w.get("tracker_repo", "")
        if repo:
            seen[repo] = legacy_watchers.index(w)

    repos_enabled = config_path.parent / "repos-enabled"
    if repos_enabled.is_dir():
        for entry in sorted(repos_enabled.iterdir()):
            if not entry.suffix == ".yaml":
                continue
            if not entry.exists():  # broken symlink
                _log.warning("Broken symlink in repos-enabled/: %s — skipping", entry.name)
                continue
            with open(entry, encoding="utf-8") as f:
                watcher_dict = yaml.safe_load(f) or {}
            per_settings = watcher_dict.pop("settings", None)
            if per_settings:
                watcher_dict["_settings"] = per_settings
            repo = watcher_dict.get("tracker_repo", "")
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_watcher_config.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add watcher.py tests/test_watcher_config.py
git commit -m "feat: add load_watcher_config() with repos-available/repos-enabled support"
```

---

## Task 2: Wire `load_watcher_config()` into `watch()` and `main()`

**Files:**
- Modify: `watcher.py` — update `watch()` (line ~604) and `main()` (line ~821)

Replace the two bare `yaml.safe_load` calls with `load_watcher_config()`. Also update `watch()` to apply per-watcher `_settings` overrides when dispatching.

- [ ] **Step 1: Write failing test for per-watcher settings override**

Add to `tests/test_watcher_config.py`:

```python
def test_watch_uses_per_watcher_model(tmp_path, monkeypatch):
    """watch() dispatches with per-watcher model override from _settings."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, """
        settings:
          model: gpt-4.1
          num_engineers: 2
          max_parallel: 1
          log_dir: logs/watcher
    """)

    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "cheap-repo.yaml", """
        tracker_repo: owner/cheap-repo
        feature_label: feature-request
        enabled: true
        settings:
          model: gpt-4.1-mini
          num_engineers: 1
    """)
    enabled = tmp_path / "repos-enabled"
    enabled.mkdir()
    os.symlink(avail / "cheap-repo.yaml", enabled / "cheap-repo.yaml")

    dispatched = []

    def fake_get_open_issues(repo, label):
        return [{"number": 1, "title": "T", "body": "", "labels": [{"name": label if isinstance(label, str) else label[0]}]}]

    def fake_dispatch(**kwargs):
        dispatched.append(kwargs)

    monkeypatch.setattr("watcher.get_open_issues", fake_get_open_issues)
    monkeypatch.setattr("watcher._dispatch", fake_dispatch)
    monkeypatch.setattr("watcher.ensure_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.add_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.check_waiting_issues", lambda *a, **kw: None)
    monkeypatch.setattr("watcher._process_resume_queue", lambda *a, **kw: [])
    monkeypatch.setattr("watcher._load_pipeline_config", lambda: {})
    (tmp_path / "logs" / "watcher").mkdir(parents=True, exist_ok=True)

    import logging
    logger = logging.getLogger("test")
    logger.addHandler(logging.NullHandler())

    watcher.watch(cfg, dry_run=False, logger=logger)

    assert len(dispatched) == 1
    assert dispatched[0]["model"] == "gpt-4.1-mini"
    assert dispatched[0]["num_engineers"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_watcher_config.py::test_watch_uses_per_watcher_model -v
```

Expected: FAIL — `watch()` still reads `yaml.safe_load` directly and ignores `_settings`.

- [ ] **Step 3: Update `watch()`**

In `watcher.py`, replace the `watch()` function's config loading section (lines ~604–615):

```python
# OLD:
#     with open(config_path, encoding="utf-8") as f:
#         config = yaml.safe_load(f)
#     settings   = config.get("settings", {})
#     ...
#     watchers = config.get("watchers", [])

# NEW — replace those lines with:
    config = load_watcher_config(config_path)

    global_settings = config.get("settings", {})
    max_parallel  = global_settings.get("max_parallel", 3)
    log_dir       = Path(config_path.parent / global_settings.get("log_dir", "logs/watcher"))
    watchers      = config.get("watchers", [])
```

Then, in the `for w in watchers:` loop inside `watch()` (around line 640), add per-watcher settings override right after reading `w`:

```python
    for w in watchers:
        if not w.get("enabled", True):
            continue
        # Apply per-watcher settings overrides (set by load_watcher_config)
        _w_settings = {**global_settings, **w.get("_settings", {})}
        model         = _w_settings.get("model", "gpt-4.1")
        num_engineers = _w_settings.get("num_engineers", 2)

        tracker_repo   = w["tracker_repo"]
        ...
```

Note: remove the `model` and `num_engineers` lines that currently appear before the loop (they are now per-watcher), but keep `max_parallel` and `log_dir` from `global_settings`.

- [ ] **Step 4: Update `main()` to use `load_watcher_config()`**

In `main()`, replace the bare `yaml.safe_load` block (lines ~821–823):

```python
# OLD:
#     with open(config_path, encoding="utf-8") as f:
#         raw = yaml.safe_load(f)
#     log_dir = Path(config_path.parent / raw.get("settings", {}).get("log_dir", "logs/watcher"))

# NEW:
    raw = load_watcher_config(config_path)
    log_dir = Path(config_path.parent / raw.get("settings", {}).get("log_dir", "logs/watcher"))
```

- [ ] **Step 5: Run all watcher tests**

```bash
pytest tests/test_watcher_config.py tests/test_watcher.py -v 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add watcher.py tests/test_watcher_config.py
git commit -m "feat: wire load_watcher_config into watch() and main(); apply per-watcher settings"
```

---

## Task 3: Add `repo enable/disable/list` CLI sub-commands

**Files:**
- Modify: `watcher.py` — add `cmd_repo_*` functions + update `_build_arg_parser()` and `main()`
- Modify: `tests/test_watcher_config.py` — add CLI sub-command tests

- [ ] **Step 1: Write failing tests for CLI sub-commands**

Add to `tests/test_watcher_config.py`:

```python
# ── repo sub-commands ─────────────────────────────────────────────────────────

from watcher import cmd_repo_enable, cmd_repo_disable, cmd_repo_list


def test_repo_enable_creates_symlink(tmp_path):
    """repo enable <name> creates a symlink repos-enabled/<name>.yaml."""
    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "mcp-tfl.yaml", "tracker_repo: owner/mcp-tfl\n")

    cmd_repo_enable(tmp_path, "mcp-tfl")

    link = tmp_path / "repos-enabled" / "mcp-tfl.yaml"
    assert link.is_symlink()
    assert link.resolve() == (avail / "mcp-tfl.yaml").resolve()


def test_repo_enable_creates_repos_enabled_dir(tmp_path):
    """repo enable creates repos-enabled/ if it doesn't exist."""
    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "my-app.yaml", "tracker_repo: owner/my-app\n")

    assert not (tmp_path / "repos-enabled").exists()
    cmd_repo_enable(tmp_path, "my-app")
    assert (tmp_path / "repos-enabled").is_dir()


def test_repo_enable_error_not_found(tmp_path):
    """repo enable <name> raises SystemExit if the file doesn't exist."""
    (tmp_path / "repos-available").mkdir()
    with pytest.raises(SystemExit):
        cmd_repo_enable(tmp_path, "nonexistent")


def test_repo_enable_error_already_enabled(tmp_path):
    """repo enable raises SystemExit if already enabled."""
    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "alpha.yaml", "tracker_repo: owner/alpha\n")
    cmd_repo_enable(tmp_path, "alpha")
    with pytest.raises(SystemExit):
        cmd_repo_enable(tmp_path, "alpha")


def test_repo_disable_removes_symlink(tmp_path):
    """repo disable removes the symlink."""
    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "beta.yaml", "tracker_repo: owner/beta\n")
    cmd_repo_enable(tmp_path, "beta")
    assert (tmp_path / "repos-enabled" / "beta.yaml").exists()

    cmd_repo_disable(tmp_path, "beta")
    assert not (tmp_path / "repos-enabled" / "beta.yaml").exists()
    # source file must still be there
    assert (avail / "beta.yaml").exists()


def test_repo_disable_error_not_enabled(tmp_path):
    """repo disable raises SystemExit if not currently enabled."""
    (tmp_path / "repos-available").mkdir()
    (tmp_path / "repos-enabled").mkdir()
    with pytest.raises(SystemExit):
        cmd_repo_disable(tmp_path, "unknown")


def test_repo_list_output(tmp_path, capsys):
    """repo list prints [enabled] / [disabled] status."""
    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "repo-a.yaml", "tracker_repo: owner/a\n")
    _write(avail / "repo-b.yaml", "tracker_repo: owner/b\n")
    cmd_repo_enable(tmp_path, "repo-a")

    cmd_repo_list(tmp_path)
    out = capsys.readouterr().out
    assert "repo-a" in out and "enabled" in out
    assert "repo-b" in out and "disabled" in out


def test_repo_list_empty(tmp_path, capsys):
    """repo list on empty repos-available/ prints a helpful message."""
    (tmp_path / "repos-available").mkdir()
    cmd_repo_list(tmp_path)
    out = capsys.readouterr().out
    assert "No repos found" in out
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_watcher_config.py -k "repo" -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'cmd_repo_enable'`

- [ ] **Step 3: Implement `cmd_repo_enable`, `cmd_repo_disable`, `cmd_repo_list`**

Add these three functions to `watcher.py` (after `load_watcher_config()`):

```python
def cmd_repo_enable(base_dir: Path, name: str) -> None:
    """Enable a watcher by creating a symlink in repos-enabled/."""
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
        print("No repos-available/ directory found.")
        return

    files = sorted(avail_dir.glob("*.yaml"))
    if not files:
        print("No repos found in repos-available/")
        return

    enabled_dir = base_dir / "repos-enabled"
    for f in files:
        link = enabled_dir / f.name
        status = "[enabled] " if (link.exists() or link.is_symlink()) and link.exists() else "[disabled]"
        print(f"  {status}  {f.stem}")
```

- [ ] **Step 4: Add `repo` sub-parser to `_build_arg_parser()`**

In `_build_arg_parser()` (line ~762), add sub-commands after the existing `add_argument` calls:

```python
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
```

- [ ] **Step 5: Dispatch `repo` sub-commands in `main()`**

At the top of `main()`, after `args = parser.parse_args()`, add:

```python
    # ── repo sub-commands ────────────────────────────────────────────────
    if args.command == "repo":
        config_path = Path(args.config).resolve()
        base_dir = config_path.parent
        if args.repo_command == "enable":
            cmd_repo_enable(base_dir, args.name)
        elif args.repo_command == "disable":
            cmd_repo_disable(base_dir, args.name)
        elif args.repo_command == "list":
            cmd_repo_list(base_dir)
        else:
            print("Usage: watcher.py repo enable|disable|list [name]")
        return
```

- [ ] **Step 6: Run all watcher tests**

```bash
pytest tests/test_watcher_config.py tests/test_watcher.py -v 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add watcher.py tests/test_watcher_config.py
git commit -m "feat: add repo enable/disable/list CLI sub-commands"
```

---

## Task 4: Create `repos-available/` with migrated entries + update docs

**Files:**
- Create: `repos-available/mcp-tfl.yaml`, `repos-available/custom-cms.yaml`, `repos-available/mybooking.yaml`
- Modify: `repos.yaml` — comment out migrated entries (leave them so the file remains valid)
- Modify: `README.md` or `docs/operations-guide.md` — add section on repos-available/repos-enabled

- [ ] **Step 1: Create `repos-available/` directory and per-repo files**

```bash
mkdir -p repos-available
```

Create `repos-available/mcp-tfl.yaml`:
```yaml
# repos-available/mcp-tfl.yaml
tracker_repo: wanleung/mcp-tfl
default_target: ~
feature_label:
  - feature-request
  - ai-build
  - enhancement
  - ai-feature
bug_label:
  - bug
  - ai-fix
doc_label: documentation
enabled: true
```

Create `repos-available/custom-cms.yaml`:
```yaml
# repos-available/custom-cms.yaml
tracker_repo: wanleung/custom-cms
default_target: ~
feature_label:
  - feature-request
  - ai-build
  - enhancement
  - ai-feature
bug_label:
  - bug
  - ai-fix
doc_label: documentation
enabled: true
```

Create `repos-available/mybooking.yaml`:
```yaml
# repos-available/mybooking.yaml
tracker_repo: wanleung/mybooking
default_target: ~
feature_label:
  - feature-request
  - ai-build
  - enhancement
  - ai-feature
bug_label:
  - bug
  - ai-fix
doc_label: documentation
enabled: true
```

- [ ] **Step 2: Enable the migrated repos**

```bash
python watcher.py repo enable mcp-tfl
python watcher.py repo enable custom-cms
python watcher.py repo enable mybooking
python watcher.py repo list
```

Expected output:
```
  [enabled]   custom-cms
  [enabled]   mcp-tfl
  [enabled]   mybooking
```

- [ ] **Step 3: Update `repos.yaml` — remove migrated entries**

Edit `repos.yaml` and remove the three migrated watcher entries (`mcp-tfl`, `custom-cms`, `mybooking`) from the `watchers:` list. Leave the `wanleung/ai-software-house` entry (it is the central agency watcher and has non-standard config). Leave the `wanleung/my-other-app` example entry (commented out).

The `repos.yaml` `watchers:` list should now only contain:
```yaml
watchers:
  - tracker_repo: wanleung/ai-software-house
    default_target: ~
    feature_label:
      - feature-request
      - ai-build
      - enhancement
      - ai-feature
    bug_label:
      - bug
      - ai-fix
    doc_label: documentation
    enabled: true
```

- [ ] **Step 4: Add `.gitignore` entry for `repos-enabled/`**

Per the design: `repos-available/` is committed; `repos-enabled/` contains symlinks that each developer manages locally.

Add to `.gitignore`:
```
repos-enabled/
```

- [ ] **Step 5: Update `docs/operations-guide.md`**

Add a new section **"Repo Watcher Config (repos-available / repos-enabled)"** to `docs/operations-guide.md`:

```markdown
## Repo Watcher Config (repos-available / repos-enabled)

Watcher entries are stored individually in `repos-available/<name>.yaml` (one file per
tracked repository). Activate a repo by symlinking it into `repos-enabled/`:

```bash
# Enable a repo
python watcher.py repo enable mcp-tfl

# Disable a repo
python watcher.py repo disable mcp-tfl

# List all repos with enabled/disabled status
python watcher.py repo list
```

**File format** (`repos-available/<name>.yaml`):

```yaml
tracker_repo: owner/repo-name
default_target: ~          # null = same repo as tracker
feature_label:
  - feature-request
  - ai-feature
bug_label: bug
doc_label: documentation
enabled: true              # optional; defaults to true

settings:                  # optional — overrides global settings for this repo only
  model: gpt-4.1-mini
  num_engineers: 1
```

**Global settings** in `repos.yaml` apply to all repos unless overridden per-repo.

**`repos-enabled/`** is gitignored — each deployment manages its own symlinks.
**`repos-available/`** is committed — it's the source of truth for all available configs.
```

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/test_watcher_config.py tests/test_watcher.py -v 2>&1 | tail -15
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add repos-available/ repos.yaml docs/operations-guide.md .gitignore
git commit -m "feat: migrate watcher entries to repos-available/; update docs and .gitignore"
```

---

## Task 5: Open PR

- [ ] **Step 1: Push branch and open PR**

```bash
git push origin feature/repos-apache2-config
git push public feature/repos-apache2-config
gh pr create \
  --title "feat: apache2-style repos-available/repos-enabled watcher config" \
  --body "$(cat <<'EOF'
## Summary
- Adds `repos-available/<name>.yaml` per-repo watcher config files
- Enables/disables repos via symlinks in `repos-enabled/` (apache2-style)
- New CLI: `python watcher.py repo enable|disable|list <name>`
- Per-watcher `settings:` block overrides global model/num_engineers
- Fully backward-compatible — existing `repos.yaml` with `watchers:` list works unchanged
- Migrates mcp-tfl, custom-cms, mybooking to `repos-available/`

## Testing
- `tests/test_watcher_config.py` — 15+ new tests covering config loading, CLI sub-commands, edge cases

## How to use
\`\`\`bash
python watcher.py repo enable  mcp-tfl   # create symlink
python watcher.py repo disable mcp-tfl   # remove symlink
python watcher.py repo list              # show all with status
\`\`\`
EOF
)"
```
