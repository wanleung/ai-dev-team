"""Tests for orchestrator revision helpers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from agents.conflict_resolver import PRContext, ResolveResult
from orchestrator import Orchestrator


@pytest.fixture
def orch(tmp_path):
    """Minimal orchestrator with no real API calls."""
    o = Orchestrator.__new__(Orchestrator)
    o.max_revisions = 3
    o.github = MagicMock()
    o.target_github = MagicMock()
    o.target_github.token = "ghp_test"
    o.target_github.repo = "owner/repo"
    o._github_token = "tok"
    o.engineer = MagicMock()
    o.reviewer = MagicMock()
    o.qa = MagicMock()
    o.skill_loader = None
    o._update_branch_enabled = False
    o.model = "gpt-4.1"
    o.senior_model = None
    o.conflict_resolver_model = None
    o.agent_kwargs = {"github_token": "tok"}
    return o


# ── _get_revision_number ──────────────────────────────────────────────────────

def test_get_revision_number_none(orch):
    assert orch._get_revision_number([]) == 0

def test_get_revision_number_single(orch):
    assert orch._get_revision_number(["ai-generated", "ai-revision-2"]) == 2

def test_get_revision_number_highest(orch):
    assert orch._get_revision_number(["ai-revision-1", "ai-revision-3", "ai-revision-2"]) == 3


# ── _extract_issue_number ─────────────────────────────────────────────────────

def test_extract_issue_number_closes(orch):
    assert orch._extract_issue_number("Some text\nCloses #42\nmore") == 42

def test_extract_issue_number_related(orch):
    assert orch._extract_issue_number("Related to #7") == 7

def test_extract_issue_number_none(orch):
    assert orch._extract_issue_number("No reference here") is None


# ── _collect_pr_feedback ──────────────────────────────────────────────────────

def test_collect_pr_feedback_filters_bot(orch):
    orch.target_github.get_pr_review_comments.return_value = [
        {"user": {"login": "alice"}, "body": "Fix the import", "path": "src/main.py", "line": 10},
        {"user": {"login": "github-actions[bot]"}, "body": "Bot comment", "path": "src/main.py", "line": 1},
    ]
    orch.target_github.get_pr_reviews.return_value = [
        {"user": {"login": "bob"}, "body": "Please add tests", "state": "CHANGES_REQUESTED"},
        {"user": {"login": "github-actions[bot]"}, "body": "Bot review", "state": "COMMENTED"},
    ]
    orch.target_github.get_issue_comments.return_value = []
    feedback = orch._collect_pr_feedback(pr_number=1)
    assert len(feedback) == 2
    assert all(f["author"] != "github-actions[bot]" for f in feedback)
    bodies = [f["body"] for f in feedback]
    assert "Fix the import" in bodies
    assert "Please add tests" in bodies


def test_collect_pr_feedback_empty_when_all_bot(orch):
    orch.target_github.get_pr_review_comments.return_value = [
        {"user": {"login": "github-actions[bot]"}, "body": "Bot", "path": "a.py", "line": 1},
    ]
    orch.target_github.get_pr_reviews.return_value = []
    orch.target_github.get_issue_comments.return_value = []
    assert orch._collect_pr_feedback(1) == []


def test_collect_pr_feedback_includes_regular_comments(orch):
    """Regular PR issue comments (e.g. test failure reports) should be included."""
    orch.target_github.get_pr_review_comments.return_value = []
    orch.target_github.get_pr_reviews.return_value = []
    orch.target_github.get_issue_comments.return_value = [
        {"user": {"login": "wanleung"}, "body": "## 🏃 Test Run Results\n\nSome tests failed: TypeError: ..."},
        {"user": {"login": "github-actions[bot]"}, "body": "CI passed"},
    ]
    feedback = orch._collect_pr_feedback(1)
    assert len(feedback) == 1
    assert feedback[0]["author"] == "wanleung"
    assert "Test Run Results" in feedback[0]["body"]
    assert feedback[0]["location"] == "comment"


def test_collect_pr_feedback_includes_copilot_pr_reviewer(orch):
    """copilot-pull-request-reviewer posts useful suggestions and must NOT be filtered out."""
    orch.target_github.get_pr_review_comments.return_value = []
    orch.target_github.get_pr_reviews.return_value = [
        {"user": {"login": "copilot-pull-request-reviewer"}, "body": "requirements-test.txt has markdown that breaks pip"},
    ]
    orch.target_github.get_issue_comments.return_value = []
    feedback = orch._collect_pr_feedback(1)
    assert len(feedback) == 1
    assert feedback[0]["author"] == "copilot-pull-request-reviewer"


# ── _format_feedback ──────────────────────────────────────────────────────────

def test_format_feedback_includes_all_items(orch):
    items = [
        {"author": "alice", "body": "Fix the import", "location": "src/main.py line 10"},
        {"author": "bob", "body": "Add docstring", "location": "review"},
    ]
    md = orch._format_feedback(items)
    assert "Fix the import" in md
    assert "Add docstring" in md
    assert "alice" in md
    assert "bob" in md


# ── _parse_merge_directives ───────────────────────────────────────────────────

def test_parse_merge_directives_explicit_directive(orch):
    feedback = [
        {"author": "wanleung", "body": "merge-branch: feature/agent/1-static-blog-platform", "location": "comment"},
    ]
    result = orch._parse_merge_directives(feedback)
    assert result == ["feature/agent/1-static-blog-platform"]


def test_parse_merge_directives_backtick_branch(orch):
    feedback = [
        {"author": "wanleung", "body": "Please incorporate tests from branch `feature/agent/1-static-blog-platform` before fixing.", "location": "comment"},
    ]
    result = orch._parse_merge_directives(feedback)
    assert result == ["feature/agent/1-static-blog-platform"]


def test_parse_merge_directives_pr_number(orch):
    orch.target_github.get_pr.return_value = {"head": {"ref": "feature/agent/1-static-blog-platform"}, "base": {"ref": "master"}}
    feedback = [
        {"author": "wanleung", "body": "merge from PR #2 before fixing tests", "location": "comment"},
    ]
    result = orch._parse_merge_directives(feedback)
    orch.target_github.get_pr.assert_called_once_with(2)
    assert result == ["feature/agent/1-static-blog-platform"]


def test_parse_merge_directives_deduplicates(orch):
    feedback = [
        {"author": "alice", "body": "merge-branch: feature/tests", "location": "comment"},
        {"author": "bob", "body": "merge-branch: feature/tests", "location": "comment"},
    ]
    assert orch._parse_merge_directives(feedback) == ["feature/tests"]


def test_parse_merge_directives_empty_when_no_directives(orch):
    feedback = [
        {"author": "alice", "body": "Please fix the import error on line 10", "location": "comment"},
    ]
    assert orch._parse_merge_directives(feedback) == []


# ── _fetch_branch_files ───────────────────────────────────────────────────────

def test_fetch_branch_files_returns_file_map(orch):
    orch.target_github.get_full_tree.return_value = [
        {"type": "blob", "path": "tests/test_blog.py", "size": 1024},
        {"type": "blob", "path": "src/blog.py", "size": 512},
    ]
    orch.target_github.get_file_content.side_effect = lambda path, ref: f"content of {path}"
    result = orch._fetch_branch_files("feature/agent/1-static-blog-platform")
    assert result == {
        "tests/test_blog.py": "content of tests/test_blog.py",
        "src/blog.py": "content of src/blog.py",
    }
    orch.target_github.get_full_tree.assert_called_once_with(ref="feature/agent/1-static-blog-platform")


def test_fetch_branch_files_skips_trees(orch):
    orch.target_github.get_full_tree.return_value = [
        {"type": "tree", "path": "src", "size": 0},
        {"type": "blob", "path": "src/main.py", "size": 100},
    ]
    orch.target_github.get_file_content.return_value = "print('hello')"
    result = orch._fetch_branch_files("main")
    assert list(result.keys()) == ["src/main.py"]


def test_fetch_branch_files_skips_large_files(orch):
    orch.target_github.get_full_tree.return_value = [
        {"type": "blob", "path": "data/huge.json", "size": 300_000},
        {"type": "blob", "path": "src/small.py", "size": 100},
    ]
    orch.target_github.get_file_content.return_value = "small content"
    result = orch._fetch_branch_files("feature/x")
    assert "data/huge.json" not in result
    assert "src/small.py" in result


def test_fetch_branch_files_skips_unreadable_files(orch):
    """Files that return None from get_file_content (binary/unreadable) are silently skipped."""
    orch.target_github.get_full_tree.return_value = [
        {"type": "blob", "path": "src/code.py", "size": 500},
        {"type": "blob", "path": "data/image.png", "size": 10000},
    ]
    def _content(path, ref):
        if path == "data/image.png":
            return None  # binary/unreadable
        return "# code content"
    orch.target_github.get_file_content.side_effect = _content
    result = orch._fetch_branch_files("feature/x")
    assert "src/code.py" in result
    assert "data/image.png" not in result


# ── run_revision merge-branch integration ────────────────────────────────────

def test_run_revision_incorporates_merge_branch_files(orch):
    """When a PR comment contains 'merge-branch: X', files from X are fetched
    and committed to the implementation branch."""
    orch.target_github.get_pr.return_value = {
        "head": {"ref": "feature/impl"},
        "base": {"ref": "master"},
        "body": "Closes #1",
        "labels": [],
        "title": "Implementation",
    }
    orch.target_github.get_pr_review_comments.return_value = []
    orch.target_github.get_pr_reviews.return_value = []
    orch.target_github.get_issue_comments.return_value = [
        {
            "user": {"login": "wanleung"},
            "body": "merge-branch: feature/tests",
        }
    ]
    orch.target_github.get_pr_files.return_value = [
        {"filename": "app/main.py"}
    ]
    orch.target_github.get_file_content.side_effect = lambda path, ref: f"# {path} on {ref}"
    orch.target_github.get_full_tree.return_value = [
        {"path": "tests/test_app.py", "type": "blob", "size": 300},
    ]

    orch.engineer.run_all_modules = MagicMock(return_value={
        "all_files": {"app/main.py": "# fixed main.py"}
    })
    orch.reviewer.run = MagicMock(return_value={"verdict": "APPROVED"})
    orch.qa.run = MagicMock(return_value={"test_files": {}})

    result = orch.run_revision(pr_number=3)

    assert result["status"] == "ok"
    # tests/test_app.py from the merge branch should have been committed
    commit_calls = [call[1] for call in orch.target_github.commit_file.call_args_list]
    committed_paths = [c["path"] for c in commit_calls]
    assert "tests/test_app.py" in committed_paths


def test_run_revision_merge_branch_does_not_overwrite_existing_files(orch):
    """Merge branch files that already exist in the current PR branch are NOT overwritten."""
    orch.target_github.get_pr.return_value = {
        "head": {"ref": "feature/impl"},
        "base": {"ref": "master"},
        "body": "Closes #1",
        "labels": [],
        "title": "Implementation",
    }
    orch.target_github.get_pr_review_comments.return_value = []
    orch.target_github.get_pr_reviews.return_value = []
    orch.target_github.get_issue_comments.return_value = [
        {"user": {"login": "wanleung"}, "body": "merge-branch: feature/tests"},
    ]
    orch.target_github.get_pr_files.return_value = [
        {"filename": "app/main.py"},
    ]
    # Both branches have app/main.py; merge branch also has tests/test_app.py
    def get_content(path, ref):
        if ref == "feature/impl":
            return "# impl main.py"
        if path == "app/main.py":
            return "# merge main.py"  # should NOT overwrite
        return "# test content"
    orch.target_github.get_file_content.side_effect = get_content
    orch.target_github.get_full_tree.return_value = [
        {"path": "app/main.py", "type": "blob", "size": 100},
        {"path": "tests/test_app.py", "type": "blob", "size": 200},
    ]

    from unittest.mock import MagicMock
    orch.engineer.run_all_modules = MagicMock(return_value={
        "all_files": {"app/main.py": "# fixed main.py"}
    })
    orch.reviewer.run = MagicMock(return_value={"verdict": "APPROVED"})
    orch.qa.run = MagicMock(return_value={"test_files": {}})

    result = orch.run_revision(pr_number=3)
    assert result["status"] == "ok"

    commit_calls = {c[1]["path"]: c[1]["content"] for c in orch.target_github.commit_file.call_args_list}
    # tests/test_app.py from merge branch should be committed (new file)
    assert "tests/test_app.py" in commit_calls
    # app/main.py from merge branch should NOT overwrite — engineer's version should be used
    if "app/main.py" in commit_calls:
        assert commit_calls["app/main.py"] == "# fixed main.py"


def test_run_revision_no_merge_branch_when_no_directive(orch):
    """Without a merge-branch directive, _fetch_branch_files is never called."""
    orch.target_github.get_pr.return_value = {
        "head": {"ref": "feature/impl"},
        "base": {"ref": "master"},
        "body": "Closes #1",
        "labels": [],
        "title": "Implementation",
    }
    orch.target_github.get_pr_review_comments.return_value = [
        {"user": {"login": "alice"}, "body": "Fix the import", "path": "app/main.py", "line": 5},
    ]
    orch.target_github.get_pr_reviews.return_value = []
    orch.target_github.get_issue_comments.return_value = []
    orch.target_github.get_pr_files.return_value = [{"filename": "app/main.py"}]
    orch.target_github.get_file_content.return_value = "# original"

    orch.engineer.run_all_modules = MagicMock(return_value={
        "all_files": {"app/main.py": "# fixed"}
    })
    orch.reviewer.run = MagicMock(return_value={"verdict": "APPROVED"})
    orch.qa.run = MagicMock(return_value={"test_files": {}})

    result = orch.run_revision(pr_number=3)

    assert result["status"] == "ok"
    # get_full_tree should never be called if no merge directives
    orch.target_github.get_full_tree.assert_not_called()


# ── _fetch_design_from_issue ──────────────────────────────────────────────────

def test_fetch_design_from_issue_finds_architect_comment(orch):
    orch.github.get_issue_comments.return_value = [
        {"body": "## 📋 PRD\n\nSome product doc", "user": {"login": "github-actions[bot]"}},
        {"body": "## 🏗️ System Design (Architect)\n\nThe full architecture here", "user": {"login": "github-actions[bot]"}},
        {"body": "Random human comment", "user": {"login": "alice"}},
    ]
    design = orch._fetch_design_from_issue(issue_number=5)
    assert "System Design" in design
    assert "architecture here" in design


def test_fetch_design_from_issue_returns_empty_string_when_not_found(orch):
    orch.github.get_issue_comments.return_value = [
        {"body": "Just a comment", "user": {"login": "alice"}},
    ]
    assert orch._fetch_design_from_issue(5) == ""


# ── run_revision ──────────────────────────────────────────────────────────────

def test_run_revision_exits_when_max_revisions_reached(orch):
    orch.target_github.get_pr.return_value = {
        "head": {"ref": "feature/my-app"},
        "base": {"ref": "master"},
        "body": "Closes #3",
        "labels": [{"name": "ai-generated"}, {"name": "ai-revision-3"}],
        "title": "My App",
    }
    result = orch.run_revision(pr_number=10)
    assert result["status"] == "max_revisions_reached"
    orch.target_github.add_pr_comment.assert_called_once()
    comment_body = orch.target_github.add_pr_comment.call_args[0][1]
    assert "Max revisions reached" in comment_body
    orch.target_github.get_pr_files.assert_not_called()
    orch.target_github.commit_file.assert_not_called()


def test_run_revision_exits_when_no_human_feedback(orch):
    orch.target_github.get_pr.return_value = {
        "head": {"ref": "feature/my-app"},
        "base": {"ref": "master"},
        "body": "Closes #3",
        "labels": [{"name": "ai-generated"}],
        "title": "My App",
    }
    orch.target_github.get_pr_review_comments.return_value = []
    orch.target_github.get_pr_reviews.return_value = []
    result = orch.run_revision(pr_number=10)
    assert result["status"] == "no_feedback"
    orch.target_github.get_pr_files.assert_not_called()
    orch.target_github.commit_file.assert_not_called()
    orch.target_github.add_pr_comment.assert_not_called()

# ── _parse_update_directive ───────────────────────────────────────────────────

def test_parse_update_directive_detects_update_branch(orch):
    feedback = [
        {"body": "Looks good overall", "author": "alice"},
        {"body": "update-branch", "author": "alice"},
    ]
    assert orch._parse_update_directive(feedback) is True


def test_parse_update_directive_detects_colon_form(orch):
    feedback = [{"body": "update-branch: true", "author": "alice"}]
    assert orch._parse_update_directive(feedback) is True


def test_parse_update_directive_no_match(orch):
    feedback = [{"body": "Please fix the tests", "author": "alice"}]
    assert orch._parse_update_directive(feedback) is False


# ── _update_branch_from_base ──────────────────────────────────────────────────

def test_update_branch_already_up_to_date(orch):
    """merge returns 204 → status 'up_to_date', no commit."""
    orch.target_github.merge_base_into_branch.return_value = 204
    result = orch._update_branch_from_base("feature/agent/1-my-pr")
    assert result["status"] == "up_to_date"
    orch.target_github.commit_file.assert_not_called()


def test_update_branch_clean_merge(orch):
    """merge returns 201 → status 'merged', no conflict resolution needed."""
    orch.target_github.merge_base_into_branch.return_value = 201
    result = orch._update_branch_from_base("feature/agent/1-my-pr")
    assert result["status"] == "merged"
    orch.target_github.commit_file.assert_not_called()


def test_update_branch_conflict_ai_resolves(orch):
    """409 → ConflictResolverAgent resolves files → retry returns 201 → status 'merged'."""
    orch.target_github.merge_base_into_branch.side_effect = [409, 201]

    pr_ctx = PRContext(pr_title="My PR", pr_body="body", design_doc="", skills="")
    resolved_result = ResolveResult(status="resolved", resolved_files=["app/main.py"])

    with patch("orchestrator.ConflictResolverAgent") as MockResolver:
        instance = MockResolver.return_value
        instance.resolve.return_value = resolved_result

        result = orch._update_branch_from_base(
            "feature/agent/1-my-pr", pr_number=42, pr_context=pr_ctx
        )

    assert result["status"] == "merged"
    # ConflictResolverAgent was constructed with correct model + kwargs
    MockResolver.assert_called_once()
    # resolve() was invoked with the right branches and pr_context
    instance.resolve.assert_called_once_with(
        repo_url="https://ghp_test@github.com/owner/repo.git",
        head_branch="feature/agent/1-my-pr",
        base_branch="master",
        pr_context=pr_ctx,
    )
    # Retry merge was attempted after resolution
    assert orch.target_github.merge_base_into_branch.call_count == 2


def test_update_branch_conflict_fallback(orch):
    """409 → ConflictResolverAgent resolves → retry still 409 → posts PR comment, returns 'conflict'."""
    orch.target_github.merge_base_into_branch.side_effect = [409, 409]

    pr_ctx = PRContext(pr_title="My PR", pr_body="body", design_doc="", skills="")
    # Resolver reports success but the retry merge still fails
    resolved_result = ResolveResult(status="resolved", resolved_files=["src/utils.py"])

    with patch("orchestrator.ConflictResolverAgent") as MockResolver:
        instance = MockResolver.return_value
        instance.resolve.return_value = resolved_result

        result = orch._update_branch_from_base(
            "feature/agent/1-my-pr", pr_number=42, pr_context=pr_ctx
        )

    assert result["status"] == "conflict"
    assert "src/utils.py" in result["conflicting_files"]
    orch.target_github.add_pr_comment.assert_called_once()
    comment_body = orch.target_github.add_pr_comment.call_args[0][1]
    assert "resolve these conflicts manually" in comment_body
    assert "src/utils.py" in comment_body


def test_update_branch_conflict_no_pr_number(orch):
    """409 with pr_number=None → no crash, no PR comment, returns conflict."""
    orch.target_github.merge_base_into_branch.return_value = 409
    result = orch._update_branch_from_base("feature/agent/1-my-pr", pr_number=None)
    assert result["status"] == "conflict"
    orch.target_github.get_pr_files.assert_not_called()
    orch.target_github.add_pr_comment.assert_not_called()


# ── run_revision step 0: auto-update branch ───────────────────────────────────

def _make_revision_mocks(orch, pr_number=42, head_branch="feature/agent/1-fix"):
    """Set up minimal mocks for run_revision() to reach step 3 without errors."""
    orch.target_github.get_pr.return_value = {
        "number": pr_number,
        "head": {"ref": head_branch},
        "base": {"ref": "master"},
        "body": "",
        "labels": [],
    }
    orch.target_github.get_issue_comments.return_value = []
    orch.target_github.get_pr_review_comments.return_value = []
    orch.target_github.get_pr_reviews.return_value = []
    orch.target_github.get_pr_files.return_value = []
    orch.target_github.get_file_content.return_value = None
    orch.engineer.run_all_modules.return_value = MagicMock(
        all_files={}, structured_files={}, modules={}
    )
    orch.reviewer.run.return_value = MagicMock(issues=[], structured_files={})
    orch.qa.run.return_value = MagicMock(issues=[], structured_files={})
    orch._fetch_design_from_issue = MagicMock(return_value="")
    orch._get_revision_number = MagicMock(return_value=0)
    orch._format_feedback = MagicMock(return_value="feedback md")
    orch._extract_issue_number = MagicMock(return_value=None)
    orch._parse_merge_directives = MagicMock(return_value=[])


def test_run_revision_skips_update_when_disabled(orch):
    """update_branch_enabled=False → merge_base_into_branch never called."""
    orch._update_branch_enabled = False
    _make_revision_mocks(orch)
    orch.target_github.get_issue_comments.return_value = [
        {"body": "update-branch", "user": {"login": "alice"}}
    ]
    # Provide at least one feedback item so run_revision doesn't return early
    orch.target_github.get_pr_review_comments.return_value = [
        {"body": "Fix the tests", "user": {"login": "alice"}, "path": "x.py", "line": 1}
    ]
    orch.run_revision(42)
    orch.target_github.merge_base_into_branch.assert_not_called()


def test_run_revision_skips_update_when_no_directive(orch):
    """Enabled but no 'update-branch' comment → merge_base_into_branch never called."""
    orch._update_branch_enabled = True
    _make_revision_mocks(orch)
    orch.target_github.get_issue_comments.return_value = [
        {"body": "Please fix the null pointer", "user": {"login": "alice"}}
    ]
    orch.target_github.get_pr_review_comments.return_value = [
        {"body": "Fix the tests", "user": {"login": "alice"}, "path": "x.py", "line": 1}
    ]
    orch.run_revision(42)
    orch.target_github.merge_base_into_branch.assert_not_called()


def test_run_revision_aborts_on_conflict(orch):
    """update-branch directive + enabled + conflict → run_revision returns conflict status."""
    orch._update_branch_enabled = True
    _make_revision_mocks(orch)
    orch.target_github.get_issue_comments.return_value = [
        {"body": "update-branch", "user": {"login": "alice"}}
    ]
    # First merge → 409 conflict; ConflictResolverAgent resolves (empty files); retry → still 409
    orch.target_github.merge_base_into_branch.side_effect = [409, 409]

    resolved_result = ResolveResult(status="resolved", resolved_files=[])

    with patch("orchestrator.ConflictResolverAgent") as MockResolver:
        instance = MockResolver.return_value
        instance.resolve.return_value = resolved_result

        result = orch.run_revision(42)

    assert result["status"] == "conflict"
    orch.target_github.add_pr_comment.assert_called_once()
    assert orch.target_github.merge_base_into_branch.call_count == 2
    orch.engineer.run_all_modules.assert_not_called()


def test_run_revision_updates_then_proceeds(orch):
    """update-branch succeeds (201) → run_revision continues and engineer is called."""
    orch._update_branch_enabled = True
    _make_revision_mocks(orch)
    orch.target_github.get_issue_comments.return_value = [
        {"body": "update-branch", "user": {"login": "alice"}}
    ]
    orch.target_github.get_pr_review_comments.return_value = [
        {"body": "Fix the tests", "user": {"login": "bob"}, "path": "x.py", "line": 1}
    ]
    orch.target_github.merge_base_into_branch.return_value = 201

    orch.run_revision(42)

    # Merge was attempted once (clean 201, no retry needed)
    orch.target_github.merge_base_into_branch.assert_called_once()
    # Engineer was invoked to process the feedback
    orch.engineer.run_all_modules.assert_called_once()


# ── _parse_update_directive ───────────────────────────────────────────────

def test_parse_update_directive_no_acknowledgment(orch):
    """Directive with no prior acknowledgment → pending."""
    comments = [
        {"body": "Please review this PR", "author": "alice"},
        {"body": "update-branch", "author": "alice"},
    ]
    assert orch._parse_update_directive(comments) is True


def test_parse_update_directive_already_acknowledged(orch):
    """Directive followed by bot acknowledgment → already processed."""
    comments = [
        {"body": "update-branch", "author": "alice"},
        {"body": "✅ Merged master into branch. <!-- auto-update-branch -->", "author": "bot"},
    ]
    assert orch._parse_update_directive(comments) is False


def test_parse_update_directive_new_after_acknowledged(orch):
    """Directive → ack → new directive → pending again."""
    comments = [
        {"body": "update-branch", "author": "alice"},
        {"body": "✅ Merged master. <!-- auto-update-branch -->", "author": "bot"},
        {"body": "update-branch", "author": "alice"},  # new request
    ]
    assert orch._parse_update_directive(comments) is True


def test_parse_update_directive_only_ack(orch):
    """Only acknowledgment, no directive → False."""
    comments = [
        {"body": "<!-- auto-update-branch -->", "author": "bot"},
    ]
    assert orch._parse_update_directive(comments) is False


def test_parse_update_directive_no_comments(orch):
    """Empty feedback list → False."""
    assert orch._parse_update_directive([]) is False


# ── _update_branch_from_base marker posting ───────────────────────────────

def test_update_branch_posts_marker_on_clean_merge(orch):
    """201 clean merge → bot posts acknowledgment with marker."""
    orch.target_github.merge_base_into_branch.return_value = 201
    result = orch._update_branch_from_base("feature-branch", pr_number=42)
    assert result["status"] == "merged"
    orch.target_github.add_pr_comment.assert_called_once()
    comment_body = orch.target_github.add_pr_comment.call_args[0][1]
    assert "<!-- auto-update-branch -->" in comment_body
    assert "✅" in comment_body


def test_update_branch_posts_marker_on_up_to_date(orch):
    """204 up-to-date → bot posts acknowledgment with marker."""
    orch.target_github.merge_base_into_branch.return_value = 204
    result = orch._update_branch_from_base("feature-branch", pr_number=42)
    assert result["status"] == "up_to_date"
    orch.target_github.add_pr_comment.assert_called_once()
    comment_body = orch.target_github.add_pr_comment.call_args[0][1]
    assert "<!-- auto-update-branch -->" in comment_body


def test_update_branch_no_marker_comment_without_pr_number(orch):
    """Without pr_number, no PR comment posted even on success."""
    orch.target_github.merge_base_into_branch.return_value = 201
    result = orch._update_branch_from_base("feature-branch", pr_number=None)
    assert result["status"] == "merged"
    orch.target_github.add_pr_comment.assert_not_called()


def test_update_branch_posts_marker_after_ai_resolution(orch):
    """Retry merge (201/204) after ConflictResolverAgent resolution → posts marker."""
    orch.target_github.merge_base_into_branch.side_effect = [409, 201]  # conflict, then success

    pr_ctx = PRContext(pr_title="My PR", pr_body="body", design_doc="", skills="")
    resolved_result = ResolveResult(status="resolved", resolved_files=["src/main.py"])

    with patch("orchestrator.ConflictResolverAgent") as MockResolver:
        instance = MockResolver.return_value
        instance.resolve.return_value = resolved_result

        result = orch._update_branch_from_base("feature-branch", pr_number=42, pr_context=pr_ctx)

    assert result["status"] == "merged"

    # Check that marker is posted
    assert orch.target_github.add_pr_comment.call_count == 1
    comment_body = orch.target_github.add_pr_comment.call_args[0][1]
    assert "<!-- auto-update-branch -->" in comment_body
    assert "after resolving conflicts" in comment_body or "✅" in comment_body


def test_update_branch_posts_marker_on_conflict(orch):
    """Unresolvable conflict (409 → 409) → posts marker with conflict message."""
    orch.target_github.merge_base_into_branch.side_effect = [409, 409]  # conflict, retry also fails
    orch.target_github.get_pr_files.return_value = [{"filename": "src/main.py"}]
    orch.target_github.get_file_content.side_effect = [
        "# PR version",  # head_branch
        "# master version",  # base_branch
    ]
    orch.engineer.call.return_value = "# attempted merge"
    
    result = orch._update_branch_from_base("feature-branch", pr_number=42)
    assert result["status"] == "conflict"
    
    # Check that marker is posted with conflict message
    assert orch.target_github.add_pr_comment.call_count == 1
    comment_body = orch.target_github.add_pr_comment.call_args[0][1]
    assert "<!-- auto-update-branch -->" in comment_body
    assert "⚠️" in comment_body or "conflict" in comment_body.lower()
