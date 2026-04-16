"""Tests for the LLM judge scoring strategy.

This module tests the LLMJudgeStrategy that evaluates PR review summaries
against a five-dimension rubric using an LLM (gpt-5.4-mini).
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

import agentbench.scoring.strategies.llm_judge as llm_judge_module
from agentbench.cases.models import ReviewCaseDefinition, ReviewFindingTruth
from agentbench.models import ScoringConfig, StepDefinition, StepScore
from agentbench.scoring.strategies.llm_judge import (
    DEFAULT_JUDGE_MODEL,
    JudgeVerdict,
    LLMJudgeStrategy,
)


class DummyAPIError(Exception):
    """Base API error for testing OPENAI_ERRORS handling."""


class DummyAPITimeoutError(Exception):
    """Timeout API error for testing OPENAI_ERRORS handling."""


class DummyRateLimitError(Exception):
    """Rate limit API error for testing OPENAI_ERRORS handling."""


class DummyAuthenticationError(DummyAPIError):
    """Auth-like error caught through APIError base class path."""


@pytest.fixture
def sample_case():
    """Create a sample review case."""
    return ReviewCaseDefinition(
        case_id="pr_001",
        case_set_id="test_v1",
        difficulty="medium",
        tags=["auth", "security"],
        ticket_text="Add user authentication endpoint",
        diff_patch="diff --git a/app.py b/app.py\n+def login():\n+    pass",
        expected_findings=[
            ReviewFindingTruth(
                finding_id="F1",
                canonical_label="missing_permission_check",
                severity="high",
                file_path="app.py",
                line_span=(10, 20),
                must_detect=True,
                summary="Missing auth check",
            )
        ],
    )


@pytest.fixture
def sample_step():
    """Create a sample step definition for s2_review_summary."""
    return StepDefinition(
        step_id="s2_review_summary",
        order=1,
        input="Write a review summary for:\n\nTicket:\n{ticket_text}\n\nDiff:\n{diff_patch}",
        timeout_ms=15000,
        scoring=ScoringConfig(strategy="llm_judge", weight=1.0),
    )


class TestLLMJudgeInitialization:
    """Tests for LLMJudgeStrategy initialization."""

    def test_default_judge_model(self):
        """Test that the default judge model is gpt-5.4-mini."""
        assert DEFAULT_JUDGE_MODEL == "gpt-5.4-mini"

    def test_strategy_id(self):
        """Test that strategy_id is 'llm_judge'."""
        strategy = LLMJudgeStrategy()
        assert strategy.strategy_id == "llm_judge"

    def test_init_with_custom_client(self):
        """Test initialization with a custom OpenAI client."""
        mock_client = MagicMock()
        strategy = LLMJudgeStrategy(client=mock_client)
        assert strategy._client is mock_client


class TestJudgePrompt:
    """Tests for the judge prompt template."""

    def test_rubric_dimensions_in_prompt(self, sample_case):
        """Test that all 5 rubric dimensions are in the prompt template."""
        strategy = LLMJudgeStrategy()
        prompt = strategy._build_judge_prompt("Summary text", sample_case)

        # Check all 5 required dimensions
        assert "Prioritizes most important issue first" in prompt
        assert "Grounded in actual diff and ticket" in prompt
        assert "Mentions missing tests when relevant" in prompt
        assert "Avoids filler and low-value commentary" in prompt
        assert "Actionable for PR author" in prompt

    def test_score_range_in_prompt(self, sample_case):
        """Test that score range 0.0-1.0 is specified in the prompt."""
        strategy = LLMJudgeStrategy()
        prompt = strategy._build_judge_prompt("Summary", sample_case)

        assert "0.0-1.0" in prompt

    def test_json_output_format(self, sample_case):
        """Test that prompt requests JSON output with score and reasoning."""
        strategy = LLMJudgeStrategy()
        prompt = strategy._build_judge_prompt("Summary", sample_case)

        assert '"score":' in prompt
        assert '"reasoning":' in prompt

    def test_prompt_includes_case_data(self, sample_case):
        """Test that prompt includes ticket and diff from case."""
        strategy = LLMJudgeStrategy()
        prompt = strategy._build_judge_prompt("Review summary here", sample_case)

        assert sample_case.ticket_text in prompt
        assert sample_case.diff_patch in prompt
        assert "Review summary here" in prompt


class TestScoreParsing:
    """Tests for JudgeVerdict validation and legacy parse helper."""

    def test_judge_verdict_normalize_scale(self):
        """JudgeVerdict should normalize percentage scale to 0.0-1.0."""
        assert JudgeVerdict.normalize_scale(85) == 0.85

        verdict = JudgeVerdict.model_validate(
            {
                "dimension_scores": {
                    "prioritization": 0.85,
                    "grounding": 0.85,
                    "test_coverage": 0.85,
                    "no_filler": 0.85,
                    "actionability": 0.85,
                },
                "score": 0.85,
                "reasoning": "Strong, actionable summary with clear prioritization.",
            }
        )
        assert verdict.score == 0.85

    def test_judge_verdict_clamps_score_range(self):
        """JudgeVerdict should reject values outside allowed score scales."""
        with pytest.raises(ValueError):
            JudgeVerdict.normalize_scale(1.5)
        with pytest.raises(ValueError):
            JudgeVerdict.normalize_scale(-0.25)

    def test_parse_valid_json_response(self):
        """Test parsing a valid JSON response."""
        strategy = LLMJudgeStrategy()
        response = '{"score": 0.85, "reasoning": "Good summary"}'

        score, reasoning = strategy._parse_judge_response(response)

        assert score == 0.85
        assert reasoning == "Good summary"

    def test_parse_json_in_markdown_code_block(self):
        """Test parsing JSON wrapped in markdown code block."""
        strategy = LLMJudgeStrategy()
        response = (
            '```json\n{"score": 0.75, "reasoning": "Okay summary with concrete priorities."}\n```'
        )

        score, reasoning = strategy._parse_judge_response(response)

        assert score == 0.75
        assert reasoning == "Okay summary with concrete priorities."

    def test_parse_json_in_generic_code_block(self):
        """Test parsing JSON wrapped in generic markdown code block."""
        strategy = LLMJudgeStrategy()
        response = (
            '```\n{"score": 0.90, "reasoning": "Excellent review with actionable guidance."}\n```'
        )

        score, reasoning = strategy._parse_judge_response(response)

        assert score == 0.90
        assert reasoning == "Excellent review with actionable guidance."

    def test_score_clamped_to_valid_range(self):
        """Test that invalid score scales are rejected."""
        strategy = LLMJudgeStrategy()

        # Regex fallback score above percentage scale should fall back to 0.0 verdict
        response = "score=150 reasoning=Detailed explanation for high score clamp"
        score, reasoning = strategy._parse_judge_response(response)
        assert score == 0.0
        assert "defaulted to 0.0" in reasoning

        # Boundary 0.0 should stay at 0.0
        response = (
            '{"dimension_scores": {"prioritization": 0.0, "grounding": 0.0, '
            '"test_coverage": 0.0, "no_filler": 0.0, "actionability": 0.0}, '
            '"score": 0.0, "reasoning": "Detailed low boundary explanation."}'
        )
        score, _ = strategy._parse_judge_response(response)
        assert score == 0.0

    def test_judge_verdict_requires_reasoning_length(self):
        """JudgeVerdict enforces minimum reasoning length."""
        with pytest.raises(ValidationError):
            JudgeVerdict.model_validate(
                {
                    "dimension_scores": {
                        "prioritization": 0.5,
                        "grounding": 0.5,
                        "test_coverage": 0.5,
                        "no_filler": 0.5,
                        "actionability": 0.5,
                    },
                    "score": 0.5,
                    "reasoning": "short",
                }
            )

    def test_parse_failure_raises_value_error(self):
        """Test that invalid JSON falls back to zero-score verdict."""
        strategy = LLMJudgeStrategy()
        response = "Not valid JSON"

        score, reasoning = strategy._parse_judge_response(response)
        assert score == 0.0
        assert "defaulted to 0.0" in reasoning


class TestScoreMethod:
    """Tests for the async score method."""

    @pytest.mark.asyncio
    async def test_score_success(self, sample_step, sample_case):
        """Test successful scoring with mocked judge."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        # OpenAI format: choices[0].message.content
        mock_choice = MagicMock()
        mock_choice.message.content = (
            '{"dimension_scores": {"prioritization": 0.9, "grounding": 0.8, '
            '"test_coverage": 0.9, "no_filler": 0.8, "actionability": 0.85}, '
            '"score": 0.85, "reasoning": "Good review with clear prioritization."}'
        )
        mock_choice.message.refusal = None
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        strategy = LLMJudgeStrategy(client=mock_client)

        score = await strategy.score(
            step=sample_step,
            response_text="This is a good review summary.",
            run_id="run-001",
            latency_ms=1000,
            case=sample_case,
        )

        assert isinstance(score, StepScore)
        assert score.run_id == "run-001"
        assert score.case_id == sample_case.case_id
        assert score.step_id == "s2_review_summary"
        assert score.strategy == "llm_judge"
        assert score.raw_score == 0.85
        assert score.weighted_score == 0.85  # weight is 1.0
        assert score.latency_ms == 1000
        assert score.passed is True  # >= 0.5
        assert score.details["reasoning"] == "Good review with clear prioritization."
        assert score.details["dimension_scores"] == {
            "prioritization": 0.9,
            "grounding": 0.8,
            "test_coverage": 0.9,
            "no_filler": 0.8,
            "actionability": 0.85,
        }
        assert score.details["judge_model"] == DEFAULT_JUDGE_MODEL
        assert score.details["parse_failed"] is False
        assert score.details["error_type"] is None
        assert score.scoring_failed is False
        assert score.error_type is None

        # Verify the judge was called
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == DEFAULT_JUDGE_MODEL
        assert call_kwargs["temperature"] == 0

    @pytest.mark.asyncio
    async def test_score_with_parse_failure_fallback(self, sample_step, sample_case):
        """Test that invalid judge content falls back to zero score verdict."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        # OpenAI format: choices[0].message.content
        mock_choice = MagicMock()
        mock_choice.message.content = "Invalid JSON"
        mock_choice.message.refusal = None
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        strategy = LLMJudgeStrategy(client=mock_client)

        score = await strategy.score(
            step=sample_step,
            response_text="Summary",
            run_id="run-002",
            latency_ms=500,
            case=sample_case,
        )

        # Parser fallback returns score 0.0 without raising, but is flagged
        # as a scoring failure so it's never averaged in as a real 0.0.
        assert score.raw_score == 0.0
        assert score.passed is False
        assert score.details["parse_failed"] is True
        assert score.details["error_type"] == "parse_error"
        assert score.scoring_failed is True
        assert score.error_type == "parse_error"
        assert "defaulted to 0.0" in score.details["reasoning"]

    @pytest.mark.asyncio
    async def test_parse_failure_returns_failed(self, sample_step, sample_case):
        """Explicit regression test for parse failure behavior."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "{"  # malformed JSON
        mock_choice.message.refusal = None
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        strategy = LLMJudgeStrategy(client=mock_client)
        score = await strategy.score(
            step=sample_step,
            response_text="Summary",
            run_id="run-002b",
            latency_ms=500,
            case=sample_case,
        )

        assert score.raw_score == 0.0
        assert score.passed is False
        assert score.details["parse_failed"] is True
        assert score.details["error_type"] == "parse_error"
        assert score.scoring_failed is True
        assert score.error_type == "parse_error"

    @pytest.mark.asyncio
    async def test_score_rejects_wrong_rubric_key_name(self, sample_step, sample_case):
        """Wrong rubric key (priority vs prioritization) must fail validation."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = (
            '{"dimension_scores": {"priority": 0.9, "grounding": 0.8, '
            '"test_coverage": 0.8, "no_filler": 0.8, "actionability": 0.8}, '
            '"score": 0.82, "reasoning": "Detailed rubric reasoning with concrete guidance."}'
        )
        mock_choice.message.refusal = None
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        strategy = LLMJudgeStrategy(client=mock_client)
        score = await strategy.score(
            step=sample_step,
            response_text="Summary",
            run_id="run-contract-001",
            latency_ms=400,
            case=sample_case,
        )

        assert score.raw_score == 0.0
        assert score.passed is False

    @pytest.mark.asyncio
    async def test_score_rejects_missing_dimension_no_filler(self, sample_step, sample_case):
        """Missing rubric dimension (no_filler) must fail validation."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = (
            '{"dimension_scores": {"prioritization": 0.2, "grounding": 0.2, '
            '"test_coverage": 0.2, "actionability": 0.2}, "score": 0.9, '
            '"reasoning": "Detailed rubric reasoning with concrete guidance."}'
        )
        mock_choice.message.refusal = None
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        strategy = LLMJudgeStrategy(client=mock_client)
        score = await strategy.score(
            step=sample_step,
            response_text="Summary",
            run_id="run-contract-002",
            latency_ms=400,
            case=sample_case,
        )

        assert score.raw_score == 0.0
        assert score.passed is False

    @pytest.mark.asyncio
    async def test_score_rejects_extra_unknown_dimension(self, sample_step, sample_case):
        """Extra unknown rubric dimension must fail validation."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = (
            '{"dimension_scores": {"prioritization": 0.2, "grounding": 0.2, '
            '"test_coverage": 0.2, "no_filler": 0.2, "actionability": 0.2, '
            '"unknown_dimension": 1.0}, "score": 0.33, '
            '"reasoning": "Detailed rubric reasoning with concrete guidance."}'
        )
        mock_choice.message.refusal = None
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        strategy = LLMJudgeStrategy(client=mock_client)
        score = await strategy.score(
            step=sample_step,
            response_text="Summary",
            run_id="run-contract-003",
            latency_ms=400,
            case=sample_case,
        )

        assert score.raw_score == 0.0
        assert score.passed is False

    @pytest.mark.asyncio
    async def test_score_rejects_inconsistent_average(self, sample_step, sample_case):
        """Overall score must equal the average of all five dimensions."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = (
            '{"dimension_scores": {"prioritization": 0.6, "grounding": 0.6, '
            '"test_coverage": 0.6, "no_filler": 0.6, "actionability": 0.6}, '
            '"score": 0.9, "reasoning": "Detailed rubric reasoning with concrete guidance."}'
        )
        mock_choice.message.refusal = None
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        strategy = LLMJudgeStrategy(client=mock_client)
        score = await strategy.score(
            step=sample_step,
            response_text="Summary",
            run_id="run-contract-004",
            latency_ms=400,
            case=sample_case,
        )

        assert score.raw_score == 0.0
        assert score.passed is False
        assert score.scoring_failed is True
        assert score.error_type == "parse_error"

    @pytest.mark.asyncio
    async def test_score_applies_weight(self, sample_case):
        """Test that scoring config weight is applied."""
        step_with_weight = StepDefinition(
            step_id="s2_review_summary",
            order=1,
            input="Review",
            timeout_ms=15000,
            scoring=ScoringConfig(strategy="llm_judge", weight=2.0),
        )

        mock_client = MagicMock()
        mock_response = MagicMock()
        # OpenAI format: choices[0].message.content
        mock_choice = MagicMock()
        mock_choice.message.content = (
            '{"dimension_scores": {"prioritization": 0.8, "grounding": 0.8, '
            '"test_coverage": 0.8, "no_filler": 0.8, "actionability": 0.8}, '
            '"score": 0.80, "reasoning": "Good review with practical guidance."}'
        )
        mock_choice.message.refusal = None
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        strategy = LLMJudgeStrategy(client=mock_client)

        score = await strategy.score(
            step=step_with_weight,
            response_text="Summary",
            run_id="run-003",
            latency_ms=1000,
            case=sample_case,
        )

        # raw_score should be 0.80, weighted should be 0.80 * 2.0 = 1.6
        assert score.raw_score == 0.80
        assert score.weighted_score == 1.6
        assert score.details["weight_applied"] == 2.0
        assert score.details["dimension_scores"] == {
            "prioritization": 0.8,
            "grounding": 0.8,
            "test_coverage": 0.8,
            "no_filler": 0.8,
            "actionability": 0.8,
        }

    @pytest.mark.asyncio
    async def test_score_passed_threshold(self, sample_case, sample_step):
        """Test that scores >= 0.5 are marked as passed."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        # OpenAI format: choices[0].message.content
        mock_choice = MagicMock()
        mock_choice.message.content = (
            '{"dimension_scores": {"prioritization": 0.49, "grounding": 0.49, '
            '"test_coverage": 0.49, "no_filler": 0.49, "actionability": 0.49}, '
            '"score": 0.49, "reasoning": "Just below threshold with concise rationale."}'
        )
        mock_choice.message.refusal = None
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        strategy = LLMJudgeStrategy(client=mock_client)

        score = await strategy.score(
            step=sample_step,
            response_text="Summary",
            run_id="run-004",
            latency_ms=1000,
            case=sample_case,
        )

        assert score.raw_score == 0.49
        assert score.passed is False  # < 0.5

    @pytest.mark.asyncio
    async def test_refusal_handling_returns_failed_score(self, sample_step, sample_case):
        """Judge refusal should produce parse failure fallback and failed score."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "{}"
        mock_choice.message.refusal = "safety refusal"
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        strategy = LLMJudgeStrategy(client=mock_client)
        score = await strategy.score(
            step=sample_step,
            response_text="Summary",
            run_id="run-004b",
            latency_ms=1000,
            case=sample_case,
        )

        assert score.raw_score == 0.0
        assert score.passed is False
        assert score.details["parse_failed"] is True
        assert score.details["error_type"] == "parse_error"
        assert score.scoring_failed is True
        assert score.error_type == "parse_error"
        assert "refused" in score.details["reasoning"].lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "api_error_cls",
        [DummyAPITimeoutError, DummyRateLimitError, DummyAuthenticationError],
    )
    async def test_api_errors_return_failed_structured_score(
        self,
        sample_step,
        sample_case,
        monkeypatch,
        caplog,
        api_error_cls,
    ):
        """API timeout/auth/rate-limit errors should return failed structured StepScore."""
        monkeypatch.setattr(
            llm_judge_module,
            "OPENAI_ERRORS",
            (DummyAPIError, DummyAPITimeoutError, DummyRateLimitError),
        )

        strategy = LLMJudgeStrategy(client=MagicMock())
        strategy._invoke_judge = AsyncMock(side_effect=api_error_cls("simulated api failure"))

        with caplog.at_level("ERROR"):
            score = await strategy.score(
                step=sample_step,
                response_text="Summary",
                run_id="run-api-001",
                latency_ms=750,
                case=sample_case,
            )

        assert score.raw_score == 0.0
        assert score.weighted_score == 0.0
        assert score.passed is False
        assert score.details["parse_failed"] is True
        assert score.details["error_type"] == "api_error"
        assert score.scoring_failed is True
        assert score.error_type == "api_error"
        assert "API failure fallback" in score.details["reasoning"]
        assert any("LLM judge API error" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_regex_fallback_marks_scoring_failed(self, sample_step, sample_case):
        """Regex-recovered score (no valid JSON) is flagged as a scoring failure."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "score: 0.8\nreasoning: solid summary overall"
        mock_choice.message.refusal = None
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        strategy = LLMJudgeStrategy(client=mock_client)
        score = await strategy.score(
            step=sample_step,
            response_text="Summary",
            run_id="run-regex-fallback",
            latency_ms=500,
            case=sample_case,
        )

        assert score.raw_score == 0.8
        assert score.scoring_failed is True
        assert score.error_type == "parse_error"
        assert score.details["parse_failed"] is True
        assert score.details["error_type"] == "parse_error"

    @pytest.mark.asyncio
    async def test_details_mirror_first_class_fields(self, sample_step, sample_case):
        """details['parse_failed']/['error_type'] mirror the first-class fields."""
        mock_client = MagicMock()

        # Success case: clean strict JSON parse.
        success_response = MagicMock()
        success_choice = MagicMock()
        success_choice.message.content = (
            '{"dimension_scores": {"prioritization": 0.8, "grounding": 0.8, '
            '"test_coverage": 0.8, "no_filler": 0.8, "actionability": 0.8}, '
            '"score": 0.8, "reasoning": "Solid review with clear guidance."}'
        )
        success_choice.message.refusal = None
        success_response.choices = [success_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=success_response)

        strategy = LLMJudgeStrategy(client=mock_client)
        success_score = await strategy.score(
            step=sample_step,
            response_text="Summary",
            run_id="run-mirror-success",
            latency_ms=500,
            case=sample_case,
        )
        assert success_score.scoring_failed == success_score.details["parse_failed"]
        assert success_score.error_type == success_score.details["error_type"]

        # Failure case: unparseable content triggers the total-failure fallback.
        failure_response = MagicMock()
        failure_choice = MagicMock()
        failure_choice.message.content = "Not valid JSON at all"
        failure_choice.message.refusal = None
        failure_response.choices = [failure_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=failure_response)

        failure_score = await strategy.score(
            step=sample_step,
            response_text="Summary",
            run_id="run-mirror-failure",
            latency_ms=500,
            case=sample_case,
        )
        assert failure_score.scoring_failed == failure_score.details["parse_failed"]
        assert failure_score.error_type == failure_score.details["error_type"]


class TestInvalidScoreScaleRejection:
    """Tests for rejecting unsupported score scales in mocked judge responses."""

    @staticmethod
    async def _score_with_invalid_scale_response(
        sample_step,
        sample_case,
        invalid_response: str,
        run_id: str,
    ) -> StepScore:
        """Score using a mocked invalid-scale response that triggers normalize_scale rejection."""
        strategy = LLMJudgeStrategy(client=MagicMock())

        async def _invoke_with_invalid_scale(_prompt: str) -> JudgeVerdict:
            payload = json.loads(invalid_response)
            # Unsupported scales must be rejected, not clamped.
            JudgeVerdict.normalize_scale(payload["score"])
            return JudgeVerdict.model_validate(payload)

        strategy._invoke_judge = AsyncMock(side_effect=_invoke_with_invalid_scale)

        return await strategy.score(
            step=sample_step,
            response_text="Summary",
            run_id=run_id,
            latency_ms=500,
            case=sample_case,
        )

    @pytest.mark.asyncio
    async def test_rejects_5_point_scale_score(self, sample_step, sample_case):
        """5-point scale score (4.0) should fail instead of becoming 1.0."""
        invalid_response = (
            '{"dimension_scores": {"prioritization": 4.0, "grounding": 4.0, '
            '"test_coverage": 4.0, "no_filler": 4.0, "actionability": 4.0}, '
            '"score": 4.0, "reasoning": "Detailed reasoning for unsupported 5-point scale response."}'
        )

        score = await self._score_with_invalid_scale_response(
            sample_step=sample_step,
            sample_case=sample_case,
            invalid_response=invalid_response,
            run_id="run-invalid-5-point",
        )

        assert score.raw_score == 0.0
        assert score.passed is False
        assert score.details["parse_failed"] is True
        assert score.details["error_type"] == "parse_error"
        assert score.scoring_failed is True
        assert score.error_type == "parse_error"

    @pytest.mark.asyncio
    async def test_rejects_10_point_scale_score(self, sample_step, sample_case):
        """10-point scale score (8.0) should fail instead of becoming 0.8 or 1.0."""
        invalid_response = (
            '{"dimension_scores": {"prioritization": 8.0, "grounding": 8.0, '
            '"test_coverage": 8.0, "no_filler": 8.0, "actionability": 8.0}, '
            '"score": 8.0, "reasoning": "Detailed reasoning for unsupported 10-point scale response."}'
        )

        score = await self._score_with_invalid_scale_response(
            sample_step=sample_step,
            sample_case=sample_case,
            invalid_response=invalid_response,
            run_id="run-invalid-10-point",
        )

        assert score.raw_score == 0.0
        assert score.passed is False
        assert score.details["parse_failed"] is True
        assert score.details["error_type"] == "parse_error"
        assert score.scoring_failed is True
        assert score.error_type == "parse_error"

    @pytest.mark.asyncio
    async def test_rejects_negative_score(self, sample_step, sample_case):
        """Negative score should fail and produce failed StepScore."""
        invalid_response = (
            '{"dimension_scores": {"prioritization": -0.2, "grounding": -0.2, '
            '"test_coverage": -0.2, "no_filler": -0.2, "actionability": -0.2}, '
            '"score": -0.2, "reasoning": "Detailed reasoning for unsupported negative-scale response."}'
        )

        score = await self._score_with_invalid_scale_response(
            sample_step=sample_step,
            sample_case=sample_case,
            invalid_response=invalid_response,
            run_id="run-invalid-negative",
        )

        assert score.raw_score == 0.0
        assert score.passed is False
        assert score.details["parse_failed"] is True
        assert score.details["error_type"] == "parse_error"
        assert score.scoring_failed is True
        assert score.error_type == "parse_error"

    @pytest.mark.asyncio
    async def test_rejects_score_above_100(self, sample_step, sample_case):
        """Score above 100 should fail and produce failed StepScore."""
        invalid_response = (
            '{"dimension_scores": {"prioritization": 150.0, "grounding": 150.0, '
            '"test_coverage": 150.0, "no_filler": 150.0, "actionability": 150.0}, '
            '"score": 150.0, "reasoning": "Detailed reasoning for unsupported >100 score response."}'
        )

        score = await self._score_with_invalid_scale_response(
            sample_step=sample_step,
            sample_case=sample_case,
            invalid_response=invalid_response,
            run_id="run-invalid-over-100",
        )

        assert score.raw_score == 0.0
        assert score.passed is False
        assert score.details["parse_failed"] is True
        assert score.details["error_type"] == "parse_error"
        assert score.scoring_failed is True
        assert score.error_type == "parse_error"


class TestTemperatureSetting:
    """Tests for temperature configuration."""

    @pytest.mark.asyncio
    async def test_temperature_is_zero_for_determinism(self, sample_case):
        """Test that temperature is set to 0 for deterministic judging."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        # OpenAI format: choices[0].message.content
        mock_choice = MagicMock()
        mock_choice.message.content = (
            '{"dimension_scores": {"prioritization": 0.9, "grounding": 0.9, '
            '"test_coverage": 0.9, "no_filler": 0.9, "actionability": 0.9}, '
            '"score": 0.9, "reasoning": "Great review with clear next steps."}'
        )
        mock_choice.message.refusal = None
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        strategy = LLMJudgeStrategy(client=mock_client)

        step_mock = MagicMock()
        step_mock.step_id = "s2_review_summary"
        step_mock.scoring = MagicMock(weight=1.0)

        await strategy.score(
            step=step_mock,
            response_text="Summary",
            run_id="run-005",
            latency_ms=1000,
            case=sample_case,
        )

        # Verify temperature is 0
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0
