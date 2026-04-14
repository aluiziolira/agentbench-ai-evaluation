"""Demo-optimized Rich renderers for benchmark report output.

Enhanced visuals for hiring portfolio showcase with:
- Executive summary with key metrics
- Visual badges and awards for winners
- Color-coded performance indicators
- Progress bars and sparklines
- Professional banner/header
- Demo mode with enhanced styling

All functions are side-effect free: no HTTP calls, no sleep, no Typer.
"""

from __future__ import annotations

from typing import Any

from rich import box
from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from agentbench.models.results import AgentSummary, BenchmarkReport
from cli.reporting import (
    AUTH_SECURITY_PREFIX,
    EM_DASH,
    compute_insights,
    compute_winners,
    group_cases_by_topic,
    order_agents,
    sort_cases,
)


def _topic_sort_key(topic: str) -> tuple[int, str]:
    """Auth/Security sorts first, then alphabetical."""
    if topic == AUTH_SECURITY_PREFIX:
        return (0, "")
    return (1, topic.lower())


# -----------------------------------------------------------------------------
# Demo Visual Constants
# -----------------------------------------------------------------------------

DEMO_COLORS = {
    "gold": "#FFD700",
    "silver": "#C0C0C0",
    "bronze": "#CD7F32",
    "winner": "bold bright_green",
    "excellent": "bright_green",
    "good": "green",
    "average": "yellow",
    "poor": "red",
    "accent": "bright_cyan",
    "header": "bright_blue",
    "border": "blue",
}

# Icons for visual impact
ICONS = {
    "trophy": "\U0001f3c6",
    "medal_gold": "\U0001f947",
    "medal_silver": "\U0001f948",
    "medal_bronze": "\U0001f949",
    "star": "\u2b50",
    "rocket": "\U0001f680",
    "check": "\u2713",
    "warning": "\u26a0",
    "chart": "\U0001f4ca",
    "clock": "\u23f1",
    "target": "\U0001f3af",
    "shield": "\U0001f6e1",
    "zap": "\u26a1",
    "brain": "\U0001f9e0",
    "code": "\U0001f4bb",
    "fire": "\U0001f525",
}

TOPIC_ICONS = {
    "Auth/Security": "\U0001f6e1",
    "Testing": "\U0001f9ea",
    "Null Safety": "\U0001f512",
    "API Compatibility": "\U0001f50c",
    "Error Handling": "\u26a0",
    "Caching/State": "\u26a1",
    "Input Validation": "\u2713",
    "Performance": "\U0001f680",
}

# -----------------------------------------------------------------------------
# Demo-optimized renderers
# -----------------------------------------------------------------------------


def render_demo_header() -> RenderableType:
    """Render an impressive demo header banner."""
    # Create a multi-line banner with ASCII styling
    banner_lines = [
        f"{ICONS['rocket']} [bold bright_blue]AgentBench[/] {ICONS['chart']}",
        "[dim]AI Agent Evaluation Framework[/]",
        "",
        "[bright_cyan]Event-driven Orchestration • Deterministic Scoring • Reproducible Baselines[/]",
    ]

    header_text = Text.from_markup("\n".join(banner_lines), justify="center")

    return Panel(
        Align.center(header_text),
        box=box.DOUBLE_EDGE,
        border_style="bright_blue",
        padding=(1, 2),
    )


def render_executive_summary(agents: list[AgentSummary], case_count: int) -> RenderableType:
    """Render an executive summary with key metrics for demo impact."""
    ordered = order_agents(agents)

    if not ordered:
        return Panel("[dim]No agents to summarize[/]", title="Executive Summary")

    # Build summary metrics
    top_agent = ordered[0]
    total_agents = len(agents)
    avg_score = sum(a.avg_score for a in agents) / total_agents if agents else 0

    # Performance grade
    if top_agent.avg_score >= 0.9:
        grade = f"{ICONS['trophy']} [bold bright_green]PRODUCTION READY[/]"
    elif top_agent.avg_score >= 0.8:
        grade = f"{ICONS['star']} [bold green]STRONG BASELINE[/]"
    elif top_agent.avg_score >= 0.7:
        grade = "[yellow]BORDERLINE[/]"
    else:
        grade = "[red]NEEDS ITERATION[/]"

    # Create metric cards
    metrics = Table.grid(padding=2)
    metrics.add_column(justify="center", min_width=20)
    metrics.add_column(justify="center", min_width=20)
    metrics.add_column(justify="center", min_width=20)

    metrics.add_row(
        Panel(
            f"[bold bright_blue]{total_agents}[/]\n[dim]Agents Evaluated[/]",
            box=box.ROUNDED,
            border_style="blue",
        ),
        Panel(
            f"[bold bright_green]{case_count}[/]\n[dim]Test Cases[/]",
            box=box.ROUNDED,
            border_style="green",
        ),
        Panel(
            f"[bold bright_cyan]{avg_score:.1%}[/]\n[dim]Benchmark Avg[/]",
            box=box.ROUNDED,
            border_style="cyan",
        ),
    )

    # Winner announcement
    winner_text = Text.assemble(
        (f"{ICONS['medal_gold']} ", ""),
        ("Leading Agent: ", "bold"),
        (top_agent.agent_id, "bold bright_green"),
        (f" ({top_agent.avg_score:.1%} accuracy)", ""),
    )

    grade_text = Text.from_markup(f"Performance Grade: {grade}")
    summary_content = Group(
        Align.center(winner_text),
        Align.center(grade_text),
        Text(""),
    )

    # Combine text and metrics table vertically using safe renderable grouping
    content_group = Group(summary_content, Align.center(metrics))

    return Panel(
        content_group,
        title=f"[bold bright_blue]{ICONS['target']} Executive Summary[/]",
        border_style="bright_blue",
        box=box.ROUNDED,
        padding=(1, 2),
    )


def _get_medal_for_rank(rank: int) -> str:
    """Get medal emoji for ranking."""
    medals = {0: ICONS["medal_gold"], 1: ICONS["medal_silver"], 2: ICONS["medal_bronze"]}
    return medals.get(rank, "")


def _get_score_color(score: float) -> str:
    """Get color based on score."""
    if score >= 0.9:
        return "bright_green"
    elif score >= 0.8:
        return "green"
    elif score >= 0.7:
        return "yellow"
    else:
        return "red"


def render_summary_table_demo(agents: list[AgentSummary]) -> Table:
    """Render an enhanced agent summary table with demo visuals."""
    ordered = order_agents(agents)

    table = Table(
        title=f"{ICONS['chart']} Agent Performance Leaderboard",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold bright_blue",
        border_style="blue",
        row_styles=["", "dim"],
        padding=(0, 1),
    )

    table.add_column("Rank", justify="center", width=6)
    table.add_column("Agent", style="cyan", min_width=20)
    table.add_column("Score", justify="center", min_width=10)
    table.add_column("Bar", justify="left", width=12)
    table.add_column("P50 Latency", justify="right", style="yellow")
    table.add_column("P95 Latency", justify="right", style="yellow")
    table.add_column("Success %", justify="center")

    for rank, agent in enumerate(ordered):
        medal = _get_medal_for_rank(rank)
        score_color = _get_score_color(agent.avg_score)

        # Score with percentage bar
        score_bar_filled = int(agent.avg_score * 10)
        score_bar = "█" * score_bar_filled + "░" * (10 - score_bar_filled)

        # Reliability indicator
        if agent.failure_rate == 0:
            reliability = f"{ICONS['check']} [green]100%[/]"
        else:
            reliability = f"{ICONS['warning']} [red]{(1 - agent.failure_rate):.0%}[/]"

        table.add_row(
            f"{medal} #{rank + 1}" if medal else f"#{rank + 1}",
            agent.agent_id,
            f"[{score_color}]{agent.avg_score:.2f}[/]",
            f"[{score_color}]{score_bar}[/]",
            f"{agent.p50_latency_ms:,}ms",
            f"{agent.p95_latency_ms:,}ms",
            reliability,
        )
    return table


def render_per_topic_tables_demo(
    report: BenchmarkReport,
    console_width: int,
) -> list[Table]:
    """Render enhanced per-topic tables with visual indicators."""
    ordered = order_agents(report.agents)
    agent_ids = [a.agent_id for a in ordered]

    grouped = group_cases_by_topic(report.per_case_scores, report.per_case_topics)
    sorted_topics = sorted(grouped.keys(), key=_topic_sort_key)

    tables: list[Table] = []

    for topic in sorted_topics:
        cases = sort_cases(grouped[topic])
        icon = TOPIC_ICONS.get(topic, ICONS["code"])

        # Create table with modern styling
        topic_table = Table(
            title=f"{icon} {topic}",
            box=box.SIMPLE_HEAD,
            show_header=True,
            header_style="bold bright_cyan",
            border_style="cyan",
            padding=(0, 1),
        )

        topic_table.add_column("Case", style="bright_white", min_width=25)

        for aid in agent_ids:
            topic_table.add_column(
                aid[:15] + "..." if len(aid) > 15 else aid,
                justify="center",
                width=12,
            )

        for case_id, scores in cases:
            winners = compute_winners(scores)
            row_cells: list[Any] = [case_id[:30] + "..." if len(case_id) > 30 else case_id]

            for aid in agent_ids:
                score = scores.get(aid)
                if score is None:
                    cell = Text(EM_DASH, style="dim")
                else:
                    is_winner = aid in winners
                    color = _get_score_color(score)
                    if is_winner:
                        cell = Text(
                            f"{ICONS['star']} {score:.2f}",
                            style=f"bold {color}",
                        )
                    else:
                        cell = Text(f"{score:.2f}", style=color)
                row_cells.append(cell)

            topic_table.add_row(*row_cells)

        tables.append(topic_table)

    return tables


def render_step_breakdown_demo(agents: list[AgentSummary]) -> Table:
    """Render enhanced step breakdown with visual indicators."""
    ordered = order_agents(agents)
    if not ordered:
        return Table(title="Step Breakdown", box=box.ROUNDED)

    # Collect all step IDs
    all_steps: set[str] = set()
    for agent in ordered:
        all_steps.update(agent.step_breakdown.keys())
    sorted_steps = sorted(all_steps)

    table = Table(
        title=f"{ICONS['brain']} Step-Level Analysis",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold bright_blue",
        border_style="blue",
        padding=(0, 1),
    )

    table.add_column("Step", style="bright_cyan", min_width=20)

    for agent in ordered:
        table.add_column(
            agent.agent_id[:15] + "..." if len(agent.agent_id) > 15 else agent.agent_id,
            justify="center",
        )

    for step in sorted_steps:
        step_scores: dict[str, float] = {}
        for agent in ordered:
            score = agent.step_breakdown.get(step)
            if score is not None:
                step_scores[agent.agent_id] = score
        winners = compute_winners(step_scores)

        row_cells: list[Any] = [f"{step}"]

        for agent in ordered:
            score = agent.step_breakdown.get(step)
            if score is None:
                cell = Text(EM_DASH, style="dim")
            else:
                is_winner = agent.agent_id in winners
                color = _get_score_color(score)
                if is_winner:
                    cell = Text(
                        f"{score:.2f}",
                        style=f"bold {color}",
                    )
                else:
                    cell = Text(f"{score:.2f}", style=color)
            row_cells.append(cell)

        table.add_row(*row_cells)

    return table


def render_insights_demo(insights: dict[str, Any]) -> RenderableType:
    """Render enhanced insights panel with visual hierarchy."""
    lines: list[Text] = []

    # Overall leader with big visual
    leaders = sorted(insights.get("overall_leader", set()))
    if leaders:
        leader_str = ", ".join(leaders)
        leader_text = Text.assemble(
            Text(f"{ICONS['trophy']} Top Performer: ", style="bold bright_yellow"),
            Text(leader_str, style="bold bright_green"),
        )
        lines.append(leader_text)
        lines.append(Text(""))

    # Per-topic winners in a grid-like format
    per_topic = insights.get("per_topic_leaders", {})
    if per_topic:
        lines.append(Text(f"{ICONS['target']} Category Leaders:", style="bold bright_blue"))
        sorted_topics = sorted(per_topic.keys(), key=_topic_sort_key)
        for topic in sorted_topics:
            icon = TOPIC_ICONS.get(topic, ICONS["code"])
            topic_leaders = sorted(per_topic[topic])
            if topic_leaders:
                leader_str = ", ".join(topic_leaders)
                leader_line = Text.assemble(
                    Text(f"  {icon} {topic}: ", style="bold"),
                    Text(leader_str, style="bright_green"),
                )
                lines.append(leader_line)
        lines.append(Text(""))

    # Biggest spread with visual indicator
    spread_info = insights.get("biggest_spread")
    if spread_info:
        case_id = spread_info["case_id"]
        spread = spread_info["spread"]
        # Visual spread indicator
        spread_bar = "█" * int(spread * 20) + "░" * (20 - int(spread * 20))
        spread_text = Text.assemble(
            Text(f"{ICONS['warning']} Highest Variance: ", style="bold bright_red"),
            Text(f"{spread:.2f} on {case_id}\n", style=""),
            Text(f"  {spread_bar}", style="dim"),
        )
        lines.append(spread_text)

    content = Text("\n").join(lines)

    return Panel(
        content,
        title=f"[bold bright_blue]{ICONS['star']} Key Insights[/]",
        border_style="bright_blue",
        box=box.ROUNDED,
        padding=(1, 2),
    )


def render_topic_performance_chart(
    agents: list[AgentSummary],
    per_case_scores: dict[str, dict[str, float]],
    per_case_topics: dict[str, str],
) -> RenderableType:
    """Render a topic performance comparison chart."""
    ordered = order_agents(agents)
    agent_ids = [a.agent_id for a in ordered]

    grouped = group_cases_by_topic(per_case_scores, per_case_topics)

    if not grouped:
        return Panel("[dim]No topic data available[/]")

    # Compute average per topic per agent
    topic_chart = Table.grid(padding=1)
    topic_chart.add_column("Topic", min_width=20)
    for aid in agent_ids:
        short_name = aid[:12] + "..." if len(aid) > 12 else aid
        topic_chart.add_column(short_name, justify="center", min_width=12)

    sorted_topics = sorted(grouped.keys(), key=_topic_sort_key)
    for topic in sorted_topics:
        cases = grouped[topic]
        row = [f"{TOPIC_ICONS.get(topic, ICONS['code'])} {topic}"]

        for aid in agent_ids:
            scores = [s for cid, sc in cases for ag, s in sc.items() if ag == aid and s is not None]
            if scores:
                avg = sum(scores) / len(scores)
                color = _get_score_color(avg)
                filled = int(avg * 8)
                bar = "█" * filled + "░" * (8 - filled)
                row.append(f"[{color}]{bar} {avg:.2f}[/]")
            else:
                row.append(EM_DASH)

        topic_chart.add_row(*row)

    return Panel(
        topic_chart,
        title=f"[bold bright_cyan]{ICONS['chart']} Topic Performance Overview[/]",
        border_style="cyan",
        box=box.ROUNDED,
        padding=(1, 2),
    )


def render_full_demo_report(
    report: BenchmarkReport,
    console: Console,
    show_per_case: bool = True,
) -> None:
    """Render the complete demo-optimized benchmark report."""
    # Header
    console.print()
    console.print(render_demo_header())
    console.print()

    # Executive summary
    console.print(render_executive_summary(report.agents, report.case_count))
    console.print()

    # Main performance table
    console.print(render_summary_table_demo(report.agents))
    console.print()

    if show_per_case:
        # Topic performance chart
        console.print(
            render_topic_performance_chart(
                report.agents,
                report.per_case_scores,
                report.per_case_topics,
            )
        )
        console.print()

        # Per-topic tables
        topic_tables = render_per_topic_tables_demo(report, console.width)
        for table in topic_tables:
            console.print(table)
            console.print()

        # Step breakdown
        console.print(render_step_breakdown_demo(report.agents))
        console.print()

        # Insights
        insights = compute_insights(
            report.agents,
            report.per_case_scores,
            report.per_case_topics,
        )
        console.print(render_insights_demo(insights))
        console.print()

    # Footer
    console.print(
        Rule(
            f"[dim]AgentBench v0.1.0 • {report.case_count} cases evaluated • {len(report.agents)} agents[/]",
            style="dim",
        )
    )
    console.print()
