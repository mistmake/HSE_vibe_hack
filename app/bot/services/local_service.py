from __future__ import annotations

from dataclasses import asdict
import re
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from app.bot.domain import BotProfile, ClarificationRequest, ManualFormulaOverride, StoredSource
from app.bot.services.local_storage import ProfileRepository, SourceRepository
from app.bot.services.wiki_formula import extract_formula_from_wiki_page
from gradebook_finder import find_group_gradebooks
from study_analysis import AnalysisPipeline, OpenAIStudentMatcher, OpenAIWorksheetStructureAnalyzer
from study_analysis.llm import FormulaParseResult, OpenAIFormulaWeightParser
from study_analysis.normalizer import aggregate_subjects, normalize_subject
from study_analysis.schemas import AnalysisResult, GlobalSummary, NormalizedAnalysis


class LocalStudyBotService:
    def __init__(
        self,
        profiles: ProfileRepository,
        sources: SourceRepository,
        analysis_runner: Callable[[str, str, str | None], AnalysisResult] | None = None,
        gradebook_resolver: Callable[[str, str | None], dict] | None = None,
        formula_parser: OpenAIFormulaWeightParser | None = None,
        llm_model: str = "gpt-5-mini",
        enable_llm_student_match: bool = False,
        enable_llm_structure: bool = True,
        enable_gradebook_gpt: bool = False,
    ) -> None:
        self.profiles = profiles
        self.sources = sources
        self.analysis_runner = analysis_runner or self._build_default_runner(
            llm_model=llm_model,
            enable_llm_student_match=enable_llm_student_match,
            enable_llm_structure=enable_llm_structure,
        )
        self.gradebook_resolver = gradebook_resolver or self._build_default_gradebook_resolver(
            enable_gradebook_gpt=enable_gradebook_gpt,
        )
        self.formula_parser = formula_parser or OpenAIFormulaWeightParser(model=llm_model)

    def get_profile(self, telegram_id: int) -> BotProfile | None:
        return self.profiles.get(telegram_id)

    def register_profile(
        self,
        telegram_id: int,
        full_name: str,
        group_name: str,
        program_code: str | None = None,
    ) -> BotProfile:
        return self.profiles.upsert(
            telegram_id,
            full_name=full_name.strip(),
            group_name=group_name.strip(),
            program_code=program_code.strip().upper() if program_code else None,
        )

    def add_source(self, telegram_id: int, source_url: str) -> StoredSource:
        source_url = source_url.strip()
        if not _is_google_sheet_url(source_url):
            raise ValueError("Сейчас в MVP бот принимает только публичные ссылки на Google Sheets.")
        return self.sources.save_new(
            telegram_id=telegram_id,
            source_url=source_url,
            source_type="google_sheet",
            source_metadata={},
        )

    def discover_profile_sources(self, telegram_id: int) -> list[dict[str, str | None]]:
        profile = self.get_profile(telegram_id)
        if profile is None:
            raise ValueError("Сначала нужно заполнить профиль через /start.")
        if not profile.program_code:
            raise ValueError("Для автопоиска ведомостей выбери программу в профиле.")

        resolved = self.gradebook_resolver(profile.group_name, profile.program_code)
        matches = _select_preferred_gradebook_matches(resolved.get("matches", []))
        if not matches:
            raise ValueError(
                f"Не удалось найти ведомости для группы {profile.group_name} в программе {profile.program_code}."
            )
        return [
            {
                "google_sheet_url": str(match.get("google_sheet_url") or ""),
                "subject_name": str(match.get("subject_name") or "") or None,
                "subject_page_title": str(match.get("subject_page_title") or "") or None,
                "subject_page_url": str(match.get("subject_page_url") or "") or None,
                "source": str(match.get("source") or "wiki"),
                "match_type": str(match.get("match_type") or "") or None,
            }
            for match in matches
        ]

    def save_discovered_sources(
        self,
        telegram_id: int,
        matches: list[dict[str, str | None]],
    ) -> list[StoredSource]:
        if not matches:
            raise ValueError("Сначала выбери хотя бы одну ведомость.")
        stored_sources = []
        for match in matches:
            source_url = (match.get("google_sheet_url") or "").strip()
            if not source_url:
                continue
            stored_sources.append(
                self.sources.save_new(
                    telegram_id=telegram_id,
                    source_url=source_url,
                    source_type="google_sheet",
                    source_metadata={
                        "subject_page_title": match.get("subject_page_title"),
                        "subject_page_url": match.get("subject_page_url"),
                        "gradebook_reason": match.get("reason"),
                    },
                    subject_name=match.get("subject_name"),
                    progress_message=f"Ведомость найдена через {match.get('source', 'wiki')}.",
                )
            )
        return stored_sources

    def sync_profile_sources(self, telegram_id: int) -> list[StoredSource]:
        return self.save_discovered_sources(
            telegram_id=telegram_id,
            matches=self.discover_profile_sources(telegram_id),
        )

    def sync_and_analyze_profile(self, telegram_id: int) -> list[StoredSource]:
        sources = self.sync_profile_sources(telegram_id)
        analyzed_sources = []
        for source in sources:
            analyzed_sources.append(self.run_analysis(telegram_id, source.id))
        return analyzed_sources

    def list_sources(self, telegram_id: int) -> list[StoredSource]:
        return self.sources.list_for_user(telegram_id)

    def get_source(self, telegram_id: int, source_id: int) -> StoredSource | None:
        return self.sources.get(telegram_id, source_id)

    def run_analysis(self, telegram_id: int, source_id: int) -> StoredSource:
        profile = self.get_profile(telegram_id)
        if profile is None:
            raise ValueError("Сначала нужно заполнить профиль через /start.")
        source = self.get_source(telegram_id, source_id)
        if source is None:
            raise ValueError("Источник не найден.")
        source.status = "running"
        source.progress_message = "Извлекаю структуру и считаю результат."
        source.last_error = None
        source.clarification = None
        source = self.sources.update(source)
        try:
            result = self.analysis_runner(
                source.source_url,
                profile.full_name,
                _build_analysis_group_hint(profile.group_name),
            )
        except Exception as exc:
            source.status = "failed"
            source.progress_message = "Анализ завершился ошибкой."
            source.last_error = _format_analysis_error(exc)
            return self.sources.update(source)
        auto_formula_applied = False
        if source.manual_formula is None:
            auto_formula = _build_wiki_formula_override(source, result)
            if auto_formula is not None:
                source.manual_formula = auto_formula
                result = _apply_manual_formula_override(result, auto_formula)
                auto_formula_applied = True
        if source.manual_formula is not None and not auto_formula_applied:
            result = _apply_manual_formula_override(result, source.manual_formula)
        source.analysis_result = asdict(result)
        source.subject_name = _extract_subject_name(result)
        source.overall_confidence = _extract_overall_confidence(result)
        clarification = _build_clarification(result)
        if clarification is not None:
            source.status = "needs_clarification"
            source.progress_message = "Нужно подтверждение по спорным данным."
            source.clarification = clarification
        else:
            source.status = "completed"
            source.progress_message = "Анализ завершен."
        return self.sources.update(source)

    def apply_manual_formula_text(self, telegram_id: int, source_id: int, formula_text: str) -> StoredSource:
        return self._apply_manual_formula(
            telegram_id=telegram_id,
            source_id=source_id,
            source_type="text",
            parse=lambda result: self.formula_parser.parse_formula_text(formula_text),
        )

    def apply_manual_formula_image(
        self,
        telegram_id: int,
        source_id: int,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> StoredSource:
        return self._apply_manual_formula(
            telegram_id=telegram_id,
            source_id=source_id,
            source_type="image",
            parse=lambda result: self.formula_parser.parse_formula_image(image_bytes, mime_type=mime_type),
        )

    def resolve_clarification(self, telegram_id: int, source_id: int, action: str) -> StoredSource:
        source = self.get_source(telegram_id, source_id)
        if source is None:
            raise ValueError("Источник не найден.")
        if source.clarification is None:
            raise ValueError("Для этого источника нет активного уточнения.")
        source.clarification.response = action
        source.status = "completed"
        source.progress_message = "Уточнение сохранено. Анализ помечен завершенным."
        if action == "reject":
            source.last_error = "Пользователь не подтвердил спорную гипотезу. Нужна доработка flow ручного исправления."
        return self.sources.update(source)

    def completed_sources(self, telegram_id: int) -> list[StoredSource]:
        return [source for source in self.list_sources(telegram_id) if source.status == "completed" and source.normalized]

    def _apply_manual_formula(
        self,
        telegram_id: int,
        source_id: int,
        source_type: str,
        parse: Callable[[AnalysisResult], FormulaParseResult],
    ) -> StoredSource:
        profile = self.get_profile(telegram_id)
        if profile is None:
            raise ValueError("Сначала нужно заполнить профиль через /start.")
        source = self.get_source(telegram_id, source_id)
        if source is None:
            raise ValueError("Источник не найден.")

        base_result = self.analysis_runner(
            source.source_url,
            profile.full_name,
            _build_analysis_group_hint(profile.group_name),
        )
        parsed_formula = parse(base_result)
        manual_formula = ManualFormulaOverride(
            formula_text=parsed_formula.formula_text,
            weights=_build_component_weight_override(base_result, parsed_formula),
            parser_confidence=parsed_formula.confidence,
            source_type=source_type,
            reason=parsed_formula.reason,
        )
        if not manual_formula.weights:
            raise ValueError("Не удалось сопоставить формулу с компонентами этой ведомости.")
        source.manual_formula = manual_formula
        adjusted_result = _apply_manual_formula_override(base_result, manual_formula)
        source.analysis_result = asdict(adjusted_result)
        source.subject_name = _extract_subject_name(adjusted_result)
        source.overall_confidence = _extract_overall_confidence(adjusted_result)
        source.status = "completed"
        source.progress_message = "Формула оценивания загружена вручную и применена."
        source.last_error = None
        source.clarification = None
        return self.sources.update(source)

    @staticmethod
    def _build_default_runner(
        llm_model: str,
        enable_llm_student_match: bool,
        enable_llm_structure: bool,
    ) -> Callable[[str, str, str | None], AnalysisResult]:
        student_matcher = OpenAIStudentMatcher(model=llm_model) if enable_llm_student_match else None
        structure_analyzer = OpenAIWorksheetStructureAnalyzer(model=llm_model) if enable_llm_structure else None
        pipeline = AnalysisPipeline(
            student_matcher=student_matcher,
            structure_analyzer=structure_analyzer,
        )

        def run(source: str, full_name: str, group_name: str | None) -> AnalysisResult:
            return pipeline.analyze(source=source, full_name=full_name, group=group_name)

        return run

    @staticmethod
    def _build_default_gradebook_resolver(
        enable_gradebook_gpt: bool,
    ) -> Callable[[str, str | None], dict]:
        def resolve(group_name: str, program_code: str | None) -> dict:
            return find_group_gradebooks(
                group_name=group_name,
                program_code=program_code,
                use_gpt=enable_gradebook_gpt,
            )

        return resolve


def _is_google_sheet_url(source_url: str) -> bool:
    parsed = urlparse(source_url)
    return parsed.scheme in {"http", "https"} and parsed.netloc == "docs.google.com" and "/spreadsheets/" in parsed.path


def _extract_subject_name(result: AnalysisResult) -> str | None:
    subjects = result.normalized.subjects
    return subjects[0].name if subjects else result.source.title


def _extract_overall_confidence(result: AnalysisResult) -> float | None:
    if not result.worksheets:
        return None
    confidences = [worksheet.extraction.overall_confidence for worksheet in result.worksheets]
    return round(sum(confidences) / len(confidences), 2)


def _build_clarification(result: AnalysisResult) -> ClarificationRequest | None:
    if not result.worksheets:
        return None
    extraction = result.worksheets[0].extraction
    if extraction.matched_student.confidence < 0.75 and extraction.matched_student.value:
        return ClarificationRequest(
            kind="student_match",
            prompt="Я не до конца уверен, что нашел твою строку. Подтверди, пожалуйста.",
            hypothesis=extraction.matched_student.value,
            options=["Да, это я", "Нет"],
        )
    if extraction.grading_scheme.confidence < 0.75 and extraction.grading_scheme.formula_text:
        return ClarificationRequest(
            kind="grading_scheme",
            prompt="Я неуверенно распознал формулу оценивания.",
            hypothesis=extraction.grading_scheme.formula_text,
            options=["Подтвердить", "Пропустить"],
        )
    for deadline in extraction.deadlines:
        if deadline.confidence < 0.75:
            return ClarificationRequest(
                kind="deadline",
                prompt="Нашел возможный дедлайн, но не уверен в дате.",
                hypothesis=f"{deadline.name}: {deadline.date_text}",
                options=["Подтвердить", "Пропустить"],
            )
    return None


def _deduplicate_gradebook_matches(matches: list[dict]) -> list[dict]:
    best_by_url: dict[str, dict] = {}
    for match in matches:
        url = match.get("google_sheet_url")
        if not url:
            continue
        current = best_by_url.get(url)
        if current is None or _gradebook_match_rank(match) < _gradebook_match_rank(current):
            best_by_url[url] = match
    return list(best_by_url.values())


def _select_preferred_gradebook_matches(matches: list[dict]) -> list[dict]:
    unique_matches = _deduplicate_gradebook_matches(matches)
    exact_matches = [match for match in unique_matches if match.get("match_type") == "group_specific"]
    preferred_pool = exact_matches if exact_matches else unique_matches
    return _select_one_match_per_subject(preferred_pool)


def _gradebook_match_rank(match: dict) -> tuple[int, str]:
    match_type = match.get("match_type")
    return (
        0 if match_type == "group_specific" else 1,
        str(match.get("subject_name", "")),
    )


def _select_one_match_per_subject(matches: list[dict]) -> list[dict]:
    best_by_subject: dict[str, dict] = {}
    for match in matches:
        subject_key = str(
            match.get("subject_page_title")
            or match.get("subject_name")
            or match.get("google_sheet_url")
            or ""
        )
        current = best_by_subject.get(subject_key)
        if current is None or _gradebook_match_rank(match) < _gradebook_match_rank(current):
            best_by_subject[subject_key] = match
    return sorted(best_by_subject.values(), key=_gradebook_match_rank)


def _build_analysis_group_hint(group_name: str | None) -> str | None:
    if not group_name:
        return None
    if re.search(r"\b\d{3}-\d\b", group_name):
        return None
    return group_name


def _format_analysis_error(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        request_url = exc.geturl()
        if "docs.google.com/spreadsheets" in request_url or "sheets.googleusercontent.com" in request_url:
            if exc.code in {400, 403}:
                return (
                    "Не удалось выгрузить Google Sheets. Проверь, что таблица открыта по ссылке "
                    "для чтения и разрешено скачивание."
                )
            if exc.code == 404:
                return "Не удалось найти Google Sheets по этой ссылке. Проверь адрес таблицы."
        return f"Не удалось загрузить источник: HTTP {exc.code}."
    if isinstance(exc, URLError):
        return "Не удалось подключиться к источнику. Проверь ссылку и доступ к сети."
    return str(exc)


def _apply_manual_formula_override(result: AnalysisResult, manual_formula: ManualFormulaOverride) -> AnalysisResult:
    for worksheet in result.worksheets:
        extraction = worksheet.extraction
        override_weights = manual_formula.weights
        updated_components = []
        for component in extraction.grading_scheme.components:
            updated_components.append(
                type(component)(
                    name=component.name,
                    weight=override_weights.get(component.name, 0.0),
                    max_score=component.max_score,
                )
            )
        extraction.grading_scheme.components = updated_components
        extraction.grading_scheme.formula_text = manual_formula.formula_text
        extraction.grading_scheme.confidence = max(extraction.grading_scheme.confidence, manual_formula.parser_confidence)
        extraction.warnings = [
            warning
            for warning in extraction.warnings
            if "weight" not in warning.lower() and "formula" not in warning.lower()
        ]
        extraction.warnings.append("Manual grading formula override was applied.")
    result.normalized = _rebuild_normalized_analysis(result)
    return result


def _build_wiki_formula_override(source: StoredSource, result: AnalysisResult) -> ManualFormulaOverride | None:
    if not _result_has_missing_weights(result):
        return None
    subject_page_title = source.source_metadata.get("subject_page_title") if source.source_metadata else None
    subject_page_url = source.source_metadata.get("subject_page_url") if source.source_metadata else None
    parsed_formula = extract_formula_from_wiki_page(
        subject_page_title=str(subject_page_title) if subject_page_title else None,
        subject_page_url=str(subject_page_url) if subject_page_url else None,
    )
    if parsed_formula is None:
        return None
    weights = _build_component_weight_override(result, parsed_formula)
    if not weights:
        return None
    return ManualFormulaOverride(
        formula_text=parsed_formula.formula_text,
        weights=weights,
        parser_confidence=parsed_formula.confidence,
        source_type="wiki",
        reason=parsed_formula.reason,
    )


def _result_has_missing_weights(result: AnalysisResult) -> bool:
    for worksheet in result.worksheets:
        if any(component.weight is None for component in worksheet.extraction.grading_scheme.components):
            return True
    return False


def _rebuild_normalized_analysis(result: AnalysisResult) -> NormalizedAnalysis:
    normalized_subjects = []
    normalized_deadlines = []
    recommendations = []
    warnings: list[str] = []
    student_query = result.worksheets[0].extraction.student_query if result.worksheets else None
    for worksheet in result.worksheets:
        validation = worksheet.validation
        extraction = worksheet.extraction
        if not validation.is_valid:
            warnings.extend(issue.message for issue in validation.issues if issue.level == "error")
            continue
        subject, deadlines, subject_recommendations, subject_warnings = normalize_subject(
            extraction=extraction,
            student_query=extraction.student_query,
            subject_name_override=result.source.title,
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
        source_title=result.source.title,
    )
    return NormalizedAnalysis(
        student={
            "full_name": student_query.full_name if student_query else "",
            "group": student_query.group if student_query else None,
        },
        subjects=aggregated_subjects,
        deadlines=normalized_deadlines,
        recommendations=recommendations,
        global_summary=GlobalSummary(
            average_score=summary.average_score,
            high_risk_subjects=summary.high_risk_subjects,
            missing_data_sources=max(0, len(result.source.worksheets) - len(normalized_subjects)),
        ),
        warnings=warnings,
    )


def _build_component_weight_override(result: AnalysisResult, parsed_formula: FormulaParseResult) -> dict[str, float]:
    component_names = _collect_component_names(result)
    if not component_names:
        return {}
    weights_by_name = {name: 0.0 for name in component_names}
    normalized_terms = _normalize_formula_terms(parsed_formula)
    matched_any = False
    for formula_name, formula_weight in normalized_terms:
        matched_names = _match_formula_to_components(formula_name, component_names)
        if not matched_names:
            continue
        matched_any = True
        split_weight = formula_weight / len(matched_names)
        for component_name in matched_names:
            weights_by_name[component_name] += split_weight
    if not matched_any:
        return {}
    return _renormalize_weight_override(weights_by_name)


def _collect_component_names(result: AnalysisResult) -> list[str]:
    names: list[str] = []
    seen = set()
    for worksheet in result.worksheets:
        for component in worksheet.extraction.grading_scheme.components:
            if component.name in seen:
                continue
            seen.add(component.name)
            names.append(component.name)
    return names


def _normalize_formula_terms(parsed_formula: FormulaParseResult) -> list[tuple[str, float]]:
    positive_terms = [(item.name, max(0.0, item.weight)) for item in parsed_formula.components if item.weight > 0]
    total = sum(weight for _, weight in positive_terms)
    if total <= 0:
        return []
    return [(name, weight / total) for name, weight in positive_terms]


def _match_formula_to_components(formula_name: str, component_names: list[str]) -> list[str]:
    formula_key = _normalize_component_key(formula_name)
    if not formula_key:
        return []

    exact_matches = [name for name in component_names if _normalize_component_key(name) == formula_key]
    if exact_matches:
        return exact_matches

    contains_matches = [
        name
        for name in component_names
        if formula_key in _normalize_component_key(name) or _normalize_component_key(name) in formula_key
    ]
    if contains_matches:
        return contains_matches

    formula_base = _component_base_key(formula_name)
    base_matches = [name for name in component_names if _component_base_key(name) == formula_base]
    if base_matches:
        return base_matches

    scored_matches = sorted(
        (
            (_sequence_score(formula_key, _normalize_component_key(name)), name)
            for name in component_names
        ),
        reverse=True,
    )
    if scored_matches and scored_matches[0][0] >= 0.6:
        return [scored_matches[0][1]]
    return []


def _normalize_component_key(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Zа-яА-Я0-9]+", " ", value.lower()).strip()
    tokens = []
    for token in normalized.split():
        if token in {"h", "hw", "homework"}:
            tokens.append("hw")
        else:
            tokens.append(token)
    return " ".join(tokens)


def _component_base_key(value: str) -> str:
    normalized = _normalize_component_key(value)
    parts = normalized.split()
    alpha_parts = [part for part in parts if not part.isdigit()]
    return " ".join(alpha_parts[:2]) if alpha_parts else normalized


def _sequence_score(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    left_set = set(left.split())
    right_set = set(right.split())
    if left_set and left_set == right_set:
        return 1.0
    overlap = len(left_set & right_set) / max(len(left_set | right_set), 1)
    return max(overlap, 0.0)


def _renormalize_weight_override(weights_by_name: dict[str, float]) -> dict[str, float]:
    total = sum(max(weight, 0.0) for weight in weights_by_name.values())
    if total <= 0:
        return {}
    return {
        name: round(max(weight, 0.0) / total, 6)
        for name, weight in weights_by_name.items()
    }
