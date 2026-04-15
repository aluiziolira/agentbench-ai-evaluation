"""LLM-based judge scoring strategy for AgentBench.

This module implements the LLMJudgeStrategy that uses an LLM (gpt-5.4-mini)
to evaluate the quality of PR review summaries against a rubric with five dimensions.
"""

import json
import logging
import re
from typing import Any

from agentbench.cases.models import ReviewCaseDefinition
from agentbench.models.results import StepScore
from agentbench.models.workflow import StepDefinition

logger = logging.getLogger(__name__)

# Default judge model kept fixed for evaluation independence
DEFAULT_JUDGE_MODEL = "gpt-5.4-mini"

# Judge prompt template with rubric dimensions
JUDGE_PROMPT_TEMPLATE = """You are evaluating a PR review summary. Rate it on these dimensions (0.0-1.0 each):
1. Prioritizes most important issue first
2. Grounded in actual diff and ticket
3. Mentions missing tests when relevant
4. Avoids filler and low-value commentary
5. Actionable for PR author

Review Summary to evaluate:
{summary_text}

Ticket:
{ticket_text}

Diff:
{diff_patch}

Return JSON:
{{
  "score": <float 0.0-1.0>,
  "reasoning": "<explanation>"
}}"""


class LLMJudgeStrategy:
    """LLM-based judge strategy for scoring review summaries.

    This strategy uses an LLM (gpt-5.4-mini) to evaluate the quality of a review summary
    against a five-dimension rubric. The judge returns a score between
    0.0 and 1.0 with explanatory reasoning.

    The judge model is STATIC and FIXED to "gpt-5.4-mini" to ensure evaluation
    independence and consistency across all scoring operations.

    Attributes:
        strategy_id: Unique identifier for this scoring strategy ("llm_judge").
        _client: Optional pre-configured OpenAI client for testing.
        _judge_model: Static model identifier (always "gpt-5.4-mini").

    Example:
        >>> strategy = LLMJudgeStrategy()
        >>> score = strategy.score(step, response_text, run_id, latency_ms, case)
    """

    strategy_id: str = "llm_judge"

    def __init__(self, client: Any | None = None) -> None:
        """Initialize the LLM judge strategy.

        Args:
            client: Optional pre-configured OpenAI client.
                If not provided, a new client will be created using default
                environment configuration (OPENAI_API_KEY).
        """
        self._client = client
        self._judge_model = DEFAULT_JUDGE_MODEL

    def _get_client(self) -> Any:
        """Get or create the OpenAI client.

        Returns:
            Configured OpenAI AsyncOpenAI client.

        Raises:
            ImportError: If openai package is not installed.
        """
        if self._client is not None:
            return self._client

        try:
            import openai

            self._client = openai.AsyncOpenAI()
            return self._client
        except ImportError as e:
            raise ImportError(
                "openai package is required for LLMJudgeStrategy. Install with: pip install openai"
            ) from e

    def _build_judge_prompt(
        self,
        summary_text: str,
        case: ReviewCaseDefinition,
    ) -> str:
        """Build the judge prompt with rubric and case data.

        Args:
            summary_text: The review summary text to evaluate.
            case: The review case containing ticket and diff.

        Returns:
            Formatted judge prompt string.
        """
        return JUDGE_PROMPT_TEMPLATE.format(
            summary_text=summary_text,
            ticket_text=case.ticket_text,
            diff_patch=case.diff_patch,
        )

    def _parse_judge_response(self, response_text: str) -> tuple[float, str]:
        """Parse the judge response to extract score and reasoning.

        Attempts to extract a JSON object with 'score' and 'reasoning' fields.
        Falls back to pattern matching if JSON parsing fails.

        Args:
            response_text: Raw text response from the judge LLM.

        Returns:
            Tuple of (score: float, reasoning: str).

        Raises:
            ValueError: If response cannot be parsed for a valid score.
        """
        json_patterns = [
            r"```json\s*(\{.*?\})\s*```",  # Markdown JSON block
            r"```\s*(\{.*?\})\s*```",  # Generic code block with JSON
            r'(\{\s*"score".*?\})',  # Raw JSON object with score field
        ]

        json_str = None
        for pattern in json_patterns:
            match = re.search(pattern, response_text, re.DOTALL)
            if match:
                json_str = match.group(1)
                break

        if json_str is None:
            json_str = response_text.strip()

        try:
            data = json.loads(json_str)
            if "score" in data:
                score = float(data["score"])
                reasoning = data.get("reasoning", "No reasoning provided")
                if score > 10.0 and score <= 100.0:
                    score = score / 100.0
                score = max(0.0, min(1.0, score))
                return score, reasoning
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        score_pattern = r"(?:score|rating)[\s:=]+(\d+\.?\d*)"
        match = re.search(score_pattern, response_text, re.IGNORECASE)
        if match:
            try:
                score = float(match.group(1))
                if score > 1.0 and score <= 100.0:
                    score = score / 100.0
                score = max(0.0, min(1.0, score))
                return score, "Score extracted via pattern matching"
            except ValueError:
                pass

        raise ValueError(f"Could not parse valid score from judge response: {response_text[:200]}")

    async def _invoke_judge(self, prompt: str) -> str:
        """Invoke the judge LLM with the given prompt.

        Args:
            prompt: The formatted judge prompt.

        Returns:
            Raw text response from the judge LLM.
        """
        client = self._get_client()

        response = await client.chat.completions.create(
            model=self._judge_model,
            max_completion_tokens=1024,
            temperature=0,  # Deterministic for consistent judging
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        )

        # Extract text content from response (OpenAI format)
        return str(response.choices[0].message.content)

    async def score(
        self,
        step: StepDefinition,
        response_text: str,
        run_id: str,
        latency_ms: int,
        case: ReviewCaseDefinition,
    ) -> StepScore:
        """Score the review summary using an LLM judge.

        Args:
            step: The workflow step definition containing scoring configuration.
            response_text: The review summary text to evaluate.
            run_id: Unique identifier for this evaluation run.
            latency_ms: Latency of the agent response in milliseconds.
            case: The review case containing ticket and diff context.

        Returns:
            StepScore containing the computed score and metadata.

        Note:
            If the judge response cannot be parsed, returns a neutral score
            of 0.5 with an explanation in the details.
        """
        judge_prompt = self._build_judge_prompt(response_text, case)

        judge_response = await self._invoke_judge(judge_prompt)

        try:
            score, reasoning = self._parse_judge_response(judge_response)
            parse_failed = False
        except ValueError as e:
            logger.warning(
                "LLM judge parse failure for run_id=%s, case_id=%s: %s",
                run_id,
                case.case_id,
                str(e),
            )
            score = 0.5
            reasoning = f"Parse failure fallback: {str(e)}"
            parse_failed = True

        weight = step.scoring.weight if step.scoring else 1.0
        weighted_score = score * weight

        passed = score >= 0.5

        return StepScore(
            run_id=run_id,
            case_id=case.case_id,
            step_id=step.step_id,
            strategy=self.strategy_id,
            raw_score=score,
            weighted_score=weighted_score,
            latency_ms=latency_ms,
            passed=passed,
            details={
                "reasoning": reasoning,
                "judge_model": self._judge_model,
                "judge_prompt": judge_prompt,
                "judge_response": judge_response,
                "parse_failed": parse_failed,
                "weight_applied": weight,
            },
        )
