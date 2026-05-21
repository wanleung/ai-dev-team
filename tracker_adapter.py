"""tracker_adapter.py — Abstract tracker interface and GitHub implementation.

Defines TriageItem, TrackerAdapter ABC, and GitHubTrackerAdapter.
Future: JiraTrackerAdapter follows the same interface.
"""
from __future__ import annotations

import logging
import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

import requests

log = logging.getLogger("tracker_adapter")


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

    @abstractmethod
    def add_score_label(self, item: TriageItem, score: float) -> None:
        """Ensure label 'score-{math.floor(score + 0.5)}' exists in repo and attach it to item."""

    @abstractmethod
    def post_score_comment(
        self,
        item: TriageItem,
        score: float,
        dimension_scores: dict[str, int],
        score_scale: int = 10,
    ) -> None:
        """Post a comment with the editorial score summary on the item."""


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
        except Exception as exc:
            log.warning("tracker_adapter: failed to post approve comment on #%s: %s", number, exc)
        self._api("POST", f"/repos/{self.repo}/issues/{number}/labels",
                  json={"labels": [self.approved_label, self.trigger_label]})
        try:
            self._api("DELETE",
                      f"/repos/{self.repo}/issues/{number}/labels/{self.pending_label}")
        except Exception as exc:
            if getattr(exc, "response", None) is not None and exc.response.status_code == 404:
                pass  # label already absent — expected
            else:
                log.warning("tracker_adapter: failed to remove pending label from #%s: %s", number, exc)

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
        except Exception as exc:
            log.warning("tracker_adapter: failed to post skip comment on #%s: %s", number, exc)
        self._api("POST", f"/repos/{self.repo}/issues/{number}/labels",
                  json={"labels": [self.skipped_label]})
        try:
            self._api("PATCH", f"/repos/{self.repo}/issues/{number}",
                      json={"state": "closed", "state_reason": "not_planned"})
        except Exception as exc:
            log.warning("tracker_adapter: failed to close issue #%s: %s", number, exc)
        try:
            self._api("DELETE",
                      f"/repos/{self.repo}/issues/{number}/labels/{self.pending_label}")
        except Exception as exc:
            if getattr(exc, "response", None) is not None and exc.response.status_code == 404:
                pass  # label already absent — expected
            else:
                log.warning("tracker_adapter: failed to remove pending label from #%s: %s", number, exc)

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
        except Exception as exc:
            log.warning("tracker_adapter: failed to fetch triage comments for #%s: %s", item_id, exc)

    def add_score_label(self, item: TriageItem, score: float) -> None:
        """Ensure label 'score-{math.floor(score + 0.5)}' exists in repo and attach it to item."""
        label_name = f"score-{math.floor(score + 0.5)}"
        # Only genuine 404 ("label not found") triggers creation.
        # Auth failures, timeouts, and other HTTP errors must propagate.
        try:
            self._api("GET", f"/repos/{self.repo}/labels/{label_name}")
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                try:
                    self._api(
                        "POST",
                        f"/repos/{self.repo}/labels",
                        json={"name": label_name, "color": "0075ca"},
                    )
                except requests.HTTPError as create_exc:
                    if create_exc.response is not None and create_exc.response.status_code == 422:
                        # Concurrent run already created the label — fall through to attach.
                        pass
                    else:
                        log.warning("tracker_adapter: could not create label %r: %s", label_name, create_exc)
                        return   # don't try to attach a label that wasn't created
                except Exception as create_exc:
                    log.warning("tracker_adapter: could not create label %r: %s", label_name, create_exc)
                    return   # don't try to attach a label that wasn't created
            else:
                log.warning(
                    "tracker_adapter: unexpected error checking label %r (%s): %s",
                    label_name,
                    getattr(exc.response, "status_code", "?"),
                    exc,
                )
                raise
        try:
            self._api(
                "POST",
                f"/repos/{self.repo}/issues/{item.id}/labels",
                json={"labels": [label_name]},
            )
        except Exception as exc:
            log.warning("tracker_adapter: failed to add score label to #%s: %s", item.id, exc)

    def post_score_comment(
        self,
        item: TriageItem,
        score: float,
        dimension_scores: dict[str, int],
        score_scale: int = 10,
    ) -> None:
        """Post a comment with the editorial score summary on the item."""
        dim_line = " | ".join(f"{k}={v}" for k, v in dimension_scores.items())
        body = (
            f"**Editorial Score: {score:.1f}/{score_scale}**\n"
            f"{dim_line}"
        )
        try:
            self._api(
                "POST",
                f"/repos/{self.repo}/issues/{item.id}/comments",
                json={"body": body},
            )
        except Exception as exc:
            log.warning("tracker_adapter: failed to post score comment on #%s: %s", item.id, exc)
