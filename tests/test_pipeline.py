import unittest
import io
from pathlib import Path
from unittest.mock import patch
import zipfile

from study_analysis.fetchers import load_source
from study_analysis.llm import LLMStudentMatchSuggestion
from study_analysis.pipeline import AnalysisPipeline
from study_analysis.schemas import (
    SourceDocument,
    WorksheetColumnDefinition,
    WorksheetSnapshot,
    WorksheetStructureHint,
)


class FakeStudentMatcher:
    def __init__(self, row_index: int | None, matched_value: str | None, confidence: float = 0.9) -> None:
        self.row_index = row_index
        self.matched_value = matched_value
        self.confidence = confidence

    def match_student_row(self, prepared, student_query) -> LLMStudentMatchSuggestion | None:
        return LLMStudentMatchSuggestion(
            row_index=self.row_index,
            matched_value=self.matched_value,
            confidence=self.confidence,
            reason="Chosen from non-standard student alias column.",
        )


class FakeStructureAnalyzer:
    def analyze_structure(self, worksheet, student_query) -> WorksheetStructureHint | None:
        return WorksheetStructureHint(
            header_row_indices=[0, 1],
            data_start_row=2,
            subject_name="Algorithms",
            name_column_index=0,
            group_column_index=1,
            component_columns=[
                WorksheetColumnDefinition(index=2, label="HW 1", role="component", max_score=10.0, weight=0.4),
                WorksheetColumnDefinition(index=3, label="HW 2", role="component", max_score=10.0, weight=0.6),
            ],
            confidence=0.93,
            reason="Merged two header rows into meaningful homework components.",
        )


class FakeStructureAnalyzerWithoutComponents:
    def analyze_structure(self, worksheet, student_query) -> WorksheetStructureHint | None:
        return WorksheetStructureHint(
            header_row_indices=[0, 1],
            data_start_row=2,
            subject_name="Algorithms",
            name_column_index=0,
            group_column_index=1,
            component_columns=[],
            confidence=0.82,
            reason="Header rows identified, component labels should be merged from them.",
        )


class AnalysisPipelineTestCase(unittest.TestCase):
    @staticmethod
    def _build_xlsx_workbook() -> bytes:
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as workbook_zip:
            workbook_zip.writestr(
                "xl/workbook.xml",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Grade" sheetId="1" r:id="rId1"/>
    <sheet name="Data" sheetId="2" state="hidden" r:id="rId2"/>
  </sheets>
</workbook>""",
            )
            workbook_zip.writestr(
                "xl/_rels/workbook.xml.rels",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
</Relationships>""",
            )
            workbook_zip.writestr(
                "xl/sharedStrings.xml",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="4" uniqueCount="4">
  <si><t>Student</t></si>
  <si><t>Group</t></si>
  <si><t>Иванов И.И.</t></si>
  <si><t>БПМИ231</t></si>
</sst>""",
            )
            workbook_zip.writestr(
                "xl/worksheets/sheet1.xml",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="s"><v>0</v></c>
      <c r="B1" t="s"><v>1</v></c>
      <c r="C1" t="inlineStr"><is><t>HW 40% / 10</t></is></c>
    </row>
    <row r="2">
      <c r="A2" t="s"><v>2</v></c>
      <c r="B2" t="s"><v>3</v></c>
      <c r="C2"><v>8</v></c>
    </row>
  </sheetData>
</worksheet>""",
            )
            workbook_zip.writestr(
                "xl/worksheets/sheet2.xml",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>Hidden</t></is></c></row>
  </sheetData>
</worksheet>""",
            )
        return content.getvalue()

    def test_local_csv_pipeline_returns_normalized_subject(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "algorithms.csv"
        result = AnalysisPipeline().analyze(
            source=str(fixture),
            full_name="Иванов Иван Иванович",
            group="БПМИ231",
        )

        self.assertEqual(len(result.normalized.subjects), 1)
        subject = result.normalized.subjects[0]
        self.assertEqual(subject.name, "algorithms")
        self.assertAlmostEqual(subject.current_weighted_score, 3.8, places=1)
        self.assertAlmostEqual(subject.predicted_score, 6.2, places=1)
        self.assertEqual(subject.risk_level, "high")
        self.assertTrue(result.normalized.recommendations)

    def test_llm_fallback_recovers_student_from_nonstandard_column(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "nonstandard_student_column.csv"
        result = AnalysisPipeline(
            student_matcher=FakeStudentMatcher(row_index=0, matched_value="Иванов И.И.")
        ).analyze(
            source=str(fixture),
            full_name="Иванов Иван Иванович",
            group="БПМИ231",
        )

        self.assertEqual(len(result.normalized.subjects), 1)
        extraction = result.worksheets[0].extraction
        self.assertEqual(extraction.matched_student.method, "llm_fallback")
        self.assertEqual(extraction.matched_student.row_index, 0)
        self.assertGreaterEqual(extraction.matched_student.validator_confidence or 0.0, 0.45)

    def test_llm_fallback_is_rejected_when_validation_fails(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "nonstandard_student_column.csv"
        result = AnalysisPipeline(
            student_matcher=FakeStudentMatcher(row_index=1, matched_value="Петров П.П.", confidence=0.99)
        ).analyze(
            source=str(fixture),
            full_name="Иванов Иван Иванович",
            group="БПМИ231",
        )

        self.assertEqual(len(result.normalized.subjects), 0)
        self.assertTrue(
            any("deterministic validation rejected" in warning for warning in result.worksheets[0].extraction.warnings)
        )

    @patch("study_analysis.fetchers._read_text_from_url")
    def test_remote_csv_url_is_loaded(self, read_text_from_url) -> None:
        read_text_from_url.return_value = (
            "Student,Group,ДЗ 40% / 10\nИванов И.И.,БПМИ231,7\n",
            "text/csv",
        )

        source = load_source("https://example.com/grades.csv")

        self.assertEqual(source.source_type, "remote_file")
        self.assertEqual(source.worksheets[0].title, "grades")
        self.assertEqual(source.worksheets[0].rows[1][0], "Иванов И.И.")

    @patch("study_analysis.fetchers._read_text_from_url")
    def test_google_sheet_url_still_uses_google_fetcher(self, read_text_from_url) -> None:
        def fake_read(url: str):
            if url.endswith("/edit"):
                return (
                    '<title>Algorithms 2026 - Google Sheets</title>'
                    '"sheetId":0,"title":"Homeworks","index":0'
                    '"sheetId":11,"title":"Controls","index":1',
                    "text/html",
                )
            return (
                "Student,Group,ДЗ 40% / 10\nИванов И.И.,БПМИ231,7\n",
                "text/csv",
            )

        read_text_from_url.side_effect = fake_read

        source = load_source("https://docs.google.com/spreadsheets/d/demo/edit#gid=0")

        self.assertEqual(source.source_type, "google_sheet")
        self.assertEqual(source.title, "Algorithms 2026")
        self.assertEqual(len(source.worksheets), 2)
        self.assertEqual(source.worksheets[0].gid, "0")
        self.assertEqual(source.worksheets[1].title, "Controls")

    @patch("study_analysis.fetchers._read_bytes_from_url")
    @patch("study_analysis.fetchers._read_text_from_url")
    def test_google_sheet_falls_back_to_xlsx_when_sheet_entries_are_missing(
        self,
        read_text_from_url,
        read_bytes_from_url,
    ) -> None:
        def fake_read_text(url: str):
            if url.endswith("/edit"):
                return ('<title>English 2026 - Google Sheets</title><script>bootstrapData={}</script>', "text/html")
            raise AssertionError(f"Unexpected CSV export attempt for {url}")

        read_text_from_url.side_effect = fake_read_text
        read_bytes_from_url.return_value = (self._build_xlsx_workbook(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        source = load_source("https://docs.google.com/spreadsheets/d/demo/")

        self.assertEqual(source.title, "English 2026")
        self.assertEqual(len(source.worksheets), 1)
        self.assertEqual(source.worksheets[0].title, "Grade")
        self.assertEqual(source.worksheets[0].rows[1][0], "Иванов И.И.")

    @patch("study_analysis.pipeline.load_source")
    def test_pipeline_aggregates_multiple_worksheets_into_one_subject(self, mocked_load_source) -> None:
        mocked_load_source.return_value = SourceDocument(
            source_url="https://docs.google.com/spreadsheets/d/demo/edit#gid=0",
            source_type="google_sheet",
            title="Algorithms 2026",
            spreadsheet_id="demo",
            worksheets=[
                WorksheetSnapshot(
                    title="Homeworks",
                    gid="0",
                    rows=[
                        ["Student", "Group", "HW1 50% / 10", "HW2 50% / 10"],
                        ["Иванов И.И.", "БПМИ231", "8", "9"],
                    ],
                ),
                WorksheetSnapshot(
                    title="Controls",
                    gid="11",
                    rows=[
                        ["Student", "Group", "Control 100% / 10"],
                        ["Иванов И.И.", "БПМИ231", "6"],
                    ],
                ),
            ],
        )

        result = AnalysisPipeline().analyze(
            source="https://docs.google.com/spreadsheets/d/demo/edit#gid=0",
            full_name="Иванов Иван Иванович",
            group="БПМИ231",
        )

        self.assertEqual(len(result.normalized.subjects), 1)
        subject = result.normalized.subjects[0]
        self.assertEqual(subject.name, "Algorithms 2026")
        self.assertEqual(len(subject.components), 3)
        self.assertEqual({component.source_sheet for component in subject.components}, {"Homeworks", "Controls"})

    def test_structure_analyzer_rebuilds_complex_headers(self) -> None:
        fixture = SourceDocument(
            source_url="local",
            source_type="local_file",
            title="Algorithms 2026",
            worksheets=[
                WorksheetSnapshot(
                    title="Complex",
                    gid="local",
                    rows=[
                        ["Student", "Group", "Homeworks", "Homeworks"],
                        ["", "", "1", "2"],
                        ["Иванов И.И.", "БПМИ231", "7", "8"],
                    ],
                )
            ],
        )
        with patch("study_analysis.pipeline.load_source", return_value=fixture):
            result = AnalysisPipeline(structure_analyzer=FakeStructureAnalyzer()).analyze(
                source="local",
                full_name="Иванов Иван Иванович",
                group="БПМИ231",
            )

        self.assertEqual(len(result.normalized.subjects), 1)
        subject = result.normalized.subjects[0]
        self.assertEqual(subject.name, "Algorithms 2026")
        self.assertEqual([component.name for component in subject.components], ["HW 1", "HW 2"])
        self.assertAlmostEqual(subject.predicted_score, 7.6, places=1)
        self.assertTrue(any("refined via LLM analysis" in warning for warning in result.normalized.warnings))

    def test_structure_analyzer_can_fall_back_to_merged_header_labels(self) -> None:
        fixture = SourceDocument(
            source_url="local",
            source_type="local_file",
            title="Algorithms 2026",
            worksheets=[
                WorksheetSnapshot(
                    title="Complex",
                    gid="local",
                    rows=[
                        ["Student", "Group", "Homeworks", "Homeworks"],
                        ["", "", "1", "2"],
                        ["Иванов И.И.", "БПМИ231", "7", "8"],
                    ],
                )
            ],
        )
        with patch("study_analysis.pipeline.load_source", return_value=fixture):
            result = AnalysisPipeline(
                structure_analyzer=FakeStructureAnalyzerWithoutComponents()
            ).analyze(
                source="local",
                full_name="Иванов Иван Иванович",
                group="БПМИ231",
            )

        self.assertEqual(len(result.normalized.subjects), 1)
        subject = result.normalized.subjects[0]
        self.assertEqual(subject.name, "Algorithms 2026")
        self.assertEqual([component.name for component in subject.components], ["Homeworks 1", "Homeworks 2"])

    @patch("study_analysis.pipeline.load_source")
    def test_pipeline_merges_two_row_headers_without_llm(self, mocked_load_source) -> None:
        mocked_load_source.return_value = SourceDocument(
            source_url="local",
            source_type="local_file",
            title="Algorithms 2026",
            worksheets=[
                WorksheetSnapshot(
                    title="Complex",
                    gid="local",
                    rows=[
                        ["Student", "HW", "", "Exam", ""],
                        ["", "1", "2", "written", "oral"],
                        ["Иванов И.И.", "7", "8", "6", "9"],
                    ],
                )
            ],
        )

        result = AnalysisPipeline().analyze(
            source="local",
            full_name="Иванов Иван Иванович",
            group=None,
        )

        subject = result.normalized.subjects[0]
        self.assertEqual(
            [component.name for component in subject.components],
            ["HW 1", "HW 2", "Exam written", "Exam oral"],
        )

    @patch("study_analysis.pipeline.load_source")
    def test_pipeline_extracts_decimal_weights_from_headers(self, mocked_load_source) -> None:
        mocked_load_source.return_value = SourceDocument(
            source_url="local",
            source_type="local_file",
            title="Entrepreneurship",
            worksheets=[
                WorksheetSnapshot(
                    title="Gradebook",
                    gid="local",
                    rows=[
                        ["Student", "0.3 * Project", "0,2 * Cases", "0.4xExam"],
                        ["Иванов И.И.", "8", "7", "6"],
                    ],
                )
            ],
        )

        result = AnalysisPipeline().analyze(
            source="local",
            full_name="Иванов Иван Иванович",
            group=None,
        )

        components = result.worksheets[0].extraction.grading_scheme.components
        self.assertEqual([component.weight for component in components], [0.3, 0.2, 0.4])


if __name__ == "__main__":
    unittest.main()
