import pytest
from pydantic import ValidationError
import yaml

def test_valid_minimal_config(tmp_path):
    """A config with only defaults passes validation."""
    from config_schema import load_config
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump({"llm": {"model": "gpt-4.1"}}))
    result = load_config(str(cfg_file))
    assert result.llm.model == "gpt-4.1"

def test_unknown_top_level_key_raises(tmp_path):
    """An unknown top-level key raises ValidationError."""
    from config_schema import load_config
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump({"llm": {"model": "gpt-4.1"}, "typo_key": "bad"}))
    with pytest.raises(ValidationError):
        load_config(str(cfg_file))

def test_missing_llm_model_uses_default():
    """Omitting llm.model gives the default 'gpt-4.1'."""
    from config_schema import AppConfig
    cfg = AppConfig.model_validate({})
    assert cfg.llm.model == "gpt-4.1"

def test_repo_config_extra_fields_allowed():
    """RepoWatcherEntry allows arbitrary extra keys for future expansion."""
    from config_schema import RepoWatcherEntry
    entry = RepoWatcherEntry.model_validate({
        "tracker_repo": "owner/repo",
        "custom_future_field": "value",
    })
    assert entry.tracker_repo == "owner/repo"

def test_invalid_num_engineers_raises():
    """Non-integer num_engineers raises ValidationError."""
    from config_schema import AppConfig
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"pipeline": {"num_engineers": "two"}})

def test_missing_tracker_repo_raises():
    """RepoWatcherEntry requires tracker_repo — missing it raises ValidationError."""
    from config_schema import load_repo_entry
    with pytest.raises(ValidationError):
        load_repo_entry({"enabled": True})

def test_repo_watcher_entry_accepts_llm_section():
    """RepoWatcherEntry accepts an llm section with model and overrides."""
    from config_schema import RepoWatcherEntry, LLMConfig
    entry = RepoWatcherEntry(
        tracker_repo="owner/my-repo",
        llm={
            "model": "ollama/qwen3.5",
            "overrides": {"architect": "openai/gpt-4.1"},
            "pools": {"openai": 3},
        },
    )
    assert entry.llm is not None
    assert entry.llm.model == "ollama/qwen3.5"

def test_repo_watcher_entry_no_llm_defaults_none():
    """RepoWatcherEntry without llm section defaults to None."""
    from config_schema import RepoWatcherEntry
    entry = RepoWatcherEntry(tracker_repo="owner/my-repo")
    assert entry.llm is None
