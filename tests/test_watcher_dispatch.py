"""Tests for label-based watcher dispatch."""
from unittest.mock import MagicMock


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
