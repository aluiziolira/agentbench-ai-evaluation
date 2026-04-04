"""Fixture Loader for AgentBench Cases.

This module provides functions to load case manifests and review case definitions
from local filesystem fixtures. All loading is local and file-based only.

Functions:
    load_manifest: Load and validate a CaseSetManifest from manifest.json
    list_enabled_cases: Filter manifest entries to return only enabled cases
    load_case: Load a single ReviewCaseDefinition from fixture files
    load_case_set: Load all enabled cases for a case set
"""

import json
from pathlib import Path

from pydantic import ValidationError

from agentbench.cases.models import (
    CaseManifestEntry,
    CaseSetManifest,
    DisallowedFinding,
    ReviewCaseDefinition,
    ReviewFindingTruth,
)


def load_manifest(manifest_path: Path) -> CaseSetManifest:
    """Load and validate a CaseSetManifest from a manifest.json file.

    Args:
        manifest_path: Path to the manifest.json file

    Returns:
        Parsed and validated CaseSetManifest instance

    Raises:
        FileNotFoundError: If the manifest file does not exist
        ValueError: If the JSON is malformed or fails validation against
            the CaseSetManifest model
    """
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")

    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest path is not a file: {manifest_path}")

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed JSON in manifest file {manifest_path}: {e}") from e
    except IOError as e:
        raise ValueError(f"Failed to read manifest file {manifest_path}: {e}") from e

    try:
        manifest = CaseSetManifest.model_validate(raw_data)
    except ValidationError as e:
        raise ValueError(f"Invalid manifest data in {manifest_path}: {e}") from e

    return manifest


def list_enabled_cases(
    manifest: CaseSetManifest,
    case_set_id: str | None = None,
) -> list[CaseManifestEntry]:
    """Return only enabled cases from the manifest, optionally filtered by case_set_id.

    Args:
        manifest: The CaseSetManifest to filter
        case_set_id: Optional case_set_id to match against. If provided,
            also filters cases where manifest.case_set_id matches.
            Defaults to None (no case_set_id filtering).

    Returns:
        List of enabled CaseManifestEntry instances matching the criteria
    """
    # If case_set_id is provided, verify manifest matches
    if case_set_id is not None and manifest.case_set_id != case_set_id:
        return []

    return [case for case in manifest.cases if case.enabled]


def load_case(case_id: str, fixtures_dir: Path) -> ReviewCaseDefinition:
    """Load a single ReviewCaseDefinition from fixture files.

    Loads case data from the following files in fixtures_dir/cases/{case_id}/:
        - ticket.md: The ticket/PR description text
        - diff.patch: The unified diff representing the code change
        - ground_truth.json: Expected findings and disallowed findings
        - metadata.json: Case metadata (difficulty, tags, etc.)

    Args:
        case_id: Unique identifier for the case (e.g., "pr_001_missing_auth_check")
        fixtures_dir: Path to the fixtures directory containing cases/ subdirectory

    Returns:
        Fully populated ReviewCaseDefinition instance

    Raises:
        FileNotFoundError: If any required fixture file is missing
        ValueError: If any fixture file is malformed or fails validation
    """
    case_dir = fixtures_dir / "cases" / case_id

    if not case_dir.exists():
        raise FileNotFoundError(f"Case directory not found: {case_dir}")

    if not case_dir.is_dir():
        raise FileNotFoundError(f"Case path is not a directory: {case_dir}")

    # Required file paths
    ticket_path = case_dir / "ticket.md"
    diff_path = case_dir / "diff.patch"
    ground_truth_path = case_dir / "ground_truth.json"
    metadata_path = case_dir / "metadata.json"

    # Read ticket.md
    if not ticket_path.exists():
        raise FileNotFoundError(f"Ticket file not found: {ticket_path}")
    try:
        ticket_text = ticket_path.read_text(encoding="utf-8")
    except IOError as e:
        raise ValueError(f"Failed to read ticket file {ticket_path}: {e}") from e

    # Read diff.patch
    if not diff_path.exists():
        raise FileNotFoundError(f"Diff file not found: {diff_path}")
    try:
        diff_patch = diff_path.read_text(encoding="utf-8")
    except IOError as e:
        raise ValueError(f"Failed to read diff file {diff_path}: {e}") from e

    # Read and parse ground_truth.json
    if not ground_truth_path.exists():
        raise FileNotFoundError(f"Ground truth file not found: {ground_truth_path}")
    try:
        with open(ground_truth_path, "r", encoding="utf-8") as f:
            ground_truth_data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed JSON in ground truth file {ground_truth_path}: {e}") from e
    except IOError as e:
        raise ValueError(f"Failed to read ground truth file {ground_truth_path}: {e}") from e

    # Parse expected_findings
    try:
        expected_findings_raw = ground_truth_data.get("expected_findings", [])
        expected_findings = [ReviewFindingTruth.model_validate(f) for f in expected_findings_raw]
    except ValidationError as e:
        raise ValueError(f"Invalid expected_findings in {ground_truth_path}: {e}") from e
    except Exception as e:
        raise ValueError(f"Failed to parse expected_findings in {ground_truth_path}: {e}") from e

    # Parse disallowed_findings (optional, defaults to empty list)
    try:
        disallowed_findings_raw = ground_truth_data.get("disallowed_findings", [])
        disallowed_findings = [DisallowedFinding.model_validate(f) for f in disallowed_findings_raw]
    except ValidationError as e:
        raise ValueError(f"Invalid disallowed_findings in {ground_truth_path}: {e}") from e
    except Exception as e:
        raise ValueError(f"Failed to parse disallowed_findings in {ground_truth_path}: {e}") from e

    # Read and parse metadata.json
    if not metadata_path.exists():
        raise FileNotFoundError(f"Metadata file not found: {metadata_path}")
    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed JSON in metadata file {metadata_path}: {e}") from e
    except IOError as e:
        raise ValueError(f"Failed to read metadata file {metadata_path}: {e}") from e

    # Extract case_set_id from metadata or infer from fixtures_dir
    case_set_id = metadata.get("case_set_id", "unknown")

    # Extract difficulty from metadata
    difficulty = metadata.get("difficulty", "medium")
    if difficulty not in ("easy", "medium", "hard"):
        raise ValueError(
            f"Invalid difficulty '{difficulty}' in {metadata_path}. "
            "Must be one of: easy, medium, hard"
        )

    # Extract tags from metadata
    tags = metadata.get("tags", [])
    if not isinstance(tags, list):
        raise ValueError(f"Invalid tags in {metadata_path}: must be a list")

    # Construct the ReviewCaseDefinition
    try:
        case = ReviewCaseDefinition(
            case_id=case_id,
            case_set_id=case_set_id,
            difficulty=difficulty,  # type: ignore[arg-type]
            tags=tags,
            ticket_text=ticket_text,
            diff_patch=diff_patch,
            expected_findings=expected_findings,
            disallowed_findings=disallowed_findings,
        )
    except ValidationError as e:
        raise ValueError(f"Failed to create ReviewCaseDefinition for {case_id}: {e}") from e

    return case


def load_case_set(case_set_id: str, fixtures_dir: Path) -> list[ReviewCaseDefinition]:
    """Load all enabled cases for a case set.

    This is a convenience function that:
    1. Loads the manifest from fixtures_dir/manifest.json
    2. Filters enabled cases matching case_set_id
    3. Loads each case and returns as a list

    Args:
        case_set_id: The case set ID to load (e.g., "pr_review_cases_v1")
        fixtures_dir: Path to the fixtures directory containing manifest.json
            and cases/ subdirectory

    Returns:
        List of fully populated ReviewCaseDefinition instances for all
        enabled cases in the set

    Raises:
        FileNotFoundError: If manifest file or any case directory is missing
        ValueError: If manifest or any case fixture is malformed
    """
    manifest_path = fixtures_dir / "manifest.json"

    # Load and validate the manifest
    manifest = load_manifest(manifest_path)

    # Filter enabled cases for this case_set_id
    enabled_entries = list_enabled_cases(manifest, case_set_id=case_set_id)

    # Load each case
    cases: list[ReviewCaseDefinition] = []
    for entry in enabled_entries:
        case = load_case(entry.case_id, fixtures_dir)
        cases.append(case)

    return cases
