"""ConflictResolverAgent: resolves git merge conflicts using a real local clone."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .base_agent import BaseAgent


@dataclass
class PRContext:
    """Context about a pull request, used to guide conflict resolution."""

    pr_title: str
    pr_body: str
    design_doc: str = ""
    skills: str = ""


@dataclass
class ResolveResult:
    """Result of a conflict-resolution run."""

    status: str                          # "resolved" | "failed"
    resolved_files: list[str] = field(default_factory=list)
    failed_files: list[str] = field(default_factory=list)
    reason: str = ""


class ConflictResolverAgent(BaseAgent):
    """Resolves git merge conflicts using a local clone and LLM-assisted resolution.

    Clones the repository to a temp directory, runs ``git merge`` to obtain
    real conflict markers, calls the LLM per conflicting file, commits the
    resolved files, and pushes back to the remote.
    """

    role_name = "conflict_resolver"

    def resolve(
        self,
        repo_url: str,
        head_branch: str,
        base_branch: str,
        pr_context: PRContext,
    ) -> ResolveResult:
        """Clone the repo, merge base into head, resolve conflicts, and push.

        Args:
            repo_url:    Authenticated HTTPS clone URL (may include token).
            head_branch: The PR's source branch.
            base_branch: The target branch to merge from (e.g. ``"main"``).
            pr_context:  Pull-request metadata used to guide LLM resolution.

        Returns:
            A :class:`ResolveResult` with ``status``, ``resolved_files``,
            ``failed_files``, and an optional ``reason`` string.
        """
        tmpdir = tempfile.mkdtemp()
        try:
            return self._resolve(tmpdir, repo_url, head_branch, base_branch, pr_context)
        except Exception as exc:
            return ResolveResult(status="failed", reason=str(exc))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # ── internal ──────────────────────────────────────────────────────────────

    def _run(self, cmd: list[str], cwd: str | None = None):
        """Run a subprocess command and return its CompletedProcess."""
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
        )

    def _resolve(
        self,
        tmpdir: str,
        repo_url: str,
        head_branch: str,
        base_branch: str,
        pr_context: PRContext,
    ) -> ResolveResult:
        """Core resolution logic executed inside the temp directory."""
        # 1. Clone
        r = self._run(["git", "clone", "--depth=50", repo_url, tmpdir])
        if r.returncode != 0:
            return ResolveResult(status="failed", reason=f"clone failed: {r.stderr.strip()}")

        # 2. Checkout head branch
        self._run(["git", "checkout", head_branch], cwd=tmpdir)

        # 3. Fetch base and attempt merge
        self._run(["git", "fetch", "origin", base_branch], cwd=tmpdir)
        merge_r = self._run(["git", "merge", f"origin/{base_branch}"], cwd=tmpdir)

        if merge_r.returncode == 0:
            # No conflicts — already up to date or clean merge
            return ResolveResult(status="resolved", resolved_files=[])

        # 4. Find conflicting files
        diff_r = self._run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            cwd=tmpdir,
        )
        conflict_files = [f for f in diff_r.stdout.strip().splitlines() if f]

        if not conflict_files:
            return ResolveResult(status="resolved", resolved_files=[])

        # 5. Resolve each file with LLM
        resolved_files: list[str] = []
        failed_files: list[str] = []

        for path in conflict_files:
            full_path = Path(tmpdir) / path
            try:
                raw = full_path.read_text(encoding="utf-8", errors="replace")
                resolved = self._resolve_file(path, raw, pr_context)
                full_path.write_text(resolved, encoding="utf-8")
                self._run(["git", "add", path], cwd=tmpdir)
                resolved_files.append(path)
            except Exception:
                failed_files.append(path)

        if failed_files:
            return ResolveResult(
                status="failed",
                resolved_files=resolved_files,
                failed_files=failed_files,
                reason=f"LLM resolution failed for: {', '.join(failed_files)}",
            )

        # 6. Commit
        self._run(
            ["git", "commit", "-m", f"chore: resolve merge conflicts with {base_branch}"],
            cwd=tmpdir,
        )

        # 7. Push
        push_r = self._run(["git", "push", "origin", head_branch], cwd=tmpdir)
        if push_r.returncode != 0:
            return ResolveResult(
                status="failed",
                reason=f"push failed: {push_r.stderr.strip()}",
            )

        return ResolveResult(status="resolved", resolved_files=resolved_files)

    def _resolve_file(self, path: str, content: str, ctx: PRContext) -> str:
        """Ask the LLM to resolve conflict markers in a single file.

        Args:
            path:    Relative path of the file inside the repo.
            content: Raw file content including ``<<<<<<<``/``=======``/``>>>>>>>`` markers.
            ctx:     Pull-request context to steer the resolution.

        Returns:
            Resolved file content as a plain string (no conflict markers).
        """
        design_section = f"\nDesign context:\n{ctx.design_doc}\n" if ctx.design_doc else ""
        skills_section = f"\nSkills:\n{ctx.skills}\n" if ctx.skills else ""
        prompt = (
            f"You are resolving a git merge conflict in a pull request.\n\n"
            f"PR Title: {ctx.pr_title}\n"
            f"PR Description: {ctx.pr_body}\n"
            f"{design_section}"
            f"{skills_section}\n"
            f"Resolve the following conflict. Output ONLY the resolved file content, "
            f"no explanation, no markdown fences.\n\n"
            f"File: {path}\n\n"
            f"{content}"
        )
        return self.call(prompt)
