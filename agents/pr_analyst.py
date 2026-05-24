"""PR Analyst Agent - Parses campaign briefs and produces structured research.

Subclasses BaseAgent to implement the PR Analyst (Alex) role.
Parses GitHub issue body, calls LLM (via BaseAgent.call), validates JSON output,
and returns structured research dict.
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

# Required fields that must be present in the campaign brief
REQUIRED_BRIEF_FIELDS = ["client_product", "goal", "target_audience", "key_message"]

# Keys expected in the LLM JSON output
REQUIRED_OUTPUT_KEYS = ["Opportunity", "Audience", "Angle", "Channels", "Risks"]

# Retry configuration for LLM calls
MAX_LLM_RETRIES = 3
LLM_RETRY_BACKOFF_BASE = 2  # seconds


class PRAnalystAgent(BaseAgent):
    """PR Analyst Agent that parses campaign briefs and produces structured research."""

    role_name = "pr_analyst"

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
        """Execute the PR Analyst pipeline stage.

        Args:
            context: Must contain 'issue_body' (markdown) and 'issue_number' (int).

        Returns:
            Updated context with 'pr_analyst' dict (Opportunity, Audience, Angle, Channels, Risks).

        Raises:
            ValueError: If issue_body missing or required brief fields incomplete.
            ParseError: If LLM output cannot be parsed or validated.
            TimeoutError: If LLM call times out after retries.
        """
        issue_body = context.get("issue_body", "")
        if not issue_body:
            raise ValueError("Missing issue_body in context")

        parsed_brief = self._parse_brief(issue_body)
        self._validate_brief(parsed_brief, context.get("issue_number"))
        user_prompt = self._construct_user_prompt(parsed_brief)
        llm_response = self._call_llm_with_retry(user_prompt)
        validated_output = self._parse_and_validate_json(llm_response)

        context["pr_analyst"] = validated_output
        logger.info("PR Analyst stage completed successfully")
        return context

    def _parse_brief(self, issue_body: str) -> Dict[str, str]:
        """Parse markdown issue body into structured field dictionary.

        Extracts fields from the campaign-brief.md template format:
        ### Field Name
        <!-- comment -->
        field value

        Args:
            issue_body: Raw markdown string from GitHub issue

        Returns:
            Dictionary mapping field names to their values (stripped of whitespace)
        """
        parsed = {}
        field_patterns = self._get_field_patterns()

        for key, pattern in field_patterns.items():
            match = re.search(pattern, issue_body, re.DOTALL | re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                value = re.sub(r"<!--.*?-->", "", value).strip()
                if value:
                    parsed[key] = value

        return parsed

    def _validate_brief(
        self, parsed_brief: Dict[str, str], issue_number: Optional[int] = None
    ) -> None:
        """Validate that all required brief fields are present and non-empty.

        Args:
            parsed_brief: Dictionary of parsed field values
            issue_number: GitHub issue number for error context

        Raises:
            ValueError: If any required field is missing or empty
        """
        missing_fields = []
        for field in REQUIRED_BRIEF_FIELDS:
            value = parsed_brief.get(field, "").strip()
            if not value:
                missing_fields.append(field)

        if missing_fields:
            issue_ref = f" (issue #{issue_number})" if issue_number else ""
            error_msg = (
                f"Campaign brief incomplete{issue_ref}. "
                f"Missing required fields: {', '.join(missing_fields)}"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

    def _construct_user_prompt(self, parsed_brief: Dict[str, str]) -> str:
        """Construct the user prompt by injecting parsed brief fields.

        Args:
            parsed_brief: Dictionary of parsed campaign brief fields

        Returns:
            Formatted user prompt string ready for LLM consumption
        """
        prompt_parts = [
            "Please analyze the following campaign brief and produce a structured research report.",
            "",
            "### Campaign Brief",
            "",
        ]
        prompt_parts.extend(self._format_required_fields(parsed_brief))
        prompt_parts.extend(self._format_optional_fields(parsed_brief))
        prompt_parts.extend([
            "",
            "Analyze this brief carefully and return ONLY a valid JSON object matching the schema defined in your system instructions.",
        ])
        return "\n".join(prompt_parts)

    def _call_llm_with_retry(self, user_prompt: str) -> str:
        """Call the LLM with exponential backoff retry on timeout.

        Uses BaseAgent.call() which automatically applies the role system prompt.
        """
        last_exception = None

        for attempt in range(MAX_LLM_RETRIES):
            try:
                logger.info(
                    f"Calling LLM for PR Analyst (attempt {attempt + 1}/{MAX_LLM_RETRIES})"
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
                # Non-timeout errors are not retried
                logger.error(f"LLM call failed: {e}")
                raise

        raise TimeoutError(
            f"LLM request timed out after {MAX_LLM_RETRIES} attempts"
        ) from last_exception

    def _parse_and_validate_json(self, llm_response: str) -> Dict[str, Any]:
        """Parse LLM response as JSON and validate required keys.

        Handles cases where LLM wraps JSON in markdown code blocks.
        Retries once with a fallback prompt if keys are missing.

        Args:
            llm_response: Raw string response from LLM

        Returns:
            Validated dictionary with required keys:
                Opportunity, Audience, Angle, Channels, Risks

        Raises:
            ParseError: If response cannot be parsed or validated
        """
        try:
            cleaned_response = self._strip_markdown_code_blocks(llm_response)
            parsed = json.loads(cleaned_response)
            self._check_required_keys(parsed)
            self._validate_output_types(parsed)
            return parsed

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Initial JSON parse failed: {e}")
            retry_response = self._retry_with_fallback_prompt(llm_response)
            if retry_response:
                return retry_response
            raise ParseError(f"Agent output malformed: {e}") from e

    def _strip_markdown_code_blocks(self, text: str) -> str:
        """Remove markdown code block formatting from LLM response.

        Args:
            text: Raw LLM response that may contain ```json blocks

        Returns:
            Cleaned JSON string
        """
        # Remove ```json or ``` wrappers
        pattern = r"```(?:json)?\s*\n?(.*?)\n?\s*```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text.strip()

    def _validate_output_types(self, parsed: Dict[str, Any]) -> None:
        """Validate that output fields have correct types and constraints.

        Args:
            parsed: Dictionary of parsed LLM output

        Raises:
            ValueError: If types or constraints are violated
        """
        self._validate_string_fields(parsed)
        self._validate_channels_field(parsed)
        self._validate_risks_field(parsed)

    def _retry_with_fallback_prompt(
        self, original_response: str
    ) -> Optional[Dict[str, Any]]:
        """Retry LLM call with a stricter fallback prompt for JSON formatting.

        Args:
            original_response: The malformed response that failed validation

        Returns:
            Validated dictionary if retry succeeds, None otherwise
        """
        logger.info("Retrying with fallback prompt for JSON validation")
        try:
            retry_response = self._call(
                f"Your previous response could not be parsed. "
                f"Please return ONLY the JSON object with all required keys: "
                f"Opportunity, Audience, Angle, Channels, Risks. "
                f"No markdown, no explanations, just raw JSON. "
                f"Original response was: {original_response[:500]}..."
            )
            cleaned = self._strip_markdown_code_blocks(retry_response)
            parsed = json.loads(cleaned)
            self._check_required_keys(parsed)
            self._validate_output_types(parsed)
            return parsed

        except Exception as e:
            logger.error(f"Fallback retry failed: {e}")
            return None


    def _get_field_patterns(self) -> Dict[str, str]:
        """Return field patterns for parsing brief markdown."""
        return {
            "client_product": r"### Client/Product\s*\*?\s*\n<!--.*?-->\s*\n(.*?)(?=\n###|$)",
            "goal": r"### Goal\s*\*?\s*\n<!--.*?-->\s*\n(.*?)(?=\n###|$)",
            "target_audience": r"### Target Audience\s*\*?\s*\n<!--.*?-->\s*\n(.*?)(?=\n###|$)",
            "key_message": r"### Key Message\s*\*?\s*\n<!--.*?-->\s*\n(.*?)(?=\n###|$)",
            "channels": r"### Channels\s*\n<!--.*?-->\s*\n(.*?)(?=\n###|$)",
            "tone": r"### Tone\s*\n<!--.*?-->\s*\n(.*?)(?=\n###|$)",
            "deadline_timing": r"### Deadline/Timing\s*\n<!--.*?-->\s*\n(.*?)(?=\n###|$)",
        }

    def _format_required_fields(self, parsed_brief: Dict[str, str]) -> List[str]:
        """Format required brief fields."""
        return [
            f"**Client/Product**: {parsed_brief.get('client_product', 'N/A')}",
            f"**Goal**: {parsed_brief.get('goal', 'N/A')}",
            f"**Target Audience**: {parsed_brief.get('target_audience', 'N/A')}",
            f"**Key Message**: {parsed_brief.get('key_message', 'N/A')}",
        ]

    def _format_optional_fields(self, parsed_brief: Dict[str, str]) -> List[str]:
        """Format optional brief fields if present."""
        lines = []
        if parsed_brief.get("channels"):
            lines.append(f"**Channels**: {parsed_brief['channels']}")
        if parsed_brief.get("tone"):
            lines.append(f"**Tone**: {parsed_brief['tone']}")
        if parsed_brief.get("deadline_timing"):
            lines.append(f"**Deadline/Timing**: {parsed_brief['deadline_timing']}")
        return lines

    def _check_required_keys(self, parsed: Dict[str, Any]) -> None:
        """Check that all required keys are present."""
        missing_keys = [key for key in REQUIRED_OUTPUT_KEYS if key not in parsed]
        if missing_keys:
            raise ValueError(f"Missing required keys: {', '.join(missing_keys)}")

    def _validate_string_fields(self, parsed: Dict[str, Any]) -> None:
        """Validate string fields are strings and non-empty."""
        for key in ["Opportunity", "Audience", "Angle"]:
            if not isinstance(parsed[key], str):
                raise ValueError(f"'{key}' must be a string")
            if not parsed[key].strip():
                raise ValueError(f"'{key}' must not be empty")

    def _validate_channels_field(self, parsed: Dict[str, Any]) -> None:
        """Validate Channels field is a list of strings with max 10 items."""
        if not isinstance(parsed["Channels"], list):
            raise ValueError("'Channels' must be a list")
        if len(parsed["Channels"]) > 10:
            raise ValueError("'Channels' must have at most 10 items")
        for channel in parsed["Channels"]:
            if not isinstance(channel, str):
                raise ValueError("Each channel must be a string")

    def _validate_risks_field(self, parsed: Dict[str, Any]) -> None:
        """Validate Risks field is a list of strings with max 5 items."""
        if not isinstance(parsed["Risks"], list):
            raise ValueError("'Risks' must be a list")
        if len(parsed["Risks"]) > 5:
            raise ValueError("'Risks' must have at most 5 items")
        for risk in parsed["Risks"]:
            if not isinstance(risk, str):
                raise ValueError("Each risk must be a string")


class ParseError(Exception):
    """Raised when LLM output cannot be parsed into valid structured data."""

    pass