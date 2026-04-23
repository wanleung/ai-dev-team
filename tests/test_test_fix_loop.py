"""Tests for TestFixLoopMixin.run_test_fix_loop()."""
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import MagicMock, call
import pytest
from test_fix_loop import TestFixLoopMixin


@dataclass
class FakeResult:
    tests_passed: Optional[bool] = None
    test_results: str = ""
    test_retry_count: int = 0
    test_fix_history: list = field(default_factory=list)


class FakeMixin(TestFixLoopMixin):
    pass


def _make_mixin():
    return FakeMixin()


def _run_tests_pass(result):
    result.tests_passed = True
    result.test_results = "1 passed"


def _run_tests_fail(result):
    result.tests_passed = False
    result.test_results = "FAILED test_foo"


def test_returns_immediately_when_first_run_passes():
    mixin = _make_mixin()
    result = FakeResult()
    run_tests_fn = MagicMock(side_effect=_run_tests_pass)
    fix_fn = MagicMock()

    mixin.run_test_fix_loop(
        result=result,
        run_tests_fn=run_tests_fn,
        get_all_files_fn=lambda: {},
        write_files_fn=MagicMock(),
        commit_fn=MagicMock(return_value=True),
        post_comment_fn=MagicMock(),
        fix_fn=fix_fn,
        max_retries=3,
    )

    run_tests_fn.assert_called_once()
    fix_fn.assert_not_called()
    assert result.test_retry_count == 0


def test_calls_fix_and_retests_on_failure():
    mixin = _make_mixin()
    result = FakeResult()
    call_count = [0]

    def run_tests_fn(r):
        call_count[0] += 1
        if call_count[0] == 1:
            _run_tests_fail(r)
        else:
            _run_tests_pass(r)

    fix_fn = MagicMock(return_value={"app/foo.py": "fixed"})
    write_fn = MagicMock()
    commit_fn = MagicMock(return_value=True)

    mixin.run_test_fix_loop(
        result=result,
        run_tests_fn=run_tests_fn,
        get_all_files_fn=lambda: {"app/foo.py": "broken"},
        write_files_fn=write_fn,
        commit_fn=commit_fn,
        post_comment_fn=MagicMock(),
        fix_fn=fix_fn,
        max_retries=3,
    )

    assert call_count[0] == 2         # initial run + 1 retry
    fix_fn.assert_called_once()
    write_fn.assert_called_once_with({"app/foo.py": "fixed"})
    assert result.test_retry_count == 1
    assert len(result.test_fix_history) == 1
    assert "Attempt 1" in result.test_fix_history[0]


def test_stops_loop_when_tests_pass_midway():
    mixin = _make_mixin()
    result = FakeResult()
    runs = [0]

    def run_tests_fn(r):
        runs[0] += 1
        if runs[0] <= 2:
            _run_tests_fail(r)
        else:
            _run_tests_pass(r)

    fix_fn = MagicMock(return_value={"app/foo.py": "v2"})

    mixin.run_test_fix_loop(
        result=result,
        run_tests_fn=run_tests_fn,
        get_all_files_fn=lambda: {},
        write_files_fn=MagicMock(),
        commit_fn=MagicMock(return_value=True),
        post_comment_fn=MagicMock(),
        fix_fn=fix_fn,
        max_retries=5,
    )

    assert runs[0] == 3              # fail, fail, pass
    assert result.test_retry_count == 2
    assert result.tests_passed is True


def test_exhausts_retries_and_posts_comment():
    mixin = _make_mixin()
    result = FakeResult()
    post_fn = MagicMock()

    mixin.run_test_fix_loop(
        result=result,
        run_tests_fn=lambda r: _run_tests_fail(r),
        get_all_files_fn=lambda: {"app/foo.py": "broken"},
        write_files_fn=MagicMock(),
        commit_fn=MagicMock(return_value=True),
        post_comment_fn=post_fn,
        fix_fn=MagicMock(return_value={"app/foo.py": "fix"}),
        max_retries=3,
    )

    assert result.test_retry_count == 3
    post_fn.assert_called_once()
    msg = post_fn.call_args[0][0]
    assert "Automatic Test Fix Exhausted" in msg
    assert "Human review required" in msg
    assert "Attempt 1" in msg


def test_breaks_on_empty_patch():
    mixin = _make_mixin()
    result = FakeResult()
    fix_fn = MagicMock(return_value={})
    run_count = [0]

    def run_tests(r):
        run_count[0] += 1
        _run_tests_fail(r)

    mixin.run_test_fix_loop(
        result=result,
        run_tests_fn=run_tests,
        get_all_files_fn=lambda: {},
        write_files_fn=MagicMock(),
        commit_fn=MagicMock(return_value=True),
        post_comment_fn=MagicMock(),
        fix_fn=fix_fn,
        max_retries=5,
    )

    # Only the initial run + 1 fix attempt (which returned {}) — loop breaks
    assert run_count[0] == 1
    assert result.test_retry_count == 0


def test_retry_count_and_history_accurate():
    mixin = _make_mixin()
    result = FakeResult()

    def fix_fn(failure, files):
        return {"app/a.py": "v1", "app/b.py": "v2"}

    mixin.run_test_fix_loop(
        result=result,
        run_tests_fn=lambda r: _run_tests_fail(r),
        get_all_files_fn=lambda: {},
        write_files_fn=MagicMock(),
        commit_fn=MagicMock(return_value=True),
        post_comment_fn=MagicMock(),
        fix_fn=fix_fn,
        max_retries=2,
    )

    assert result.test_retry_count == 2
    assert len(result.test_fix_history) == 2
    assert "2 file(s) patched" in result.test_fix_history[0]
    assert "2 file(s) patched" in result.test_fix_history[1]
