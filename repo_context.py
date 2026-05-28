"""Repo context awareness — file tree injection and size detection.

RepoContextLoader fetches the full repo tree, decides small vs large,
and renders an appropriate tree text for injection into agent prompts.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
import zipfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

log = logging.getLogger(__name__)

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
        Any file deeper than depth 2 contributes its depth-2 parent as a summary line.
        """
        lines = ["## Repo File Tree (top-level, large repo)\n"]
        seen_dirs: set[str] = set()
        for entry in sorted(blobs, key=lambda e: e["path"]):
            path = entry["path"]
            parts = path.split("/")
            depth = len(parts)
            if depth <= 2:
                lines.append(f"  {path}")
            else:
                # Show the depth-2 parent dir exactly once
                parent = "/".join(parts[:2])
                if parent not in seen_dirs:
                    seen_dirs.add(parent)
                    lines.append(f"  {parent}/  (...)")
        return "\n".join(lines)


class RepoAutoIndexer:
    """Downloads a GitHub repo and indexes it into the RAG codebase collection.

    Called before the Engineer stage when RAG MCP is configured.
    Uses the rag-mcp/indexer.py subprocess so the RAG server is always
    the single source of truth for embeddings.
    """

    def __init__(self, indexer_script: str = "rag-mcp/indexer.py") -> None:
        self.indexer_script = indexer_script

    def index(
        self,
        repo: str,
        github_token: str,
        repo_dir: Optional[str] = None,
        ref: str = "HEAD",
    ) -> None:
        """Download repo zip and run indexer against it.

        Args:
            repo: 'owner/repo' string.
            github_token: GitHub personal access token.
            repo_dir: If provided, use this local directory instead of downloading.
            ref: Git ref to download (default HEAD).
        """
        script = Path(self.indexer_script)
        if not script.exists():
            return  # RAG indexer not available — skip silently

        if repo_dir:
            self._run_indexer(repo_dir)
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                extracted = self._download_repo_zip(repo, github_token, tmpdir, ref)
                if extracted:
                    self._run_indexer(extracted)

    def _download_repo_zip(
        self, repo: str, github_token: str, tmpdir: str, ref: str
    ) -> Optional[str]:
        """Download repo zipball and extract. Returns extracted directory path or None."""
        zip_path = Path(tmpdir) / "repo.zip"
        url = f"https://api.github.com/repos/{repo}/zipball/{ref}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                zip_path.write_bytes(resp.read())
        except Exception as exc:
            log.warning("RAG repo download failed (%s): %s", repo, exc)
            return None

        extract_dir = Path(tmpdir) / "repo"
        extract_dir.mkdir()
        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(extract_dir)
        except zipfile.BadZipFile:
            return None

        # GitHub zip contains a single top-level dir like "owner-repo-sha/"
        subdirs = [d for d in extract_dir.iterdir() if d.is_dir()]
        return str(subdirs[0]) if subdirs else str(extract_dir)

    def _run_indexer(self, path: str) -> None:
        """Run rag-mcp/indexer.py --source codebase --path <path> --clean."""
        proc = subprocess.run(
            [sys.executable, self.indexer_script, "--source", "codebase", "--path", path, "--clean"],
            check=False,
            timeout=300,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            log.warning("RAG indexer exited %d: %s", proc.returncode, proc.stderr[:200])

    def index_local_dir(self, path: str) -> None:
        """Index a local directory into the RAG codebase collection.

        Non-blocking wrapper around _run_indexer(). Safe to call in a try/except.

        Args:
            path: Absolute or relative path to the directory to index.
        """
        script = Path(self.indexer_script)
        if not script.exists():
            return  # RAG indexer not available — skip silently
        self._run_indexer(path)
