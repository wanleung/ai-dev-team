from utils import sanitise, deep_merge


def test_sanitise_replaces_single_secret():
    assert sanitise("error: https://mytoken@host/repo", "mytoken") == "error: https://***@host/repo"


def test_sanitise_replaces_multiple_secrets():
    result = sanitise("tok1 and tok2 here", "tok1", "tok2")
    assert result == "*** and *** here"


def test_sanitise_empty_secret_is_safe():
    assert sanitise("no change", "", None) == "no change"


def test_sanitise_no_match_returns_unchanged():
    assert sanitise("hello world", "secret") == "hello world"


def test_sanitise_multiple_occurrences():
    assert sanitise("x secret x secret x", "secret") == "x *** x *** x"


def test_deep_merge_flat_override():
    result = deep_merge({"a": 1, "b": 2}, {"b": 3, "c": 4})
    assert result == {"a": 1, "b": 3, "c": 4}


def test_deep_merge_nested():
    base = {"llm": {"model": "gpt-4o", "timeout": 30}, "key": "x"}
    override = {"llm": {"model": "claude-3"}}
    result = deep_merge(base, override)
    assert result == {"llm": {"model": "claude-3", "timeout": 30}, "key": "x"}


def test_deep_merge_does_not_mutate_base():
    base = {"a": {"b": 1}}
    override = {"a": {"c": 2}}
    result = deep_merge(base, override)
    assert base == {"a": {"b": 1}}   # base must not be mutated
    assert result == {"a": {"b": 1, "c": 2}}


def test_deep_merge_empty_override_returns_copy():
    base = {"a": 1}
    result = deep_merge(base, {})
    assert result == {"a": 1}
    assert result is not base


def test_deep_merge_scalar_override_wins():
    """A scalar in override replaces a dict in base (override wins always)."""
    result = deep_merge({"a": {"nested": 1}}, {"a": "flat"})
    assert result == {"a": "flat"}


def test_deep_merge_non_overlapping_nested_branch_is_aliased():
    """Non-overlapping nested objects are shallow-aliased in the result.

    This is pre-existing behavior (preserved from the original _deep_merge in
    orchestrator.py). The result shares nested dict references for keys that
    exist only in base. Callers should not mutate the result's nested objects.
    """
    base = {"a": {"x": 1}, "b": {"y": 2}}
    result = deep_merge(base, {"a": {"z": 3}})
    # "b" only exists in base — result["b"] is the same object
    assert result["b"] is base["b"]
