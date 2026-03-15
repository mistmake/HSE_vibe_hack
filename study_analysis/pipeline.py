from __future__ import annotations

from study_analysis.extractor import extract
from study_analysis.fetchers import load_source
from study_analysis.llm import StudentRowMatcher, WorksheetStructureAnalyzer
from study_analysis.normalizer import aggregate_subjects, normalize_subject
from study_analysis.preprocess import prepare_worksheet
from study_analysis.schemas import (
    AnalysisResult,
    GlobalSummary,
    NormalizedAnalysis,
    StudentQuery,
    WorksheetAnalysis,
)
from study_analysis.validator import validate_extraction


class AnalysisPipeline:
    def __init__(
        self,
        student_matcher: StudentRowMatcher | None = None,
        structure_analyzer: WorksheetStructureAnalyzer | None = None,
    ) -> None:
        self.student_matcher = student_matcher
        self.structure_analyzer = structure_analyzer

    def analyze(self, source: str, full_name: str, group: str | None = None) -> AnalysisResult:
        student_query = StudentQuery(full_name=full_name, group=group)
        document = load_source(source)
        source_subject_name = _resolve_source_subject_name(document)
        worksheet_results: list[WorksheetAnalysis] = []
        normalized_subjects = []
        normalized_deadlines = []
        recommendations = []
        warnings: list[str] = []
        for worksheet in document.worksheets:
            prepared = prepare_worksheet(worksheet)
            if self.structure_analyzer is not None and _structure_looks_suspicious(prepared):
                prepared = _reprepare_with_structure_hint(
                    worksheet=worksheet,
                    student_query=student_query,
                    structure_analyzer=self.structure_analyzer,
                    fallback_prepared=prepared,
                )
            extraction = extract(
                prepared=prepared,
                student_query=student_query,
                source_url=document.source_url,
                source_type=document.source_type,
                source_subject_name=source_subject_name,
                student_matcher=self.student_matcher,
            )
            validation = validate_extraction(extraction)
            worksheet_results.append(
                WorksheetAnalysis(prepared=prepared, extraction=extraction, validation=validation)
            )
            if not validation.is_valid:
                warnings.extend(issue.message for issue in validation.issues if issue.level == "error")
                continue
            subject, deadlines, subject_recommendations, subject_warnings = normalize_subject(
                extraction=extraction,
                student_query=student_query,
                subject_name_override=source_subject_name,
            )
            normalized_subjects.append(subject)
            normalized_deadlines.extend(deadlines)
            recommendations.extend(subject_recommendations)
            warnings.extend(subject_warnings)
            warnings.extend(issue.message for issue in validation.issues if issue.level == "warning")
        aggregated_subjects, recommendations, summary = aggregate_subjects(
            subjects=normalized_subjects,
            deadlines=normalized_deadlines,
            warnings=warnings,
            source_title=document.title,
        )
        normalized = NormalizedAnalysis(
            student={
                "full_name": student_query.full_name,
                "group": student_query.group,
            },
            subjects=aggregated_subjects,
            deadlines=normalized_deadlines,
            recommendations=recommendations,
            global_summary=GlobalSummary(
                average_score=summary.average_score,
                high_risk_subjects=summary.high_risk_subjects,
                missing_data_sources=max(0, len(document.worksheets) - len(normalized_subjects)),
            ),
            warnings=warnings,
        )
        return AnalysisResult(
            source=document,
            worksheets=worksheet_results,
            normalized=normalized,
        )


def _structure_looks_suspicious(prepared: PreparedWorksheet) -> bool:
    if not prepared.headers:
        return True
    if len(prepared.header_row_indices) > 1:
        return True
    numeric_headers = sum(1 for header in prepared.headers if _is_mostly_numeric_header(header))
    non_empty_headers = [header for header in prepared.headers if header.strip()]
    repeated_headers = len(non_empty_headers) != len(set(non_empty_headers))
    name_group_missing = "Student" not in prepared.headers and "Group" not in prepared.headers
    return (
        numeric_headers >= max(5, len(non_empty_headers) // 2)
        or repeated_headers
        or name_group_missing
    )


def _is_mostly_numeric_header(header: str) -> bool:
    stripped = header.strip()
    if not stripped:
        return False
    return stripped.replace(".", "").isdigit()


def _reprepare_with_structure_hint(
    worksheet,
    student_query: StudentQuery,
    structure_analyzer: WorksheetStructureAnalyzer,
    fallback_prepared: PreparedWorksheet,
) -> PreparedWorksheet:
    warnings = list(fallback_prepared.warnings)
    try:
        hint = structure_analyzer.analyze_structure(worksheet, student_query)
    except Exception as exc:
        warnings.append(f"LLM structure analysis failed: {exc}")
        return prepare_worksheet(worksheet, warnings=warnings)
    if hint is None:
        warnings.append("LLM structure analysis did not return a usable structure hint.")
        return prepare_worksheet(worksheet, warnings=warnings)
    warnings.append("Worksheet structure was refined via LLM analysis.")
    return prepare_worksheet(worksheet, structure_hint=hint, warnings=warnings)


def _resolve_source_subject_name(document) -> str | None:
    if document.title:
        return document.title
    if document.worksheets:
        first_title = document.worksheets[0].title
        if first_title and not first_title.lower().startswith("gid_"):
            return first_title
    return None
