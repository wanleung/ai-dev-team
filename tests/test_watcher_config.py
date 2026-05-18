"""tests/test_watcher_config.py — Tests for load_watcher_config() and repo sub-commands."""
from __future__ import annotations

import logging
import os
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import watcher
from watcher import load_watcher_config, cmd_repo_enable, cmd_repo_disable, cmd_repo_list, _deep_merge_llm


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


def test_broken_symlink_skipped(tmp_path, caplog):
    """Broken symlinks in repos-enabled/ are skipped with a warning."""
    import logging
    cfg = tmp_path / "repos.yaml"
    _write(cfg, "settings:\n  max_parallel: 1\n")

    enabled = tmp_path / "repos-enabled"
    enabled.mkdir()
    os.symlink(tmp_path / "repos-available" / "ghost.yaml", enabled / "ghost.yaml")

    with caplog.at_level(logging.WARNING, logger="watcher"):
        result = load_watcher_config(cfg)
    assert "Broken symlink" in caplog.text
    assert result["watchers"] == []


def test_duplicate_tracker_repo_enabled_wins(tmp_path, caplog):
    """If same tracker_repo appears in both legacy and repos-enabled/, enabled wins."""
    import logging
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

    with caplog.at_level(logging.WARNING, logger="watcher"):
        result = load_watcher_config(cfg)
    assert "Duplicate tracker_repo" in caplog.text
    repos = [w["tracker_repo"] for w in result["watchers"]]
    assert repos.count("owner/shared") == 1
    w = next(w for w in result["watchers"] if w["tracker_repo"] == "owner/shared")
    assert w["feature_label"] == "new-label"


def test_non_yaml_files_in_enabled_are_ignored(tmp_path):
    """README and .conf files in repos-enabled/ are silently skipped."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, "settings:\n  max_parallel: 1\n")
    enabled = tmp_path / "repos-enabled"
    enabled.mkdir()
    (enabled / "README").write_text("don't parse me")
    (enabled / "repo.conf").write_text("tracker_repo: owner/should-not-appear")

    result = load_watcher_config(cfg)
    assert result["watchers"] == []


def test_missing_tracker_repo_in_enabled_is_skipped(tmp_path, caplog):
    """repos-enabled/ file without tracker_repo is skipped with a warning."""
    import logging
    cfg = tmp_path / "repos.yaml"
    _write(cfg, "settings:\n  max_parallel: 1\n")

    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "broken-config.yaml", "feature_label: feature-request\n")

    enabled = tmp_path / "repos-enabled"
    enabled.mkdir()
    os.symlink(avail / "broken-config.yaml", enabled / "broken-config.yaml")

    with caplog.at_level(logging.WARNING, logger="watcher"):
        result = load_watcher_config(cfg)
    assert "no tracker_repo" in caplog.text
    assert result["watchers"] == []


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
        if label == "feature-request":
            return [{"number": 1, "title": "T", "body": "", "labels": [{"name": "feature-request"}]}]
        return []

    def fake_dispatch(**kwargs):
        dispatched.append(kwargs)
        return SimpleNamespace(
            next_label=None,
            verdict="success",
            tests_passed=True,
            deploy_tests_passed=True,
        )

    monkeypatch.setattr("watcher.get_open_issues", fake_get_open_issues)
    monkeypatch.setattr("watcher._dispatch", fake_dispatch)
    monkeypatch.setattr("watcher.ensure_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.add_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.remove_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.post_comment",  lambda *a, **kw: None)
    monkeypatch.setattr("watcher.check_waiting_issues", lambda *a, **kw: None)
    monkeypatch.setattr("watcher._process_resume_queue", lambda *a, **kw: [])
    monkeypatch.setattr("watcher._load_pipeline_config", lambda: {})
    (tmp_path / "logs" / "watcher").mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("test")
    logger.addHandler(logging.NullHandler())

    watcher.watch(cfg, dry_run=False, logger=logger)

    assert len(dispatched) == 1
    assert dispatched[0]["model"] == "gpt-4.1-mini"
    assert dispatched[0]["num_engineers"] == 1


def test_watch_uses_global_model_when_no_per_watcher_settings(tmp_path, monkeypatch):
    """watch() uses global model when watcher has no _settings."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, """
        settings:
          model: gpt-4.1
          num_engineers: 2
          max_parallel: 1
          log_dir: logs/watcher
        watchers:
          - tracker_repo: owner/plain-repo
            feature_label: feature-request
            enabled: true
    """)
    (tmp_path / "logs" / "watcher").mkdir(parents=True, exist_ok=True)

    dispatched = []

    def fake_get_open_issues(repo, label):
        if label == "feature-request":
            return [{"number": 1, "title": "T", "body": "", "labels": [{"name": "feature-request"}]}]
        return []

    def fake_dispatch(**kwargs):
        dispatched.append(kwargs)
        return SimpleNamespace(next_label=None, verdict="success", tests_passed=True, deploy_tests_passed=True)

    monkeypatch.setattr("watcher.get_open_issues", fake_get_open_issues)
    monkeypatch.setattr("watcher._dispatch", fake_dispatch)
    monkeypatch.setattr("watcher.ensure_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.add_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.remove_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.post_comment", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.check_waiting_issues", lambda *a, **kw: None)
    monkeypatch.setattr("watcher._process_resume_queue", lambda *a, **kw: [])
    monkeypatch.setattr("watcher._load_pipeline_config", lambda: {})

    logger = logging.getLogger("test")
    logger.addHandler(logging.NullHandler())

    watcher.watch(cfg, dry_run=False, logger=logger)

    assert len(dispatched) == 1
    assert dispatched[0]["model"] == "gpt-4.1"
    assert dispatched[0]["num_engineers"] == 2


# ── repo sub-commands ─────────────────────────────────────────────────────────

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


def test_repo_enable_error_no_avail_dir(tmp_path):
    """repo enable raises SystemExit when repos-available/ doesn't exist at all."""
    with pytest.raises(SystemExit):
        cmd_repo_enable(tmp_path, "anything")


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
    lines = out.splitlines()
    assert any("enabled" in l and "repo-a" in l for l in lines)
    assert any("disabled" in l and "repo-b" in l for l in lines)


def test_repo_list_empty(tmp_path, capsys):
    """repo list on empty repos-available/ prints a helpful message."""
    (tmp_path / "repos-available").mkdir()
    cmd_repo_list(tmp_path)
    err = capsys.readouterr().err
    assert "No repos found" in err


def test_repo_list_no_avail_dir(tmp_path, capsys):
    """repo list when repos-available/ is absent prints a helpful message to stderr."""
    cmd_repo_list(tmp_path)
    err = capsys.readouterr().err
    assert "No repos-available" in err


# ── Issue 1: labels dict string format ───────────────────────────────────────

def test_watch_uses_new_labels_dict_string_format(tmp_path, monkeypatch):
    """watch() correctly resolves pipeline_name from labels: {label: pipeline} string values."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, """
        settings:
          model: gpt-4.1
          num_engineers: 1
          max_parallel: 1
          log_dir: logs/watcher
        watchers:
          - tracker_repo: owner/repo
            labels:
              enhancement: ai-feature
              ai-fix: ai-fix
            enabled: true
    """)
    (tmp_path / "logs" / "watcher").mkdir(parents=True, exist_ok=True)
    dispatched = []

    def fake_get_open_issues(repo, label):
        if label == "enhancement":
            return [{"number": 1, "title": "T", "body": "", "labels": [{"name": "enhancement"}]}]
        return []

    def fake_dispatch(**kwargs):
        dispatched.append(kwargs)
        return SimpleNamespace(next_label=None, verdict="success", tests_passed=True, deploy_tests_passed=True)

    monkeypatch.setattr("watcher.get_open_issues", fake_get_open_issues)
    monkeypatch.setattr("watcher._dispatch", fake_dispatch)
    monkeypatch.setattr("watcher.ensure_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.add_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.remove_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.post_comment", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.check_waiting_issues", lambda *a, **kw: None)
    monkeypatch.setattr("watcher._process_resume_queue", lambda *a, **kw: [])
    monkeypatch.setattr("watcher._load_pipeline_config", lambda: {})

    logger = logging.getLogger("test")
    logger.addHandler(logging.NullHandler())
    watcher.watch(cfg, dry_run=False, logger=logger)

    assert len(dispatched) == 1
    assert dispatched[0]["label"] == "ai-feature"


# ── Issue 2: cmd_repo_enable input validation ─────────────────────────────────

def test_repo_enable_rejects_path_traversal(tmp_path):
    """cmd_repo_enable rejects names with path separators or leading dots."""
    with pytest.raises(SystemExit):
        cmd_repo_enable(tmp_path, "../evil")
    with pytest.raises(SystemExit):
        cmd_repo_enable(tmp_path, ".hidden")


def test_repo_disable_rejects_path_traversal(tmp_path):
    """cmd_repo_disable rejects names with path separators or leading dots."""
    with pytest.raises(SystemExit):
        cmd_repo_disable(tmp_path, "../evil")
    with pytest.raises(SystemExit):
        cmd_repo_disable(tmp_path, ".hidden")


def test_legacy_watcher_settings_stored_as_underscore(tmp_path):
    """Legacy watchers: entries with settings: get settings→_settings transformation."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, """
        watchers:
          - tracker_repo: owner/legacy
            feature_label: feature-request
            enabled: true
            settings:
              model: gpt-4.1-mini
              num_engineers: 1
    """)
    result = load_watcher_config(cfg)
    w = result["watchers"][0]
    assert w["_settings"]["model"] == "gpt-4.1-mini"
    assert "settings" not in w


def test_pipeline_timeout_default(tmp_path):
    """load_watcher_config does not inject pipeline_timeout_s when absent from config."""
    cfg = {"watchers": []}
    cfg_file = tmp_path / "repos.yaml"
    cfg_file.write_text(yaml.dump(cfg))
    result = load_watcher_config(cfg_file)
    assert "pipeline_timeout_s" not in result.get("settings", {})


def test_pipeline_timeout_custom(tmp_path):
    """load_watcher_config passes through a custom pipeline_timeout_s."""
    cfg = {"watchers": [], "settings": {"pipeline_timeout_s": 1800}}
    cfg_file = tmp_path / "repos.yaml"
    cfg_file.write_text(yaml.dump(cfg))
    result = load_watcher_config(cfg_file)
    assert result["settings"]["pipeline_timeout_s"] == 1800


# ── _deep_merge_llm ───────────────────────────────────────────────────────────


def test_merge_llm_model_repo_wins():
    global_llm = {"model": "openai/gpt-4.1", "overrides": {"architect": "openai/gpt-4.1"}}
    repo_llm = {"model": "ollama/qwen3.5"}
    result = _deep_merge_llm(global_llm, repo_llm)
    assert result["model"] == "ollama/qwen3.5"
    assert result["overrides"]["architect"] == "openai/gpt-4.1"  # global kept


def test_merge_llm_overrides_key_by_key():
    global_llm = {"model": "openai/gpt-4.1", "overrides": {"architect": "openai/gpt-4.1", "engineer": "openai/gpt-4.1-mini"}}
    repo_llm = {"overrides": {"architect": "claude-3-5-sonnet-20241022"}}
    result = _deep_merge_llm(global_llm, repo_llm)
    assert result["overrides"]["architect"] == "claude-3-5-sonnet-20241022"  # repo wins
    assert result["overrides"]["engineer"] == "openai/gpt-4.1-mini"  # global kept


def test_merge_llm_pools_key_by_key():
    global_llm = {"model": "openai/gpt-4.1", "pools": {"openai": 10, "anthropic": 5}}
    repo_llm = {"pools": {"openai": 3}}
    result = _deep_merge_llm(global_llm, repo_llm)
    assert result["pools"]["openai"] == 3       # repo wins
    assert result["pools"]["anthropic"] == 5    # global kept


def test_merge_llm_fallback_replaced_not_merged():
    global_llm = {"model": "openai/gpt-4.1", "fallbacks": [{"model": "openai/gpt-4.1-mini"}]}
    repo_llm = {"fallbacks": [{"model": "ollama/qwen3.5"}]}
    result = _deep_merge_llm(global_llm, repo_llm)
    assert result["fallbacks"] == [{"model": "ollama/qwen3.5"}]


def test_merge_llm_no_repo_llm_returns_global_copy():
    global_llm = {"model": "openai/gpt-4.1", "overrides": {"architect": "openai/gpt-4.1"}}
    result = _deep_merge_llm(global_llm, {})
    assert result == global_llm
    assert result is not global_llm  # top-level copy
    assert result["overrides"] is not global_llm["overrides"]  # nested dict is a copy
    # Verify mutation independence
    global_llm["overrides"]["architect"] = "mutated"
    assert result["overrides"]["architect"] == "openai/gpt-4.1"


def test_merge_llm_empty_global():
    result = _deep_merge_llm({}, {"model": "ollama/qwen3.5"})
    assert result["model"] == "ollama/qwen3.5"


def test_merge_llm_empty_model_does_not_replace_global():
    result = _deep_merge_llm({"model": "openai/gpt-4.1"}, {"model": ""})
    assert result["model"] == "openai/gpt-4.1"


# ── load_watcher_config: llm extraction ──────────────────────────────────────

def test_load_watcher_config_extracts_llm(tmp_path):
    """llm: key is extracted from repo entry and stored as _llm."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, """
        watchers:
          - tracker_repo: owner/alpha
            enabled: true
            llm:
              model: "ollama/qwen3.5"
              overrides:
                architect: "openai/gpt-4.1"
    """)
    result = load_watcher_config(cfg)
    w = result["watchers"][0]
    assert "_llm" in w
    assert w["_llm"]["model"] == "ollama/qwen3.5"
    assert w["_llm"]["overrides"]["architect"] == "openai/gpt-4.1"
    assert "llm" not in w  # original key removed


def test_load_watcher_config_no_llm_key_absent(tmp_path):
    """Repo entries without llm: have no _llm key."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, """
        watchers:
          - tracker_repo: owner/alpha
            enabled: true
    """)
    result = load_watcher_config(cfg)
    w = result["watchers"][0]
    assert "_llm" not in w


def test_load_watcher_config_llm_in_repos_enabled(tmp_path):
    """llm: key in repos-available/ entry is extracted to _llm."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, "settings:\n  max_parallel: 1\n")

    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "my-repo.yaml", """
        tracker_repo: owner/my-repo
        enabled: true
        llm:
          model: "openai/gpt-4.1"
          pools:
            openai: 3
    """)

    enabled = tmp_path / "repos-enabled"
    enabled.mkdir()
    os.symlink(avail / "my-repo.yaml", enabled / "my-repo.yaml")

    result = load_watcher_config(cfg)
    w = result["watchers"][0]
    assert w["_llm"]["model"] == "openai/gpt-4.1"
    assert w["_llm"]["pools"]["openai"] == 3


def test_load_watcher_config_llm_null_is_ignored(tmp_path):
    """llm: null (bare YAML key) leaves _llm absent from the watcher entry."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, "watchers:\n  - tracker_repo: owner/a\n    enabled: true\n    llm:\n")
    w = load_watcher_config(cfg)["watchers"][0]
    assert "_llm" not in w


def test_watch_task_dict_contains_effective_llm(tmp_path, monkeypatch):
    """Tasks queued for a watcher include effective_llm merging global + repo llm."""
    cfg_path = tmp_path / "repos.yaml"
    _write(cfg_path, """
        watchers:
          - tracker_repo: owner/alpha
            labels:
              ai-feature: ai-feature
            enabled: true
            llm:
              model: "ollama/qwen3.5"
              overrides:
                engineer: "ollama/qwen3.5"
        settings:
          max_parallel: 1
          num_engineers: 1
    """)

    # Patch global config with known LLM settings
    global_cfg = {
        "llm": {
            "model": "openai/gpt-4.1",
            "overrides": {"architect": "openai/gpt-4.1", "engineer": "openai/gpt-4.1-mini"},
        },
        "pipeline": {},
        "settings": {},
    }
    monkeypatch.setattr(watcher, "_load_pipeline_config", lambda: global_cfg)

    issues = [{"number": 1, "title": "feat", "labels": []}]
    monkeypatch.setattr(watcher, "get_open_issues", lambda repo, label: issues if label == "ai-feature" else [])
    monkeypatch.setattr(watcher, "add_label", lambda *a, **kw: None)
    monkeypatch.setattr(watcher, "ensure_label", lambda *a, **kw: None)
    monkeypatch.setattr(watcher, "check_waiting_issues", lambda *a, **kw: None)
    monkeypatch.setattr(watcher, "_watch_prs", lambda *a, **kw: None)
    monkeypatch.setattr(watcher, "_process_resume_queue", lambda *a, **kw: [])
    (tmp_path / "logs" / "watcher").mkdir(parents=True, exist_ok=True)

    tasks = []
    monkeypatch.setattr(watcher, "_run_tasks", lambda t, *a, **kw: tasks.extend(t))

    watcher.watch(cfg_path, once=True, dry_run=False)

    assert len(tasks) == 1
    llm = tasks[0]["llm"]
    assert llm["model"] == "ollama/qwen3.5"           # repo wins
    assert llm["overrides"]["architect"] == "openai/gpt-4.1"   # global kept
    assert llm["overrides"]["engineer"] == "ollama/qwen3.5"    # repo wins


def test_watch_task_dict_llm_is_global_when_no_repo_llm(tmp_path, monkeypatch):
    """Tasks for repo without llm: section use global LLM config unchanged."""
    cfg_path = tmp_path / "repos.yaml"
    _write(cfg_path, """
        watchers:
          - tracker_repo: owner/alpha
            labels:
              ai-feature: ai-feature
            enabled: true
        settings:
          max_parallel: 1
          num_engineers: 1
    """)

    global_cfg = {
        "llm": {"model": "openai/gpt-4.1", "overrides": {"architect": "openai/gpt-4.1"}},
        "pipeline": {},
        "settings": {},
    }
    monkeypatch.setattr(watcher, "_load_pipeline_config", lambda: global_cfg)

    issues = [{"number": 1, "title": "feat", "labels": []}]
    monkeypatch.setattr(watcher, "get_open_issues", lambda repo, label: issues if label == "ai-feature" else [])
    monkeypatch.setattr(watcher, "add_label", lambda *a, **kw: None)
    monkeypatch.setattr(watcher, "ensure_label", lambda *a, **kw: None)
    monkeypatch.setattr(watcher, "check_waiting_issues", lambda *a, **kw: None)
    monkeypatch.setattr(watcher, "_watch_prs", lambda *a, **kw: None)
    monkeypatch.setattr(watcher, "_process_resume_queue", lambda *a, **kw: [])
    (tmp_path / "logs" / "watcher").mkdir(parents=True, exist_ok=True)

    tasks = []
    monkeypatch.setattr(watcher, "_run_tasks", lambda t, *a, **kw: tasks.extend(t))

    watcher.watch(cfg_path, once=True, dry_run=False)

    assert tasks[0]["llm"]["model"] == "openai/gpt-4.1"
