from __future__ import annotations

import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

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
                        "match_type": "group_specific",
                        "source": "wiki_regex",
                    }
                ]
            },
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
