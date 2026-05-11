"""Regression test for _stage_timeouts class-level default.

Ensures that Orchestrator.__new__() instances don't raise AttributeError
when accessing _stage_timeouts, which was set only in __init__ previously.
"""

from orchestrator import Orchestrator


def test_stage_timeouts_class_level_default():
    """Orchestrator.__new__() must have _stage_timeouts without calling __init__."""
    orch = Orchestrator.__new__(Orchestrator)
    # None is the class-level sentinel; __init__ sets a real dict
    assert orch._stage_timeouts is None


def test_make_stage_registry_on_new_stub_does_not_raise():
    """_make_stage_registry on a __new__ stub must not raise AttributeError for _stage_timeouts."""
    orch = Orchestrator.__new__(Orchestrator)
    orch._stage_timeouts = None  # class-level default
    orch._stage_skips = {}
    orch._pipeline_yaml_stages = None
    orch._mode = "full"
    for attr in ("pm", "pm_reviewer", "architect", "architect_reviewer",
                 "engineer", "junior_engineer", "senior_engineer", "reviewer",
                 "qa", "qa_planner", "deployment_tester", "tier_reviewer"):
        setattr(orch, attr, None)
    # Must not raise AttributeError
    registry = orch._make_stage_registry()
    assert isinstance(registry, dict)
