"""Unit tests for the case loader module.

Validates manifest loading, case loading, and error handling for the
fixture-based case loading system.
"""

import json
from pathlib import Path

import pytest

from agentbench.cases.loader import (
    list_enabled_cases,
    load_case,
    load_case_set,
    load_manifest,
    resolve_case_topic,
)
from agentbench.cases.models import (
    CaseManifestEntry,
    CaseSetManifest,
    ReviewCaseDefinition,
)


class TestLoadManifest:
    """Tests for the load_manifest function."""

    def test_load_valid_manifest(self, tmp_path: Path) -> None:
        """Should successfully load and parse a valid manifest file."""
        manifest_data = {
            "case_set_id": "pr_review_cases_v1",
            "version": "1.0.0",
            "cases": [
                {
                    "case_id": "pr_001_missing_auth_check",
                    "difficulty": "medium",
                    "enabled": True,
                    "tags": ["auth", "api", "tests"],
                },
                {
                    "case_id": "pr_002_missing_test_coverage",
                    "difficulty": "easy",
                    "enabled": True,
                    "tags": ["tests"],
                },
            ],
        }

        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_data))

        manifest = load_manifest(manifest_path)

        assert isinstance(manifest, CaseSetManifest)
        assert manifest.case_set_id == "pr_review_cases_v1"
        assert manifest.version == "1.0.0"
        assert len(manifest.cases) == 2
        assert manifest.cases[0].case_id == "pr_001_missing_auth_check"
        assert manifest.cases[1].case_id == "pr_002_missing_test_coverage"

    def test_manifest_missing_file(self, tmp_path: Path) -> None:
        """Should raise FileNotFoundError for non-existent manifest."""
        manifest_path = tmp_path / "nonexistent_manifest.json"

        with pytest.raises(FileNotFoundError) as exc_info:
            load_manifest(manifest_path)

        assert "not found" in str(exc_info.value).lower()

    def test_manifest_not_a_file(self, tmp_path: Path) -> None:
        """Should raise FileNotFoundError if manifest path is a directory."""
        manifest_path = tmp_path / "manifest_dir"
        manifest_path.mkdir()

        with pytest.raises(FileNotFoundError) as exc_info:
            load_manifest(manifest_path)

        assert "not a file" in str(exc_info.value).lower()

    def test_manifest_malformed_json(self, tmp_path: Path) -> None:
        """Should raise ValueError for malformed JSON."""
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text("{invalid json content")

        with pytest.raises(ValueError) as exc_info:
            load_manifest(manifest_path)

        assert "malformed json" in str(exc_info.value).lower()

    def test_manifest_missing_required_field(self, tmp_path: Path) -> None:
        """Should raise ValueError for manifest missing required fields."""
        manifest_data = {
            "case_set_id": "pr_review_cases_v1",
            # Missing 'version' and 'cases'
        }

        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_data))

        with pytest.raises(ValueError) as exc_info:
            load_manifest(manifest_path)

        assert "invalid manifest" in str(exc_info.value).lower()

    def test_manifest_invalid_case_entry(self, tmp_path: Path) -> None:
        """Should raise ValueError for invalid case entry in manifest."""
        manifest_data = {
            "case_set_id": "pr_review_cases_v1",
            "version": "1.0.0",
            "cases": [
                {
                    "case_id": "pr_001",
                    "difficulty": "invalid_difficulty",  # Invalid value
                    "enabled": True,
                }
            ],
        }

        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_data))

        with pytest.raises(ValueError) as exc_info:
            load_manifest(manifest_path)

        assert "invalid manifest" in str(exc_info.value).lower()


class TestListEnabledCases:
    """Tests for the list_enabled_cases function."""

    def test_list_all_enabled_cases(self) -> None:
        """Should return all enabled cases from manifest."""
        manifest = CaseSetManifest(
            case_set_id="pr_review_cases_v1",
            version="1.0.0",
            cases=[
                CaseManifestEntry(case_id="pr_001", difficulty="easy", enabled=True, tags=["auth"]),
                CaseManifestEntry(
                    case_id="pr_002", difficulty="medium", enabled=True, tags=["tests"]
                ),
                CaseManifestEntry(
                    case_id="pr_003", difficulty="hard", enabled=False, tags=["perf"]
                ),
            ],
        )

        enabled = list_enabled_cases(manifest)

        assert len(enabled) == 2
        assert enabled[0].case_id == "pr_001"
        assert enabled[1].case_id == "pr_002"

    def test_list_enabled_with_case_set_id_match(self) -> None:
        """Should return enabled cases when case_set_id matches."""
        manifest = CaseSetManifest(
            case_set_id="pr_review_cases_v1",
            version="1.0.0",
            cases=[
                CaseManifestEntry(case_id="pr_001", difficulty="easy", enabled=True, tags=["auth"]),
                CaseManifestEntry(case_id="pr_002", difficulty="medium", enabled=False, tags=[]),
            ],
        )

        enabled = list_enabled_cases(manifest, case_set_id="pr_review_cases_v1")

        assert len(enabled) == 1
        assert enabled[0].case_id == "pr_001"

    def test_list_enabled_with_case_set_id_mismatch(self) -> None:
        """Should return empty list when case_set_id doesn't match."""
        manifest = CaseSetManifest(
            case_set_id="pr_review_cases_v1",
            version="1.0.0",
            cases=[
                CaseManifestEntry(case_id="pr_001", difficulty="easy", enabled=True, tags=[]),
            ],
        )

        enabled = list_enabled_cases(manifest, case_set_id="other_case_set")

        assert len(enabled) == 0

    def test_list_enabled_all_disabled(self) -> None:
        """Should return empty list when all cases are disabled."""
        manifest = CaseSetManifest(
            case_set_id="pr_review_cases_v1",
            version="1.0.0",
            cases=[
                CaseManifestEntry(case_id="pr_001", difficulty="easy", enabled=False, tags=[]),
                CaseManifestEntry(case_id="pr_002", difficulty="medium", enabled=False, tags=[]),
            ],
        )

        enabled = list_enabled_cases(manifest)

        assert len(enabled) == 0

    def test_list_enabled_empty_cases(self) -> None:
        """Should handle empty cases list."""
        manifest = CaseSetManifest(
            case_set_id="pr_review_cases_v1",
            version="1.0.0",
            cases=[],
        )

        enabled = list_enabled_cases(manifest)

        assert len(enabled) == 0


class TestLoadCase:
    """Tests for the load_case function."""

    def create_valid_case_fixtures(
        self, case_dir: Path, case_set_id: str = "pr_review_cases_v1"
    ) -> None:
        """Helper to create valid fixture files for a case."""
        # ticket.md
        (case_dir / "ticket.md").write_text(
            "# Add admin endpoint\n\nThis PR adds an admin endpoint for user management."
        )

        # diff.patch
        (case_dir / "diff.patch").write_text(
            "--- a/app/api/admin.py\n+++ b/app/api/admin.py\n@@ -10,5 +10,10 @@\n"
        )

        # ground_truth.json
        ground_truth = {
            "expected_findings": [
                {
                    "finding_id": "F1",
                    "canonical_label": "missing_permission_check",
                    "severity": "high",
                    "file_path": "app/api/admin.py",
                    "line_span": [42, 57],
                    "must_detect": True,
                    "summary": "The endpoint no longer enforces the admin permission check.",
                }
            ],
            "disallowed_findings": [{"canonical_label": "style_only_nit"}],
        }
        (case_dir / "ground_truth.json").write_text(json.dumps(ground_truth))

        # metadata.json
        metadata = {
            "case_set_id": case_set_id,
            "difficulty": "medium",
            "tags": ["auth", "api", "tests"],
        }
        (case_dir / "metadata.json").write_text(json.dumps(metadata))

    def test_load_valid_case(self, tmp_path: Path) -> None:
        """Should successfully load a complete case."""
        case_id = "pr_001_missing_auth_check"
        fixtures_dir = tmp_path
        case_dir = fixtures_dir / "cases" / case_id
        case_dir.mkdir(parents=True)

        self.create_valid_case_fixtures(case_dir)

        case = load_case(case_id, fixtures_dir)

        assert isinstance(case, ReviewCaseDefinition)
        assert case.case_id == case_id
        assert case.case_set_id == "pr_review_cases_v1"
        assert case.difficulty == "medium"
        assert case.tags == ["auth", "api", "tests"]
        assert "admin endpoint" in case.ticket_text
        assert "app/api/admin.py" in case.diff_patch
        assert len(case.expected_findings) == 1
        assert case.expected_findings[0].finding_id == "F1"
        assert len(case.disallowed_findings) == 1
        assert case.disallowed_findings[0].canonical_label == "style_only_nit"

    def test_load_case_missing_directory(self, tmp_path: Path) -> None:
        """Should raise FileNotFoundError for missing case directory."""
        case_id = "nonexistent_case"
        fixtures_dir = tmp_path

        with pytest.raises(FileNotFoundError) as exc_info:
            load_case(case_id, fixtures_dir)

        assert "not found" in str(exc_info.value).lower()
        assert case_id in str(exc_info.value)

    def test_load_case_missing_ticket(self, tmp_path: Path) -> None:
        """Should raise FileNotFoundError for missing ticket.md."""
        case_id = "pr_001"
        fixtures_dir = tmp_path
        case_dir = fixtures_dir / "cases" / case_id
        case_dir.mkdir(parents=True)

        self.create_valid_case_fixtures(case_dir)
        (case_dir / "ticket.md").unlink()  # Remove ticket file

        with pytest.raises(FileNotFoundError) as exc_info:
            load_case(case_id, fixtures_dir)

        assert "ticket.md" in str(exc_info.value)

    def test_load_case_missing_diff(self, tmp_path: Path) -> None:
        """Should raise FileNotFoundError for missing diff.patch."""
        case_id = "pr_001"
        fixtures_dir = tmp_path
        case_dir = fixtures_dir / "cases" / case_id
        case_dir.mkdir(parents=True)

        self.create_valid_case_fixtures(case_dir)
        (case_dir / "diff.patch").unlink()  # Remove diff file

        with pytest.raises(FileNotFoundError) as exc_info:
            load_case(case_id, fixtures_dir)

        assert "diff.patch" in str(exc_info.value)

    def test_load_case_missing_ground_truth(self, tmp_path: Path) -> None:
        """Should raise FileNotFoundError for missing ground_truth.json."""
        case_id = "pr_001"
        fixtures_dir = tmp_path
        case_dir = fixtures_dir / "cases" / case_id
        case_dir.mkdir(parents=True)

        self.create_valid_case_fixtures(case_dir)
        (case_dir / "ground_truth.json").unlink()  # Remove ground truth file

        with pytest.raises(FileNotFoundError) as exc_info:
            load_case(case_id, fixtures_dir)

        assert "ground_truth.json" in str(exc_info.value)

    def test_load_case_missing_metadata(self, tmp_path: Path) -> None:
        """Should raise FileNotFoundError for missing metadata.json."""
        case_id = "pr_001"
        fixtures_dir = tmp_path
        case_dir = fixtures_dir / "cases" / case_id
        case_dir.mkdir(parents=True)

        self.create_valid_case_fixtures(case_dir)
        (case_dir / "metadata.json").unlink()  # Remove metadata file

        with pytest.raises(FileNotFoundError) as exc_info:
            load_case(case_id, fixtures_dir)

        assert "metadata.json" in str(exc_info.value)

    def test_load_case_malformed_ground_truth_json(self, tmp_path: Path) -> None:
        """Should raise ValueError for malformed ground_truth.json."""
        case_id = "pr_001"
        fixtures_dir = tmp_path
        case_dir = fixtures_dir / "cases" / case_id
        case_dir.mkdir(parents=True)

        self.create_valid_case_fixtures(case_dir)
        (case_dir / "ground_truth.json").write_text("{invalid json")

        with pytest.raises(ValueError) as exc_info:
            load_case(case_id, fixtures_dir)

        assert "malformed json" in str(exc_info.value).lower()

    def test_load_case_invalid_finding_in_ground_truth(self, tmp_path: Path) -> None:
        """Should raise ValueError for invalid finding in ground_truth.json."""
        case_id = "pr_001"
        fixtures_dir = tmp_path
        case_dir = fixtures_dir / "cases" / case_id
        case_dir.mkdir(parents=True)

        self.create_valid_case_fixtures(case_dir)

        # Write ground truth with invalid finding (missing required field)
        ground_truth = {
            "expected_findings": [
                {
                    "finding_id": "F1",
                    # Missing 'canonical_label' which is required
                    "severity": "high",
                    "file_path": "app.py",
                    "line_span": [10, 20],
                    "summary": "Missing auth.",
                }
            ],
            "disallowed_findings": [],
        }
        (case_dir / "ground_truth.json").write_text(json.dumps(ground_truth))

        with pytest.raises(ValueError) as exc_info:
            load_case(case_id, fixtures_dir)

        assert "invalid expected_findings" in str(exc_info.value).lower()

    def test_load_case_malformed_metadata_json(self, tmp_path: Path) -> None:
        """Should raise ValueError for malformed metadata.json."""
        case_id = "pr_001"
        fixtures_dir = tmp_path
        case_dir = fixtures_dir / "cases" / case_id
        case_dir.mkdir(parents=True)

        self.create_valid_case_fixtures(case_dir)
        (case_dir / "metadata.json").write_text("{invalid json")

        with pytest.raises(ValueError) as exc_info:
            load_case(case_id, fixtures_dir)

        assert "malformed json" in str(exc_info.value).lower()

    def test_load_case_invalid_difficulty_in_metadata(self, tmp_path: Path) -> None:
        """Should raise ValueError for invalid difficulty in metadata.json."""
        case_id = "pr_001"
        fixtures_dir = tmp_path
        case_dir = fixtures_dir / "cases" / case_id
        case_dir.mkdir(parents=True)

        self.create_valid_case_fixtures(case_dir)

        # Write metadata with invalid difficulty
        metadata = {
            "case_set_id": "pr_review_cases_v1",
            "difficulty": "super_hard",  # Invalid value
            "tags": ["auth"],
        }
        (case_dir / "metadata.json").write_text(json.dumps(metadata))

        with pytest.raises(ValueError) as exc_info:
            load_case(case_id, fixtures_dir)

        assert "invalid difficulty" in str(exc_info.value).lower()

    def test_load_case_invalid_tags_in_metadata(self, tmp_path: Path) -> None:
        """Should raise ValueError for invalid tags type in metadata.json."""
        case_id = "pr_001"
        fixtures_dir = tmp_path
        case_dir = fixtures_dir / "cases" / case_id
        case_dir.mkdir(parents=True)

        self.create_valid_case_fixtures(case_dir)

        # Write metadata with invalid tags (not a list)
        metadata = {
            "case_set_id": "pr_review_cases_v1",
            "difficulty": "medium",
            "tags": "auth,api",  # Should be a list
        }
        (case_dir / "metadata.json").write_text(json.dumps(metadata))

        with pytest.raises(ValueError) as exc_info:
            load_case(case_id, fixtures_dir)

        assert "invalid tags" in str(exc_info.value).lower()

    def test_load_case_no_disallowed_findings(self, tmp_path: Path) -> None:
        """Should handle ground truth without disallowed_findings."""
        case_id = "pr_001"
        fixtures_dir = tmp_path
        case_dir = fixtures_dir / "cases" / case_id
        case_dir.mkdir(parents=True)

        self.create_valid_case_fixtures(case_dir)

        # Write ground truth without disallowed_findings
        ground_truth = {
            "expected_findings": [
                {
                    "finding_id": "F1",
                    "canonical_label": "missing_permission_check",
                    "severity": "high",
                    "file_path": "app/api/admin.py",
                    "line_span": [42, 57],
                    "must_detect": True,
                    "summary": "The endpoint no longer enforces the admin permission check.",
                }
            ]
            # No disallowed_findings field
        }
        (case_dir / "ground_truth.json").write_text(json.dumps(ground_truth))

        case = load_case(case_id, fixtures_dir)

        assert len(case.disallowed_findings) == 0


class TestLoadCaseSet:
    """Tests for the load_case_set function."""

    def create_valid_case_fixtures(self, case_dir: Path) -> None:
        """Helper to create valid fixture files for a case."""
        # ticket.md
        (case_dir / "ticket.md").write_text(
            "# Add admin endpoint\n\nThis PR adds an admin endpoint for user management."
        )

        # diff.patch
        (case_dir / "diff.patch").write_text(
            "--- a/app/api/admin.py\n+++ b/app/api/admin.py\n@@ -10,5 +10,10 @@\n"
        )

        # ground_truth.json
        ground_truth = {
            "expected_findings": [
                {
                    "finding_id": "F1",
                    "canonical_label": "missing_permission_check",
                    "severity": "high",
                    "file_path": "app/api/admin.py",
                    "line_span": [42, 57],
                    "must_detect": True,
                    "summary": "The endpoint no longer enforces the admin permission check.",
                }
            ],
            "disallowed_findings": [],
        }
        (case_dir / "ground_truth.json").write_text(json.dumps(ground_truth))

        # metadata.json
        metadata = {
            "case_set_id": "pr_review_cases_v1",
            "difficulty": "medium",
            "tags": ["auth", "api"],
        }
        (case_dir / "metadata.json").write_text(json.dumps(metadata))

    def test_load_case_set_success(self, tmp_path: Path) -> None:
        """Should load all enabled cases for a case set."""
        fixtures_dir = tmp_path

        # Create manifest
        manifest_data = {
            "case_set_id": "pr_review_cases_v1",
            "version": "1.0.0",
            "cases": [
                {
                    "case_id": "pr_001",
                    "difficulty": "easy",
                    "enabled": True,
                    "tags": ["auth"],
                },
                {
                    "case_id": "pr_002",
                    "difficulty": "medium",
                    "enabled": True,
                    "tags": ["tests"],
                },
                {
                    "case_id": "pr_003",
                    "difficulty": "hard",
                    "enabled": False,  # Disabled case
                    "tags": ["perf"],
                },
            ],
        }
        (fixtures_dir / "manifest.json").write_text(json.dumps(manifest_data))

        # Create case fixtures for enabled cases
        for case_id in ["pr_001", "pr_002", "pr_003"]:
            case_dir = fixtures_dir / "cases" / case_id
            case_dir.mkdir(parents=True)
            self.create_valid_case_fixtures(case_dir)

        cases = load_case_set("pr_review_cases_v1", fixtures_dir)

        # Should only load enabled cases (pr_001 and pr_002)
        assert len(cases) == 2
        case_ids = {c.case_id for c in cases}
        assert "pr_001" in case_ids
        assert "pr_002" in case_ids
        assert "pr_003" not in case_ids

    def test_load_case_set_no_matching_cases(self, tmp_path: Path) -> None:
        """Should return empty list when case_set_id doesn't match."""
        fixtures_dir = tmp_path

        # Create manifest with different case_set_id
        manifest_data = {
            "case_set_id": "pr_review_cases_v1",
            "version": "1.0.0",
            "cases": [
                {
                    "case_id": "pr_001",
                    "difficulty": "easy",
                    "enabled": True,
                    "tags": [],
                },
            ],
        }
        (fixtures_dir / "manifest.json").write_text(json.dumps(manifest_data))

        # Create case fixtures
        case_dir = fixtures_dir / "cases" / "pr_001"
        case_dir.mkdir(parents=True)
        self.create_valid_case_fixtures(case_dir)

        # Try to load with different case_set_id
        cases = load_case_set("different_case_set", fixtures_dir)

        assert len(cases) == 0

    def test_load_case_set_empty_enabled_cases(self, tmp_path: Path) -> None:
        """Should return empty list when all cases are disabled."""
        fixtures_dir = tmp_path

        # Create manifest with all disabled cases
        manifest_data = {
            "case_set_id": "pr_review_cases_v1",
            "version": "1.0.0",
            "cases": [
                {
                    "case_id": "pr_001",
                    "difficulty": "easy",
                    "enabled": False,
                    "tags": [],
                },
            ],
        }
        (fixtures_dir / "manifest.json").write_text(json.dumps(manifest_data))

        # Create case fixtures
        case_dir = fixtures_dir / "cases" / "pr_001"
        case_dir.mkdir(parents=True)
        self.create_valid_case_fixtures(case_dir)

        cases = load_case_set("pr_review_cases_v1", fixtures_dir)

        assert len(cases) == 0

    def test_load_case_set_missing_manifest(self, tmp_path: Path) -> None:
        """Should raise FileNotFoundError when manifest.json is missing."""
        fixtures_dir = tmp_path

        with pytest.raises(FileNotFoundError) as exc_info:
            load_case_set("pr_review_cases_v1", fixtures_dir)

        assert "manifest.json" in str(exc_info.value)

    def test_load_case_set_missing_case_directory(self, tmp_path: Path) -> None:
        """Should raise FileNotFoundError when a case directory is missing."""
        fixtures_dir = tmp_path

        # Create manifest referencing a case that doesn't exist
        manifest_data = {
            "case_set_id": "pr_review_cases_v1",
            "version": "1.0.0",
            "cases": [
                {
                    "case_id": "nonexistent_case",
                    "difficulty": "easy",
                    "enabled": True,
                    "tags": [],
                },
            ],
        }
        (fixtures_dir / "manifest.json").write_text(json.dumps(manifest_data))

        with pytest.raises(FileNotFoundError) as exc_info:
            load_case_set("pr_review_cases_v1", fixtures_dir)

        assert "nonexistent_case" in str(exc_info.value)


class TestLoaderIntegration:
    """Integration tests combining multiple loader functions."""

    def test_full_fixture_loading_workflow(self, tmp_path: Path) -> None:
        """Should successfully load complete case set from fixtures."""
        fixtures_dir = tmp_path

        # Create comprehensive manifest
        manifest_data = {
            "case_set_id": "pr_review_cases_v1",
            "version": "1.0.0",
            "cases": [
                {
                    "case_id": "pr_001_missing_auth_check",
                    "difficulty": "hard",
                    "enabled": True,
                    "tags": ["security", "auth"],
                },
                {
                    "case_id": "pr_002_api_contract_break",
                    "difficulty": "medium",
                    "enabled": True,
                    "tags": ["api", "contract"],
                },
            ],
        }
        (fixtures_dir / "manifest.json").write_text(json.dumps(manifest_data))

        # Create case fixtures
        for case_id in ["pr_001_missing_auth_check", "pr_002_api_contract_break"]:
            case_dir = fixtures_dir / "cases" / case_id
            case_dir.mkdir(parents=True)

            # ticket.md
            (case_dir / "ticket.md").write_text(f"# {case_id}\n\nDescription here.")

            # diff.patch
            (case_dir / "diff.patch").write_text("diff content here")

            # ground_truth.json
            ground_truth = {
                "expected_findings": [
                    {
                        "finding_id": "F1",
                        "canonical_label": "missing_permission_check",
                        "severity": "high",
                        "file_path": "app/api/admin.py",
                        "line_span": [42, 57],
                        "must_detect": True,
                        "summary": "Missing auth check",
                    }
                ],
                "disallowed_findings": [],
            }
            (case_dir / "ground_truth.json").write_text(json.dumps(ground_truth))

            # metadata.json
            metadata = {
                "case_set_id": "pr_review_cases_v1",
                "difficulty": "medium",
                "tags": ["auth", "api"],
            }
            (case_dir / "metadata.json").write_text(json.dumps(metadata))

        # Load the full case set
        manifest = load_manifest(fixtures_dir / "manifest.json")
        enabled_cases = list_enabled_cases(manifest)

        assert len(enabled_cases) == 2

        # Load each case individually
        for case_def in enabled_cases:
            case = load_case(case_def.case_id, fixtures_dir)
            assert isinstance(case, ReviewCaseDefinition)
            assert case.case_id == case_def.case_id
            assert case.case_set_id == "pr_review_cases_v1"

        # Load full case set via convenience function
        cases = load_case_set("pr_review_cases_v1", fixtures_dir)

        assert len(cases) == 2
        assert {c.case_id for c in cases} == {
            "pr_001_missing_auth_check",
            "pr_002_api_contract_break",
        }


class TestResolveCaseTopic:
    """Tests for the resolve_case_topic function."""

    def test_pr_001_auth_security(self) -> None:
        assert resolve_case_topic(["auth", "api", "tests"]) == "Auth/Security"

    def test_pr_002_testing(self) -> None:
        assert resolve_case_topic(["tests", "coverage"]) == "Testing"

    def test_pr_003_null_safety(self) -> None:
        assert resolve_case_topic(["null-safety", "defensive-programming"]) == "Null Safety"

    def test_pr_004_api_compatibility(self) -> None:
        assert resolve_case_topic(["backward-compatibility", "contract"]) == "API Compatibility"

    def test_pr_005_error_handling(self) -> None:
        assert resolve_case_topic(["error-handling", "robustness", "file-io"]) == "Error Handling"

    def test_pr_006_caching_state(self) -> None:
        assert resolve_case_topic(["caching", "state", "consistency"]) == "Caching/State"

    def test_pr_007_input_validation(self) -> None:
        assert resolve_case_topic(["validation", "input-sanitization"]) == "Input Validation"

    def test_pr_008_database_n1(self) -> None:
        assert (
            resolve_case_topic(["performance", "database", "n+1", "optimization"]) == "Database/N+1"
        )

    def test_unknown_tags_returns_other(self) -> None:
        assert resolve_case_topic(["foo", "bar"]) == "Other"

    def test_empty_tags_returns_other(self) -> None:
        assert resolve_case_topic([]) == "Other"

    def test_case_insensitive(self) -> None:
        assert resolve_case_topic(["AUTH", "Security", "Admin"]) == "Auth/Security"
        assert resolve_case_topic(["Testing", "Coverage"]) == "Testing"
        assert resolve_case_topic(["N+1"]) == "Database/N+1"
