"""BootstrapPatternsAgent — scans a target repo and generates .github/copilot-instructions.md.

Run once when adding a new repo to repos.yaml to give AI agents
day-one codebase context. The generated file is committed directly
to the target repo's default branch.

Subsequent updates happen incrementally via LearningAgent.
"""
import logging

from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

# Key files to sample for stack detection, checked in order
CANDIDATE_FILES = [
    "package.json",
    "pubspec.yaml",
    "requirements.txt",
    "pyproject.toml",
    "Gemfile",
    "go.mod",
    "pom.xml",
    "README.md",
    "README.rst",
]

MAX_FILE_SAMPLE_CHARS = 2000


class BootstrapPatternsAgent(BaseAgent):
    """Generates an initial .github/copilot-instructions.md for a target repo."""

    role_name = "bootstrap_patterns_agent"

    def run(self, target_gh, commit: bool = True) -> str:
        """Scan target_gh repo, generate codebase patterns content, and optionally commit it.

        Args:
            target_gh: GitHubClient pointing at the target repo.
            commit: If True, commit .github/copilot-instructions.md to the repo's default branch.

        Returns:
            The generated markdown string.
        """
        repo_name = target_gh.repo

        # Build file tree summary
        try:
            tree = target_gh.get_full_tree()
        except Exception as e:
            logger.warning("BootstrapPatternsAgent: could not fetch tree for %s: %s", repo_name, e)
            tree = []

        blobs = [e["path"] for e in tree if e.get("type") == "blob"]
        tree_summary = "\n".join(f"  {p}" for p in sorted(blobs)[:80])

        # Sample key files
        samples: list[str] = []
        for candidate in CANDIDATE_FILES:
            if candidate in blobs:
                content = target_gh.get_file_content(candidate)
                if content is not None:
                    samples.append(f"### {candidate}\n```\n{content[:MAX_FILE_SAMPLE_CHARS]}\n```")
                    if len(samples) >= 5:
                        break

        prompt = (
            f"Repo: {repo_name}\n\n"
            f"File tree (first 80 files):\n{tree_summary}\n\n"
            + ("\n\n".join(samples) if samples else "No key files sampled.")
        )

        agents_md = self.call(prompt)

        if commit:
            try:
                default_branch = target_gh.get_default_branch()
                target_gh.commit_file(
                    path=".github/copilot-instructions.md",
                    content=agents_md,
                    message="chore: add AI agent codebase patterns [bootstrap]",
                    branch=default_branch,
                )
                logger.info(
                    "BootstrapPatternsAgent: committed .github/copilot-instructions.md to %s",
                    repo_name,
                )
            except Exception as e:
                logger.warning(
                    "BootstrapPatternsAgent: could not commit to %s: %s",
                    repo_name, e,
                )

        return agents_md
