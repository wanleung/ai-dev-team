"""Tests for github_client.py PR read, tree, and merge conflict paths.

Tests for GithubClient API methods:
- get_pr_review_comments: inline PR comments
- get_pr_reviews: review-level submissions (APPROVED, CHANGES_REQUESTED, etc.)
- get_pr_files: list of changed files in a PR
- get_file_content: decoded file content at a specific ref
- get_full_tree: recursive file tree
- merge_base_into_branch: merge operations with conflict handling
- search_files: glob pattern matching on file paths
"""
import base64
import pytest
from unittest.mock import MagicMock, patch
from github_client import GitHubClient


@pytest.fixture
def client():
    """Return a GithubClient with fake token and repo."""
    return GitHubClient("owner/repo", github_token="fake-token")


def test_get_pr_review_comments_success(client):
    """get_pr_review_comments returns list of inline review comments."""
    mock_comments = [
        {
            "id": 1234,
            "body": "Looks good to me!",
            "path": "src/main.py",
            "line": 10,
            "user": {"login": "reviewer1"},
        },
        {
            "id": 5678,
            "body": "Consider refactoring this",
            "path": "src/utils.py",
            "line": 42,
            "user": {"login": "reviewer2"},
        },
    ]
    
    with patch.object(client, "_request", return_value=mock_comments) as mock_req:
        comments = client.get_pr_review_comments(7)
    
    mock_req.assert_called_once_with("GET", "/repos/owner/repo/pulls/7/comments")
    assert len(comments) == 2
    assert comments[0]["body"] == "Looks good to me!"
    assert comments[0]["path"] == "src/main.py"
    assert comments[1]["body"] == "Consider refactoring this"
    assert comments[1]["path"] == "src/utils.py"


def test_get_pr_review_comments_empty(client):
    """get_pr_review_comments returns empty list when no comments exist."""
    with patch.object(client, "_request", return_value=[]) as mock_req:
        comments = client.get_pr_review_comments(42)
    
    mock_req.assert_called_once_with("GET", "/repos/owner/repo/pulls/42/comments")
    assert comments == []


def test_get_pr_reviews_success(client):
    """get_pr_reviews returns list of review submissions with state."""
    mock_reviews = [
        {
            "id": 100,
            "state": "APPROVED",
            "user": {"login": "senior-dev"},
            "body": "Ship it!",
        },
        {
            "id": 101,
            "state": "CHANGES_REQUESTED",
            "user": {"login": "architect"},
            "body": "Please address the security concerns",
        },
        {
            "id": 102,
            "state": "COMMENTED",
            "user": {"login": "junior-dev"},
            "body": "Just some minor notes",
        },
    ]
    
    with patch.object(client, "_request", return_value=mock_reviews) as mock_req:
        reviews = client.get_pr_reviews(15)
    
    mock_req.assert_called_once_with("GET", "/repos/owner/repo/pulls/15/reviews")
    assert len(reviews) == 3
    assert reviews[0]["state"] == "APPROVED"
    assert reviews[1]["state"] == "CHANGES_REQUESTED"
    assert reviews[2]["state"] == "COMMENTED"


def test_get_pr_files_success(client):
    """get_pr_files returns list of changed files with metadata."""
    mock_files = [
        {
            "filename": "src/app.py",
            "status": "modified",
            "additions": 45,
            "deletions": 12,
            "changes": 57,
        },
        {
            "filename": "tests/test_app.py",
            "status": "added",
            "additions": 120,
            "deletions": 0,
            "changes": 120,
        },
        {
            "filename": "README.md",
            "status": "modified",
            "additions": 3,
            "deletions": 1,
            "changes": 4,
        },
    ]
    
    with patch.object(client, "_request", return_value=mock_files) as mock_req:
        files = client.get_pr_files(99)
    
    mock_req.assert_called_once_with("GET", "/repos/owner/repo/pulls/99/files")
    assert len(files) == 3
    assert files[0]["filename"] == "src/app.py"
    assert files[1]["filename"] == "tests/test_app.py"
    assert files[2]["filename"] == "README.md"


def test_get_file_content_success(client):
    """get_file_content decodes and returns file content from base64."""
    content_text = "def hello():\n    print('Hello, world!')\n"
    encoded_content = base64.b64encode(content_text.encode("utf-8")).decode("ascii")
    
    mock_response = {
        "type": "file",
        "encoding": "base64",
        "size": len(content_text),
        "name": "main.py",
        "path": "src/main.py",
        "content": encoded_content,
        "sha": "abc123def456",
    }
    
    with patch.object(client, "_request", return_value=mock_response) as mock_req:
        content = client.get_file_content("src/main.py", "main")
    
    mock_req.assert_called_once_with(
        "GET",
        "/repos/owner/repo/contents/src/main.py",
        params={"ref": "main"},
    )
    assert content == content_text


def test_get_file_content_not_found(client):
    """get_file_content returns None when file doesn't exist (404)."""
    with patch.object(client, "_request", side_effect=RuntimeError("404 Not Found")) as mock_req:
        content = client.get_file_content("nonexistent.py", "main")
    
    mock_req.assert_called_once()
    assert content is None


def test_get_file_content_decode_failure(client):
    """get_file_content returns None when base64 decode fails."""
    mock_response = {
        "type": "file",
        "content": "not-valid-base64!@#$",
    }
    
    with patch.object(client, "_request", return_value=mock_response):
        content = client.get_file_content("binary.dat", "main")
    
    assert content is None


def test_get_full_tree_success(client):
    """get_full_tree returns list of file paths (blobs only)."""
    mock_tree_data = {
        "sha": "tree-sha-123",
        "url": "https://api.github.com/repos/owner/repo/git/trees/tree-sha-123",
        "tree": [
            {"path": "README.md", "type": "blob", "size": 1024, "sha": "blob1"},
            {"path": "src", "type": "tree", "sha": "tree1"},
            {"path": "src/app.py", "type": "blob", "size": 2048, "sha": "blob2"},
            {"path": "src/utils.py", "type": "blob", "size": 512, "sha": "blob3"},
            {"path": "tests", "type": "tree", "sha": "tree2"},
            {"path": "tests/test_app.py", "type": "blob", "size": 3072, "sha": "blob4"},
        ],
        "truncated": False,
    }
    
    with patch.object(client, "get_default_branch", return_value="main"):
        with patch.object(client, "_request", return_value=mock_tree_data) as mock_req:
            tree = client.get_full_tree()
    
    mock_req.assert_called_once_with(
        "GET",
        "/repos/owner/repo/git/trees/main",
        params={"recursive": "1"},
    )
    assert len(tree) == 6  # blobs + trees both returned
    blobs = [e for e in tree if e["type"] == "blob"]
    trees_in_result = [e for e in tree if e["type"] == "tree"]
    assert all(e["size"] > 0 for e in blobs)
    assert all(e["size"] == 0 for e in trees_in_result)


def test_get_full_tree_with_ref(client):
    """get_full_tree uses provided ref instead of default branch."""
    mock_tree_data = {
        "sha": "feature-tree-sha",
        "tree": [
            {"path": "feature.py", "type": "blob", "size": 500, "sha": "blobX"},
        ],
        "truncated": False,
    }
    
    with patch.object(client, "_request", return_value=mock_tree_data) as mock_req:
        tree = client.get_full_tree(ref="feature-branch")
    
    mock_req.assert_called_once_with(
        "GET",
        "/repos/owner/repo/git/trees/feature-branch",
        params={"recursive": "1"},
    )
    assert len(tree) == 1
    assert tree[0]["path"] == "feature.py"


def test_get_full_tree_truncated(client):
    """get_full_tree returns empty list when tree is truncated."""
    mock_tree_data = {
        "sha": "large-tree-sha",
        "tree": [
            {"path": "file1.py", "type": "blob", "size": 100, "sha": "blob1"},
        ],
        "truncated": True,  # Repo too large
    }
    
    with patch.object(client, "get_default_branch", return_value="main"):
        with patch.object(client, "_request", return_value=mock_tree_data):
            tree = client.get_full_tree()
    
    assert tree == []


def test_get_full_tree_error(client):
    """get_full_tree returns empty list on any error and logs warning."""
    with patch.object(client, "get_default_branch", return_value="main"):
        with patch.object(client, "_request", side_effect=RuntimeError("API Error")):
            tree = client.get_full_tree()
    
    assert tree == []


def test_merge_base_into_branch_success(client):
    """merge_base_into_branch returns 201 on successful merge."""
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    
    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        status = client.merge_base_into_branch("main", "feature-branch", "Merge main into feature")
    
    assert status == 201
    mock_post.assert_called_once_with(
        "https://api.github.com/repos/owner/repo/merges",
        json={
            "base": "feature-branch",
            "head": "main",
            "commit_message": "Merge main into feature",
        },
    )


def test_merge_base_into_branch_up_to_date(client):
    """merge_base_into_branch returns 204 when already up to date."""
    mock_resp = MagicMock()
    mock_resp.status_code = 204
    
    with patch.object(client._session, "post", return_value=mock_resp):
        status = client.merge_base_into_branch("main", "feature-branch")
    
    assert status == 204


def test_merge_base_into_branch_conflict(client):
    """merge_base_into_branch returns 409 on merge conflict."""
    mock_resp = MagicMock()
    mock_resp.status_code = 409
    mock_resp.text = "Merge conflict"
    
    with patch.object(client._session, "post", return_value=mock_resp):
        status = client.merge_base_into_branch("main", "feature-branch")
    
    assert status == 409


def test_merge_base_into_branch_unexpected_error(client):
    """merge_base_into_branch raises RuntimeError on unexpected status."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"
    
    with patch.object(client._session, "post", return_value=mock_resp):
        with pytest.raises(RuntimeError) as exc_info:
            client.merge_base_into_branch("main", "feature-branch")
    
    assert "GitHub merges API failed [500]" in str(exc_info.value)


def test_search_files_success(client):
    """search_files returns matching file paths (blobs only)."""
    mock_tree_data = {
        "sha": "tree-sha",
        "tree": [
            {"path": "README.md", "type": "blob"},
            {"path": "docs/README.md", "type": "blob"},
            {"path": "src/app.py", "type": "blob"},
            {"path": "src/utils.py", "type": "blob"},
            {"path": "tests/test_app.py", "type": "blob"},
            {"path": "src", "type": "tree"},  # should be excluded
        ],
    }
    
    with patch.object(client, "get_default_branch", return_value="main"):
        with patch.object(client, "_request", return_value=mock_tree_data):
            # Search for README.md files
            results = client.search_files("README.md")
    
    # Pattern "README.md" matches both "README.md" and "docs/README.md" (right-anchored)
    assert len(results) == 2
    assert "README.md" in results
    assert "docs/README.md" in results


def test_search_files_with_wildcard(client):
    """search_files supports glob patterns with wildcards."""
    mock_tree_data = {
        "sha": "tree-sha",
        "tree": [
            {"path": "src/app.py", "type": "blob"},
            {"path": "src/utils.py", "type": "blob"},
            {"path": "tests/test_app.py", "type": "blob"},
            {"path": "README.md", "type": "blob"},
        ],
    }
    
    with patch.object(client, "get_default_branch", return_value="main"):
        with patch.object(client, "_request", return_value=mock_tree_data):
            # Search for Python files
            results = client.search_files("*.py")
    
    assert len(results) == 3
    assert "src/app.py" in results
    assert "src/utils.py" in results
    assert "tests/test_app.py" in results
    assert "README.md" not in results


def test_search_files_with_ref(client):
    """search_files uses provided ref for tree lookup."""
    mock_tree_data = {
        "sha": "feature-tree",
        "tree": [
            {"path": "feature.py", "type": "blob"},
        ],
    }
    
    with patch.object(client, "_request", return_value=mock_tree_data) as mock_req:
        results = client.search_files("*.py", ref="feature-branch")
    
    mock_req.assert_called_once_with(
        "GET",
        "/repos/owner/repo/git/trees/feature-branch",
        params={"recursive": "1"},
    )
    assert len(results) == 1
    assert "feature.py" in results


def test_search_files_no_matches(client):
    """search_files returns empty list when no files match."""
    mock_tree_data = {
        "sha": "tree-sha",
        "tree": [
            {"path": "README.md", "type": "blob"},
            {"path": "LICENSE", "type": "blob"},
        ],
    }
    
    with patch.object(client, "get_default_branch", return_value="main"):
        with patch.object(client, "_request", return_value=mock_tree_data):
            results = client.search_files("*.java")
    
    assert results == []


def test_search_files_excludes_trees(client):
    """search_files returns only blobs, not tree entries."""
    mock_tree_data = {
        "sha": "tree-sha",
        "tree": [
            {"path": "src", "type": "tree"},
            {"path": "src/app.py", "type": "blob"},
            {"path": "tests", "type": "tree"},
            {"path": "tests/test.py", "type": "blob"},
        ],
    }
    
    with patch.object(client, "get_default_branch", return_value="main"):
        with patch.object(client, "_request", return_value=mock_tree_data):
            results = client.search_files("*")
    
    # Only blobs should be returned
    assert "src/app.py" in results
    assert "tests/test.py" in results
    assert "src" not in results
    assert "tests" not in results
