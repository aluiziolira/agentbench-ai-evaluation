"""AgentBench CLI - Operator interface for benchmark management."""

import asyncio
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from agentbench.cases.loader import list_enabled_cases, load_manifest

app = typer.Typer(help="AgentBench - AI Agent Evaluation Framework")
console = Console()


@app.command()
def run(
    workflow: str = typer.Option("wf_pr_review_v1", "--workflow", "-w", help="Workflow ID"),
    case_set: str = typer.Option("pr_review_cases_v1", "--case-set", "-c", help="Case set ID"),
    agents: list[str] = typer.Option(  # noqa: B008
        ["gpt-4o-mini", "claude-haiku-4-5"], "--agents", "-a", help="Agent IDs"
    ),
    api_url: str = typer.Option("http://localhost:8000", "--api-url", help="API URL"),
) -> None:
    import uuid

    import httpx

    benchmark_id = str(uuid.uuid4())

    console.print(f"[bold blue]Starting benchmark {benchmark_id}...[/]")
    console.print(f"  Workflow: {workflow}")
    console.print(f"  Case Set: {case_set}")
    console.print(f"  Agents: {', '.join(agents)}")

    try:
        response = httpx.post(
            f"{api_url}/benchmarks",
            json={
                "workflow_id": workflow,
                "case_set_id": case_set,
                "agents": agents,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        result = response.json()
        console.print(f"[bold green]Benchmark started: {result['benchmark_id']}[/]")
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/]")
        raise typer.Exit(1) from None


@app.command()
def report(
    benchmark_id: str = typer.Argument(..., help="Benchmark ID"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Watch for completion"),
    api_url: str = typer.Option("http://localhost:8000", "--api-url", help="API URL"),
) -> None:
    """Get benchmark report."""
    import httpx

    console.print(f"[bold blue]Fetching report for {benchmark_id}...[/]")

    while True:
        try:
            response = httpx.get(
                f"{api_url}/benchmarks/{benchmark_id}",
                timeout=10.0,
            )
            response.raise_for_status()
            result = response.json()

            if result.get("status") == "in_progress":
                console.print("[yellow]Benchmark in progress...[/]")
                if not watch:
                    console.print("Use --watch to wait for completion")
                    break
                time.sleep(5)
                continue

            # Display report
            console.print("[bold green]Benchmark Complete![/]")
            console.print(f"Workflow: {result.get('workflow_id')}")
            console.print(f"Case Count: {result.get('case_count')}")

            # Agent summaries
            if result.get("agents"):
                table = Table(title="Agent Performance")
                table.add_column("Agent", style="cyan")
                table.add_column("Avg Score", style="green")
                table.add_column("P50 Latency", style="yellow")

                for agent in result["agents"]:
                    table.add_row(
                        agent["agent_id"],
                        f"{agent['avg_score']:.2f}",
                        f"{agent['p50_latency_ms']}ms",
                    )
                console.print(table)

            break

        except Exception as e:
            console.print(f"[bold red]Error: {e}[/]")
        raise typer.Exit(1) from None


@app.command()
def list_cases(
    case_set: str = typer.Option("pr_review_cases_v1", "--case-set", "-c", help="Case set ID"),
    fixtures_dir: Path = typer.Option(  # noqa: B008
        Path("fixtures/pr_review"), "--fixtures-dir", help="Fixtures directory"
    ),
) -> None:
    """List available cases in a case set."""
    try:
        manifest = load_manifest(fixtures_dir / "manifest.json")
        enabled_cases = list_enabled_cases(manifest, case_set)

        console.print(f"[bold blue]Case Set: {case_set}[/]")
        console.print(f"Version: {manifest.version}")
        console.print(f"Total Cases: {len(enabled_cases)}\n")

        table = Table(title="Enabled Cases")
        table.add_column("Case ID", style="cyan")
        table.add_column("Difficulty", style="yellow")
        table.add_column("Tags", style="green")

        for case in enabled_cases:
            table.add_row(
                case.case_id,
                case.difficulty,
                ", ".join(case.tags),
            )

        console.print(table)

    except FileNotFoundError:
        console.print(f"[bold red]Case set not found: {case_set}[/]")
        raise typer.Exit(1) from None
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/]")
        raise typer.Exit(1) from None


@app.command()
def seed(
    mongo_uri: str = typer.Option("mongodb://localhost:27017", "--mongo-uri", help="MongoDB URI"),
    fixtures_dir: Path = typer.Option(  # noqa: B008
        Path("fixtures/pr_review"), "--fixtures-dir", help="Fixtures directory"
    ),
) -> None:
    """Seed the database with initial data."""
    import json

    from agentbench.models import WorkflowDefinition
    from agentbench.storage.mongo import MongoStorage

    async def do_seed() -> None:
        mongo = MongoStorage(mongo_uri, "agentbench")
        await mongo.setup_indexes()

        # Load and register workflow
        workflow_path = Path("workflows/wf_pr_review_v1.json")
        if workflow_path.exists():
            with open(workflow_path) as f:
                workflow_data = json.load(f)

            workflow = WorkflowDefinition(**workflow_data)

            try:
                await mongo.create_workflow(workflow)
                console.print(f"[green]Created workflow: {workflow.workflow_id}[/]")
            except Exception as e:
                console.print(f"[yellow]Workflow may already exist: {e}[/]")

        console.print("[bold green]Database seeded successfully![/]")

    asyncio.run(do_seed())


@app.command()
def rescore(
    run_id: str = typer.Option(..., "--run-id", help="Run ID"),
    step: str = typer.Option(..., "--step", help="Step ID"),
    strategy: str = typer.Option(..., "--strategy", help="Scoring strategy"),
    rubric: str | None = typer.Option(None, "--rubric", help="Scoring rubric"),
) -> None:
    """Re-score a step with different parameters."""
    console.print(f"[bold blue]Re-scoring run {run_id}, step {step}...[/]")
    console.print(f"Strategy: {strategy}")
    if rubric:
        console.print(f"Rubric: {rubric}")

    # Implementation would load raw I/O and re-score
    console.print("[yellow]Re-scoring not yet fully implemented[/]")


@app.command()
def version() -> None:
    """Show version information."""
    console.print("AgentBench v0.1.0")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind to"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind to"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload for development"),
) -> None:
    """Start the AgentBench API server."""
    import uvicorn

    from agentbench.api.app import app as api_app

    console.print(f"[bold blue]Starting AgentBench API server on {host}:{port}...[/]")
    uvicorn.run(api_app, host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
