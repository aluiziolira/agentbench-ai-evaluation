"""Review case models for AgentBench."""

from typing import Literal

from pydantic import BaseModel, field_validator


class ReviewFindingTruth(BaseModel):
    finding_id: str
    canonical_label: str
    severity: Literal["high", "medium", "low"]
    file_path: str
    line_span: tuple[int, int]
    must_detect: bool = True
    summary: str

    @field_validator("line_span")
    @classmethod
    def validate_line_span(cls, v: tuple[int, int]) -> tuple[int, int]:
        if v[0] > v[1]:
            raise ValueError("line_span start must be <= end")
        return v


class DisallowedFinding(BaseModel):
    canonical_label: str


class CaseManifestEntry(BaseModel):
    case_id: str
    difficulty: Literal["easy", "medium", "hard"]
    enabled: bool
    tags: list[str]


class CaseSetManifest(BaseModel):
    case_set_id: str
    version: str
    cases: list[CaseManifestEntry]


class ReviewCaseDefinition(BaseModel):
    case_id: str
    case_set_id: str
    difficulty: Literal["easy", "medium", "hard"]
    tags: list[str]
    ticket_text: str
    diff_patch: str
    expected_findings: list[ReviewFindingTruth]
    disallowed_findings: list[DisallowedFinding] = []
