"""Test harness for deterministic CLI report rendering.

Provides Rich console fixtures and reusable benchmark report data
for testing report output without terminal width or color dependencies.
"""

from __future__ import annotations

import importlib

import pytest
from rich.console import Console, ConsoleRenderable
from rich.text import Text

from agentbench.models.results import AgentSummary, BenchmarkReport
from cli.reporting import (
    compute_insights,
    compute_winners,
    group_cases_by_topic,
    order_agents,
    render_insights,
    render_per_topic_tables,
    render_step_breakdown,
    render_summary_table,
    sort_cases,
)

# ---------------------------------------------------------------------------
# Deterministic Rich console fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fixed_console() -> Console:
    """Rich Console with fixed 80-char width and no color system.

    Produces plain-text output suitable for exact string assertions.
    No ANSI escape codes will appear in the rendered output.
    """
    return Console(
        width=80,
        color_system=None,
        legacy_windows=False,
        force_terminal=False,
    )


@pytest.fixture()
def wide_console() -> Console:
    """Rich Console with 120-char width and no color system."""
    return Console(
        width=120,
        color_system=None,
        legacy_windows=False,
        force_terminal=False,
    )


@pytest.fixture()
def narrow_console() -> Console:
    """Rich Console with 40-char width and no color system."""
    return Console(
        width=40,
        color_system=None,
        legacy_windows=False,
        force_terminal=False,
    )


def render(console: Console, renderable: ConsoleRenderable) -> str:
    """Render a Rich object to plain text using the given console."""
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def load_reporting_demo_module():
    """Import demo reporting module lazily for regression tests."""
    try:
        return importlib.import_module("cli.reporting_demo")
    except Exception as exc:  # pragma: no cover - import failure is test failure
        pytest.fail(f"Unable to import cli.reporting_demo: {exc}")


# ---------------------------------------------------------------------------
# Console harness validation tests
# ---------------------------------------------------------------------------


class TestConsoleHarness:
    """Validate the deterministic console fixture itself."""

    def test_console_harness_produces_plain_text(self, fixed_console: Console) -> None:
        """Fixed console must produce text without ANSI codes."""
        rendered = render(fixed_console, Text("hello world", style="bold red"))
        assert rendered.strip() == "hello world"

    def test_console_harness_respects_width(self, fixed_console: Console) -> None:
        """Fixed console must wrap at configured width."""
        long_line = "A" * 100
        rendered = render(fixed_console, Text(long_line))
        # With width=80, the text should be wrapped (no line > 80 chars)
        lines = rendered.splitlines()
        for line in lines:
            assert len(line) <= 80, f"Line exceeded 80 chars: {line!r}"

    def test_wide_console_allows_longer_lines(self, wide_console: Console) -> None:
        """Wide console must allow up to 120 chars per line."""
        long_line = "A" * 100
        rendered = render(wide_console, Text(long_line))
        lines = rendered.splitlines()
        # 100 chars should fit within 120
        assert len(lines) == 1
        assert len(lines[0]) == 100

    def test_narrow_console_wraps_early(self, narrow_console: Console) -> None:
        """Narrow console must wrap at 40 chars."""
        long_line = "A" * 60
        rendered = render(narrow_console, Text(long_line))
        lines = rendered.splitlines()
        for line in lines:
            assert len(line) <= 40, f"Line exceeded 40 chars: {line!r}"


# ---------------------------------------------------------------------------
# Benchmark report fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def two_agent_report() -> BenchmarkReport:
    """Two-agent happy path with full per-case scores and topics."""
    return BenchmarkReport(
        benchmark_id="bench-001",
        workflow_id="wf_pr_review_v1",
        case_set_id="pr_review_cases_v1",
        created_at="2026-04-01T12:00:00Z",
        case_count=3,
        agents=[
            AgentSummary(
                agent_id="claude-haiku-4-5",
                avg_score=0.91,
                p50_latency_ms=2500,
                p95_latency_ms=5000,
                failure_rate=0.0,
                step_breakdown={"s1_findings": 0.88, "s2_review_summary": 0.94},
            ),
            AgentSummary(
                agent_id="gpt-4o-mini",
                avg_score=0.85,
                p50_latency_ms=1500,
                p95_latency_ms=7500,
                failure_rate=0.0,
                step_breakdown={"s1_findings": 0.82, "s2_review_summary": 0.88},
            ),
        ],
        per_case_scores={
            "pr_001_missing_auth_check": {
                "claude-haiku-4-5": 0.92,
                "gpt-4o-mini": 0.92,
            },
            "pr_002_missing_test_coverage": {
                "claude-haiku-4-5": 0.90,
                "gpt-4o-mini": 0.88,
            },
            "pr_003_missing_null_guard": {
                "claude-haiku-4-5": 0.91,
                "gpt-4o-mini": 0.75,
            },
        },
        per_case_topics={
            "pr_001_missing_auth_check": "Auth/Security",
            "pr_002_missing_test_coverage": "Testing",
            "pr_003_missing_null_guard": "Null Safety",
        },
    )


@pytest.fixture()
def single_agent_report() -> BenchmarkReport:
    """Single-agent path with one agent and per-case scores."""
    return BenchmarkReport(
        benchmark_id="bench-002",
        workflow_id="wf_pr_review_v1",
        case_set_id="pr_review_cases_v1",
        created_at="2026-04-02T09:00:00Z",
        case_count=2,
        agents=[
            AgentSummary(
                agent_id="claude-haiku-4-5",
                avg_score=0.88,
                p50_latency_ms=2000,
                p95_latency_ms=4500,
                failure_rate=0.0,
                step_breakdown={"s1_findings": 0.85, "s2_review_summary": 0.91},
            ),
        ],
        per_case_scores={
            "pr_001_missing_auth_check": {"claude-haiku-4-5": 0.90},
            "pr_002_missing_test_coverage": {"claude-haiku-4-5": 0.86},
        },
        per_case_topics={
            "pr_001_missing_auth_check": "Auth/Security",
            "pr_002_missing_test_coverage": "Testing",
        },
    )


@pytest.fixture()
def tie_winners_report() -> BenchmarkReport:
    """Report where agents have the same average score."""
    return BenchmarkReport(
        benchmark_id="bench-003",
        workflow_id="wf_pr_review_v1",
        case_set_id="pr_review_cases_v1",
        created_at="2026-04-03T15:00:00Z",
        case_count=2,
        agents=[
            AgentSummary(
                agent_id="claude-haiku-4-5",
                avg_score=0.85,
                p50_latency_ms=2500,
                p95_latency_ms=5000,
                failure_rate=0.0,
                step_breakdown={"s1_findings": 0.85, "s2_review_summary": 0.85},
            ),
            AgentSummary(
                agent_id="gpt-4o-mini",
                avg_score=0.85,
                p50_latency_ms=1500,
                p95_latency_ms=7500,
                failure_rate=0.0,
                step_breakdown={"s1_findings": 0.85, "s2_review_summary": 0.85},
            ),
        ],
        per_case_scores={
            "pr_001_missing_auth_check": {
                "claude-haiku-4-5": 0.85,
                "gpt-4o-mini": 0.85,
            },
            "pr_002_missing_test_coverage": {
                "claude-haiku-4-5": 0.85,
                "gpt-4o-mini": 0.85,
            },
        },
        per_case_topics={
            "pr_001_missing_auth_check": "Auth/Security",
            "pr_002_missing_test_coverage": "Testing",
        },
    )


@pytest.fixture()
def sparse_scores_report() -> BenchmarkReport:
    """Report with sparse per-case scores (not every agent scored every case)."""
    return BenchmarkReport(
        benchmark_id="bench-004",
        workflow_id="wf_pr_review_v1",
        case_set_id="pr_review_cases_v1",
        created_at="2026-04-04T10:00:00Z",
        case_count=3,
        agents=[
            AgentSummary(
                agent_id="claude-haiku-4-5",
                avg_score=0.80,
                p50_latency_ms=2000,
                p95_latency_ms=4000,
                failure_rate=0.1,
                step_breakdown={"s1_findings": 0.80, "s2_review_summary": 0.80},
            ),
            AgentSummary(
                agent_id="gpt-4o-mini",
                avg_score=0.75,
                p50_latency_ms=1800,
                p95_latency_ms=6000,
                failure_rate=0.0,
                step_breakdown={"s1_findings": 0.75, "s2_review_summary": 0.75},
            ),
        ],
        per_case_scores={
            "pr_001_missing_auth_check": {
                "claude-haiku-4-5": 0.90,
                "gpt-4o-mini": 0.88,
            },
            "pr_002_missing_test_coverage": {
                "claude-haiku-4-5": 0.70,
            },
            # pr_003 missing entirely - partial failures
        },
        per_case_topics={
            "pr_001_missing_auth_check": "Auth/Security",
            "pr_002_missing_test_coverage": "Testing",
            "pr_003_missing_null_guard": "Null Safety",
        },
    )


@pytest.fixture()
def legacy_report_no_topics() -> BenchmarkReport:
    """Legacy payload missing per_case_topics (backward compat)."""
    return BenchmarkReport(
        benchmark_id="bench-005",
        workflow_id="wf_pr_review_v1",
        case_set_id="pr_review_cases_v1",
        created_at="2026-03-15T08:00:00Z",
        case_count=2,
        agents=[
            AgentSummary(
                agent_id="claude-haiku-4-5",
                avg_score=0.82,
                p50_latency_ms=2200,
                p95_latency_ms=4800,
                failure_rate=0.0,
                step_breakdown={"s1_findings": 0.80, "s2_review_summary": 0.84},
            ),
        ],
        per_case_scores={
            "pr_001_missing_auth_check": {"claude-haiku-4-5": 0.85},
            "pr_002_missing_test_coverage": {"claude-haiku-4-5": 0.79},
        },
        # per_case_topics intentionally omitted (uses default={})
    )


@pytest.fixture()
def long_names_report() -> BenchmarkReport:
    """Report with very long case IDs and agent names to test truncation/wrapping."""
    return BenchmarkReport(
        benchmark_id="bench-006",
        workflow_id="wf_pr_review_v1",
        case_set_id="pr_review_cases_v1",
        created_at="2026-04-05T14:00:00Z",
        case_count=2,
        agents=[
            AgentSummary(
                agent_id="anthropic-claude-3-5-sonnet-20241022-with-extended-thinking",
                avg_score=0.93,
                p50_latency_ms=5000,
                p95_latency_ms=12000,
                failure_rate=0.0,
                step_breakdown={"s1_findings": 0.90, "s2_review_summary": 0.96},
            ),
            AgentSummary(
                agent_id="openai-gpt-4o-mini-2024-07-18-with-reasoning-effort-high",
                avg_score=0.88,
                p50_latency_ms=3000,
                p95_latency_ms=9000,
                failure_rate=0.05,
                step_breakdown={"s1_findings": 0.86, "s2_review_summary": 0.90},
            ),
        ],
        per_case_scores={
            "pr_001_missing_authentication_check_on_admin_dashboard_endpoint_v2": {
                "anthropic-claude-3-5-sonnet-20241022-with-extended-thinking": 0.95,
                "openai-gpt-4o-mini-2024-07-18-with-reasoning-effort-high": 0.90,
            },
            "pr_002_missing_unit_test_coverage_for_discount_calculator_service_module": {
                "anthropic-claude-3-5-sonnet-20241022-with-extended-thinking": 0.91,
                "openai-gpt-4o-mini-2024-07-18-with-reasoning-effort-high": 0.86,
            },
        },
        per_case_topics={
            "pr_001_missing_authentication_check_on_admin_dashboard_endpoint_v2": "Auth/Security",
            "pr_002_missing_unit_test_coverage_for_discount_calculator_service_module": "Testing",
        },
    )


# ---------------------------------------------------------------------------
# Edge case regression tests
# ---------------------------------------------------------------------------


class TestEdgeCaseRegressions:
    """Comprehensive edge case tests for report rendering."""

    def test_tied_overall_winners(
        self, tie_winners_report: BenchmarkReport, fixed_console: Console
    ) -> None:
        """Multiple agents with identical avg_score both marked as winners."""
        table = render_summary_table(tie_winners_report.agents)
        output = render(fixed_console, table)
        # Both agents should appear with their scores
        assert "claude-haiku-4-5" in output
        assert "gpt-4o-mini" in output
        assert "0.85" in output
        # Both should be marked as winners (bold) since they tie
        # Verify both agents are present and ordered by agent_id
        claude_pos = output.find("claude-haiku-4-5")
        gpt_pos = output.find("gpt-4o-mini")
        assert claude_pos < gpt_pos, "Tied agents should be sorted by agent_id"

    def test_tied_per_case_winners(
        self, tie_winners_report: BenchmarkReport, fixed_console: Console
    ) -> None:
        """Multiple agents with identical case score both marked as winners in topic table."""
        tables = render_per_topic_tables(tie_winners_report, 80)
        # Both cases have tied scores (0.85 each)
        for table in tables:
            output = render(fixed_console, table)
            # Both agents should appear in each case row
            assert "0.85" in output
            # Both should be marked as winners (bold formatting applied)
            # The em dash should NOT appear since both have scores
            assert "\u2014" not in output, "No missing scores in tied case"

    def test_single_agent_report(
        self, single_agent_report: BenchmarkReport, fixed_console: Console
    ) -> None:
        """Only one agent in report - comprehensive validation."""
        # Test summary table
        summary_table = render_summary_table(single_agent_report.agents)
        summary_output = render(fixed_console, summary_table)
        assert "claude-haiku-4-5" in summary_output
        assert "0.88" in summary_output
        assert "2000ms" in summary_output
        assert "0%" in summary_output or "0.0%" in summary_output

        # Test per-topic tables
        topic_tables = render_per_topic_tables(single_agent_report, 80)
        assert len(topic_tables) == 2
        for table in topic_tables:
            output = render(fixed_console, table)
            assert "claude-haiku-4-5" in output
            # Single agent should always be the winner
            assert "0.90" in output or "0.86" in output

        # Test step breakdown
        step_table = render_step_breakdown(single_agent_report.agents)
        step_output = render(fixed_console, step_table)
        assert "claude-haiku-4-5" in step_output
        assert "s1_findings" in step_output
        assert "s2_review_summary" in step_output

        # Test insights
        insights = compute_insights(
            single_agent_report.agents,
            single_agent_report.per_case_scores,
            single_agent_report.per_case_topics,
        )
        assert insights["overall_leader"] == {"claude-haiku-4-5"}
        assert insights["biggest_spread"] is None  # No spread with single agent

    def test_sparse_agent_case_matrix(
        self, sparse_scores_report: BenchmarkReport, fixed_console: Console
    ) -> None:
        """Missing agent scores for some cases render as em dash."""
        tables = render_per_topic_tables(sparse_scores_report, 80)

        # Find the Testing topic table (pr_002 has sparse data)
        testing_table = None
        for table in tables:
            if table.title and "Testing" in table.title:
                testing_table = table
                break

        assert testing_table is not None
        output = render(fixed_console, testing_table)
        # Should show em dash for missing gpt-4o-mini score on pr_002
        assert "\u2014" in output, "Missing scores should render as em dash"

        # Verify claude's score is present
        assert "0.70" in output, "Present scores should be visible"

    def test_long_case_and_agent_ids(
        self, long_names_report: BenchmarkReport, fixed_console: Console
    ) -> None:
        """Long identifiers handled without crashing (truncation/wrapping)."""
        # Test summary table with long agent IDs
        summary_table = render_summary_table(long_names_report.agents)
        summary_output = render(fixed_console, summary_table)

        # Both agents should be present (may be truncated with ellipsis)
        assert "anthropic-claude-3-5" in summary_output
        assert "openai-gpt-4o-mini" in summary_output

        # Test per-topic tables with long case IDs
        topic_tables = render_per_topic_tables(long_names_report, 80)
        assert len(topic_tables) == 2

        for table in topic_tables:
            output = render(fixed_console, table)
            # Long case IDs should be present (may be truncated/wrapped)
            assert "pr_001" in output or "pr_002" in output
            # Scores should still be visible
            assert "0.9" in output or "0.8" in output

        # Test step breakdown with long agent IDs
        step_table = render_step_breakdown(long_names_report.agents)
        step_output = render(fixed_console, step_table)
        assert "anthropic-claude-3-5" in step_output
        assert "openai-gpt-4o-mini" in step_output

    def test_non_identical_step_breakdown(
        self, non_identical_steps_report: BenchmarkReport, fixed_console: Console
    ) -> None:
        """Agents with different step sets - missing steps render as em dash."""
        table = render_step_breakdown(non_identical_steps_report.agents)
        output = render(fixed_console, table)

        # All unique steps should be present
        assert "s1_findings" in output
        assert "s2_review_summary" in output
        assert "s3_edge_cases" in output
        assert "s4_security_check" in output

        # Claude has s3 but not s4, GPT has s4 but not s3
        # Missing steps should show em dash
        assert "\u2014" in output, "Missing steps should render as em dash"

        # Scores should be present
        assert "0.88" in output  # Claude s1
        assert "0.92" in output  # Claude s2
        assert "0.90" in output  # Claude s3
        assert "0.82" in output  # GPT s1
        assert "0.88" in output  # GPT s2
        assert "0.85" in output  # GPT s4


@pytest.fixture()
def non_identical_steps_report() -> BenchmarkReport:
    """Report where agents have different step sets (partial overlap)."""
    return BenchmarkReport(
        benchmark_id="bench-007",
        workflow_id="wf_pr_review_v1",
        case_set_id="pr_review_cases_v1",
        created_at="2026-04-06T11:00:00Z",
        case_count=2,
        agents=[
            AgentSummary(
                agent_id="claude-haiku-4-5",
                avg_score=0.90,
                p50_latency_ms=2000,
                p95_latency_ms=4500,
                failure_rate=0.0,
                step_breakdown={
                    "s1_findings": 0.88,
                    "s2_review_summary": 0.92,
                    "s3_edge_cases": 0.90,
                },
            ),
            AgentSummary(
                agent_id="gpt-4o-mini",
                avg_score=0.85,
                p50_latency_ms=1800,
                p95_latency_ms=6000,
                failure_rate=0.0,
                step_breakdown={
                    "s1_findings": 0.82,
                    "s2_review_summary": 0.88,
                    "s4_security_check": 0.85,
                },
            ),
        ],
        per_case_scores={
            "pr_001_missing_auth_check": {
                "claude-haiku-4-5": 0.92,
                "gpt-4o-mini": 0.88,
            },
            "pr_002_missing_test_coverage": {
                "claude-haiku-4-5": 0.88,
                "gpt-4o-mini": 0.82,
            },
        },
        per_case_topics={
            "pr_001_missing_auth_check": "Auth/Security",
            "pr_002_missing_test_coverage": "Testing",
        },
    )


# ---------------------------------------------------------------------------
# Fixture validation tests
# ---------------------------------------------------------------------------


class TestBenchmarkReportFixtures:
    """Validate that all benchmark report fixtures are well-formed."""

    def test_two_agent_report_structure(self, two_agent_report: BenchmarkReport) -> None:
        """Two-agent fixture has two agents and matching per-case keys."""
        assert len(two_agent_report.agents) == 2
        assert len(two_agent_report.per_case_scores) == 3
        assert len(two_agent_report.per_case_topics) == 3
        for agent in two_agent_report.agents:
            assert agent.failure_rate == 0.0

    def test_single_agent_report_structure(self, single_agent_report: BenchmarkReport) -> None:
        """Single-agent fixture has exactly one agent."""
        assert len(single_agent_report.agents) == 1
        assert single_agent_report.agents[0].agent_id == "claude-haiku-4-5"
        assert len(single_agent_report.per_case_scores) == 2

    def test_tie_winners_report_same_avg(self, tie_winners_report: BenchmarkReport) -> None:
        """Tie fixture has agents with identical average scores."""
        assert len(tie_winners_report.agents) == 2
        scores = [a.avg_score for a in tie_winners_report.agents]
        assert scores[0] == scores[1] == 0.85

    def test_sparse_scores_missing_agent_data(self, sparse_scores_report: BenchmarkReport) -> None:
        """Sparse fixture has cases where not all agents have scores."""
        case_002 = sparse_scores_report.per_case_scores["pr_002_missing_test_coverage"]
        assert "claude-haiku-4-5" in case_002
        assert "gpt-4o-mini" not in case_002
        # pr_003 missing entirely from scores
        assert "pr_003_missing_null_guard" not in sparse_scores_report.per_case_scores

    def test_legacy_report_no_topics(self, legacy_report_no_topics: BenchmarkReport) -> None:
        """Legacy fixture has empty per_case_topics."""
        assert legacy_report_no_topics.per_case_topics == {}

    def test_long_names_report_has_long_identifiers(
        self, long_names_report: BenchmarkReport
    ) -> None:
        """Long names fixture has identifiers exceeding 30 characters."""
        for agent in long_names_report.agents:
            assert len(agent.agent_id) > 30
        for case_id in long_names_report.per_case_scores:
            assert len(case_id) > 30


# ---------------------------------------------------------------------------
# Data helper tests
# ---------------------------------------------------------------------------


class TestOrderAgents:
    """Tests for order_agents sorting."""

    def test_sorts_by_avg_score_descending(self, two_agent_report: BenchmarkReport) -> None:
        """Higher avg_score comes first."""
        result = order_agents(two_agent_report.agents)
        assert result[0].agent_id == "claude-haiku-4-5"  # 0.91
        assert result[1].agent_id == "gpt-4o-mini"  # 0.85

    def test_tiebreak_by_agent_id(self, tie_winners_report: BenchmarkReport) -> None:
        """Tied scores sorted by agent_id ascending."""
        result = order_agents(tie_winners_report.agents)
        assert result[0].agent_id == "claude-haiku-4-5"  # alphabetically first
        assert result[1].agent_id == "gpt-4o-mini"

    def test_single_agent(self, single_agent_report: BenchmarkReport) -> None:
        """Single agent returns a single-element list."""
        result = order_agents(single_agent_report.agents)
        assert len(result) == 1
        assert result[0].agent_id == "claude-haiku-4-5"

    def test_empty_list(self) -> None:
        """Empty list returns empty list."""
        assert order_agents([]) == []


class TestGroupCasesByTopic:
    """Tests for group_cases_by_topic."""

    def test_groups_correctly(self, two_agent_report: BenchmarkReport) -> None:
        """Cases grouped under their canonical topics."""
        groups = group_cases_by_topic(
            two_agent_report.per_case_scores,
            two_agent_report.per_case_topics,
        )
        assert "Auth/Security" in groups
        assert "Testing" in groups
        assert "Null Safety" in groups
        assert len(groups["Auth/Security"]) == 1
        assert len(groups["Testing"]) == 1
        assert len(groups["Null Safety"]) == 1

    def test_uncategorized_when_no_topic(self) -> None:
        """Cases without topic go to Other."""
        scores = {"pr_001": {"agent-a": 0.5}}
        topics: dict[str, str] = {}
        groups = group_cases_by_topic(scores, topics)
        assert "Other" in groups
        assert len(groups["Other"]) == 1

    def test_empty_scores(self) -> None:
        """Empty scores returns empty dict."""
        groups = group_cases_by_topic({}, {})
        assert groups == {}

    def test_partial_topic_map(self) -> None:
        """Cases with no topic mapping fall back to Other."""
        scores = {
            "pr_001": {"a": 0.5},
            "pr_002": {"a": 0.8},
            "pr_003": {"a": 0.3},
        }
        topics = {"pr_001": "Auth/Security"}  # pr_002, pr_003 missing
        groups = group_cases_by_topic(scores, topics)
        assert len(groups["Auth/Security"]) == 1
        assert len(groups["Other"]) == 2
        case_ids_in_other = {cid for cid, _ in groups["Other"]}
        assert "pr_002" in case_ids_in_other
        assert "pr_003" in case_ids_in_other


class TestSortCases:
    """Tests for sort_cases."""

    def test_sorts_by_case_id(self) -> None:
        """Cases sorted by case_id alphabetically."""
        cases = [
            ("pr_003_c", {"a": 0.5}),
            ("pr_001_a", {"a": 0.9}),
            ("pr_002_b", {"a": 0.7}),
        ]
        result = sort_cases(cases)
        assert result[0][0] == "pr_001_a"
        assert result[1][0] == "pr_002_b"
        assert result[2][0] == "pr_003_c"

    def test_empty_cases(self) -> None:
        """Empty list returns empty list."""
        assert sort_cases([]) == []


class TestComputeWinners:
    """Tests for compute_winners."""

    def test_single_winner(self) -> None:
        """Agent with highest score wins."""
        winners = compute_winners({"a": 0.9, "b": 0.8, "c": 0.7})
        assert winners == {"a"}

    def test_tie_returns_multiple(self) -> None:
        """Tied agents both win."""
        winners = compute_winners({"a": 0.85, "b": 0.85, "c": 0.7})
        assert winners == {"a", "b"}

    def test_all_null_returns_empty(self) -> None:
        """All None scores returns empty set."""
        winners = compute_winners({"a": None, "b": None})
        assert winners == set()

    def test_mixed_null_ignores_nulls(self) -> None:
        """None scores are ignored."""
        winners = compute_winners({"a": 0.9, "b": None, "c": None})
        assert winners == {"a"}

    def test_single_agent(self) -> None:
        """Single agent is always winner."""
        winners = compute_winners({"a": 0.5})
        assert winners == {"a"}

    def test_empty_dict(self) -> None:
        """Empty scores returns empty set."""
        assert compute_winners({}) == set()


class TestComputeInsights:
    """Tests for compute_insights."""

    def test_overall_leader(self, two_agent_report: BenchmarkReport) -> None:
        """Overall leader is the agent with highest avg_score."""
        insights = compute_insights(
            two_agent_report.agents,
            two_agent_report.per_case_scores,
            two_agent_report.per_case_topics,
        )
        assert insights["overall_leader"] == {"claude-haiku-4-5"}

    def test_overall_leader_tie(self, tie_winners_report: BenchmarkReport) -> None:
        """Tied overall leaders both returned."""
        insights = compute_insights(
            tie_winners_report.agents,
            tie_winners_report.per_case_scores,
            tie_winners_report.per_case_topics,
        )
        assert insights["overall_leader"] == {"claude-haiku-4-5", "gpt-4o-mini"}

    def test_per_topic_leaders(self, two_agent_report: BenchmarkReport) -> None:
        """Per-topic leaders computed correctly."""
        insights = compute_insights(
            two_agent_report.agents,
            two_agent_report.per_case_scores,
            two_agent_report.per_case_topics,
        )
        # Auth/Security: claude=0.92, gpt=0.92 -> tie
        assert insights["per_topic_leaders"]["Auth/Security"] == {"claude-haiku-4-5", "gpt-4o-mini"}
        # Testing: claude=0.90, gpt=0.88 -> claude wins
        assert insights["per_topic_leaders"]["Testing"] == {"claude-haiku-4-5"}
        # Null Safety: claude=0.91, gpt=0.75 -> claude wins
        assert insights["per_topic_leaders"]["Null Safety"] == {"claude-haiku-4-5"}

    def test_biggest_spread(self, two_agent_report: BenchmarkReport) -> None:
        """Biggest spread is the max score difference on a single case."""
        insights = compute_insights(
            two_agent_report.agents,
            two_agent_report.per_case_scores,
            two_agent_report.per_case_topics,
        )
        spread = insights["biggest_spread"]
        assert spread is not None
        # pr_003: 0.91 - 0.75 = 0.16
        assert spread["spread"] == 0.16
        assert spread["case_id"] == "pr_003_missing_null_guard"

    def test_no_spread_for_single_agent(self, single_agent_report: BenchmarkReport) -> None:
        """Single agent has no spread (only 1 score per case)."""
        insights = compute_insights(
            single_agent_report.agents,
            single_agent_report.per_case_scores,
            single_agent_report.per_case_topics,
        )
        assert insights["biggest_spread"] is None

    def test_legacy_report_no_topics(self, legacy_report_no_topics: BenchmarkReport) -> None:
        """Legacy report with no topics still works (all go to Other)."""
        insights = compute_insights(
            legacy_report_no_topics.agents,
            legacy_report_no_topics.per_case_scores,
            legacy_report_no_topics.per_case_topics,
        )
        assert "Other" in insights["per_topic_leaders"]


# ---------------------------------------------------------------------------
# Rich renderer tests
# ---------------------------------------------------------------------------


class TestRenderSummaryTable:
    """Tests for render_summary_table."""

    def test_renders_agents_ordered(
        self, two_agent_report: BenchmarkReport, fixed_console: Console
    ) -> None:
        """Summary table renders agents ordered by score."""
        table = render_summary_table(two_agent_report.agents)
        output = render(fixed_console, table)
        # claude (0.91) should appear before gpt (0.85)
        claude_pos = output.find("claude-haiku-4-5")
        gpt_pos = output.find("gpt-4o-mini")
        assert claude_pos < gpt_pos

    def test_single_agent(
        self, single_agent_report: BenchmarkReport, fixed_console: Console
    ) -> None:
        """Summary table works with a single agent."""
        table = render_summary_table(single_agent_report.agents)
        output = render(fixed_console, table)
        assert "claude-haiku-4-5" in output
        assert "0.88" in output

    def test_shows_latency(self, two_agent_report: BenchmarkReport, fixed_console: Console) -> None:
        """Summary table shows latency values."""
        table = render_summary_table(two_agent_report.agents)
        output = render(fixed_console, table)
        assert "2500ms" in output
        assert "1500ms" in output


class TestRenderPerTopicTables:
    """Tests for render_per_topic_tables."""

    def test_creates_one_table_per_topic(self, two_agent_report: BenchmarkReport) -> None:
        """One table per topic."""
        tables = render_per_topic_tables(two_agent_report, 80)
        assert len(tables) == 3  # Auth/Security, Null Safety, Testing

    def test_auth_security_comes_first(self, two_agent_report: BenchmarkReport) -> None:
        """Auth/Security topic table appears first."""
        tables = render_per_topic_tables(two_agent_report, 80)
        assert tables[0].title == "Topic: Auth/Security"

    def test_topics_alpha_after_auth(self, two_agent_report: BenchmarkReport) -> None:
        """After Auth/Security, topics are alphabetical."""
        tables = render_per_topic_tables(two_agent_report, 80)
        titles = [t.title for t in tables]
        # Auth/Security first, then Null Safety, then Testing (alphabetical)
        assert titles[0] == "Topic: Auth/Security"
        assert titles[1] == "Topic: Null Safety"
        assert titles[2] == "Topic: Testing"

    def test_single_agent_columns(
        self, single_agent_report: BenchmarkReport, fixed_console: Console
    ) -> None:
        """Per-topic tables work with a single agent."""
        tables = render_per_topic_tables(single_agent_report, 80)
        assert len(tables) == 2
        for t in tables:
            output = render(fixed_console, t)
            assert "claude-haiku-4-5" in output

    def test_em_dash_for_missing_score(
        self, sparse_scores_report: BenchmarkReport, fixed_console: Console
    ) -> None:
        """Missing scores render as em dash."""
        tables = render_per_topic_tables(sparse_scores_report, 80)
        # pr_002 has only claude, gpt is missing -> should show em dash
        testing_table = [t for t in tables if t.title and "Testing" in t.title][0]
        output = render(fixed_console, testing_table)
        assert "\u2014" in output  # em dash

    def test_legacy_no_topics_groups_as_uncategorized(
        self, legacy_report_no_topics: BenchmarkReport, fixed_console: Console
    ) -> None:
        """Legacy report with no topics groups everything as Other."""
        tables = render_per_topic_tables(legacy_report_no_topics, 80)
        assert len(tables) == 1
        assert tables[0].title == "Topic: Other"


class TestRenderStepBreakdown:
    """Tests for render_step_breakdown."""

    def test_renders_all_steps(
        self, two_agent_report: BenchmarkReport, fixed_console: Console
    ) -> None:
        """Step breakdown shows all steps."""
        table = render_step_breakdown(two_agent_report.agents)
        output = render(fixed_console, table)
        assert "s1_findings" in output
        assert "s2_review_summary" in output

    def test_shows_agent_scores(
        self, two_agent_report: BenchmarkReport, fixed_console: Console
    ) -> None:
        """Step breakdown shows agent scores per step."""
        table = render_step_breakdown(two_agent_report.agents)
        output = render(fixed_console, table)
        # claude: s1=0.88, s2=0.94
        assert "0.88" in output
        assert "0.94" in output

    def test_single_agent(
        self, single_agent_report: BenchmarkReport, fixed_console: Console
    ) -> None:
        """Step breakdown works with single agent."""
        table = render_step_breakdown(single_agent_report.agents)
        output = render(fixed_console, table)
        assert "claude-haiku-4-5" in output

    def test_empty_agents(self) -> None:
        """Step breakdown handles empty agent list."""
        table = render_step_breakdown([])
        assert table is not None


class TestRenderInsights:
    """Tests for render_insights."""

    def test_renders_overall_leader(
        self, two_agent_report: BenchmarkReport, fixed_console: Console
    ) -> None:
        """Insights panel shows overall leader."""
        insights = compute_insights(
            two_agent_report.agents,
            two_agent_report.per_case_scores,
            two_agent_report.per_case_topics,
        )
        rendered = render(fixed_console, render_insights(insights))
        assert "Overall Leader" in rendered
        assert "claude-haiku-4-5" in rendered

    def test_renders_biggest_spread(
        self, two_agent_report: BenchmarkReport, fixed_console: Console
    ) -> None:
        """Insights panel shows biggest spread."""
        insights = compute_insights(
            two_agent_report.agents,
            two_agent_report.per_case_scores,
            two_agent_report.per_case_topics,
        )
        rendered = render(fixed_console, render_insights(insights))
        assert "Biggest Spread" in rendered
        assert "0.16" in rendered

    def test_renders_topic_leaders(
        self, two_agent_report: BenchmarkReport, fixed_console: Console
    ) -> None:
        """Insights panel shows per-topic leaders."""
        insights = compute_insights(
            two_agent_report.agents,
            two_agent_report.per_case_scores,
            two_agent_report.per_case_topics,
        )
        rendered = render(fixed_console, render_insights(insights))
        assert "Auth/Security" in rendered
        assert "Testing" in rendered
        assert "Null Safety" in rendered


class TestDemoRendererRegressions:
    """Regression tests for demo-mode report rendering."""

    def test_render_executive_summary_renders_without_rich_text_table_crash(
        self,
        two_agent_report: BenchmarkReport,
        fixed_console: Console,
    ) -> None:
        """Executive summary render path should not crash on Rich composition."""
        demo = load_reporting_demo_module()
        summary = demo.render_executive_summary(
            two_agent_report.agents,
            two_agent_report.case_count,
        )

        try:
            output = render(fixed_console, summary)
        except Exception as exc:  # pragma: no cover - this is the regression signal
            pytest.fail(f"render_executive_summary raised unexpectedly: {exc}")

        assert "Executive Summary" in output
        assert "Leading Agent:" in output
        assert "claude-haiku-4-5" in output
        assert "Agents Evaluated" in output
        assert "Test Cases" in output

    def test_render_full_demo_report_includes_expected_sections(
        self,
        two_agent_report: BenchmarkReport,
        fixed_console: Console,
    ) -> None:
        """Full demo rendering should complete and include key section markers."""
        demo = load_reporting_demo_module()
        try:
            with fixed_console.capture() as capture:
                demo.render_full_demo_report(
                    two_agent_report,
                    fixed_console,
                    show_per_case=True,
                )
        except Exception as exc:  # pragma: no cover - this is the regression signal
            pytest.fail(f"render_full_demo_report raised unexpectedly: {exc}")

        output = capture.get()
        section_markers = [
            "Executive Summary",
            "Agent Performance Leaderboard",
            "Topic Performance Overview",
            "Auth/Security",
            "Step-Level Analysis",
            "Key Insights",
            "AgentBench v0.1.0",
        ]
        for marker in section_markers:
            assert marker in output

        positions = [output.find(marker) for marker in section_markers]
        assert positions == sorted(positions)
