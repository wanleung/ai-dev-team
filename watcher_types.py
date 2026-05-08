"""TypedDict definitions for GitHub API response objects used in watcher.py."""
from __future__ import annotations

from typing import TypedDict


class GitHubLabel(TypedDict):
    name: str
    color: str


class GitHubIssue(TypedDict):
    number: int
    title: str
    body: str | None
    html_url: str
    labels: list[GitHubLabel]
    state: str
    pull_request: dict | None  # present only on PR-linked issues


class GitHubComment(TypedDict):
    id: int
    body: str
    user: dict  # {"login": str}
    created_at: str


class GitHubPR(TypedDict):
    number: int
    title: str
    body: str | None
    html_url: str
    labels: list[GitHubLabel]
    state: str
    draft: bool
    head: dict   # {"ref": str, "sha": str}
    base: dict   # {"ref": str}


class WatcherTask(TypedDict):
    issue: GitHubIssue
    tracker_repo: str
    default_target: str | None
    label: str
    model: str
    num_engineers: int
