"""Repo context awareness — file tree injection and size detection.

RepoContextLoader fetches the full repo tree, decides small vs large,
and renders an appropriate tree text for injection into agent prompts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from github_client import GitHubClient


@dataclass
class RepoContext:
    """Holds the fetched repo context for injection into agent prompts."""
    file_count: int = 0
    is_large: bool = False
    tree_text: str = ""
    paths: list[dict] = field(default_factory=list)


class RepoContextLoader:
    """Fetches and renders the target repo's file tree.

    Small repos (file_count < threshold): full tree injected into prompts.
    Large repos (file_count >= threshold): top-2-level tree only.
    """

    def __init__(self, threshold: int = 50) -> None:
        self.threshold = threshold

    def build(self, gh: Optional["GitHubClient"]) -> RepoContext:
        """Fetch tree from GitHub and return a RepoContext.

        Returns an empty RepoContext if gh is None or the API call fails.
        """
        if gh is None:
            return RepoContext()

        paths = gh.get_full_tree()
        # Count blobs only (not tree/dir entries)
        blobs = [e for e in paths if e["type"] == "blob"]
        file_count = len(blobs)
        is_large = file_count >= self.threshold

        if file_count == 0:
            return RepoContext(file_count=0, is_large=False, tree_text="", paths=paths)

        if is_large:
            tree_text = self._render_top_level(blobs)
        else:
            tree_text = self._render_full(blobs)

        return RepoContext(
            file_count=file_count,
            is_large=is_large,
            tree_text=tree_text,
            paths=paths,
        )

    def _render_full(self, blobs: list[dict]) -> str:
        """Render all file paths as a compact sorted list."""
        lines = ["## Repo File Tree\n"]
        for entry in sorted(blobs, key=lambda e: e["path"]):
            lines.append(f"  {entry['path']}")
        return "\n".join(lines)

    def _render_top_level(self, blobs: list[dict]) -> str:
        """Render only paths with depth <= 2 (top-level dirs + their direct children).

        Depth is the number of '/' separators + 1.
        e.g. 'src/main.py' → depth 2 (shown), 'src/utils/helper.py' → depth 3 (hidden).
        """
        lines = ["## Repo File Tree (top-level, large repo)\n"]
        seen_dirs: set[str] = set()
        for entry in sorted(blobs, key=lambda e: e["path"]):
            path = entry["path"]
            parts = path.split("/")
            depth = len(parts)
            if depth <= 2:
                lines.append(f"  {path}")
            elif depth == 3:
                # Show parent dir as a summary line once
                parent = "/".join(parts[:2])
                if parent not in seen_dirs:
                    seen_dirs.add(parent)
                    lines.append(f"  {parent}/  (... {depth-2}+ levels deep)")
        return "\n".join(lines)
