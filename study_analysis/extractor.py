from __future__ import annotations

import re
from datetime import datetime
from difflib import SequenceMatcher

from study_analysis.llm import StudentRowMatcher
from study_analysis.schemas import (
    DeadlineCandidate,
    ExtractionResult,
    GradingComponent,
    GradingScheme,
    MatchCandidate,
    PreparedWorksheet,
    StudentQuery,
    StudentScore,
    SubjectGuess,
    WorksheetColumnDefinition,
)


COMPONENT_KEYWORDS = {
    "name": ("student", "name", "fio", "фио", "студент"),
    "group": ("group", "группа"),
    "hw": ("дз", "д/з", "hw", "homework", "домаш"),
    "quiz": ("quiz", "test", "тест"),
    "control": ("кр", "контроль", "midterm", "контр"),
    "exam": ("exam", "экзам", "final", "итог"),
    "project": ("project", "проект"),
    "lab": ("lab", "лаба", "лаб"),
}


def extract(
    prepared: PreparedWorksheet,
    student_query: StudentQuery,
    source_url: str,
    source_type: str,
    source_subject_name: str | None = None,
    student_matcher: StudentRowMatcher | None = None,
) -> ExtractionResult:
    matched_row_index, matched_student, match_warnings = _resolve_student_match(
        prepared=prepared,
        student_query=student_query,
        student_matcher=student_matcher,
    )
    subject_name = _resolve_subject_name(prepared, source_subject_name=source_subject_name)
    component_columns = _detect_component_columns(prepared)
    scores, components = _extract_scores(prepared, matched_row_index, component_columns)
    deadlines = _extract_deadlines(prepared, subject_name)
    warnings = list(prepared.warnings) + list(match_warnings)
    if matched_row_index is None:
        warnings.append("Student row was not confidently identified.")
    if not components:
        warnings.append("No assessment component columns were detected.")
    if any(component.weight is None for component in components):
        warnings.append("Weights were not found for some components and may need inference.")
    overall_confidence = _compute_overall_confidence(
        match_confidence=matched_student.confidence,
        subject_confidence=0.85 if subject_name != prepared.title else 0.65,
        component_count=len(components),
        scored_count=sum(1 for score in scores if score.score is not None),
    )
    formula_text = " + ".join(
        _format_formula_fragment(component) for component in components if component.weight is not None
    ) or None
    return ExtractionResult(
        source_type=source_type,
        source_url=source_url,
        sheet_name=prepared.title,
        student_query=student_query,
        matched_student=matched_student,
        subject=SubjectGuess(name=subject_name, confidence=0.85 if subject_name else 0.4),
        grading_scheme=GradingScheme(
            formula_text=formula_text,
            components=components,
            confidence=0.8 if components else 0.3,
        ),
        student_scores=scores,
        deadlines=deadlines,
        warnings=warnings,
        overall_confidence=round(overall_confidence, 2),
    )


def _resolve_student_match(
    prepared: PreparedWorksheet,
    student_query: StudentQuery,
    student_matcher: StudentRowMatcher | None,
) -> tuple[int | None, MatchCandidate, list[str]]:
    matched_row_index, matched_cell, match_confidence = _find_student_row(prepared, student_query)
    heuristic_match = MatchCandidate(
        value=matched_cell,
        confidence=round(match_confidence, 2),
        method="heuristic",
        row_index=matched_row_index,
        validator_confidence=round(match_confidence, 2),
    )
    warnings: list[str] = []
    if matched_row_index is not None or student_matcher is None:
        return matched_row_index, heuristic_match, warnings
    suggestion = student_matcher.match_student_row(prepared, student_query)
    if suggestion is None or suggestion.row_index is None:
        warnings.append("LLM fallback did not return a usable student row.")
        return matched_row_index, heuristic_match, warnings
    if suggestion.row_index < 0 or suggestion.row_index >= len(prepared.data_rows):
        warnings.append("LLM fallback returned an out-of-range row index.")
        return matched_row_index, heuristic_match, warnings
    validated_match = _validate_llm_match(prepared, student_query, suggestion.row_index)
    if validated_match is None:
        warnings.append(
            f"LLM fallback suggested row {suggestion.row_index}, but deterministic validation rejected it."
        )
        return matched_row_index, heuristic_match, warnings
    warnings.append("Student row was recovered via LLM fallback and deterministic validation.")
    validated_match.method = "llm_fallback"
    validated_match.reason = suggestion.reason
    validated_match.confidence = round(max(validated_match.confidence, suggestion.confidence), 2)
    return suggestion.row_index, validated_match, warnings


def _find_student_row(prepared: PreparedWorksheet, student_query: StudentQuery) -> tuple[int | None, str | None, float]:
    best_index = None
    best_cell = None
    best_score = 0.0
    name_col, group_col = _resolve_identity_columns(prepared)
    for row_index, row in enumerate(prepared.data_rows):
        candidate_cell = row[name_col] if name_col is not None and name_col < len(row) else " ".join(row[:2])
        score = _name_similarity(candidate_cell, student_query.full_name)
        if student_query.group and group_col is not None and group_col < len(row):
            group_value = row[group_col]
            if _normalize_text(group_value) == _normalize_text(student_query.group):
                score = min(1.0, score + 0.15)
        elif student_query.group and any(
            _normalize_text(student_query.group) == _normalize_text(cell) for cell in row
        ):
            score = min(1.0, score + 0.1)
        if score > best_score:
            best_score = score
            best_index = row_index
            best_cell = candidate_cell
    if best_score < 0.45:
        return None, best_cell, round(best_score, 2)
    return best_index, best_cell, round(best_score, 2)


def _validate_llm_match(
    prepared: PreparedWorksheet,
    student_query: StudentQuery,
    row_index: int,
) -> MatchCandidate | None:
    row = prepared.data_rows[row_index]
    best_cell, best_name_score = _best_name_signal(row, student_query.full_name)
    group_match = _row_has_group(row, student_query.group)
    validator_confidence = min(1.0, best_name_score + (0.15 if group_match else 0.0))
    accepts = validator_confidence >= 0.45 or (group_match and best_name_score >= 0.3)
    if not accepts:
        return None
    return MatchCandidate(
        value=best_cell,
        confidence=round(validator_confidence, 2),
        row_index=row_index,
        validator_confidence=round(validator_confidence, 2),
    )


def _guess_subject_name(title: str) -> str:
    cleaned = title.replace("_", " ").strip()
    cleaned = re.sub(r"\bgid\s*\d+\b", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned or "Unknown subject"


def _resolve_subject_name(prepared: PreparedWorksheet, source_subject_name: str | None = None) -> str:
    if source_subject_name:
        return source_subject_name
    if prepared.structure_hint and prepared.structure_hint.subject_name:
        return prepared.structure_hint.subject_name
    return _guess_subject_name(prepared.title)


def _resolve_identity_columns(prepared: PreparedWorksheet) -> tuple[int | None, int | None]:
    if prepared.structure_hint is not None:
        return prepared.structure_hint.name_column_index, prepared.structure_hint.group_column_index
    return _find_column_by_kind(prepared.headers, "name"), _find_column_by_kind(prepared.headers, "group")


def _detect_component_columns(prepared: PreparedWorksheet) -> list[WorksheetColumnDefinition]:
    if prepared.structure_hint is not None and prepared.structure_hint.component_columns:
        return [column for column in prepared.structure_hint.component_columns if column.role == "component"]
    component_columns: list[WorksheetColumnDefinition] = []
    for index, header in enumerate(prepared.headers):
        kind = _classify_header(header)
        if kind in {"name", "group", None}:
            continue
        component_columns.append(WorksheetColumnDefinition(index=index, label=header.strip() or kind, role="component"))
    return component_columns


def _extract_scores(
    prepared: PreparedWorksheet,
    matched_row_index: int | None,
    component_columns: list[WorksheetColumnDefinition],
) -> tuple[list[StudentScore], list[GradingComponent]]:
    if matched_row_index is None:
        return [], []
    row = prepared.data_rows[matched_row_index]
    scores: list[StudentScore] = []
    components: list[GradingComponent] = []
    for column in component_columns:
        column_index = column.index
        header = column.label
        raw_value = row[column_index] if column_index < len(row) else ""
        score_value = _parse_number(raw_value)
        max_score = column.max_score if column.max_score is not None else _extract_max_score(header)
        if max_score is None and score_value is not None:
            max_score = 10.0 if score_value <= 10 else 100.0
        weight = column.weight if column.weight is not None else _extract_weight(header)
        comment = f"Found in column '{header}'"
        scores.append(
            StudentScore(
                component=header,
                score=score_value,
                max_score=max_score,
                comment=comment,
                confidence=0.9 if score_value is not None else 0.45,
            )
        )
        components.append(GradingComponent(name=header, weight=weight, max_score=max_score))
    return scores, components


def _extract_deadlines(prepared: PreparedWorksheet, subject_name: str) -> list[DeadlineCandidate]:
    candidates: list[DeadlineCandidate] = []
    for row in prepared.rows[:15]:
        row_text = " ".join(str(cell) for cell in row)
        date_text = _extract_date(row_text)
        if not date_text:
            continue
        lowered = row_text.lower()
        if any(keyword in lowered for keyword in ("экзам", "exam", "контроль", "deadline", "дедлайн", "сдача")):
            name = "Deadline"
            if "экзам" in lowered or "exam" in lowered:
                name = "Exam"
            elif "контроль" in lowered:
                name = "Control"
            candidates.append(DeadlineCandidate(name=f"{subject_name}: {name}", date_text=date_text, confidence=0.6))
    return candidates


def _compute_overall_confidence(
    match_confidence: float,
    subject_confidence: float,
    component_count: int,
    scored_count: int,
) -> float:
    component_signal = 0.0
    if component_count:
        component_signal = min(1.0, 0.4 + 0.15 * component_count + 0.1 * scored_count)
    return max(0.0, min(1.0, 0.5 * match_confidence + 0.2 * subject_confidence + 0.3 * component_signal))


def _format_formula_fragment(component: GradingComponent) -> str:
    return f"{component.weight:.2f}*{component.name}"


def _find_column_by_kind(headers: list[str], kind: str) -> int | None:
    for index, header in enumerate(headers):
        if _classify_header(header) == kind:
            return index
    return None


def _classify_header(header: str) -> str | None:
    lowered = header.lower()
    for kind, keywords in COMPONENT_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return kind
    if _looks_numeric_metric(lowered):
        return "metric"
    return None


def _looks_numeric_metric(header: str) -> bool:
    digits_only = bool(re.fullmatch(r"[\d.\s]+", header))
    if digits_only:
        return True
    return any(char.isdigit() for char in header) or "%" in header


def _normalize_text(value: str) -> str:
    value = value.casefold()
    value = re.sub(r"[^0-9a-zа-я]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _best_name_signal(row: list[str], target: str) -> tuple[str | None, float]:
    best_cell = None
    best_score = 0.0
    for cell in row:
        cell_text = str(cell).strip()
        if not cell_text:
            continue
        score = _name_similarity(cell_text, target)
        if score > best_score:
            best_score = score
            best_cell = cell_text
    return best_cell, best_score


def _row_has_group(row: list[str], group: str | None) -> bool:
    if not group:
        return False
    normalized_group = _normalize_text(group)
    return any(_normalize_text(str(cell)) == normalized_group for cell in row)


def _name_similarity(candidate: str, target: str) -> float:
    candidate_norm = _normalize_text(candidate)
    target_norm = _normalize_text(target)
    if not candidate_norm or not target_norm:
        return 0.0
    if candidate_norm == target_norm:
        return 1.0
    candidate_tokens = candidate_norm.split()
    target_tokens = target_norm.split()
    sequence_ratio = SequenceMatcher(None, candidate_norm, target_norm).ratio()
    if candidate_tokens and target_tokens and candidate_tokens[0] == target_tokens[0]:
        candidate_initials = "".join(token[0] for token in candidate_tokens[1:] if token)
        target_initials = "".join(token[0] for token in target_tokens[1:] if token)
        if candidate_initials and target_initials and candidate_initials == target_initials[: len(candidate_initials)]:
            return max(sequence_ratio, 0.92)
        return max(sequence_ratio, 0.72)
    return sequence_ratio


def _parse_number(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    value = value.replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    if not match:
        return None
    return float(match.group())


def _extract_weight(header: str) -> float | None:
    percent_match = re.search(r"(\d+(?:[.,]\d+)?)\s*%", header)
    if percent_match:
        return float(percent_match.group(1).replace(",", ".")) / 100.0
    coefficient_match = re.search(r"(?<!\d)(0(?:[.,]\d+)?|1(?:[.,]0+)?)\s*[*xх×]", header, flags=re.IGNORECASE)
    if coefficient_match:
        return float(coefficient_match.group(1).replace(",", "."))
    return None


def _extract_max_score(header: str) -> float | None:
    patterns = (
        r"/\s*(\d+(?:[.,]\d+)?)",
        r"из\s*(\d+(?:[.,]\d+)?)",
        r"max\s*(\d+(?:[.,]\d+)?)",
        r"\(\s*(\d+(?:[.,]\d+)?)\s*\)",
    )
    for pattern in patterns:
        match = re.search(pattern, header, flags=re.IGNORECASE)
        if match:
            return float(match.group(1).replace(",", "."))
    return None


def _extract_date(text: str) -> str | None:
    for pattern in (r"\b(\d{4}-\d{2}-\d{2})\b", r"\b(\d{2}\.\d{2}\.\d{4})\b"):
        match = re.search(pattern, text)
        if not match:
            continue
        raw = match.group(1)
        if "." in raw:
            return datetime.strptime(raw, "%d.%m.%Y").date().isoformat()
        return raw
    return None
