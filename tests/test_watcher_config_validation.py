import io
import pytest
from pathlib import Path
from unittest.mock import patch


def test_load_pipeline_config_invalid_local_raises(monkeypatch):
    """Invalid config.local.yaml causes ValueError with 'Invalid config' message."""
    import watcher

    base_yaml = "llm:\n  model: gpt-4o\n"
    local_yaml = "llm: not-a-dict\n"  # overrides dict with string — schema violation

    orig_exists = Path.exists

    def fake_exists(self):
        if self.name == "config.yaml":
            return True
        if self.name == "config.local.yaml":
            return True
        return orig_exists(self)

    original_open = open

    def fake_open(path, *args, **kwargs):
        path_str = str(path)
        if path_str.endswith("config.local.yaml"):
            return io.StringIO(local_yaml)
        if path_str.endswith("config.yaml"):
            return io.StringIO(base_yaml)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr("builtins.open", fake_open)

    with pytest.raises(ValueError, match="Invalid config"):
        watcher._load_pipeline_config()


def test_load_pipeline_config_valid_local_overrides(monkeypatch):
    """Valid config.local.yaml override loads silently and merges correctly."""
    import watcher

    base_yaml = "llm:\n  model: gpt-4o\n"
    local_yaml = "llm:\n  model: gpt-4o-mini\n"

    orig_exists = Path.exists

    def fake_exists(self):
        if self.name == "config.yaml":
            return True
        if self.name == "config.local.yaml":
            return True
        return orig_exists(self)

    original_open = open

    def fake_open(path, *args, **kwargs):
        path_str = str(path)
        if path_str.endswith("config.local.yaml"):
            return io.StringIO(local_yaml)
        if path_str.endswith("config.yaml"):
            return io.StringIO(base_yaml)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr("builtins.open", fake_open)

    cfg = watcher._load_pipeline_config()
    assert cfg["llm"]["model"] == "gpt-4o-mini"


def test_load_pipeline_config_no_local_file(monkeypatch):
    """Absent config.local.yaml: base config loaded without error."""
    import watcher

    base_yaml = "llm:\n  model: gpt-4o\n"

    orig_exists = Path.exists

    def fake_exists(self):
        if self.name == "config.yaml":
            return True
        if self.name == "config.local.yaml":
            return False
        return orig_exists(self)

    original_open = open

    def fake_open(path, *args, **kwargs):
        path_str = str(path)
        if path_str.endswith("config.yaml"):
            return io.StringIO(base_yaml)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr("builtins.open", fake_open)

    cfg = watcher._load_pipeline_config()
    assert cfg.get("llm", {}).get("model") == "gpt-4o"


def test_load_pipeline_config_rejects_unknown_top_level_key(monkeypatch):
    """AppConfig has extra='forbid': unknown top-level keys raise ValueError."""
    import watcher

    # 'unknown_top_level_key' is not in AppConfig schema → ValidationError → ValueError
    base_yaml = "llm:\n  model: gpt-4o\nunknown_top_level_key: true\n"

    orig_exists = Path.exists

    def fake_exists(self):
        if self.name == "config.yaml":
            return True
        if self.name == "config.local.yaml":
            return False
        return orig_exists(self)

    original_open = open

    def fake_open(path, *args, **kwargs):
        path_str = str(path)
        if path_str.endswith("config.yaml"):
            return io.StringIO(base_yaml)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr("builtins.open", fake_open)

    with pytest.raises(ValueError, match="Invalid config"):
        watcher._load_pipeline_config()
