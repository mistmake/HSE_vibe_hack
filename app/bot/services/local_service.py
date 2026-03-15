from __future__ import annotations

from dataclasses import asdict
from typing import Callable
from urllib.parse import urlparse

from app.bot.domain import BotProfile, ClarificationRequest, StoredSource
from app.bot.services.local_storage import ProfileRepository, SourceRepository
from study_analysis import AnalysisPipeline, OpenAIStudentMatcher, OpenAIWorksheetStructureAnalyzer
from study_analysis.schemas import AnalysisResult


class LocalStudyBotService:
    def __init__(
        self,
        profiles: ProfileRepository,
        sources: SourceRepository,
        analysis_runner: Callable[[str, str, str | None], AnalysisResult] | None = None,
        llm_model: str = "gpt-5-mini",
        enable_llm_student_match: bool = False,
        enable_llm_structure: bool = True,
    ) -> None:
        self.profiles = profiles
        self.sources = sources
        self.analysis_runner = analysis_runner or self._build_default_runner(
            llm_model=llm_model,
            enable_llm_student_match=enable_llm_student_match,
            enable_llm_structure=enable_llm_structure,
        )

    def get_profile(self, telegram_id: int) -> BotProfile | None:
        return self.profiles.get(telegram_id)

    def register_profile(self, telegram_id: int, full_name: str, group_name: str) -> BotProfile:
        return self.profiles.upsert(telegram_id, full_name=full_name.strip(), group_name=group_name.strip())

    def add_source(self, telegram_id: int, source_url: str) -> StoredSource:
        source_url = source_url.strip()
        if not _is_google_sheet_url(source_url):
            raise ValueError("Сейчас в MVP бот принимает только публичные ссылки на Google Sheets.")
        return self.sources.save_new(
            telegram_id=telegram_id,
            source_url=source_url,
            source_type="google_sheet",
        )

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
            result = self.analysis_runner(source.source_url, profile.full_name, profile.group_name)
        except Exception as exc:
            source.status = "failed"
            source.progress_message = "Анализ завершился ошибкой."
            source.last_error = str(exc)
            return self.sources.update(source)
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
