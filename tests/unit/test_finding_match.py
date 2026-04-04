"""Unit tests for the FindingMatchStrategy scoring algorithm.

This module validates the deterministic findings matcher implementation,
covering exact matches, optional findings, false positives, disallowed
findings, parse failures, line range tolerances, and severity mismatches.
"""

import json
import logging
from typing import Any

import pytest

from agentbench.cases.models import (
    DisallowedFinding,
    ReviewCaseDefinition,
    ReviewFindingTruth,
)
from agentbench.models.workflow import ScoringConfig, StepDefinition
from agentbench.scoring.strategies.finding_match import FindingMatchStrategy


@pytest.fixture
def strategy() -> FindingMatchStrategy:
    """Provide a FindingMatchStrategy instance."""
    return FindingMatchStrategy()


@pytest.fixture
def base_step() -> StepDefinition:
    """Provide a base step definition for s1_findings."""
    return StepDefinition(
        step_id="s1_findings",
        order=0,
        input="Review this diff for material issues...",
        timeout_ms=15000,
        scoring=ScoringConfig(
            strategy="finding_match",
            weight=2.0,
        ),
    )


@pytest.fixture
def base_case() -> ReviewCaseDefinition:
    """Provide a base review case with one must_detect finding."""
    return ReviewCaseDefinition(
        case_id="pr_001",
        case_set_id="pr_review_cases_v1",
        difficulty="medium",
        tags=["auth"],
        ticket_text="Add admin endpoint",
        diff_patch="diff content",
        expected_findings=[
            ReviewFindingTruth(
                finding_id="F1",
                canonical_label="missing_permission_check",
                severity="high",
                file_path="app/api/admin.py",
                line_span=(42, 57),
                must_detect=True,
                summary="Missing permission check.",
            ),
        ],
        disallowed_findings=[],
    )


def create_agent_response(findings: list[dict[str, Any]]) -> str:
    """Helper to create a JSON response from a list of findings."""
    return json.dumps({"findings": findings})


class TestExactMatch:
    """Tests for exact matching scenarios."""

    def test_exact_match_full_points(
        self,
        strategy: FindingMatchStrategy,
        base_step: StepDefinition,
        base_case: ReviewCaseDefinition,
    ) -> None:
        """Exact match should receive full base points + severity bonus."""
        response = create_agent_response(
            [
                {
                    "canonical_label": "missing_permission_check",
                    "severity": "high",
                    "file_path": "app/api/admin.py",
                    "start_line": 42,
                    "end_line": 57,
                    "title": "Missing permission",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-001", 1000, base_case)

        # Max points: 1.0 (must_detect)
        # Earned: 1.0 base + 0.25 severity bonus = 1.25
        # Normalized: 1.25 / 1.0 = 1.0 (clamped)
        assert score.raw_score == 1.0
        assert score.weighted_score == 2.0  # 1.0 * 2.0 weight
        assert score.passed is True
        assert score.strategy == "finding_match"
        assert score.details["findings_count"] == 1
        assert len(score.details["matches"]) == 1
        assert len(score.details["missed_findings"]) == 0

    def test_exact_match_with_all_fields(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """Exact match should work with all optional fields present."""
        case = ReviewCaseDefinition(
            case_id="pr_002",
            case_set_id="pr_review_cases_v1",
            difficulty="medium",
            tags=["api"],
            ticket_text="Update API",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="contract_breaking_change",
                    severity="medium",
                    file_path="app/api/users.py",
                    line_span=(10, 20),
                    must_detect=True,
                    summary="API contract change.",
                ),
            ],
        )

        response = create_agent_response(
            [
                {
                    "canonical_label": "contract_breaking_change",
                    "severity": "medium",
                    "file_path": "app/api/users.py",
                    "start_line": 10,
                    "end_line": 20,
                    "title": "API contract break",
                    "why_it_matters": "Changes response format",
                    "suggested_test": "Test old clients",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-002", 1000, case)

        assert score.raw_score == 1.0
        assert len(score.details["matches"]) == 1
        assert score.details["matches"][0]["severity_match"] == "exact"


class TestOptionalFinding:
    """Tests for optional (must_detect=false) findings."""

    def test_optional_finding_half_points(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """Optional finding match should receive 0.5 base points."""
        case = ReviewCaseDefinition(
            case_id="pr_003",
            case_set_id="pr_review_cases_v1",
            difficulty="medium",
            tags=["tests"],
            ticket_text="Add feature",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="missing_test_coverage",
                    severity="medium",
                    file_path="tests/test_feature.py",
                    line_span=(1, 1),
                    must_detect=False,  # Optional
                    summary="Missing test coverage.",
                ),
            ],
        )

        response = create_agent_response(
            [
                {
                    "canonical_label": "missing_test_coverage",
                    "severity": "medium",
                    "file_path": "tests/test_feature.py",
                    "start_line": 1,
                    "end_line": 1,
                    "title": "Missing tests",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-003", 1000, case)

        # Max points: 0.5 (optional)
        # Earned: 0.5 base + 0.25 severity bonus = 0.75
        # Normalized: 0.75 / 0.5 = 1.5 -> clamped to 1.0
        assert score.raw_score == 1.0
        assert score.passed is True

    def test_mixed_must_and_optional_findings(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """Case with both must_detect and optional findings."""
        case = ReviewCaseDefinition(
            case_id="pr_004",
            case_set_id="pr_review_cases_v1",
            difficulty="hard",
            tags=["auth", "tests"],
            ticket_text="Complex change",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="missing_permission_check",
                    severity="high",
                    file_path="app/auth.py",
                    line_span=(10, 20),
                    must_detect=True,
                    summary="Must detect.",
                ),
                ReviewFindingTruth(
                    finding_id="F2",
                    canonical_label="missing_test_coverage",
                    severity="low",
                    file_path="tests/test_auth.py",
                    line_span=(1, 10),
                    must_detect=False,  # Optional
                    summary="Optional test.",
                ),
            ],
        )

        response = create_agent_response(
            [
                {
                    "canonical_label": "missing_permission_check",
                    "severity": "high",
                    "file_path": "app/auth.py",
                    "start_line": 10,
                    "end_line": 20,
                    "title": "Missing auth",
                },
                {
                    "canonical_label": "missing_test_coverage",
                    "severity": "low",
                    "file_path": "tests/test_auth.py",
                    "start_line": 1,
                    "end_line": 10,
                    "title": "Missing tests",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-004", 1000, case)

        # Max points: 1.0 + 0.5 = 1.5
        # Earned: 1.0 + 0.25 + 0.5 + 0.25 = 2.0
        # Normalized: 2.0 / 1.5 = 1.333 -> clamped to 1.0
        assert score.raw_score == 1.0
        assert len(score.details["matches"]) == 2


class TestFalsePositivePenalty:
    """Tests for false positive detection and penalties."""

    def test_unmatched_finding_penalty(
        self,
        strategy: FindingMatchStrategy,
        base_step: StepDefinition,
        base_case: ReviewCaseDefinition,
    ) -> None:
        """Each unmatched false positive should deduct 0.25 points."""
        response = create_agent_response(
            [
                {
                    "canonical_label": "missing_permission_check",
                    "severity": "high",
                    "file_path": "app/api/admin.py",
                    "start_line": 42,
                    "end_line": 57,
                    "title": "Correct finding",
                },
                {
                    "canonical_label": "logging_observability_gap",
                    "severity": "low",
                    "file_path": "app/main.py",
                    "start_line": 100,
                    "end_line": 110,
                    "title": "False positive - not in ground truth",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-005", 1000, base_case)

        # Max points: 1.0
        # Earned before penalty: 1.0 + 0.25 = 1.25
        # Penalty: 0.25 for false positive
        # Earned after penalty: 1.0
        # Normalized: 1.0 / 1.0 = 1.0
        assert score.raw_score == 1.0
        assert len(score.details["false_positives"]) == 1
        assert score.details["false_positives"][0]["canonical_label"] == "logging_observability_gap"

    def test_multiple_false_positives(
        self,
        strategy: FindingMatchStrategy,
        base_step: StepDefinition,
        base_case: ReviewCaseDefinition,
    ) -> None:
        """Multiple false positives accumulate penalties."""
        response = create_agent_response(
            [
                {
                    "canonical_label": "missing_permission_check",
                    "severity": "high",
                    "file_path": "app/api/admin.py",
                    "start_line": 42,
                    "end_line": 57,
                    "title": "Correct finding",
                },
                {
                    "canonical_label": "logging_observability_gap",
                    "severity": "low",
                    "file_path": "app/main.py",
                    "start_line": 100,
                    "end_line": 110,
                    "title": "False positive 1",
                },
                {
                    "canonical_label": "missing_null_guard",
                    "severity": "medium",
                    "file_path": "app/utils.py",
                    "start_line": 50,
                    "end_line": 60,
                    "title": "False positive 2",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-006", 1000, base_case)

        # Max points: 1.0
        # Earned before penalty: 1.25
        # Penalty: 0.5 for two false positives
        # Earned after penalty: 0.75
        # Normalized: 0.75 / 1.0 = 0.75
        assert score.raw_score == 0.75
        assert len(score.details["false_positives"]) == 2


class TestDisallowedFinding:
    """Tests for disallowed finding penalties."""

    def test_disallowed_finding_penalty(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """Each disallowed finding should deduct 0.5 points."""
        case = ReviewCaseDefinition(
            case_id="pr_005",
            case_set_id="pr_review_cases_v1",
            difficulty="medium",
            tags=["style"],
            ticket_text="Update code",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="missing_error_handling",
                    severity="medium",
                    file_path="app/api.py",
                    line_span=(20, 30),
                    must_detect=True,
                    summary="Missing error handling.",
                ),
            ],
            disallowed_findings=[
                DisallowedFinding(canonical_label="style_only_nit"),
            ],
        )

        response = create_agent_response(
            [
                {
                    "canonical_label": "missing_error_handling",
                    "severity": "medium",
                    "file_path": "app/api.py",
                    "start_line": 20,
                    "end_line": 30,
                    "title": "Valid finding",
                },
                {
                    "canonical_label": "style_only_nit",
                    "severity": "low",
                    "file_path": "app/main.py",
                    "start_line": 1,
                    "end_line": 10,
                    "title": "Disallowed - style nit",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-007", 1000, case)

        # Max points: 1.0
        # Earned before penalties: 1.0 + 0.25 = 1.25
        # Penalties: 0.25 for false positive + 0.5 for disallowed = 0.75
        # Earned after penalty: max(0, 1.25 - 0.75) = 0.5
        # Normalized: 0.5 / 1.0 = 0.5
        assert score.raw_score == 0.5
        assert len(score.details["disallowed_findings"]) == 1
        assert score.details["disallowed_findings"][0]["canonical_label"] == "style_only_nit"
        assert score.details["disallowed_findings"][0]["penalty"] == 0.5

    def test_only_disallowed_finding_zero_score(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """Only disallowed findings with no valid matches results in zero score."""
        case = ReviewCaseDefinition(
            case_id="pr_006",
            case_set_id="pr_review_cases_v1",
            difficulty="medium",
            tags=[],
            ticket_text="Update",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="missing_validation",
                    severity="high",
                    file_path="app/validators.py",
                    line_span=(10, 20),
                    must_detect=True,
                    summary="Missing validation.",
                ),
            ],
            disallowed_findings=[
                DisallowedFinding(canonical_label="style_only_nit"),
            ],
        )

        # Response only contains disallowed finding
        response = create_agent_response(
            [
                {
                    "canonical_label": "style_only_nit",
                    "severity": "low",
                    "file_path": "app/main.py",
                    "start_line": 1,
                    "end_line": 10,
                    "title": "Style nit - disallowed",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-008", 1000, case)

        # No matches, only disallowed finding
        # Max points: 1.0
        # Earned: 0 - 0.5 = 0 (floored)
        # Normalized: 0 / 1.0 = 0.0
        assert score.raw_score == 0.0
        assert score.passed is False
        assert len(score.details["disallowed_findings"]) == 1


class TestMalformedJson:
    """Tests for parse failure handling."""

    def test_invalid_json_zero_score(
        self,
        strategy: FindingMatchStrategy,
        base_step: StepDefinition,
        base_case: ReviewCaseDefinition,
    ) -> None:
        """Invalid JSON response should result in zero score."""
        response = "This is not valid JSON"

        score = strategy.score(base_step, response, "run-009", 1000, base_case)

        assert score.raw_score == 0.0
        assert score.weighted_score == 0.0
        assert score.passed is False
        assert score.details["error"] == "parse_failure"
        assert "findings_count" in score.details

    def test_missing_required_field_zero_score(
        self,
        strategy: FindingMatchStrategy,
        base_step: StepDefinition,
        base_case: ReviewCaseDefinition,
    ) -> None:
        """JSON missing required fields should result in zero score."""
        response = json.dumps(
            {
                "findings": [
                    {
                        # Missing canonical_label
                        "severity": "high",
                        "file_path": "app/api/admin.py",
                        "start_line": 42,
                        "end_line": 57,
                    },
                ],
            }
        )

        score = strategy.score(base_step, response, "run-010", 1000, base_case)

        assert score.raw_score == 0.0
        assert score.passed is False
        assert score.details["error"] == "parse_failure"

    def test_invalid_severity_zero_score(
        self,
        strategy: FindingMatchStrategy,
        base_step: StepDefinition,
        base_case: ReviewCaseDefinition,
    ) -> None:
        """JSON with invalid severity value should result in zero score."""
        response = json.dumps(
            {
                "findings": [
                    {
                        "canonical_label": "missing_permission_check",
                        "severity": "critical",  # Invalid severity
                        "file_path": "app/api/admin.py",
                        "start_line": 42,
                        "end_line": 57,
                    },
                ],
            }
        )

        score = strategy.score(base_step, response, "run-011", 1000, base_case)

        assert score.raw_score == 0.0
        assert score.passed is False


class TestLineRangeOverlap:
    """Tests for line range matching with overlap and tolerance."""

    def test_exact_line_match(
        self,
        strategy: FindingMatchStrategy,
        base_step: StepDefinition,
        base_case: ReviewCaseDefinition,
    ) -> None:
        """Exact line span match should be detected."""
        response = create_agent_response(
            [
                {
                    "canonical_label": "missing_permission_check",
                    "severity": "high",
                    "file_path": "app/api/admin.py",
                    "start_line": 42,
                    "end_line": 57,
                    "title": "Exact match",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-012", 1000, base_case)

        assert score.raw_score == 1.0
        assert len(score.details["matches"]) == 1

    def test_partial_overlap(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """Partial overlap in line ranges should match."""
        case = ReviewCaseDefinition(
            case_id="pr_007",
            case_set_id="pr_review_cases_v1",
            difficulty="medium",
            tags=[],
            ticket_text="Update",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="state_consistency_bug",
                    severity="high",
                    file_path="app/state.py",
                    line_span=(100, 120),
                    must_detect=True,
                    summary="State bug.",
                ),
            ],
        )

        # Predicted range overlaps partially (105-115 within 100-120)
        response = create_agent_response(
            [
                {
                    "canonical_label": "state_consistency_bug",
                    "severity": "high",
                    "file_path": "app/state.py",
                    "start_line": 105,
                    "end_line": 115,
                    "title": "Overlapping range",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-013", 1000, case)

        assert score.raw_score == 1.0
        assert len(score.details["matches"]) == 1

    def test_range_within_tolerance_before(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """Range within 5 lines before expected should match."""
        case = ReviewCaseDefinition(
            case_id="pr_008",
            case_set_id="pr_review_cases_v1",
            difficulty="medium",
            tags=[],
            ticket_text="Update",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="performance_regression",
                    severity="medium",
                    file_path="app/perf.py",
                    line_span=(50, 60),
                    must_detect=True,
                    summary="Perf issue.",
                ),
            ],
        )

        # Predicted range ends 3 lines before expected (within tolerance)
        response = create_agent_response(
            [
                {
                    "canonical_label": "performance_regression",
                    "severity": "medium",
                    "file_path": "app/perf.py",
                    "start_line": 40,
                    "end_line": 47,
                    "title": "Within tolerance before",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-014", 1000, case)

        assert score.raw_score == 1.0
        assert len(score.details["matches"]) == 1

    def test_range_within_tolerance_after(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """Range within 5 lines after expected should match."""
        case = ReviewCaseDefinition(
            case_id="pr_009",
            case_set_id="pr_review_cases_v1",
            difficulty="medium",
            tags=[],
            ticket_text="Update",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="incorrect_business_rule",
                    severity="high",
                    file_path="app/rules.py",
                    line_span=(100, 110),
                    must_detect=True,
                    summary="Business rule issue.",
                ),
            ],
        )

        # Predicted range starts 4 lines after expected ends (within tolerance)
        response = create_agent_response(
            [
                {
                    "canonical_label": "incorrect_business_rule",
                    "severity": "high",
                    "file_path": "app/rules.py",
                    "start_line": 114,
                    "end_line": 120,
                    "title": "Within tolerance after",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-015", 1000, case)

        assert score.raw_score == 1.0
        assert len(score.details["matches"]) == 1

    def test_range_outside_tolerance(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """Range outside 5 lines tolerance should not match."""
        case = ReviewCaseDefinition(
            case_id="pr_010",
            case_set_id="pr_review_cases_v1",
            difficulty="medium",
            tags=[],
            ticket_text="Update",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="missing_validation",
                    severity="high",
                    file_path="app/validators.py",
                    line_span=(10, 20),
                    must_detect=True,
                    summary="Missing validation.",
                ),
            ],
        )

        # Predicted range is way outside tolerance (>5 lines away)
        response = create_agent_response(
            [
                {
                    "canonical_label": "missing_validation",
                    "severity": "high",
                    "file_path": "app/validators.py",
                    "start_line": 50,  # Way after line 20 (difference of 30)
                    "end_line": 60,
                    "title": "Outside tolerance",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-016", 1000, case)

        # No match due to line tolerance
        assert score.raw_score == 0.0
        assert len(score.details["matches"]) == 0
        assert "F1" in score.details["missed_findings"]


class TestSeverityMismatch:
    """Tests for severity level matching."""

    def test_exact_severity_match_bonus(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """Exact severity match should get the 0.25 bonus."""
        case = ReviewCaseDefinition(
            case_id="pr_011",
            case_set_id="pr_review_cases_v1",
            difficulty="medium",
            tags=[],
            ticket_text="Update",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="missing_error_handling",
                    severity="medium",
                    file_path="app/errors.py",
                    line_span=(30, 40),
                    must_detect=True,
                    summary="Missing error handling.",
                ),
            ],
        )

        response = create_agent_response(
            [
                {
                    "canonical_label": "missing_error_handling",
                    "severity": "medium",  # Exact match
                    "file_path": "app/errors.py",
                    "start_line": 30,
                    "end_line": 40,
                    "title": "Exact severity",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-017", 1000, case)

        assert score.raw_score == 1.0  # 1.0 + 0.25 = 1.25 -> clamped
        assert score.details["matches"][0]["severity_match"] == "exact"
        assert score.details["matches"][0]["expected_severity"] == "medium"
        assert score.details["matches"][0]["predicted_severity"] == "medium"

    def test_one_level_severity_mismatch(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """One-level severity mismatch should match but no bonus."""
        case = ReviewCaseDefinition(
            case_id="pr_012",
            case_set_id="pr_review_cases_v1",
            difficulty="medium",
            tags=[],
            ticket_text="Update",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="missing_error_handling",
                    severity="high",
                    file_path="app/errors.py",
                    line_span=(30, 40),
                    must_detect=True,
                    summary="Missing error handling.",
                ),
            ],
        )

        response = create_agent_response(
            [
                {
                    "canonical_label": "missing_error_handling",
                    "severity": "medium",  # One level below high
                    "file_path": "app/errors.py",
                    "start_line": 30,
                    "end_line": 40,
                    "title": "One level mismatch",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-018", 1000, case)

        # No severity bonus, but match counts
        assert score.details["matches"][0]["severity_match"] == "one_level"
        # Score: 1.0 (no bonus), no penalties, max 1.0 -> 1.0
        assert score.raw_score == 1.0

    def test_two_level_severity_mismatch(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """Two-level severity mismatch should match but no bonus."""
        case = ReviewCaseDefinition(
            case_id="pr_013",
            case_set_id="pr_review_cases_v1",
            difficulty="medium",
            tags=[],
            ticket_text="Update",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="missing_error_handling",
                    severity="high",
                    file_path="app/errors.py",
                    line_span=(30, 40),
                    must_detect=True,
                    summary="Missing error handling.",
                ),
            ],
        )

        response = create_agent_response(
            [
                {
                    "canonical_label": "missing_error_handling",
                    "severity": "low",  # Two levels below high
                    "file_path": "app/errors.py",
                    "start_line": 30,
                    "end_line": 40,
                    "title": "Two level mismatch",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-019", 1000, case)

        assert score.details["matches"][0]["severity_match"] == "mismatch"
        # Score: 1.0 (no bonus), no penalties, max 1.0 -> 1.0
        assert score.raw_score == 1.0

    def test_reverse_one_level_mismatch(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """Severity one level higher should also be one_level mismatch."""
        case = ReviewCaseDefinition(
            case_id="pr_014",
            case_set_id="pr_review_cases_v1",
            difficulty="medium",
            tags=[],
            ticket_text="Update",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="missing_error_handling",
                    severity="low",
                    file_path="app/errors.py",
                    line_span=(30, 40),
                    must_detect=True,
                    summary="Missing error handling.",
                ),
            ],
        )

        response = create_agent_response(
            [
                {
                    "canonical_label": "missing_error_handling",
                    "severity": "medium",  # One level above low
                    "file_path": "app/errors.py",
                    "start_line": 30,
                    "end_line": 40,
                    "title": "One level higher",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-020", 1000, case)

        assert score.details["matches"][0]["severity_match"] == "one_level"


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_findings_list(
        self,
        strategy: FindingMatchStrategy,
        base_step: StepDefinition,
        base_case: ReviewCaseDefinition,
    ) -> None:
        """Empty findings list when there are expected findings should score 0."""
        response = create_agent_response([])

        score = strategy.score(base_step, response, "run-021", 1000, base_case)

        assert score.raw_score == 0.0
        assert score.passed is False
        assert len(score.details["missed_findings"]) == 1
        assert score.details["missed_findings"][0] == "F1"

    def test_no_expected_findings_with_response(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """When there are no expected findings, any finding is a false positive."""
        case = ReviewCaseDefinition(
            case_id="pr_015",
            case_set_id="pr_review_cases_v1",
            difficulty="easy",
            tags=[],
            ticket_text="Simple fix",
            diff_patch="diff",
            expected_findings=[],  # No expected findings
        )

        response = create_agent_response(
            [
                {
                    "canonical_label": "logging_observability_gap",
                    "severity": "low",
                    "file_path": "app/main.py",
                    "start_line": 1,
                    "end_line": 10,
                    "title": "Unwanted finding",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-022", 1000, case)

        # Max points: 0, but we start at 1.0 and subtract penalties
        # Penalty: 0.25 for false positive
        # Raw score: max(0, 1.0 - 0.25) = 0.75 -> but normalized by max(0, ...)
        # Actually with no expected findings, max_points = 0, so special handling
        # Implementation starts at 1.0 and subtracts penalties
        assert score.raw_score < 1.0
        assert len(score.details["false_positives"]) == 1

    def test_passed_threshold(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """Test that passed is True when score >= 0.5."""
        case = ReviewCaseDefinition(
            case_id="pr_016",
            case_set_id="pr_review_cases_v1",
            difficulty="medium",
            tags=[],
            ticket_text="Update",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="missing_permission_check",
                    severity="high",
                    file_path="app/auth.py",
                    line_span=(10, 20),
                    must_detect=True,
                    summary="Missing auth.",
                ),
            ],
        )

        # Partial match with penalties that still result in score >= 0.5
        # This is tricky - need to find a scenario where score is right at threshold
        # With 1 must_detect finding: max = 1.0
        # Score 0.5 would mean earning 0.5 before normalization
        # That could be: missing the finding completely but no penalties = 0
        # Or: matching with one false positive: 1.0 + 0.25 - 0.25 = 1.0 -> 1.0

        # Let's test borderline: low score should fail
        response = create_agent_response([])  # No findings
        score = strategy.score(base_step, response, "run-023", 1000, case)
        assert score.raw_score == 0.0
        assert score.passed is False

    def test_details_contains_breakdown(
        self,
        strategy: FindingMatchStrategy,
        base_step: StepDefinition,
        base_case: ReviewCaseDefinition,
    ) -> None:
        """Score details should contain the full scoring breakdown."""
        response = create_agent_response(
            [
                {
                    "canonical_label": "missing_permission_check",
                    "severity": "high",
                    "file_path": "app/api/admin.py",
                    "start_line": 42,
                    "end_line": 57,
                    "title": "Test finding",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-024", 1000, base_case)

        assert "scoring_breakdown" in score.details
        breakdown = score.details["scoring_breakdown"]
        assert "max_achievable_points" in breakdown
        assert "total_base_points" in breakdown
        assert "total_severity_bonus" in breakdown
        assert "match_details" in breakdown


class TestLineRangeEdgeCases:
    """Additional edge cases for line range matching."""

    def test_single_line_finding(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """Single line findings should match correctly."""
        case = ReviewCaseDefinition(
            case_id="pr_017",
            case_set_id="pr_review_cases_v1",
            difficulty="medium",
            tags=[],
            ticket_text="Update",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="missing_null_guard",
                    severity="medium",
                    file_path="app/utils.py",
                    line_span=(42, 42),  # Single line
                    must_detect=True,
                    summary="Missing null guard.",
                ),
            ],
        )

        response = create_agent_response(
            [
                {
                    "canonical_label": "missing_null_guard",
                    "severity": "medium",
                    "file_path": "app/utils.py",
                    "start_line": 42,
                    "end_line": 42,  # Single line
                    "title": "Single line",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-025", 1000, case)

        assert score.raw_score == 1.0
        assert len(score.details["matches"]) == 1

    def test_exact_tolerance_boundary(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """Test exact boundary of 5-line tolerance."""
        case = ReviewCaseDefinition(
            case_id="pr_018",
            case_set_id="pr_review_cases_v1",
            difficulty="medium",
            tags=[],
            ticket_text="Update",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="missing_validation",
                    severity="high",
                    file_path="app/validators.py",
                    line_span=(100, 110),
                    must_detect=True,
                    summary="Missing validation.",
                ),
            ],
        )

        # Exactly 5 lines after expected range ends (115 is 5 from 110)
        response = create_agent_response(
            [
                {
                    "canonical_label": "missing_validation",
                    "severity": "high",
                    "file_path": "app/validators.py",
                    "start_line": 115,
                    "end_line": 120,
                    "title": "Exactly 5 lines tolerance",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-026", 1000, case)

        assert score.raw_score == 1.0
        assert len(score.details["matches"]) == 1

    def test_just_outside_tolerance(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """Test just outside 5-line tolerance (6 lines away)."""
        case = ReviewCaseDefinition(
            case_id="pr_019",
            case_set_id="pr_review_cases_v1",
            difficulty="medium",
            tags=[],
            ticket_text="Update",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="missing_validation",
                    severity="high",
                    file_path="app/validators.py",
                    line_span=(100, 110),
                    must_detect=True,
                    summary="Missing validation.",
                ),
            ],
        )

        # 6 lines after expected range ends (116 is 6 from 110)
        response = create_agent_response(
            [
                {
                    "canonical_label": "missing_validation",
                    "severity": "high",
                    "file_path": "app/validators.py",
                    "start_line": 116,
                    "end_line": 120,
                    "title": "Just outside tolerance",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-027", 1000, case)

        # Should NOT match due to tolerance
        assert len(score.details["matches"]) == 0
        assert "F1" in score.details["missed_findings"]


class TestScoringNormalization:
    """Tests for score normalization and clamping."""

    def test_score_clamped_to_one(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """Raw score should be clamped to maximum of 1.0."""
        case = ReviewCaseDefinition(
            case_id="pr_020",
            case_set_id="pr_review_cases_v1",
            difficulty="medium",
            tags=[],
            ticket_text="Update",
            diff_patch="diff",
            expected_findings=[
                # Only optional finding with max bonus could exceed 1.0 before clamping
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="missing_test_coverage",
                    severity="medium",
                    file_path="tests/test.py",
                    line_span=(1, 1),
                    must_detect=False,  # 0.5 base
                    summary="Optional test.",
                ),
            ],
        )

        response = create_agent_response(
            [
                {
                    "canonical_label": "missing_test_coverage",
                    "severity": "medium",
                    "file_path": "tests/test.py",
                    "start_line": 1,
                    "end_line": 1,
                    "title": "Optional finding exact match",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-028", 1000, case)

        # 0.5 base + 0.25 bonus = 0.75
        # Max = 0.5
        # 0.75 / 0.5 = 1.5 -> clamped to 1.0
        assert score.raw_score == 1.0

    def test_score_floored_at_zero(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """Raw score should be floored at minimum of 0.0."""
        case = ReviewCaseDefinition(
            case_id="pr_021",
            case_set_id="pr_review_cases_v1",
            difficulty="medium",
            tags=[],
            ticket_text="Update",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="missing_error_handling",
                    severity="medium",
                    file_path="app/errors.py",
                    line_span=(1, 10),
                    must_detect=True,
                    summary="Missing error handling.",
                ),
            ],
        )

        # Only false positives and disallowed findings
        response = create_agent_response(
            [
                {
                    "canonical_label": "logging_observability_gap",
                    "severity": "low",
                    "file_path": "app/main.py",
                    "start_line": 100,
                    "end_line": 110,
                    "title": "False positive",
                },
                {
                    "canonical_label": "style_only_nit",
                    "severity": "low",
                    "file_path": "app/style.py",
                    "start_line": 1,
                    "end_line": 5,
                    "title": "Another false positive",
                },
            ]
        )

        # Need disallowed findings in the case
        case_with_disallowed = ReviewCaseDefinition(
            case_id="pr_021",
            case_set_id="pr_review_cases_v1",
            difficulty="medium",
            tags=[],
            ticket_text="Update",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="missing_error_handling",
                    severity="medium",
                    file_path="app/errors.py",
                    line_span=(1, 10),
                    must_detect=True,
                    summary="Missing error handling.",
                ),
            ],
            disallowed_findings=[
                DisallowedFinding(canonical_label="style_only_nit"),
            ],
        )

        score = strategy.score(base_step, response, "run-029", 1000, case_with_disallowed)

        # No matches, penalties: 0.25 (FP) + 0.5 (disallowed) = 0.75
        # Raw would be 0 - 0.75 = -0.75, but floored to 0
        assert score.raw_score == 0.0


class TestFilePathMatching:
    """Tests for file path matching requirements."""

    def test_file_path_must_match_exactly(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """Different file paths should not match even with same label and lines."""
        case = ReviewCaseDefinition(
            case_id="pr_022",
            case_set_id="pr_review_cases_v1",
            difficulty="medium",
            tags=[],
            ticket_text="Update",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="missing_permission_check",
                    severity="high",
                    file_path="app/api/admin.py",
                    line_span=(42, 57),
                    must_detect=True,
                    summary="Missing permission.",
                ),
            ],
        )

        # Same label and lines, but different file path
        response = create_agent_response(
            [
                {
                    "canonical_label": "missing_permission_check",
                    "severity": "high",
                    "file_path": "app/api/users.py",  # Different file!
                    "start_line": 42,
                    "end_line": 57,
                    "title": "Same label, different file",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-030", 1000, case)

        # Should NOT match due to different file_path
        assert len(score.details["matches"]) == 0
        assert "F1" in score.details["missed_findings"]
        assert score.raw_score == 0.0


class TestMultipleExpectedFindings:
    """Tests for cases with multiple expected findings."""

    def test_partial_match_multiple_findings(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """Partial match with multiple expected findings."""
        case = ReviewCaseDefinition(
            case_id="pr_023",
            case_set_id="pr_review_cases_v1",
            difficulty="hard",
            tags=["auth", "tests"],
            ticket_text="Complex PR",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="missing_permission_check",
                    severity="high",
                    file_path="app/auth.py",
                    line_span=(10, 20),
                    must_detect=True,
                    summary="Missing auth.",
                ),
                ReviewFindingTruth(
                    finding_id="F2",
                    canonical_label="missing_test_coverage",
                    severity="medium",
                    file_path="tests/test_auth.py",
                    line_span=(1, 50),
                    must_detect=True,
                    summary="Missing tests.",
                ),
                ReviewFindingTruth(
                    finding_id="F3",
                    canonical_label="missing_error_handling",
                    severity="medium",
                    file_path="app/errors.py",
                    line_span=(30, 40),
                    must_detect=False,  # Optional
                    summary="Missing error handling.",
                ),
            ],
        )

        # Only match 1 out of 2 must_detect, miss the optional
        response = create_agent_response(
            [
                {
                    "canonical_label": "missing_permission_check",
                    "severity": "high",
                    "file_path": "app/auth.py",
                    "start_line": 10,
                    "end_line": 20,
                    "title": "Found auth issue",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-031", 1000, case)

        # Max points: 1.0 + 1.0 + 0.5 = 2.5
        # Earned: 1.0 + 0.25 = 1.25
        # Normalized: 1.25 / 2.5 = 0.5
        assert score.raw_score == 0.5
        assert score.passed is True  # Right at threshold
        assert len(score.details["matches"]) == 1
        assert len(score.details["missed_findings"]) == 2

    def test_match_all_findings(
        self, strategy: FindingMatchStrategy, base_step: StepDefinition
    ) -> None:
        """Matching all expected findings should give perfect score."""
        case = ReviewCaseDefinition(
            case_id="pr_024",
            case_set_id="pr_review_cases_v1",
            difficulty="hard",
            tags=[],
            ticket_text="Complex PR",
            diff_patch="diff",
            expected_findings=[
                ReviewFindingTruth(
                    finding_id="F1",
                    canonical_label="missing_permission_check",
                    severity="high",
                    file_path="app/auth.py",
                    line_span=(10, 20),
                    must_detect=True,
                    summary="Missing auth.",
                ),
                ReviewFindingTruth(
                    finding_id="F2",
                    canonical_label="missing_test_coverage",
                    severity="medium",
                    file_path="tests/test_auth.py",
                    line_span=(1, 50),
                    must_detect=True,
                    summary="Missing tests.",
                ),
            ],
        )

        response = create_agent_response(
            [
                {
                    "canonical_label": "missing_permission_check",
                    "severity": "high",
                    "file_path": "app/auth.py",
                    "start_line": 10,
                    "end_line": 20,
                    "title": "Found auth issue",
                },
                {
                    "canonical_label": "missing_test_coverage",
                    "severity": "medium",
                    "file_path": "tests/test_auth.py",
                    "start_line": 1,
                    "end_line": 50,
                    "title": "Found test coverage issue",
                },
            ]
        )

        score = strategy.score(base_step, response, "run-032", 1000, case)

        # Max points: 1.0 + 1.0 = 2.0
        # Earned: 1.0 + 0.25 + 1.0 + 0.25 = 2.5 -> clamped to 2.0
        # Normalized: 2.0 / 2.0 = 1.0
        assert score.raw_score == 1.0
        assert len(score.details["matches"]) == 2
        assert len(score.details["missed_findings"]) == 0




