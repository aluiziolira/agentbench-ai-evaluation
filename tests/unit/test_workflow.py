"""Tests for workflow definition validation.

Validates that workflow JSON files conform to the WorkflowDefinition model.
"""

import json
from datetime import datetime
from pathlib import Path

from agentbench.models import WorkflowDefinition

WORKFLOWS_DIR = Path(__file__).parent.parent.parent / "workflows"


class TestWorkflowValidation:
    """Tests that workflow definitions validate against the model."""

    def test_wf_pr_review_v1_json_exists(self) -> None:
        """Test that the workflow JSON file exists."""
        workflow_path = WORKFLOWS_DIR / "wf_pr_review_v1.json"
        assert workflow_path.exists(), f"Workflow file not found: {workflow_path}"

    def test_wf_pr_review_v1_validates_against_model(self) -> None:
        """Test that wf_pr_review_v1.json validates against WorkflowDefinition."""
        workflow_path = WORKFLOWS_DIR / "wf_pr_review_v1.json"

        with open(workflow_path) as f:
            data = json.load(f)

        # Should validate without raising
        workflow = WorkflowDefinition.model_validate(data)

        # Verify core properties
        assert workflow.workflow_id == "wf_pr_review_v1"
        assert workflow.version == "1.0.0"
        assert workflow.status == "published"
        assert workflow.scoring_aggregation == "weighted_average"

    def test_wf_pr_review_v1_has_exactly_two_steps(self) -> None:
        """Test that workflow has exactly two steps."""
        workflow_path = WORKFLOWS_DIR / "wf_pr_review_v1.json"

        with open(workflow_path) as f:
            data = json.load(f)

        workflow = WorkflowDefinition.model_validate(data)

        assert len(workflow.steps) == 2, "Workflow must have exactly 2 steps"

    def test_wf_pr_review_v1_step_order(self) -> None:
        """Test that steps are in correct order."""
        workflow_path = WORKFLOWS_DIR / "wf_pr_review_v1.json"

        with open(workflow_path) as f:
            data = json.load(f)

        workflow = WorkflowDefinition.model_validate(data)

        # Steps should be ordered by order field
        assert workflow.steps[0].order == 0
        assert workflow.steps[1].order == 1

    def test_wf_pr_review_v1_step_ids_match_spec(self) -> None:
        """Test that step IDs match the spec requirements."""
        workflow_path = WORKFLOWS_DIR / "wf_pr_review_v1.json"

        with open(workflow_path) as f:
            data = json.load(f)

        workflow = WorkflowDefinition.model_validate(data)

        step_ids = [step.step_id for step in workflow.steps]
        assert "s1_findings" in step_ids, "Missing s1_findings step"
        assert "s2_review_summary" in step_ids, "Missing s2_review_summary step"

    def test_wf_pr_review_v1_step_1_configuration(self) -> None:
        """Test that step 1 (s1_findings) is configured correctly."""
        workflow_path = WORKFLOWS_DIR / "wf_pr_review_v1.json"

        with open(workflow_path) as f:
            data = json.load(f)

        workflow = WorkflowDefinition.model_validate(data)

        # Find s1_findings step
        step1 = next(s for s in workflow.steps if s.step_id == "s1_findings")

        assert step1.timeout_ms == 15000
        assert step1.scoring.strategy == "finding_match"
        assert step1.scoring.weight == 2.0
        assert step1.scoring.rubric is None

        # Verify required placeholders are present in the prompt
        assert "{ticket_text}" in step1.input
        assert "{diff_patch}" in step1.input

    def test_wf_pr_review_v1_step_2_configuration(self) -> None:
        """Test that step 2 (s2_review_summary) is configured correctly."""
        workflow_path = WORKFLOWS_DIR / "wf_pr_review_v1.json"

        with open(workflow_path) as f:
            data = json.load(f)

        workflow = WorkflowDefinition.model_validate(data)

        # Find s2_review_summary step
        step2 = next(s for s in workflow.steps if s.step_id == "s2_review_summary")

        assert step2.timeout_ms == 15000
        assert step2.scoring.strategy == "llm_judge"
        assert step2.scoring.weight == 1.0
        assert step2.scoring.rubric is not None
        assert "Prioritizes the most important issue first" in step2.scoring.rubric

        # Verify required placeholders are present in the prompt
        assert "{ticket_text}" in step2.input
        assert "{diff_patch}" in step2.input

    def test_wf_pr_review_v1_has_valid_timestamps(self) -> None:
        """Test that created_at and published_at are valid ISO-8601 timestamps."""
        workflow_path = WORKFLOWS_DIR / "wf_pr_review_v1.json"

        with open(workflow_path) as f:
            data = json.load(f)

        workflow = WorkflowDefinition.model_validate(data)

        # Should be able to parse as datetime
        created = datetime.fromisoformat(workflow.created_at)
        assert created.tzinfo is not None, "created_at must have timezone"

        assert workflow.published_at is not None
        published = datetime.fromisoformat(workflow.published_at)
        assert published.tzinfo is not None, "published_at must have timezone"

    def test_wf_pr_review_v1_json_roundtrip(self) -> None:
        """Test that workflow can be serialized and deserialized."""
        workflow_path = WORKFLOWS_DIR / "wf_pr_review_v1.json"

        with open(workflow_path) as f:
            original_data = json.load(f)

        workflow = WorkflowDefinition.model_validate(original_data)

        # Serialize back to dict
        serialized = workflow.model_dump()

        # Key fields should match
        assert serialized["workflow_id"] == original_data["workflow_id"]
        assert serialized["version"] == original_data["version"]
        assert serialized["status"] == original_data["status"]
        assert len(serialized["steps"]) == len(original_data["steps"])

    def test_wf_pr_review_v1_step_1_prompt_content(self) -> None:
        """Test that step 1 prompt matches the spec template."""
        workflow_path = WORKFLOWS_DIR / "wf_pr_review_v1.json"

        with open(workflow_path) as f:
            data = json.load(f)

        workflow = WorkflowDefinition.model_validate(data)
        step1 = next(s for s in workflow.steps if s.step_id == "s1_findings")

        # Verify key phrases from the spec prompt are present
        assert "You are reviewing a pull request as a senior software engineer" in step1.input
        assert "Return JSON only with this schema" in step1.input
        assert '"findings":' in step1.input
        assert "canonical_label" in step1.input
        assert "Return at most 5 findings" in step1.input
        assert "Do not include style nits" in step1.input

    def test_wf_pr_review_v1_step_2_prompt_content(self) -> None:
        """Test that step 2 prompt matches the spec template."""
        workflow_path = WORKFLOWS_DIR / "wf_pr_review_v1.json"

        with open(workflow_path) as f:
            data = json.load(f)

        workflow = WorkflowDefinition.model_validate(data)
        step2 = next(s for s in workflow.steps if s.step_id == "s2_review_summary")

        # Verify key phrases from the spec prompt are present
        assert "You are writing the final PR review summary" in step2.input
        assert "Write a concise review summary for the PR author" in step2.input
        assert "4 to 8 lines total" in step2.input
        assert "prioritize the most important issue first" in step2.input
        assert "no praise, no filler" in step2.input
