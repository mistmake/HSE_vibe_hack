from __future__ import annotations

import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from app.bot.formatters import format_summary, format_subject_details
from app.bot.services.local_service import LocalStudyBotService
from app.bot.services.local_storage import ProfileRepository, SQLiteStorage, SourceRepository
from study_analysis.schemas import (
    AnalysisResult,
    ExtractionResult,
    GlobalSummary,
    GradingComponent,
    GradingScheme,
    MatchCandidate,
    NormalizedAnalysis,
    NormalizedComponent,
    NormalizedSubject,
    Recommendation,
    SourceDocument,
    StudentQuery,
    StudentScore,
    SubjectGuess,
    ValidationReport,
    WorksheetAnalysis,
    WorksheetSnapshot,
)


class StubFormulaParser:
    def parse_formula_text(self, formula_text: str):
        from study_analysis.llm import FormulaParseResult, FormulaWeightItem

        return FormulaParseResult(
            formula_text=formula_text,
            components=[
                FormulaWeightItem(name="ДЗ", weight=0.3),
                FormulaWeightItem(name="Экзамен", weight=0.7),
            ],
            confidence=0.95,
            reason="stub",
        )

    def parse_formula_image(self, image_bytes: bytes, mime_type: str = "image/jpeg"):
        return self.parse_formula_text("ДЗ 30%, Экзамен 70%")


def build_fake_result(
    *,
    matched_confidence: float = 0.95,
    grading_confidence: float = 0.9,
) -> AnalysisResult:
    extraction = ExtractionResult(
        source_type="google_sheet",
        source_url="https://docs.google.com/spreadsheets/d/demo/edit#gid=0",
        sheet_name="Algorithms",
        student_query=StudentQuery(full_name="Иванов Иван Иванович", group="БПМИ231"),
        matched_student=MatchCandidate(value="Иванов И.И.", confidence=matched_confidence),
        subject=SubjectGuess(name="Алгоритмы", confidence=0.9),
        grading_scheme=GradingScheme(
            formula_text="0.4*ДЗ + 0.6*Экзамен",
            components=[
                GradingComponent(name="ДЗ", weight=0.4, max_score=10.0),
                GradingComponent(name="Экзамен", weight=0.6, max_score=10.0),
            ],
            confidence=grading_confidence,
        ),
        student_scores=[
            StudentScore(component="ДЗ", score=8.0, max_score=10.0, comment="ok", confidence=0.95),
        ],
        deadlines=[],
        warnings=[],
        overall_confidence=min(matched_confidence, grading_confidence),
    )
    normalized = NormalizedAnalysis(
        student={"full_name": "Иванов Иван Иванович", "group": "БПМИ231"},
        subjects=[
            NormalizedSubject(
                name="Алгоритмы",
                source_url=extraction.source_url,
                components=[
                    NormalizedComponent(name="ДЗ", weight=0.4, score=8.0, max_score=10.0, status="complete"),
                    NormalizedComponent(name="Экзамен", weight=0.6, score=None, max_score=10.0, status="pending"),
                ],
                current_weighted_score=3.2,
                predicted_score=8.0,
                risk_level="medium",
                confidence=extraction.overall_confidence,
            )
        ],
        deadlines=[],
        recommendations=[
            Recommendation(
                subject="Алгоритмы",
                reason="Pending exam",
                action="Сначала подготовь экзамен.",
                urgency="high",
            )
        ],
        global_summary=GlobalSummary(average_score=8.0, high_risk_subjects=0, missing_data_sources=0),
        warnings=[],
    )
    return AnalysisResult(
        source=SourceDocument(
            source_url=extraction.source_url,
            source_type="google_sheet",
            worksheets=[WorksheetSnapshot(title="Algorithms", gid="0", rows=[])],
            title="Алгоритмы",
            spreadsheet_id="demo",
        ),
        worksheets=[
            WorksheetAnalysis(
                prepared=None,  # type: ignore[arg-type]
                extraction=extraction,
                validation=ValidationReport(is_valid=True, issues=[]),
            )
        ],
        normalized=normalized,
    )


class LocalStudyBotServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        storage = SQLiteStorage(Path(self.temp_dir.name) / "bot.sqlite3")
        self.service = LocalStudyBotService(
            profiles=ProfileRepository(storage),
            sources=SourceRepository(storage),
            analysis_runner=lambda source, full_name, group_name: build_fake_result(),
            gradebook_resolver=lambda group_name, program_code: {
                "matches": [
                    {
                        "subject_name": "Алгоритмы",
                        "google_sheet_url": "https://docs.google.com/spreadsheets/d/demo/edit#gid=0",
                        "subject_page_title": "Algorithms 2026",
                        "subject_page_url": "http://wiki.cs.hse.ru/Algorithms_2026",
                        "match_type": "group_specific",
                        "source": "wiki_regex",
                    }
                ]
            },
            formula_parser=StubFormulaParser(),
            enable_llm_structure=False,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_register_profile_and_add_source(self) -> None:
        profile = self.service.register_profile(1, "Иванов Иван Иванович", "БПМИ231", "PMI")
        source = self.service.add_source(1, "https://docs.google.com/spreadsheets/d/demo/edit#gid=0")

        self.assertEqual(profile.full_name, "Иванов Иван Иванович")
        self.assertEqual(profile.program_code, "PMI")
        self.assertEqual(source.status, "created")

    def test_run_analysis_stores_completed_result(self) -> None:
        self.service.register_profile(1, "Иванов Иван Иванович", "БПМИ231", "PMI")
        source = self.service.add_source(1, "https://docs.google.com/spreadsheets/d/demo/edit#gid=0")

        analyzed = self.service.run_analysis(1, source.id)

        self.assertEqual(analyzed.status, "completed")
        self.assertEqual(analyzed.subject_name, "Алгоритмы")
        self.assertIsNotNone(analyzed.analysis_result)

    def test_low_confidence_creates_clarification(self) -> None:
        storage = SQLiteStorage(Path(self.temp_dir.name) / "bot_low_conf.sqlite3")
        service = LocalStudyBotService(
            profiles=ProfileRepository(storage),
            sources=SourceRepository(storage),
            analysis_runner=lambda source, full_name, group_name: build_fake_result(matched_confidence=0.5),
            gradebook_resolver=lambda group_name, program_code: {"matches": []},
            enable_llm_structure=False,
        )
        service.register_profile(2, "Иванов Иван Иванович", "БПМИ231", "PMI")
        source = service.add_source(2, "https://docs.google.com/spreadsheets/d/demo/edit#gid=0")

        analyzed = service.run_analysis(2, source.id)

        self.assertEqual(analyzed.status, "needs_clarification")
        self.assertEqual(analyzed.clarification.kind, "student_match")  # type: ignore[union-attr]

    def test_formatters_render_source_result(self) -> None:
        self.service.register_profile(1, "Иванов Иван Иванович", "БПМИ231", "PMI")
        source = self.service.add_source(1, "https://docs.google.com/spreadsheets/d/demo/edit#gid=0")
        analyzed = self.service.run_analysis(1, source.id)

        summary = format_summary([analyzed])
        details = format_subject_details(analyzed)

        self.assertIn("Сводка по учебе", summary)
        self.assertIn("Алгоритмы", details)
        self.assertIn("Компоненты", details)

    def test_sync_profile_sources_uses_gradebook_resolver(self) -> None:
        self.service.register_profile(1, "Иванов Иван Иванович", "257-1", "PAD")

        sources = self.service.sync_profile_sources(1)

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].subject_name, "Алгоритмы")
        self.assertEqual(sources[0].status, "created")

    def test_sync_and_analyze_profile_runs_analysis_for_resolved_sources(self) -> None:
        self.service.register_profile(1, "Иванов Иван Иванович", "257-1", "PAD")

        analyzed_sources = self.service.sync_and_analyze_profile(1)

        self.assertEqual(len(analyzed_sources), 1)
        self.assertEqual(analyzed_sources[0].status, "completed")
        self.assertIsNotNone(analyzed_sources[0].analysis_result)

    def test_discover_profile_sources_returns_candidates_without_saving(self) -> None:
        self.service.register_profile(1, "Иванов Иван Иванович", "257-1", "PAD")

        matches = self.service.discover_profile_sources(1)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["subject_name"], "Алгоритмы")
        self.assertEqual(matches[0]["subject_page_title"], "Algorithms 2026")
        self.assertEqual(self.service.list_sources(1), [])

    def test_save_discovered_sources_saves_only_selected_candidates(self) -> None:
        self.service.register_profile(1, "Иванов Иван Иванович", "257-1", "PAD")

        stored = self.service.save_discovered_sources(
            1,
            [
                {
                    "subject_name": "Алгоритмы",
                    "google_sheet_url": "https://docs.google.com/spreadsheets/d/demo/edit#gid=0",
                    "subject_page_title": "Algorithms 2026",
                    "subject_page_url": "http://wiki.cs.hse.ru/Algorithms_2026",
                    "source": "wiki_regex",
                }
            ],
        )

        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].subject_name, "Алгоритмы")
        self.assertEqual(stored[0].source_metadata["subject_page_title"], "Algorithms 2026")
        self.assertEqual(len(self.service.list_sources(1)), 1)

    def test_apply_manual_formula_text_updates_weights(self) -> None:
        self.service.register_profile(1, "Иванов Иван Иванович", "БПМИ231", "PMI")
        source = self.service.add_source(1, "https://docs.google.com/spreadsheets/d/demo/edit#gid=0")

        updated = self.service.apply_manual_formula_text(1, source.id, "0.3*ДЗ + 0.7*Экзамен")

        self.assertIsNotNone(updated.manual_formula)
        components = updated.normalized["subjects"][0]["components"]  # type: ignore[index]
        weights = {component["name"]: component["weight"] for component in components}
        self.assertEqual(weights["ДЗ"], 0.3)
        self.assertEqual(weights["Экзамен"], 0.7)

    def test_run_analysis_formats_google_http_errors_for_user(self) -> None:
        storage = SQLiteStorage(Path(self.temp_dir.name) / "bot_http_error.sqlite3")

        def failing_runner(source, full_name, group_name):
            raise HTTPError(
                url="https://docs.google.com/spreadsheets/d/demo/export?format=csv&gid=0",
                code=400,
                msg="Bad Request",
                hdrs=None,
                fp=None,
            )

        service = LocalStudyBotService(
            profiles=ProfileRepository(storage),
            sources=SourceRepository(storage),
            analysis_runner=failing_runner,
            gradebook_resolver=lambda group_name, program_code: {"matches": []},
            enable_llm_structure=False,
        )
        service.register_profile(3, "Иванов Иван Иванович", "БПМИ231", "PMI")
        source = service.add_source(3, "https://docs.google.com/spreadsheets/d/demo/edit#gid=0")

        analyzed = service.run_analysis(3, source.id)

        self.assertEqual(analyzed.status, "failed")
        self.assertIn("Не удалось выгрузить Google Sheets", analyzed.last_error)

    @patch("app.bot.services.local_service.extract_formula_from_wiki_page")
    def test_run_analysis_applies_formula_from_wiki_when_weights_missing(self, extract_formula_from_wiki_page) -> None:
        from study_analysis.llm import FormulaParseResult, FormulaWeightItem

        storage = SQLiteStorage(Path(self.temp_dir.name) / "bot_wiki_formula.sqlite3")

        def build_missing_weight_result(source, full_name, group_name):
            extraction = ExtractionResult(
                source_type="google_sheet",
                source_url=source,
                sheet_name="LAaG",
                student_query=StudentQuery(full_name=full_name, group=group_name),
                matched_student=MatchCandidate(value=full_name, confidence=0.95),
                subject=SubjectGuess(name="LAaG", confidence=0.9),
                grading_scheme=GradingScheme(
                    formula_text=None,
                    components=[
                        GradingComponent(name="HW_1", weight=None, max_score=10.0),
                        GradingComponent(name="Q_1", weight=None, max_score=10.0),
                        GradingComponent(name="W_1", weight=None, max_score=10.0),
                        GradingComponent(name="O_1", weight=None, max_score=10.0),
                        GradingComponent(name="E_1", weight=None, max_score=10.0),
                        GradingComponent(name="I_1", weight=None, max_score=10.0),
                    ],
                    confidence=0.6,
                ),
                student_scores=[
                    StudentScore(component="HW_1", score=8.0, max_score=10.0, comment="ok", confidence=0.9),
                    StudentScore(component="Q_1", score=7.0, max_score=10.0, comment="ok", confidence=0.9),
                    StudentScore(component="W_1", score=6.0, max_score=10.0, comment="ok", confidence=0.9),
                    StudentScore(component="O_1", score=9.0, max_score=10.0, comment="ok", confidence=0.9),
                    StudentScore(component="E_1", score=5.0, max_score=10.0, comment="ok", confidence=0.9),
                    StudentScore(component="I_1", score=7.0, max_score=10.0, comment="ok", confidence=0.9),
                ],
                deadlines=[],
                warnings=["Weights were not found for some components and may need inference."],
                overall_confidence=0.8,
            )
            return AnalysisResult(
                source=SourceDocument(
                    source_url=source,
                    source_type="google_sheet",
                    worksheets=[WorksheetSnapshot(title="LAaG", gid="0", rows=[])],
                    title="LAaG",
                    spreadsheet_id="demo",
                ),
                worksheets=[
                    WorksheetAnalysis(
                        prepared=None,  # type: ignore[arg-type]
                        extraction=extraction,
                        validation=ValidationReport(is_valid=True, issues=[]),
                    )
                ],
                normalized=NormalizedAnalysis(
                    student={"full_name": full_name, "group": group_name},
                    subjects=[],
                    deadlines=[],
                    recommendations=[],
                    global_summary=GlobalSummary(average_score=0.0, high_risk_subjects=0, missing_data_sources=0),
                    warnings=[],
                ),
            )

        extract_formula_from_wiki_page.return_value = FormulaParseResult(
            formula_text="F = 0.13125*HW_1 + 0.175*Q_1 + 0.175*W_1 + 0.21875*O_1 + 0.3*E_1",
            components=[
                FormulaWeightItem(name="H_1", weight=0.13125),
                FormulaWeightItem(name="Q_1", weight=0.175),
                FormulaWeightItem(name="W_1", weight=0.175),
                FormulaWeightItem(name="O_1", weight=0.21875),
                FormulaWeightItem(name="E_1", weight=0.3),
            ],
            confidence=0.9,
            reason="wiki",
        )

        service = LocalStudyBotService(
            profiles=ProfileRepository(storage),
            sources=SourceRepository(storage),
            analysis_runner=build_missing_weight_result,
            gradebook_resolver=lambda group_name, program_code: {"matches": []},
            formula_parser=StubFormulaParser(),
            enable_llm_structure=False,
        )
        service.register_profile(4, "Иванов Иван Иванович", "257-1", "PAD")
        source = service.sources.save_new(
            telegram_id=4,
            source_url="https://docs.google.com/spreadsheets/d/demo/edit#gid=0",
            source_type="google_sheet",
            source_metadata={
                "subject_page_title": "LAaG DSBA 2025/2026",
                "subject_page_url": "http://wiki.cs.hse.ru/LAaG_DSBA_2025/2026",
            },
            subject_name="Linear Algebra and Geometry (modules 1-4)",
        )

        analyzed = service.run_analysis(4, source.id)

        self.assertEqual(analyzed.manual_formula.source_type, "wiki")  # type: ignore[union-attr]
        components = analyzed.normalized["subjects"][0]["components"]  # type: ignore[index]
        weights = {component["name"]: component["weight"] for component in components}
        self.assertGreater(weights["HW_1"], 0.1)
        self.assertEqual(weights["I_1"], 0.0)
