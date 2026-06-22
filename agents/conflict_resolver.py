"""ConflictResolverAgent: resolves git merge conflicts using a real local clone."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from .base_agent import BaseAgent
from utils import sanitise as _sanitise_utils


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

    status: Literal["resolved", "failed"]  # "resolved" | "failed"
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
        github_token: str | None = None,
    ) -> ResolveResult:
        """Clone the repo, merge base into head, resolve conflicts, and push.

        Args:
            repo_url:      Clean HTTPS clone URL (no embedded token).
            head_branch:   The PR's source branch.
            base_branch:   The target branch to merge from (e.g. ``"main"``).
            pr_context:    Pull-request metadata used to guide LLM resolution.
            github_token:  GitHub PAT used for authentication via
                           ``http.extraHeader`` (never embedded in URL).

        Returns:
            A :class:`ResolveResult` with ``status``, ``resolved_files``,
            ``failed_files``, and an optional ``reason`` string.
        """
        self._token = github_token  # Enables _sanitise() to redact if needed
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
    def _sanitise(self, text: str) -> str:
        """Remove the GitHub token from *text* so it is safe to log or surface."""
        return _sanitise_utils(text, getattr(self, "_token", None))

    def _clone_and_setup(self, tmpdir: str, repo_url: str, head_branch: str) -> Optional[str]:
        """Clone repo and setup git config. Returns error reason if failed, None on success."""
        clone_cmd = ["git", "clone", "--filter=blob:none"]
        # Authenticate via header instead of embedding token in URL
        token = getattr(self, "_token", None)
        if token:
            clone_cmd += ["-c", f"http.extraHeader=Bearer {token}"]
        clone_cmd += [repo_url, tmpdir]
        r = self._run(clone_cmd)
        if r.returncode != 0:
            return f"clone failed: {self._sanitise(r.stderr.strip())}"

        self._run(["git", "config", "user.email", "conflict-resolver@bot"], cwd=tmpdir)
        self._run(["git", "config", "user.name", "Conflict Resolver Bot"], cwd=tmpdir)

        r = self._run(["git", "checkout", head_branch], cwd=tmpdir)
        if r.returncode != 0:
            return f"checkout failed: {self._sanitise(r.stderr.strip())}"
        return None

    def _fetch_and_merge(self, tmpdir: str, base_branch: str) -> tuple[bool, Optional[str]]:
        """Fetch base branch and attempt merge.
        
        Returns:
            (success, error_reason): success=True if clean merge, False if conflicts,
                                     error_reason set only if git operation failed
        """
        r = self._run(["git", "fetch", "origin", base_branch], cwd=tmpdir)
        if r.returncode != 0:
            return False, f"fetch failed: {self._sanitise(r.stderr.strip())}"
        
        merge_r = self._run(["git", "merge", f"origin/{base_branch}"], cwd=tmpdir)
        return merge_r.returncode == 0, None

    def _get_conflict_files(self, tmpdir: str) -> list[str]:
        """Get list of files with merge conflicts."""
        diff_r = self._run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            cwd=tmpdir,
        )
        return [f for f in diff_r.stdout.strip().splitlines() if f]

    def _resolve_conflicts(self, tmpdir: str, conflict_files: list[str],
                          pr_context: PRContext) -> tuple[list[str], list[str]]:
        """Resolve each conflicting file with LLM. Returns (resolved, failed) file lists."""
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

        return resolved_files, failed_files

    def _commit_and_push(self, tmpdir: str, head_branch: str,
                        base_branch: str) -> Optional[str]:
        """Commit resolved conflicts and push. Returns error reason if failed, None on success."""
        self._run(
            ["git", "commit", "-m", f"chore: resolve merge conflicts with {base_branch}"],
            cwd=tmpdir,
        )

        push_cmd = ["git"]
        token = getattr(self, "_token", None)
        if token:
            push_cmd += ["-c", f"http.extraHeader=Bearer {token}"]
        push_cmd += ["push", "origin", head_branch]
        push_r = self._run(push_cmd, cwd=tmpdir)
        if push_r.returncode != 0:
            return f"push failed: {self._sanitise(push_r.stderr.strip())}"
        return None

    def _resolve(
        self,
        tmpdir: str,
        repo_url: str,
        head_branch: str,
        base_branch: str,
        pr_context: PRContext,
    ) -> ResolveResult:
        """Core resolution logic executed inside the temp directory."""
        # 1. Clone and setup
        err = self._clone_and_setup(tmpdir, repo_url, head_branch)
        if err:
            return ResolveResult(status="failed", reason=err)

        # 2. Fetch and merge
        clean_merge, err = self._fetch_and_merge(tmpdir, base_branch)
        if err:
            return ResolveResult(status="failed", reason=err)
        if clean_merge:
            return ResolveResult(status="resolved", resolved_files=[])

        # 3. Find conflicting files
        conflict_files = self._get_conflict_files(tmpdir)
        if not conflict_files:
            return ResolveResult(status="resolved", resolved_files=[])

        # 4. Resolve with LLM
        resolved_files, failed_files = self._resolve_conflicts(tmpdir, conflict_files, pr_context)
        if failed_files:
            return ResolveResult(status="failed", resolved_files=resolved_files,
                                failed_files=failed_files,
                                reason=f"LLM resolution failed for: {', '.join(failed_files)}")

        # 5. Commit and push
        err = self._commit_and_push(tmpdir, head_branch, base_branch)
        if err:
            return ResolveResult(status="failed", resolved_files=resolved_files, reason=err)
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
