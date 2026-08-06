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
    assert captured["run"][1]["planning_artifacts"] is None


def test_resolve_superpowers_artifacts_from_issue_blocks():
    body = """
Target repo: owner/app

```superpowers-spec
# Spec
Acceptance Criteria:
- Login works
```

```superpowers-plan
# Plan
### Task 1: Auth
Build login.
```
"""

    artifacts = watcher._resolve_superpowers_artifacts(body, "", None, None)

    assert artifacts["spec"].startswith("# Spec")
    assert artifacts["plan"].startswith("# Plan")
    assert artifacts["sources"] == {"spec": "issue-block", "plan": "issue-block"}


def test_resolve_superpowers_artifacts_from_referenced_files():
    body = """
Superpowers-Spec: docs/superpowers/specs/auth.md
Superpowers-Plan: docs/superpowers/plans/auth.md
"""

    class FakeGH:
        def __init__(self, files):
            self.files = files

        def get_file_content(self, path):
            return self.files[path]

    target = FakeGH({
        "docs/superpowers/specs/auth.md": "# Auth Spec",
        "docs/superpowers/plans/auth.md": "# Auth Plan",
    })

    artifacts = watcher._resolve_superpowers_artifacts(body, "", MagicMock(), target)

    assert artifacts["spec"] == "# Auth Spec"
    assert artifacts["plan"] == "# Auth Plan"
    assert artifacts["sources"]["spec"] == "target-repo:docs/superpowers/specs/auth.md"
    assert artifacts["sources"]["plan"] == "target-repo:docs/superpowers/plans/auth.md"


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


def _dispatch_with_pipeline_config(monkeypatch, tmp_path, pipeline_cfg):
    captured = {}

    class FakeOrch:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self._pipeline_yaml_stages = None

        def load_pipeline_for_label(self, label):
            return None

        def run(self, *a, **kw):
            captured["run_kwargs"] = kw
            return MagicMock(success=True)

    fake_mod = types.ModuleType("orchestrator")
    fake_mod.Orchestrator = FakeOrch
    monkeypatch.setitem(sys.modules, "orchestrator", fake_mod)

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
        "llm": {},
        "pipeline": pipeline_cfg,
    })

    from watcher import _dispatch
    _dispatch(
        label="news-article",
        tracker_repo="owner/tracker",
        target_repo="owner/target",
        issue_number=1,
        model="gpt-4.1",
        num_engineers=1,
        log_file=tmp_path / "run.log",
        logger=None,
    )

    return captured


def test_dispatch_passes_reviewer_max_retries(monkeypatch, tmp_path):
    """_dispatch forwards news reviewer retry config into Orchestrator."""
    captured = _dispatch_with_pipeline_config(
        monkeypatch, tmp_path, {"reviewer_max_retries": 5}
    )

    assert captured["reviewer_max_retries"] == 5


def test_dispatch_passes_max_test_retries(monkeypatch, tmp_path):
    """_dispatch forwards test-fix retry config into Orchestrator."""
    captured = _dispatch_with_pipeline_config(
        monkeypatch, tmp_path, {"max_test_retries": 10}
    )

    assert captured["max_test_retries"] == 10


def test_dispatch_passes_revision_limits(monkeypatch, tmp_path):
    """_dispatch forwards revision limit config into Orchestrator."""
    captured = _dispatch_with_pipeline_config(
        monkeypatch,
        tmp_path,
        {
            "max_revisions": 6,
            "max_prd_revisions": 4,
            "max_design_revisions": 5,
        },
    )

    assert captured["max_revisions"] == 6
    assert captured["max_prd_revisions"] == 4
    assert captured["max_design_revisions"] == 5


def test_dispatch_defaults_reviewer_max_retries_when_missing(monkeypatch, tmp_path):
    """_dispatch preserves the Orchestrator default when reviewer_max_retries is missing."""
    captured = _dispatch_with_pipeline_config(monkeypatch, tmp_path, {})

    assert captured["reviewer_max_retries"] == 2


def test_dispatch_defaults_reviewer_max_retries_when_null(monkeypatch, tmp_path):
    """_dispatch treats reviewer_max_retries: null as the default."""
    captured = _dispatch_with_pipeline_config(
        monkeypatch, tmp_path, {"reviewer_max_retries": None}
    )

    assert captured["reviewer_max_retries"] == 2


def test_dispatch_allows_zero_reviewer_max_retries(monkeypatch, tmp_path):
    """_dispatch allows reviewer_max_retries: 0 to mean no retry after the first review."""
    captured = _dispatch_with_pipeline_config(
        monkeypatch, tmp_path, {"reviewer_max_retries": 0}
    )

    assert captured["reviewer_max_retries"] == 0


def test_dispatch_passes_superpowers_artifacts_from_issue(monkeypatch, tmp_path):
    captured = {}

    class FakeOrch:
        def __init__(self, **kwargs):
            self._pipeline_yaml_stages = None

        def load_pipeline_for_label(self, label):
            return ["superpowers_ingest"]

        def run(self, *a, **kw):
            captured["run_kwargs"] = kw
            return MagicMock(success=True)

    fake_mod = types.ModuleType("orchestrator")
    fake_mod.Orchestrator = FakeOrch
    monkeypatch.setitem(sys.modules, "orchestrator", fake_mod)

    class FakeGH:
        def __init__(self, repo, token):
            pass

        def get_issue(self, n):
            return {
                "title": "planned",
                "body": "```superpowers-spec\n# Spec\n```\n```superpowers-plan\n# Plan\n```",
            }

        def get_issue_comments(self, n):
            return []

    fake_gh_mod = types.ModuleType("github_client")
    fake_gh_mod.GitHubClient = FakeGH
    fake_gh_mod.parse_target_repo = lambda b: None
    monkeypatch.setitem(sys.modules, "github_client", fake_gh_mod)
    monkeypatch.setattr(watcher, "_load_pipeline_config", lambda: {"llm": {}, "pipeline": {}})

    from watcher import _dispatch
    _dispatch(
        label="planned",
        tracker_repo="owner/tracker",
        target_repo="owner/target",
        issue_number=1,
        model="gpt-4.1",
        num_engineers=1,
        log_file=tmp_path / "run.log",
        logger=None,
    )

    artifacts = captured["run_kwargs"]["planning_artifacts"]
    assert artifacts["spec"] == "# Spec"
    assert artifacts["plan"] == "# Plan"


def test_concurrent_dispatch_does_not_redirect_global_stdout(tmp_path):
    """Concurrent _dispatch calls must not clobber sys.stdout/sys.stderr."""
    import threading
    import sys
    from unittest.mock import MagicMock, patch
    from watcher import _dispatch

    log1 = tmp_path / "run1.log"
    log2 = tmp_path / "run2.log"

    original_stdout = sys.stdout
    original_stderr = sys.stderr

    # A fake PipelineResult
    fake_result = MagicMock()
    fake_result.errors = []
    fake_result.next_label = None

    mock_orch_instance = MagicMock()
    mock_orch_instance.run.return_value = fake_result
    mock_orch_instance.load_pipeline_for_label.return_value = None
    mock_orch_class = MagicMock(return_value=mock_orch_instance)

    fake_gh_instance = MagicMock()
    fake_gh_instance.get_issue.return_value = {"title": "t", "body": "", "labels": []}
    fake_gh_instance.get_issue_comments.return_value = []
    fake_gh_class = MagicMock(return_value=fake_gh_instance)

    errors = []

    def run_dispatch(log_file):
        try:
            _dispatch(
                label="ai-feature",
                tracker_repo="owner/repo",
                target_repo="owner/repo",
                issue_number=1,
                model="gpt-4.1",
                num_engineers=1,
                log_file=log_file,
                logger=None,
            )
        except Exception as exc:
            errors.append(str(exc))

    # Inject fakes into sys.modules BEFORE spawning threads so both threads
    # share the same patched state without racing.  local `from x import Y`
    # inside _dispatch re-reads sys.modules on every call, picking up our fakes.
    with patch.dict(sys.modules, {
        "orchestrator": MagicMock(Orchestrator=mock_orch_class),
        "github_client": MagicMock(GitHubClient=fake_gh_class),
    }), patch("watcher._collect_issue_prior_context", return_value=""), \
       patch("watcher._load_pipeline_config", return_value={"llm": {}, "pipeline": {}}):

        t1 = threading.Thread(target=run_dispatch, args=(log1,))
        t2 = threading.Thread(target=run_dispatch, args=(log2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    # After both threads complete, global stdout/stderr must be unchanged
    assert sys.stdout is original_stdout, "sys.stdout was corrupted by _dispatch"
    assert sys.stderr is original_stderr, "sys.stderr was corrupted by _dispatch"
    assert errors == [], f"Dispatch raised errors: {errors}"

    import logging as _logging

    # Both log files must have been created (logging actually reached the file)
    assert log1.exists(), f"run1 log was not created at {log1}"
    assert log2.exists(), f"run2 log was not created at {log2}"

    # No FileHandlers for these paths should remain (no handler leaks)
    leaked = [
        h for h in _logging.getLogger().handlers
        if isinstance(h, _logging.FileHandler)
        and h.baseFilename in (str(log1.resolve()), str(log2.resolve()))
    ]
    assert leaked == [], f"FileHandler(s) leaked onto root logger: {leaked}"
