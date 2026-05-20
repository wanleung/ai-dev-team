"""tracker_adapter.py — Abstract tracker interface and GitHub implementation.

Defines TriageItem, TrackerAdapter ABC, and GitHubTrackerAdapter.
Future: JiraTrackerAdapter follows the same interface.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

import requests


TRIAGE_COMMENT_MARKER = "[INTAKE TRIAGE]"
_NOTES_RE = re.compile(r"^NOTES:\s*(.*)$", re.MULTILINE)


@dataclass
class TriageItem:
    id: str
    title: str
    body: str
    url: str
    created_at: datetime
    metadata: dict = field(default_factory=dict)


class TrackerAdapter(ABC):
    @abstractmethod
    def list_pending(self) -> list[TriageItem]:
        """Return all items currently in triage-pending state."""

    @abstractmethod
    def approve(self, item: TriageItem, notes: str) -> None:
        """Mark approved: post comment, add approved + trigger labels, remove pending label."""

    @abstractmethod
    def skip(self, item: TriageItem, reason: str) -> None:
        """Mark skipped: post comment, add skipped label, close item."""

    @abstractmethod
    def is_approved(self, item_id: str) -> tuple[bool, str]:
        """Return (approved, editorial_notes). Used by orchestrator fast-pass."""


class GitHubTrackerAdapter(TrackerAdapter):
    """GitHub Issues implementation of TrackerAdapter."""

    def __init__(
        self,
        repo: str,
        token: str,
        pending_label: str = "triage-pending",
        approved_label: str = "triage-approved",
        skipped_label: str = "triage-skipped",
        trigger_label: str = "press",
    ) -> None:
        self.repo = repo
        self._token = token
        self.pending_label = pending_label
        self.approved_label = approved_label
        self.skipped_label = skipped_label
        self.trigger_label = trigger_label

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _api(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"https://api.github.com{path}"
        resp = requests.request(method, url, headers=self._headers(), timeout=15, **kwargs)
        resp.raise_for_status()
        return resp

    def list_pending(self) -> list[TriageItem]:
        items = []
        page = 1
        while True:
            resp = requests.get(
                f"https://api.github.com/repos/{self.repo}/issues",
                headers=self._headers(),
                params={"state": "open", "labels": self.pending_label, "per_page": 100, "page": page},
                timeout=15,
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            for issue in batch:
                if "pull_request" in issue:
                    continue
                created_at = datetime.fromisoformat(
                    issue["created_at"].replace("Z", "+00:00")
                )
                items.append(TriageItem(
                    id=str(issue["number"]),
                    title=issue.get("title", ""),
                    body=issue.get("body") or "",
                    url=issue.get("html_url", ""),
                    created_at=created_at,
                    metadata={
                        "number": issue["number"],
                        "labels": [l["name"] for l in issue.get("labels", [])],
                    },
                ))
            if len(batch) < 100:
                break
            page += 1
        return items

    def approve(self, item: TriageItem, notes: str) -> None:
        number = item.id
        comment = (
            f"{TRIAGE_COMMENT_MARKER}\n"
            f"VERDICT: PUBLISH\n"
            f"NOTES: {notes}\n\n"
            "_Batch intake triage approved this story for the pipeline._"
        )
        try:
            self._api("POST", f"/repos/{self.repo}/issues/{number}/comments",
                      json={"body": comment})
        except Exception:
            pass  # comment failure must not block label transition
        self._api("POST", f"/repos/{self.repo}/issues/{number}/labels",
                  json={"labels": [self.approved_label, self.trigger_label]})
        try:
            self._api("DELETE",
                      f"/repos/{self.repo}/issues/{number}/labels/{self.pending_label}")
        except Exception:
            pass  # label may already be absent

    def skip(self, item: TriageItem, reason: str) -> None:
        number = item.id
        comment = (
            f"{TRIAGE_COMMENT_MARKER}\n"
            f"VERDICT: SKIP\n"
            f"NOTES: {reason}\n\n"
            "_Batch intake triage skipped this story. Issue closed._"
        )
        try:
            self._api("POST", f"/repos/{self.repo}/issues/{number}/comments",
                      json={"body": comment})
        except Exception:
            pass
        self._api("POST", f"/repos/{self.repo}/issues/{number}/labels",
                  json={"labels": [self.skipped_label]})
        try:
            self._api("PATCH", f"/repos/{self.repo}/issues/{number}",
                      json={"state": "closed", "state_reason": "not_planned"})
        except Exception:
            pass
        try:
            self._api("DELETE",
                      f"/repos/{self.repo}/issues/{number}/labels/{self.pending_label}")
        except Exception:
            pass

    def is_approved(self, item_id: str) -> tuple[bool, str]:
        resp = requests.get(
            f"https://api.github.com/repos/{self.repo}/issues/{item_id}",
            headers=self._headers(),
            timeout=15,
        )
        resp.raise_for_status()
        issue = resp.json()
        label_names = {l["name"] for l in issue.get("labels", [])}
        if self.approved_label not in label_names:
            return False, ""
        # fetch notes from most recent INTAKE TRIAGE comment (newest first, paginated)
        try:
            page = 1
            while True:
                cr = requests.get(
                    f"https://api.github.com/repos/{self.repo}/issues/{item_id}/comments",
                    headers=self._headers(),
                    params={"per_page": 100, "sort": "created", "direction": "desc", "page": page},
                    timeout=15,
                )
                cr.raise_for_status()
                batch = cr.json()
                if not batch:
                    break
                for comment in batch:
                    body = comment.get("body", "")
                    if TRIAGE_COMMENT_MARKER in body:
                        m = _NOTES_RE.search(body)
                        if m:
                            return True, m.group(1).strip()
                if len(batch) < 100:
                    break
                page += 1
        except Exception:
            pass
        return True, ""
