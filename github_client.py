"""
GitHubClient: thin wrapper around the GitHub REST API.
Uses GITHUB_TOKEN for authentication. Supports creating issues, branches,
file commits, pull requests, and comments.
"""
from __future__ import annotations

import base64
import os
import re
from typing import Optional

import requests


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
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.API_BASE}{path}"
        response = requests.request(method, url, headers=self.headers, **kwargs)
        if not response.ok:
            raise RuntimeError(
                f"GitHub API {method} {url} failed [{response.status_code}]: {response.text[:500]}"
            )
        return response.json() if response.text else {}

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

    def close_issue(self, issue_number: int, comment: Optional[str] = None) -> None:
        """Close an issue, optionally adding a final comment."""
        if comment:
            self.add_issue_comment(issue_number, comment)
        self._request(
            "PATCH",
            f"/repos/{self.repo}/issues/{issue_number}",
            json={"state": "closed"},
        )

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
        self._request(
            "POST",
            f"/repos/{self.repo}/git/refs",
            json={"ref": f"refs/heads/{branch_name}", "sha": sha},
        )
        return branch_name

    def commit_file(
        self,
        path: str,
        content: str,
        message: str,
        branch: str,
        encoding: str = "utf-8",
    ) -> dict:
        """Create or update a file in the repo on the given branch.

        Args:
            path: File path relative to repo root (e.g., 'src/main.py').
            content: Text content of the file.
            message: Git commit message.
            branch: Branch to commit to.
            encoding: Text encoding (default 'utf-8').

        Returns:
            GitHub API response with commit and content data.
        """
        encoded = base64.b64encode(content.encode(encoding)).decode("ascii")

        # Check if file already exists (for update vs create)
        payload: dict = {"message": message, "content": encoded, "branch": branch}
        try:
            existing = self._request("GET", f"/repos/{self.repo}/contents/{path}", params={"ref": branch})
            payload["sha"] = existing["sha"]
        except RuntimeError:
            pass  # File doesn't exist yet — create it

        return self._request("PUT", f"/repos/{self.repo}/contents/{path}", json=payload)

    # ── Pull Requests ────────────────────────────────────────────────────────

    def create_pull_request(
        self,
        title: str,
        body: str,
        head: str,
        base: Optional[str] = None,
        draft: bool = False,
    ) -> dict:
        """Open a pull request. Returns PR data including number and url."""
        return self._request(
            "POST",
            f"/repos/{self.repo}/pulls",
            json={
                "title": title,
                "body": body,
                "head": head,
                "base": base or self.get_default_branch(),
                "draft": draft,
            },
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

    def __repr__(self) -> str:
        return f"GitHubClient(repo={self.repo!r})"
