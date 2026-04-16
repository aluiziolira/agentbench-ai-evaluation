"""LLM-based judge scoring strategy for AgentBench.

This module implements the LLMJudgeStrategy that uses an LLM (gpt-5.4-mini)
to evaluate the quality of PR review summaries against a rubric with five dimensions.
"""

import json
import logging
import re
from typing import Any

from openai.lib._pydantic import to_strict_json_schema
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from agentbench.cases.models import ReviewCaseDefinition
from agentbench.models.results import StepScore
from agentbench.models.workflow import StepDefinition

OPENAI_ERRORS: tuple[type[Exception], ...]

try:
    from openai import APIError, APITimeoutError, RateLimitError

    OPENAI_ERRORS = (APIError, APITimeoutError, RateLimitError)
except ImportError:

    class _OpenAIErrorFallbackError(Exception):
        """Fallback OpenAI error type used when imports are unavailable."""

    OPENAI_ERRORS = (_OpenAIErrorFallbackError,)


class DimensionScores(BaseModel):
    """Strict rubric dimension scores for all five dimensions."""

    prioritization: float = Field(ge=0.0, le=1.0)
    grounding: float = Field(ge=0.0, le=1.0)
    test_coverage: float = Field(ge=0.0, le=1.0)
    no_filler: float = Field(ge=0.0, le=1.0)
    actionability: float = Field(ge=0.0, le=1.0)


class JudgeVerdict(BaseModel):
    """Structured output for the LLM judge with validation."""

    dimension_scores: DimensionScores = Field(description="Individual scores per rubric dimension")
    score: float = Field(ge=0.0, le=1.0, description="Quality score between 0.0 and 1.0")
    reasoning: str = Field(min_length=10, description="Explanation based on rubric dimensions")

    @field_validator("score", mode="before")
    @classmethod
    def normalize_scale(cls, v: Any) -> float:
        """Handle percentage scale (85 → 0.85) and reject invalid ranges."""
        score = float(v)
        if 0.0 <= score <= 1.0:
            return score
        if 10.0 < score <= 100.0:
            return score / 100.0
        raise ValueError("score must be in [0.0, 1.0] or percentage scale in (10.0, 100.0]")

    @model_validator(mode="after")
    def validate_score_average(self) -> "JudgeVerdict":
        """Ensure overall score matches rubric dimension average."""
        dimensions = self.dimension_scores
        avg = (
            dimensions.prioritization
            + dimensions.grounding
            + dimensions.test_coverage
            + dimensions.no_filler
            + dimensions.actionability
        ) / 5.0

        if abs(self.score - avg) > 0.01:
            raise ValueError(
                f"score must equal average of dimensions within 0.01 tolerance: score={self.score:.4f}, average={avg:.4f}"
            )

        return self


JUDGE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "judge_verdict",
        "strict": True,
        "schema": to_strict_json_schema(JudgeVerdict),
    },
}
logger = logging.getLogger(__name__)
PARSE_FAILURE_REASON_PREFIX = "Could not parse valid score from judge response"

DEFAULT_JUDGE_MODEL = "gpt-5.4-mini"

JUDGE_PROMPT_TEMPLATE = """You are evaluating a PR review summary.

Score each dimension using ONLY these anchors:

1) Prioritizes most important issue first (key: prioritization)
- 1.0: Leads with highest-impact issue first.
- 0.7: Top issue identified; ordering slightly off.
- 0.3: Important issues buried or weakly ordered.
- 0.0: No prioritization; critical issues missing.

2) Grounded in actual diff and ticket (key: grounding)
- 1.0: Claims specific and tied to diff/ticket.
- 0.7: Generally grounded; minor vagueness.
- 0.3: Several generic or weakly supported claims.
- 0.0: Ungrounded or hallucinated claims.

3) Mentions missing tests when relevant (key: test_coverage)
- 1.0: Correctly flags missing tests or states coverage is adequate.
- 0.7: Addresses test relevance but misses nuance.
- 0.3: Superficial or unclear test treatment.
- 0.0: Ignores a relevant test gap.

4) Avoids filler and low-value commentary (key: no_filler)
- 1.0: Concise, signal-dense, no fluff.
- 0.7: Mostly concise; minor filler.
- 0.3: Noticeable filler that dilutes feedback.
- 0.0: Predominantly filler.

5) Actionable for PR author (key: actionability)
- 1.0: Clear, concrete next steps.
- 0.7: Actionable overall; some steps underspecified.
- 0.3: Vague suggestions with limited guidance.
- 0.0: Not actionable; no clear next steps.

Scoring rule:
- Overall score = arithmetic average of the five dimension scores.
- Keep all scores in [0.0, 1.0].

Review Summary to evaluate:
{summary_text}

Ticket:
{ticket_text}

Diff:
{diff_patch}

Return JSON:
{{
  "dimension_scores": {{
    "prioritization": <float 0.0-1.0>,
    "grounding": <float 0.0-1.0>,
    "test_coverage": <float 0.0-1.0>,
    "no_filler": <float 0.0-1.0>,
    "actionability": <float 0.0-1.0>
  }},
  "score": <float 0.0-1.0, average of dimension_scores>,
  "reasoning": "<brief explanation referencing the rubric dimensions>"
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
        """Initialize LLM judge with optional pre-configured OpenAI client."""
        self._client = client
        self._judge_model = DEFAULT_JUDGE_MODEL

    def _get_client(self) -> Any:
        """Get or create the OpenAI client."""
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
        """Build the judge prompt with rubric and case data."""
        return JUDGE_PROMPT_TEMPLATE.format(
            summary_text=summary_text,
            ticket_text=case.ticket_text,
            diff_patch=case.diff_patch,
        )

    def _parse_judge_response(self, response_text: str) -> tuple[float, str]:
        """Parse judge response to extract score and reasoning.

        Layered defensive parsing:
        1) Pydantic validation on candidate JSON payloads
        2) json-repair recovery + Pydantic validation
        3) Regex score extraction fallback
        """
        verdict = self._parse_judge_response_unified(response_text)
        return verdict.score, verdict.reasoning

    def _build_fallback_verdict(
        self,
        score: float,
        reasoning: str,
        extracted_dimensions: dict[str, float] | None = None,
    ) -> JudgeVerdict:
        """Build a JudgeVerdict resilient to dimension_scores model shape."""
        extracted_dimensions = extracted_dimensions or {}

        dimension_field = JudgeVerdict.model_fields.get("dimension_scores")
        dimension_annotation = (
            getattr(dimension_field, "annotation", None) if dimension_field is not None else None
        )

        dimension_payload: BaseModel | dict[str, float]
        if isinstance(dimension_annotation, type) and issubclass(dimension_annotation, BaseModel):
            dimension_payload = dimension_annotation.model_validate(
                {
                    name: max(0.0, min(1.0, float(extracted_dimensions.get(name, score))))
                    for name in dimension_annotation.model_fields
                }
            )
        else:
            dimension_payload = {
                k: max(0.0, min(1.0, float(v))) for k, v in extracted_dimensions.items()
            }

        reasoning_text = reasoning.strip() or "Score extracted via regex fallback"
        if len(reasoning_text) < 10:
            reasoning_text = f"{reasoning_text} (fallback)"

        return JudgeVerdict.model_validate(
            {
                "dimension_scores": dimension_payload,
                "score": score,
                "reasoning": reasoning_text,
            }
        )

    def _extract_dimension_scores_regex(
        self, response_text: str, fallback_score: float
    ) -> dict[str, float]:
        """Extract per-dimension scores via regex with score fallback."""
        dimension_keys = [
            "prioritization",
            "grounding",
            "test_coverage",
            "no_filler",
            "actionability",
        ]

        dimension_scores: dict[str, float] = {}
        for key in dimension_keys:
            key_pattern = rf"[\"']?{re.escape(key)}[\"']?\s*[:=]\s*(-?\d+(?:\.\d+)?)"
            match = re.search(key_pattern, response_text, re.IGNORECASE)
            if not match:
                continue

            try:
                value = float(match.group(1))
                if 10.0 < value <= 100.0:
                    value = value / 100.0
                dimension_scores[key] = max(0.0, min(1.0, value))
            except ValueError:
                continue

        if not dimension_scores:
            dimension_scores = dict.fromkeys(dimension_keys, fallback_score)

        return dimension_scores

    def _parse_judge_response_unified(self, response_text: str) -> JudgeVerdict:
        """Parse judge response through unified runtime fallback path."""
        json_patterns = [
            r"```json\s*(\{.*?\})\s*```",  # Markdown JSON block
            r"```\s*(\{.*?\})\s*```",  # Generic code block with JSON
            r'(\{\s*"score".*?\})',  # Raw JSON object with score field
        ]

        json_candidates: list[str] = []
        for pattern in json_patterns:
            for match in re.finditer(pattern, response_text, re.DOTALL):
                candidate = match.group(1).strip()
                if candidate and candidate not in json_candidates:
                    json_candidates.append(candidate)

        response_stripped = response_text.strip()
        if response_stripped and response_stripped not in json_candidates:
            json_candidates.append(response_stripped)

        # Layer 1: strict Pydantic parsing
        for json_candidate in json_candidates:
            try:
                return JudgeVerdict.model_validate_json(json_candidate)
            except (ValidationError, ValueError, TypeError):
                continue

        # Layer 2: json-repair fallback + Pydantic validation
        try:
            from json_repair import repair_json

            has_repair = True
        except ImportError:
            has_repair = False

        if has_repair:
            for json_candidate in json_candidates:
                try:
                    repaired = repair_json(json_candidate)
                    if isinstance(repaired, str):
                        verdict = JudgeVerdict.model_validate_json(repaired)
                    else:
                        verdict = JudgeVerdict.model_validate(repaired)
                    return verdict
                except (ValidationError, ValueError, TypeError, json.JSONDecodeError):
                    continue

        # Layer 3: regex score extraction
        score_pattern = r"[\"']?(?:score|rating)[\"']?\s*[:=]\s*(-?\d+(?:\.\d+)?)"
        score_match = re.search(score_pattern, response_text, re.IGNORECASE)
        if score_match:
            try:
                score = JudgeVerdict.normalize_scale(float(score_match.group(1)))

                reasoning_json_pattern = (
                    r'"(?:reasoning|explanation)"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"'
                )
                reasoning_json_match = re.search(
                    reasoning_json_pattern, response_text, re.IGNORECASE
                )
                if reasoning_json_match:
                    reasoning = bytes(reasoning_json_match.group(1), "utf-8").decode(
                        "unicode_escape"
                    )
                else:
                    reasoning_pattern = r"(?:reasoning|explanation)[\s:=]+(.+)"
                    reasoning_match = re.search(
                        reasoning_pattern,
                        response_text,
                        re.IGNORECASE | re.DOTALL,
                    )
                    reasoning = (
                        reasoning_match.group(1).strip()
                        if reasoning_match
                        else "Score extracted via regex fallback"
                    )

                dimension_scores = self._extract_dimension_scores_regex(response_text, score)
                return self._build_fallback_verdict(score, reasoning, dimension_scores)
            except ValueError:
                pass

        fallback_reasoning = (
            f"{PARSE_FAILURE_REASON_PREFIX}; defaulted to 0.0. "
            f"Response excerpt: {response_text[:200]}"
        )
        return self._build_fallback_verdict(0.0, fallback_reasoning)

    async def _invoke_judge(self, prompt: str) -> JudgeVerdict:
        """Invoke the judge LLM with structured output guarantees."""
        client = self._get_client()

        response = await client.chat.completions.create(
            model=self._judge_model,
            max_completion_tokens=1500,
            temperature=0,  # Deterministic for consistent judging
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            response_format=JUDGE_RESPONSE_FORMAT,
            seed=42,
        )

        message = response.choices[0].message

        refusal = getattr(message, "refusal", None)
        if isinstance(refusal, str) and refusal:
            raise ValueError(f"Judge refused to respond: {refusal}")

        content = message.content
        if isinstance(content, str):
            response_text = content
        elif isinstance(content, list):
            response_text = "".join(
                part.get("text", "") if isinstance(part, dict) else getattr(part, "text", "")
                for part in content
            )
        else:
            response_text = str(content)

        return self._parse_judge_response_unified(response_text)

    async def score(
        self,
        step: StepDefinition,
        response_text: str,
        run_id: str,
        latency_ms: int,
        case: ReviewCaseDefinition,
    ) -> StepScore:
        """Score review summary with dimension-level breakdown.

        Returns StepScore with dimension_scores, error_type, and parse_failed metadata.
        Note: event-driven pipeline receives simplified payload; direct score_response() calls preserve full details.
        """
        judge_prompt = self._build_judge_prompt(response_text, case)

        judge_response: Any = None
        dimension_scores: dict[str, float] = {}
        error_type: str | None = None

        try:
            judge_response = await self._invoke_judge(judge_prompt)
            score = judge_response.score
            reasoning = judge_response.reasoning
            dimension_scores = judge_response.dimension_scores.model_dump()
            parse_failed = False
        except OPENAI_ERRORS as e:
            logger.error(
                "LLM judge API error for run_id=%s, case_id=%s: %s",
                run_id,
                case.case_id,
                str(e),
            )
            score = 0.0
            reasoning = f"API failure fallback: {str(e)}"
            dimension_scores = {}
            parse_failed = True
            error_type = "api_error"
        except (ValidationError, ValueError, TypeError) as e:
            logger.warning(
                "LLM judge parse failure for run_id=%s, case_id=%s: %s",
                run_id,
                case.case_id,
                str(e),
            )
            score = 0.0
            reasoning = f"Parse failure fallback: {str(e)}"
            dimension_scores = {}
            parse_failed = True
            error_type = "parse_error"

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
                "judge_response": (
                    judge_response.model_dump()
                    if isinstance(judge_response, JudgeVerdict)
                    else judge_response
                ),
                "dimension_scores": dimension_scores,
                "parse_failed": parse_failed,
                "error_type": error_type,
                "weight_applied": weight,
            },
        )
