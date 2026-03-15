from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class StudentQuery:
    full_name: str
    group: str | None = None


@dataclass
class WorksheetSnapshot:
    title: str
    gid: str
    rows: list[list[str]]


@dataclass
class SourceDocument:
    source_url: str
    source_type: str
    worksheets: list[WorksheetSnapshot]
    title: str | None = None
    spreadsheet_id: str | None = None


@dataclass
class PreparedWorksheet:
    title: str
    gid: str
    rows: list[list[str]]
    header_row_index: int
    headers: list[str]
    data_rows: list[list[str]]
    context_text: str
    header_row_indices: list[int] = field(default_factory=list)
    structure_hint: "WorksheetStructureHint | None" = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class MatchCandidate:
    value: str | None
    confidence: float
    method: str = "heuristic"
    row_index: int | None = None
    validator_confidence: float | None = None
    reason: str | None = None


@dataclass
class WorksheetColumnDefinition:
    index: int
    label: str
    role: str
    max_score: float | None = None
    weight: float | None = None
    confidence: float | None = None


@dataclass
class WorksheetStructureHint:
    header_row_indices: list[int]
    data_start_row: int
    subject_name: str | None
    name_column_index: int | None
    group_column_index: int | None
    component_columns: list[WorksheetColumnDefinition]
    confidence: float
    reason: str


@dataclass
class SubjectGuess:
    name: str
    confidence: float


@dataclass
class GradingComponent:
    name: str
    weight: float | None = None
    max_score: float | None = None


@dataclass
class GradingScheme:
    formula_text: str | None
    components: list[GradingComponent]
    confidence: float


@dataclass
class StudentScore:
    component: str
    score: float | None
    max_score: float | None
    comment: str
    confidence: float


@dataclass
class DeadlineCandidate:
    name: str
    date_text: str
    confidence: float


@dataclass
class ExtractionResult:
    source_type: str
    source_url: str
    sheet_name: str
    student_query: StudentQuery
    matched_student: MatchCandidate
    subject: SubjectGuess
    grading_scheme: GradingScheme
    student_scores: list[StudentScore]
    deadlines: list[DeadlineCandidate]
    warnings: list[str]
    overall_confidence: float


@dataclass
class ValidationIssue:
    level: str
    code: str
    message: str


@dataclass
class ValidationReport:
    is_valid: bool
    issues: list[ValidationIssue]


@dataclass
class NormalizedComponent:
    name: str
    weight: float
    score: float | None
    max_score: float
    status: str
    source_sheet: str | None = None


@dataclass
class NormalizedSubject:
    name: str
    source_url: str
    components: list[NormalizedComponent]
    current_weighted_score: float
    predicted_score: float
    risk_level: str
    confidence: float


@dataclass
class NormalizedDeadline:
    subject: str
    name: str
    date: str
    urgency: str


@dataclass
class Recommendation:
    subject: str
    reason: str
    action: str
    urgency: str


@dataclass
class GlobalSummary:
    average_score: float
    high_risk_subjects: int
    missing_data_sources: int


@dataclass
class NormalizedAnalysis:
    student: dict[str, Any]
    subjects: list[NormalizedSubject]
    deadlines: list[NormalizedDeadline]
    recommendations: list[Recommendation]
    global_summary: GlobalSummary
    warnings: list[str] = field(default_factory=list)


@dataclass
class WorksheetAnalysis:
    prepared: PreparedWorksheet
    extraction: ExtractionResult
    validation: ValidationReport


@dataclass
class AnalysisResult:
    source: SourceDocument
    worksheets: list[WorksheetAnalysis]
    normalized: NormalizedAnalysis

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
