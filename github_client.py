"""
GitHubClient: thin wrapper around the GitHub REST API.
Uses GITHUB_TOKEN for authentication. Supports creating issues, branches,
file commits, pull requests, and comments.
"""
from __future__ import annotations

import base64
import logging
import os
import re
import time
from typing import Optional

log = logging.getLogger(__name__)

import requests
from utils import sanitise


def parse_target_repo(text: str) -> Optional[str]:
    """Extract a 'owner/repo' target directive from an issue body.

    Recognises:
        **Target repo:** owner/project   (Markdown bold with colon inside)
        Target repo: owner/project
        target-repo: owner/project

    Returns the first match, or None if not found.
    """
    if not text:
        return None
    patterns = [
        # Markdown bold with colon inside: **Target repo:** owner/repo
        r"[*][*][Tt]arget[- ][Rr]epo:[*][*]\s*([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)",
        # Plain text: Target repo: owner/repo  (colon after word, outside any markup)
        r"[Tt]arget[- ][Rr]epo\s*:\s*([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return None


class GitHubClient:
    """GitHub REST API client for the software house pipeline.

    Handles creating and updating GitHub artifacts: Issues (PRD, tasks),
    branches, file commits, Pull Requests, and review comments.
    """

    API_BASE = "https://api.github.com"

    def __init__(self, repo: str, github_token: Optional[str] = None) -> None:
        """
        Args:
            repo: Full repo name in 'owner/repo' format.
            github_token: GitHub personal access token. Falls back to GITHUB_TOKEN env var.
        """
        token = github_token or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise EnvironmentError("GITHUB_TOKEN environment variable is required.")
        if "/" not in repo:
            raise ValueError(f"repo must be 'owner/repo' format, got: {repo!r}")

        self.repo = repo
        self.token = token          # raw token needed by ConflictResolverAgent for authenticated clone URLs
        _headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._session = requests.Session()
        self._session.headers.update(_headers)

    def __del__(self) -> None:
        """Close the underlying HTTP session on garbage collection."""
        try:
            self._session.close()
        except Exception:
            pass

    # Transient HTTP status codes that should be retried
    _RETRYABLE = {429, 500, 502, 503, 504}
    _MAX_RETRIES = 4
    _RETRY_BASE = 5.0   # seconds; doubles each attempt

    def _request(self, method: str, path: str, *, max_retries: int | None = None, **kwargs) -> dict:
        url = f"{self.API_BASE}{path}"
        retries = self._MAX_RETRIES if max_retries is None else max_retries
        for attempt in range(retries):
            response = self._session.request(method, url, **kwargs)
            if response.ok:
                return response.json() if response.text else {}
            if response.status_code not in self._RETRYABLE or attempt == retries - 1:
                raise RuntimeError(sanitise(
                    f"GitHub API {method} {url} failed [{response.status_code}]: {response.text[:500]}",
                    self.token,
                ))
            wait = self._RETRY_BASE * (2 ** attempt)
            log.warning(
                "GitHub API %s %s returned %s (attempt %d/%d) — retrying in %.0fs",
                method, url, response.status_code, attempt + 1, retries, wait,
            )
            time.sleep(wait)
        raise RuntimeError(sanitise(
            f"GitHub API {method} {url} failed after {retries} attempts",
            self.token,
        ))

    # ── Issues ──────────────────────────────────────────────────────────────

    def create_issue(self, title: str, body: str, labels: Optional[list[str]] = None) -> dict:
        """Create a GitHub Issue and return the issue data (including number and url)."""
        return self._request(
            "POST",
            f"/repos/{self.repo}/issues",
            json={"title": title, "body": body, "labels": labels or []},
        )

    def add_issue_comment(self, issue_number: int, body: str) -> dict:
        """Add a comment to an existing issue."""
        return self._request(
            "POST",
            f"/repos/{self.repo}/issues/{issue_number}/comments",
            json={"body": body},
        )

    def delete_issue_comment(self, comment_id: int) -> None:
        """Delete a GitHub issue comment. Silently ignores 404 (already deleted)."""
        try:
            self._request("DELETE", f"/repos/{self.repo}/issues/comments/{comment_id}")
        except RuntimeError as exc:
            if "[404]" in str(exc):
                return
            raise

    def get_issue(self, issue_number: int) -> dict:
        """Fetch a single issue by number."""
        return self._request("GET", f"/repos/{self.repo}/issues/{issue_number}")

    def close_issue(self, issue_number: int, comment: Optional[str] = None) -> None:
        """Close an issue, optionally adding a final comment."""
        if comment:
            self.add_issue_comment(issue_number, comment)
        self._request(
            "PATCH",
            f"/repos/{self.repo}/issues/{issue_number}",
            json={"state": "closed"},
        )

    def list_issues_by_label(self, label: str) -> list[dict]:
        """Return all open issues with the given label."""
        return self._request("GET", f"/repos/{self.repo}/issues", params={"labels": label, "state": "open"})

    # ── Branches & Files ────────────────────────────────────────────────────

    def get_default_branch(self) -> str:
        """Return the name of the repo's default branch (e.g., 'main')."""
        repo_data = self._request("GET", f"/repos/{self.repo}")
        return repo_data["default_branch"]

    def is_empty(self) -> bool:
        """Return True if the repo has no commits yet."""
        try:
            repo_data = self._request("GET", f"/repos/{self.repo}")
            # GitHub sets size=0 and the ref lookup fails for empty repos
            if repo_data.get("size", 1) == 0:
                return True
            self.get_branch_sha(repo_data["default_branch"])
            return False
        except RuntimeError as e:
            if "409" in str(e) or "Git Repository is empty" in str(e):
                return True
            raise

    def initialize_repo(self, default_branch: str = "main") -> str:
        """Create an initial commit so the repo is no longer empty.

        Returns the SHA of the initial commit.
        """
        import base64 as _b64
        readme = "# Project\n\nInitialized by AI Software House.\n"
        encoded = _b64.b64encode(readme.encode()).decode("ascii")
        result = self._request(
            "PUT",
            f"/repos/{self.repo}/contents/README.md",
            json={
                "message": "chore: initial commit",
                "content": encoded,
                "branch": default_branch,
            },
        )
        return result["commit"]["sha"]

    def get_branch_sha(self, branch: str) -> str:
        """Return the latest commit SHA for a branch."""
        ref = self._request("GET", f"/repos/{self.repo}/git/ref/heads/{branch}")
        return ref["object"]["sha"]

    def create_branch(self, branch_name: str, from_branch: Optional[str] = None) -> str:
        """Create a new branch. Auto-initializes the repo if it is empty.
        If the branch already exists, reuses it (idempotent).

        Returns the branch name.
        """
        base = from_branch or self.get_default_branch()
        # If repo is empty, create an initial commit first
        try:
            sha = self.get_branch_sha(base)
        except RuntimeError as e:
            if "409" in str(e) or "Git Repository is empty" in str(e) or "422" in str(e):
                sha = self.initialize_repo(default_branch=base)
            else:
                raise
        try:
            self._request(
                "POST",
                f"/repos/{self.repo}/git/refs",
                json={"ref": f"refs/heads/{branch_name}", "sha": sha},
            )
        except RuntimeError as e:
            if "422" in str(e) and "already exists" in str(e).lower():
                # Branch exists from a previous run — that's fine, reuse it
                pass
            else:
                raise
        return branch_name

    def commit_file(
        self,
        path: str,
        content: str,
        message: str,
        branch: str,
        encoding: str = "utf-8",
        max_retries: int | None = None,
        _sha_retry: bool = True,
    ) -> dict:
        """Create or update a file in the repo on the given branch.

        Args:
            path: File path relative to repo root (e.g., 'src/main.py').
            content: Text content of the file.
            message: Git commit message.
            branch: Branch to commit to.
            encoding: Text encoding (default 'utf-8').
            max_retries: Override the default retry count.
            _sha_retry: Internal flag — False on the recursive retry to prevent loops.

        Returns:
            GitHub API response with commit and content data.
        """
        encoded = base64.b64encode(content.encode(encoding)).decode("ascii")

        payload: dict = {"message": message, "content": encoded, "branch": branch}
        try:
            existing = self._request(
                "GET",
                f"/repos/{self.repo}/contents/{path}",
                params={"ref": branch},
                max_retries=max_retries,
            )
            payload["sha"] = existing["sha"]
        except RuntimeError:
            if not _sha_retry:
                raise  # On retry path, GET failure is unexpected — abort
            pass  # First attempt: file doesn't exist yet — create it

        try:
            return self._request(
                "PUT",
                f"/repos/{self.repo}/contents/{path}",
                json=payload,
                max_retries=max_retries,
            )
        except RuntimeError as exc:
            if _sha_retry and "409" in str(exc):
                log.warning(
                    "[github_client] 409 SHA conflict on %s — fetching fresh SHA and retrying once",
                    path,
                )
                # Recurse with _sha_retry=False to prevent infinite loop.
                # The recursive call re-GETs the file to pick up the fresh SHA.
                return self.commit_file(
                    path, content, message, branch,
                    encoding=encoding,
                    max_retries=max_retries,
                    _sha_retry=False,
                )
            raise

    # ── Pull Requests ────────────────────────────────────────────────────────

    def create_pull_request(
        self,
        title: str,
        body: str,
        head: str,
        base: Optional[str] = None,
        draft: bool = False,
    ) -> dict:
        """Open a pull request. If one already exists for this head branch, returns it."""
        base_branch = base or self.get_default_branch()
        try:
            return self._request(
                "POST",
                f"/repos/{self.repo}/pulls",
                json={
                    "title": title,
                    "body": body,
                    "head": head,
                    "base": base_branch,
                    "draft": draft,
                },
            )
        except RuntimeError as e:
            if "422" in str(e) and "already exists" in str(e).lower():
                # PR already open for this branch — find and return it
                prs = self._request(
                    "GET",
                    f"/repos/{self.repo}/pulls",
                    params={"state": "open", "head": f"{self.repo.split('/')[0]}:{head}"},
                )
                if prs:
                    return prs[0]
            raise

    def convert_pull_request_to_draft(self, pull_number: int) -> None:
        """Convert an open PR to draft state via PATCH.

        GitHub supports draft=True on PATCH since 2023. Raises RuntimeError on failure.
        """
        self._request(
            "PATCH",
            f"/repos/{self.repo}/pulls/{pull_number}",
            json={"draft": True},
        )

    def add_pr_review(self, pr_number: int, body: str, event: str = "COMMENT") -> dict:
        """Add a review to a pull request.

        Args:
            pr_number: Pull request number.
            body: Review body markdown text.
            event: One of 'APPROVE', 'REQUEST_CHANGES', 'COMMENT'.
        """
        return self._request(
            "POST",
            f"/repos/{self.repo}/pulls/{pr_number}/reviews",
            json={"body": body, "event": event},
        )

    def add_pr_comment(self, pr_number: int, body: str) -> dict:
        """Add a general comment to a pull request's conversation."""
        return self.add_issue_comment(pr_number, body)

    def merge_base_into_branch(
        self,
        base_branch: str,
        head_branch: str,
        commit_message: str = "",
    ) -> int:
        """Merge *base_branch* INTO *head_branch* via the GitHub merges API.

        Uses a raw ``requests.post`` (not ``_request``) so callers can inspect
        the 409 conflict status without catching an exception.

        Returns:
            201 — merge commit created (clean merge)
            204 — already up to date (no action needed)
            409 — merge conflict (caller must resolve)

        Raises:
            RuntimeError — any other unexpected HTTP status.
        """
        url = f"{self.API_BASE}/repos/{self.repo}/merges"
        payload: dict = {"base": head_branch, "head": base_branch}
        if commit_message:
            payload["commit_message"] = commit_message

        resp = self._session.post(url, json=payload)
        if resp.status_code in (201, 204, 409):
            return resp.status_code
        raise RuntimeError(
            f"GitHub merges API failed [{resp.status_code}]: {resp.text[:500]}"
        )

    def get_pr(self, pr_number: int) -> dict:
        """Return pull request metadata."""
        return self._request("GET", f"/repos/{self.repo}/pulls/{pr_number}")

    def get_pr_review_comments(self, pr_number: int) -> list:
        """Return inline review comments on a pull request."""
        return self._request("GET", f"/repos/{self.repo}/pulls/{pr_number}/comments")

    def get_pr_reviews(self, pr_number: int) -> list:
        """Return review-level submissions (APPROVED, CHANGES_REQUESTED, COMMENTED)."""
        return self._request("GET", f"/repos/{self.repo}/pulls/{pr_number}/reviews")

    def get_pr_files(self, pr_number: int) -> list:
        """Return list of files changed in a pull request."""
        return self._request("GET", f"/repos/{self.repo}/pulls/{pr_number}/files")

    def get_file_content(self, path: str, ref: Optional[str] = None) -> Optional[str]:
        """Fetch decoded text content of a file at a given ref (branch/sha).

        Returns None if the file does not exist or cannot be decoded.
        """
        try:
            params: dict = {}
            if ref is not None:
                params["ref"] = ref
            data = self._request(
                "GET", f"/repos/{self.repo}/contents/{path}", params=params or None
            )
        except RuntimeError:
            return None
        raw = data.get("content", "")
        try:
            return base64.b64decode(raw).decode("utf-8")
        except Exception:
            return None

    def list_files(self, path: str = "", ref: Optional[str] = None) -> list[dict]:
        """List files and directories at `path` in the repo.

        Returns a list of dicts with keys: name, type ('file'|'dir'), path.
        """
        params: dict = {}
        if ref:
            params["ref"] = ref
        url_path = f"/repos/{self.repo}/contents/{path}".rstrip("/")
        result = self._request("GET", url_path, params=params or None)
        if isinstance(result, list):
            return [{"name": e["name"], "type": e["type"], "path": e["path"]} for e in result]
        # Single file returned (happens when path points to a file, not dir)
        return [{"name": result["name"], "type": result["type"], "path": result["path"]}]

    def get_full_tree(self, ref: Optional[str] = None) -> list[dict]:
        """Return the full recursive file tree of the repo.

        Uses the git tree API with recursive=1 for efficiency.
        Returns [] if the tree is truncated (repo too large) or on any error.

        Returns:
            List of dicts with keys: path (str), type ('blob'|'tree'), size (int).
            Returns [] on any error or if the response is truncated.
        """
        try:
            sha = ref or self.get_default_branch()
            tree_data = self._request(
                "GET", f"/repos/{self.repo}/git/trees/{sha}",
                params={"recursive": "1"},
            )
            if tree_data.get("truncated"):
                return []
            return [
                {"path": e["path"], "type": e["type"], "size": e.get("size", 0)}
                for e in tree_data.get("tree", [])
            ]
        except Exception as exc:
            log.warning("get_full_tree failed for %s: %s", self.repo, exc)
            return []

    def search_files(self, pattern: str, ref: Optional[str] = None) -> list[str]:
        """Return all file paths in the repo matching a glob pattern.

        Uses the git tree API (recursive). Pattern is matched using pathlib.PurePath.match()
        which is right-anchored (e.g., 'README.md' matches 'docs/README.md').
        Returns list of file paths (blobs only, no trees).
        """
        from pathlib import PurePath
        
        sha = ref or self.get_default_branch()
        tree_data = self._request(
            "GET", f"/repos/{self.repo}/git/trees/{sha}", params={"recursive": "1"}
        )
        blobs = [e["path"] for e in tree_data.get("tree", []) if e["type"] == "blob"]
        
        # Match paths against glob pattern
        # Handle ** which should match zero or more path segments
        def match_glob(path: str, pattern: str) -> bool:
            if PurePath(path).match(pattern):
                return True
            # If pattern starts with **, also try without it (zero directories)
            if pattern.startswith('**/'):
                if PurePath(path).match(pattern[3:]):
                    return True
            return False
        
        return [p for p in blobs if match_glob(p, pattern)]

    def get_issue_comments(self, issue_number: int) -> list:
        """Return all comments on an issue (or PR timeline)."""
        return self._request("GET", f"/repos/{self.repo}/issues/{issue_number}/comments")

    def add_pr_label(self, pr_number: int, label_name: str) -> None:
        """Add a label to a pull request (uses the issues labels endpoint)."""
        self._request(
            "POST", f"/repos/{self.repo}/issues/{pr_number}/labels",
            json={"labels": [label_name]},
        )

    def remove_pr_label(self, pr_number: int, label_name: str) -> None:
        """Remove a label from a pull request. Ignores errors if label absent."""
        try:
            self._request(
                "DELETE", f"/repos/{self.repo}/issues/{pr_number}/labels/{label_name}"
            )
        except RuntimeError:
            pass

    # ── Labels ───────────────────────────────────────────────────────────────

    def ensure_labels(self, labels: list[dict]) -> None:
        """Create labels if they don't exist. Each label: {name, color, description}."""
        existing = {lbl["name"] for lbl in self._request("GET", f"/repos/{self.repo}/labels")}
        for label in labels:
            if label["name"] not in existing:
                try:
                    self._request("POST", f"/repos/{self.repo}/labels", json=label)
                except RuntimeError:
                    pass  # Label may have been created concurrently

    def get_repo_languages(self, repo: str) -> list[str]:
        """Return lowercase list of programming languages used in a repo.

        Calls GET /repos/{repo}/languages (GitHub Linguist endpoint).
        Returns [] on any error.

        Args:
            repo: Repository in "owner/repo" format.

        Returns:
            List of lowercase language names (e.g. ["python", "dart"]).
        """
        try:
            data = self._request("GET", f"/repos/{repo}/languages")
            return [lang.lower() for lang in data.keys()]
        except Exception:
            return []

    def __repr__(self) -> str:
        return f"GitHubClient(repo={self.repo!r}, token='***')"
