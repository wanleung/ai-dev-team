"""PR Proposal Agent - Assembles campaign proposal and opens GitHub PR.

Subclasses BaseAgent to implement the PR Proposal Assembler (Jordan) role.
Consumes analyst and creative outputs, generates a markdown proposal via LLM,
creates a feature branch, and opens a GitHub Pull Request for human review.
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Tuple

from agents.base_agent import BaseAgent
from github_client import GitHubClient

logger = logging.getLogger(__name__)

# Retry configuration
MAX_LLM_RETRIES = 3
LLM_RETRY_BACKOFF_BASE = 2
MAX_PR_RETRIES = 3
RATE_LIMIT_WAIT = 60


class PRProposalAgent(BaseAgent):
    """PR Proposal Agent that assembles research and concepts into a PR."""

    role_name = "pr_proposal"

    def __init__(self, *args, tool_registry=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._tool_registry = tool_registry

    def _call(self, prompt: str) -> str:
        if self._tool_registry is not None:
            try:
                return self.call_with_tools(prompt, tools=self._tool_registry)
            except (AttributeError, NotImplementedError):
                pass
        return self.call(prompt)

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the PR Proposal pipeline stage.

        Args:
            context: Must contain pr_analyst dict, pr_creative list, issue_number int, github_client.

        Returns:
            Updated context with pr_proposal dict (pr_url, pr_number, branch_name, markdown_body).

        Raises:
            ValueError: If required context missing. TimeoutError: LLM timeout. RuntimeError: PR creation failure.
        """
        analyst_output, concepts, issue_number, github_client = self._validate_context(context)

        user_prompt = self._construct_user_prompt(analyst_output, concepts)
        llm_response = self._call_llm_with_retry(user_prompt)
        markdown_body, pr_metadata = self._parse_llm_response(llm_response)
        branch_name = self._generate_branch_name(issue_number, concepts[0]["big_idea"])

        pr_result = self._create_pr_with_retry(
            client=github_client,
            branch_name=branch_name,
            title=pr_metadata.get("pr_title", f"Campaign Proposal #{issue_number}"),
            body=markdown_body,
            issue_number=issue_number,
            markdown_body=markdown_body,
        )

        context["pr_proposal"] = self._build_result(pr_result, branch_name, markdown_body)
        logger.info("PR Proposal stage completed successfully")
        return context

    def _construct_user_prompt(
        self, analyst_output: Dict[str, Any], concepts: List[Dict[str, Any]]
    ) -> str:
        """Construct the user prompt by injecting analyst and creative data.

        Args:
            analyst_output: Validated research dict from pr_analyst stage
            concepts: List of validated campaign concept dicts

        Returns:
            Formatted user prompt string ready for LLM consumption
        """
        prompt_parts = [
            "Please assemble the following research findings and creative concepts into a polished campaign proposal.",
            "",
            "### Analyst Research",
        ]
        prompt_parts.extend(self._format_analyst_section(analyst_output))
        prompt_parts.append("")
        prompt_parts.append("### Creative Concepts")
        prompt_parts.extend(self._format_concepts_section(concepts))
        prompt_parts.extend([
            "",
            "Generate the proposal document exactly as specified in your system instructions.",
            "Ensure the final JSON block with pr_title and pr_body is strictly valid and parsable."
        ])
        return "\n".join(prompt_parts)

    def _call_llm_with_retry(self, user_prompt: str) -> str:
        """Call the LLM (via BaseAgent.call) with exponential backoff retry on timeout."""
        last_exception = None

        for attempt in range(MAX_LLM_RETRIES):
            try:
                logger.info(
                    f"Calling LLM for PR Proposal (attempt {attempt + 1}/{MAX_LLM_RETRIES})"
                )
                return self._call(user_prompt)

            except TimeoutError as e:
                last_exception = e
                wait_time = LLM_RETRY_BACKOFF_BASE ** (attempt + 1)
                logger.warning(
                    f"LLM timeout on attempt {attempt + 1}, retrying in {wait_time}s: {e}"
                )
                time.sleep(wait_time)

            except Exception as e:
                logger.error(f"LLM call failed: {e}")
                raise

        raise TimeoutError(
            f"LLM request timed out after {MAX_LLM_RETRIES} attempts"
        ) from last_exception

    def _parse_llm_response(self, response: str) -> Tuple[str, Dict[str, str]]:
        """Parse LLM response into markdown body and PR metadata JSON.

        Extracts the JSON code block at the end of the response.
        Falls back to default metadata if parsing fails.

        Args:
            response: Raw string response from LLM

        Returns:
            Tuple of (markdown_body, pr_metadata_dict)
        """
        # Find the last JSON code block (not first — earlier blocks may be body examples)
        all_matches = list(re.finditer(r'```(?:json)?\s*\n?(.*?)\n?\s*```', response, re.DOTALL))
        json_match = all_matches[-1] if all_matches else None
        if json_match:
            json_str = json_match.group(1).strip()
            try:
                metadata = json.loads(json_str)
                markdown_body = response[:json_match.start()].strip()
                return markdown_body, metadata
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse PR metadata JSON: {e}")

        # Fallback: use entire response as markdown, generate default metadata
        logger.warning("No valid JSON metadata block found in LLM response, using fallback.")
        return response.strip(), {
            "pr_title": "AI-Generated Campaign Proposal",
            "pr_body": "Automated PR proposal generated by the PR/Marketing Campaign Pipeline."
        }

    def _generate_branch_name(self, issue_number: int, big_idea: str) -> str:
        """Generate a sanitized branch name from issue number and concept title.

        Args:
            issue_number: GitHub issue number
            big_idea: First concept's big idea string

        Returns:
            Sanitized branch name string
        """
        # Simple slugify: lowercase, replace non-alphanumeric with hyphens
        slug = re.sub(r'[^a-z0-9]+', '-', big_idea.lower()).strip('-')
        if not slug:
            slug = "campaign-concept"
        return f"campaign/{issue_number}-{slug}"

    def _validate_context(self, context: Dict[str, Any]) -> tuple:
        """Validate and extract required fields from context."""
        analyst_output = context.get("pr_analyst")
        concepts = context.get("pr_creative")
        issue_number = context.get("issue_number")
        github_client = context.get("github_client")

        if not analyst_output or not concepts:
            raise ValueError("Missing pr_analyst or pr_creative in context")
        if not issue_number:
            raise ValueError("Missing issue_number in context")
        if not github_client:
            raise ValueError("Missing github_client in context")

        return analyst_output, concepts, issue_number, github_client

    def _build_result(self, pr_result: Dict[str, Any], branch_name: str, markdown_body: str) -> Dict[str, Any]:
        """Build the result dictionary for context."""
        return {
            "pr_url": pr_result.get("pr_url"),
            "pr_number": pr_result.get("pr_number"),
            "branch_name": branch_name,
            "markdown_body": markdown_body
        }

    def _format_analyst_section(self, analyst_output: Dict[str, Any]) -> List[str]:
        """Format analyst research section."""
        return [
            f"- **Opportunity**: {analyst_output.get('Opportunity', 'N/A')}",
            f"- **Audience**: {analyst_output.get('Audience', 'N/A')}",
            f"- **Angle**: {analyst_output.get('Angle', 'N/A')}",
            f"- **Channels**: {', '.join(analyst_output.get('Channels', []))}",
            f"- **Risks**: {', '.join(analyst_output.get('Risks', []))}",
        ]

    def _format_concepts_section(self, concepts: List[Dict[str, Any]]) -> List[str]:
        """Format creative concepts section."""
        lines = []
        for i, concept in enumerate(concepts, 1):
            lines.append(f"\n#### Concept {i}")
            lines.append(f"- **Big Idea**: {concept.get('big_idea', 'N/A')}")
            lines.append(f"- **How It Works**: {concept.get('how_it_works', 'N/A')}")
            lines.append(f"- **Why It Works**: {concept.get('why_it_works', 'N/A')}")
            lines.append(f"- **Headline Hook**: {concept.get('headline_hook', 'N/A')}")
            lines.append(f"- **Platform Tactics**: {json.dumps(concept.get('platform_tactics', {}))}")
            lines.append(f"- **Press Release Angle**: {concept.get('press_release_angle', 'N/A')}")
            lines.append(f"- **Social Copy Example**: {concept.get('social_copy_example', 'N/A')}")
        return lines

    def _attempt_pr_creation(
        self, client: GitHubClient, branch: str, title: str, body: str, issue_number: int, markdown_body: str
    ) -> Dict[str, Any]:
        """Attempt to create PR with branch and file commit."""
        actual_branch = client.create_branch(branch)
        file_path = f"proposals/campaign-{issue_number}.md"
        client.commit_file(
            path=file_path,
            content=markdown_body,
            message=f"feat: add campaign proposal for issue #{issue_number}",
            branch=actual_branch,
        )
        response = client.create_pull_request(title=title, body=body, head=actual_branch)
        return {"pr_url": response.get("html_url"), "pr_number": response.get("number")}

    def _handle_pr_error(
        self, error: Exception, client: GitHubClient, original_branch: str, current_branch: str, issue_number: int
    ) -> str:
        """Handle PR creation errors and return new branch name if retryable."""
        error_msg = str(error).lower()
        if "branch" in error_msg and ("exist" in error_msg or "409" in error_msg):
            new_branch = f"{original_branch}-{int(time.time())}"
            logger.warning(f"Branch exists, retrying with {new_branch}")
            return new_branch
        elif "rate limit" in error_msg or "429" in error_msg:
            logger.warning("GitHub rate limit hit, waiting 60s")
            time.sleep(RATE_LIMIT_WAIT)
            return current_branch
        else:
            logger.error(f"PR creation failed: {error}")
            try:
                client.add_issue_comment(issue_number, f"Pipeline failed to create PR: {error}")
            except Exception:
                logger.error("Failed to comment on issue about PR failure")
            raise RuntimeError(f"PR creation failed: {error}") from error

    def _create_pr_with_retry(
        self,
        client: GitHubClient,
        branch_name: str,
        title: str,
        body: str,
        issue_number: int,
        markdown_body: str,
    ) -> Dict[str, Any]:
        """Create branch, commit proposal file, open GitHub PR with retry logic.

        Args:
            client: Initialized GitHubClient instance
            branch_name: Target feature branch name
            title: PR title
            body: PR body (markdown)
            issue_number: Original issue number for error reporting
            markdown_body: Proposal markdown to commit as a file

        Returns:
            Dictionary containing pr_url and pr_number

        Raises:
            RuntimeError: If PR creation fails after maximum retries
        """
        current_branch = branch_name
        for _attempt in range(MAX_PR_RETRIES):
            try:
                return self._attempt_pr_creation(
                    client, current_branch, title, body, issue_number, markdown_body
                )
            except Exception as e:
                current_branch = self._handle_pr_error(
                    e, client, branch_name, current_branch, issue_number
                )
        raise RuntimeError("Failed to create PR after maximum retries")