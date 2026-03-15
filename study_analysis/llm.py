from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Protocol

from study_analysis.schemas import (
    PreparedWorksheet,
    StudentQuery,
    WorksheetColumnDefinition,
    WorksheetSnapshot,
    WorksheetStructureHint,
)


@dataclass
class LLMStudentMatchSuggestion:
    row_index: int | None
    matched_value: str | None
    confidence: float
    reason: str


class StudentRowMatcher(Protocol):
    def match_student_row(
        self,
        prepared: PreparedWorksheet,
        student_query: StudentQuery,
    ) -> LLMStudentMatchSuggestion | None:
        ...


class WorksheetStructureAnalyzer(Protocol):
    def analyze_structure(
        self,
        worksheet: WorksheetSnapshot,
        student_query: StudentQuery,
    ) -> WorksheetStructureHint | None:
        ...


class OpenAIStudentMatcher:
    def __init__(self, model: str | None = None) -> None:
        _load_dotenv_if_available()
        self.model = model or os.getenv("STUDY_ANALYSIS_LLM_MODEL", "gpt-5-mini")

    def match_student_row(
        self,
        prepared: PreparedWorksheet,
        student_query: StudentQuery,
    ) -> LLMStudentMatchSuggestion | None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "OpenAI matcher requires the 'openai' package to be installed."
            ) from exc

        client = OpenAI()
        response = client.responses.create(
            model=self.model,
            instructions=(
                "You help identify which worksheet row belongs to a student. "
                "Return JSON only. Choose a row only if there is meaningful evidence "
                "from name variants, initials, group, or row context. Otherwise return null row_index."
            ),
            input=_build_match_prompt(prepared, student_query),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "student_row_match",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "row_index": {"type": ["integer", "null"]},
                            "matched_value": {"type": ["string", "null"]},
                            "confidence": {"type": "number"},
                            "reason": {"type": "string"},
                        },
                        "required": ["row_index", "matched_value", "confidence", "reason"],
                        "additionalProperties": False,
                    },
                }
            },
        )
        payload = json.loads(response.output_text)
        return LLMStudentMatchSuggestion(
            row_index=payload["row_index"],
            matched_value=payload["matched_value"],
            confidence=float(payload["confidence"]),
            reason=payload["reason"],
        )


class OpenAIWorksheetStructureAnalyzer:
    def __init__(self, model: str | None = None) -> None:
        _load_dotenv_if_available()
        self.model = model or os.getenv("STUDY_ANALYSIS_LLM_MODEL", "gpt-5-mini")

    def analyze_structure(
        self,
        worksheet: WorksheetSnapshot,
        student_query: StudentQuery,
    ) -> WorksheetStructureHint | None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "OpenAI structure analyzer requires the 'openai' package to be installed."
            ) from exc

        client = OpenAI()
        response = client.responses.create(
            model=self.model,
            instructions=(
                "You help map the structure of complex grade spreadsheets. "
                "Return JSON only. Identify header rows, the start of student data, "
                "the student-name and group columns if present, and only the columns "
                "that are real assessment components. Ignore helper numbering columns "
                "and repeated nested numeric labels unless they are part of a meaningful component label."
            ),
            input=_build_structure_prompt(worksheet, student_query),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "worksheet_structure_hint",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "header_row_indices": {
                                "type": "array",
                                "items": {"type": "integer"},
                            },
                            "data_start_row": {"type": "integer"},
                            "subject_name": {"type": ["string", "null"]},
                            "name_column_index": {"type": ["integer", "null"]},
                            "group_column_index": {"type": ["integer", "null"]},
                            "component_columns": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "index": {"type": "integer"},
                                        "label": {"type": "string"},
                                        "role": {"type": "string"},
                                        "max_score": {"type": ["number", "null"]},
                                        "weight": {"type": ["number", "null"]},
                                        "confidence": {"type": ["number", "null"]},
                                    },
                                    "required": [
                                        "index",
                                        "label",
                                        "role",
                                        "max_score",
                                        "weight",
                                        "confidence",
                                    ],
                                    "additionalProperties": False,
                                },
                            },
                            "confidence": {"type": "number"},
                            "reason": {"type": "string"},
                        },
                        "required": [
                            "header_row_indices",
                            "data_start_row",
                            "subject_name",
                            "name_column_index",
                            "group_column_index",
                            "component_columns",
                            "confidence",
                            "reason",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
        )
        payload = json.loads(response.output_text)
        return WorksheetStructureHint(
            header_row_indices=payload["header_row_indices"],
            data_start_row=payload["data_start_row"],
            subject_name=payload["subject_name"],
            name_column_index=payload["name_column_index"],
            group_column_index=payload["group_column_index"],
            component_columns=[
                WorksheetColumnDefinition(
                    index=item["index"],
                    label=item["label"],
                    role=item["role"],
                    max_score=item["max_score"],
                    weight=item["weight"],
                    confidence=item["confidence"],
                )
                for item in payload["component_columns"]
            ],
            confidence=float(payload["confidence"]),
            reason=payload["reason"],
        )


def _build_match_prompt(prepared: PreparedWorksheet, student_query: StudentQuery) -> str:
    rows = []
    for index, row in enumerate(prepared.data_rows[:120]):
        rows.append({"row_index": index, "cells": row})
    return json.dumps(
        {
            "task": "Identify the most likely student row in the worksheet.",
            "student_query": {
                "full_name": student_query.full_name,
                "group": student_query.group,
            },
            "worksheet": {
                "title": prepared.title,
                "headers": prepared.headers,
                "rows": rows,
            },
            "rules": [
                "Consider initials, abbreviations, and different formatting of the same name.",
                "Use group as supporting evidence when available.",
                "Return row_index null if you are not reasonably confident.",
            ],
        },
        ensure_ascii=False,
    )


def _build_structure_prompt(worksheet: WorksheetSnapshot, student_query: StudentQuery) -> str:
    rows = []
    for index, row in enumerate(worksheet.rows[:30]):
        rows.append({"row_index": index, "cells": row[:80]})
    return json.dumps(
        {
            "task": "Identify worksheet structure for extracting one student's grades.",
            "student_query": {
                "full_name": student_query.full_name,
                "group": student_query.group,
            },
            "worksheet": {
                "title": worksheet.title,
                "rows": rows,
            },
            "rules": [
                "Header rows may span multiple lines and should be merged conceptually.",
                "Ignore simple numbering columns when they do not represent standalone assessment components.",
                "If a label is hierarchical, return the final meaningful merged component label.",
                "Only return columns that correspond to actual grade components.",
            ],
        },
        ensure_ascii=False,
    )


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()
