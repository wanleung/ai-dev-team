"""PR Proposal Agent - Assembles campaign proposal and opens GitHub PR.

Subclasses BaseAgent to implement the PR Proposal Assembler (Jordan) role.
Consumes analyst and creative outputs, generates a markdown proposal via LLM,
creates a feature branch, and opens a GitHub Pull Request for human review.
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

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
            context: Pipeline context dictionary containing:
                - pr_analyst: Dict with Opportunity, Audience, Angle, Channels, Risks
                - pr_creative: List of concept dicts
                - issue_number: Integer GitHub issue number
                - github_client: Initialized GitHubClient instance

        Returns:
            Updated context dictionary with 'pr_proposal' key containing:
                - pr_url, pr_number, branch_name, markdown_body
        """
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

        context["pr_proposal"] = {
            "pr_url": pr_result.get("pr_url"),
            "pr_number": pr_result.get("pr_number"),
            "branch_name": branch_name,
            "markdown_body": markdown_body
        }
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
            f"- **Opportunity**: {analyst_output.get('Opportunity', 'N/A')}",
            f"- **Audience**: {analyst_output.get('Audience', 'N/A')}",
            f"- **Angle**: {analyst_output.get('Angle', 'N/A')}",
            f"- **Channels**: {', '.join(analyst_output.get('Channels', []))}",
            f"- **Risks**: {', '.join(analyst_output.get('Risks', []))}",
            "",
            "### Creative Concepts",
        ]

        for i, concept in enumerate(concepts, 1):
            prompt_parts.append(f"\n#### Concept {i}")
            prompt_parts.append(f"- **Big Idea**: {concept.get('big_idea', 'N/A')}")
            prompt_parts.append(f"- **How It Works**: {concept.get('how_it_works', 'N/A')}")
            prompt_parts.append(f"- **Why It Works**: {concept.get('why_it_works', 'N/A')}")
            prompt_parts.append(f"- **Headline Hook**: {concept.get('headline_hook', 'N/A')}")
            prompt_parts.append(f"- **Platform Tactics**: {json.dumps(concept.get('platform_tactics', {}))}")
            prompt_parts.append(f"- **Press Release Angle**: {concept.get('press_release_angle', 'N/A')}")
            prompt_parts.append(f"- **Social Copy Example**: {concept.get('social_copy_example', 'N/A')}")

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
        for attempt in range(MAX_PR_RETRIES):
            try:
                # Create the branch from default
                actual_branch = client.create_branch(current_branch)

                # Commit the proposal file to the branch
                file_path = f"proposals/campaign-{issue_number}.md"
                client.commit_file(
                    path=file_path,
                    content=markdown_body,
                    message=f"feat: add campaign proposal for issue #{issue_number}",
                    branch=actual_branch,
                )

                # Open the PR
                response = client.create_pull_request(
                    title=title,
                    body=body,
                    head=actual_branch,
                )
                return {
                    "pr_url": response.get("html_url"),
                    "pr_number": response.get("number"),
                }
            except Exception as e:
                error_msg = str(e).lower()
                if "branch" in error_msg and ("exist" in error_msg or "409" in error_msg):
                    current_branch = f"{branch_name}-{int(time.time())}"
                    logger.warning(f"Branch exists, retrying with {current_branch}")
                    continue
                elif "rate limit" in error_msg or "429" in error_msg:
                    logger.warning("GitHub rate limit hit, waiting 60s")
                    time.sleep(RATE_LIMIT_WAIT)
                    continue
                else:
                    logger.error(f"PR creation failed: {e}")
                    try:
                        client.add_issue_comment(
                            issue_number,
                            f"Pipeline failed to create PR: {e}"
                        )
                    except Exception:
                        logger.error("Failed to comment on issue about PR failure")
                    raise RuntimeError(f"PR creation failed: {e}") from e
        raise RuntimeError("Failed to create PR after maximum retries")