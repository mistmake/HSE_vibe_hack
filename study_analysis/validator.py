from __future__ import annotations

from study_analysis.schemas import ExtractionResult, ValidationIssue, ValidationReport


def validate_extraction(extraction: ExtractionResult) -> ValidationReport:
    issues: list[ValidationIssue] = []
    if extraction.matched_student.confidence < 0.6:
        issues.append(
            ValidationIssue(
                level="error",
                code="student_match_low_confidence",
                message="Student match confidence is too low for reliable analysis.",
            )
        )
    if not extraction.student_scores:
        issues.append(
            ValidationIssue(
                level="error",
                code="no_scores_found",
                message="No score columns were extracted from the worksheet.",
            )
        )
    for score in extraction.student_scores:
        if score.score is None:
            continue
        if score.max_score is not None and score.score > score.max_score:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="score_exceeds_max",
                    message=f"Component '{score.component}' has score above max_score.",
                )
            )
    weights = [component.weight for component in extraction.grading_scheme.components if component.weight is not None]
    if weights:
        weight_sum = sum(weights)
        if abs(weight_sum - 1.0) > 0.15:
            issues.append(
                ValidationIssue(
                    level="warning",
                    code="weight_sum_suspicious",
                    message=f"Component weights sum to {weight_sum:.2f}, which is far from 1.0.",
                )
            )
    else:
        issues.append(
            ValidationIssue(
                level="warning",
                code="weights_missing",
                message="No explicit component weights were found.",
            )
        )
    if extraction.overall_confidence < 0.6:
        issues.append(
            ValidationIssue(
                level="warning",
                code="overall_confidence_low",
                message="Overall extraction confidence is low.",
            )
        )
    return ValidationReport(
        is_valid=not any(issue.level == "error" for issue in issues),
        issues=issues,
    )
