import json
import logging
import time
from typing import Any, Dict, List

from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

REQUIRED_PLATFORMS = ["LinkedIn", "Instagram", "TikTok", "X/Twitter"]


class PRCreativeAgent(BaseAgent):
    """
    PR Creative Agent (Casey) - Generates campaign concepts from analyst research.

    Subclasses BaseAgent to leverage LLM integration and orchestrator context handling.
    Consumes structured analyst output and produces 3-5 distinct campaign concepts.
    """

    role_name = "pr_creative"

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
        """
        Executes the creative generation stage.
        
        Extracts analyst output from context, constructs the LLM prompt, 
        handles retries on timeout/parse errors, validates the output schema, 
        and updates the context with the generated concepts.
        """
        analyst_output = context.get("pr_analyst")
        if not analyst_output:
            raise ValueError("Missing 'pr_analyst' in context. Analyst stage must run first.")

        user_prompt = self._build_user_prompt(analyst_output)

        llm_response = self._call_llm_with_retry(user_prompt)
        
        try:
            concepts = self._parse_and_validate_concepts(llm_response)
        except ValueError as e:
            logger.warning(f"Parse error encountered: {e}. Retrying once with strict formatting prompt.")
            strict_prompt = (
                "CRITICAL: You must output ONLY a valid JSON array. "
                "Do not include markdown formatting, explanations, or conversational text.\n\n"
                f"{user_prompt}"
            )
            llm_response_retry = self._call_llm_with_retry(strict_prompt)
            concepts = self._parse_and_validate_concepts(llm_response_retry)

        context["pr_creative"] = concepts
        return context

    def _build_user_prompt(self, analyst_output: Dict[str, Any]) -> str:
        """Injects analyst research into the user prompt template."""
        return (
            f"Analyst Research Input:\n"
            f"- Opportunity: {analyst_output.get('Opportunity', '')}\n"
            f"- Audience: {analyst_output.get('Audience', '')}\n"
            f"- Angle: {analyst_output.get('Angle', '')}\n"
            f"- Channels: {', '.join(analyst_output.get('Channels', []))}\n"
            f"- Risks: {', '.join(analyst_output.get('Risks', []))}\n\n"
            f"Generate the JSON array of concepts as instructed."
        )

    def _call_llm_with_retry(self, prompt: str, max_retries: int = 3) -> str:
        """Calls the LLM (via BaseAgent.call) with exponential backoff on timeout errors."""
        last_error = None
        for attempt in range(max_retries):
            try:
                return self._call(prompt)
            except Exception as e:
                last_error = e
                if "timeout" in str(e).lower() and attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"LLM timeout on attempt {attempt + 1}, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    break
        raise RuntimeError(f"LLM request failed after {max_retries} attempts: {last_error}")

    def _parse_and_validate_concepts(self, response: str) -> List[Dict[str, Any]]:
        """Parses LLM response, cleans markdown, and validates concept schema."""
        cleaned = self._clean_json_fences(response)
        concepts = self._parse_json_array(cleaned)
        concepts = self._enforce_count_constraints(concepts)
        self._validate_concept_fields(concepts)
        self._ensure_platform_tactics(concepts)
        return concepts


    def _clean_json_fences(self, response: str) -> str:
        """Remove markdown JSON code block fences from response."""
        cleaned = response.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned.split("```json", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        return cleaned.strip()

    def _parse_json_array(self, cleaned: str) -> List[Dict[str, Any]]:
        """Parse cleaned string as JSON and validate it's a list."""
        try:
            concepts = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError("Invalid JSON from LLM") from e

        if not isinstance(concepts, list):
            raise ValueError("LLM response is not a JSON array")
        return concepts

    def _enforce_count_constraints(self, concepts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Enforce concept count constraints: at least 3, at most 5."""
        if len(concepts) < 3:
            raise ValueError(f"LLM returned only {len(concepts)} concepts; need at least 3. Retrying.")
        elif len(concepts) > 5:
            logger.warning(f"LLM returned {len(concepts)} concepts. Truncating to 5.")
            return concepts[:5]
        return concepts

    def _validate_concept_fields(self, concepts: List[Dict[str, Any]]) -> None:
        """Validate that each concept has all required fields."""
        required_fields = [
            "big_idea", "how_it_works", "why_it_works", "headline_hook",
            "platform_tactics", "press_release_angle", "social_copy_example"
        ]
        for i, concept in enumerate(concepts):
            for field in required_fields:
                if field not in concept:
                    raise ValueError(f"Concept {i} missing required field: {field}")
            if not isinstance(concept.get("platform_tactics"), dict):
                raise ValueError(f"Concept {i} 'platform_tactics' must be a dictionary")

    def _ensure_platform_tactics(self, concepts: List[Dict[str, Any]]) -> None:
        """Ensure all required platforms are present in each concept's platform_tactics."""
        for concept in concepts:
            tactics = concept.get("platform_tactics", {})
            if not isinstance(tactics, dict):
                tactics = {}
            for platform in REQUIRED_PLATFORMS:
                if platform not in tactics:
                    tactics[platform] = ""
            concept["platform_tactics"] = tactics