"""Deterministic findings matcher scoring strategy.

This module implements the finding_match scoring strategy, which scores
structured findings from s1_findings against seeded ground truth.

The strategy rewards detection of important issues and penalizes noisy
false positives while remaining deterministic and explainable.
"""

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from agentbench.cases.models import (
    DisallowedFinding,
    ReviewCaseDefinition,
    ReviewFindingTruth,
)
from agentbench.models.results import StepScore
from agentbench.models.workflow import StepDefinition

logger = logging.getLogger(__name__)


class AgentFinding(BaseModel):
    """Expected structure of a finding from the agent response.

    This model defines the schema that agent responses must follow
    for the findings step of the PR review workflow.
    """

    canonical_label: str = Field(
        ...,
        description="Label from the canonical taxonomy",
    )
    severity: Literal["high", "medium", "low"] = Field(
        ...,
        description="Severity level of the finding",
    )
    file_path: str = Field(
        ...,
        description="Path to the affected file",
    )
    start_line: int = Field(
        ...,
        description="Start line number (1-indexed, inclusive)",
    )
    end_line: int = Field(
        ...,
        description="End line number (1-indexed, inclusive)",
    )
    title: str = Field(
        default="",
        description="Short title for the finding",
    )
    why_it_matters: str = Field(
        default="",
        description="Explanation of why this finding matters",
    )
    suggested_test: str = Field(
        default="",
        description="Suggested regression test",
    )


class AgentFindingsResponse(BaseModel):
    """Expected structure of the agent's findings response.

    This is the root model that wraps the list of findings.
    """

    findings: list[AgentFinding] = Field(
        default_factory=list,
        description="List of findings identified by the agent",
    )


class FindingMatchStrategy:
    """Deterministic scoring strategy for matching findings.

    This strategy scores agent responses by comparing identified findings
    against ground truth expectations. It uses exact matching on canonical
    labels and file paths, with line range overlap or tolerance matching.

    Scoring Formula:
        - Each must_detect=true finding: 1.0 base points
        - Each optional finding: 0.5 base points
        - Exact severity match: +0.25 bonus
        - One-level severity mismatch: reduced credit (handled in base)
        - Each unmatched false positive: -0.25 penalty
        - Each disallowed finding: -0.50 penalty
        - Floor raw total at 0.0
        - Normalize by max achievable positive points
        - Clamp final raw_score to [0.0, 1.0]

    Matching Rules:
        - canonical_label must match exactly
        - file_path must match exactly
        - Predicted line range must overlap expected line_span OR
          fall within ±5 lines tolerance

    Attributes:
        strategy_id: Unique identifier for this strategy ("finding_match").
        line_tolerance: Number of lines tolerance for line matching (default: 5).
    """

    strategy_id: str = "finding_match"
    line_tolerance: int = 5

    # Severity levels for mismatch calculation
    _severity_levels = {"high": 3, "medium": 2, "low": 1}

    async def score(
        self,
        step: StepDefinition,
        response_text: str,
        run_id: str,
        latency_ms: int,
        case: ReviewCaseDefinition,
    ) -> StepScore:
        """Score an agent's findings response against ground truth.

        Args:
            step: The workflow step definition (s1_findings).
            response_text: The raw JSON response from the agent.
            run_id: Unique identifier for this evaluation run.
            latency_ms: Execution latency in milliseconds.
            case: The review case with ground truth findings.

        Returns:
            StepScore with raw_score, weighted_score, and detailed breakdown.

        Note:
            If the response is not valid JSON matching the schema,
            raw_score will be 0.0 and a warning will be logged.
        """
        # Parse agent response
        parsed_findings = self._parse_response(response_text, run_id, case.case_id)

        if parsed_findings is None:
            # Parse failure - return zero score
            return StepScore(
                run_id=run_id,
                case_id=case.case_id,
                step_id=step.step_id,
                strategy=self.strategy_id,
                raw_score=0.0,
                weighted_score=0.0,
                latency_ms=latency_ms,
                passed=False,
                details={
                    "error": "parse_failure",
                    "message": "Response is not valid JSON matching the required schema",
                    "findings_count": 0,
                    "matches": [],
                    "false_positives": [],
                    "disallowed_findings": [],
                    "missed_findings": [f.finding_id for f in case.expected_findings],
                },
            )

        # Calculate matches and penalties
        matches = self._find_matches(parsed_findings, case.expected_findings)
        false_positives = self._find_false_positives(
            parsed_findings, case.expected_findings, matches
        )
        disallowed = self._find_disallowed(parsed_findings, case.disallowed_findings)
        missed = self._find_missed_findings(case.expected_findings, matches)

        # Calculate raw score
        raw_score = self._calculate_raw_score(
            matches, false_positives, disallowed, case.expected_findings
        )

        # Apply weight
        weight = step.scoring.weight
        weighted_score = raw_score * weight

        # Determine if step passed (using 0.5 as threshold)
        passed = raw_score >= 0.5

        # Build details
        details = {
            "findings_count": len(parsed_findings),
            "expected_findings_count": len(case.expected_findings),
            "matches": matches,
            "false_positives": false_positives,
            "disallowed_findings": disallowed,
            "missed_findings": missed,
            "scoring_breakdown": self._build_scoring_breakdown(
                matches, false_positives, disallowed, case.expected_findings
            ),
        }

        return StepScore(
            run_id=run_id,
            case_id=case.case_id,
            step_id=step.step_id,
            strategy=self.strategy_id,
            raw_score=raw_score,
            weighted_score=weighted_score,
            latency_ms=latency_ms,
            passed=passed,
            details=details,
        )

    def _parse_response(
        self, response_text: str, run_id: str, case_id: str
    ) -> list[AgentFinding] | None:
        """Parse the agent response into structured findings.

        Args:
            response_text: The raw JSON response from the agent.
            run_id: Unique identifier for this evaluation run (for logging).
            case_id: Identifier of the case being evaluated (for logging).

        Returns:
            List of parsed findings, or None if parsing/validation fails.
        """
        try:
            # First, try to parse as JSON
            data = json.loads(response_text)

            # Validate against schema
            response = AgentFindingsResponse.model_validate(data)
            return response.findings

        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning(
                "Failed to parse agent response",
                extra={
                    "correlation_id": run_id,
                    "case_id": case_id,
                    "error": str(e),
                    "response_preview": response_text[:200],
                },
            )
            return None

    def _find_matches(
        self,
        agent_findings: list[AgentFinding],
        expected_findings: list[ReviewFindingTruth],
    ) -> list[dict[str, Any]]:
        """Find matches between agent findings and expected findings.

        A match requires:
        - Exact canonical_label match
        - Exact file_path match
        - Line range overlap OR within tolerance

        Args:
            agent_findings: Findings parsed from agent response.
            expected_findings: Ground truth expected findings.

        Returns:
            List of match records with finding details and severity assessment.
        """
        matches = []

        for expected in expected_findings:
            for agent_finding in agent_findings:
                if self._is_match(agent_finding, expected):
                    severity_match = self._assess_severity_match(
                        agent_finding.severity, expected.severity
                    )
                    matches.append(
                        {
                            "expected_finding_id": expected.finding_id,
                            "canonical_label": expected.canonical_label,
                            "file_path": expected.file_path,
                            "line_match": True,
                            "expected_severity": expected.severity,
                            "predicted_severity": agent_finding.severity,
                            "severity_match": severity_match,
                            "must_detect": expected.must_detect,
                        }
                    )
                    break  # One agent finding can match only one expected finding

        return matches

    def _is_match(self, agent_finding: AgentFinding, expected: ReviewFindingTruth) -> bool:
        """Check if an agent finding matches an expected finding.

        Args:
            agent_finding: A finding from the agent response.
            expected: A ground truth expected finding.

        Returns:
            True if the findings match according to the rules.
        """
        # Exact canonical_label match required
        if agent_finding.canonical_label != expected.canonical_label:
            return False

        # Exact file_path match required
        if agent_finding.file_path != expected.file_path:
            return False

        # Line range must overlap or be within tolerance
        return self._line_ranges_match(
            (agent_finding.start_line, agent_finding.end_line),
            expected.line_span,
        )

    def _line_ranges_match(
        self,
        predicted: tuple[int, int],
        expected: tuple[int, int],
    ) -> bool:
        """Check if predicted line range matches expected line span.

        Matching occurs if:
        1. The ranges overlap, OR
        2. The predicted range falls within ±5 lines tolerance of the expected range

        Args:
            predicted: (start_line, end_line) from agent finding.
            expected: (start, end) from ground truth.

        Returns:
            True if the line ranges match.
        """
        pred_start, pred_end = predicted
        exp_start, exp_end = expected

        # Check for overlap
        # Ranges overlap if: pred_start <= exp_end AND pred_end >= exp_start
        if pred_start <= exp_end and pred_end >= exp_start:
            return True

        # Check tolerance: predicted range within ±5 lines of expected
        # This means the predicted start is within tolerance of expected start/end
        # OR the predicted end is within tolerance of expected start/end
        tolerance = self.line_tolerance

        # Check if any point in predicted range is close to expected range
        pred_close_to_exp = (
            abs(pred_start - exp_start) <= tolerance
            or abs(pred_start - exp_end) <= tolerance
            or abs(pred_end - exp_start) <= tolerance
            or abs(pred_end - exp_end) <= tolerance
        )

        # Check if predicted range is "near" expected range
        # (predicted is entirely before expected but close)
        before_but_close = pred_end < exp_start and abs(pred_end - exp_start) <= tolerance

        # (predicted is entirely after expected but close)
        after_but_close = pred_start > exp_end and abs(pred_start - exp_end) <= tolerance

        return pred_close_to_exp or before_but_close or after_but_close

    def _assess_severity_match(
        self,
        predicted: Literal["high", "medium", "low"],
        expected: Literal["high", "medium", "low"],
    ) -> str:
        """Assess how well the predicted severity matches the expected.

        Args:
            predicted: Severity predicted by the agent.
            expected: Expected severity from ground truth.

        Returns:
            "exact" if severities match exactly.
            "one_level" if severities differ by one level (e.g., high→medium).
            "mismatch" if severities differ by more than one level.
        """
        if predicted == expected:
            return "exact"

        pred_level = self._severity_levels[predicted]
        exp_level = self._severity_levels[expected]
        diff = abs(pred_level - exp_level)

        if diff == 1:
            return "one_level"
        return "mismatch"

    def _find_false_positives(
        self,
        agent_findings: list[AgentFinding],
        expected_findings: list[ReviewFindingTruth],
        matches: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Find agent findings that don't match any expected finding.

        Args:
            agent_findings: All findings from agent response.
            expected_findings: Ground truth expected findings.
            matches: Already identified matches.

        Returns:
            List of false positive findings.
        """
        # Get labels of matched findings
        matched_labels = {m["canonical_label"] for m in matches}

        false_positives = []
        for finding in agent_findings:
            if finding.canonical_label not in matched_labels:
                false_positives.append(
                    {
                        "canonical_label": finding.canonical_label,
                        "severity": finding.severity,
                        "file_path": finding.file_path,
                        "start_line": finding.start_line,
                        "end_line": finding.end_line,
                        "reason": "no_matching_expected_finding",
                    }
                )

        return false_positives

    def _find_disallowed(
        self,
        agent_findings: list[AgentFinding],
        disallowed_findings: list[DisallowedFinding],
    ) -> list[dict]:
        """Find agent findings that are in the disallowed list.

        Args:
            agent_findings: All findings from agent response.
            disallowed_findings: List of disallowed finding types.

        Returns:
            List of disallowed findings found in agent response.
        """
        if not disallowed_findings:
            return []

        disallowed_labels = {d.canonical_label for d in disallowed_findings}

        disallowed = []
        for finding in agent_findings:
            if finding.canonical_label in disallowed_labels:
                disallowed.append(
                    {
                        "canonical_label": finding.canonical_label,
                        "severity": finding.severity,
                        "file_path": finding.file_path,
                        "penalty": 0.5,
                    }
                )

        return disallowed

    def _find_missed_findings(
        self,
        expected_findings: list[ReviewFindingTruth],
        matches: list[dict],
    ) -> list[str]:
        """Find expected findings that were not matched.

        Args:
            expected_findings: All ground truth expected findings.
            matches: Already identified matches.

        Returns:
            List of finding IDs that were missed.
        """
        matched_ids = {m["expected_finding_id"] for m in matches}

        missed = []
        for expected in expected_findings:
            if expected.finding_id not in matched_ids:
                missed.append(expected.finding_id)

        return missed

    def _calculate_raw_score(
        self,
        matches: list[dict[str, Any]],
        false_positives: list[dict[str, Any]],
        disallowed: list[dict[str, Any]],
        expected_findings: list[ReviewFindingTruth],
    ) -> float:
        """Calculate the raw score using the scoring formula.

        Formula:
        - Each must_detect=true finding: 1.0 base points
        - Each optional finding: 0.5 base points
        - Exact severity match: +0.25 bonus
        - Each unmatched false positive: -0.25 penalty
        - Each disallowed finding: -0.50 penalty
        - Floor raw total at 0.0
        - Normalize by max achievable positive points
        - Clamp final raw_score to [0.0, 1.0]

        Args:
            matches: List of matched findings.
            false_positives: List of false positive findings.
            disallowed: List of disallowed findings.
            expected_findings: All expected findings for max points calc.

        Returns:
            Normalized raw score clamped to [0.0, 1.0].
        """
        # Calculate max achievable points
        max_points = sum(1.0 if f.must_detect else 0.5 for f in expected_findings)

        if max_points == 0:
            # Edge case: no expected findings
            # Score is based solely on penalties
            penalties = len(false_positives) * 0.25 + len(disallowed) * 0.5
            raw = max(0.0, 1.0 - penalties)  # Start at 1.0, subtract penalties
            return max(0.0, min(1.0, raw))

        # Calculate earned points
        earned = 0.0

        for match in matches:
            # Base points based on must_detect
            if match["must_detect"]:
                earned += 1.0
            else:
                earned += 0.5

            # Severity bonus
            if match["severity_match"] == "exact":
                earned += 0.25
            # One-level mismatch gets no bonus but keeps base points
            # Larger mismatch also gets no bonus

        # Subtract penalties
        penalties = len(false_positives) * 0.25 + len(disallowed) * 0.5
        earned = max(0.0, earned - penalties)

        # Normalize by max achievable points
        normalized = earned / max_points

        # Clamp to [0.0, 1.0]
        return max(0.0, min(1.0, normalized))

    def _build_scoring_breakdown(
        self,
        matches: list[dict[str, Any]],
        false_positives: list[dict[str, Any]],
        disallowed: list[dict[str, Any]],
        expected_findings: list[ReviewFindingTruth],
    ) -> dict[str, Any]:
        """Build a detailed breakdown of the scoring calculation.

        Args:
            matches: List of matched findings.
            false_positives: List of false positive findings.
            disallowed: List of disallowed findings.
            expected_findings: All expected findings.

        Returns:
            Dictionary with detailed scoring breakdown.
        """
        # Calculate points per match
        match_breakdown = []
        total_base = 0.0
        total_bonus = 0.0

        for match in matches:
            base = 1.0 if match["must_detect"] else 0.5
            bonus = 0.25 if match["severity_match"] == "exact" else 0.0
            total_base += base
            total_bonus += bonus
            match_breakdown.append(
                {
                    "finding_id": match["expected_finding_id"],
                    "canonical_label": match["canonical_label"],
                    "base_points": base,
                    "severity_bonus": bonus,
                    "severity_match": match["severity_match"],
                }
            )

        # Calculate penalties
        fp_penalty = len(false_positives) * 0.25
        disallowed_penalty = len(disallowed) * 0.5

        # Calculate max achievable
        max_points = sum(1.0 if f.must_detect else 0.5 for f in expected_findings)

        earned_before_penalty = total_base + total_bonus
        earned_after_penalty = max(0.0, earned_before_penalty - fp_penalty - disallowed_penalty)

        return {
            "max_achievable_points": max_points,
            "matches_count": len(matches),
            "total_base_points": total_base,
            "total_severity_bonus": total_bonus,
            "earned_before_penalties": earned_before_penalty,
            "false_positive_count": len(false_positives),
            "false_positive_penalty": fp_penalty,
            "disallowed_count": len(disallowed),
            "disallowed_penalty": disallowed_penalty,
            "earned_after_penalties": earned_after_penalty,
            "match_details": match_breakdown,
        }
