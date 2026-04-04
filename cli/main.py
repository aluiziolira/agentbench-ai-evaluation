"""CLI entry point for AgentBench."""

import typer
import structlog

logger = structlog.get_logger()
app = typer.Typer(help="AgentBench - AI evaluation framework")


@app.command()
def version():
    """Show version information."""
    typer.echo("AgentBench 0.1.0")


@app.command()
def run(
    workflow: str = typer.Option(..., "--workflow", "-w", help="Workflow to run"),
    case: str = typer.Option(..., "--case", "-c", help="Case to evaluate"),
):
    """Run an evaluation workflow."""
    logger.info("cli.run", workflow=workflow, case=case)
    typer.echo(f"Running workflow: {workflow} with case: {case}")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind to"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind to"),
):
    """Start the API server."""
    import uvicorn
    from agentbench.main import app

    logger.info("cli.serve", host=host, port=port)
    uvicorn.run(app, host=host, port=port)


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
