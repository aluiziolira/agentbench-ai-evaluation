"""Unit tests for AgentBench CLI."""

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from text for testing."""
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi_escape.sub("", text)


class TestVersionCommand:
    """Tests for the version command."""

    def test_version_shows_correct_version(self):
        """Test that version command displays correct version."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "AgentBench v0.1.0" in result.output

    def test_version_no_args_required(self):
        """Test that version command accepts no arguments."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0


class TestListCasesCommand:
    """Tests for the list-cases command."""

    def test_list_cases_with_valid_case_set(self, tmp_path):
        """Test listing cases with a valid case set."""
        # Create a temporary fixtures directory with manifest
        fixtures_dir = tmp_path / "fixtures"
        cases_dir = fixtures_dir / "cases"
        cases_dir.mkdir(parents=True)

        # Create manifest.json
        manifest = {
            "version": "1.0.0",
            "case_set_id": "pr_review_cases_v1",
            "cases": [
                {
                    "case_id": "pr_001",
                    "case_set_id": "pr_review_cases_v1",
                    "enabled": True,
                    "difficulty": "medium",
                    "tags": ["security", "authentication"],
                },
                {
                    "case_id": "pr_002",
                    "case_set_id": "pr_review_cases_v1",
                    "enabled": True,
                    "difficulty": "hard",
                    "tags": ["performance"],
                },
                {
                    "case_id": "pr_003",
                    "case_set_id": "pr_review_cases_v1",
                    "enabled": False,  # Disabled case
                    "difficulty": "easy",
                    "tags": ["documentation"],
                },
            ],
        }

        with open(fixtures_dir / "manifest.json", "w") as f:
            json.dump(manifest, f)

        # Create case directories with minimal required files
        for case_id in ["pr_001", "pr_002", "pr_003"]:
            case_dir = cases_dir / case_id
            case_dir.mkdir()
            (case_dir / "ticket.md").write_text("Test ticket")
            (case_dir / "diff.patch").write_text("Test diff")
            with open(case_dir / "ground_truth.json", "w") as f:
                json.dump({"expected_findings": [], "disallowed_findings": []}, f)
            with open(case_dir / "metadata.json", "w") as f:
                json.dump({"difficulty": "medium", "tags": []}, f)

        result = runner.invoke(
            app,
            ["list-cases", "--case-set", "pr_review_cases_v1", "--fixtures-dir", str(fixtures_dir)],
        )
        assert result.exit_code == 0
        assert "Case Set: pr_review_cases_v1" in result.output
        assert "Total Cases: 2" in result.output  # Only enabled cases
        assert "pr_001" in result.output
        assert "pr_002" in result.output
        assert "pr_003" not in result.output  # Disabled, shouldn't appear

    def test_list_cases_missing_manifest(self, tmp_path):
        """Test listing cases when manifest file is missing."""
        fixtures_dir = tmp_path / "nonexistent"

        result = runner.invoke(
            app,
            ["list-cases", "--case-set", "pr_review_cases_v1", "--fixtures-dir", str(fixtures_dir)],
        )
        assert result.exit_code == 1
        assert "Case set not found" in result.output

    def test_list_cases_wrong_case_set_id(self, tmp_path):
        """Test listing cases with mismatched case_set_id."""
        fixtures_dir = tmp_path / "fixtures"
        fixtures_dir.mkdir()

        # Create manifest with different case_set_id
        manifest = {
            "version": "1.0.0",
            "case_set_id": "different_case_set",  # Different from requested
            "cases": [],
        }

        with open(fixtures_dir / "manifest.json", "w") as f:
            json.dump(manifest, f)

        result = runner.invoke(
            app,
            ["list-cases", "--case-set", "pr_review_cases_v1", "--fixtures-dir", str(fixtures_dir)],
        )
        assert result.exit_code == 0
        assert "Total Cases: 0" in result.output


class TestSeedCommand:
    """Tests for the seed command."""

    @patch("agentbench.storage.mongo.MongoStorage")
    @patch("json.load")
    def test_seed_creates_workflow(self, mock_json_load, mock_mongo_class):
        """Test that seed command creates workflow when it exists."""
        # Setup mocks
        mock_mongo = AsyncMock()
        mock_mongo_class.return_value = mock_mongo
        mock_mongo.setup_indexes = AsyncMock()
        mock_mongo.create_workflow = AsyncMock()

        # Create temporary workflow file with all required fields
        workflow_data = {
            "workflow_id": "wf_pr_review_v1",
            "version": "1.0.0",
            "status": "published",
            "description": "Test workflow",
            "created_at": "2024-01-01T00:00:00Z",
            "steps": [
                {
                    "step_id": "s1_findings",
                    "order": 1,
                    "input": "ticket_and_diff",
                    "scoring": {
                        "strategy": "finding_match",
                        "rubric": "Test rubric",
                        "weight": 1.0,
                    },
                    "timeout_ms": 60000,
                }
            ],
        }
        mock_json_load.return_value = workflow_data

        with patch("cli.main.Path") as mock_path_class:
            # Mock the workflow file existence check
            mock_workflow_path = MagicMock()
            mock_workflow_path.exists.return_value = True

            # Mock file opening
            mock_file = MagicMock()
            mock_context = MagicMock()
            mock_context.__enter__ = MagicMock(return_value=mock_file)
            mock_context.__exit__ = MagicMock(return_value=False)
            mock_workflow_path.open.return_value = mock_context

            mock_path_class.side_effect = lambda x: (
                mock_workflow_path if x == "workflows/wf_pr_review_v1.json" else Path(x)
            )

            result = runner.invoke(app, ["seed", "--mongo-uri", "mongodb://test:27017"])
            assert result.exit_code == 0
            assert "Database seeded successfully" in result.output

    @patch("agentbench.storage.mongo.MongoStorage")
    @patch("json.load")
    def test_seed_handles_existing_workflow(self, mock_json_load, mock_mongo_class):
        """Test that seed command handles already-existing workflows gracefully."""
        # Setup mocks
        mock_mongo = AsyncMock()
        mock_mongo_class.return_value = mock_mongo
        mock_mongo.setup_indexes = AsyncMock()

        # Create workflow raises exception (already exists)
        mock_mongo.create_workflow = AsyncMock(side_effect=Exception("Workflow already exists"))

        workflow_data = {
            "workflow_id": "wf_pr_review_v1",
            "version": "1.0.0",
            "status": "published",
            "description": "Test workflow",
            "created_at": "2024-01-01T00:00:00Z",
            "steps": [
                {
                    "step_id": "s1_findings",
                    "order": 1,
                    "input": "ticket_and_diff",
                    "scoring": {
                        "strategy": "finding_match",
                        "rubric": "Test rubric",
                        "weight": 1.0,
                    },
                    "timeout_ms": 60000,
                }
            ],
        }
        mock_json_load.return_value = workflow_data

        with patch("cli.main.Path") as mock_path_class:
            # Mock the workflow file existence check
            mock_workflow_path = MagicMock()
            mock_workflow_path.exists.return_value = True

            # Mock file opening
            mock_file = MagicMock()
            mock_context = MagicMock()
            mock_context.__enter__ = MagicMock(return_value=mock_file)
            mock_context.__exit__ = MagicMock(return_value=False)
            mock_workflow_path.open.return_value = mock_context

            mock_path_class.side_effect = lambda x: (
                mock_workflow_path if x == "workflows/wf_pr_review_v1.json" else Path(x)
            )

            result = runner.invoke(app, ["seed", "--mongo-uri", "mongodb://test:27017"])
            assert result.exit_code == 0
            assert "Workflow may already exist" in result.output
            assert "Database seeded successfully" in result.output

    @patch("agentbench.storage.mongo.MongoStorage")
    def test_seed_skips_if_no_workflow_file(self, mock_mongo_class):
        """Test that seed command skips workflow creation if file doesn't exist."""
        # Setup mocks
        mock_mongo = AsyncMock()
        mock_mongo_class.return_value = mock_mongo
        mock_mongo.setup_indexes = AsyncMock()

        with patch("cli.main.Path") as mock_path_class:
            # Mock the workflow file doesn't exist
            mock_workflow_path = MagicMock()
            mock_workflow_path.exists.return_value = False

            mock_path_class.side_effect = lambda x: (
                mock_workflow_path if x == "workflows/wf_pr_review_v1.json" else Path(x)
            )

            result = runner.invoke(app, ["seed", "--mongo-uri", "mongodb://test:27017"])
            assert result.exit_code == 0
            assert "Database seeded successfully" in result.output
            # create_workflow should not be called
            mock_mongo.create_workflow.assert_not_called()


class TestRunCommand:
    """Tests for the run command."""

    @patch("httpx.post")
    def test_run_creates_benchmark(self, mock_post):
        """Test that run command creates a benchmark."""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {"benchmark_id": "bench-123"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = runner.invoke(
            app,
            [
                "run",
                "--workflow",
                "wf_pr_review_v1",
                "--case-set",
                "pr_review_cases_v1",
                "--agents",
                "gpt-4o-mini",
                "--agents",
                "claude-haiku-4-5",
            ],
        )
        assert result.exit_code == 0
        assert "Starting benchmark" in result.output
        assert "wf_pr_review_v1" in result.output
        assert "pr_review_cases_v1" in result.output
        assert "gpt-4o-mini" in result.output
        assert "claude-haiku-4-5" in result.output
        assert "Benchmark started: bench-123" in result.output

    @patch("httpx.post")
    def test_run_handles_api_error(self, mock_post):
        """Test that run command handles API errors gracefully."""
        # Setup mock to raise exception
        mock_post.side_effect = Exception("Connection refused")

        result = runner.invoke(
            app,
            [
                "run",
                "--workflow",
                "wf_pr_review_v1",
                "--case-set",
                "pr_review_cases_v1",
                "--agents",
                "gpt-4o-mini",
            ],
        )
        assert result.exit_code == 1
        assert "Error: Connection refused" in result.output


class TestReportCommand:
    """Tests for the report command."""

    @patch("httpx.get")
    def test_report_shows_completed_benchmark(self, mock_get):
        """Test that report command displays completed benchmark."""
        # Setup mock response for completed benchmark
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "benchmark_id": "bench-123",
            "workflow_id": "wf_pr_review_v1",
            "case_count": 5,
            "status": "completed",
            "agents": [
                {"agent_id": "gpt-4o-mini", "avg_score": 0.85, "p50_latency_ms": 1200},
                {"agent_id": "claude-haiku-4-5", "avg_score": 0.82, "p50_latency_ms": 1100},
            ],
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = runner.invoke(app, ["report", "bench-123"])
        assert result.exit_code == 0
        assert "Fetching report for bench-123" in result.output
        assert "Benchmark Complete" in result.output
        assert "wf_pr_review_v1" in result.output
        assert "gpt-4o-mini" in result.output
        assert "claude-haiku-4-5" in result.output
        assert "0.85" in result.output
        assert "0.82" in result.output

    @patch("httpx.get")
    def test_report_in_progress_no_watch(self, mock_get):
        """Test that report command shows in-progress status without watch."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"benchmark_id": "bench-123", "status": "in_progress"}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = runner.invoke(app, ["report", "bench-123"])
        assert result.exit_code == 0
        assert "Benchmark in progress" in result.output
        assert "Use --watch to wait for completion" in result.output

    @patch("cli.main.time.sleep")
    @patch("httpx.get")
    def test_report_watch_waits_for_completion(self, mock_get, mock_sleep):
        """Test that report --watch waits for benchmark completion."""
        # First call returns in_progress, second returns completed
        mock_response_in_progress = MagicMock()
        mock_response_in_progress.json.return_value = {
            "benchmark_id": "bench-123",
            "status": "in_progress",
        }
        mock_response_in_progress.raise_for_status = MagicMock()

        mock_response_completed = MagicMock()
        mock_response_completed.json.return_value = {
            "benchmark_id": "bench-123",
            "workflow_id": "wf_pr_review_v1",
            "case_count": 5,
            "status": "completed",
            "agents": [],
        }
        mock_response_completed.raise_for_status = MagicMock()

        mock_get.side_effect = [mock_response_in_progress, mock_response_completed]

        result = runner.invoke(app, ["report", "bench-123", "--watch"])
        assert result.exit_code == 0
        assert "Benchmark Complete" in result.output
        mock_sleep.assert_called_once_with(5)


class TestRescoreCommand:
    """Tests for the rescore command."""

    def test_rescore_shows_message(self):
        """Test that rescore command shows appropriate message."""
        result = runner.invoke(
            app,
            [
                "rescore",
                "--run-id",
                "run-123",
                "--step",
                "s1_findings",
                "--strategy",
                "llm_judge",
                "--rubric",
                "Test rubric",
            ],
        )
        assert result.exit_code == 0
        assert "Re-scoring run run-123, step s1_findings" in result.output
        assert "Strategy: llm_judge" in result.output
        assert "Rubric: Test rubric" in result.output
        assert "Re-scoring not yet fully implemented" in result.output

    def test_rescore_without_rubric(self):
        """Test that rescore command works without optional rubric."""
        result = runner.invoke(
            app,
            [
                "rescore",
                "--run-id",
                "run-123",
                "--step",
                "s1_findings",
                "--strategy",
                "finding_match",
            ],
        )
        assert result.exit_code == 0
        assert "Strategy: finding_match" in result.output
        # No rubric should be printed
        assert "Rubric:" not in result.output


class TestCLIHelp:
    """Tests for CLI help and general functionality."""

    def test_main_help(self):
        """Test that main help shows all commands."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "AgentBench - AI Agent Evaluation Framework" in result.output
        assert "run" in result.output
        assert "report" in result.output
        assert "list-cases" in result.output
        assert "seed" in result.output
        assert "rescore" in result.output
        assert "version" in result.output

    def test_run_help(self):
        """Test that run command help shows options."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "--workflow" in output
        assert "--case-set" in output
        assert "--agents" in output
        assert "--api-url" in output

    def test_report_help(self):
        """Test that report command help shows options."""
        result = runner.invoke(app, ["report", "--help"])
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "BENCHMARK_ID" in output
        assert "--watch" in output

    def test_list_cases_help(self):
        """Test that list-cases command help shows options."""
        result = runner.invoke(app, ["list-cases", "--help"])
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "--case-set" in output
        assert "--fixtures-dir" in output
