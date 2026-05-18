"""Tests for label-based watcher dispatch."""
import sys
import types
from unittest.mock import MagicMock

import watcher


def test_dispatch_uses_pipeline_for_label(monkeypatch, tmp_path):
    """Watcher passes the label to Orchestrator and uses pipelines/<label>.yaml."""
    from watcher import _dispatch

    captured: dict = {}

    class FakeOrch:
        def __init__(self, **kwargs):
            captured["init"] = kwargs
            self._pipeline_yaml_stages = None
        def load_pipeline_for_label(self, label, project_dir=None):
            captured["label"] = label
            return ["pm", "engineer"]
        def run(self, requirement, **kwargs):
            captured["run"] = (requirement, kwargs)
            captured["stages"] = self._pipeline_yaml_stages
            return MagicMock(success=True)

    fake_module = MagicMock()
    fake_module.Orchestrator = FakeOrch

    monkeypatch.setitem(__import__("sys").modules, "orchestrator", fake_module)

    # Provide a fake GitHubClient that returns a stub issue
    class FakeGH:
        def __init__(self, repo, token):
            pass
        def get_issue(self, n):
            return {"title": "T", "body": "B"}

    fake_gh_module = MagicMock()
    fake_gh_module.GitHubClient = FakeGH
    fake_gh_module.parse_target_repo = lambda b: None
    monkeypatch.setitem(__import__("sys").modules, "github_client", fake_gh_module)

    _dispatch(
        label="ai-feature",
        tracker_repo="owner/r", target_repo="owner/r", issue_number=1,
        model="m", num_engineers=1,
        log_file=tmp_path / "test.log",
        logger=MagicMock(),
    )
    assert captured["label"] == "ai-feature"
    assert captured["stages"] == ["pm", "engineer"]


def test_dispatch_uses_llm_cfg_when_provided(monkeypatch, tmp_path):
    """_dispatch uses llm_cfg model/overrides instead of global config when provided."""
    captured = {}

    # Minimal fake Orchestrator that records what model/overrides it got
    class FakeOrch:
        def __init__(self, **kwargs):
            captured.update(kwargs)
        def load_pipeline_for_label(self, label):
            return None
        def run(self, *a, **kw):
            return MagicMock(success=True)
        _pipeline_yaml_stages = None

    fake_mod = types.ModuleType("orchestrator")
    fake_mod.Orchestrator = FakeOrch
    monkeypatch.setitem(sys.modules, "orchestrator", fake_mod)

    # Fake GitHubClient that returns a stub issue
    class FakeGH:
        def __init__(self, repo, token):
            pass
        def get_issue(self, n):
            return {"title": "t", "body": "", "labels": []}
        def get_issue_comments(self, n):
            return []

    fake_gh_mod = types.ModuleType("github_client")
    fake_gh_mod.GitHubClient = FakeGH
    fake_gh_mod.parse_target_repo = lambda b: None
    monkeypatch.setitem(sys.modules, "github_client", fake_gh_mod)

    monkeypatch.setattr(watcher, "_load_pipeline_config", lambda: {
        "llm": {"model": "openai/gpt-4.1", "overrides": {}},
        "pipeline": {},
    })

    log_file = tmp_path / "run.log"
    repo_llm = {"model": "ollama/qwen3.5", "overrides": {"engineer": "ollama/qwen3.5"}}

    from watcher import _dispatch
    _dispatch(
        label="ai-feature",
        tracker_repo="owner/tracker",
        target_repo="owner/target",
        issue_number=1,
        model="gpt-4.1",
        num_engineers=1,
        log_file=log_file,
        logger=None,
        llm_cfg=repo_llm,
    )

    assert captured.get("model") == "ollama/qwen3.5"
    assert captured.get("model_overrides", {}).get("engineer") == "ollama/qwen3.5"
