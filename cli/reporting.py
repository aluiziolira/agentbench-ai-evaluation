"""Pure data helpers and Rich renderers for benchmark report output.

All functions are side-effect free: no HTTP calls, no sleep, no Typer.
"""

from __future__ import annotations

from typing import Any

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text

from agentbench.models.results import AgentSummary, BenchmarkReport

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EM_DASH = "\u2014"  # "—"
AUTH_SECURITY_PREFIX = "Auth/Security"


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def order_agents(agents: list[AgentSummary]) -> list[AgentSummary]:
    """Sort agents by avg_score descending, then agent_id ascending for ties."""
    return sorted(agents, key=lambda a: (-a.avg_score, a.agent_id))


def group_cases_by_topic(
    per_case_scores: dict[str, dict[str, float]],
    per_case_topics: dict[str, str],
) -> dict[str, list[tuple[str, dict[str, float]]]]:
    """Group cases under canonical topics.

    Returns a dict mapping topic name -> list of (case_id, agent_scores).
    """
    groups: dict[str, list[tuple[str, dict[str, float]]]] = {}
    for case_id, scores in per_case_scores.items():
        topic = per_case_topics.get(case_id, "Other")
        groups.setdefault(topic, []).append((case_id, scores))
    return groups


def sort_cases(cases: list[tuple[str, dict[str, float]]]) -> list[tuple[str, dict[str, float]]]:
    """Sort cases by case_id within a topic group."""
    return sorted(cases, key=lambda c: c[0])


def compute_winners(scores: dict[str, float]) -> set[str]:
    """Return agent_ids with the highest non-null score (handles ties).

    Filters out None values. If all scores are None, returns empty set.
    """
    valid: dict[str, float] = {aid: s for aid, s in scores.items() if s is not None}
    if not valid:
        return set()
    max_score = max(valid.values())
    return {aid for aid, s in valid.items() if s == max_score}


def _topic_sort_key(topic: str) -> tuple[int, str]:
    """Auth/Security sorts first, then alphabetical."""
    if topic == AUTH_SECURITY_PREFIX:
        return (0, "")
    return (1, topic.lower())


def compute_insights(
    agents: list[AgentSummary],
    per_case_scores: dict[str, dict[str, float]],
    per_case_topics: dict[str, str],
) -> dict[str, Any]:
    """Compute overall leader, per-topic leaders, and biggest score spread.

    Returns:
        {
            "overall_leader": set of agent_ids,
            "per_topic_leaders": dict[topic, set[agent_id]],
            "biggest_spread": {"case_id": str, "spread": float} or None,
        }
    """
    ordered = order_agents(agents)

    # Overall leader
    if ordered:
        top_score = ordered[0].avg_score
        overall_leader: set[str] = {a.agent_id for a in ordered if a.avg_score == top_score}
    else:
        overall_leader = set()

    # Per-topic leaders
    grouped = group_cases_by_topic(per_case_scores, per_case_topics)
    per_topic_leaders: dict[str, set[str]] = {}
    for topic, cases in grouped.items():
        # Average per agent across all cases in this topic
        agent_totals: dict[str, list[float]] = {}
        for _case_id, scores in cases:
            for aid, s in scores.items():
                if s is not None:
                    agent_totals.setdefault(aid, []).append(s)

        agent_avgs: dict[str, float] = {}
        for aid, vals in agent_totals.items():
            agent_avgs[aid] = sum(vals) / len(vals)

        if agent_avgs:
            winners = compute_winners(agent_avgs)
            per_topic_leaders[topic] = winners
        else:
            per_topic_leaders[topic] = set()

    # Biggest spread (max difference between any two agents on a single case)
    biggest_spread: dict[str, Any] | None = None
    max_spread = -1.0
    for case_id, scores in per_case_scores.items():
        valid_scores = [s for s in scores.values() if s is not None]
        if len(valid_scores) >= 2:
            spread = max(valid_scores) - min(valid_scores)
            if spread > max_spread:
                max_spread = spread
                biggest_spread = {"case_id": case_id, "spread": round(spread, 4)}

    return {
        "overall_leader": overall_leader,
        "per_topic_leaders": per_topic_leaders,
        "biggest_spread": biggest_spread,
    }


# ---------------------------------------------------------------------------
# Rich renderers
# ---------------------------------------------------------------------------


def _render_score_cell(score: float | None, is_winner: bool) -> Text:
    """Render a single score cell with optional bold for winner."""
    if score is None:
        return Text(EM_DASH)
    text = f"{score:.2f}"
    style = "bold" if is_winner else ""
    return Text(text, style=style)


def render_summary_table(agents: list[AgentSummary]) -> Table:
    """Render the agent summary table (avg score, latency, failure rate)."""
    ordered = order_agents(agents)

    table = Table(title="Agent Performance", show_lines=False)
    table.add_column("Agent", style="cyan")
    table.add_column("Avg Score", justify="right")
    table.add_column("P50 Latency", justify="right", style="yellow")
    table.add_column("P95 Latency", justify="right", style="yellow")
    table.add_column("Failure Rate", justify="right")

    # Find overall winners
    if ordered:
        top_score = ordered[0].avg_score
        winners = {a.agent_id for a in ordered if a.avg_score == top_score}
    else:
        winners = set()

    for agent in ordered:
        score_text = _render_score_cell(agent.avg_score, agent.agent_id in winners)
        table.add_row(
            agent.agent_id,
            score_text,
            f"{agent.p50_latency_ms}ms",
            f"{agent.p95_latency_ms}ms",
            f"{agent.failure_rate:.0%}",
        )

    return table


def render_per_topic_tables(
    report: BenchmarkReport,
    console_width: int,
) -> list[Table]:
    """Render one table per topic with dynamic agent columns.

    Agent columns get equal ratio. Topics ordered: Auth/Security first,
    then alphabetical.
    """
    ordered = order_agents(report.agents)
    agent_ids = [a.agent_id for a in ordered]

    grouped = group_cases_by_topic(report.per_case_scores, report.per_case_topics)

    # Sort topics: Auth/Security first, then alphabetical
    sorted_topics = sorted(grouped.keys(), key=_topic_sort_key)

    tables: list[Table] = []
    num_agents = len(agent_ids)

    for topic in sorted_topics:
        cases = sort_cases(grouped[topic])

        # Compute per-case winners within this topic
        topic_table = Table(title=f"Topic: {topic}", show_lines=False)
        topic_table.add_column("Case", style="cyan", min_width=20)

        # Add equal-ratio agent columns
        for aid in agent_ids:
            topic_table.add_column(aid, justify="right", ratio=1 if num_agents > 0 else None)

        for case_id, scores in cases:
            winners = compute_winners(scores)
            row_cells: list[Any] = [case_id]
            for aid in agent_ids:
                score = scores.get(aid)
                is_winner = aid in winners
                row_cells.append(_render_score_cell(score, is_winner))
            topic_table.add_row(*row_cells)

        tables.append(topic_table)

    return tables


def render_step_breakdown(agents: list[AgentSummary]) -> Table:
    """Render step-level comparison across all agents."""
    ordered = order_agents(agents)
    if not ordered:
        return Table(title="Step Breakdown", show_lines=False)

    # Collect all step IDs in sorted order
    all_steps: set[str] = set()
    for agent in ordered:
        all_steps.update(agent.step_breakdown.keys())
    sorted_steps = sorted(all_steps)

    table = Table(title="Step Breakdown", show_lines=False)
    table.add_column("Step", style="cyan")

    for agent in ordered:
        table.add_column(agent.agent_id, justify="right")

    for step in sorted_steps:
        # Compute winners for this step across agents
        step_scores: dict[str, float] = {}
        for agent in ordered:
            score = agent.step_breakdown.get(step)
            if score is not None:
                step_scores[agent.agent_id] = score
        winners = compute_winners(step_scores)

        row_cells: list[Any] = [step]
        for agent in ordered:
            score = agent.step_breakdown.get(step)
            is_winner = agent.agent_id in winners
            row_cells.append(_render_score_cell(score, is_winner))
        table.add_row(*row_cells)

    return table


def render_insights(insights: dict[str, Any]) -> RenderableType:
    """Render a compact insights summary.

    Shows overall leader, per-topic leaders, and biggest score spread.
    """
    from rich.panel import Panel
    from rich.text import Text

    lines: list[Text] = []

    # Overall leader
    leaders = sorted(insights.get("overall_leader", set()))
    leader_str = ", ".join(leaders) if leaders else EM_DASH
    lines.append(Text.assemble(Text("Overall Leader: ", style="bold"), Text(leader_str)))

    # Per-topic leaders
    per_topic = insights.get("per_topic_leaders", {})
    if per_topic:
        sorted_topics = sorted(per_topic.keys(), key=_topic_sort_key)
        for topic in sorted_topics:
            topic_leaders = sorted(per_topic[topic])
            leader_str = ", ".join(topic_leaders) if topic_leaders else EM_DASH
            lines.append(Text.assemble(Text(f"{topic}: ", style="bold"), Text(leader_str)))

    # Biggest spread
    spread_info = insights.get("biggest_spread")
    if spread_info:
        case_id = spread_info["case_id"]
        spread = spread_info["spread"]
        lines.append(
            Text.assemble(
                Text("Biggest Spread: ", style="bold"),
                Text(f"{spread:.2f} on {case_id}"),
            )
        )

    content = Text("\n").join(lines)
    return Panel(content, title="Insights", border_style="blue")
