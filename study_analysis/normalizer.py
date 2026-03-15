from __future__ import annotations

from datetime import date, datetime

from study_analysis.schemas import (
    DeadlineCandidate,
    ExtractionResult,
    GlobalSummary,
    NormalizedComponent,
    NormalizedDeadline,
    NormalizedSubject,
    Recommendation,
    StudentQuery,
)


def normalize_subject(
    extraction: ExtractionResult,
    student_query: StudentQuery,
    subject_name_override: str | None = None,
) -> tuple[NormalizedSubject, list[NormalizedDeadline], list[Recommendation], list[str]]:
    warnings = list(extraction.warnings)
    subject_name = subject_name_override or extraction.subject.name
    component_lookup = {score.component: score for score in extraction.student_scores}
    weights = _resolve_weights(extraction)
    normalized_components: list[NormalizedComponent] = []
    completed_scores: list[float] = []
    for component in extraction.grading_scheme.components:
        score_item = component_lookup.get(component.name)
        max_score = component.max_score or (score_item.max_score if score_item else None) or 10.0
        score_value = score_item.score if score_item else None
        weight = weights[component.name]
        status = "complete" if score_value is not None else "pending"
        normalized_components.append(
            NormalizedComponent(
                name=component.name,
                weight=round(weight, 4),
                score=score_value,
                max_score=max_score,
                status=status,
                source_sheet=extraction.sheet_name,
            )
        )
        if score_value is not None and max_score:
            completed_scores.append((score_value / max_score) * 10.0)
    current_score = _compute_current_score(normalized_components)
    predicted_score = _compute_predicted_score(normalized_components, completed_scores)
    risk_level = _compute_risk_level(current_score, predicted_score)
    deadlines = [_normalize_deadline(candidate, subject_name) for candidate in extraction.deadlines]
    recommendations = _build_recommendations(subject_name, normalized_components, deadlines, predicted_score)
    if any(component.weight is None for component in extraction.grading_scheme.components):
        warnings.append("Missing weights were inferred during normalization.")
    subject = NormalizedSubject(
        name=subject_name,
        source_url=extraction.source_url,
        components=normalized_components,
        current_weighted_score=round(current_score, 2),
        predicted_score=round(predicted_score, 2),
        risk_level=risk_level,
        confidence=extraction.overall_confidence,
    )
    return subject, deadlines, recommendations, warnings


def aggregate_subjects(
    subjects: list[NormalizedSubject],
    deadlines: list[NormalizedDeadline],
    warnings: list[str],
    source_title: str | None = None,
) -> tuple[list[NormalizedSubject], list[Recommendation], GlobalSummary]:
    if not subjects:
        return (
            [],
            [],
            GlobalSummary(average_score=0.0, high_risk_subjects=0, missing_data_sources=0),
        )
    if len(subjects) == 1:
        subject = subjects[0]
        if source_title:
            subject = NormalizedSubject(
                name=source_title,
                source_url=subject.source_url,
                components=subject.components,
                current_weighted_score=subject.current_weighted_score,
                predicted_score=subject.predicted_score,
                risk_level=subject.risk_level,
                confidence=subject.confidence,
            )
        recommendations = _build_recommendations(subject.name, subject.components, deadlines, subject.predicted_score)
        return (
            [subject],
            recommendations,
            GlobalSummary(
                average_score=subject.predicted_score,
                high_risk_subjects=1 if subject.risk_level == "high" else 0,
                missing_data_sources=0,
            ),
        )
    all_components: list[NormalizedComponent] = []
    for subject in subjects:
        all_components.extend(subject.components)
    merged_components = _renormalize_components(all_components)
    current_score = _compute_current_score(merged_components)
    completed_scores = [
        (component.score / component.max_score) * 10.0
        for component in merged_components
        if component.score is not None and component.max_score
    ]
    predicted_score = _compute_predicted_score(merged_components, completed_scores)
    risk_level = _compute_risk_level(current_score, predicted_score)
    merged_subject = NormalizedSubject(
        name=source_title or subjects[0].name,
        source_url=subjects[0].source_url,
        components=merged_components,
        current_weighted_score=round(current_score, 2),
        predicted_score=round(predicted_score, 2),
        risk_level=risk_level,
        confidence=round(sum(subject.confidence for subject in subjects) / len(subjects), 2),
    )
    recommendations = _build_recommendations(merged_subject.name, merged_components, deadlines, predicted_score)
    summary = GlobalSummary(
        average_score=merged_subject.predicted_score,
        high_risk_subjects=1 if merged_subject.risk_level == "high" else 0,
        missing_data_sources=0,
    )
    return [merged_subject], recommendations, summary


def _resolve_weights(extraction: ExtractionResult) -> dict[str, float]:
    components = extraction.grading_scheme.components
    known_weights = {component.name: component.weight for component in components if component.weight is not None}
    known_total = sum(weight for weight in known_weights.values() if weight is not None)
    missing_names = [component.name for component in components if component.weight is None]
    inferred_weight = 0.0
    if missing_names:
        remaining = max(0.0, 1.0 - known_total)
        if remaining == 0.0:
            inferred_weight = 1.0 / len(components)
            return {component.name: inferred_weight for component in components}
        inferred_weight = remaining / len(missing_names)
    resolved = {}
    for component in components:
        if component.weight is not None:
            resolved[component.name] = component.weight
        else:
            resolved[component.name] = inferred_weight
    return resolved


def _compute_current_score(components: list[NormalizedComponent]) -> float:
    total = 0.0
    for component in components:
        if component.score is None or component.max_score == 0:
            continue
        normalized_score = (component.score / component.max_score) * 10.0
        total += normalized_score * component.weight
    return min(10.0, total)


def _compute_predicted_score(components: list[NormalizedComponent], completed_scores: list[float]) -> float:
    baseline = sum(completed_scores) / len(completed_scores) if completed_scores else 6.0
    total = 0.0
    for component in components:
        if component.score is None:
            total += baseline * component.weight
            continue
        total += (component.score / component.max_score) * 10.0 * component.weight
    return min(10.0, total)


def _compute_risk_level(current_score: float, predicted_score: float) -> str:
    signal = min(current_score, predicted_score)
    if signal < 4.0:
        return "high"
    if signal < 6.5:
        return "medium"
    return "low"


def _renormalize_components(components: list[NormalizedComponent]) -> list[NormalizedComponent]:
    total_weight = sum(component.weight for component in components)
    if total_weight <= 0:
        fallback_weight = 1.0 / len(components) if components else 0.0
        return [
            NormalizedComponent(
                name=component.name,
                weight=round(fallback_weight, 4),
                score=component.score,
                max_score=component.max_score,
                status=component.status,
                source_sheet=component.source_sheet,
            )
            for component in components
        ]
    return [
        NormalizedComponent(
            name=component.name,
            weight=round(component.weight / total_weight, 4),
            score=component.score,
            max_score=component.max_score,
            status=component.status,
            source_sheet=component.source_sheet,
        )
        for component in components
    ]


def _normalize_deadline(candidate: DeadlineCandidate, subject_name: str) -> NormalizedDeadline:
    urgency = "medium"
    days_left = _days_until(candidate.date_text)
    if days_left is not None:
        if days_left <= 3:
            urgency = "high"
        elif days_left <= 7:
            urgency = "medium"
        else:
            urgency = "low"
    return NormalizedDeadline(
        subject=subject_name,
        name=candidate.name,
        date=candidate.date_text,
        urgency=urgency,
    )


def _days_until(date_text: str) -> int | None:
    try:
        target = datetime.strptime(date_text, "%Y-%m-%d").date()
    except ValueError:
        return None
    return (target - date.today()).days


def _build_recommendations(
    subject_name: str,
    components: list[NormalizedComponent],
    deadlines: list[NormalizedDeadline],
    predicted_score: float,
) -> list[Recommendation]:
    recommendations: list[Recommendation] = []
    if predicted_score < 6.0:
        recommendations.append(
            Recommendation(
                subject=subject_name,
                reason="Predicted score is below the comfortable threshold.",
                action="Review the highest-weight components first and confirm the grading formula.",
                urgency="high",
            )
        )
    for component in components:
        if component.score is None and component.weight >= 0.25:
            recommendations.append(
                Recommendation(
                    subject=subject_name,
                    reason=f"Component '{component.name}' is still pending and has significant weight.",
                    action=f"Prioritize completing '{component.name}' next.",
                    urgency="high",
                )
            )
        elif component.score is not None:
            normalized_score = (component.score / component.max_score) * 10.0
            if normalized_score < 6.0:
                recommendations.append(
                    Recommendation(
                        subject=subject_name,
                        reason=f"Current score in '{component.name}' is low relative to its max score.",
                        action=f"Focus on improving '{component.name}' or clarifying whether the extracted score is correct.",
                        urgency="medium" if component.weight < 0.25 else "high",
                    )
                )
    for deadline in deadlines:
        if deadline.urgency == "high":
            recommendations.append(
                Recommendation(
                    subject=subject_name,
                    reason=f"Upcoming deadline '{deadline.name}' is very close.",
                    action="Surface this item in the bot/frontend as the next urgent task.",
                    urgency="high",
                )
            )
    return recommendations
