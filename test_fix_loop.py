"""TestFixLoopMixin — shared retry loop for test-failure auto-fixing.

Both Orchestrator and BugFixOrchestrator inherit this mixin.
"""
from __future__ import annotations

from typing import Callable

from rich.console import Console

console = Console()


class TestFixLoopMixin:
    """Mixin providing run_test_fix_loop() for orchestrators with an engineer agent.

    The mixin holds no state. All side-effectful operations are injected as
    callables so the mixin can be unit-tested independently.
    """

    def run_test_fix_loop(
        self,
        result,
        run_tests_fn: Callable,
        get_all_files_fn: Callable[[], dict],
        write_files_fn: Callable[[dict], None],
        commit_fn: Callable[[int, dict], bool],
        post_comment_fn: Callable[[str], None],
        fix_fn: Callable[[str, dict], dict],
        max_retries: int = 5,
    ) -> None:
        """Run tests, then retry engineer fixes up to max_retries times on failure.

        Args:
            result:            PipelineResult or BugFixResult (duck-typed).
                               Must have: tests_passed (bool|None), test_results (str),
                               test_retry_count (int), test_fix_history (list[str]).
            run_tests_fn:      callable(result) — runs tests and sets
                               result.tests_passed + result.test_results.
            get_all_files_fn:  callable() → dict[str, str] of current files on disk.
            write_files_fn:    callable(patches: dict) — writes patched files to disk.
            commit_fn:         callable(attempt: int, patches: dict) → bool.
                               Should commit the patches; return True on success,
                               False if nothing changed (triggers early break).
            post_comment_fn:   callable(message: str) — post to PR or Issue.
            fix_fn:            callable(failure_output: str, all_files: dict) → dict.
                               Calls engineer.fix_failures(); returns patched files.
            max_retries:       Maximum fix attempts before giving up.
        """
        run_tests_fn(result)

        if getattr(result, "tests_passed", None) is True:
            return

        for attempt in range(1, max_retries + 1):
            console.print(f"    🔁 Test fix attempt {attempt}/{max_retries}…")

            all_files = get_all_files_fn()
            failure_output = getattr(result, "test_results", "") or ""

            patches = fix_fn(failure_output, all_files)
            if not patches:
                console.print(
                    "    ⚠️  Engineer returned no patches — stopping retry loop."
                )
                break

            write_files_fn(patches)

            committed = commit_fn(attempt, patches)
            if not committed:
                console.print(
                    "    ⚠️  No code changes after fix — stopping retry loop."
                )
                break

            result.test_fix_history.append(
                f"Attempt {attempt}: {len(patches)} file(s) patched"
            )
            result.test_retry_count += 1

            run_tests_fn(result)
            if getattr(result, "tests_passed", None) is True:
                console.print(
                    f"    ✅ Tests passed after {attempt} fix attempt(s)."
                )
                return

        if getattr(result, "tests_passed", None) is not True:
            console.print(
                f"    ⚠️  All {result.test_retry_count} fix attempt(s) failed."
            )
            history_md = "\n".join(
                f"- {h}" for h in result.test_fix_history
            ) or "(no attempts completed)"
            failure_lines = (
                getattr(result, "test_results", "") or ""
            ).strip().splitlines()
            truncated = (
                "\n".join(failure_lines[-60:])
                if len(failure_lines) > 60
                else "\n".join(failure_lines)
            )
            message = (
                f"## ⚠️ Automatic Test Fix Exhausted\n\n"
                f"After {result.test_retry_count} attempt(s), tests are still "
                f"failing. Human review required.\n\n"
                f"### Fix History\n\n{history_md}\n\n"
                f"### Final Failure Output\n\n```\n{truncated}\n```"
            )
            post_comment_fn(message)
