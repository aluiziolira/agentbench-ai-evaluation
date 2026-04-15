"""Tests for the LLM judge scoring strategy.

This module tests the LLMJudgeStrategy that evaluates PR review summaries
against a five-dimension rubric using an LLM (gpt-5.4-mini).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agentbench.cases.models import ReviewCaseDefinition, ReviewFindingTruth
from agentbench.models import ScoringConfig, StepDefinition, StepScore
from agentbench.scoring.strategies.llm_judge import (
    DEFAULT_JUDGE_MODEL,
    LLMJudgeStrategy,
)


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
    """Tests for parsing the judge response."""

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
        response = '```json\n{"score": 0.75, "reasoning": "Okay"}\n```'

        score, reasoning = strategy._parse_judge_response(response)

        assert score == 0.75
        assert reasoning == "Okay"

    def test_parse_json_in_generic_code_block(self):
        """Test parsing JSON wrapped in generic markdown code block."""
        strategy = LLMJudgeStrategy()
        response = '```\n{"score": 0.90, "reasoning": "Excellent"}\n```'

        score, reasoning = strategy._parse_judge_response(response)

        assert score == 0.90

    def test_score_clamped_to_valid_range(self):
        """Test that scores outside 0.0-1.0 are clamped."""
        strategy = LLMJudgeStrategy()

        # Score above 1.0 should be clamped to 1.0
        response = '{"score": 1.5, "reasoning": "Too high"}'
        score, _ = strategy._parse_judge_response(response)
        assert score == 1.0

        # Score below 0.0 should be clamped to 0.0
        response = '{"score": -0.5, "reasoning": "Too low"}'
        score, _ = strategy._parse_judge_response(response)
        assert score == 0.0

    def test_parse_failure_raises_value_error(self):
        """Test that invalid JSON raises ValueError."""
        strategy = LLMJudgeStrategy()
        response = "Not valid JSON"

        with pytest.raises(ValueError):
            strategy._parse_judge_response(response)


class TestScoreMethod:
    """Tests for the async score method."""

    @pytest.mark.asyncio
    async def test_score_success(self, sample_step, sample_case):
        """Test successful scoring with mocked judge."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        # OpenAI format: choices[0].message.content
        mock_choice = MagicMock()
        mock_choice.message.content = '{"score": 0.85, "reasoning": "Good review"}'
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
        assert score.details["reasoning"] == "Good review"
        assert score.details["judge_model"] == DEFAULT_JUDGE_MODEL
        assert score.details["parse_failed"] is False

        # Verify the judge was called
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == DEFAULT_JUDGE_MODEL
        assert call_kwargs["temperature"] == 0

    @pytest.mark.asyncio
    async def test_score_with_parse_failure_fallback(self, sample_step, sample_case):
        """Test that parse failures return 0.5 with explanation."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        # OpenAI format: choices[0].message.content
        mock_choice = MagicMock()
        mock_choice.message.content = "Invalid JSON"
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

        # Should get fallback score of 0.5
        assert score.raw_score == 0.5
        assert score.passed is True  # 0.5 >= 0.5
        assert score.details["parse_failed"] is True
        assert "Parse failure fallback" in score.details["reasoning"]

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
        mock_choice.message.content = '{"score": 0.80, "reasoning": "Good"}'
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

    @pytest.mark.asyncio
    async def test_score_passed_threshold(self, sample_case, sample_step):
        """Test that scores >= 0.5 are marked as passed."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        # OpenAI format: choices[0].message.content
        mock_choice = MagicMock()
        mock_choice.message.content = '{"score": 0.49, "reasoning": "Just below"}'
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


class TestTemperatureSetting:
    """Tests for temperature configuration."""

    @pytest.mark.asyncio
    async def test_temperature_is_zero_for_determinism(self, sample_case):
        """Test that temperature is set to 0 for deterministic judging."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        # OpenAI format: choices[0].message.content
        mock_choice = MagicMock()
        mock_choice.message.content = '{"score": 0.9, "reasoning": "Great"}'
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
